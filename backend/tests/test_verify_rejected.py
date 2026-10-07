import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import verify_approval_rejected as v  # noqa: E402
from agent import approvals, config  # noqa: E402
from agent.tools import execute_tool  # noqa: E402
from test_agent import MID, ctx_with_rekap  # noqa: E402


@pytest.fixture
def data_layout(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for name, rel in [("TRACE_DIR", "traces"), ("REKAP_DIR", "agent/rekap"), ("REPORT_DIR", "agent/laporan"),
                      ("OUTBOX_DIR", "agent/outbox")]:
        monkeypatch.setattr(config, name, data / rel)
    monkeypatch.setattr(config, "AGENT_DB", data / "agent" / "agent.db")
    return data


def _pending_task_approval():
    ctx, rekap_id = ctx_with_rekap("buatkan task untuk semua action items")
    out = execute_tool("buat_task", json.dumps({"rekap_id": rekap_id, "item_ids": ["A1", "A2"]}), ctx)
    assert out["status"] == "awaiting_approval"
    return ctx, out["approval_id"]


def test_verifier_passes_after_a_clean_rejection(data_layout):
    ctx, approval_id = _pending_task_approval()
    baseline = v.snapshot(data_layout)
    approvals.decide(ctx.approvals, approval_id, setuju=False, trace_dir=data_layout / "traces")
    results = v.verify(data_layout, approval_id, baseline)
    assert all(ok for _, ok, _ in results), [r for r in results if not r[1]]
    assert len(results) == 8


def test_verifier_fails_when_the_approval_was_executed_instead(data_layout):
    ctx, approval_id = _pending_task_approval()
    baseline = v.snapshot(data_layout)
    from test_agent import FakeStorage
    approvals.decide(ctx.approvals, approval_id, setuju=True, isian={"A2": {"penanggung_jawab": "Budi"}},
                     rekaps=ctx.rekaps, storage=FakeStorage(), trace_dir=data_layout / "traces")
    failed = {name for name, ok, _ in v.verify(data_layout, approval_id, baseline) if not ok}
    assert {"status ditolak di database", "trace mencatat keputusan tolak", "trace tanpa eksekusi tool", "jumlah task sama"} <= failed


def test_verifier_fails_while_the_approval_is_still_pending(data_layout):
    ctx, approval_id = _pending_task_approval()
    baseline = v.snapshot(data_layout)
    failed = {name for name, ok, _ in v.verify(data_layout, approval_id, baseline) if not ok}
    assert "status ditolak di database" in failed and "trace mencatat keputusan tolak" in failed
