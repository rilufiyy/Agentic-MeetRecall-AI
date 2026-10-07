"""
Page 3 - AI Chat (RAG) - meeting intelligence edition.

Renders structured response (Section A/B):
  transcription_summary, key_actions, keywords, sources

Sidebar (Section E): speaker chart + retrieval settings.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd

st.set_page_config(page_title="AI Chat - MeetRecall AI", layout="wide")

from utils.styles import ASSISTANT_AVATAR, USER_AVATAR, inject, user_html
from utils.api_client import api_client
from utils.timefmt import fmt_range

inject()

# Optional URL parameters, used by scripts/run_demo_session.py for reproducible
# screenshots: ?meeting=<id>&q=<question>&mode=hybrid&min_score=0.40&open_sources=1
_qp = st.query_params


def _qp_float(name: str, default: float) -> float:
    try:
        return float(_qp.get(name, default))
    except (TypeError, ValueError):
        return default


_OPEN_SOURCES = _qp.get("open_sources") == "1"

for _k, _v in [("current_meeting_id",""),("chat_messages",[]),("chat_meeting_id","")]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _render_assistant(msg: dict) -> None:
    """Render AI chat response — clean prose first, details in collapsed sections."""
    # Main answer as natural prose
    answer = msg.get("transcription_summary", "")
    st.markdown(answer)
    # Follow-up questions are rewritten into a standalone question before retrieval.
    if msg.get("retrieval_query"):
        st.caption(f"Kueri retrieval: {msg['retrieval_query']}")

    # Action items — collapsed by default unless there are any
    actions = msg.get("key_actions", [])
    if actions:
        with st.expander(f"Action Items ({len(actions)})", expanded=False):
            for item in actions:
                st.markdown(f"- {item}")

    # Keywords — always collapsed so chat feels clean
    kws = msg.get("keywords", [])
    if kws:
        with st.expander("Keywords", expanded=False):
            tags = " ".join(
                f'<span style="background:rgba(139,92,246,0.2);color:#c4b5fd;padding:2px 8px;'
                f'border-radius:12px;font-size:12px;margin:2px;display:inline-block;">'
                f'{kw}</span>'
                for kw in kws
            )
            st.markdown(tags, unsafe_allow_html=True)

    # Source citations — always collapsed
    srcs = msg.get("sources", [])
    mode = msg.get("retrieval_mode", "")
    if srcs:
        label = f"Sumber Transkripsi ({len(srcs)} kutipan"
        label += f", mode {mode}{', reranked' if msg.get('reranked') else ''})" if mode else ")"
        with st.expander(label, expanded=_OPEN_SOURCES):
            for src in srcs:
                spk_name = src.get("speaker", "?")
                span     = fmt_range(src.get("start_time", 0), src.get("end_time", 0))
                text     = src.get("text", "")
                details = []
                if src.get("vector_score") is not None:
                    details.append(f"cosine {src['vector_score']:.3f}")
                if src.get("keyword_score") is not None:
                    details.append(f"BM25 {src['keyword_score']:.2f}")
                if src.get("rerank_score") is not None:
                    details.append(f"rerank {src['rerank_score']:.2f}")
                if src.get("matched_terms"):
                    details.append("kata cocok: " + ", ".join(src["matched_terms"]))
                st.markdown(
                    f"**{spk_name}** · `{span}`"
                    + (f" _({' | '.join(details)})_" if details else "")
                    # A chunk holds several "Speaker: text" lines; keep each on its own line.
                    + "\n\n" + "\n".join(f"> {line}  " for line in text.split("\n"))
                )
    if msg.get("abstained"):
        st.caption("Retrieval menolak menjawab karena tidak ada bagian transkrip yang cukup relevan.")


with st.sidebar:
    st.markdown("### Pilih Meeting")
    meetings  = api_client.list_meetings()
    completed = [m for m in meetings if m.get("status") == "completed"]
    if completed:
        opts = {f"{m['filename']} ({m['meeting_id'][:8]}...)": m["meeting_id"] for m in completed}
        _want = _qp.get("meeting") or st.session_state.current_meeting_id
        def_k = next((k for k, v in opts.items() if v == _want), list(opts.keys())[0])
        sel_lbl = st.selectbox("Meeting", list(opts.keys()), index=list(opts.keys()).index(def_k), label_visibility="collapsed")
        selected_id = opts[sel_lbl]
    else:
        selected_id = st.text_input("Meeting ID", value=st.session_state.current_meeting_id, placeholder="Paste meeting ID here", label_visibility="collapsed")
    st.divider()
    st.markdown("### Retrieval")
    top_k = st.slider("Jumlah kutipan (top_k)", 1, 10, int(_qp_float("top_k", 3)),
                      help="Berapa segmen transkrip paling relevan yang dipakai sebagai konteks jawaban.")
    _mode_labels = {"Hybrid (BM25 + vector)": "hybrid", "Vector (FAISS)": "vector",
                    "Full-text (BM25)": "fulltext"}
    _mode_idx = {"hybrid": 0, "vector": 1, "fulltext": 2}.get(_qp.get("mode", "hybrid"), 0)
    retrieval_mode = _mode_labels[st.selectbox("Metode retrieval", list(_mode_labels), index=_mode_idx)]
    fusion, alpha = "rrf", 0.5
    if retrieval_mode == "hybrid":
        fusion = st.radio("Fusi", ["rrf", "weighted"], horizontal=True,
                          index=1 if _qp.get("fusion") == "weighted" else 0,
                          help="RRF memakai peringkat; weighted memakai skor ternormalisasi.")
        if fusion == "weighted":
            alpha = st.slider("alpha (bobot vector)", 0.0, 1.0, _qp_float("alpha", 0.5), 0.05)
    min_score = st.slider("Ambang penolakan (cosine)", 0.0, 0.8, _qp_float("min_score", 0.40), 0.05,
                          help="0 = nonaktif. Di atas 0, pertanyaan yang tidak cukup mirip "
                               "dengan isi meeting dijawab 'tidak ditemukan'.")
    expand_neighbors = st.slider("Segmen tetangga sebagai konteks", 0, 3, 1)
    rerank = st.toggle("Rerank (cross-encoder)", value=_qp.get("rerank") == "1",
                       help="Tahap kedua; model diunduh saat pertama dipakai.")
    retrieval_settings = {
        "retrieval_mode": retrieval_mode, "fusion": fusion, "alpha": alpha,
        "min_score": min_score, "expand_neighbors": expand_neighbors, "rerank": rerank,
    }
    if st.button("Clear chat history", use_container_width=True):
        st.session_state.chat_messages = []
        st.rerun()

    if selected_id:
        # --- Speaker distribution chart (Section E) ---
        st.divider()
        st.markdown("### Speaker Distribution")
        _t = api_client.get_transcript(selected_id)
        if _t.get("status") not in ("processing","failed") and "segments" in _t:
            _cnt: dict = {}
            for seg in _t["segments"]:
                spk = seg.get("speaker","Unknown")
                _cnt[spk] = _cnt.get(spk, 0) + 1
            if _cnt:
                st.bar_chart(pd.DataFrame({"Segmen": _cnt.values()}, index=list(_cnt.keys())), color="#6366f1")


if selected_id != st.session_state.chat_meeting_id:
    st.session_state.chat_messages = []
    st.session_state.chat_meeting_id = selected_id
if selected_id:
    st.session_state.current_meeting_id = selected_id

st.markdown("<h1 style='font-size:2.1rem;font-weight:900;'>AI Chat</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#94a3b8;font-size:1rem;margin-bottom:8px;'>Tanya jawab seputar isi meeting menggunakan RAG (BM25 + FAISS + Groq LLM).</p>", unsafe_allow_html=True)

if not selected_id:
    st.info("Belum ada meeting yang dipilih. Upload file di halaman 1 Upload terlebih dahulu.")
    st.stop()

st.markdown(f"<p style='color:#94a3b8;font-size:13px;'>Meeting ID: <code>{selected_id}</code></p>", unsafe_allow_html=True)
st.divider()

for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"], avatar=ASSISTANT_AVATAR if msg["role"] == "assistant" else USER_AVATAR):
        if msg["role"] == "assistant":
            _render_assistant(msg)
        else:
            st.markdown(user_html(msg["content"]), unsafe_allow_html=True)

prompt = st.chat_input("Tanyakan sesuatu tentang meeting ini...")
if not prompt and _qp.get("q") and not st.session_state.get("_qp_question_done"):
    prompt = _qp.get("q")
    st.session_state._qp_question_done = True
if prompt:
    st.session_state.chat_messages.append({"role":"user","content":prompt})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(user_html(prompt), unsafe_allow_html=True)
    # Extract last 3 Q&A turns for conversation memory
    _msgs = st.session_state.chat_messages
    _history = []
    for _i, _m in enumerate(_msgs[:-1] if _msgs else []):
        if _m["role"] == "user" and _i + 1 < len(_msgs) and _msgs[_i + 1]["role"] == "assistant":
            _history.append({
                "question": _m["content"],
                "answer": _msgs[_i + 1].get("transcription_summary", ""),
            })
    _history = _history[-3:] or None

    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        with st.spinner("Mencari konteks dan membuat jawaban..."):
            resp = api_client.rag_chat(selected_id, prompt, top_k=top_k, history=_history,
                                       retrieval=retrieval_settings)
        if "error" in resp:
            md = {"role": "assistant", "transcription_summary": f"Error: {resp.get('error', '')}", "key_actions": [], "keywords": [], "sources": []}
        else:
            md = {"role":"assistant","transcription_summary":resp.get("transcription_summary","Tidak ada jawaban."),"key_actions":resp.get("key_actions",[]),"keywords":resp.get("keywords",[]),"sources":resp.get("sources",[]),
                  "retrieval_mode":resp.get("retrieval_mode",""),"reranked":resp.get("reranked",False),"abstained":resp.get("abstained",False),
                  "retrieval_query":resp.get("retrieval_query","") if resp.get("retrieval_query","") != prompt else ""}
        _render_assistant(md)
    st.session_state.chat_messages.append(md)