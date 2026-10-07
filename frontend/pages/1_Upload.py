"""
Page 1 - Upload and Transcribe

Steps:
  1. Choose provider (Gemini Transcribe | Groq Whisper | Local Whisper+Pyannote)
  2. Upload audio/video file
  3. Poll /api/jobs/{id} every 5 s: antre -> diproses -> selesai / gagal (W78 job queue,
     notification email to REPORT_EMAIL_TO when the job ends)
  4. Navigate to Results page to view transcript
"""
from __future__ import annotations

import time

import streamlit as st

st.set_page_config(
    page_title="Upload - MeetRecall AI",
    layout="wide",
)

from utils.styles import inject          
from utils.api_client import api_client  
from utils.agent_view import JOB_LABEL, jobs_table

inject()

# Session state
if "current_meeting_id" not in st.session_state:
    st.session_state.current_meeting_id = ""

# Page header
st.markdown("""
<h1 style="font-size:2.1rem; font-weight:900; margin-bottom:4px;">Upload and Transcribe</h1>
<p style="color:#94a3b8; font-size:1rem; margin-bottom:28px;">
    Upload an audio or video recording to start speaker-labelled transcription.
</p>
""", unsafe_allow_html=True)

# Step 1 - Provider selection
st.markdown("""
<div class="step-row">
    <span class="step-num">1</span>
    <span class="step-title">Choose Transcription Provider</span>
</div>
""", unsafe_allow_html=True)

_PROVIDERS = {
    "Gemini 3.5 Transcribe (transkripsi + label pembicara di cloud, disarankan untuk CPU)": "gemini",
    "Groq Whisper + Pyannote (cloud ASR, label pembicara lokal)": "groq",
    "Groq Whisper saja (paling cepat, tanpa label pembicara)": "groq_fast",
    "Local - Whisper + Pyannote (gratis offline, berat di CPU)": "local",
}
_INFO = {
    "gemini": "<strong>Gemini 3.5 Transcribe</strong>: transkripsi, label pembicara, dan timestamp "
              "dalam satu panggilan API, sehingga laptop tidak memproses audio.<br>"
              "Butuh <code>GEMINI_API_KEY</code>. Maksimal 30 menit per file. Tersedia free tier; "
              "pada free tier, data dapat dipakai Google untuk meningkatkan produknya.",
    "groq": "<strong>Whisper Large v3 Turbo di Groq API</strong> untuk transkripsi, "
            "<strong>pyannote/speaker-diarization-3.1</strong> lokal untuk label pembicara.<br>"
            "Butuh <code>GROQ_API_KEY</code>; label pembicara butuh <code>HUGGINGFACE_TOKEN</code> "
            "(tanpa token, semua segmen menjadi Speaker 1). Audio dikirim ke Groq.",
    "groq_fast": "<strong>Whisper Large v3 Turbo di Groq API</strong> tanpa diarization.<br>"
                 "Paling ringan untuk laptop CPU. Butuh <code>GROQ_API_KEY</code>. "
                 "Semua segmen berlabel Speaker 1. Audio dikirim ke Groq.",
    "local": "<strong>Whisper lokal</strong> (LOCAL_WHISPER_MODEL) + "
             "<strong>pyannote/speaker-diarization-3.1</strong>.<br>"
             "Gratis dan privat, tetapi sangat lambat di CPU. Cocok bila tersedia GPU.",
}

col_l, col_r, _ = st.columns([1.4, 1, 0.6])
with col_l:
    provider_label = st.radio(
        "Provider",
        list(_PROVIDERS),
        index=0,
        label_visibility="collapsed",
    )
provider = _PROVIDERS[provider_label]

_avail = api_client.providers()
_status = (_avail.get("transcription") or {}).get(provider, {})
st.markdown(f"""<div class="info-box">{_INFO[provider]}</div>""", unsafe_allow_html=True)
if _status and not _status.get("ready", True):
    st.warning(f"Provider ini belum siap: {_status.get('note', '')}.")
elif provider == "groq" and _status and not _status.get("speaker_labels"):
    st.info("HUGGINGFACE_TOKEN belum diisi, jadi label pembicara tidak tersedia (Speaker 1 semua).")
if _avail.get("llm"):
    st.caption(f"LLM untuk AI Chat: {_avail['llm']}")

st.markdown("<br>", unsafe_allow_html=True)

