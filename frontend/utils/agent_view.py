"""
Rendering helpers for the agent page (W78): the step trace of one agent run
and the transcription job table. Data comes from the backend as is; nothing
here calls an LLM.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd
import streamlit as st

JOB_LABEL = {"antre": "ANTRE", "diproses": "DIPROSES", "selesai": "SELESAI", "gagal": "GAGAL"}
_TONE = {"pass": "#22c55e", "ok": "#22c55e", "fail": "#ef4444", "error": "#ef4444", "invalid_args": "#ef4444",
         "flag": "#f59e0b", "rejected": "#f59e0b", "not_found": "#f59e0b", "awaiting_approval": "#a855f7",
         "needs_human": "#a855f7"}
_STATUS_TEXT = {
    "completed": "selesai menjawab",
    "awaiting_approval": "menunggu persetujuan Anda",
    "needs_human": "bertanya balik ke Anda",
    "rejected_input": "input ditolak",
    "rejected_scope": "di luar cakupan",
    "max_iterations": "batas langkah tercapai",
    "tool_error": "tool gagal berulang",
    "llm_error": "model tidak dapat dihubungi",
}


def status_text(status: str) -> str:
    return _STATUS_TEXT.get(status, status)


def _box(title: str, body: str, tone: str) -> None:
    st.markdown(
        f"<div style='border-left:4px solid {tone};background:rgba(148,163,184,0.08);"
        f"border-radius:6px;padding:8px 12px;margin:6px 0;'>"
        f"<div style='font-weight:700;font-size:14px;'>{title}</div>"
        f"<div style='font-size:13px;color:#cbd5e1;'>{body}</div></div>",
        unsafe_allow_html=True,
    )


def _ms(value) -> str:
    return f"{value:,.0f} ms" if isinstance(value, (int, float)) else "-"


def describe(e: Dict) -> Dict:
    """One trace event as a row: what happened, why it matters, how long it took."""
    ev = e.get("event")
    if ev == "run_start":
        return {"judul": "Permintaan diterima", "isi": f"Pesan: {e.get('pesan_user', '')}",
                "tone": "#64748b", "latency": None}
    if ev == "guardrail":
        hasil = e.get("hasil", "")
        detail = e.get("detail")
        return {"judul": f"Guardrail {e.get('nama')}: {hasil}",
                "isi": json.dumps(detail, ensure_ascii=False)[:300] if detail else "",
                "tone": _TONE.get(hasil, "#64748b"), "latency": None}
    if ev == "llm_call":
        tujuan = e.get("tujuan", "")
        tools = e.get("tool_calls_diminta") or []
        if e.get("status") == "error":
            keputusan = f"Gagal: {str(e.get('error', ''))[:200]}"
        elif tujuan == "agent":
            keputusan = (f"LLM memutuskan memanggil tool <b>{', '.join(tools)}</b>" if tools
                         else "LLM memutuskan menjawab tanpa tool")
        else:
            keputusan = f"Panggilan LLM di dalam tool ({tujuan})"
        tokens = f"{e.get('input_tokens', '-')} token masuk, {e.get('output_tokens', '-')} token keluar"
        judul = f"LLM, iterasi {e.get('iterasi')}" if tujuan == "agent" else "LLM ekstraksi"
        return {"judul": judul, "isi": f"{keputusan}. {tokens}.",
                "tone": "#ef4444" if e.get("status") == "error" else "#6366f1", "latency": e.get("latency_ms")}
    if ev == "tool_call":
        status = e.get("status", "")
        fase = " (eksekusi setelah persetujuan)" if e.get("fase") == "eksekusi" else ""
        return {"judul": f"Tool {e.get('tool')}{fase}: {status}",
                "isi": (e.get("error") or "")[:300], "tone": _TONE.get(status, "#64748b"),
                "latency": e.get("latency_ms"), "argumen": e.get("argumen"), "hasil": e.get("ringkasan_output")}
    if ev == "approval":
        return {"judul": f"Approval {e.get('approval_id')}: {e.get('keputusan_user')}",
                "isi": f"Aksi tulis {e.get('tool')} ditahan sampai Anda memutuskan.",
                "tone": "#a855f7", "latency": None}
    if ev == "run_end":
        return {"judul": f"Selesai: {status_text(e.get('status', ''))}",
                "isi": f"{e.get('jumlah_iterasi')} iterasi, {e.get('jumlah_llm_call')} panggilan LLM, "
                       f"biaya {e.get('total_biaya_usd')} USD",
                "tone": _TONE.get(e.get("status"), "#22c55e"), "latency": e.get("total_latency_ms")}
    return {"judul": ev or "?", "isi": "", "tone": "#64748b", "latency": None}


def render_steps(steps: List[Dict], key: str) -> None:
    """Timeline of one run, in trace order, with tool arguments and results."""
    if not steps:
        st.caption("Belum ada langkah.")
        return
    end = next((e for e in steps if e.get("event") == "run_end"), {})
    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)
    c1.metric("Iterasi", end.get("jumlah_iterasi", "-"))
    c2.metric("Panggilan LLM", end.get("jumlah_llm_call", "-"))
    tin, tout = end.get("total_input_tokens"), end.get("total_output_tokens")
    c3.metric("Token", f"{tin + tout:,}" if tin is not None and tout is not None else "n/a")
    c4.metric("Latensi", f"{(end.get('total_latency_ms') or 0) / 1000:.1f} s")
    gagal = end.get("llm_call_gagal") or 0
    st.caption(f"trace_id {steps[0].get('trace_id')} (data/traces/*.jsonl)"
               + (f" | {gagal} panggilan LLM gagal dan dicoba ulang; token mereka tidak terhitung" if gagal else ""))

    as_table = st.toggle("Tampilkan sebagai tabel", key=f"tbl_{key}")
    rows = [describe(e) | {"step": e.get("step")} for e in steps]
    if as_table:
        st.dataframe(pd.DataFrame([{"step": r["step"], "langkah": r["judul"],
                                    "detail": r["isi"].replace("<b>", "").replace("</b>", ""),
                                    "latency_ms": r["latency"]} for r in rows]),
                     hide_index=True, use_container_width=True)
        return
    for r in rows:
        _box(f"{r['step']}. {r['judul']}" + (f" <span style='color:#94a3b8;font-weight:400;'>"
                                             f"({_ms(r['latency'])})</span>" if r["latency"] else ""),
             r["isi"], r["tone"])
        if r.get("argumen") is not None or r.get("hasil"):
            with st.expander("Argumen dan hasil tool", expanded=False):
                st.markdown("**Argumen dari LLM** (divalidasi Pydantic sebelum dijalankan)")
                st.json(r.get("argumen") or {}, expanded=True)
                st.markdown("**Ringkasan hasil** (yang dikembalikan ke LLM)")
                st.json(r.get("hasil") or {}, expanded=True)


_TZ_LABEL = os.getenv("REPORT_TZ_LABEL", "WIB")
_TZ = timezone(timedelta(hours=float(os.getenv("REPORT_TZ_OFFSET_HOURS", "7"))))


def _local(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return f"{moment.astimezone(_TZ):%Y-%m-%d %H:%M:%S}"


def jobs_table(jobs: List[Dict]) -> None:
    if not jobs:
        st.caption("Belum ada job transkripsi.")
        return
    st.dataframe(pd.DataFrame([{
        "file": j["filename"], "status": JOB_LABEL.get(j["status"], j["status"]), "provider": j["provider"],
        f"diunggah ({_TZ_LABEL})": _local(j.get("dibuat")),
        "lama proses (s)": j.get("durasi_proses_detik"),
        "notifikasi": j.get("notifikasi") or "-", "error": (j.get("error") or "")[:80],
    } for j in jobs]), hide_index=True, use_container_width=True)
