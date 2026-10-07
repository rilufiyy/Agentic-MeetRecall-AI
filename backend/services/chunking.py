"""
Chunking: group consecutive transcript segments into retrieval chunks.

A single ASR segment is often one short sentence ("Let's try that next
week."), which carries too little context to be retrieved on its own, and a
top-3 search over one-sentence chunks sees only a small slice of a meeting.
Consecutive segments are therefore merged into windows of about
CHUNK_TARGET_WORDS words, with CHUNK_OVERLAP_SEGMENTS segments repeated
between windows so an exchange cut at a boundary still appears whole in one
chunk.

The target stays small because the embedding model
(paraphrase-multilingual-MiniLM-L12-v2) reads only the first 128 tokens of
a text; longer chunks would be embedded without their tail.

Each chunk keeps its speakers and time span, and every line in the chunk text
is prefixed with its speaker, so "what did Speaker 2 say" still matches.
"""
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

CHUNK_VERSION = 2   # bump when the chunking changes so old indexes are rebuilt
CHUNK_TARGET_WORDS = int(os.getenv("CHUNK_TARGET_WORDS", "60"))
CHUNK_OVERLAP_SEGMENTS = int(os.getenv("CHUNK_OVERLAP_SEGMENTS", "1"))


def _field(seg, name):
    return seg.get(name) if isinstance(seg, dict) else getattr(seg, name)


def build_chunks(
    segments: Sequence,
    target_words: int = CHUNK_TARGET_WORDS,
    overlap: int = CHUNK_OVERLAP_SEGMENTS,
) -> Tuple[List[str], List[Dict]]:
    """
    Merge segments (TranscriptSegment or dict with speaker, start_time,
    end_time, text) into (texts, metadata) for vector_store.index_meeting.
    """
    segs = [s for s in segments if str(_field(s, "text") or "").strip()]
    texts: List[str] = []
    metas: List[Dict] = []
    start = 0
    while start < len(segs):
        end, words = start, 0
        while end < len(segs) and (end == start or words < target_words):
            words += len(str(_field(segs[end], "text")).split())
            end += 1
        window = segs[start:end]

        speakers: List[str] = []
        for s in window:
            if _field(s, "speaker") not in speakers:
                speakers.append(_field(s, "speaker"))
        texts.append("\n".join(
            f"{_field(s, 'speaker')}: {str(_field(s, 'text')).strip()}" for s in window
        ))
        metas.append({
            "speaker": ", ".join(speakers),
            "start_time": float(_field(window[0], "start_time") or 0.0),
            "end_time": float(_field(window[-1], "end_time") or 0.0),
            "segment_count": len(window),
            "chunk_version": CHUNK_VERSION,
        })

        if end >= len(segs):
            break
        start = max(end - overlap, start + 1)
    return texts, metas
