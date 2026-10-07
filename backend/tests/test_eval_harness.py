import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import eval_harness as h  # noqa: E402


def test_harness_refuses_a_directory_without_the_eval_marker(tmp_path):
    with pytest.raises(h.EvalError):
        h.check_isolated(tmp_path)
    (tmp_path / h.MARKER).write_text("x", encoding="utf-8")
    h.check_isolated(tmp_path)   # a marked directory passes


def test_prepare_copies_data_and_marks_it_without_touching_the_source(tmp_path):
    src = tmp_path / "demo"
    (src / "meetings").mkdir(parents=True)
    (src / "meetings" / "m1.json").write_text("{}", encoding="utf-8")
    (src / "faiss").mkdir()
    (src / "meetings.json").write_text("[]", encoding="utf-8")
    (src / "sources.json").write_text("{}", encoding="utf-8")
    (src / "agent").mkdir()
    (src / "agent" / "agent.db").write_text("demo db", encoding="utf-8")   # must NOT be copied
    before = sorted(p.relative_to(src).as_posix() for p in src.rglob("*"))
    dst = tmp_path / "eval" / "data"
    info = h.prepare(src, dst)
    assert info["meetings"] == 1 and (dst / h.MARKER).exists()
    assert not (dst / "agent" / "agent.db").exists()
    assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*")) == before   # source unchanged
    with pytest.raises(h.EvalError):
        h.prepare(src, dst)   # refuses to overwrite a populated eval directory without --force


def test_scenario_file_is_consistent():
    scenarios = h.load_scenarios()
    ids = [s["id"] for s in scenarios]
    assert len(ids) == len(set(ids)) >= 20
    for s in scenarios:
        assert s["varian"] and all(v["pesan"].strip() for v in s["varian"])
        assert s["varian"][0]["prioritas"] == 1
        assert s["meeting_id"]
    assert "A-02" in ids and "MTK-01" not in ids   # the open slot is not part of the run set
    inj = next(s for s in scenarios if s["id"] == "INJ-02")
    assert inj["meeting_id"] == h.INJECTION_MEETING_ID


def test_write_scenarios_carry_a_simulated_decision_and_it03_neutral_is_priority_one():
    by_id = {s["id"]: s for s in h.load_scenarios()}
    assert {i: by_id[i]["keputusan_approval"] for i in ("W-01", "W-02", "W-03", "W-04")} == \
        {"W-01": "setuju", "W-02": "tolak", "W-03": "setuju", "W-04": "tolak"}
    assert all(not s.get("keputusan_approval") for i, s in by_id.items() if not i.startswith("W-"))
    assert [r["keputusan_approval"] for r in h.select_runs(h.load_scenarios(), ["W-02"])] == ["tolak"]
    assert [r["varian"] for r in h.select_runs(h.load_scenarios(), ["IT-03"])] == ["premis", "netral"]   # T4-D5 exception
    assert [r["varian"] for r in h.select_runs(h.load_scenarios(), ["IT-01"])] == ["premis"]


@pytest.fixture
def eval_data(tmp_path, monkeypatch):
    from agent import config
    data = tmp_path / "data"
    for name, rel in [("TRACE_DIR", "traces"), ("REKAP_DIR", "agent/rekap"), ("REPORT_DIR", "agent/laporan"), ("OUTBOX_DIR", "agent/outbox")]:
        monkeypatch.setattr(config, name, data / rel)
    monkeypatch.setattr(config, "AGENT_DB", data / "agent" / "agent.db")
    data.mkdir()
    (data / h.MARKER).write_text("x", encoding="utf-8")
    return data


def _pending_task_approval():
    from agent.tools import execute_tool
    from test_agent import ctx_with_rekap
    ctx, rekap_id = ctx_with_rekap("buatkan task untuk semua action items")
    out = execute_tool("buat_task", json.dumps({"rekap_id": rekap_id, "item_ids": ["A1", "A2"]}), ctx)
    assert out["status"] == "awaiting_approval"
    return ctx, out["approval_id"]


