# MeetRecall Agentic AI

Agent untuk tindak lanjut meeting. Pengguna memberi instruksi dalam bahasa alami, lalu agent menganalisis transkrip meeting, merangkum keputusan, mengekstrak action items, membuat task, dan menyiapkan laporan untuk dikirim lewat email.

Project ini adalah lanjutan dari MeetRecall AI (RAG atas transkrip meeting) dan dikembangkan untuk task "Agentic AI & AI Orchestration".

## Fitur

- Agent dengan tool calling atas transkrip meeting (retrieval, ekstraksi poin, statistik).
- Workflow tindak lanjut meeting: rekap, action items, task, laporan PDF/DOCX.
- Aksi tulis (buat task, kirim email) tidak dijalankan LLM. Semuanya lewat approval dua fase yang diklik pengguna.
- Email hanya ke satu alamat tetap (`REPORT_EMAIL_TO`), tanpa Cc atau Bcc.
- Guardrails dan tracing per request dan per langkah (JSONL).
- Tool dapat dipanggil langsung (`local`) atau lewat MCP (`mcp`), diatur dengan `AGENT_TOOL_TRANSPORT`.
- Harness evaluasi untuk mengukur kualitas agent (`backend/scripts/eval_harness.py`).

## Struktur

```
backend/
  agent/        loop agent, tools, workflow, approvals, guardrails, MCP server/client
  routers/      endpoint FastAPI (agent, rag, transcribe)
  services/     layanan transkripsi dan retrieval (W6)
  scripts/      eval_harness.py
  tests/        pytest
frontend/
  app.py        Streamlit
  pages/        Upload, Hasil, AI Chat, Retrieval Lab, Agent
docs/           dokumen desain, evaluasi, dan alur end-to-end
docker-compose.yml
```

## Menjalankan

Semua lewat Docker. Image dasar `meetrecall-backend:latest` (hasil W6) harus sudah ada di mesin ini. Bila belum, build dari `backend/Dockerfile`.

1. Salin `backend/.env.example` menjadi `backend/.env`, lalu isi kredensial sendiri (`GROQ_API_KEY`, dan seterusnya). Jangan commit `.env`.
2. Build image agent dan jalankan:

```bash
docker build -f backend/Dockerfile.agent -t meetrecall-agent:latest backend
docker compose up -d
```

3. Buka UI di http://localhost:8503 dan dokumentasi API di http://localhost:8090/docs.

Kode di-mount dari host. Untuk perubahan kode cukup `docker compose restart backend`. Perubahan `backend/.env` butuh `docker compose up -d --force-recreate backend`.

Model Hugging Face disimpan di `hf-cache/` (bind mount, tidak ikut git, ukurannya beberapa GB).

## Test

```bash
docker run --rm -v "$(pwd)/backend:/app" -w /app meetrecall-agent:latest python -m pytest tests -q
```

## Konfigurasi penting

| Variabel | Fungsi |
|---|---|
| `GROQ_API_KEY` | Kunci API untuk agent dan RAG |
| `AGENT_MODEL` | Model agent (default `openai/gpt-oss-20b`) |
| `AGENT_TOOL_TRANSPORT` | `local` atau `mcp` |
| `EMAIL_MODE` | `dry_run` (tulis file .eml) atau `smtp` (kirim sungguhan) |
| `REPORT_EMAIL_TO` | Satu-satunya penerima email yang diizinkan |

Daftar lengkap ada di `backend/.env.example`.

## Dokumentasi

Dokumen desain, evaluasi, dan alur end-to-end ada di folder [docs](docs). Catatan kemajuan ada di [PROGRESS.md](PROGRESS.md).
