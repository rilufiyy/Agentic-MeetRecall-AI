# Observability: Langfuse Cloud, metadata saja

Status: disetujui 2026-11-19. Implementasi: `backend/agent/observability.py`, hook di `backend/agent/tracing.py`.

## Keputusan

Trace agent disalin ke **Langfuse Cloud** sebagai **metadata saja**, lewat OTLP/HTTP (`/api/public/otel/v1/traces`,
header `x-langfuse-ingestion-version: 4`), memakai library standar Python tanpa SDK atau dependency baru.
Fitur ini mati secara default (`LANGFUSE_ENABLED=false`). Saat mati, perilaku agent identik.

Trace JSONL lokal (`data/traces/*.jsonl`) tetap menjadi sumber kebenaran. Langfuse hanya dipakai untuk melihat
latency, token, biaya, status, dan urutan langkah per run.

## Alasan memilih Langfuse, bukan LangSmith

1. **Loop agent tidak memakai LangChain.** Agent memanggil Groq SDK langsung (`agent/llm_client.py`) dengan loop
   sendiri (`agent/loop.py`) dan tool lewat MCP. Kelebihan utama LangSmith ada pada integrasi LangChain/LangGraph,
   yang tidak dipakai di sini.
2. **Trace lokal sudah lengkap.** `Tracer` sudah mencatat setiap langkah (`run_start`, `llm_call`, `tool_call`,
   `mcp_call`, `guardrail`, `approval`, `run_end`) beserta token, biaya, dan latency. Yang dibutuhkan hanya tampilan
   dari data yang sudah ada, bukan instrumentasi baru. Langfuse menerima OTLP standar, sehingga cukup satu titik
   sambung di `Tracer.log`, tanpa mengubah loop, client LLM, atau tool.

## Alasan memakai Cloud, bukan self-hosted

- Data meeting dalam proyek ini bersumber dari video YouTube publik.
- Yang dikirim hanya metadata: teks user, jawaban model, argumen dan output tool, detail guardrail, dan pesan error
  tidak pernah dikirim (allowlist per jenis event, diterapkan sebelum span dibangun).
- Self-hosted Langfuse v4 membutuhkan Postgres, ClickHouse, Redis, dan MinIO yang harus dirawat sendiri, padahal
  tujuan awalnya adalah observability tanpa memelihara database.

Risiko keluarnya data dinilai rendah dengan kondisi di atas.

## Region: EU (`https://cloud.langfuse.com`)

Data disimpan di region EU Langfuse Cloud, yang tunduk pada GDPR. UU No. 27 Tahun 2022 tentang Pelindungan Data
Pribadi (UU PDP) banyak mengikuti prinsip GDPR, dan untuk transfer data pribadi ke luar wilayah Indonesia
mensyaratkan negara tujuan punya tingkat pelindungan yang setara atau lebih tinggi. GDPR dinilai memenuhi
kesetaraan itu, sehingga region EU dipilih dibanding region lain.

Kode hanya menerima host ini, persis: nilai lain di `LANGFUSE_HOST` (termasuk region US, JP, atau HIPAA) mematikan
ekspor. Penilaian ini bersifat teknis, bukan opini hukum; bila data berubah menjadi data pribadi atau internal,
penilaian kesesuaian UU PDP perlu dikonfirmasi ke tim legal.

**Perlu dievaluasi ulang** bila MeetRecall dipakai untuk rekaman meeting internal perusahaan: pada kondisi itu
pilihannya kembali ke self-hosted, atau kirim metadata saja setelah kebijakan data disetujui.

## Pengembangan lanjutan: Prompt Management (katalog)

Saat ini prompt diidentifikasi lewat metadata `prompt_nama`, `prompt_versi` (12 karakter awal SHA-256), dan
`prompt_sha256`. Atribut `langfuse.observation.prompt.name`/`.version` sengaja belum dipakai: versinya wajib
bilangan bulat dan merujuk ke prompt yang terdaftar di Prompt Management Langfuse.

Bila dibutuhkan, Prompt Management dipakai **hanya sebagai katalog**:

- Setiap perubahan `SYSTEM_PROMPT` (`agent/loop.py`) dan `_EXTRACT_SYSTEM` (`agent/tools.py`) didaftarkan sebagai
  versi baru di Langfuse, dengan SHA-256 dicatat di label atau konfigurasinya.
- Kode memetakan SHA-256 ke nomor versi katalog (tabel statis di kode), lalu mengisi `prompt.name`/`.version`
  supaya trace terhubung ke versi prompt di UI.
- **Tanpa fetch saat runtime.** Prompt tetap berasal dari kode yang di-review dan di-commit. Agent tidak mengambil
  prompt dari Langfuse saat start atau per request, sehingga tidak ada ketergantungan jaringan, perubahan prompt
  tidak bisa terjadi di luar review kode, dan hasil eval tetap bisa diulang dari commit yang sama.

## Batas yang dijaga kode

- Host wajib diisi lewat `LANGFUSE_HOST`, tanpa default, dan harus persis `https://cloud.langfuse.com`.
- `meeting_id` dikirim sebagai HMAC-SHA256 dengan `LANGFUSE_HASH_SALT` (session id). Tidak ada user id.
- Prompt diidentifikasi dengan nama dan SHA-256, bukan isi teks.
- Fail-open: antrean terbatas, thread latar, timeout pendek, circuit breaker. Server yang mati tidak memperlambat
  atau menggagalkan run.