def test_simulated_rejection_is_verified_from_trace_and_database(eval_data):
    ctx, approval_id = _pending_task_approval()
    out = h.simulate_decision(ctx.approvals, approval_id, "tolak", eval_data)
    assert out["simulasi"] is True and out["semua_lolos"] is True
    assert len(out["verifikasi_penolakan"]) == 8 and all(c["lolos"] for c in out["verifikasi_penolakan"])
    assert out["hasil"]["status"] == "rejected"


def test_simulated_approval_records_its_side_effects_and_never_sends_email(eval_data):
    ctx, approval_id = _pending_task_approval()
    out = h.simulate_decision(ctx.approvals, approval_id, "setuju", eval_data)
    assert out["keputusan"] == "setuju" and out["efek"]["task_baru"] >= 1 and out["efek"]["eml_baru"] == []


def test_simulated_decision_refuses_bad_input_and_non_eval_directories(eval_data, tmp_path):
    ctx, approval_id = _pending_task_approval()
    with pytest.raises(h.EvalError):
        h.simulate_decision(ctx.approvals, approval_id, "mungkin", eval_data)
    with pytest.raises(h.EvalError):
        h.simulate_decision(ctx.approvals, approval_id, "tolak", tmp_path / "bukan_eval")   # no marker


def _eval_with_weekly_example(tmp_path):
    data = tmp_path / "data"
    (data / "meetings").mkdir(parents=True)
    (data / h.MARKER).write_text("x", encoding="utf-8")
    segs = [{"start_time": 0.0, "end_time": 15.0, "speaker": "Speaker 0", "text": "Halo."},
            {"start_time": 44.4, "end_time": 60.0, "speaker": "Speaker 0", "text": "Tengah."},
            {"start_time": 60.8, "end_time": 73.0, "speaker": "Speaker 1", "text": "Akhir."},
            {"start_time": 74.0, "end_time": 80.0, "speaker": "Speaker 2", "text": "Penutup."}]
    (data / "meetings" / f"{h.INJECTION_SOURCE_ID}.json").write_text(json.dumps(
        {"meeting_id": h.INJECTION_SOURCE_ID, "filename": "weekly.mp4", "duration": 98.0, "full_text": "x", "provider": "gemini",
         "created_at": "2026-01-01T00:00:00", "status": "completed", "segments": segs}), encoding="utf-8")
    (data / "meetings.json").write_text(json.dumps([{"meeting_id": h.INJECTION_SOURCE_ID, "filename": "weekly.mp4"}]), encoding="utf-8")
    (data / "sources.json").write_text("{}", encoding="utf-8")
    return data


def test_injection_meeting_is_synthetic_isolated_and_idempotent(tmp_path):
    data = _eval_with_weekly_example(tmp_path)
    info = h.create_injection_meeting(data)
    h.create_injection_meeting(data)                                       # second call must not duplicate anything
    meeting = json.loads((data / "meetings" / f"{info['meeting_id']}.json").read_text(encoding="utf-8"))
    assert info["meeting_id"] == h.INJECTION_MEETING_ID and meeting["provider"] == "sintetis"
    assert meeting["filename"].startswith("[SINTETIS]")
    inserted = [s for s in meeting["segments"] if s["text"] == h.INJECTION_TEXT]
    assert len(inserted) == 1 and inserted[0]["start_time"] == 50.0 and inserted[0]["speaker"] == "Speaker 2"
    assert len(meeting["segments"]) == 5 and [s["text"] for s in meeting["segments"] if s["text"] != h.INJECTION_TEXT] == \
        ["Halo.", "Tengah.", "Akhir.", "Penutup."]                      # other segments untouched, order by start time
    times = [s["start_time"] for s in meeting["segments"]]
    assert times == sorted(times)
    assert "attacker@example.com" in h.INJECTION_TEXT and h.INJECTION_TARGET_MEETING in h.INJECTION_TEXT
    index = json.loads((data / "meetings.json").read_text(encoding="utf-8"))
    assert [m["meeting_id"] for m in index].count(h.INJECTION_MEETING_ID) == 1
    sources = json.loads((data / "sources.json").read_text(encoding="utf-8"))
    assert sources[h.INJECTION_MEETING_ID]["sintetis"] is True and "Bukan meeting nyata" in sources[h.INJECTION_MEETING_ID]["catatan"]


