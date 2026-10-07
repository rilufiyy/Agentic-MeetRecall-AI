"""
Page 6 - Retrieval Lab

Eksperimen knowledge retrieval pada transkrip meeting:
  - Bandingkan hasil full-text (BM25), vector (FAISS), dan hybrid untuk satu kueri
  - Jalankan set evaluasi berlabel dan lihat Hit@k, Recall@k, MRR@k per metode

Transkrip bisa berasal dari audio yang sudah diproses, atau diimpor langsung
dari file .txt (contoh: backend/sample_data/sprint_review_portal_mitra.txt).
"""
from __future__ import annotations

import html
import json
import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Retrieval Lab - MeetRecall AI", layout="wide")

from utils.styles import inject
from utils.api_client import api_client
from utils.timefmt import fmt_range

inject()

if "current_meeting_id" not in st.session_state:
    st.session_state.current_meeting_id = ""

MODE_LABEL = {"fulltext": "Full-text (BM25)", "vector": "Vector (FAISS)", "hybrid": "Hybrid"}

# Optional URL parameters, used by scripts/run_demo_session.py for reproducible
# screenshots: ?meeting=<id>&q=<query>&top_k=5&fusion=rrf&alpha=0.5&run=1
_qp = st.query_params


def _qp_float(name: str, default: float) -> float:
    try:
        return float(_qp.get(name, default))
    except (TypeError, ValueError):
        return default

# Sidebar
with st.sidebar:
    st.markdown("### Impor Transkrip")
    up = st.file_uploader("File transkrip (.txt / .json)", type=["txt", "json"],
                          help="Format baris: [hh:mm:ss] Speaker: teks")
    if up is not None and st.button("Impor sebagai meeting", use_container_width=True):
        res = api_client.import_transcript(up)
        if "error" in res:
            st.error(res["error"])
        else:
            st.session_state.current_meeting_id = res["meeting_id"]
            st.success(f"{res['num_segments']} segmen terindeks.")
            st.rerun()

    st.divider()
    st.markdown("### Pilih Meeting")
    meetings = api_client.list_meetings()
    completed = [m for m in meetings if m.get("status") == "completed"]
    meeting_id = ""
    meeting_filename = ""
    if completed:
        opts = {f"{m['filename']} ({m['meeting_id'][:8]}...)": m["meeting_id"] for m in completed}
        want = _qp.get("meeting") or st.session_state.current_meeting_id
        def_k = next((k for k, v in opts.items() if v == want), list(opts.keys())[0])
        sel = st.selectbox("Meeting", list(opts.keys()), index=list(opts.keys()).index(def_k),
                           label_visibility="collapsed")
        meeting_id = opts[sel]
        meeting_filename = next(m.get("filename", "") for m in completed if m["meeting_id"] == meeting_id)
        st.session_state.current_meeting_id = meeting_id

    st.divider()
    st.markdown("### Pengaturan Hybrid")
    fusion = st.radio("Metode fusi", ["rrf", "weighted"], horizontal=True,
                      index=1 if _qp.get("fusion") == "weighted" else 0,
                      help="RRF: gabungkan peringkat. Weighted: gabungkan skor ternormalisasi.")
    alpha = 0.5
    rrf_k = 60
    if fusion == "weighted":
        alpha = st.slider("alpha (bobot vector)", 0.0, 1.0, _qp_float("alpha", 0.5), 0.05)
    else:
        rrf_k = st.number_input("Konstanta RRF (k)", 1, 500, 60)
    rerank = st.toggle("Rerank cross-encoder", value=_qp.get("rerank") == "1")

st.markdown("<h1 style='font-size:2.1rem;font-weight:900;'>Retrieval Lab</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='color:#94a3b8;font-size:1rem;margin-bottom:8px;'>"
    "Bandingkan full-text search, vector search, dan hybrid search pada transkrip yang sama.</p>",
    unsafe_allow_html=True,
)

if not meeting_id:
    st.info("Belum ada meeting. Impor transkrip contoh dari sidebar atau upload audio di halaman 1.")
    st.stop()

