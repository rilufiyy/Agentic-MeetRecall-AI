import json
from pathlib import Path

import pytest

from agent import config
from agent.llm_client import ChatClient
from agent.tools import ToolContext
from agent.workflow import run_workflow
from test_agent import ACTION_ITEMS, MID, FakeStorage, ScriptedLLM, completion, fake_retrieve, read_trace, tmp_dirs  # noqa: F401

pytestmark = pytest.mark.usefixtures("tmp_dirs")


def make(script):
    llm = ChatClient(model="openai/gpt-oss-20b", create=script)
    factory = lambda tracer, llm_: ToolContext(tracer=tracer, llm=llm_, storage=FakeStorage(), retrieve=fake_retrieve)
    return dict(ctx_factory=factory, llm=llm)


def extraction_script():
    # Every extraction call gets the same answer; enough to create a rekap with action items.
    return ScriptedLLM(completion(json.dumps(ACTION_ITEMS)))


def test_report_follows_a_fixed_order_with_no_agent_llm_loop(tmp_path):
    script = extraction_script()
    res = run_workflow(MID, "laporan", ["pdf"], **make(script))
    assert res.status == "completed" and res.iterations == 0
    assert res.tools_called == ["ekstrak_poin_meeting", "ekspor_laporan"]
    assert res.approval_id is None and "rapat - Rekap.pdf" in res.answer
    assert all(not any(m["role"] == "tool" for m in r.get("messages", [])) for r in script.requests)   # no tool-calling loop
    events = read_trace(tmp_path, res.trace_id)
    assert {e["mode"] for e in events} == {"workflow"}
    assert [e["tool"] for e in events if e["event"] == "tool_call"] == ["ekstrak_poin_meeting", "ekspor_laporan"]
    assert events[-1]["event"] == "run_end" and events[-1]["status"] == "completed"


def test_report_and_email_stops_at_the_approval_and_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("REPORT_EMAIL_TO", "pemilik@example.com")
    res = run_workflow(MID, "laporan", ["pdf", "docx"], kirim=True, **make(extraction_script()))
    assert res.status == "awaiting_approval" and res.approval_id
    assert res.tools_called == ["ekstrak_poin_meeting", "ekspor_laporan", "kirim_email_rekap"]
    assert "p***@example.com" in res.answer and "pemilik@example.com" not in res.answer
    assert not list(Path(config.OUTBOX_DIR).glob("*")) if Path(config.OUTBOX_DIR).exists() else True   # nothing was sent


def test_task_requests_approval_for_every_action_item_and_creates_nothing():
    res = run_workflow(MID, "task", **make(extraction_script()))
    assert res.status == "awaiting_approval" and res.tools_called == ["ekstrak_poin_meeting", "buat_task"]
    from agent.approvals import ApprovalStore
    store = ApprovalStore()
    assert store.tasks(MID) == []
    assert [i["id"] for i in store.get(res.approval_id)["preview"]["items"]] == ["A1", "A2"]


def test_srt_only_skips_the_llm_extraction_entirely():
    script = extraction_script()
    res = run_workflow(MID, "laporan", ["srt"], **make(script))
    assert res.status == "completed" and res.tools_called == ["ekspor_laporan"]
    assert script.requests == []                                      # no LLM call at all
    assert any(Path(config.REPORT_DIR).rglob("*.srt"))


def test_invalid_requests_are_refused_before_anything_runs():
    kw = make(extraction_script())
    with pytest.raises(ValueError):
        run_workflow(MID, "hapus", **kw)
    with pytest.raises(ValueError):
        run_workflow(MID, "laporan", ["xls"], **kw)
    with pytest.raises(ValueError):
        run_workflow(MID, "laporan", ["srt"], kirim=True, **kw)      # SRT cannot be mailed
    with pytest.raises(ValueError):
        run_workflow(MID, "task", kirim=True, **kw)


def test_a_failing_step_ends_the_run_with_a_clear_status():
    res = run_workflow("tidak-ada", "laporan", ["pdf"], **make(extraction_script()))
    assert res.status == "workflow_error" and res.tools_called == ["ekstrak_poin_meeting"]
    assert "ekstrak_poin_meeting" in res.answer
