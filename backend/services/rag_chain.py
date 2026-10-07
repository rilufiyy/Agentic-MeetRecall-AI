"""
RAG (Retrieval-Augmented Generation) chain — meeting intelligence edition.

Pipeline:
  0. Small talk (greetings, thanks) gets a fixed reply without retrieval or
     LLM call (services/small_talk.py).
  0b. Follow-up questions ("Which league does he play in?") are rewritten
     into a standalone question by the LLM before retrieval, because the raw
     follow-up has too few words in common with the transcript. Falls back
     to the original question when rewriting fails.
  1. Retrieve top-k (default 3) chunks with the selected retrieval mode
     (vector / fulltext / hybrid, see services/retrieval.py).
  2. If retrieval abstains (nothing close enough), answer "not found"
     without calling the LLM.
  3. Build a compact context string (neighbour chunks included when
     expand_neighbors > 0). Meeting-wide questions (summary, decisions,
     action items) get the whole transcript instead when it fits in
     FULL_TRANSCRIPT_MAX_CHARS, because top-k chunks cover only part of a
     meeting; retrieved chunks are still returned as citations.
  4. Generate a concise, factual answer via the shared LLMService.
  5. Post-process: extract key_actions and keywords from retrieved context.
  6. Return RAGChatResponse (pure JSON, no HTML).

Performance targets (Section F):
  top_k         = 3 default
  context_chars ≤ 1200
  max_new_tokens = 150
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List

from models.schemas import RAGChatResponse, SourceChunk
from services.llm import llm_service
from services.retrieval import RetrievalConfig, format_chunk, retrieval_service
from services.small_talk import small_talk_reply
from services.storage import storage_service

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS: int = 2400
FULL_TRANSCRIPT_MAX_CHARS: int = 12000   # about 3k tokens

# Questions about the meeting as a whole, which top-k retrieval answers badly.
_MEETING_WIDE = re.compile(
    r"summar|ringkas|rangkum|recap|overview|gambaran umum|kesimpulan|conclu"
    r"|keputusan|decision|decided|disepakati|agreed"
    r"|action item|tindak lanjut|follow[- ]?up|next step|langkah selanjutnya|to-?do"
    r"|poin (utama|penting)|main (point|topic)|key (point|takeaway)"
    r"|(apa|topik|hal) (saja )?yang dibahas|what (was|were) discussed|topics",
    re.IGNORECASE,
)


def is_meeting_wide(query: str) -> bool:
    return bool(_MEETING_WIDE.search(query))


# Common function words, used to answer fixed replies in the question's language.
_ID_WORDS = {
    "apa", "siapa", "kapan", "mana", "dimana", "bagaimana", "gimana", "berapa",
    "kenapa", "mengapa", "apakah", "yang", "dan", "ini", "itu", "dia", "mereka",
    "saja", "tentang", "untuk", "dengan", "ada", "tidak", "sudah", "akan", "bisa",
    "dari", "ke", "di", "oleh", "pada", "dalam", "nya", "kah", "tolong", "jelaskan",
}
_EN_WORDS = {
    "what", "who", "whom", "when", "where", "why", "how", "which", "is", "are",
    "was", "were", "the", "a", "an", "do", "does", "did", "he", "she", "they", "it",
    "in", "of", "to", "and", "about", "this", "that", "can", "could", "will",
    "would", "should", "please", "tell", "me", "explain", "any", "there",
}


def question_language(query: str) -> str:
    """'en' or 'id' by counting function words; ties go to 'id' (the UI language)."""
    words = re.findall(r"[a-z]+", query.lower())
    en = sum(w in _EN_WORDS for w in words)
    idn = sum(w in _ID_WORDS for w in words)
    return "en" if en > idn else "id"

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "it", "its", "we", "our", "you", "your", "they", "their",
    "he", "she", "his", "her", "i", "my", "me", "us", "in", "on", "at",
    "to", "for", "of", "and", "or", "but", "with", "from", "by", "as",
    "if", "so", "not", "no", "yes", "also", "just", "there", "here",
    "when", "where", "what", "how", "who", "which", "than", "then",
    "about", "up", "out", "get", "got", "let", "say", "said", "know",
    "think", "make", "go", "going", "one", "two", "all", "any", "some",
    "like", "more", "very", "really", "okay", "um", "uh", "yeah",
    "right", "well", "now", "back", "see",
    "speaker",   # every chunk line starts with "Speaker N:"
}

_ACTION_KEYWORDS = {
    "will", "should", "must", "need to", "going to", "plan to",
    "decided", "action item", "follow up", "todo", "next step",
    "responsible", "assign", "deadline", "deliver", "commit",
}


def _build_context(chunks: List[Dict]) -> str:
    lines, total = [], 0
    for c in chunks:
        line = c.get("expanded_text") or format_chunk(c)
        if total + len(line) > MAX_CONTEXT_CHARS:
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)


def _full_transcript(meeting_id: str) -> str:
    """Whole transcript as 'Speaker (t): text' lines, or '' when too long or missing."""
    result = storage_service.load_meeting(meeting_id)
    if not result:
        return ""
    text = "\n".join(f"{s.speaker} ({s.start_time:.0f}s): {s.text.strip()}"
                     for s in result.segments if s.text.strip())
    return text if len(text) <= FULL_TRANSCRIPT_MAX_CHARS else ""


_MAX_HISTORY_TURNS = 3   


def _build_prompt(query: str, context: str, history: list | None = None) -> str:
    """
    Build a conversational RAG prompt.

    Includes prior conversation turns (up to _MAX_HISTORY_TURNS) so the LLM
    can handle follow-up questions like "tell me more" or "who said that?".
    """
    history_block = ""
    if history:
        history_block = "Previous conversation:\n" + _format_history(history) + "\n\n"

    return (
        "You are an assistant that answers questions about a meeting using ONLY the "
        "transcript excerpts below.\n"
        "Rules:\n"
        "- Use only facts stated in the excerpts. Do not add names, numbers, dates, "
        "reasons, or other details that the excerpts do not state, and do not use "
        "outside knowledge.\n"
        "- The previous conversation only tells you what the question refers to; "
        "it is not a source of facts.\n"
        "- If the excerpts do not answer the question, say that the transcript does "
        "not mention it. You may add what the excerpts do say about the topic.\n"
        "- If the user asks about action items or decisions, list them explicitly, "
        "as stated in the excerpts.\n"
        "- Answer in the same language as the user's question, even when the "
        "transcript is in another language.\n"
        "- Write a clear, concise answer in full sentences.\n\n"
        f"{history_block}"
        f"Transcript excerpts:\n{context}\n\n"
        f"User: {query}\n"
        "Assistant:"
    )


def _format_history(history: list) -> str:
    lines = []
    for t in history[-_MAX_HISTORY_TURNS:]:
        lines.append(f"User: {t.get('question', t.get('q', ''))}")
        lines.append(f"Assistant: {t.get('answer', t.get('a', ''))}")
    return "\n".join(lines)


def _rewrite_query(query: str, history: list | None) -> str:
    """
    Turn a follow-up question into a standalone question for retrieval.

    Retrieval sees only the query, so "Which league does he play in?" has
    nothing to match on. Returns `query` unchanged when there is no history
    or the LLM call fails or returns something unusable.
    """
    if not history:
        return query
    prompt = (
        "Rewrite the user's last question so it can be understood without the "
        "conversation: replace pronouns and vague references (he, she, it, they, "
        "that, dia, itu, tersebut) with what they refer to. Keep the language of the "
        "last question. Do not answer it and do not add new information. If it is "
        "already standalone, return it unchanged. Output only the question.\n\n"
        f"Conversation:\n{_format_history(history)}\n\n"
        f"Last question: {query}\n"
        "Standalone question:"
    )
    try:
        text = llm_service.generate(prompt, max_new_tokens=80, num_beams=1)
    except Exception as exc:
        logger.warning(f"Query rewrite failed, using the original question: {exc}")
        return query
    lines = (text or "").strip().splitlines()
    rewritten = lines[0].strip().strip('"') if lines else ""
    if not rewritten or len(rewritten) > 300:
        return query
    return rewritten


def _extract_keywords(context: str, top_n: int = 8) -> List[str]:
    tokens = re.findall(r"\b[a-zA-Z]{3,}\b", context.lower())
    freq: Dict[str, int] = {}
    for tok in tokens:
        if tok not in _STOPWORDS:
            freq[tok] = freq.get(tok, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:top_n]]


def _extract_key_actions(context: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", context)
    actions: List[str] = []
    for sent in sentences:
        lower = sent.lower()
        if any(kw in lower for kw in _ACTION_KEYWORDS):
            cleaned = sent.strip()
            if len(cleaned) > 15:
                actions.append(cleaned)
    return actions[:5]


class RAGChain:
    """Retrieval-Augmented Generation over a single meeting's transcript."""

    # Fixed replies (no LLM call), in the language of the question.
    _NOT_FOUND = {
        "id": "Informasi tersebut tidak ditemukan dalam transkrip meeting ini. "
              "Coba ubah pertanyaan atau gunakan kata kunci yang disebut dalam meeting.",
        "en": "That information was not found in this meeting's transcript. "
              "Try rephrasing the question or using keywords mentioned in the meeting.",
    }
    _INDEX_MISSING = {
        "id": "Transkrip meeting ini belum bisa dicari. "
              "Pastikan transkripsi sudah selesai dan index FAISS sudah dibuat.",
        "en": "No relevant information found in this meeting's transcript. "
              "Ensure transcription has completed and the FAISS index is built.",
    }

    def chat(
        self, meeting_id: str, query: str, top_k: int = 3,
        history: list | None = None,
        config: RetrievalConfig | None = None,
    ) -> RAGChatResponse:
        """
        Retrieve relevant chunks and generate a structured grounded answer.

        Returns RAGChatResponse with transcription_summary, key_actions,
        keywords, source citations, and retrieval diagnostics.
        """
        cfg = config or RetrievalConfig(mode="vector")
        cfg.top_k = top_k

        reply = small_talk_reply(query)
        if reply:
            return RAGChatResponse(
                meeting_id=meeting_id,
                transcription_summary=reply,
                key_actions=[],
                keywords=[],
                sources=[],
                retrieval_mode=cfg.mode,
            )

        retrieval_query = _rewrite_query(query, history)

        # Meeting-wide questions read the whole transcript when it fits; the
        # retrieved chunks are then only citations, so abstention is skipped.
        # A transcript that is too long gets a wider top-k instead.
        wide = is_meeting_wide(retrieval_query)
        full_text = _full_transcript(meeting_id) if wide else ""
        if full_text:
            cfg.min_score = 0.0
        elif wide:
            cfg.top_k = max(cfg.top_k, 8)

        outcome = retrieval_service.retrieve(meeting_id, retrieval_query, cfg)
        chunks = outcome.chunks

        if not chunks and not full_text:
            lang = question_language(query)
            if outcome.abstain_reason == "index_missing":
                msg = self._INDEX_MISSING[lang]
            else:
                msg = self._NOT_FOUND[lang]
            return RAGChatResponse(
                meeting_id=meeting_id,
                transcription_summary=msg,
                key_actions=[],
                keywords=[],
                sources=[],
                retrieval_mode=outcome.mode,
                abstained=outcome.abstained,
                abstain_reason=outcome.abstain_reason,
                retrieval_latency_ms=round(outcome.latency_ms, 2),
                retrieval_query=retrieval_query,
            )

        context = full_text or _build_context(chunks)
        summary = llm_service.generate(
            _build_prompt(query, context, history),
            max_new_tokens=500 if full_text else 300, num_beams=1,
        )

        return RAGChatResponse(
            meeting_id=meeting_id,
            transcription_summary=summary,
            key_actions=_extract_key_actions(context),
            keywords=_extract_keywords(context),
            sources=[SourceChunk(**_source_fields(c)) for c in chunks],
            retrieval_mode=f"{outcome.mode} + full transcript" if full_text else outcome.mode,
            reranked=outcome.reranked,
            retrieval_latency_ms=round(outcome.latency_ms, 2),
            retrieval_query=retrieval_query,
        )


def _source_fields(c: Dict) -> Dict:
    keys = SourceChunk.model_fields.keys()
    return {k: v for k, v in c.items() if k in keys and v is not None}


rag_chain = RAGChain()