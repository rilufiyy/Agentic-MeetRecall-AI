"""
Retrieval service: full-text (BM25), vector (FAISS), and hybrid search.

Pipeline for one query:
  1. Candidate generation
       - vector   : cosine similarity over the meeting's FAISS index
       - fulltext : BM25 over the same segments (services.keyword_index)
       - hybrid   : both, merged with a fusion method
  2. Fusion (hybrid only)
       - "rrf"      : Reciprocal Rank Fusion, score = sum(w / (k + rank)).
                      Uses ranks only, so BM25 scores (unbounded) and cosine
                      scores (-1..1) never need to be put on one scale.
       - "weighted" : min-max normalise each score list, then
                      alpha * vector + (1 - alpha) * bm25.
                      Gives direct control over the balance, but depends on
                      the normalisation of each list.
  3. Optional reranking with a multilingual cross-encoder (second stage).
  4. Optional abstention when nothing in the transcript is close enough
     (min_score on cosine similarity, see _should_abstain).
  5. Optional neighbour expansion: attach adjacent chunks as extra context
     for the LLM.

Chunks are windows of consecutive transcript segments (services.chunking),
not single ASR segments. chunk_id is shared by FAISS and BM25 (both are built from the same list),
so results from different methods can be compared and fused by id.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from services.keyword_index import BM25Index, tokenize
from services.vector_store import vector_store

logger = logging.getLogger(__name__)

RETRIEVAL_MODES = ("vector", "fulltext", "hybrid")
FUSION_METHODS = ("rrf", "weighted")

RERANKER_MODEL_ID = os.getenv(
    "RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
)


# Fusion helpers (pure functions, unit-tested in tests/test_retrieval.py)

def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[int]],
    k: int = 60,
    weights: Optional[Sequence[float]] = None,
) -> Dict[int, float]:
    """
    Merge several ranked lists of ids into one score map.

    score(d) = sum_i  w_i / (k + rank_i(d)),  rank starts at 1.
    A document missing from a list simply gets no contribution from it.
    k dampens the advantage of the very top ranks (60 is the common default).
    """
    weights = list(weights) if weights else [1.0] * len(ranked_lists)
    fused: Dict[int, float] = {}
    for w, ranking in zip(weights, ranked_lists):
        for rank, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + w / (k + rank)
    return fused


def _min_max(scores: Dict[int, float]) -> Dict[int, float]:
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi - lo < 1e-12:
        return {d: 1.0 for d in scores}
    return {d: (s - lo) / (hi - lo) for d, s in scores.items()}


def weighted_score_fusion(
    vector_scores: Dict[int, float],
    keyword_scores: Dict[int, float],
    alpha: float = 0.5,
) -> Dict[int, float]:
    """alpha * norm(vector) + (1 - alpha) * norm(bm25); missing score counts as 0."""
    v, kw = _min_max(vector_scores), _min_max(keyword_scores)
    ids = set(v) | set(kw)
    return {d: alpha * v.get(d, 0.0) + (1 - alpha) * kw.get(d, 0.0) for d in ids}


# Configuration and result containers

@dataclass
class RetrievalConfig:
    mode: str = "hybrid"
    top_k: int = 3
    candidate_k: int = 20          # candidates per method before fusion/rerank
    fusion: str = "rrf"
    rrf_k: int = 60
    alpha: float = 0.5             # weight of the vector side (weighted fusion)
    rerank: bool = False
    min_score: float = 0.0         # cosine threshold for abstention, 0 = off
    expand_neighbors: int = 0      # attach N segments before/after as context

    def validate(self) -> None:
        if self.mode not in RETRIEVAL_MODES:
            raise ValueError(f"mode must be one of {RETRIEVAL_MODES}")
        if self.fusion not in FUSION_METHODS:
            raise ValueError(f"fusion must be one of {FUSION_METHODS}")
        self.candidate_k = max(self.candidate_k, self.top_k)


@dataclass
class RetrievalOutcome:
    mode: str
    chunks: List[Dict] = field(default_factory=list)
    abstained: bool = False
    abstain_reason: str = ""
    reranked: bool = False
    latency_ms: float = 0.0


# Reranker (lazy, optional)

class _CrossEncoderReranker:
    _model = None
    _failed = False

    def available(self) -> bool:
        if self._model is not None:
            return True
        if self._failed:
            return False
        try:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading reranker: {RERANKER_MODEL_ID}")
            _CrossEncoderReranker._model = CrossEncoder(RERANKER_MODEL_ID, max_length=256)
            return True
        except Exception as exc:  # model download blocked, no internet, etc.
            logger.warning(f"Reranker unavailable, continuing without it: {exc}")
            _CrossEncoderReranker._failed = True
            return False

    def score(self, query: str, texts: List[str]) -> List[float]:
        return [float(s) for s in self._model.predict([(query, t) for t in texts])]


# Service

class RetrievalService:

    def __init__(self) -> None:
        # meeting_id -> (id(chunk_list), BM25Index); rebuilt when FAISS is rebuilt
        self._bm25_cache: Dict[str, tuple] = {}
        self._reranker = _CrossEncoderReranker()

    # Index access

    def _chunks(self, meeting_id: str) -> Optional[List[Dict]]:
        if not vector_store._load_if_needed(meeting_id):
            return None
        return vector_store._cache[meeting_id][1]

    def _bm25(self, meeting_id: str, chunks: List[Dict]) -> BM25Index:
        cached = self._bm25_cache.get(meeting_id)
        if cached and cached[0] == id(chunks):
            return cached[1]
        # The speaker label is indexed together with the text, so questions
        # such as "apa kata Dimas soal ..." can match on the speaker name even
        # when the segment itself never mentions it (cheap metadata enrichment).
        index = BM25Index([f"{c.get('speaker', '')} {c['text']}" for c in chunks])
        self._bm25_cache[meeting_id] = (id(chunks), index)
        return index

    def reranker_available(self) -> bool:
        return self._reranker.available()

    # Main entry point

    def retrieve(self, meeting_id: str, query: str, cfg: RetrievalConfig) -> RetrievalOutcome:
        cfg.validate()
        t0 = time.perf_counter()
        out = RetrievalOutcome(mode=cfg.mode)

        chunks = self._chunks(meeting_id)
        if not chunks:
            out.abstained, out.abstain_reason = True, "index_missing"
            return out

        # 1. Candidate generation. The flat FAISS index is exact, so scoring every
        #    segment is cheap for meeting-sized data and gives each candidate a
        #    cosine score (also used for abstention and for display).
        need_vector = cfg.mode in ("vector", "hybrid")
        vector_scores: Dict[int, float] = {}
        if need_vector:
            for hit in vector_store.search(meeting_id, query, top_k=len(chunks)):
                vector_scores[hit["chunk_id"]] = hit["score"]
        vector_rank = sorted(vector_scores, key=lambda d: -vector_scores[d])[: cfg.candidate_k]

        keyword_scores: Dict[int, float] = {}
        matched: Dict[int, List[str]] = {}
        if cfg.mode in ("fulltext", "hybrid"):
            for hit in self._bm25(meeting_id, chunks).search(query, cfg.candidate_k):
                keyword_scores[hit["doc_idx"]] = hit["score"]
                matched[hit["doc_idx"]] = hit["matched_terms"]
        keyword_rank = sorted(keyword_scores, key=lambda d: -keyword_scores[d])

        # 2. Ranking / fusion
        if cfg.mode == "vector":
            final = {d: vector_scores[d] for d in vector_rank}
        elif cfg.mode == "fulltext":
            final = dict(keyword_scores)
        elif cfg.fusion == "rrf":
            final = reciprocal_rank_fusion([vector_rank, keyword_rank], k=cfg.rrf_k)
        else:
            final = weighted_score_fusion(
                {d: vector_scores[d] for d in vector_rank}, keyword_scores, cfg.alpha
            )
        ranked = sorted(final, key=lambda d: -final[d])[: cfg.candidate_k]

        # 3. Abstention (answer "not found" instead of feeding weak context)
        reason = self._should_abstain(cfg, query, vector_scores, matched, ranked)
        if reason:
            out.abstained, out.abstain_reason = True, reason
            out.latency_ms = (time.perf_counter() - t0) * 1000
            return out

        # 4. Optional second-stage reranking over the fused candidates
        rerank_scores: Dict[int, float] = {}
        if cfg.rerank and ranked and self._reranker.available():
            scores = self._reranker.score(query, [chunks[d]["text"] for d in ranked])
            rerank_scores = dict(zip(ranked, scores))
            ranked = sorted(ranked, key=lambda d: -rerank_scores[d])
            out.reranked = True

        # 5. Build result records
        for rank, d in enumerate(ranked[: cfg.top_k], start=1):
            c = chunks[d]
            record = {
                "chunk_id": d,
                "rank": rank,
                "text": c["text"],
                "speaker": c.get("speaker", "Unknown"),
                "start_time": c.get("start_time", 0.0),
                "end_time": c.get("end_time", 0.0),
                "score": rerank_scores.get(d, final[d]),
                "vector_score": vector_scores.get(d),
                "keyword_score": keyword_scores.get(d),
                "rerank_score": rerank_scores.get(d),
                "matched_terms": matched.get(d, []),
                "retrieval_mode": cfg.mode,
            }
            if cfg.expand_neighbors > 0:
                record["expanded_text"] = self._expand(chunks, d, cfg.expand_neighbors)
            out.chunks.append(record)

        out.latency_ms = (time.perf_counter() - t0) * 1000
        return out

    # Helpers

    @staticmethod
    def _should_abstain(
        cfg: RetrievalConfig,
        query: str,
        vector_scores: Dict[int, float],
        matched: Dict[int, List[str]],
        ranked: List[int],
    ) -> str:
        if not ranked:
            return "no_match"
        if cfg.min_score <= 0:
            return ""
        best_cos = max(vector_scores.values()) if vector_scores else 0.0
        semantic_ok = best_cos >= cfg.min_score
        if cfg.mode == "vector":
            return "" if semantic_ok else "below_min_score"
        # Lexical evidence counts as "strong" when a segment contains at least
        # half of the distinct query terms (e.g. an exact ticket code + topic).
        q_terms = set(tokenize(query))
        lexical_ok = bool(q_terms) and any(
            len(terms) / len(q_terms) >= 0.5 for terms in matched.values()
        )
        if cfg.mode == "fulltext":
            return "" if lexical_ok else "weak_lexical_match"
        return "" if (semantic_ok or lexical_ok) else "below_min_score"

    @staticmethod
    def _expand(chunks: List[Dict], idx: int, n: int) -> str:
        # Neighbouring chunks share their boundary segments, so repeated lines are dropped.
        lo, hi = max(0, idx - n), min(len(chunks), idx + n + 1)
        lines: List[str] = []
        for i in range(lo, hi):
            for line in chunks[i]["text"].split("\n"):
                if line not in lines:
                    lines.append(line)
        return format_chunk({**chunks[lo], "end_time": chunks[hi - 1].get("end_time", 0.0),
                             "text": "\n".join(lines)})


def format_chunk(c: Dict) -> str:
    """Chunk as LLM context: time span header, then 'Speaker: text' lines."""
    return f"[{c.get('start_time', 0):.1f}s - {c.get('end_time', 0):.1f}s]\n{c['text']}"


retrieval_service = RetrievalService()
