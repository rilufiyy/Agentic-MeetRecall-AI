"""
Proactive suggestions: next steps worth offering after a recap exists.

Built by code from stored data (rekap, exports, tasks, approvals), no LLM call. A suggestion is only text plus
the sentence a button would send as the user's own message; nothing is executed here. The click goes through the
normal agent run, so write intent and the approval step apply unchanged.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from agent import approvals, reporting
from agent.guardrails import normalize

ALL_KINDS = ("ringkasan", "keputusan", "action_items", "isu_terbuka")
MAIL_FORMATS = ("pdf", "docx", "md")


def _action_items_without_task(rekap: Dict, task_quotes: Dict[str, str]) -> List[Dict]:
    items = (rekap.get("bagian", {}).get("action_items") or {}).get("items", [])
    return [i for i in items if normalize(i["kutipan"]) not in task_quotes]


def suggest(rekap: Optional[Dict], exports: List[Dict], task_quotes: Dict[str, str],
            rekap_approvals: List[Dict]) -> List[Dict]:
    """Suggestions as {id, teks, prompt}. `prompt` is the literal request a click sends to the agent."""
    if not rekap:
        return []
    out: List[Dict] = []
    busy = {a["tool"] for a in rekap_approvals if a["status"] in ("menunggu", "diproses")}

    todo = _action_items_without_task(rekap, task_quotes)
    if todo and "buat_task" not in busy:
        unclear = sum(1 for i in todo if approvals.needs_owner(i) or approvals.needs_deadline(i))
        teks = f"Ada {len(todo)} action item yang belum dijadikan task."
        if unclear:
            who = "Semuanya" if unclear == len(todo) else f"{unclear} di antaranya"
            teks += (f" {who} belum jelas penanggung jawab atau tenggatnya; "
                     "Anda bisa mengisinya saat persetujuan.")
        out.append({"id": "task", "teks": teks + " Buat sebagai task? Anda masih akan diminta menyetujui sebelum task dibuat.",
                    "tombol": "Buat task",
                    "prompt": "Buatkan task untuk semua action items"})

    complete = all(reporting.section_status(rekap, k) != "belum_dianalisis" for k in ALL_KINDS)
    if complete and not exports:
        out.append({"id": "laporan", "teks": "Rekap sudah lengkap tapi belum ada laporan. Buat laporan PDF?",
                    "tombol": "Buat laporan PDF", "prompt": "Buatkan laporan PDF"})

    mailable = [e["format"] for e in exports if e["format"] in MAIL_FORMATS]
    emailed = any(a["tool"] == "kirim_email_rekap" and a["status"] in ("menunggu", "diproses", "dieksekusi")
                  for a in rekap_approvals)
    if mailable and not emailed:
        out.append({"id": "email", "teks": "Laporan sudah siap tapi belum dikirim. Kirim ke email Anda? "
                                           "Anda masih akan diminta menyetujui sebelum email terkirim.",
                    "tombol": "Kirim ke email saya",
                    "prompt": f"Kirim laporan {', '.join(dict.fromkeys(mailable))} ke email saya"})
    return out