# Step 2 - Upload file
st.markdown("""
<div class="step-row">
    <span class="step-num">2</span>
    <span class="step-title">Upload Recording</span>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Supported formats: MP4, MKV, MOV, AVI, MP3, WAV, M4A, WEBM",
    type=["mp4", "mkv", "mov", "avi", "mp3", "wav", "m4a", "webm"],
)

source_url = st.text_input(
    "URL YouTube sumber (opsional)",
    placeholder="https://www.youtube.com/watch?v=... atau https://youtu.be/...",
    help="Hanya untuk mencantumkan sumber: judul video, kanal, dan tautan masuk ke laporan dan email. "
         "Video tidak diunduh dari tautan ini; file tetap diunggah di atas.",
)

col_btn, _ = st.columns([1, 3])
with col_btn:
    start_btn = st.button(
        "Start Transcription",
        type="primary",
        disabled=uploaded_file is None,
        use_container_width=True,
    )

if start_btn and uploaded_file:
    with st.spinner("Uploading to backend..."):
        result = api_client.upload_file(uploaded_file, provider=provider, source_url=source_url)

    if "error" in result:
        st.error(f"Upload failed: {result['error']}")
    else:
        meeting_id = result["meeting_id"]
        src = result.get("source")
        if not src:
            src_line = ""
        elif src.get("judul"):
            src_line = f"Sumber: {src['judul']} ({src.get('kanal') or 'kanal tidak diketahui'})<br>"
        else:
            src_line = "Sumber: tautan tersimpan, judul tidak bisa diambil dari YouTube (laporan memakai nama file)<br>"
        st.session_state.current_meeting_id = meeting_id
        st.session_state["_poll_mid"] = meeting_id
        st.markdown(f"""<div class="success-box">
            <strong>Upload accepted.</strong><br>
            Meeting ID: <code>{meeting_id}</code><br>
            {src_line}
            <small>Job transkripsi masuk antrean - status di bawah. Email notifikasi dikirim saat selesai.</small>
        </div>""", unsafe_allow_html=True)
        time.sleep(0.4)
        st.rerun()

st.divider()

# Job queue (W78): visible even before a Meeting ID is chosen
st.markdown("""
<div class="step-row">
    <span class="step-num">3</span>
    <span class="step-title">Antrean Job Transkripsi</span>
</div>
""", unsafe_allow_html=True)
jobs_table(api_client.list_jobs(limit=10))
st.caption("Job dijalankan satu per satu. Saat selesai atau gagal, notifikasi dikirim ke REPORT_EMAIL_TO.")

st.divider()

# Step 4 - Status polling
st.markdown("""
<div class="step-row">
    <span class="step-num">4</span>
    <span class="step-title">Processing Status</span>
</div>
""", unsafe_allow_html=True)

mid_input = st.text_input(
    "Meeting ID",
    placeholder="Auto-filled after upload - or paste an existing ID",
    key="_poll_mid",
)

if not mid_input:
    st.markdown("""<div class="info-box">
        Upload a file above, or paste a Meeting ID to check status.
    </div>""", unsafe_allow_html=True)
    st.stop()

# Sync current_meeting_id with whatever is in the text input
st.session_state.current_meeting_id = mid_input

status_data = api_client.get_status(mid_input)
if "error" in status_data:
    st.error(status_data["error"])
    st.stop()

# Job row (W78). Meetings imported or transcribed before W78 have no job row.
job = api_client.get_job(mid_input)
job = job if "error" not in job else {}
status = {"queued": "antre", "processing": "diproses", "completed": "selesai",
          "failed": "gagal"}.get(status_data.get("status"), status_data.get("status", "unknown"))
status = job.get("status", status)

# Metrics row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Status job", JOB_LABEL.get(status, status.upper()))
c2.metric("Provider", status_data.get("provider", "-").upper())
c3.metric("Duration", f"{status_data.get('duration', 0):.1f}s")
c4.metric("File",     (status_data.get("filename", "-") or "-")[:20])
if job.get("notifikasi"):
    st.caption(f"Notifikasi email: {job['notifikasi']}")

st.markdown("<br>", unsafe_allow_html=True)

# Status-specific UI
if status == "antre":
    st.markdown("""
    <div class="proc-box">
        <h3 style="color:#fbbf24; margin:0 0 8px 0;">Menunggu antrean</h3>
        <p style="color:#cbd5e1; font-size:14px; margin:0; line-height:1.7;">
            Job dijalankan satu per satu. File ini mulai diproses setelah job sebelumnya selesai.<br>
            Halaman diperbarui otomatis tiap <strong>5 detik</strong>.
        </p>
    </div>
    """, unsafe_allow_html=True)
    time.sleep(5)
    st.rerun()

elif status == "diproses":
    st.markdown("""
    <div class="proc-box">
        <h3 style="color:#fbbf24; margin:0 0 8px 0;">Transcription in Progress</h3>
        <p style="color:#cbd5e1; font-size:14px; margin:0; line-height:1.7;">
            The AI is processing your recording.<br>
            This page auto-refreshes every <strong>5 seconds</strong>.<br>
            Local models may take several minutes depending on file length.
        </p>
    </div>
    """, unsafe_allow_html=True)
    time.sleep(5)
    st.rerun()

elif status == "gagal":
    st.error("Transcription failed. Please re-upload the file and try again."
             + (f" Penyebab: {job['error']}" if job.get("error") else ""))

elif status == "selesai":
    st.markdown("""<div class="success-box">
        <strong>Transcription complete.</strong>
        Your meeting has been indexed for AI Chat and Retrieval Lab.
    </div>""", unsafe_allow_html=True)
    st.markdown("""<div class="info-box" style="margin-top:12px;">
        Open <strong>2 Hasil</strong> in the sidebar to view the transcript and summary.<br>
        Or head to <strong>3 AI Chat</strong> to ask questions about this meeting,
        or <strong>5 Agent</strong> for summaries, reports, tasks, and email.
    </div>""", unsafe_allow_html=True)
