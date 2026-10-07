"""
Unit tests for the retrieval building blocks that do not need any model:
tokenizer, BM25, fusion functions, transcript parsing, and ranking metrics.

Run from backend/:  python -m pytest tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.keyword_index import BM25Index, tokenize  # noqa: E402
from services.retrieval import (  # noqa: E402
    RetrievalConfig,
    reciprocal_rank_fusion,
    retrieval_service,
    weighted_score_fusion,
)
from services.vector_store import vector_store  # noqa: E402
from services.retrieval_eval import evaluate_ranking  # noqa: E402
from services.transcript_import import parse_transcript  # noqa: E402


def test_tokenize_keeps_codes_and_drops_stopwords():
    toks = tokenize("Tiket MR-218 yang lambat di v2.4.1, p95 850 ms")
    assert "mr-218" in toks and "mr" in toks and "218" in toks
    assert "v2.4.1" in toks
    assert "yang" not in toks and "di" not in toks


def test_bm25_prefers_exact_rare_term():
    docs = [
        "notifikasi email terkirim dua kali",
        "tiket MR-241 notifikasi ganda",
        "rapat membahas notifikasi dan email",
    ]
    hits = BM25Index(docs).search("MR-241", top_k=3)
    assert hits and hits[0]["doc_idx"] == 1
    assert "mr-241" in hits[0]["matched_terms"]


def test_bm25_no_overlap_returns_nothing():
    assert BM25Index(["halo semua"]).search("PayLink") == []


def test_rrf_rewards_agreement_between_lists():
    fused = reciprocal_rank_fusion([[1, 2, 3], [2, 4, 1]], k=60)
    ranked = sorted(fused, key=lambda d: -fused[d])
    assert ranked[0] == 2          # rank 2 + rank 1 beats rank 1 + rank 3
    assert set(fused) == {1, 2, 3, 4}


def test_weighted_fusion_alpha_extremes():
    vec = {1: 0.9, 2: 0.1}
    kw = {1: 0.5, 2: 12.0}
    only_vec = weighted_score_fusion(vec, kw, alpha=1.0)
    only_kw = weighted_score_fusion(vec, kw, alpha=0.0)
    assert max(only_vec, key=only_vec.get) == 1
    assert max(only_kw, key=only_kw.get) == 2


def test_parse_transcript_timestamps_and_end_times():
    raw = "# komentar\n[00:00:04] Rina: Mulai.\n[00:00:11] Dimas: Oke.\nSari: Tanpa waktu."
    segs, duration = parse_transcript(raw)
    assert [s.speaker for s in segs] == ["Rina", "Dimas", "Sari"]
    assert segs[0].start_time == 4 and segs[0].end_time == 11
    assert segs[2].start_time == segs[1].end_time
    assert duration == segs[-1].end_time


def test_evaluate_ranking_metrics():
    m = evaluate_ranking([5, 2, 9], {2, 7})
    assert m["hit"] == 1.0 and m["rr"] == 0.5 and m["recall"] == 0.5
    assert evaluate_ranking([1, 3], {2})["hit"] == 0.0


# Abstention (min_score) with a stub vector store, so no embedding model is needed.
# Chunks and cosine scores are taken from the "Ginger Cola Launch" meeting where
# the chat used to report a wrongly rejected question.

_GINGER_CHUNKS = [
    "Speaker 0: Carrie, can you please give us an update on the marketing strategy?",
    "Speaker 0: Where are we with the advertising and promotion strategy?\n"
    "Speaker 3: But we are planning to have a power hitter from the Japan Baseball League "
    "as a celebrity endorsement.",
    "Speaker 0: Let's move on to the charity walkathon.",
]


def _stub_index(monkeypatch, meeting_id, cosines):
    chunks = [{"speaker": "Speaker 0", "start_time": float(i), "end_time": i + 1.0,
               "text": t, "chunk_id": i} for i, t in enumerate(_GINGER_CHUNKS)]
    monkeypatch.setitem(vector_store._cache, meeting_id, (None, chunks))
    monkeypatch.setattr(vector_store, "search", lambda mid, q, top_k=5: sorted(
        ({**c, "score": s} for c, s in zip(chunks, cosines)), key=lambda h: -h["score"]))


def test_hybrid_does_not_abstain_when_a_chunk_has_half_the_query_terms(monkeypatch):
    # best cosine 0.359 < 0.40, but chunk 1 contains 5/5 query terms
    _stub_index(monkeypatch, "abstain-lexical", [0.06, 0.359, 0.03])
    q = "Who is the celebrity endorsement from the Japan Baseball League?"
    out = retrieval_service.retrieve("abstain-lexical", q,
                                     RetrievalConfig(mode="hybrid", min_score=0.40, top_k=3))
    assert not out.abstained
    assert out.chunks[0]["chunk_id"] == 1
    assert len(out.chunks[0]["matched_terms"]) == 5


def test_abstains_when_cosine_and_lexical_evidence_are_both_weak(monkeypatch):
    _stub_index(monkeypatch, "abstain-weak", [0.10, 0.20, 0.05])
    # 1 of 4 query terms ("baseball") matches: below the 50% lexical rule
    q = "What position does the baseball player field?"
    hybrid = retrieval_service.retrieve("abstain-weak", q,
                                        RetrievalConfig(mode="hybrid", min_score=0.40))
    assert hybrid.abstained and hybrid.abstain_reason == "below_min_score"
    # vector mode ignores lexical evidence, so the 5/5 question is rejected there
    q5 = "Who is the celebrity endorsement from the Japan Baseball League?"
    vector = retrieval_service.retrieve("abstain-weak", q5,
                                        RetrievalConfig(mode="vector", min_score=0.40))
    assert vector.abstained
