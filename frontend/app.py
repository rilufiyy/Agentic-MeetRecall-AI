"""
MeetRecall AI - Landing page.
"""
import streamlit as st

st.set_page_config(
    page_title="MeetRecall AI",
    layout="wide",
    initial_sidebar_state="expanded",
)

from utils.styles import inject          # noqa: E402
from utils.api_client import api_client  # noqa: E402

inject()

# Session state defaults
if "current_meeting_id" not in st.session_state:
    st.session_state.current_meeting_id = ""

# Hero banner
st.markdown("""
<div style="
    background: linear-gradient(135deg, #1e1b4b 0%, #4f46e5 55%, #7c3aed 100%);
    border-radius: 20px;
    padding: 48px 44px;
    margin-bottom: 32px;
    color: white;
">
    <h1 style="font-size:2.8rem; font-weight:900; margin:0 0 10px 0; color:white; letter-spacing:-1px;">
        MeetRecall AI
    </h1>
    <p style="font-size:1.1rem; opacity:0.88; margin:0; max-width:580px; line-height:1.7;">
        Ask questions about your meetings and get answers grounded in the transcript.
        Speaker-labelled transcription, full-text / vector / hybrid retrieval,
        and a RAG chatbot with cited sources.
    </p>
    <div style="margin-top:22px; display:flex; gap:10px; flex-wrap:wrap;">
        <span style="background:rgba(255,255,255,0.17); padding:5px 14px; border-radius:999px; font-size:13px; font-weight:600;">Gemini Transcribe</span>
        <span style="background:rgba(255,255,255,0.17); padding:5px 14px; border-radius:999px; font-size:13px; font-weight:600;">BM25 Full-text</span>
        <span style="background:rgba(255,255,255,0.17); padding:5px 14px; border-radius:999px; font-size:13px; font-weight:600;">FAISS Vector</span>
        <span style="background:rgba(255,255,255,0.17); padding:5px 14px; border-radius:999px; font-size:13px; font-weight:600;">Hybrid Search</span>
        <span style="background:rgba(255,255,255,0.17); padding:5px 14px; border-radius:999px; font-size:13px; font-weight:600;">Groq LLM</span>
        <span style="background:rgba(255,255,255,0.17); padding:5px 14px; border-radius:999px; font-size:13px; font-weight:600;">CPU-friendly</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Backend status
health = api_client.health()
status = health.get("status", "unreachable")

if status == "healthy":
    st.markdown("""<div class="success-box">
        Backend connected — ffmpeg ready, all systems operational.
    </div>""", unsafe_allow_html=True)
elif status == "degraded":
    st.markdown("""<div class="warn-box">
        Backend running but ffmpeg is missing — audio conversion may fail.<br>
        <small>Rebuild: <code>docker-compose up -d --build</code></small>
    </div>""", unsafe_allow_html=True)
else:
    st.error("Backend unreachable. Start with: docker-compose up -d")

st.markdown("<br>", unsafe_allow_html=True)

# Feature cards
col1, col2, col3 = st.columns(3, gap="large")

with col1:
    st.markdown("""
    <div class="feat-card">
        <div class="feat-title">Transcribe</div>
        <div class="feat-desc">
            Upload audio or video recordings and get a speaker-labelled transcript using
            <strong>Gemini 3.5 Transcribe</strong> (speaker labels included), or Whisper on Groq or
            locally with <strong>pyannote 3.1</strong>.
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="feat-card">
        <div class="feat-title">AI Chat (RAG)</div>
        <div class="feat-desc">
            Ask natural language questions about any meeting. Answers are grounded in
            the transcript via <strong>full-text, vector, or hybrid search</strong> +
            <strong>Groq LLM</strong> (local Qwen2 fallback) generation with cited sources.
        </div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="feat-card">
        <div class="feat-title">Retrieval Lab</div>
        <div class="feat-desc">
            Compare <strong>BM25 full-text</strong>, <strong>FAISS vector</strong>, and
            <strong>hybrid (RRF / weighted)</strong> search side by side, and measure them with
            <strong>Hit@k, Recall@k, MRR@k</strong> and abstain accuracy on an evaluation set.
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("""
<div class="feat-card" style="margin-top:18px;">
    <div class="feat-title">MeetRecall Agent</div>
    <div class="feat-desc">
        Agent dengan tool calling: memilih sendiri tool untuk ringkasan, keputusan, action items,
        statistik, dan <strong>ekspor laporan (PDF, DOCX, Markdown, SRT)</strong>. Membuat task dan
        mengirim email hanya setelah <strong>persetujuan Anda</strong>. Setiap langkah tercatat dan
        tampil di panel jejak langkah. Transkripsi berjalan sebagai job dengan notifikasi email.
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Quick start guide
with st.expander("Quick Start Guide", expanded=False):
    st.markdown("""
**1. Configure environment**
```bash
cp backend/.env.example backend/.env
# GEMINI_API_KEY    -- Gemini Transcribe (transcript + speaker labels)
# GROQ_API_KEY      -- RAG answers (openai/gpt-oss-20b) and Groq Whisper
# HUGGINGFACE_TOKEN -- optional, pyannote speaker labels for groq / local
```

**2. Start services**
```bash
docker-compose up -d --build
# UI  -> http://localhost:8503
# API -> http://localhost:8090/docs
```

**3. Transcribe a meeting**
- Open **1 Upload** from the sidebar
- Choose provider (Gemini = default, speaker labels included; Groq = fast Whisper; Local = offline)
- Upload your file, click **Start Transcription**
- Switch to **2 Hasil** once processing completes

**4. Explore**
- **3 AI Chat** -- ask questions about the meeting
- **4 Retrieval Lab** -- compare full-text, vector, and hybrid search

No transcript yet? Import `backend/sample_data/sprint_review_portal_mitra.txt`
from the Retrieval Lab (or `POST /api/transcript/import`).
    """)

# Sidebar
with st.sidebar:
    st.markdown("### Navigate")
    st.markdown("""
| Page | Function |
|---|---|
| **1 Upload** | Upload and transcribe |
| **2 Hasil** | View transcript and summary |
| **3 AI Chat** | RAG question answering |
| **4 Retrieval Lab** | Full-text vs vector vs hybrid |
| **5 Agent** | Agent tindak lanjut: rekap, laporan, task, email |
    """)
    st.divider()
    st.markdown("### Models")
    st.markdown("""
- whisper-large-v3-turbo (Groq) / local Whisper
- pyannote/speaker-diarization-3.1
- paraphrase-multilingual-MiniLM-L12-v2
- openai/gpt-oss-20b (Groq) / Qwen2-0.5B (local)
    """)