"""
Verify that a rejected approval left no side effects. Read-only: it never writes to the data directory.

    python scripts/verify_approval_rejected.py baseline --data data --out baseline.json
    (reject the approval in the UI)
    python scripts/verify_approval_rejected.py verify --data data --approval-id APxxxx --baseline baseline.json

Checks (all must pass): the approval row is `ditolak` with a decision time; the trace holds an approval event with
keputusan_user "tolak"; the trace holds NO execution tool_call for that approval; the number of tasks, the outbox
files, the report files (SHA-256), the rekap files and every other approval are unchanged since the baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(data: Path) -> Dict:
    data = Path(data)
    con = sqlite3.connect(f"file:{(data / 'agent' / 'agent.db').as_posix()}?mode=ro", uri=True)
    try:
        approvals = {r[0]: r[1] for r in con.execute("SELECT approval_id, status FROM approvals")}
        tasks = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        con.close()
    agent = data / "agent"
    return {"approvals": approvals, "tasks": tasks,
            "outbox": sorted(p.name for p in (agent / "outbox").glob("*")) if (agent / "outbox").exists() else [],
            "rekap": sorted(p.name for p in (agent / "rekap").glob("*.json")) if (agent / "rekap").exists() else [],
            "laporan": {p.relative_to(data).as_posix(): _sha(p) for p in (agent / "laporan").rglob("*") if p.is_file()}
            if (agent / "laporan").exists() else {}}


def trace_events(data: Path, approval_id: str) -> List[Dict]:
    out = []
    for f in sorted((Path(data) / "traces").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if approval_id in line:
                out.append(json.loads(line))
    return out


def verify(data: Path, approval_id: str, baseline: Dict) -> List[Tuple[str, bool, str]]:
    now = snapshot(data)
    con = sqlite3.connect(f"file:{(Path(data) / 'agent' / 'agent.db').as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT status, diputuskan, hasil FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
    finally:
        con.close()
    events = trace_events(data, approval_id)
    decisions = [e for e in events if e.get("event") == "approval" and e.get("keputusan_user") == "tolak"]
    executions = [e for e in events if e.get("event") == "tool_call" and e.get("fase") == "eksekusi"]
    others_now = {k: v for k, v in now["approvals"].items() if k != approval_id}
    others_before = {k: v for k, v in baseline["approvals"].items() if k != approval_id}
    hasil = json.loads(row[2]) if row and row[2] else {}
    return [
        ("status ditolak di database", bool(row) and row[0] == "ditolak" and row[1] is not None and hasil.get("status") == "rejected",
         f"status={row[0] if row else None}, diputuskan={row[1] if row else None}, hasil={hasil.get('status')}"),
        ("trace mencatat keputusan tolak", len(decisions) == 1, f"{len(decisions)} kejadian approval dengan keputusan_user=tolak"),
        ("trace tanpa eksekusi tool", not executions, f"{len(executions)} kejadian tool_call fase eksekusi"),
        ("jumlah task sama", now["tasks"] == baseline["tasks"], f"{baseline['tasks']} -> {now['tasks']}"),
        ("outbox sama (tidak ada email)", now["outbox"] == baseline["outbox"], f"{len(baseline['outbox'])} -> {len(now['outbox'])} berkas"),
        ("berkas laporan sama (SHA-256)", now["laporan"] == baseline["laporan"], f"{len(baseline['laporan'])} berkas"),
        ("rekap sama", now["rekap"] == baseline["rekap"], f"{len(baseline['rekap'])} -> {len(now['rekap'])} berkas"),
        ("approval lain tidak berubah", others_now == others_before, f"{len(others_before)} approval lain"),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline")
    b.add_argument("--data", default="data")
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--data", default="data")
    v.add_argument("--approval-id", required=True)
    v.add_argument("--baseline", required=True)
    args = ap.parse_args()
    if args.cmd == "baseline":
        Path(args.out).write_text(json.dumps(snapshot(Path(args.data)), indent=1, ensure_ascii=False), encoding="utf-8")
        print("baseline ditulis:", args.out)
        return
    results = verify(Path(args.data), args.approval_id, json.loads(Path(args.baseline).read_text(encoding="utf-8")))
    for name, ok, detail in results:
        print(f"{'LOLOS' if ok else 'GAGAL'}  {name}  ({detail})")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()
