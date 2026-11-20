"""
Optional export of trace metadata to Langfuse Cloud, EU region (docs/14_observability_langfuse.md).

The local JSONL trace (agent/tracing.py) stays the source of truth. Tracer.log calls forward(record)
after the line is written; this module turns an allowlisted subset of the record into OpenTelemetry spans.

Rules:
  - Off unless LANGFUSE_ENABLED=true. Off means no thread, no network, no change in behaviour.
  - Metadata only. Text the user typed, model answers, tool arguments and outputs, guardrail details
    and error messages are never sent: each event type has an allowlist applied before a span is built,
    and every attribute key must be in ALLOWED_ATTRIBUTE_KEYS. Prompts are identified by name and SHA-256.
    The only resource attribute is service.name (no host, process, OS, user name or path).
  - One host only. LANGFUSE_HOST must be exactly ALLOWED_HOST (https://cloud.langfuse.com); there is no
    default, so a missing or different value disables the export instead of sending anywhere else.
  - Fail-open. Bounded queue, background thread, short HTTP timeout, circuit breaker. Nothing here
    raises into the caller, and a down server never slows a run.
  - The meeting_id is sent as an HMAC-SHA256 with LANGFUSE_HASH_SALT (session id). There is no user
    identity in this API, so no user id is sent.

Trace shape: a run (run_start ... run_end) becomes one root span sent at run_end; every other event of the
run is a child of that root. A run that never logs run_end (an exception, a killed request) gets its root
span with level ERROR after RUN_IDLE_TIMEOUT_S without events, or at interpreter exit. Events that arrive
after that stay children of the same root; a late run_end becomes an event, never a second root. Events of a trace
that has no run_start (approval decisions, transcription jobs) are sent as root spans of their own.

Transport: OTLP/HTTP JSON, POST {host}/api/public/otel/v1/traces, basic auth with the project keys,
header x-langfuse-ingestion-version: 4. Standard library only, proxies disabled.
Attribute names: https://langfuse.com/integrations/native/opentelemetry (property mapping).
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

QUEUE_MAX = 1000              # spans waiting to be sent; new spans are dropped when full
BATCH_MAX = 50                # spans per HTTP request
FLUSH_INTERVAL_S = 2.0        # a partial batch is sent after this long
HTTP_TIMEOUT_S = 2.0
BREAKER_FAILURES = 5          # consecutive failed requests that open the circuit
BREAKER_COOLDOWN_S = 60.0     # while open, batches are dropped; then one batch is tried (half-open)
SHUTDOWN_FLUSH_S = 2.0        # max time spent sending the rest at interpreter exit
RUN_IDLE_TIMEOUT_S = 600.0    # a run with no event for this long and no run_end is closed as an error
CLOSED_RUNS_MAX = 1000        # runs closed by the timeout that are remembered for late events

# Langfuse Cloud, EU region only (see docs/14_observability_langfuse.md). Exact match, https only.
ALLOWED_HOST = "https://cloud.langfuse.com"
OTLP_PATH = "/api/public/otel/v1/traces"
SERVICE_NAME = "meetrecall-agent"
SCOPE_NAME = "meetrecall.agent"

# Fields copied per event type. Anything not listed is never sent.
_ALLOW = {
    "run_start": ("mode", "scenario_id", "model", "max_iterasi", "tools", "transport", "sumber", "aksi",
                  "formats", "kirim"),
    "run_end": ("status", "jumlah_iterasi", "tools_dipanggil", "total_latency_ms", "jumlah_llm_call",
                "llm_call_gagal", "total_input_tokens", "total_output_tokens", "total_biaya_usd"),
    "llm_call": ("tujuan", "iterasi", "status", "finish_reason", "tool_calls_diminta"),
    "tool_call": ("tool", "iterasi", "status", "fase"),
    "mcp_call": ("tool", "iterasi", "status"),
    "guardrail": ("nama", "hasil"),
    "approval": ("tool", "keputusan_user"),
}
# Never sent, whatever the event type.
FORBIDDEN = frozenset({"pesan_user", "jawaban", "argumen", "ringkasan_output", "detail", "error", "pertanyaan"})
_PROMPT_KEYS = ("prompt_nama", "prompt_versi", "prompt_sha256")
_EXTRA_META = ("trace_id_lokal", "mode", "scenario_id")
_RUN_END_ERROR = {"llm_error", "tool_error"}
_RUN_END_WARNING = {"max_iterations"}

_OBS = "langfuse.observation."
ALLOWED_ATTRIBUTE_KEYS = frozenset(
    {"langfuse.observation.type", "langfuse.trace.name", "langfuse.trace.tags", "langfuse.session.id",
     _OBS + "model.name", _OBS + "usage_details", _OBS + "cost_details", _OBS + "model.parameters",
     _OBS + "level", _OBS + "status_message"}
    | {_OBS + "metadata." + k for ev in ("llm_call", "tool_call", "mcp_call", "guardrail", "approval", "run_end")
       for k in _ALLOW[ev]}
    | {_OBS + "metadata." + k for k in _PROMPT_KEYS + _EXTRA_META}
    | {"langfuse.trace.metadata." + k for k in _ALLOW["run_start"] + _ALLOW["run_end"] + ("trace_id_lokal", "selesai")}
)
assert not any(k.rsplit(".", 1)[-1] in FORBIDDEN for k in ALLOWED_ATTRIBUTE_KEYS)

_lock = threading.Lock()
_state: Optional["_Exporter"] = None
_disabled = False


def _env_true(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _settings() -> Optional[Dict[str, str]]:
    """Validated settings, or None (export off). Logged once when on but misconfigured."""
    if not _env_true("LANGFUSE_ENABLED"):
        return None
    host = (os.getenv("LANGFUSE_HOST") or "").strip().rstrip("/")
    pk, sk = os.getenv("LANGFUSE_PUBLIC_KEY") or "", os.getenv("LANGFUSE_SECRET_KEY") or ""
    salt = os.getenv("LANGFUSE_HASH_SALT") or ""
    if host != ALLOWED_HOST:
        logger.warning("Langfuse export off: LANGFUSE_HOST must be %s.", ALLOWED_HOST)
        return None
    if not (pk and sk and salt):
        logger.warning("Langfuse export off: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HASH_SALT are required.")
        return None
    return {"host": host, "public_key": pk, "secret_key": sk, "salt": salt}


# Prompt identity

_prompt_cache: Dict[str, Dict[str, str]] = {}


def _prompt_identity(purpose: Optional[str]) -> Dict[str, str]:
    """Name, short version and SHA-256 of the static system prompt used for this purpose. No text."""
    key = "agent" if purpose == "agent" else ("ekstrak" if (purpose or "").startswith("ekstrak_poin_meeting") else None)
    if key is None:
        return {}
    if key not in _prompt_cache:
        # Imported here, not at module load: agent.loop and agent.tools import agent.tracing, which imports this.
        if key == "agent":
            from agent.loop import SYSTEM_PROMPT as text
            name = "agent.loop.SYSTEM_PROMPT"
        else:
            from agent.tools import _EXTRACT_SYSTEM as text
            name = "agent.tools._EXTRACT_SYSTEM"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _prompt_cache[key] = {"prompt_nama": name, "prompt_versi": digest[:12], "prompt_sha256": digest}
    return _prompt_cache[key]


# Ids, times, attribute values

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def otel_trace_id(trace_id: str) -> str:
    return trace_id if _HEX32.match(trace_id) else hashlib.sha256(trace_id.encode()).hexdigest()[:32]


def span_id(trace_id: str, part: Any) -> str:
    return hashlib.sha256(f"{trace_id}:{part}".encode()).hexdigest()[:16]


def _nanos(ts: Optional[str]) -> int:
    try:
        return int(datetime.fromisoformat(ts).timestamp() * 1_000_000_000)
    except (TypeError, ValueError):
        return time.time_ns()


def _session_id(meeting_id: Any, salt: str) -> Optional[str]:
    if not meeting_id:
        return None
    return hmac.new(salt.encode(), str(meeting_id).encode(), hashlib.sha256).hexdigest()[:16]


def _error_class(record: Dict) -> Optional[str]:
    """'RateLimitError: ...' -> 'RateLimitError'. Only the exception class name, never the message."""
    text = record.get("error")
    if not text or ":" not in str(text):
        return None
    name = str(text).split(":", 1)[0].strip()
    return name if name.isidentifier() else None


def _meta_value(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)


def _attributes(pairs: Dict[str, Any]) -> List[Dict]:
    """OTLP attribute list. Keys outside ALLOWED_ATTRIBUTE_KEYS and None values are dropped."""
    out = []
    for key, value in pairs.items():
        if value is None or key not in ALLOWED_ATTRIBUTE_KEYS:
            continue
        if key == "langfuse.trace.tags":          # the only array attribute; metadata lists go as JSON strings
            any_value = {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}
        else:
            any_value = {"stringValue": _meta_value(value)}
        out.append({"key": key, "value": any_value})
    return out


def _pick(record: Dict, event: str) -> Dict[str, Any]:
    return {k: record[k] for k in _ALLOW.get(event, ()) if k in record and record[k] is not None}


# Spans

class _Run:
    """What the root span of an open run needs, kept from run_start."""

    def __init__(self, record: Dict, salt: str) -> None:
        self.trace_id = str(record["trace_id"])
        self.start_ns = _nanos(record.get("ts"))
        self.mode = record.get("mode")
        self.scenario_id = record.get("scenario_id")
        self.session = _session_id(record.get("meeting_id"), salt)
        self.start_meta = _pick(record, "run_start")
        self.last_seen = time.monotonic()


def _trace_attrs(trace_id: str, mode: Any, scenario_id: Any, session: Optional[str]) -> Dict[str, Any]:
    """Trace-wide attributes, put on every span so they stay queryable."""
    attrs: Dict[str, Any] = {"langfuse.trace.name": f"meetrecall.{mode}",
                             "langfuse.trace.tags": [t for t in (mode, scenario_id) if t] or None,
                             "langfuse.session.id": session}
    if not _HEX32.match(trace_id):
        attrs[_OBS + "metadata.trace_id_lokal"] = trace_id
    return attrs


def _span(trace_id: str, sid: str, parent: Optional[str], name: str, start_ns: int, end_ns: int,
          attrs: Dict[str, Any], error: bool) -> Dict:
    span = {"traceId": otel_trace_id(trace_id), "spanId": sid, "name": name, "kind": 1,
            "startTimeUnixNano": str(start_ns), "endTimeUnixNano": str(max(end_ns, start_ns)),
            "attributes": _attributes(attrs), "status": {"code": 2 if error else 1}}
    if parent:
        span["parentSpanId"] = parent
    return span


def root_span(run: _Run, end_record: Optional[Dict]) -> Dict:
    """Root span of a run. end_record None means the run never logged run_end: level ERROR."""
    attrs = _trace_attrs(run.trace_id, run.mode, run.scenario_id, run.session)
    attrs["langfuse.observation.type"] = "span"
    meta = dict(run.start_meta)
    if end_record is not None:
        meta.update(_pick(end_record, "run_end"))
        status = end_record.get("status")
        end_ns = _nanos(end_record.get("ts"))
        level = "ERROR" if status in _RUN_END_ERROR else ("WARNING" if status in _RUN_END_WARNING else None)
        message = status if level else None
        meta["selesai"] = True
    else:
        end_ns, level, message = time.time_ns(), "ERROR", "run_tidak_selesai"
        meta["selesai"] = False
    for k, v in meta.items():
        attrs["langfuse.trace.metadata." + k] = v
    if not _HEX32.match(run.trace_id):
        attrs["langfuse.trace.metadata.trace_id_lokal"] = run.trace_id
    attrs[_OBS + "level"] = level
    attrs[_OBS + "status_message"] = message
    return _span(run.trace_id, span_id(run.trace_id, "root"), None, f"meetrecall.{run.mode}",
                 run.start_ns, end_ns, attrs, error=level == "ERROR")


def late_run_end(run: _Run, record: Dict) -> Dict:
    """run_end that arrives after the idle timeout already sent the ERROR root: an event under that root,
    so the root (same span id) is never sent twice."""
    attrs = _trace_attrs(run.trace_id, run.mode, run.scenario_id, run.session)
    attrs["langfuse.observation.type"] = "event"
    for k, v in _pick(record, "run_end").items():
        attrs[_OBS + "metadata." + k] = v
    attrs[_OBS + "level"] = "WARNING"
    attrs[_OBS + "status_message"] = "run_end_setelah_timeout"
    ts = _nanos(record.get("ts"))
    return _span(run.trace_id, span_id(run.trace_id, "run_end_terlambat"), span_id(run.trace_id, "root"),
                 "run_end_terlambat", ts, ts, attrs, error=False)


def child_span(record: Dict, run: Optional[_Run], salt: str) -> Optional[Dict]:
    """Span for one non-run event. Child of the run's root span, or a root of its own without a run."""
    event = record.get("event")
    if event not in ("llm_call", "tool_call", "mcp_call", "guardrail", "approval"):
        return None
    trace_id = str(record["trace_id"])
    session = run.session if run else _session_id(record.get("meeting_id"), salt)
    attrs = _trace_attrs(trace_id, record.get("mode"), record.get("scenario_id"), session)
    meta = _pick(record, event)
    end_ns = _nanos(record.get("ts"))
    start_ns = end_ns - int(float(record.get("latency_ms") or 0) * 1_000_000)
    level = message = None

    if event == "llm_call":
        attrs["langfuse.observation.type"] = "generation"
        attrs[_OBS + "model.name"] = record.get("model")
        meta.update(_prompt_identity(record.get("tujuan")))
        params = {k: record[k] for k in ("temperature", "reasoning_effort") if record.get(k) is not None}
        attrs[_OBS + "model.parameters"] = params or None
        if record.get("input_tokens") is not None or record.get("output_tokens") is not None:
            attrs[_OBS + "usage_details"] = {"input": record.get("input_tokens") or 0,
                                              "output": record.get("output_tokens") or 0}
        if record.get("biaya_usd") is not None:
            attrs[_OBS + "cost_details"] = {"total": record["biaya_usd"]}
        if record.get("status") == "error":
            level, message = "ERROR", _error_class(record) or "error"
        name = f"llm.{record.get('tujuan')}"
    elif event in ("tool_call", "mcp_call"):
        attrs["langfuse.observation.type"] = "span"
        if record.get("status") in ("error", "invalid_args"):
            level, message = "ERROR", record["status"]
        name = f"{'tool' if event == 'tool_call' else 'mcp'}.{record.get('tool')}"
    else:
        attrs["langfuse.observation.type"] = "event"
        start_ns = end_ns
        if event == "guardrail" and record.get("hasil") == "fail":
            level = "WARNING"
        name = f"guardrail.{record.get('nama')}" if event == "guardrail" else "approval"

    for k, v in meta.items():
        attrs[_OBS + "metadata." + k] = v
    attrs[_OBS + "level"] = level
    attrs[_OBS + "status_message"] = message
    parent = span_id(trace_id, "root") if run else None
    return _span(trace_id, span_id(trace_id, record.get("step")), parent, name, start_ns, end_ns, attrs,
                 error=level == "ERROR")