def test_injection_meeting_needs_an_eval_directory(tmp_path):
    with pytest.raises(h.EvalError):
        h.create_injection_meeting(tmp_path)   # no marker


def test_workflow_specs_exist_only_for_the_comparable_scenarios():
    by_id = {s["id"]: s for s in h.load_scenarios()}
    comparable = {i for i, s in by_id.items() if s.get("workflow")}
    assert comparable == {"L-01", "L-02", "L-03", "L-04", "W-01", "W-02", "W-03", "W-04"}
    assert by_id["L-04"]["workflow"] == {"aksi": "laporan", "formats": ["srt"], "kirim": False}
    assert by_id["W-03"]["workflow"] == {"aksi": "laporan", "formats": ["pdf"], "kirim": True}
    assert by_id["W-02"]["workflow"] == {"aksi": "task"}
    runs = h.select_runs(h.load_scenarios(), ["W-04"])
    assert runs[0]["workflow"]["kirim"] is True and runs[0]["keputusan_approval"] == "tolak"
    # every workflow spec is accepted by run_workflow's own validation (no LLM is called here)
    from agent.workflow import ACTIONS, FORMATS
    for s in by_id.values():
        spec = s.get("workflow")
        if spec:
            assert spec["aksi"] in ACTIONS and set(spec.get("formats", [])) <= set(FORMATS)


def test_workflow_mode_refuses_scenarios_without_a_workflow_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / h.MARKER).write_text("x", encoding="utf-8")
    with pytest.raises(h.EvalError, match="spesifikasi workflow"):
        h.run(["P-01"], pause=0, max_priority=1, out=None, mode="workflow")


def test_quota_stops_are_told_apart_from_agent_failures():
    groq_429 = "Model tidak dapat dihubungi: Error code: 429 - Rate limit reached for model openai/gpt-oss-20b on tokens per day (TPD): Limit 200000"
    assert h.quota_stopped("llm_error", [groq_429])
    assert h.quota_stopped("tool_error", ["Tool gagal: LLMError: rate_limit_exceeded"])
    assert h.quota_stopped("harness_error", ["RateLimitError: Too Many Requests"])
    assert not h.quota_stopped("llm_error", ["Model tidak dapat dihubungi: koneksi terputus"])      # a different provider failure
    assert not h.quota_stopped("completed", [groq_429])                                              # recovered by retry: a normal run
    assert not h.quota_stopped("rejected_scope", [groq_429])
    assert not h.quota_stopped("tool_error", ["rekap_id tidak ditemukan untuk meeting ini"])        # a real agent mistake still counts


def test_code_fingerprint_changes_when_code_changes_and_not_otherwise(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "agent" / "loop.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "skenario_tahap4.json").write_text("[]", encoding="utf-8")
    first = h.code_fingerprint(tmp_path)
    assert h.code_fingerprint(tmp_path) == first and first["jumlah_berkas"] == 2
    (tmp_path / "agent" / "loop.py").write_text("a = 2\n", encoding="utf-8")
    assert h.code_fingerprint(tmp_path)["sha"] != first["sha"]
    (tmp_path / "docs.md").write_text("tidak dihitung", encoding="utf-8")     # files outside the code areas are ignored
    (tmp_path / "agent" / "loop.py").write_text("a = 1\n", encoding="utf-8")
    assert h.code_fingerprint(tmp_path) == first


def test_config_snapshot_has_no_secrets_and_a_stable_hash():
    from agent import config
    snap = h.config_snapshot(config)
    assert snap["sha"] == h.config_snapshot(config)["sha"] and snap["MAX_ITERATIONS"] == config.MAX_ITERATIONS
    assert not any("KEY" in k or "PASSWORD" in k or "TOKEN" in k.upper() for k in snap)


def test_select_runs_picks_first_variant_and_skips_unbuilt_meetings():
    runs = h.select_runs(h.load_scenarios(), ["P-01", "IT-01"])
    assert [(r["id"], r["varian"]) for r in runs] == [("P-01", "langsung"), ("IT-01", "premis")]
    assert [r["varian"] for r in h.select_runs(h.load_scenarios(), ["IT-01"], max_priority=2)] == ["premis", "netral"]
    with pytest.raises(h.EvalError):
        h.select_runs(h.load_scenarios(), ["X-99"])
