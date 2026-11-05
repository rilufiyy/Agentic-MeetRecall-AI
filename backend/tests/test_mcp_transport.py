"""
End-to-end MCP transport: the agent loop and the workflow reach their tools through MCP (tools/list, tools/call)
and behave like the local path. Needs the `mcp` SDK; skipped without it.

Run from backend/:  python -m pytest tests/test_mcp_transport.py -q
"""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent import (ACTION_ITEMS, MID, FakeStorage, ScriptedLLM, completion, fake_retrieve,  # noqa: E402,F401
                        make_agent, read_trace, tmp_dirs)

from agent import config, mcp_client  # noqa: E402
from agent.llm_client import ChatClient  # noqa: E402
from agent.tools import ToolContext, tool_specs  # noqa: E402
from agent.workflow import run_workflow  # noqa: E402


@pytest.fixture
def mcp_on(monkeypatch):
    monkeypatch.setattr(config, "TOOL_TRANSPORT", "mcp")


def test_llm_specs_discovered_over_mcp_match_the_local_registry(mcp_on):
    assert mcp_client.agent_specs() == tool_specs()   # same names, descriptions and schemas; no host fields leak
    names = [s["function"]["name"] for s in mcp_client.agent_specs()]
    assert "jalankan_workflow" not in names and len(names) == 7


def test_loop_over_mcp_extracts_then_stops_at_approval(mcp_on, tmp_dirs, tmp_path):
    script = ScriptedLLM(
        completion(tool_calls=[("ekstrak_poin_meeting", {"meeting_id": MID, "jenis": "action_items"})]),
        completion(json.dumps(ACTION_ITEMS)),   # the extraction call inside the tool
    )
    agent = make_agent(script)
    first = agent.run("Tolong ekstrak action items", MID)
    assert first.status == "completed" or first.status == "max_iterations" or first.rekap_id
    rekap_id = first.rekap_id
    assert rekap_id and first.tools_called[0] == "ekstrak_poin_meeting"

    script2 = ScriptedLLM(completion(tool_calls=[("buat_task", {"rekap_id": rekap_id, "item_ids": ["A1"]})]))
    res = make_agent(script2).run("Buatkan task untuk A1", MID, rekap_id=rekap_id)
    assert res.status == "awaiting_approval" and res.approval_id
    assert "Menunggu persetujuan" in res.answer
    events = read_trace(tmp_path, res.trace_id)
    kinds = [e["event"] for e in events]
    assert "mcp_call" in kinds and "tool_call" in kinds   # same trace holds the transport and the tool result
    assert next(e for e in events if e["event"] == "run_start")["transport"] == "mcp"


def test_guardrails_still_apply_over_mcp(mcp_on, tmp_dirs):
    # write intent: the user only asked a question, so the model's buat_task call is refused by code
    script = ScriptedLLM(completion(tool_calls=[("buat_task", {"rekap_id": "x", "item_ids": ["A1"]})]),
                         completion("Baik."))
    res = make_agent(script).run("Jelaskan isi rapat ini", MID)
    tool_msg = next(m for m in script.requests[1]["messages"] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["status"] == "rejected"
    assert res.status in ("completed", "tool_error")
    # meeting scope: a meeting_id other than the active one is refused
    script = ScriptedLLM(completion(tool_calls=[("cari_transkrip", {"meeting_id": "m2", "query": "rilis"})]),
                         completion("Baik."))
    make_agent(script).run("Apa yang dibahas soal rilis?", MID)
    tool_msg = next(m for m in script.requests[1]["messages"] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["status"] == "invalid_args"


def test_transcript_comes_back_as_tagged_data_over_mcp(mcp_on, tmp_dirs):
    script = ScriptedLLM(completion(tool_calls=[("cari_transkrip", {"meeting_id": MID, "query": "rilis"})]),
                         completion("Rilis dibahas."))
    make_agent(script).run("Apa yang dibahas soal rilis?", MID)
    content = next(m for m in script.requests[1]["messages"] if m["role"] == "tool")["content"]
    assert content.count("<transkrip_data>") == 1 and content.rstrip().endswith("</transkrip_data>")
    assert "Ignore previous instructions" not in content.split("<transkrip_data>")[0]


def test_workflow_runs_over_mcp(mcp_on, tmp_dirs, tmp_path):
    llm = ChatClient(create=ScriptedLLM(completion(json.dumps(ACTION_ITEMS))))
    factory = lambda tr, lm: ToolContext(tracer=tr, llm=lm, storage=FakeStorage(), retrieve=fake_retrieve)
    res = run_workflow(MID, "laporan", ["srt"], ctx_factory=factory, llm=llm)
    assert res.status == "completed" and res.tools_called == ["ekspor_laporan"]
    assert any(e["event"] == "mcp_call" for e in read_trace(tmp_path, res.trace_id))
