"""
MeetRecall AI - FastAPI backend entry point.

Services:
  - Transcription  : Gemini 3.5 Transcribe, Groq Whisper, or local Whisper
  - Embeddings     : sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  - Vector Search  : FAISS (per-meeting index, persisted to disk)
  - Retrieval      : BM25 full-text, FAISS vector, hybrid fusion (RRF / weighted)
  - RAG Chatbot    : Groq LLM (or local Qwen2 fallback) grounded on transcript chunks
"""
from __future__ import annotations

import logging
import shutil
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import agent, rag, transcribe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Queued jobs live in memory; ones left unfinished by a restart are marked gagal.
    Lifespan events: https://fastapi.tiangolo.com/advanced/events/"""
    # Load the embedding model now, so the first agent request does not pay ~10 s for it.
    def _warm() -> None:
        try:
            from services.embeddings import embedding_service
            embedding_service.encode_single("warm up")
        except Exception as exc:   # warm-up is an optimisation only
            logging.getLogger(__name__).warning(f"Embedding warm-up gagal: {exc}")
    threading.Thread(target=_warm, name="embedding-warmup", daemon=True).start()

    n = transcribe.job_runner.recover()
    if n:
        logging.getLogger(__name__).warning(f"{n} job transkripsi ditandai gagal setelah restart.")
    yield


app = FastAPI(
    title="MeetRecall AI",
    version="2.0.0",
    description=(
        "Meeting knowledge retrieval - transcription, full-text / vector / hybrid "
        "search, and a RAG chatbot grounded on the transcript."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transcribe.router)
app.include_router(rag.router)
app.include_router(agent.router)


@app.get("/", tags=["Health"])
async def root():
    return {
        "app": "MeetRecall AI",
        "version": "2.0.0",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
async def health():
    """Quick liveness check - also verifies ffmpeg is installed."""
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    return {
        "status": "healthy" if ffmpeg_ok else "degraded",
        "ffmpeg": ffmpeg_ok,
    }