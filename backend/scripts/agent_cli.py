"""
Run the meeting agent from the terminal.

Run from backend/ (inside the agent container, or any env with the backend deps):
    python scripts/agent_cli.py --list
    python scripts/agent_cli.py --meeting-id <id> "Apa saja action items meeting ini?"
    python scripts/agent_cli.py --meeting-id <id> --chat        # interactive, keeps history and rekap
    python scripts/agent_cli.py --pending                        # approval requests still waiting
    python scripts/agent_cli.py --approve <approval_id>          # phase 2: execute after review
    python scripts/agent_cli.py --reject <approval_id>
    python scripts/agent_cli.py --tasks --meeting-id <id>

Write actions (task, email) never run inside the agent: the agent only creates
an approval request, and this CLI asks you before code executes it.
Needs GROQ_API_KEY in the environment. Every run is traced to data/traces/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)   # storage and traces use paths relative to backend/ (data/...)

# Outside Docker, read backend/.env (variables already set in the shell win).
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env", override=False)
except ImportError:
    pass

from agent import approvals  # noqa: E402
from agent.loop import MeetingAgent  # noqa: E402
from services.storage import storage_service  # noqa: E402


def _print_result(res) -> None:
    print("\n" + res.answer + "\n")
    print(f"[status={res.status} iterasi={res.iterations} tools={res.tools_called} "
          f"rekap_id={res.rekap_id} approval_id={res.approval_id} latency_ms={res.latency_ms} "
          f"trace_id={res.trace_id}]")
    print("[" + json.dumps(res.totals) + "]")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _review(store: approvals.ApprovalStore, approval_id: str, force: str = "") -> str:
    """Show the request, collect the decision (and missing values for tasks), execute. Returns a summary."""
    approval = store.get(approval_id)
    if approval is None:
        return f"Approval {approval_id} tidak ditemukan."
    if approval["status"] != "menunggu":
        return f"Approval {approval_id} sudah berstatus {approval['status']}."
    print("\n" + approvals.format_request(approval))
    answer = force or _ask("\nSetujui? (y/n) ").lower()
    if answer not in ("y", "ya", "yes"):
        result = approvals.decide(store, approval_id, setuju=False)
        return f"Approval {approval_id} ditolak. {result['pesan']}"

    isian = {}
    if approval["tool"] == "buat_task":
        for it in approval["preview"]["items"]:
            fill = {}
            if it["perlu_isi_penanggung_jawab"]:
                fill["penanggung_jawab"] = _ask(
                    f"{it['id']} '{it['isi']}': penanggung jawab tidak jelas di transkrip. "
                    "Isi nama (Enter = lewati item ini): ")
            if it["perlu_cek_tenggat"]:
                current = it["tenggat"] or "tidak disebut"
                while True:
                    fill["tenggat"] = _ask(f"{it['id']} tenggat '{current}'. Isi YYYY-MM-DD (Enter = biarkan): ")
                    try:
                        _, warning = approvals.check_deadline(fill["tenggat"])
                    except approvals.InvalidInput as exc:
                        print(f"  {exc}")
                        continue
                    if warning:
                        print(f"  Peringatan: {warning}")
                    break
            isian[it["id"]] = {k: v for k, v in fill.items() if v}
    result = approvals.decide(store, approval_id, setuju=True, isian=isian)
    return f"Hasil approval {approval_id}: " + json.dumps(result, ensure_ascii=False)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("message", nargs="?", help="Pesan untuk agent")
    p.add_argument("--meeting-id")
    p.add_argument("--rekap-id", help="Lanjutkan dari rekap sebelumnya")
    p.add_argument("--list", action="store_true", help="Tampilkan daftar meeting")
    p.add_argument("--chat", action="store_true", help="Mode interaktif")
    p.add_argument("--pending", action="store_true", help="Daftar approval yang menunggu")
    p.add_argument("--approve", metavar="APPROVAL_ID")
    p.add_argument("--reject", metavar="APPROVAL_ID")
    p.add_argument("--tasks", action="store_true", help="Daftar task (filter --meeting-id)")
    a = p.parse_args()

    if a.list:
        for m in storage_service.list_meetings():
            print(f"{m.meeting_id}  {m.status:<10} {m.duration / 60:5.1f} menit  {m.num_speakers} speaker  {m.filename}")
        return
    store = approvals.ApprovalStore()
    if a.pending:
        for ap in store.pending(a.meeting_id):
            print(f"{ap['approval_id']}  {ap['tool']:<18} rekap {ap['rekap_id']}  dibuat {ap['dibuat']}")
        return
    if a.approve or a.reject:
        print(_review(store, a.approve or a.reject, force="" if a.approve else "n"))
        return
    if a.tasks:
        for t in store.tasks(a.meeting_id):
            print(f"{t['task_id']:<5} {t['item_id']:<4} {t['tugas'][:60]:<60} PJ: {t['penanggung_jawab']} "
                  f"({t['sumber_penanggung_jawab']})  tenggat: {t['tenggat'] or '-'}  {t['mulai']}")
        return
    if not a.meeting_id:
        p.error("--meeting-id wajib (lihat --list)")

    agent = MeetingAgent()
    if not a.chat:
        if not a.message:
            p.error("pesan wajib diisi, atau pakai --chat")
        res = agent.run(a.message, a.meeting_id, rekap_id=a.rekap_id)
        _print_result(res)
        if res.approval_id:
            print(f"\nTinjau dengan: python scripts/agent_cli.py --approve {res.approval_id}")
        return

    info = storage_service.get_meeting_info(a.meeting_id)
    if info is None:
        p.error(f"meeting {a.meeting_id} tidak ditemukan (lihat --list)")
    print(f"MeetRecall Agent, meeting: {info.filename} ({info.duration / 60:.1f} menit, "
          f"{info.num_speakers} speaker)")
    print("Ketik pertanyaan lalu Enter. Contoh: 'Apa saja action items meeting ini?', "
          "'Buatkan task untuk A1', 'Buat laporan PDF lalu kirim ke email saya'. Ketik 'keluar' untuk berhenti.")
    history, rekap_id = [], a.rekap_id
    while True:
        msg = _ask("\nAnda> ")
        if msg.lower() in ("exit", "quit", "keluar"):
            break
        if not msg:
            continue
        res = agent.run(msg, a.meeting_id, history=history, rekap_id=rekap_id)
        _print_result(res)
        rekap_id = res.rekap_id or rekap_id
        history += [{"role": "user", "content": msg}, {"role": "assistant", "content": res.answer}]
        if res.approval_id:
            summary = _review(store, res.approval_id)
            print("\n" + summary)
            # The outcome goes into the history so the next turn knows what really happened.
            history.append({"role": "assistant", "content": "[Catatan sistem] " + summary})


if __name__ == "__main__":
    main()
