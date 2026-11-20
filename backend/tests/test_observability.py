"""
Langfuse export (agent/observability.py): off by default, metadata only, one host, OTLP/HTTP JSON, fail-open.
HTTP is mocked: no server is needed.

Run from backend/:  python -m pytest tests/test_observability.py -q
"""
import hashlib
import hmac
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import config, observability  # noqa: E402
from agent.llm_client import ChatClient  # noqa: E402
from agent.loop import SYSTEM_PROMPT, MeetingAgent  # noqa: E402
from agent.tools import ToolContext  # noqa: E402
from test_agent import MID, FakeStorage, ScriptedLLM, completion, fake_retrieve, make_agent, read_trace  # noqa: E402

CANARY = "KANARI7f3a9"
ENV = {"LANGFUSE_ENABLED": "true", "LANGFUSE_HOST": "https://cloud.langfuse.com",
       "LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test", "LANGFUSE_HASH_SALT": "garam-uji"}
OBS = "langfuse.observation."


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(config, "REKAP_DIR", tmp_path / "rekap")
    monkeypatch.setattr(config, "AGENT_DB", tmp_path / "agent.db")
    monkeypatch.setattr(config, "REPORT_DIR", tmp_path / "laporan")
    monkeypatch.setattr(config, "OUTBOX_DIR", tmp_path / "outbox")
    monkeypatch.setattr(config, "SOURCES_FILE", tmp_path / "sources.json")
    monkeypatch.setattr(config, "EMAIL_MODE", "dry_run")
    for name in list(ENV) + ["REPORT_EMAIL_TO"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(observability, "FLUSH_INTERVAL_S", 0.05)
    observability.reset()
    yield tmp_path
    observability.reset()


class FakeHTTP:
    """Replaces OpenerDirector.open: records every request; fails when `fail` is set."""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def __call__(self, *args, timeout=None):
        req = args[-1]          # an instance set as a class attribute is not bound: called as (req, timeout=)
        self.calls.append({"url": req.full_url, "headers": {k.lower(): v for k, v in req.header_items()},
                           "body": json.loads(req.data.decode("utf-8"))})
        if self.fail:
            raise OSError("connection refused")

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Resp()

    def resources(self):
        return [rs["resource"] for c in self.calls for rs in c["body"]["resourceSpans"]]

    def spans(self):
        return [s for c in self.calls for rs in c["body"]["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]


def attrs(span):
    out = {}
    for a in span["attributes"]:
        v = a["value"]
        out[a["key"]] = [x["stringValue"] for x in v["arrayValue"]["values"]] if "arrayValue" in v else v["stringValue"]
    return out


def enable(monkeypatch, fake):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake)


def scenario():
    """Covers every field that must stay local: user text, tool arguments and output, LLM error text,
    guardrail detail (an invented quote) and the final answer, each carrying the canary."""
    return ScriptedLLM(
        RuntimeError(f"rate limit {CANARY}"),
        completion(tool_calls=[("cari_transkrip", {"meeting_id": MID, "query": f"keputusan rilis {CANARY}"})]),
        completion(f'Jawaban: "{CANARY} kutipan karangan" (Speaker 0, 00:10).'),
    )


def run(script):
    return make_agent(script).run(f"Apa keputusan soal rilis? {CANARY}", MID)


def comparable(events):
    drop = {"ts", "trace_id", "latency_ms", "total_latency_ms"}
    return [{k: v for k, v in e.items() if k not in drop} for e in events]


def assert_hierarchy(spans):
    ids = {s["spanId"] for s in spans}
    parents = [s["parentSpanId"] for s in spans if "parentSpanId" in s]
    assert all(p in ids for p in parents), "every parentSpanId must match a span that was sent"


# Off by default, one host

def test_flag_off_starts_nothing_and_sends_nothing(monkeypatch, tmp_path):
    fake = FakeHTTP()
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake)
    res = run(scenario())
    assert res.status == "completed"
    assert observability._state is None
    assert not [t for t in threading.enumerate() if t.name == "langfuse-export"]
    assert fake.calls == []
    assert read_trace(tmp_path, res.trace_id)          # the local trace is still written


@pytest.mark.parametrize("host", ["", "http://cloud.langfuse.com", "https://us.cloud.langfuse.com",
                                  "https://jp.cloud.langfuse.com", "https://cloud.langfuse.com.evil.example",
                                  "http://127.0.0.1:3000"])
def test_only_eu_cloud_host_is_accepted(monkeypatch, host):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    monkeypatch.setenv("LANGFUSE_HOST", host)
    run(scenario())
    assert observability._state is None and fake.calls == []


def test_missing_salt_disables_export(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    monkeypatch.delenv("LANGFUSE_HASH_SALT")
    run(scenario())
    assert observability._state is None and fake.calls == []


# Metadata only

def test_request_is_otlp_json_with_ingestion_version_4(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    run(scenario())
    observability.flush(5)
    call = fake.calls[0]
    assert call["url"] == "https://cloud.langfuse.com/api/public/otel/v1/traces"
    assert call["headers"]["content-type"] == "application/json"
    assert call["headers"]["x-langfuse-ingestion-version"] == "4"
    assert call["headers"]["authorization"].startswith("Basic ")


def test_every_attribute_is_allowlisted_and_no_text_leaves(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    res = run(scenario())
    observability.flush(5)
    spans = fake.spans()
    assert res.status == "completed" and spans

    # Resource: service.name only (no host.name, process.*, os.*, user name or path).
    for resource in fake.resources():
        assert [a["key"] for a in resource["attributes"]] == ["service.name"]
        assert resource["attributes"][0]["value"] == {"stringValue": observability.SERVICE_NAME}

    forbidden = {"pesan_user", "jawaban", "argumen", "ringkasan_output", "detail", "error", "pertanyaan"}
    for span in spans:
        assert set(span) <= {"traceId", "spanId", "parentSpanId", "name", "kind", "startTimeUnixNano",
                             "endTimeUnixNano", "attributes", "status"}
        assert set(span["status"]) == {"code"}                      # no status.message text
        for a in span["attributes"]:
            assert a["key"] in observability.ALLOWED_ATTRIBUTE_KEYS, a["key"]
            assert not set(a["key"].split(".")) & forbidden, a["key"]
            assert not a["key"].startswith((OBS + "input", OBS + "output", "langfuse.trace.input",
                                            "langfuse.trace.output"))

    raw = json.dumps([c["body"] for c in fake.calls], ensure_ascii=False)
    assert CANARY not in raw                     # user text, tool args/output, answer, guardrail detail
    assert "rate limit" not in raw               # LLM error message
    assert "Selamat pagi" not in raw and "Speaker 1:" not in raw   # transcript text from the tool result
    types = {attrs(s).get("langfuse.observation.type") for s in spans}
    assert {"span", "generation", "event"} <= types


def test_generation_carries_model_usage_cost_and_prompt_identity(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    run(scenario())
    observability.flush(5)
    gens = [attrs(s) for s in fake.spans() if attrs(s).get("langfuse.observation.type") == "generation"]
    ok = [g for g in gens if g.get(OBS + "level") != "ERROR"]
    digest = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert ok
    for g in ok:
        assert g[OBS + "model.name"] == "openai/gpt-oss-20b"
        assert json.loads(g[OBS + "usage_details"]) == {"input": 100, "output": 20}
        assert json.loads(g[OBS + "cost_details"])["total"] == pytest.approx((100 * 0.075 + 20 * 0.30) / 1e6)
        assert g[OBS + "metadata.prompt_nama"] == "agent.loop.SYSTEM_PROMPT"
        assert g[OBS + "metadata.prompt_sha256"] == digest
        assert g[OBS + "metadata.prompt_versi"] == digest[:12]
    assert "MeetRecall Agent, asisten" not in json.dumps(gens, ensure_ascii=False)


def test_session_id_is_hmac_of_meeting_id_on_every_span(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    run(scenario())
    observability.flush(5)
    expected = hmac.new(b"garam-uji", MID.encode(), hashlib.sha256).hexdigest()[:16]
    for span in fake.spans():
        a = attrs(span)
        assert a["langfuse.session.id"] == expected
        assert not any("user" in k for k in a)
    assert f'"{MID}"' not in json.dumps([c["body"] for c in fake.calls])


# statusMessage

def test_status_message_is_error_class_or_status_never_text():
    base = {"trace_id": "t" * 32, "step": 1, "ts": "2026-11-19T07:00:00.000+00:00", "meeting_id": "m",
            "mode": "agent", "scenario_id": None, "latency_ms": 10.0}
    llm = attrs(observability.child_span({**base, "event": "llm_call", "tujuan": "agent", "model": "x",
                                          "status": "error", "error": f"RateLimitError: kuota habis {CANARY}"}, None, "s"))
    assert llm[OBS + "level"] == "ERROR" and llm[OBS + "status_message"] == "RateLimitError"
    odd = attrs(observability.child_span({**base, "event": "llm_call", "tujuan": "agent", "status": "error",
                                          "error": f"kuota habis {CANARY}"}, None, "s"))
    assert odd[OBS + "status_message"] == "error"
    tool = attrs(observability.child_span({**base, "event": "tool_call", "tool": "cari_transkrip",
                                           "status": "invalid_args", "error": f"Argumen tidak valid {CANARY}"}, None, "s"))
    assert tool[OBS + "level"] == "ERROR" and tool[OBS + "status_message"] == "invalid_args"
    assert CANARY not in json.dumps([llm, odd, tool])


# Root span and hierarchy

def test_completed_run_has_one_root_and_every_parent_exists(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    res = run(scenario())
    observability.flush(5)
    spans = fake.spans()
    roots = [s for s in spans if "parentSpanId" not in s]
    assert len(roots) == 1
    root = attrs(roots[0])
    assert roots[0]["traceId"] == res.trace_id and roots[0]["status"] == {"code": 1}
    assert root["langfuse.trace.metadata.selesai"] == "true"
    assert root["langfuse.trace.metadata.status"] == "completed"
    assert OBS + "level" not in root
    assert_hierarchy(spans)
    assert {s["traceId"] for s in spans} == {res.trace_id}


class BrokenStorage(FakeStorage):
    def load_meeting(self, meeting_id):
        raise RuntimeError(f"disk penuh {CANARY}")


def broken_agent():
    llm = ChatClient(model="openai/gpt-oss-20b", create=ScriptedLLM(completion("x")))
    factory = lambda tracer, llm_: ToolContext(tracer=tracer, llm=llm_, storage=BrokenStorage(), retrieve=fake_retrieve)
    return MeetingAgent(llm=llm, ctx_factory=factory)


def unfinished_root(spans):
    roots = [s for s in spans if "parentSpanId" not in s]
    assert len(roots) == 1
    a = attrs(roots[0])
    assert roots[0]["status"] == {"code": 2}
    assert a[OBS + "level"] == "ERROR" and a[OBS + "status_message"] == "run_tidak_selesai"
    assert a["langfuse.trace.metadata.selesai"] == "false"
    return roots[0]


def test_run_that_raises_gets_error_root_after_idle_timeout(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    monkeypatch.setattr(observability, "RUN_IDLE_TIMEOUT_S", 0.0)
    with pytest.raises(RuntimeError):
        broken_agent().run("Apa keputusan soal rilis?", MID)
    observability._state.close_stale()
    observability.flush(5)
    spans = fake.spans()
    unfinished_root(spans)
    assert_hierarchy(spans)
    assert CANARY not in json.dumps([c["body"] for c in fake.calls])


def test_run_that_raises_gets_error_root_at_exit_flush(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    with pytest.raises(RuntimeError):
        broken_agent().run("Apa keputusan soal rilis?", MID)
    exporter = observability._state
    assert exporter.runs                                   # still open: no run_end, not idle long enough
    exporter.close()                                       # what atexit calls
    spans = fake.spans()
    unfinished_root(spans)
    assert_hierarchy(spans)
    assert not exporter.runs


def test_late_events_after_idle_timeout_never_send_a_second_root(monkeypatch):
    fake = FakeHTTP()
    enable(monkeypatch, fake)
    exporter = observability._exporter()
    tid = "c" * 32
    base = {"trace_id": tid, "meeting_id": MID, "mode": "agent", "scenario_id": None}
    exporter.handle({**base, "step": 1, "event": "run_start", "ts": "2026-11-20T07:00:00.000+00:00", "model": "m"})
    exporter.handle({**base, "step": 2, "event": "tool_call", "ts": "2026-11-20T07:00:01.000+00:00",
                     "tool": "statistik_meeting", "status": "ok", "latency_ms": 5.0})
    monkeypatch.setattr(observability, "RUN_IDLE_TIMEOUT_S", 0.0)
    assert exporter.close_stale() == 1                         # timeout: ERROR root sent
    monkeypatch.setattr(observability, "RUN_IDLE_TIMEOUT_S", 600.0)
    exporter.handle({**base, "step": 3, "event": "llm_call", "ts": "2026-11-20T07:11:00.000+00:00", "tujuan": "agent",
                     "model": "m", "status": "ok", "input_tokens": 1, "output_tokens": 1, "latency_ms": 5.0})
    exporter.handle({**base, "step": 4, "event": "run_end", "ts": "2026-11-20T07:11:01.000+00:00",
                     "status": "completed", "jawaban": CANARY})
    exporter.flush(5)
    spans = fake.spans()
    root_id = observability.span_id(tid, "root")
    assert [s["spanId"] for s in spans].count(root_id) == 1    # root sent once only
    assert len([s for s in spans if "parentSpanId" not in s]) == 1
    late = [s for s in spans if s["name"] == "run_end_terlambat"]
    assert len(late) == 1 and late[0]["parentSpanId"] == root_id
    a = attrs(late[0])
    assert a["langfuse.observation.type"] == "event" and a[OBS + "level"] == "WARNING"
    assert a[OBS + "metadata.status"] == "completed"
    assert_hierarchy(spans)
    assert CANARY not in json.dumps(spans) and tid not in exporter.closed


# Fail-open

def test_circuit_breaker_opens_after_five_failures_then_half_opens(monkeypatch):
    fake = FakeHTTP(fail=True)
    enable(monkeypatch, fake)
    exporter = observability._exporter()
    span = {"traceId": "a" * 32, "spanId": "b" * 16, "name": "x", "kind": 1, "startTimeUnixNano": "1",
            "endTimeUnixNano": "2", "attributes": [], "status": {"code": 1}}
    for _ in range(observability.BREAKER_FAILURES + 3):
        exporter.put(span)
        exporter.flush(2)
    assert len(fake.calls) == observability.BREAKER_FAILURES      # later batches dropped while open
    assert exporter.open_until > 0

    fake.fail = False
    exporter.open_until = 0.0                                       # cooldown elapsed: one batch is tried
    exporter.put(span)
    exporter.flush(2)
    assert len(fake.calls) == observability.BREAKER_FAILURES + 1 and exporter.failures == 0


def test_server_down_keeps_run_and_local_trace_unchanged(monkeypatch, tmp_path):
    off_script = scenario()
    off = run(off_script)
    off_events = comparable(read_trace(tmp_path, off.trace_id))

    observability.reset()
    enable(monkeypatch, FakeHTTP(fail=True))
    on_script = scenario()
    on = run(on_script)
    on_events = comparable(read_trace(tmp_path, on.trace_id))

    assert (on.status, on.answer, on.tools_called, on.iterations) == (off.status, off.answer, off.tools_called, off.iterations)
    assert on_events == off_events                               # JSONL identical apart from ids, times, latency
    assert on_script.requests == off_script.requests             # same prompts and parameters sent to the model
