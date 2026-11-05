"""
MCP server tests: shared tool registry, write-intent guardrail, two-phase writes.
Dispatcher tests need no MCP SDK; the protocol test is skipped when `mcp` is not installed.

Run from backend/:  python -m pytest tests/test_mcp_server.py -q
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent import MID, FakeStorage, fake_retrieve, tmp_dirs  # noqa: E402,F401

from agent import mcp_server  # noqa: E402
from agent.llm_client import ChatClient  # noqa: E402
from agent.tools import TOOLS, ToolContext  # noqa: E402


def make_session():
    llm = ChatClient(model="openai/gpt-oss-20b", create=lambda **kw: None)
    factory = lambda tracer, llm_: ToolContext(tracer=tracer, llm=llm_, storage=FakeStorage(), retrieve=fake_retrieve)
    return mcp_server.McpSession(llm=llm, ctx_factory=factory)


def test_specs_come_from_the_shared_registry():
    specs = {s["name"]: s for s in mcp_server.list_specs()}
    assert set(specs) == set(TOOLS) | {mcp_server.WORKFLOW_TOOL}
    assert len(specs) == 8
    assert "approve" not in " ".join(specs).lower() and "setuju" not in " ".join(specs).lower()
    for name in ("buat_task", "kirim_email_rekap"):
        assert mcp_server.WRITE_FIELD in specs[name]["inputSchema"]["required"]
    assert mcp_server.WRITE_FIELD not in specs["statistik_meeting"]["inputSchema"].get("properties", {})


def test_read_tool_runs_through_guardrails(tmp_dirs, tmp_path):
    out = make_session().call("statistik_meeting", {"meeting_id": MID})
    assert out["status"] == "ok"
    # an unknown extra argument is still rejected by the shared validation
    bad = make_session().call("statistik_meeting", {"meeting_id": MID, "bukan_argumen": 1})
    assert bad["status"] == "invalid_args"


def test_write_tool_without_user_request_is_rejected(tmp_dirs, tmp_path):
    out = make_session().call("buat_task", {"rekap_id": "x", "item_ids": ["A1"]})
    assert out["status"] == "rejected"
    out = make_session().call("kirim_email_rekap", {"rekap_id": "x", "formats": ["pdf"], mcp_server.WRITE_FIELD: "tolong jelaskan rapatnya"})
    assert out["status"] in ("rejected", "invalid_args")


def test_write_intent_passes_then_fails_on_missing_rekap(tmp_dirs, tmp_path):
    out = make_session().call("buat_task", {"rekap_id": "tidak-ada", "item_ids": ["A1"],
                                            mcp_server.WRITE_FIELD: "buatkan task dari action items"})
    assert out["status"] == "invalid_args"   # passed the intent check, stopped at the rekap lookup


def test_mcp_run_is_traced(tmp_dirs, tmp_path):
    make_session().call("statistik_meeting", {"meeting_id": MID})
    events = [json.loads(l) for f in (tmp_path / "traces").glob("*.jsonl") for l in f.read_text(encoding="utf-8").splitlines()]
    assert {"run_start", "tool_call", "run_end"} <= {e["event"] for e in events}
    assert all(e["mode"] == "mcp" for e in events)


def test_protocol_roundtrip(tmp_dirs):
    pytest.importorskip("mcp")
    from mcp.shared.memory import create_connected_server_and_client_session


    async def go():
        async with create_connected_server_and_client_session(mcp_server.build_server(make_session())) as client:
            tools = await client.list_tools()
            res = await client.call_tool("statistik_meeting", {"meeting_id": MID})
            return tools, res

    tools, res = asyncio.run(go())
    assert len(tools.tools) == 8
    assert '"status": "ok"' in res.content[0].text


def test_workflow_tool_enforces_write_intent(tmp_dirs):
    s = make_session()
    out = s.call(mcp_server.WORKFLOW_TOOL, {"meeting_id": MID, "aksi": "task"})
    assert out["status"] == "rejected"
    out = s.call(mcp_server.WORKFLOW_TOOL, {"meeting_id": MID, "aksi": "laporan", "kirim": True, "formats": ["srt"]})
    assert out["status"] in ("rejected", "invalid_args")
    out = s.call(mcp_server.WORKFLOW_TOOL, {"meeting_id": MID, "aksi": "salah"})
    assert out["status"] == "invalid_args"


def test_workflow_srt_runs_without_llm(tmp_dirs):
    out = make_session().call(mcp_server.WORKFLOW_TOOL, {"meeting_id": MID, "aksi": "laporan", "formats": ["srt"]})
    assert out["status"] == "completed", out
    assert out["tools_dipanggil"] == ["ekspor_laporan"]
