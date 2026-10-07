"""
RAG chatbot router.

Endpoints:
  POST /api/rag/chat/{meeting_id}     - Q&A grounded in transcript
  POST /api/rag/reindex/{meeting_id}  - force rebuild FAISS index
  POST /api/rag/retrieve/{meeting_id} - compare fulltext / vector / hybrid
                                        results side by side (no LLM call)
  POST /api/rag/evaluate/{meeting_id} - run a labelled question set and return
                                        Hit@k, Recall@k, MRR@k per mode
  GET  /api/rag/retrieval-info        - available modes and reranker status
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.schemas import (
    EvaluateRequest,
    ModeResult,
    RAGChatRequest,
    RAGChatResponse,
    RetrieveRequest,
    RetrieveResponse,
    SourceChunk,
)
from services.rag_chain import rag_chain
from services.retrieval import (
    FUSION_METHODS,
    RERANKER_MODEL_ID,
    RETRIEVAL_MODES,
    RetrievalConfig,
    retrieval_service,
)
from services.retrieval_eval import run_evaluation
from services.storage import storage_service
from services.vector_store import vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["RAG Chatbot"])


def _require_completed(meeting_id: str) -> None:
    """Raise 404/409 if the meeting is missing or not yet completed."""
    info = storage_service.get_meeting_info(meeting_id)
    if not info:
        raise HTTPException(404, "Meeting not found.")
    if info.status != "completed":
        raise HTTPException(409, f"Meeting not ready. Current status: {info.status}")


def _ensure_index(meeting_id: str) -> None:
    """Build the FAISS index lazily if it is missing or uses an older chunking."""
    if vector_store.is_current(meeting_id):
        return
    result = storage_service.load_meeting(meeting_id)
    if not result:
        raise HTTPException(500, "Transcript data not found.")
    vector_store.index_segments(meeting_id, result.segments)
    logger.info(f"Lazily rebuilt FAISS index for meeting {meeting_id}.")


@router.post("/chat/{meeting_id}", response_model=RAGChatResponse)
async def chat_with_meeting(meeting_id: str, request: RAGChatRequest):
    """
    Ask a question about a specific meeting.

    The answer is grounded in retrieved transcript chunks (RAG).
    Each response includes **source citations** (speaker, timestamp, text).

    - **top_k**: number of transcript chunks to retrieve (1-10, default 3).
    - **retrieval_mode**: `vector`, `fulltext`, or `hybrid` (default).
    - **min_score**: abstain threshold on cosine similarity (0 = off).
    """
    _require_completed(meeting_id)
    _ensure_index(meeting_id)

    history = [t.model_dump() for t in request.history] if request.history else None
    cfg = RetrievalConfig(**request.to_config_kwargs())
    try:
        return rag_chain.chat(meeting_id, request.query, request.top_k, history, cfg)
    except Exception as exc:
        logger.error(f"RAG chat error for {meeting_id}: {exc}")
        raise HTTPException(500, f"RAG error: {exc}")


@router.post("/retrieve/{meeting_id}", response_model=RetrieveResponse)
async def compare_retrieval(meeting_id: str, request: RetrieveRequest):
    """Run the same query through several retrieval modes (retrieval only, no LLM)."""
    _require_completed(meeting_id)
    _ensure_index(meeting_id)

    results = []
    for mode in request.modes:
        cfg = RetrievalConfig(**{**request.to_config_kwargs(), "mode": mode,
                                 "top_k": request.top_k})
        out = retrieval_service.retrieve(meeting_id, request.query, cfg)
        results.append(ModeResult(
            mode=mode,
            chunks=[SourceChunk(**{k: v for k, v in c.items()
                                   if k in SourceChunk.model_fields and v is not None})
                    for c in out.chunks],
            abstained=out.abstained,
            abstain_reason=out.abstain_reason,
            reranked=out.reranked,
            latency_ms=round(out.latency_ms, 2),
        ))
    return RetrieveResponse(meeting_id=meeting_id, query=request.query, results=results)


@router.post("/evaluate/{meeting_id}")
async def evaluate_retrieval(meeting_id: str, request: EvaluateRequest):
    """
    Evaluate retrieval modes on a labelled question set.

    A case is answerable when it lists `relevant_text_contains` and/or
    `relevant_chunk_ids`; set `expect_no_answer: true` for questions the meeting
    does not cover (scored as abstain accuracy, needs `min_score > 0`).
    """
    _require_completed(meeting_id)
    _ensure_index(meeting_id)
    base = request.to_config_kwargs()
    base.pop("mode", None)
    try:
        return run_evaluation(
            meeting_id,
            [c.model_dump() for c in request.cases],
            modes=request.modes,
            k=request.k,
            base_config=base,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/retrieval-info")
async def retrieval_info(check_reranker: bool = False):
    """List retrieval options. check_reranker=true loads the reranker model."""
    return {
        "modes": list(RETRIEVAL_MODES),
        "fusion_methods": list(FUSION_METHODS),
        "reranker_model": RERANKER_MODEL_ID,
        "reranker_available": retrieval_service.reranker_available() if check_reranker else None,
    }


@router.post("/reindex/{meeting_id}", status_code=200)
async def reindex_meeting(meeting_id: str):
    """Force rebuild the FAISS index for a meeting (useful after edits).
    The BM25 index is rebuilt automatically on the next query."""
    _require_completed(meeting_id)
    result = storage_service.load_meeting(meeting_id)
    if not result:
        raise HTTPException(404, "Transcript data not found.")

    n_chunks = vector_store.index_segments(meeting_id, result.segments)
    return {"message": f"Re-indexed {n_chunks} chunks for meeting {meeting_id}."}
