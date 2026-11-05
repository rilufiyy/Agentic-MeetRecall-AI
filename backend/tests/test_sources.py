"""
References ("Sumber") shown under agent answers: built by code from tool results, deduplicated, and identical
over the local and MCP transports.

Run from backend/:  python -m pytest tests/test_sources.py -q
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent import ACTION_ITEMS, CHUNKS, MID, ScriptedLLM, completion, make_agent, tmp_dirs  # noqa: E402,F401

from agent import config, guardrails  # noqa: E402


@pytest.fixture(params=["local", "mcp"])
def transport(request, monkeypatch):
    if request.param == "mcp":
        pytest.importorskip("mcp")
    monkeypatch.setattr(config, "TOOL_TRANSPORT", request.param)
    return request.param


def test_search_answer_carries_transcript_sources(transport, tmp_dirs):
    script = ScriptedLLM(completion(tool_calls=[("cari_transkrip", {"meeting_id": MID, "query": "rilis"})]),
                         completion("Rilis dibahas."))
    res = make_agent(script).run("Apa yang dibahas soal rilis?", MID)
    assert res.status == "completed" and res.sources
    src = res.sources[0]
    assert src["jenis"] == "transkrip" and src["mulai"] and src["selesai"] and src["speaker"]
    known = {c["chunk_id"]: c["text"] for c in CHUNKS}
    assert all(s["teks"] == known[s["chunk_id"]][:600] for s in res.sources)   # text comes from the index, not the LLM
    assert len({s["chunk_id"] for s in res.sources}) == len(res.sources)       # no duplicates


def test_extraction_sources_are_verified_items(transport, tmp_dirs):
    script = ScriptedLLM(completion(tool_calls=[("ekstrak_poin_meeting", {"meeting_id": MID, "jenis": "action_items"})]),
                         completion(json.dumps(ACTION_ITEMS)), completion("Ada dua action item."))
    res = make_agent(script).run("Tolong ekstrak action items", MID)
    items = [s for s in res.sources if s["jenis"] == "butir"]
    assert items and all(s["butir"] == "action_items" and s["id"].startswith("A") for s in items)
    transcript = " ".join(c["text"] for c in CHUNKS)
    assert all(guardrails.quote_in_text(s["kutipan"], transcript) for s in items)


def test_no_sources_for_statistics_only(transport, tmp_dirs):
    script = ScriptedLLM(completion(tool_calls=[("statistik_meeting", {"meeting_id": MID})]), completion("Selesai."))
    assert make_agent(script).run("Tampilkan statistik pembicara", MID).sources == []


def test_answer_quotes_mark_their_sources_and_flag_invented_ones(transport, tmp_dirs):
    real = "Saya akan menyiapkan dokumen rilis sebelum 12 Oktober"
    answer = f'Speaker 1 berjanji: "{real}". Ia juga bilang "anggaran naik dua kali lipat bulan ini".'
    script = ScriptedLLM(completion(tool_calls=[("cari_transkrip", {"meeting_id": MID, "query": "dokumen rilis"})]),
                         completion(answer))
    res = make_agent(script).run("Siapa yang menyiapkan dokumen rilis?", MID)
    v = res.verifikasi
    assert (v["kutipan_total"], v["kutipan_tidak_ditemukan"], v["sumber_dikutip"]) == (2, 1, 1)
    assert [k["ditemukan"] for k in v["kutipan"]] == [True] and v["atribusi_dikoreksi"] == 0   # only the real quote is located
    cited = [s for s in res.sources if s["dikutip"]]
    assert len(cited) == 1 and real.lower() in cited[0]["teks"].lower()
    assert "tidak ditemukan persis" in res.answer   # the invented quote is flagged in the answer text too