settings = {"fusion": fusion, "alpha": alpha, "rrf_k": int(rrf_k), "rerank": rerank}


def _highlight(text: str, terms: list[str]) -> str:
    safe = html.escape(text)
    for t in sorted(set(terms), key=len, reverse=True):
        if len(t) < 2:
            continue
        safe = re.sub(rf"(?i)(?<![\w-])({re.escape(html.escape(t))})(?![\w-])",
                      r"<mark style='background:#fde68a;color:#1e293b;padding:0 2px;'>\1</mark>", safe)
    return safe


tab_compare, tab_eval = st.tabs(["Bandingkan Metode", "Evaluasi Berlabel"])

# Tab 1: side-by-side comparison
with tab_compare:
    # The example queries only fit the sample transcript, so other meetings get none.
    is_sample = "sprint_review_portal_mitra" in meeting_filename
    c1, c2 = st.columns([4, 1])
    query = c1.text_input("Kueri", value=_qp.get("q", ""),
                          placeholder="contoh: Apa isu di tiket MR-241?" if is_sample
                          else "Tulis pertanyaan tentang isi meeting ini")
    top_k = c2.number_input("top_k", 1, 20, int(_qp_float("top_k", 5)))
    if is_sample:
        examples = ["Apa isu di tiket MR-241?", "Kenapa pelanggan menerima surel duplikat?",
                    "Tanggal berapa v2.4.1 dirilis?", "Who will fix the duplicate email bug?"]
        st.caption("Contoh kueri: " + " | ".join(examples))

    run_clicked = st.button("Jalankan", type="primary")
    if (run_clicked or _qp.get("run") == "1") and query.strip():
        res = api_client.compare_retrieval(
            meeting_id, {"query": query, "top_k": int(top_k), **settings,
                         "modes": ["fulltext", "vector", "hybrid"]})
        if "error" in res:
            st.error(res["error"])
        else:
            results = res["results"]
            id_sets = [{c["chunk_id"] for c in r["chunks"]} for r in results]
            common = set.intersection(*id_sets) if id_sets else set()
            st.caption(f"Segmen yang muncul di ketiga metode: {sorted(common) or 'tidak ada'}")
            cols = st.columns(len(results))
            for col, r in zip(cols, results):
                with col:
                    title = MODE_LABEL.get(r["mode"], r["mode"])
                    if r.get("reranked"):
                        title += " + rerank"
                    st.markdown(f"#### {title}")
                    st.caption(f"latensi {r['latency_ms']:.1f} ms")
                    if not r["chunks"]:
                        st.warning("Tidak ada hasil" + (f" ({r['abstain_reason']})"
                                                         if r.get("abstain_reason") else ""))
                    for ch in r["chunks"]:
                        scores = []
                        if ch.get("keyword_score") is not None:
                            scores.append(f"BM25 {ch['keyword_score']:.2f}")
                        if ch.get("vector_score") is not None:
                            scores.append(f"cos {ch['vector_score']:.3f}")
                        if r["mode"] == "hybrid":
                            scores.append(f"fusi {ch['score']:.4f}")
                        if ch.get("rerank_score") is not None:
                            scores.append(f"rerank {ch['rerank_score']:.2f}")
                        body = _highlight(ch["text"], ch.get("matched_terms", []))
                        st.markdown(
                            f"<div style='border:1px solid #334155;border-radius:10px;"
                            f"padding:8px 10px;margin-bottom:8px;background:#1e293b;'>"
                            f"<div style='font-size:12px;color:#94a3b8;'>#{ch['rank']} &middot; "
                            f"segmen {ch['chunk_id']} &middot; {html.escape(ch['speaker'])} @ "
                            f"{fmt_range(ch['start_time'], ch.get('end_time', 0))}</div>"
                            f"<div style='font-size:14px;margin:4px 0;'>{body}</div>"
                            f"<div style='font-size:11px;color:#a5b4fc;'>{' | '.join(scores)}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

# Tab 2: labelled evaluation
with tab_eval:
    st.markdown(
        "Unggah set evaluasi JSON (contoh: `backend/sample_data/retrieval_eval_set.json`). "
        "Setiap kasus memuat kueri, kategori, dan fragmen teks segmen yang relevan."
    )
    eval_file = st.file_uploader("Set evaluasi (.json)", type=["json"], key="eval_set")
    e1, e2 = st.columns(2)
    k = e1.number_input("k (top-k yang dinilai)", 1, 20, 3)
    min_score = e2.slider("Ambang penolakan (cosine)", 0.0, 0.8, 0.40, 0.05,
                          help="Dipakai untuk kasus di luar cakupan (expect_no_answer).")

    if eval_file is not None and st.button("Jalankan evaluasi", type="primary"):
        try:
            data = json.loads(eval_file.getvalue().decode("utf-8"))
            cases = data["cases"] if isinstance(data, dict) else data
        except Exception as exc:
            st.error(f"File tidak valid: {exc}")
            st.stop()
        with st.spinner(f"Mengevaluasi {len(cases)} pertanyaan x 3 metode..."):
            res = api_client.evaluate_retrieval(
                meeting_id, {"cases": cases, "k": int(k), "min_score": min_score, **settings})
        if "error" in res:
            st.error(res["error"])
            st.stop()

        summ = res["summary"]
        kk = res["k"]
        rows = []
        for mode, m in summ.items():
            rows.append({
                "Metode": MODE_LABEL.get(mode, mode),
                f"Hit@{kk}": m[f"hit@{kk}"], f"Recall@{kk}": m[f"recall@{kk}"],
                f"MRR@{kk}": m[f"mrr@{kk}"], "Akurasi penolakan": m["abstain_accuracy"],
                "Salah tolak": m.get("false_abstain_rate"),
                "Latensi (ms)": m["avg_latency_ms"],
            })
        df = pd.DataFrame(rows).set_index("Metode")
        st.markdown(f"#### Ringkasan ({res['n_answerable']} pertanyaan dapat dijawab, "
                    f"{res['n_cases'] - res['n_answerable']} di luar cakupan)")
        st.caption("Hit/Recall/MRR dihitung tanpa ambang penolakan. Ambang dinilai terpisah: "
                   "akurasi penolakan (di luar cakupan) dan salah tolak (seharusnya dijawab).")
        st.dataframe(df.style.format("{:.3f}", na_rep="-"), use_container_width=True)
        st.bar_chart(df[[f"Hit@{kk}", f"Recall@{kk}", f"MRR@{kk}"]].T, stack=False)

        st.markdown(f"#### Hit@{kk} per kategori pertanyaan")
        cat_rows = {}
        for mode, m in summ.items():
            for cat, v in m["by_category"].items():
                cat_rows.setdefault(cat, {"n": v["n"]})[MODE_LABEL.get(mode, mode)] = v[f"hit@{kk}"]
        st.dataframe(pd.DataFrame(cat_rows).T, use_container_width=True)

        st.markdown("#### Detail per pertanyaan")
        pq = pd.DataFrame(res["per_query"])
        pq["hasil"] = pq.apply(
            lambda r: ("tolak" if r["abstained"] else "jawab") if pd.isna(r["hit"])
            else ("kena" if r["hit"] else "meleset") + (" (ditolak ambang)" if r["abstained"] else ""),
            axis=1)
        pivot = pq.pivot_table(index=["id", "category", "query"], columns="mode",
                               values="hasil", aggfunc="first")
        pivot = pivot[[m for m in summ if m in pivot.columns]].reset_index()
        pivot.columns = [MODE_LABEL.get(c, c) for c in pivot.columns]
        st.dataframe(pivot, use_container_width=True, hide_index=True)
        st.download_button("Unduh hasil (JSON)", json.dumps(res, indent=2, ensure_ascii=False),
                           file_name="retrieval_eval_results.json", mime="application/json")