def payload(spans: List[Dict]) -> Dict:
    """OTLP/HTTP JSON body. The only resource attribute is service.name."""
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": SERVICE_NAME}}]},
        "scopeSpans": [{"scope": {"name": SCOPE_NAME}, "spans": spans}]}]}


# Sender

class _Exporter:
    def __init__(self, settings: Dict[str, str]) -> None:
        self.settings = settings
        self.url = settings["host"] + OTLP_PATH
        token = base64.b64encode(f"{settings['public_key']}:{settings['secret_key']}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json",
                        "x-langfuse-ingestion-version": "4"}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.queue: "queue.Queue[Dict]" = queue.Queue(maxsize=QUEUE_MAX)
        self.runs: Dict[str, _Run] = {}
        self.closed: "OrderedDict[str, _Run]" = OrderedDict()   # closed by the idle timeout, root already sent
        self.runs_lock = threading.Lock()
        self.failures = 0
        self.open_until = 0.0
        self.dropped = 0
        self.sent = 0
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self.thread = threading.Thread(target=self._run, name="langfuse-export", daemon=True)
        self.thread.start()
        atexit.register(self.close)

    # mapping (caller thread)

    def handle(self, record: Dict) -> None:
        event, trace_id = record.get("event"), str(record.get("trace_id"))
        salt = self.settings["salt"]
        with self.runs_lock:
            if event == "run_start":
                self.runs[trace_id] = _Run(record, salt)
                return
            run = self.runs.get(trace_id)
            if run is not None:
                run.last_seen = time.monotonic()
            late = run is None and trace_id in self.closed
            if late:
                run = self.closed[trace_id]          # root already sent by the idle timeout: never send it again
            if event == "run_end":
                if late:
                    del self.closed[trace_id]
                    self.put(late_run_end(run, record))
                elif run is not None:
                    del self.runs[trace_id]
                    self.put(root_span(run, record))
                return
        span = child_span(record, run, salt)
        if span is not None:
            self.put(span)

    def close_stale(self, now: Optional[float] = None, everything: bool = False) -> int:
        """Send an ERROR root span for runs without run_end: idle too long, or all of them at exit."""
        now = time.monotonic() if now is None else now
        with self.runs_lock:
            stale = [t for t, r in self.runs.items() if everything or now - r.last_seen >= RUN_IDLE_TIMEOUT_S]
            runs = [self.runs.pop(t) for t in stale]
            for run in runs:                          # remembered, so late events attach to the root already sent
                self.closed[run.trace_id] = run
                while len(self.closed) > CLOSED_RUNS_MAX:
                    self.closed.popitem(last=False)
        for run in runs:
            self.put(root_span(run, None))
        return len(runs)

    def put(self, span: Dict) -> None:
        try:
            self.queue.put_nowait(span)
            self._idle.clear()
        except queue.Full:
            self.dropped += 1

    # sending (background thread)

    def _take_batch(self) -> List[Dict]:
        batch: List[Dict] = []
        deadline = time.monotonic() + FLUSH_INTERVAL_S
        while len(batch) < BATCH_MAX:
            timeout = deadline - time.monotonic()
            if timeout <= 0 or (self._stop.is_set() and self.queue.empty()):
                break
            try:
                batch.append(self.queue.get(timeout=min(timeout, 0.2)))
            except queue.Empty:
                if batch and self._stop.is_set():
                    break
        return batch

    def _send(self, batch: List[Dict]) -> bool:
        data = json.dumps(payload(batch), ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=self.headers, method="POST")
        try:
            with self.opener.open(req, timeout=HTTP_TIMEOUT_S) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def _run(self) -> None:
        while not (self._stop.is_set() and self.queue.empty()):
            self.close_stale()
            batch = self._take_batch()
            if not batch:
                if self.queue.empty():
                    self._idle.set()
                continue
            if time.monotonic() < self.open_until:
                self.dropped += len(batch)          # circuit open: drop, keep the queue bounded
            elif self._send(batch):
                self.sent += len(batch)
                if self.failures >= BREAKER_FAILURES:
                    logger.warning("Langfuse export resumed.")
                self.failures = 0
            else:
                self.failures += 1
                self.dropped += len(batch)
                if self.failures >= BREAKER_FAILURES:
                    if self.failures == BREAKER_FAILURES:
                        logger.warning("Langfuse export paused for %ss after %s failed requests.",
                                       BREAKER_COOLDOWN_S, BREAKER_FAILURES)
                    self.open_until = time.monotonic() + BREAKER_COOLDOWN_S
            if self.queue.empty():
                self._idle.set()

    def flush(self, timeout: float = SHUTDOWN_FLUSH_S) -> None:
        self._idle.wait(timeout)

    def close(self) -> None:
        """At exit: unfinished runs get their ERROR root span, then the queue is sent (max SHUTDOWN_FLUSH_S)."""
        if self._stop.is_set():
            return
        self.close_stale(everything=True)
        self._stop.set()
        self.thread.join(SHUTDOWN_FLUSH_S)


def _exporter() -> Optional[_Exporter]:
    global _state, _disabled
    if _state is not None or _disabled:
        return _state
    with _lock:
        if _state is None and not _disabled:
            settings = _settings()
            if settings is None:
                _disabled = True
            else:
                _state = _Exporter(settings)
    return _state


def forward(record: Dict) -> None:
    """Called by Tracer.log after the JSONL line is written. Never raises."""
    try:
        exporter = _exporter()
        if exporter is not None:
            exporter.handle(record)
    except Exception:
        pass


def flush(timeout: float = SHUTDOWN_FLUSH_S) -> None:
    if _state is not None:
        _state.flush(timeout)


def reset() -> None:
    """Forget settings and stop the sender (tests, or after changing the environment)."""
    global _state, _disabled
    with _lock:
        if _state is not None:
            _state.close()
        _state, _disabled = None, False
