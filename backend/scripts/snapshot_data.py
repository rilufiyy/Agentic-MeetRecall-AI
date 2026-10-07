"""
Read-only snapshot of a data directory, to prove it did not change.

    python scripts/snapshot_data.py --data data --out ../eval_run/snapshot_demo_acuan_2026-10-07.json
    python scripts/snapshot_data.py --data data --compare ../eval_run/snapshot_demo_acuan_2026-10-07.json

Records counts (tasks, approvals by status, rekap files, report folders, outbox files, trace lines, meetings) and
SHA-256 prefixes of agent.db, meetings.json and sources.json. `--compare` prints IDENTIK or the differing keys
and exits with 1 on a difference. Nothing is written to the data directory.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


def _sha(path: str):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] if os.path.exists(path) else None


def snapshot(data: str) -> dict:
    con = sqlite3.connect(f"file:{Path(data, 'agent', 'agent.db').as_posix()}?mode=ro", uri=True)
    try:
        tasks = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        approvals = con.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
        by_status = dict(con.execute("SELECT status, COUNT(*) FROM approvals GROUP BY status").fetchall())
    finally:
        con.close()
    return {
        "tasks": tasks, "approvals": approvals, "approvals_status": by_status,
        "rekap_files": len(glob.glob(f"{data}/agent/rekap/*.json")),
        "laporan_dirs": len(glob.glob(f"{data}/agent/laporan/*")),
        "outbox_files": len(glob.glob(f"{data}/agent/outbox/*")),
        "trace_lines": sum(sum(1 for _ in open(f, encoding="utf-8")) for f in glob.glob(f"{data}/traces/*.jsonl")),
        "meetings": len(glob.glob(f"{data}/meetings/*.json")),
        "agent_db_sha": _sha(f"{data}/agent/agent.db"), "meetings_json_sha": _sha(f"{data}/meetings.json"),
        "sources_sha": _sha(f"{data}/sources.json"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out")
    ap.add_argument("--compare")
    args = ap.parse_args()
    now = snapshot(args.data)
    if args.out:
        Path(args.out).write_text(json.dumps(now, indent=1, ensure_ascii=False), encoding="utf-8")
        print("snapshot ditulis:", args.out)
    if args.compare:
        ref = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        diff = {k: (ref.get(k), now.get(k)) for k in set(ref) | set(now) if ref.get(k) != now.get(k)}
        if diff:
            print("BERBEDA:", json.dumps(diff, ensure_ascii=False))
            sys.exit(1)
        print("IDENTIK dengan", args.compare)
    if not args.out and not args.compare:
        print(json.dumps(now, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
