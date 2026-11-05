"""
Page 5 - MeetRecall Agent (W78).

Left: chat with the agent, approval card for write actions, downloads.
Right: step trace of the selected run (LLM decisions, tool arguments and
results, guardrails, latency), so the agent's choices are visible in a demo.
Sidebar: meeting, active rekap, transcription job status (auto refresh).

Write actions (task, email) run only after the buttons here; the agent itself
can only create an approval request.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Agent - MeetRecall AI", layout="wide")

from utils.agent_view import jobs_table, render_steps, status_text  # noqa: E402
from utils.api_client import api_client  # noqa: E402
from utils.styles import ASSISTANT_AVATAR, TYPING_INDICATOR, USER_AVATAR, inject, user_html  # noqa: E402

inject()

for _k, _v in [("agent_form_error", None), ("current_meeting_id", ""), ("agent_meeting_id", ""), ("agent_messages", []),
               ("agent_rekap_id", None), ("agent_pending_prompt", None), ("agent_selected_run", None)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

EXAMPLES = [
    "Apa saja action items meeting ini?",
    "Buat laporan Word berisi ringkasan, keputusan, dan action items",
    "Buatkan task untuk semua action items",
    "Kirim rekap PDF ke email saya",
]


# Sidebar: meeting, rekap, jobs

with st.sidebar:
    st.markdown("### Pilih Meeting")
    meetings = api_client.list_meetings()
    completed = [m for m in meetings if m.get("status") == "completed"]
    if not completed:
        st.info("Belum ada meeting yang selesai ditranskripsi.")
        selected_id = ""
    else:
        opts = {f"{m['filename']} ({m['meeting_id'][:8]})": m["meeting_id"] for m in completed}
        want = st.session_state.current_meeting_id
        idx = next((i for i, v in enumerate(opts.values()) if v == want), 0)
        selected_id = opts[st.selectbox("Meeting", list(opts), index=idx, label_visibility="collapsed")]

    st.markdown("### Rekap aktif")
    st.caption(st.session_state.agent_rekap_id or "Belum ada. Rekap dibuat saat agent mengekstrak poin.")
    if st.button("Mulai percakapan baru", use_container_width=True):
        st.session_state.agent_messages = []
        st.session_state.agent_rekap_id = None
        st.session_state.agent_selected_run = None
        st.rerun()

    st.divider()

    @st.fragment(run_every=5)
    def job_panel() -> None:
        # Fragment: only this panel reruns every 5 s, the chat is not reloaded.
        jobs = api_client.list_jobs(limit=8)
        st.markdown("### Job transkripsi")
        active = [j for j in jobs if j["status"] in ("antre", "diproses")]
        st.caption(f"{len(active)} aktif, diperbarui otomatis tiap 5 detik")
        for j in jobs[:6]:
            st.markdown(f"**{j['status'].upper()}** · {j['filename'][:28]}")
    job_panel()

if selected_id != st.session_state.agent_meeting_id:
    st.session_state.agent_meeting_id = selected_id
    st.session_state.agent_messages = []
    st.session_state.agent_rekap_id = None
    st.session_state.agent_selected_run = None
if selected_id:
    st.session_state.current_meeting_id = selected_id

st.markdown("<h1 style='font-size:2.1rem;font-weight:900;'>MeetRecall Agent</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#94a3b8;'>Agent tindak lanjut meeting: memilih tool sendiri untuk ringkasan, "
            "keputusan, action items, laporan, task, dan email. Aksi tulis selalu menunggu persetujuan Anda.</p>",
            unsafe_allow_html=True)
if not selected_id:
    st.stop()


# Agent call

def run_agent(prompt: str) -> None:
    history = [{"role": m["role"], "content": m["content"]}
               for m in st.session_state.agent_messages if m["role"] in ("user", "assistant")]
    st.session_state.agent_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(user_html(prompt), unsafe_allow_html=True)
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        _typing = st.empty()
        _typing.markdown(TYPING_INDICATOR, unsafe_allow_html=True)
        res = api_client.agent_chat(selected_id, prompt, history=history,
                                    rekap_id=st.session_state.agent_rekap_id)
        _typing.empty()
    if "error" in res:
        st.session_state.agent_messages.append({"role": "assistant", "content": f"Error: {res['error']}",
                                                "status": "error", "steps": []})
        return
    st.session_state.agent_rekap_id = res.get("rekap_id") or st.session_state.agent_rekap_id
    st.session_state.agent_messages.append({
        "role": "assistant", "content": res["answer"], "status": res["status"], "steps": res.get("steps", []),
        "trace_id": res["trace_id"], "approval": res.get("approval"), "tools": res.get("tools_called", []),
        "iterations": res.get("iterations"), "latency_ms": res.get("latency_ms"),
        "sources": res.get("sources", []), "verifikasi": res.get("verifikasi", {}),
    })
    st.session_state.agent_selected_run = None   # show the newest run


def decide(approval: dict, setuju: bool, isian: dict) -> None:
    tone = "success"
    out = api_client.decide_approval(approval["approval_id"], setuju, isian)
    if out.get("status_code") == 422:
        # Invalid input: keep the approval pending and show the reason on the card.
        st.session_state.agent_form_error = {"id": approval["approval_id"], "pesan": out["error"]}
        return False
    if "error" in out:
        text = f"Persetujuan {approval['approval_id']} gagal diproses: {out['error']}"
        tone = "error"
    elif not setuju:
        text = f"Anda menolak {approval['tool']} ({approval['approval_id']}). Tidak ada yang dijalankan."
        tone = "info"
    else:
        h = out["hasil"]
        if approval["tool"] == "buat_task" and h.get("status") in ("ok", "not_found"):
            made = ", ".join(f"{t['task_id']} ({t['item_id']}, PJ {t['penanggung_jawab']})" for t in h["tasks"])
            skipped = ", ".join(f"{s['item_id']} ({s['alasan']})" for s in h.get("dilewati", []))
            text = f"Task dibuat: {made or 'tidak ada'}." + (f" Dilewati: {skipped}." if skipped else "")
            if h.get("peringatan"):
                text += " Peringatan: " + "; ".join(h["peringatan"])
        elif approval["tool"] == "kirim_email_rekap" and h.get("status") == "ok":
            names = ", ".join(h["lampiran"]) if isinstance(h["lampiran"], list) else h["lampiran"]
            count = len(h["lampiran"]) if isinstance(h["lampiran"], list) else 1
            if h.get("mode") == "dry_run":
                text = (f"Mode dry_run: email ke {h['penerima']} dengan {count} lampiran ({names}) belum dikirim, "
                        f"hanya disimpan sebagai file {h.get('path')}.")
            else:
                text = f"Email ke {h['penerima']} dengan {count} lampiran ({names}) sudah dikirim lewat SMTP."
        else:
            text = f"Eksekusi gagal: {h.get('pesan', h)}"
            tone = "error"
    # Recorded as an assistant turn so the next agent run knows what really happened.
    st.session_state.agent_messages.append({"role": "assistant", "content": "[Catatan sistem] " + text,
                                            "status": "approval", "steps": [], "tampil": text, "tone": tone})
    return True


def waiting_text(approval: dict | None) -> str:
    """One sentence for the chat; the details and the buttons are on the approval card below."""
    if not approval:
        return "Agent menyiapkan permintaan persetujuan. Tinjau kartu persetujuan di bawah."
    p = approval.get("preview") or {}
    if approval["tool"] == "kirim_email_rekap":
        att = p.get("lampiran")
        names = [a["nama_file"] for a in att] if isinstance(att, list) else [p.get("nama_file") or str(att)]
        what = f"mengirim email ke `{p.get('penerima')}` dengan {len(names)} lampiran"
    else:
        what = f"membuat {len(p.get('items', []))} task"
    return (f"Agent siap {what}. Tidak ada yang dijalankan sebelum Anda memutuskan: "
            "tinjau kartu persetujuan di bawah, lalu klik **Setujui dan jalankan** atau **Tolak**.")


def render_sources(sources: list, verifikasi: dict) -> None:
    """References the agent read this run. Built by code from tool results; each shows speaker, time and text."""
    total, missing = verifikasi.get("kutipan_total", 0), verifikasi.get("kutipan_tidak_ditemukan", 0)
    if total:
        check = (f"Kutipan di jawaban: {total - missing} dari {total} ditemukan persis di transkrip"
                 + (" (sisanya ditandai di jawaban)." if missing else "."))
    else:
        check = "Jawaban tidak mengutip langsung; cocokkan isinya dengan sumber di bawah."
    sources = sorted(sources, key=lambda s: not s.get("dikutip"))   # quoted ones first
    with st.expander(f"Sumber ({len(sources)})", expanded=False):
        st.caption(check + " Sumber = potongan transkrip dan butir terverifikasi yang dibaca agent; "
                   "yang bertanda DIKUTIP dipakai di kutipan jawaban.")
        for r in verifikasi.get("kutipan") or []:
            note = (" (atribusi di jawaban dikoreksi kode)" if r.get("dikoreksi")
                    else " (rentang waktu di jawaban dipersempit ke lokasi asli)" if r.get("dirapikan") else "")
            more = " (kutipan muncul lebih dari sekali; ini kemunculan pertama)" if r.get("ambigu") and not r.get("ditulis") else ""
            st.markdown(f"\u201c{r['kutipan']}\u201d  \n**Lokasi di transkrip:** {r['speaker']}, {r['mulai']}-{r['selesai']}{note}{more}")
        shown_other = False
        for s in sources:
            if not s.get("dikutip") and not shown_other:
                shown_other = True
                st.markdown("**Dibaca agent, tidak dikutip di jawaban**")
            tag = " **[DIKUTIP]**" if s.get("dikutip") else ""
            if s.get("jenis") == "butir":
                st.markdown(f"**{s['butir']} {s['id']}** | {s.get('speaker') or '-'} | {s.get('mulai') or '-'}{tag}  \n"
                            f"{s['isi']}  \n> {s['kutipan']}")
            else:
                weak = " (kemiripan rendah)" if s.get("relevansi") == "rendah" else ""
                st.markdown(f"Potongan transkrip ({s.get('speaker') or '-'}, {s['mulai']}-{s['selesai']}){weak}{tag}  \n> "
                            + s["teks"].replace("\n", "  \n> "))


def run_caption(m: dict) -> str:
    """'Menunggu persetujuan Anda | ekstrak_poin_meeting x3, ekspor_laporan | 4 iterasi | 41,9 dtk'."""
    from collections import Counter
    counts = Counter(m.get("tools") or [])
    tools = ", ".join(f"{name} x{n}" if n > 1 else name for name, n in counts.items()) or "tanpa tool"
    label = status_text(m["status"])
    parts = [label[:1].upper() + label[1:], tools]
    if m.get("iterations"):
        parts.append(f"{m['iterations']} iterasi")
    if m.get("latency_ms"):
        parts.append(f"{m['latency_ms'] / 1000:.1f} dtk".replace(".", ","))
    return " | ".join(parts)


# Layout

left, right = st.columns([3, 2], gap="large")

with left:
    for m in st.session_state.agent_messages:
        if m.get("status") == "approval":
            # Outcome of a button click: a status box, not a chat bubble.
            {"success": st.success, "error": st.error}.get(m.get("tone"), st.info)(m.get("tampil") or m["content"])
            continue
        with st.chat_message(m["role"], avatar=ASSISTANT_AVATAR if m["role"] == "assistant" else USER_AVATAR):
            if m["role"] == "user":
                st.markdown(user_html(m["content"]), unsafe_allow_html=True)
            elif m.get("status") == "awaiting_approval":
                st.markdown(waiting_text(m.get("approval")))
            else:
                st.markdown(m["content"])
            if m["role"] == "assistant" and m.get("status") not in (None, "approval", "error"):
                st.caption(run_caption(m))
            if m["role"] == "assistant" and m.get("sources") and m.get("status") == "completed":
                render_sources(m["sources"], m.get("verifikasi") or {})

    # Approval card: pending requests of this meeting, created here or from the CLI.
    for approval in api_client.pending_approvals(selected_id):
        p = approval["preview"]
        with st.container(border=True):
            st.markdown(f"#### Persetujuan diperlukan: `{approval['tool']}`")
            st.caption(f"approval_id {approval['approval_id']} · rekap {approval['rekap_id']}. "
                       "Agent tidak bisa menyetujui sendiri; tombol di bawah yang menjalankan aksi.")
            if p.get("peringatan"):
                st.warning(p["peringatan"])
            with st.form(f"form_{approval['approval_id']}"):
                isian = {}
                if approval["tool"] == "buat_task":
                    for it in p["items"]:
                        st.markdown(f"**{it['id']}** {it['isi']}  \n"
                                    f"<span style='color:#94a3b8;font-size:13px;'>PJ: {it['penanggung_jawab'] or '-'}"
                                    f" · tenggat: {it['tenggat'] or 'tidak disebut'} · {it['mulai']}</span>",
                                    unsafe_allow_html=True)
                        fill = {}
                        cols = st.columns(2)
                        if it["perlu_isi_penanggung_jawab"]:
                            fill["penanggung_jawab"] = cols[0].text_input(
                                "Penanggung jawab (wajib, kosong = item dilewati)", key=f"pj_{approval['approval_id']}_{it['id']}")
                        if it["perlu_cek_tenggat"]:
                            fill["tenggat"] = cols[1].text_input(
                                "Tenggat (opsional, YYYY-MM-DD)", key=f"tg_{approval['approval_id']}_{it['id']}",
                                placeholder="2026-10-31")
                        isian[it["id"]] = {k: v.strip() for k, v in fill.items() if v.strip()}
                else:
                    st.markdown(f"Kirim ke `{p['penerima']}` (mode `{p['mode']}`)  \n"
                                f"Subjek: {p['subjek']}  \nLampiran: "
                                + ", ".join(f"**{a['nama_file']}** ({a['ukuran_kb']} KB)" for a in
                                            (p["lampiran"] if isinstance(p["lampiran"], list)
                                             else [{"nama_file": p.get("nama_file"), "ukuran_kb": p.get("ukuran_kb")}])))
                b1, b2 = st.columns(2)
                ok = b1.form_submit_button("Setujui dan jalankan", type="primary", use_container_width=True)
                no = b2.form_submit_button("Tolak", use_container_width=True)
            err = st.session_state.get("agent_form_error")
            if err and err["id"] == approval["approval_id"]:
                st.error(err["pesan"])
            if ok or no:
                st.session_state.agent_form_error = None
                decide(approval, setuju=bool(ok), isian=isian)
                st.rerun()

    # Downloads for the active rekap
    rekap_id = st.session_state.agent_rekap_id
    if rekap_id:
        exports = api_client.list_exports(rekap_id)
        with st.expander(f"Unduhan laporan ({len(exports)} file)", expanded=bool(exports)):
            if not exports:
                st.caption("Belum ada file. Minta agent, misalnya: 'buat laporan PDF' atau 'ekspor subtitle SRT'.")
            for f in exports:
                data = api_client.download_export(rekap_id, f["nama_file"])
                if data is not None:
                    st.download_button(f"Unduh {f['nama_file']} ({f['ukuran_kb']} KB)", data=data,
                                       file_name=f["nama_file"], key=f"dl_{f['nama_file']}",
                                       use_container_width=True)
        tasks = api_client.list_tasks(selected_id)
        if tasks:
            with st.expander(f"Task meeting ini ({len(tasks)})"):
                st.dataframe([{"task": t["task_id"], "item": t["item_id"], "tugas": t["tugas"],
                               "PJ": f"{t['penanggung_jawab']} ({t['sumber_penanggung_jawab']})",
                               "tenggat": t["tenggat"] or "-", "waktu": t["mulai"]} for t in tasks],
                             hide_index=True, use_container_width=True)

    # Proactive next steps, built by code from the stored recap. A click sends the sentence as the user's own
    # message; the agent run and the approval card then work as always.
    if st.session_state.agent_rekap_id and not api_client.pending_approvals(selected_id):
        for sg in api_client.suggestions(selected_id, st.session_state.agent_rekap_id):
            with st.container(border=True):
                st.markdown(f"**Saran langkah berikutnya**  \n{sg['teks']}")
                if st.button(sg["tombol"], key=f"sg_{sg['id']}", type="primary"):
                    st.session_state.agent_pending_prompt = sg["prompt"]
                    st.rerun()

    st.markdown("<div style='color:#94a3b8;font-size:13px;margin-top:8px;'>Contoh permintaan:</div>",
                unsafe_allow_html=True)
    ex_cols = st.columns(2)
    for n, ex in enumerate(EXAMPLES):
        if ex_cols[n % 2].button(ex, key=f"ex_{ex}", use_container_width=True):
            st.session_state.agent_pending_prompt = ex
            st.rerun()

prompt = st.chat_input("Minta sesuatu ke agent, misalnya 'buat laporan Word lalu kirim ke email saya'")
prompt = prompt or st.session_state.agent_pending_prompt
if prompt:
    st.session_state.agent_pending_prompt = None
    with left:
        run_agent(prompt)
    st.rerun()

with right:
    st.markdown("### Jejak langkah agent")
    runs = [(i, m) for i, m in enumerate(st.session_state.agent_messages)
            if m["role"] == "assistant" and m.get("steps")]
    if not runs:
        st.caption("Setiap run agent akan tampil di sini: keputusan LLM per iterasi, tool beserta argumen dan "
                   "hasilnya, guardrail, dan latensi tiap langkah.")
    else:
        labels = {f"Run {n + 1}: {st.session_state.agent_messages[i - 1]['content'][:40]}": i
                  for n, (i, _) in enumerate(runs)}
        default = len(labels) - 1
        chosen = st.selectbox("Run", list(labels), index=default, label_visibility="collapsed")
        msg = st.session_state.agent_messages[labels[chosen]]
        render_steps(msg["steps"], key=msg["trace_id"])

    with st.expander("Status job transkripsi", expanded=False):
        jobs_table(api_client.list_jobs(limit=15))
