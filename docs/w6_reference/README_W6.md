## MeetRecall AI Improvement

This project is an extension and architectural improvement of my original project, 
[MeetRecall AI](https://github.com/rilufiyy/MeetRecall-AI), which I previously developed independently. The system was significantly expanded into a full Meeting Intelligence Platform, 
adding a RAG-based chatbot. This branch focuses on **RAG & Knowledge Retrieval**:
full-text (BM25), vector (FAISS), and hybrid search, with an evaluation lab to compare them.

---

## Table of Contents

1. [Features](#features)
2. [NLP Pipeline](#nlp-pipeline)
3. [Models Used](#models-used)
4. [Dataset](#dataset)
5. [Quick Start](#quick-start)
6. [API Reference](#api-reference)
7. [Project Structure](#project-structure)
8. [Sample Output](#sample-output)

---

## Features

| Feature | Description |
|---|---|
| **Transcription** | Upload audio/video → speaker-labelled transcript (Gemini 3.5 Transcribe, Groq Whisper, local Whisper, or AssemblyAI) |
| **RAG Chatbot** | Ask questions about a meeting → grounded answer + cited source chunks |
| **Hybrid Retrieval** | Choose full-text (BM25), vector (FAISS), or hybrid search (RRF / weighted fusion), with optional reranking and an abstain threshold |
| **Retrieval Lab** | Compare the three retrieval methods side by side and evaluate them on a labelled question set (Hit@k, Recall@k, MRR@k) |

---

## NLP Pipeline

See **[MeetRecall AI RAG_Flowchart.png](MeetRecall%20AI%20RAG_Flowchart.png)** for the full visual diagram.

![RAG Pipeline](MeetRecall%20AI%20RAG_Flowchart.png)

```
Audio / Video Input (MP4 · MKV · MP3 · WAV · M4A · WEBM · OGG · FLAC)     Transcript .txt / .json
        │                                                                   │
        ▼                                                                   │ POST /api/transcript/import
  Provider Selection                                                        │
   gemini (default) : Gemini 3.5 Transcribe → text + speakers + word times  │
   groq / groq_fast : Groq Whisper Large v3 Turbo (+ pyannote 3.1)          │
   local            : FFmpeg 16 kHz WAV → local Whisper + pyannote 3.1      │
   assemblyai       : AssemblyAI Universal-3 Pro (optional)                 │
        │                                                                   │
        ▼                                                                   ▼
Speaker-labelled Transcript  [{speaker, start, end, text}]  →  JSON storage (data/meetings/)
        │
        ▼  chunking: ~60-word windows, 1-segment overlap; one chunk list, shared chunk_id
   ┌────┴─────────────────────────────┐
   ▼                                  ▼
paraphrase-multilingual-MiniLM     BM25 keyword index
→ FAISS IndexFlatIP (cosine)       (speaker + text tokens)
   │  vector search                   │  full-text search
   └────────────┬─────────────────────┘
                ▼                            User question (Streamlit AI Chat)
                │                                          ▼
                │                            Query rewriting (follow-up): LLM rewrites
                │                            with chat history, skipped on first turn
                ▼                                          │
   Retrieval mode: vector | fulltext | hybrid ◄────────────┘
   (RRF k=60 or weighted alpha, candidate_k = 20)
                ▼
   Abstain check (cosine < min_score (default 0.40) and no chunk with ≥ 50% of the
   query terms?)  ── yes ──► "not found in transcript" (no LLM call)
                ▼ no
   Optional cross-encoder rerank (only when enabled)
                ▼  top_k = 3
   Neighbour expansion (adjacent chunks as extra context, ≤ 2400 chars)
                ▼
   openai/gpt-oss-20b on Groq (fallback: local Qwen2-0.5B-Instruct)
                ▼
   Q&A Response (answer + cited sources + keywords + action items)

Evaluation lab: labelled question set → all three modes → Hit@k · Recall@k · MRR@k ·
abstain accuracy → summary.md + charts (scripts/evaluate_retrieval.py, /api/rag/evaluate)
```

---
## Application Interface

### Main Interface
![Main Interface](documentations/main_interface.png)

### Upload Page
![Upload](documentations/upload.png)

### Processing Status
![Processing Status](documentations/processing_status.png)

---

## Transcription & Speaker Analysis

### Transcription Result
![Transcription Result](documentations/transcription_result.png)

### Speaker Transcription Detail
![Speaker Transcription](documentations/detail_speaker_transcription.png)

---

## RAG Chatbot

The system includes a Retrieval-Augmented Generation (RAG) chatbot that allows users to ask questions about meeting content.

Example queries:
- *"What decisions were made?"*
- *"What did Speaker A discuss?"*
- *"Summarize the meeting outcome."*

![RAG Chatbot](documentations/RAG_Chatbot.png)

---

## Knowledge Retrieval Experiments (Full-text, Vector, Hybrid)

This extension turns the RAG chatbot into a small retrieval lab. It is the companion
hands-on for the Tritronik Wiki article *RAG dan Knowledge Retrieval*.

### What was added

| Component | File | What it does |
|---|---|---|
| Chunking | `backend/services/chunking.py` | Merges consecutive transcript segments into chunks of about 60 words (`CHUNK_TARGET_WORDS`) with a one-segment overlap. One ASR segment is often a single short sentence, and the embedding model reads only 128 tokens, so the window stays small. Old indexes are rebuilt automatically on the next query. |
| Meeting-wide questions | `backend/services/rag_chain.py` | Questions about decisions, action items, or a summary read the whole transcript when it fits (≤ 12,000 characters) instead of only the top-k chunks; the retrieved chunks are still shown as citations. |
| Follow-up questions | `backend/services/rag_chain.py` | With chat history, the LLM first rewrites a follow-up ("Which league does he play in?") into a standalone question for retrieval; the chat shows it as "Kueri retrieval". Falls back to the original question if rewriting fails. |
| Full-text search | `backend/services/keyword_index.py` | Okapi BM25 over transcript chunks (speaker label + text). Tokenizer keeps codes such as `MR-218` or `v2.4.1` intact and drops Indonesian/English stopwords. No stemming, to keep behaviour transparent. |
| Retrieval service | `backend/services/retrieval.py` | `vector` (FAISS cosine), `fulltext` (BM25), `hybrid` (both). Hybrid fusion: **RRF** (rank based, `k=60`) or **weighted** (min-max normalised, `alpha` = weight of vector). Optional cross-encoder reranking, neighbour-chunk expansion, and an abstain threshold. |
| Evaluation | `backend/services/retrieval_eval.py`, `backend/scripts/evaluate_retrieval.py` | Hit@k, Recall@k, MRR@k per method and per question category; abstain accuracy and false-abstain rate for the threshold. |
| Sample data | `backend/sample_data/` | Synthetic Indonesian sprint-review transcript (56 segments, CC0) and a 26-question labelled set: keyword, paraphrase, mixed, cross-language, and out-of-scope questions. |
| Transcript import | `POST /api/transcript/import` | Load a `.txt` / `.json` transcript as a completed meeting, no audio needed. |
| UI | `frontend/pages/4_Retrieval_Lab.py`, `frontend/pages/3_AI_Chat.py` | Side-by-side comparison and evaluation page; retrieval settings in the chat sidebar. |

The FAISS index and the BM25 index are built from the same chunk list, so a
`chunk_id` means the same chunk in both and results can be fused by id.
Topic clustering and sentiment analysis were removed to keep the project focused on
retrieval (they remain available in the `main` branch history).

### Retrieval settings

| Setting | Default | Meaning |
|---|---|---|
| `retrieval_mode` | `hybrid` | `vector`, `fulltext`, or `hybrid` |
| `fusion` | `rrf` | `rrf` or `weighted` (hybrid only) |
| `rrf_k` | `60` | RRF constant; larger values flatten the advantage of top ranks |
| `alpha` | `0.5` | weighted fusion: `alpha * vector + (1 - alpha) * bm25` |
| `candidate_k` | `20` | candidates per method before fusion and reranking |
| `rerank` | `false` | second stage with `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (override with `RERANKER_MODEL`) |
| `min_score` | `0.40` | abstain when the best cosine similarity is below this value and no chunk matches at least half of the query terms (0 = off). 0.40 rejects all out-of-scope questions in the sample eval set with no false abstains; 0.35 let "resep rendang" through (best cosine 0.369). These numbers were measured with one-segment chunks, before chunking was added |
| `expand_neighbors` | `0` | attach N neighbouring chunks to each hit as LLM context (chat default in the UI: 1) |

> Note: the chat endpoint now defaults to `hybrid`. Send `"retrieval_mode": "vector"` to get the previous FAISS-only behaviour.

### Run the experiment

```bash
# 1. Start the stack as usual
docker compose up -d --build

# 2a. From the UI: open "6 Retrieval Lab", import
#     backend/sample_data/sprint_review_portal_mitra.txt from the sidebar,
#     then use the two tabs (comparison, labelled evaluation with
#     backend/sample_data/retrieval_eval_set.json).

# 2b. Or offline, without the UI (writes results to backend/results/retrieval_eval/)
docker compose exec backend python scripts/evaluate_retrieval.py --alpha-sweep
docker compose exec backend python scripts/evaluate_retrieval.py --rerank --k 5

# Unit tests (no model download needed)
docker compose exec backend python -m pytest tests -q
```

### Run a full demo session (answers, comparisons, evaluation, screenshots)

`backend/scripts/run_demo_session.py` runs from the host against the running stack and only
needs `requests`, `matplotlib`, and `playwright`. It sends every question of an evaluation set
through the three retrieval methods and the chatbot, runs the labelled evaluation and the alpha
sweep, and captures the Retrieval Lab, AI Chat, and Upload pages.

```bash
pip install requests matplotlib playwright && python -m playwright install chromium
python backend/scripts/run_demo_session.py --meeting-id <id> \
    --eval-set path/to/eval_set.json --screenshots
```

Results are written to `demo_results/<timestamp>/`. The AI Chat and Retrieval Lab pages also
accept URL parameters (for example `/Retrieval_Lab?meeting=<id>&q=...&run=1`), which the script
uses for reproducible screenshots.

Ranking metrics are computed with the threshold off, so they measure retrieval only.
The threshold is scored separately: abstain accuracy on out-of-scope questions and
false-abstain rate on answerable ones.

### Scope

Covered: full-text, vector, and hybrid retrieval; fusion; reranking; abstention; retrieval evaluation.
Not covered here: agentic RAG (retrieval as a tool chosen by an agent), which belongs to the
next onboarding topic, *Agentic AI & AI Orchestration*.

---

## Models Used

| Model | Source | Size | Purpose |
|---|---|---|---|
| `gemini-3.5-transcribe` (Gemini API) | [Google AI for Developers](https://ai.google.dev/gemini-api/docs/transcribe) | Cloud API | Transcription + speaker diarization for the `gemini` provider (recommended on CPU) |
| `whisper-large-v3-turbo` (Groq API) | [GroqDocs](https://console.groq.com/docs/model/whisper-large-v3-turbo) | Cloud API | ASR for the `groq` / `groq_fast` providers |
| `openai/whisper-large-v3` (local, `LOCAL_WHISPER_MODEL`) | [HuggingFace](https://huggingface.co/openai/whisper-large-v3) | ~3 GB | ASR for the `local` provider (use `openai/whisper-small` on CPU) |
| `openai/gpt-oss-20b` (Groq API) | [GroqDocs](https://console.groq.com/docs/models) | Cloud API | RAG answer generation when `GROQ_API_KEY` is set |
| `pyannote/speaker-diarization-3.1` | [HuggingFace](https://huggingface.co/pyannote/speaker-diarization-3.1) *(gated)* | ~370 MB | Speaker diarization |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | [HuggingFace](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | ~117 MB | Text embeddings — 384-dim, multilingual (EN + ID + 50 languages) |
| `Qwen/Qwen2-0.5B-Instruct` | [HuggingFace](https://huggingface.co/Qwen/Qwen2-0.5B-Instruct) | ~370 MB fp16 | Local LLM fallback — RAG answers without Groq |
| `google/flan-t5-base` | [HuggingFace](https://huggingface.co/google/flan-t5-base) | ~290 MB | Seq2Seq LLM fallback (override via `RAG_LLM_MODEL` env var) |
| AssemblyAI Universal-3 Pro | [AssemblyAI](https://www.assemblyai.com) | Cloud API | Fast cloud transcription with native speaker labels (optional) |

### Why these models?

- **whisper-small** — Best open-source ASR quality-to-size ratio; multilingual; runs on CPU without quantisation.
- **pyannote/speaker-diarization-3.1** — State-of-the-art speaker diarization; integrates cleanly with Whisper timestamps.
- **paraphrase-multilingual-MiniLM-L12-v2** — Only 117 MB; supports Indonesian and English natively; fast enough for real-time indexing; produces cosine-compatible L2-normalised vectors.
- **Qwen2-0.5B-Instruct** — Smallest instruction-tuned causal LLM with solid multilingual capability; chat template built-in; runs on CPU in fp16 within ~2 GB RAM.

---

## Dataset

### Source

User-uploaded meeting recordings (user-generated content).

#### Primary Dataset (Used in Testing)
Meeting recording sourced from YouTube: https://www.youtube.com/live/qGFoZ8yodc4?si=sdlA9fhfZe0a9ho2

##### Used for:
- transcription validation
- speaker diarization testing
- RAG retrieval evaluation

This dataset represents real conversational meeting data.

### Supported Input Formats

Any audio/video container supported by FFmpeg:

`.mp4` · `.mkv` · `.mov` · `.avi` · `.mp3` · `.wav` · `.m4a` · `.webm` · `.ogg` · `.flac`

### Annotation Method

Speaker labels are produced **automatically** — no manual annotation required:

| Provider | Method |
|---|---|
| Local | Pyannote diarization assigns `SPEAKER_00`, `SPEAKER_01`, … via timestamp overlap |
| AssemblyAI | Native speaker labelling built into the Universal-3 Pro model |

### License

| Component | License |
|---|---|
| openai/whisper-small | [MIT](https://github.com/openai/whisper/blob/main/LICENSE) |
| pyannote/speaker-diarization-3.1 | [MIT](https://huggingface.co/pyannote/speaker-diarization-3.1) — model weights require HuggingFace account acceptance |
| sentence-transformers, paraphrase-multilingual-MiniLM-L12-v2 | [Apache-2.0](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) |
| Qwen/Qwen2-0.5B-Instruct | [Apache-2.0](https://huggingface.co/Qwen/Qwen2-0.5B-Instruct) |
| FAISS | [MIT](https://github.com/facebookresearch/faiss/blob/main/LICENSE) |
| google/flan-t5-base | [Apache-2.0](https://huggingface.co/google/flan-t5-base) |
| AssemblyAI Universal-3 Pro | Commercial API — [free tier available](https://www.assemblyai.com/pricing) |
| Sample data (`sample_data/`) | **CC0** — synthetic, no real speakers |

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/) v2

### 1. Clone & configure

```bash
git clone https://github.com/rilufiyy/MeetRecall-AI-Improvement.git
cd MeetRecall-AI-Improvement

cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in:

```env
GEMINI_API_KEY=...            # recommended on CPU: Gemini 3.5 Transcribe (transcript + speaker labels)
GROQ_API_KEY=gsk_...          # recommended on CPU: LLM answers (and optional Groq Whisper)
HUGGINGFACE_TOKEN=hf_...      # for pyannote speaker labels (without it: all segments = Speaker 1)
ASSEMBLY_API_KEY=...          # optional — only needed for the AssemblyAI provider
```

### Running on a CPU-only laptop

The stack is CPU-first: the Docker image installs CPU PyTorch wheels and no GPU is requested.
Heavy models are loaded only when used. With `GEMINI_API_KEY` and `GROQ_API_KEY` set,
transcription, speaker labels, and answer generation run in the cloud, and the laptop runs
only the embedding model (~117 MB) and the retrieval logic.

| Component | CPU-friendly default | Alternative |
|---|---|---|
| Transcription + speaker labels | `gemini` provider: Gemini 3.5 Transcribe, one call, up to 30 min per file | `groq` (Groq Whisper + local pyannote), `groq_fast` (no labels), `local` (heavy), `assemblyai` |
| Answer generation | Groq `openai/gpt-oss-20b` (`GROQ_LLM_MODEL`) | local Qwen2-0.5B, also used automatically if a Groq call fails |
| Embeddings, BM25, reranker | local | none needed |

Using Gemini, Groq, or AssemblyAI sends meeting audio/text to that service; on the Gemini
free tier, content may be used by Google to improve its products. Make sure this is allowed
for your recordings.

### 2. Build & start

```bash
docker-compose up -d --build
```

> **First run**: HuggingFace model weights (~1.3 GB total) are downloaded automatically and cached in a Docker volume. Subsequent restarts are instant.

> **CPU only.** The image installs CPU PyTorch wheels; no GPU is required.

### 3. Open

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8502 |
| FastAPI interactive docs | http://localhost:8080/docs |

### 4. Usage walkthrough

1. **Upload** → go to `1 · Upload`, choose provider (Gemini by default; Groq, Local, or AssemblyAI), upload an audio/video file, wait for processing to complete.
2. **Results** → go to `2 · Hasil`, view speaker-labelled transcript and speaker breakdown, download raw text.
3. **AI Chat** → go to `3 · AI Chat`, select meeting, ask questions in any language, see cited source chunks.
4. **Retrieval Lab** → go to `4 · Retrieval Lab`, import `backend/sample_data/sprint_review_portal_mitra.txt` (or pick a meeting), compare full-text / vector / hybrid results, and run the evaluation set.

---

## Docker Deployment Guide

Panduan lengkap cara menjalankan MeetRecall AI menggunakan Docker dari nol.

### Prasyarat

Pastikan tools berikut sudah terinstall sebelum mulai:

```bash
# Cek Docker
docker --version          # minimal Docker 24.x
docker compose version    # minimal Docker Compose v2

# Cek Git
git --version
```

> Belum install Docker? Download di [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)

---

### Step 1 — Clone Repository

```bash
git clone https://github.com/rilufiyy/MeetRecall-AI-Improvement.git
cd MeetRecall-AI-Improvement
```

---

### Step 2 — Konfigurasi Environment

Salin file `.env` dari template:

```bash
cp backend/.env.example backend/.env
```

Buka `backend/.env` lalu isi variabel berikut:

```env
GEMINI_API_KEY=...                     # Disarankan untuk laptop CPU: transkripsi + label pembicara
GROQ_API_KEY=gsk_...                   # Disarankan untuk laptop CPU: LLM penjawab
HUGGINGFACE_TOKEN=hf_...               # Untuk label pembicara (Pyannote, model gated)
ASSEMBLY_API_KEY=...                   # Opsional — hanya jika pakai provider AssemblyAI
```

> **Cara dapat HuggingFace Token:**
> 1. Daftar/login di [huggingface.co](https://huggingface.co)
> 2. Pergi ke Settings → Access Tokens → New Token
> 3. Accept model license di halaman [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)

---

### Step 3 — CPU

Konfigurasi sudah untuk CPU (PyTorch versi CPU, tanpa reservasi GPU), jadi tidak ada yang perlu diubah.

> Jika sebelumnya image sudah pernah dibuild dengan PyTorch CUDA, jalankan `docker compose build --no-cache backend` sekali agar image diganti versi CPU yang jauh lebih kecil.

---

### Step 4 — Build & Jalankan

```bash
# Build image dan jalankan semua service di background
docker compose up -d --build
```

**Apa yang terjadi saat pertama kali build:**
- Docker mengunduh base image Python
- Menginstall semua dependency dari `requirements.txt`
- Saat backend pertama kali start, model HuggingFace (~1.3 GB) diunduh otomatis dan di-cache ke Docker volume `meetrecall-hf-cache`
- Proses ini bisa memakan waktu **5–15 menit** tergantung kecepatan internet

> Restart berikutnya akan instan karena model sudah ter-cache.

---

### Step 5 — Verifikasi Container Berjalan

```bash
# Cek status semua container
docker compose ps

# Output yang diharapkan:
# meetrecall-backend    running (healthy)
# meetrecall-frontend   running
```

Tunggu hingga status backend berubah menjadi `healthy` sebelum membuka UI.  
Health check backend membutuhkan waktu hingga **3 menit** saat pertama kali start (model loading).

---

### Step 6 — Buka Aplikasi

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8502 |
| FastAPI Docs (Swagger) | http://localhost:8080/docs |
| FastAPI Health Check | http://localhost:8080/health |

---

### Step 7 — Cek Log (Opsional)

```bash
# Lihat log semua service secara live
docker compose logs -f

# Lihat log backend saja
docker compose logs -f backend

# Lihat log frontend saja
docker compose logs -f frontend
```

---

### Step 8 — Stop & Restart

```bash
# Stop semua container (data tetap tersimpan)
docker compose down

# Restart tanpa rebuild
docker compose up -d

# Restart dengan rebuild (setelah ada perubahan kode)
docker compose up -d --build
```

**Mode development (tanpa rebuild):** kode `backend/` dan `frontend/` di-mount ke container dan otomatis reload saat file disimpan. Build ulang hanya diperlukan setelah `requirements.txt` berubah.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**Membersihkan storage:** setiap rebuild meninggalkan image lama tanpa nama (`<none>`) dan build cache. Hapus sesekali tanpa menyentuh volume data:

```bash
docker image prune -f
docker builder prune -f --filter until=168h
```

---

### Step 9 — Hapus Data / Reset Ulang

```bash
# Hapus container + semua volume (data meeting & cache model akan terhapus!)
docker compose down -v

# Hapus image untuk full clean build
docker compose down -v --rmi all
```

> `down -v` akan menghapus seluruh data meeting yang tersimpan dan cache model HuggingFace. Model harus diunduh ulang di run berikutnya.

---

### Ringkasan Perintah Penting

| Perintah | Fungsi |
|---|---|
| `docker compose up -d --build` | Build & jalankan semua service |
| `docker compose ps` | Cek status container |
| `docker compose logs -f backend` | Monitor log backend live |
| `docker compose down` | Stop semua (data aman) |
| `docker compose down -v` | Stop + hapus semua data |
| `docker compose up -d` | Restart tanpa rebuild |

---

## API Reference

Base URL: `http://localhost:8080/api`

### Transcription

| Method | Path | Description |
|---|---|---|
| `POST` | `/transcribe` | Upload file (`multipart/form-data`), start async pipeline. Returns `meeting_id` (202). |
| `GET` | `/status/{id}` | Poll processing status (`pending` / `processing` / `completed` / `failed`) |
| `GET` | `/transcript/{id}` | Get full transcript result (only when `completed`) |
| `GET` | `/meetings` | List all meetings, newest first |
| `DELETE` | `/transcript/{id}` | Delete meeting data + FAISS index (204) |
| `GET` | `/providers` | Which transcription providers are configured, and the active LLM backend |
| `POST` | `/transcript/import` | Import a `.txt`/`.json` transcript as a completed meeting (no audio) |

### RAG Chatbot

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/rag/chat/{id}` | `{query, top_k, history}` | Q&A with cited source chunks |
| `POST` | `/rag/reindex/{id}` | — | Force rebuild FAISS index |
| `POST` | `/rag/retrieve/{id}` | `{query, top_k, modes, fusion, alpha, rerank, ...}` | Compare retrieval methods (no LLM) |
| `POST` | `/rag/evaluate/{id}` | `{cases, k, modes, min_score, ...}` | Hit@k / Recall@k / MRR@k per method |
| `GET` | `/rag/retrieval-info` | — | Available modes, fusion methods, reranker status |

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Backend health check (includes ffmpeg availability) |

Full interactive docs: http://localhost:8080/docs

---

## Project Structure

```
MeetRecall/
├── backend/
│   ├── main.py                  ← FastAPI app, CORS, router registration
│   ├── models/
│   │   └── schemas.py           ← Pydantic v2 models (all request/response types)
│   ├── routers/
│   │   ├── transcribe.py        ← POST /transcribe, GET /status, /transcript, /meetings
│   │   └── rag.py               ← POST /rag/chat, /rag/retrieve, /rag/evaluate, /rag/reindex
│   ├── services/
│   │   ├── transcription.py     ← Gemini Transcribe, Groq Whisper, local Whisper, AssemblyAI + Pyannote
│   │   ├── embeddings.py        ← sentence-transformers singleton (384-dim)
│   │   ├── vector_store.py      ← FAISS IndexFlatIP, per-meeting .index + _chunks.pkl
│   │   ├── storage.py           ← JSON file persistence (data/meetings/)
│   │   ├── rag_chain.py         ← retrieval → context build → LLM generate
│   │   ├── keyword_index.py     ← BM25 full-text index + tokenizer
│   │   ├── retrieval.py         ← vector / fulltext / hybrid, fusion, rerank, abstain
│   │   ├── retrieval_eval.py    ← Hit@k, Recall@k, MRR@k evaluation
│   │   ├── transcript_import.py ← parse .txt/.json transcripts
│   │   └── llm.py               ← LLMService — Groq API or local HF model (fallback)
│   ├── sample_data/             ← synthetic transcript + labelled retrieval eval set
│   ├── scripts/
│   │   └── evaluate_retrieval.py ← offline retrieval experiment + charts
│   ├── tests/
│   │   └── test_retrieval.py    ← BM25, fusion, parsing, metric unit tests
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app.py                   ← Landing page + health check
│   ├── pages/
│   │   ├── 1_Upload.py          ← File upload + async status polling
│   │   ├── 2_Hasil.py           ← Transcript results + speaker breakdown + download
│   │   ├── 3_AI_Chat.py         ← RAG chat with conversation memory + source citations
│   │   └── 4_Retrieval_Lab.py   ← Full-text vs vector vs hybrid comparison + evaluation
│   ├── utils/
│   │   ├── api_client.py        ← HTTP client (all backend calls, timeout handling)
│   │   └── styles.py            ← Shared CSS — purple/indigo theme, speaker colours
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml           ← backend:8080, frontend:8502 (CPU only)
├── MeetRecall AI RAG_Flowchart.png ← RAG & knowledge retrieval pipeline diagram
├── Flowchart.pdf                ← original (pre-RAG) pipeline diagram
├── documentations/              ← UI screenshots used in this README
└── README.md
```

---

## Sample Output

### RAG Chatbot — Q&A with Cited Sources
Retrieval-augmented response generated from indexed meeting transcript chunks.
![RAG Chatbot](documentations/more_interaction_chat.png)
