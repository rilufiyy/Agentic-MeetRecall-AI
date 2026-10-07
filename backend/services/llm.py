"""
Shared LLM service — supports both seq2seq (T5/BART) and causal (Qwen2, etc.) models.

Two backends:
  - Groq API (used when GROQ_API_KEY is set): hosted open-weight models such as
    openai/gpt-oss-20b (override via GROQ_LLM_MODEL). Fast, nothing loaded locally,
    which suits CPU-only machines.
  - Local HuggingFace model (fallback, or LLM_PROVIDER=local):
    Qwen/Qwen2-0.5B-Instruct by default (override via RAG_LLM_MODEL env var).
If a Groq call fails (rate limit, network), generation falls back to the local model.

Auto-detects model architecture at load time:
  - Causal (decoder-only) : Qwen2, LLaMA, Mistral, Phi, GPT-2, etc.
  - Seq2Seq (enc-decoder) : T5, BART, mT5, etc.
"""
from __future__ import annotations

import logging
import os

import torch

logger = logging.getLogger(__name__)

LLM_MODEL_ID: str = os.getenv("RAG_LLM_MODEL", "Qwen/Qwen2-0.5B-Instruct")
GROQ_LLM_MODEL: str = os.getenv("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto").lower()   # auto | groq | local


def _cuda_works() -> bool:
    if not torch.cuda.is_available():
        return False
    try:
        torch.zeros(1).cuda()
        return True
    except Exception as exc:
        logger.warning(f"CUDA sanity check failed ({exc}). LLM will run on CPU.")
        return False

_USE_CUDA = _cuda_works()
_MAX_INPUT_TOKENS: int = 1024

# model_type values that indicate a decoder-only causal LM
_CAUSAL_FAMILIES = {
    "llama", "qwen2", "mistral", "phi", "phi-msft", "gpt2", "gpt_neo",
    "gpt_neox", "bloom", "opt", "falcon", "stablelm", "internlm",
    "baichuan", "chatglm", "gemma", "gemma2",
}


class LLMService:
    """Singleton LLM for text generation — auto-detects seq2seq vs causal."""

    _tokenizer = None
    _model = None
    _is_causal: bool = False

    def _load(self) -> None:
        if LLMService._tokenizer is not None:
            return
        from transformers import (
            AutoConfig,
            AutoModelForCausalLM,
            AutoModelForSeq2SeqLM,
            AutoTokenizer,
        )

        logger.info(f"Loading LLM: {LLM_MODEL_ID}")
        config = AutoConfig.from_pretrained(LLM_MODEL_ID)
        model_type = config.model_type.lower()
        is_causal = model_type in _CAUSAL_FAMILIES

        dtype = torch.float16 if _USE_CUDA else torch.float32
        LLMService._tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_ID)

        if is_causal:
            LLMService._model = AutoModelForCausalLM.from_pretrained(
                LLM_MODEL_ID, torch_dtype=dtype,
            )
        else:
            LLMService._model = AutoModelForSeq2SeqLM.from_pretrained(
                LLM_MODEL_ID, torch_dtype=dtype,
            )

        if _USE_CUDA:
            LLMService._model = LLMService._model.cuda()
        LLMService._model.eval()
        LLMService._is_causal = is_causal
        logger.info(f"LLM ready: {LLM_MODEL_ID} (causal={is_causal})")

    _groq_client = None

    @staticmethod
    def use_groq() -> bool:
        if LLM_PROVIDER == "local":
            return False
        return bool(os.getenv("GROQ_API_KEY"))

    def backend_name(self) -> str:
        return f"groq:{GROQ_LLM_MODEL}" if self.use_groq() else f"local:{LLM_MODEL_ID}"

    def _generate_groq(self, prompt: str, max_new_tokens: int) -> str:
        if LLMService._groq_client is None:
            from groq import Groq
            LLMService._groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        kwargs = {}
        if "gpt-oss" in GROQ_LLM_MODEL:
            # Reasoning models: keep reasoning short and out of the answer text.
            kwargs = {"reasoning_effort": "low", "include_reasoning": False}
        completion = LLMService._groq_client.chat.completions.create(
            model=GROQ_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            # Generous ceiling: reasoning tokens may share this budget.
            max_completion_tokens=max(1024, max_new_tokens * 4),
            **kwargs,
        )
        return (completion.choices[0].message.content or "").strip()

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 200,
        num_beams: int = 1,
    ) -> str:
        """Run generation and return decoded string."""
        if self.use_groq():
            try:
                text = self._generate_groq(prompt, max_new_tokens)
                if text:
                    return text
                logger.warning("Groq returned an empty answer, using local LLM.")
            except Exception as exc:
                logger.warning(f"Groq generation failed ({exc}), using local LLM.")
        return self._generate_local(prompt, max_new_tokens, num_beams)

    def _generate_local(
        self,
        prompt: str,
        max_new_tokens: int = 200,
        num_beams: int = 1,
    ) -> str:
        self._load()
        tok = LLMService._tokenizer
        model = LLMService._model

        if LLMService._is_causal:
            # Build chat-formatted input using the model's own chat template
            if tok.chat_template:
                messages = [{"role": "user", "content": prompt}]
                input_text = tok.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                input_text = prompt

            inputs = tok(
                input_text,
                return_tensors="pt",
                truncation=True,
                max_length=_MAX_INPUT_TOKENS,
            )
            if _USE_CUDA:
                inputs = {k: v.cuda() for k, v in inputs.items()}

            input_len = inputs["input_ids"].shape[1]
            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=tok.eos_token_id,
                )
            # Decode only the newly generated tokens (skip the echoed prompt)
            new_ids = output_ids[0][input_len:]
            return tok.decode(new_ids, skip_special_tokens=True).strip()

        else:
            # Seq2seq path (T5, BART, etc.)
            inputs = tok(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=_MAX_INPUT_TOKENS,
            )
            if _USE_CUDA:
                inputs = {k: v.cuda() for k, v in inputs.items()}

            with torch.no_grad():
                output_ids = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    num_beams=num_beams,
                    early_stopping=True,
                )
            return tok.decode(output_ids[0], skip_special_tokens=True).strip()


llm_service = LLMService()