"""
Structured tracing: one JSON object per line in data/traces/YYYY-MM-DD.jsonl.

Event types: run_start, llm_call, tool_call, guardrail, approval, run_end.
Every event carries trace_id, step, event, ts, meeting_id, mode, scenario_id;
the remaining fields depend on the event (see docs/01_desain.md section 6).
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent import config

# Secret-looking keys only; "input_tokens" and "output_tokens" must stay readable.
_SECRET_KEY = re.compile(
    r"api[_-]?key|secret|passw(or)?d|authorization|bearer|^token$|(access|auth|refresh|bot)[_-]?token",
    re.IGNORECASE,
)
_LOCK = threading.Lock()


def redact(value: Any) -> Any:
    """Mask values stored under secret-looking keys, recursively."""
    if isinstance(value, dict):
        return {k: ("***" if _SECRET_KEY.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Tracer:
    def __init__(
        self,
        meeting_id: str,
        mode: str = "agent",
        scenario_id: Optional[str] = None,
        trace_dir: Optional[Path] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.meeting_id = meeting_id
        self.mode = mode
        self.scenario_id = scenario_id
        self.trace_dir = Path(trace_dir or config.TRACE_DIR)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.step = 0
        self.events: List[Dict] = []   # kept in memory for the run summary

    @property
    def path(self) -> Path:
        return self.trace_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"

    def log(self, event: str, **fields: Any) -> Dict:
        self.step += 1
        record = {
            "trace_id": self.trace_id,
            "step": self.step,
            "event": event,
            "ts": _now(),
            "meeting_id": self.meeting_id,
            "mode": self.mode,
            "scenario_id": self.scenario_id,
            **redact(fields),
        }
        self.events.append(record)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _LOCK, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return record

    def guardrail(self, name: str, result: str, detail: Any = None) -> None:
        self.log("guardrail", nama=name, hasil=result, detail=detail)

    def totals(self) -> Dict[str, Any]:
        """Sum tokens and cost over the llm_call events of this trace."""
        calls = [e for e in self.events if e["event"] == "llm_call"]
        answered = [e for e in calls if e.get("input_tokens") is not None]

        def total(key):
            # Failed requests report no usage; they are counted in llm_call_gagal, not guessed.
            values = [e.get(key) for e in answered]
            return None if not answered or any(v is None for v in values) else sum(values)

        cost = total("biaya_usd")
        return {
            "jumlah_llm_call": len(calls),
            "llm_call_gagal": len(calls) - len(answered),
            "total_input_tokens": total("input_tokens"),
            "total_output_tokens": total("output_tokens"),
            "total_biaya_usd": round(cost, 8) if cost is not None else None,
        }
