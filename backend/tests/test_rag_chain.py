"""
Unit tests for follow-up question rewriting in the RAG chain. The LLM and
retrieval are replaced by stubs, but importing services.rag_chain still needs
the full backend deps (torch), so the tests are skipped without them.

Run from backend/:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

rc = pytest.importorskip("services.rag_chain")
from services.retrieval import RetrievalConfig, RetrievalOutcome  # noqa: E402

Q1 = "Who is the celebrity endorsement from the Japan Baseball League?"
A1 = "The transcript mentions a power hitter from the Japan Baseball League."
FOLLOW_UP = "Which league does he play in?"
STANDALONE = "Which league does the power hitter celebrity endorsement play in?"
HISTORY = [{"question": Q1, "answer": A1}]


def _llm(rewrite_output):
    """Stub LLM: rewrite prompts get `rewrite_output`, answer prompts get a fixed answer."""
    calls = []

    def generate(prompt, **kw):
        calls.append(prompt)
        if "Standalone question:" in prompt:
            if isinstance(rewrite_output, Exception):
                raise rewrite_output
            return rewrite_output
        return "He plays in the Japan Baseball League."
    return generate, calls


def test_rewrite_skipped_without_history(monkeypatch):
    generate, calls = _llm(STANDALONE)
    monkeypatch.setattr(rc.llm_service, "generate", generate)
    assert rc._rewrite_query(FOLLOW_UP, None) == FOLLOW_UP
    assert rc._rewrite_query(FOLLOW_UP, []) == FOLLOW_UP
    assert calls == []


def test_rewrite_uses_history_and_cleans_output(monkeypatch):
    generate, calls = _llm(f'"{STANDALONE}"\nExplanation: replaced "he".')
    monkeypatch.setattr(rc.llm_service, "generate", generate)
    assert rc._rewrite_query(FOLLOW_UP, HISTORY) == STANDALONE
    assert Q1 in calls[0] and FOLLOW_UP in calls[0]


@pytest.mark.parametrize("bad_output", [RuntimeError("LLM down"), "", "   \n", "x" * 400])
def test_rewrite_falls_back_to_original_question(monkeypatch, bad_output):
    generate, _ = _llm(bad_output)
    monkeypatch.setattr(rc.llm_service, "generate", generate)
    assert rc._rewrite_query(FOLLOW_UP, HISTORY) == FOLLOW_UP


def test_chat_retrieves_with_rewritten_query(monkeypatch):
    generate, calls = _llm(STANDALONE)
    monkeypatch.setattr(rc.llm_service, "generate", generate)
    seen = []

    def retrieve(meeting_id, query, cfg):
        seen.append(query)
        return RetrievalOutcome(mode=cfg.mode, chunks=[{
            "chunk_id": 1, "rank": 1, "text": "Speaker 3: a power hitter from the Japan Baseball League",
            "speaker": "Speaker 3", "start_time": 76.7, "end_time": 110.2, "score": 0.03}])
    monkeypatch.setattr(rc.retrieval_service, "retrieve", retrieve)

    resp = rc.rag_chain.chat("m1", FOLLOW_UP, 3, HISTORY,
                             RetrievalConfig(mode="hybrid", min_score=0.40))
    assert seen == [STANDALONE]
    assert resp.retrieval_query == STANDALONE
    assert not resp.abstained
    # the answer prompt still carries the user's own question
    assert f"User: {FOLLOW_UP}" in calls[-1]


def test_chat_keeps_original_query_when_rewrite_fails(monkeypatch):
    generate, _ = _llm(RuntimeError("LLM down"))
    monkeypatch.setattr(rc.llm_service, "generate", generate)
    seen = []

    def retrieve(meeting_id, query, cfg):
        seen.append(query)
        return RetrievalOutcome(mode=cfg.mode, abstained=True, abstain_reason="below_min_score")
    monkeypatch.setattr(rc.retrieval_service, "retrieve", retrieve)

    resp = rc.rag_chain.chat("m1", FOLLOW_UP, 3, HISTORY,
                             RetrievalConfig(mode="hybrid", min_score=0.40))
    assert seen == [FOLLOW_UP]
    assert resp.abstained and resp.retrieval_query == FOLLOW_UP


@pytest.mark.parametrize("query,lang", [
    ("Which specific sports league does he play in?", "en"),
    ("Who is the celebrity endorsement?", "en"),
    ("Apa isu di tiket MR-241?", "id"),
    ("Siapa yang bertanggung jawab atas bug ini?", "id"),
    ("MR-241", "id"),                        # no signal: UI language
])
def test_question_language(query, lang):
    assert rc.question_language(query) == lang


@pytest.mark.parametrize("query,expected", [
    ("Which specific sports league does he play in?", "was not found"),
    ("Liga apa yang dia mainkan?", "tidak ditemukan"),
])
def test_not_found_reply_follows_question_language(monkeypatch, query, expected):
    monkeypatch.setattr(rc.retrieval_service, "retrieve", lambda mid, q, cfg: RetrievalOutcome(
        mode=cfg.mode, abstained=True, abstain_reason="below_min_score"))
    resp = rc.rag_chain.chat("m1", query, 3, None, RetrievalConfig(mode="hybrid", min_score=0.40))
    assert resp.abstained and expected in resp.transcription_summary


def test_prompt_asks_for_the_question_language():
    assert "same language as the user's question" in rc._build_prompt("Who?", "ctx")
