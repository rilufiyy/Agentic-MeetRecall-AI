"""
Chat client for the agent: Groq chat completions with tools or with a strict
JSON schema, plus token usage and latency for tracing.

Separate from services/llm.py on purpose: that service returns text only and
falls back to a local 0.5B model, which the agent must not do silently. Here a
failed request raises, and the loop decides what to do.

Groq references:
  tool use           https://console.groq.com/docs/tool-use
  structured outputs https://console.groq.com/docs/structured-outputs
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent import config
from agent.tracing import Tracer


class LLMError(Exception):
    """The LLM request failed (network, rate limit, invalid tool call output)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str          # raw JSON string as produced by the model


@dataclass
class LLMResult:
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float = 0.0


def _attr(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class ChatClient:
    """
    `create` is the function that sends one request (defaults to the Groq SDK's
    chat.completions.create). Tests pass a scripted fake instead.
    """

    def __init__(self, model: str = config.AGENT_MODEL, create: Optional[Callable] = None) -> None:
        self.model = model
        self._create = create

    def _sdk_create(self) -> Callable:
        if self._create is None:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise LLMError("GROQ_API_KEY belum diset di environment.")
            from groq import Groq
            self._create = Groq(api_key=api_key).chat.completions.create
        return self._create

    def chat(
        self,
        messages: List[Dict],
        tracer: Tracer,
        purpose: str,
        iterasi: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        json_schema: Optional[Dict] = None,
        max_completion_tokens: int = config.AGENT_MAX_COMPLETION_TOKENS,
        reasoning_effort: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> LLMResult:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": config.AGENT_TEMPERATURE if temperature is None else temperature,
            "max_completion_tokens": max_completion_tokens,
        }
        if "gpt-oss" in self.model:
            kwargs["reasoning_effort"] = reasoning_effort or config.AGENT_REASONING_EFFORT
            kwargs["include_reasoning"] = False
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": json_schema}

        t0 = time.perf_counter()
        try:
            completion = self._sdk_create()(**kwargs)
        except LLMError:
            raise
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            tracer.log("llm_call", tujuan=purpose, model=self.model, iterasi=iterasi,
                       status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}",
                       input_tokens=None, output_tokens=None, biaya_usd=None,
                       latency_ms=round(latency, 1))
            raise LLMError(str(exc)) from exc
        latency = (time.perf_counter() - t0) * 1000

        choice = _attr(completion, "choices")[0]
        message = _attr(choice, "message")
        calls = [
            ToolCall(
                id=_attr(tc, "id"),
                name=_attr(_attr(tc, "function"), "name"),
                arguments=_attr(_attr(tc, "function"), "arguments") or "{}",
            )
            for tc in (_attr(message, "tool_calls") or [])
        ]
        usage = _attr(completion, "usage")
        in_tok = _attr(usage, "prompt_tokens") if usage is not None else None
        out_tok = _attr(usage, "completion_tokens") if usage is not None else None

        result = LLMResult(
            content=(_attr(message, "content") or "").strip(),
            tool_calls=calls,
            finish_reason=_attr(choice, "finish_reason"),
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=round(latency, 1),
        )
        tracer.log(
            "llm_call", tujuan=purpose, model=self.model, iterasi=iterasi, status="ok",
            reasoning_effort=kwargs.get("reasoning_effort"), temperature=kwargs["temperature"],
            input_tokens=in_tok, output_tokens=out_tok,
            biaya_usd=config.estimate_cost(self.model, in_tok, out_tok),
            latency_ms=result.latency_ms, finish_reason=result.finish_reason,
            tool_calls_diminta=[c.name for c in calls],
        )
        return result

    def chat_json(self, messages: List[Dict], schema_name: str, schema: Dict,
                  tracer: Tracer, purpose: str) -> Dict:
        """
        Strict structured output (no tools in the same request, see module docstring).
        Groq sometimes answers 400 json_validate_failed with an empty generation;
        that request is retried (twice at most).
        """
        for attempt in range(3):
            try:
                result = self.chat(
                    messages, tracer, purpose,
                    json_schema={"name": schema_name, "strict": True, "schema": schema},
                    reasoning_effort=config.EXTRACT_REASONING_EFFORT,
                    temperature=config.EXTRACT_TEMPERATURE,
                    max_completion_tokens=config.EXTRACT_MAX_COMPLETION_TOKENS,
                )
                break
            except LLMError as exc:
                if attempt == 2 or "json_validate_failed" not in str(exc):
                    raise
        try:
            return json.loads(result.content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Output JSON tidak valid: {exc}") from exc
