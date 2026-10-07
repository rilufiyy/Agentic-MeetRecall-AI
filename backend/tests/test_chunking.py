"""
Unit tests for segment chunking and meeting-wide question routing.

Run from backend/:  python -m pytest tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.chunking import CHUNK_VERSION, build_chunks  # noqa: E402


def _seg(i, speaker, words):
    return {"speaker": speaker, "start_time": float(i), "end_time": i + 0.9,
            "text": " ".join(f"w{i}_{j}" for j in range(words))}


def test_segments_are_merged_up_to_target_words():
    segs = [_seg(i, f"Speaker {i % 2}", 10) for i in range(12)]
    texts, metas = build_chunks(segs, target_words=30, overlap=0)
    assert len(texts) == 4
    assert all(m["segment_count"] == 3 for m in metas)
    assert metas[0]["speaker"] == "Speaker 0, Speaker 1"
    assert metas[1]["start_time"] == 3.0 and metas[1]["end_time"] == 5.9
    assert texts[0].split("\n")[0].startswith("Speaker 0: w0_0")


def test_overlap_repeats_boundary_segment():
    segs = [_seg(i, "Speaker 1", 10) for i in range(6)]
    texts, _ = build_chunks(segs, target_words=30, overlap=1)
    assert texts[0].split("\n")[-1] == texts[1].split("\n")[0]
    assert texts[-1].endswith("w5_9")          # nothing is dropped at the end


def test_long_segment_is_its_own_chunk_and_empty_ones_are_skipped():
    segs = [_seg(0, "A", 100), {"speaker": "B", "start_time": 1, "end_time": 2, "text": "  "},
            _seg(2, "C", 5)]
    texts, metas = build_chunks(segs, target_words=30, overlap=1)
    assert len(texts) == 2
    assert metas[0]["segment_count"] == 1
    assert all(m["chunk_version"] == CHUNK_VERSION for m in metas)


def test_meeting_wide_questions_are_detected():
    import pytest
    rag_chain = pytest.importorskip("services.rag_chain")  # needs the full backend deps
    for q in ["what were the main decisions in this meeting?", "Apa keputusan utama?",
              "Apa saja action item dan tenggatnya?", "Ringkas meeting ini",
              "Siapa yang bertanggung jawab atas tindak lanjutnya?"]:
        assert rag_chain.is_meeting_wide(q), q
    for q in ["Berapa target p95 untuk MR-218?", "Who is John Smith?"]:
        assert not rag_chain.is_meeting_wide(q), q
