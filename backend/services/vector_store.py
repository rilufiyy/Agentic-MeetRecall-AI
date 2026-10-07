"""
FAISS vector store - one index per meeting, persisted to disk.

Index type: IndexFlatIP (inner-product on L2-normalised vectors = cosine similarity).
Chunk metadata (text, speaker, timestamps) is stored alongside in a pickle file.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Dict, List

from services.chunking import CHUNK_VERSION, build_chunks
from services.embeddings import embedding_service, EMBEDDING_DIM

logger = logging.getLogger(__name__)

_FAISS_DIR = Path("data/faiss")
_FAISS_DIR.mkdir(parents=True, exist_ok=True)


class FAISSVectorStore:
    """Per-meeting FAISS indices with disk persistence."""

    def __init__(self) -> None:
        self._cache: Dict[str, tuple] = {}

    # Paths

    @staticmethod
    def _idx_path(meeting_id: str) -> Path:
        return _FAISS_DIR / f"{meeting_id}.index"

    @staticmethod
    def _meta_path(meeting_id: str) -> Path:
        return _FAISS_DIR / f"{meeting_id}_chunks.pkl"

    # Build

    def index_meeting(
        self,
        meeting_id: str,
        texts: List[str],
        metadata: List[Dict],
    ) -> None:
        """
        Build and persist a FAISS index for one meeting.

        Args:
            texts    : List of text strings (one per transcript segment).
            metadata : Parallel list of dicts {speaker, start_time, end_time}.
        """
        if not texts:
            logger.warning(f"No texts to index for meeting {meeting_id}.")
            return

        import faiss

        embeddings = embedding_service.encode(texts)
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        index.add(embeddings)

        chunk_data: List[Dict] = [
            {**meta, "text": text, "chunk_id": i}
            for i, (text, meta) in enumerate(zip(texts, metadata))
        ]

        # Persist
        faiss.write_index(index, str(self._idx_path(meeting_id)))
        with open(self._meta_path(meeting_id), "wb") as f:
            pickle.dump(chunk_data, f)

        # Update cache
        self._cache[meeting_id] = (index, chunk_data)
        logger.info(f"Indexed {len(texts)} chunks for meeting {meeting_id}.")

    def index_segments(self, meeting_id: str, segments) -> int:
        """Chunk transcript segments (services.chunking) and index them. Returns the chunk count."""
        texts, metadata = build_chunks(segments)
        self.index_meeting(meeting_id, texts, metadata)
        return len(texts)

    # Search

    def search(
        self, meeting_id: str, query: str, top_k: int = 5
    ) -> List[Dict]:
        """Return top-k chunks most similar to query (cosine similarity)."""
        if not self._load_if_needed(meeting_id):
            return []

        index, chunk_data = self._cache[meeting_id]
        query_emb = embedding_service.encode_single(query).reshape(1, -1)
        k = min(top_k, index.ntotal)
        scores, indices = index.search(query_emb, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:
                chunk = dict(chunk_data[idx])
                chunk["score"] = float(score)
                results.append(chunk)
        return results

    # Helpers

    def _load_if_needed(self, meeting_id: str) -> bool:
        if meeting_id in self._cache:
            return True
        idx_path = self._idx_path(meeting_id)
        meta_path = self._meta_path(meeting_id)
        if not idx_path.exists() or not meta_path.exists():
            logger.warning(f"No FAISS index on disk for meeting {meeting_id}.")
            return False
        import faiss
        index = faiss.read_index(str(idx_path))
        with open(meta_path, "rb") as f:
            chunk_data = pickle.load(f)
        self._cache[meeting_id] = (index, chunk_data)
        return True

    def exists(self, meeting_id: str) -> bool:
        return self._idx_path(meeting_id).exists()

    def is_current(self, meeting_id: str) -> bool:
        """True when an index exists and was built with the current chunking."""
        if not self._load_if_needed(meeting_id):
            return False
        chunks = self._cache[meeting_id][1]
        return bool(chunks) and chunks[0].get("chunk_version") == CHUNK_VERSION


vector_store = FAISSVectorStore()