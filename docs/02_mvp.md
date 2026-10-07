# Tahap 2: MVP agent loop

Status: kode selesai dan lolos unit test. Uji end-to-end dengan LLM nyata belum dijalankan karena `GROQ_API_KEY` belum tersedia di environment (belum diukur).

## Isi MVP

| File | Isi |
|---|---|
| `backend/agent/config.py` | Model, batas iterasi, konfigurasi retrieval, tabel harga untuk estimasi biaya |
| `backend/agent/llm_client.py` | Klien Groq: chat dengan tools, structured output strict, token usage, latency |
| `backend/agent/tools.py` | Tool `cari_transkrip`, `ekstrak_poin_meeting`, `statistik_meeting`, registry, eksekusi dan validasi argumen |
| `backend/agent/guardrails.py` | Verifikasi kutipan, status penanggung jawab dan tenggat, deteksi pola injection, cek input |
| `backend/agent/rekap_store.py` | Penyimpanan rekap terstruktur (`data/agent/rekap/{rekap_id}.json`) |
| `backend/agent/tracing.py` | Penulis JSONL (`data/traces/YYYY-MM-DD.jsonl`) |
| `backend/agent/loop.py` | Agent loop |
| `backend/scripts/agent_cli.py` | CLI demo |
| `backend/tests/test_agent.py` | 14 unit test dengan LLM palsu |

Kode W6 tidak diubah. Rencana awal menambah method di `services/llm.py` diganti dengan modul klien terpisah, supaya agent tidak mewarisi fallback diam-diam ke model lokal.

## Perubahan terhadap desain Tahap 1

1. Ambang abstain retrieval. `min_score = 0.40` dari W6 ditentukan pada transkrip sintetis bahasa Indonesia. Pada meeting asli "Ginger Cola Launch", query "who will handle the launch marketing" abstain padahal chunk relevan ada (cosine terbaik 0,359), dan chunk berisi "we have decided to pitch the new Ginger Cola" hanya mendapat cosine 0,209 untuk query tentang keputusan. Perubahan:
   - `cari_transkrip`: bila abstain, kembalikan maksimal 3 chunk terbaik dengan `relevansi: "rendah"` dan pesan agar agent menjawab "tidak ditemukan" bila isinya tidak menjawab.
   - `ekstrak_poin_meeting`: retrieval tanpa abstain; penjaga kebenarannya adalah verifikasi kutipan oleh kode.
   - Ambang yang tepat untuk data asli masuk ke evaluasi Tahap 4 (belum diukur).
2. Item rekap memakai field `isi` untuk semua jenis (bukan `keputusan`, `isu`, `poin` terpisah) agar validasi dan template PDF seragam.
3. Status tenggat ditambah `tidak_terverifikasi`: tenggat yang ditulis LLM tetapi tidak ada di chunk sumber dikosongkan dan item masuk daftar eskalasi.
4. Kutipan yang dirujuk ke `chunk_id` salah tetapi ada persis di chunk lain yang ikut diambil diterima, dengan metadata chunk yang benar. Kutipan yang tidak ada di chunk mana pun ditolak.

## Perilaku loop

- Maksimal 8 panggilan LLM per request (`AGENT_MAX_ITERATIONS`).
- Tool dieksekusi berurutan. Argumen divalidasi Pydantic (`extra="forbid"`); argumen salah, tool tidak dikenal, atau JSON rusak menjadi hasil `invalid_args` untuk LLM, bukan exception.
- Dua error tool berturut-turut menghentikan run dengan status `tool_error`.
- Request LLM yang gagal diulang sekali, lalu run berhenti dengan `llm_error`. Tidak ada fallback ke model lokal.
- Input ditolak sebelum panggilan LLM bila meeting tidak ada, belum selesai diproses, pesan kosong, atau lebih dari 2.000 karakter.
- Jawaban akhir dicek: kutipan dalam tanda kutip yang tidak ada di transkrip diberi catatan sistem di bawah jawaban dan dicatat sebagai guardrail `kutipan_jawaban_akhir`.
- Teks transkrip dikirim ke LLM di dalam `<transkrip_data>`; tag penutup di dalam transkrip dinetralkan.

## Hasil uji yang sudah dijalankan

| Uji | Hasil |
|---|---|
| Unit test agent (host, Python 3.14) | 14 lolos |
| Seluruh test backend di container (Python 3.11, termasuk test W6) | 76 lolos |
| Smoke test tool 1 dan 3 pada meeting asli "Ginger Cola Launch" (retrieval FAISS + BM25 nyata, tanpa LLM) | Berjalan. Pemanggilan pertama 12,8 detik karena memuat model embedding; berikutnya 52 ms. Statistik: durasi 03:25, 3 speaker, 10 giliran, Speaker 0 bicara 66,2 persen waktu bicara. Temuan ambang abstain di atas berasal dari uji ini. |
| Agent end-to-end dengan Groq | belum diukur |

## Cara menjalankan

Sama seperti W6, semua dijalankan lewat Docker (Python 3.11 di dalam image), tanpa venv. Buat `backend/.env` dari `backend/.env.example` dan isi `GROQ_API_KEY`. Lalu dari folder `Demo project` di cmd:

```bat
docker run --rm -it --env-file backend\.env -v "%cd%\backend:/app" -v meetrecallairagchatbot_meetrecall-hf-cache:/root/.cache/huggingface -w /app meetrecall-backend:latest python scripts/agent_cli.py --list
```

Di PowerShell, ganti `%cd%` dengan `${PWD}`.

Perintah di atas memakai image dan cache model dari W6, jadi tidak perlu build ulang. Ganti `--list` dengan `--meeting-id <id> "pertanyaan"` atau `--meeting-id <id> --chat`.

Unit test:

```bat
docker run --rm -v "%cd%\backend:/app" -w /app meetrecall-backend:latest python -m pytest tests -q
```

## Uji pertama dengan Groq dan perbaikannya (2026-10-05)

Pertanyaan "apa saja action items pada meeting ini?" pada meeting Ginger Cola dijawab "Tidak ditemukan" (trace `a7e3848097024f54b3d5ee5db824b261`). Agent memilih tool yang benar; panggilan ekstraksi di dalam tool mengembalikan daftar kosong, padahal transkrip memuat permintaan dan komitmen yang jelas (00:20, 02:19).

| Percobaan (ekstraksi action items) | Ginger Cola | Rapat Evaluasi (ID) | Token output per panggilan |
|---|---|---|---|
| Prompt awal, reasoning low | 0 atau 1 item, berubah antar run | tidak diuji | 32 |
| Prompt awal, reasoning medium | 1 atau 2 item | tidak diuji | tidak dicatat |
| Prompt dengan kriteria eksplisit, reasoning medium | 4 item pada 3 run; 2 dari 5 run error | 7 sampai 8 item; 1 dari 3 run error | 3.257 sampai 3.817 |
| Prompt dengan kriteria eksplisit, reasoning low | 4 item pada 4 dari 4 run | 0 item, kutipan ditolak (3 dari 3 run) | 221 sampai 346 |
| Ditambah chunk tidak dipotong untuk ekstraksi | 4 item (1 run) | 6 sampai 7 item, 0 sampai 2 kutipan ditolak (3 run) | 346 sampai 908 |

Temuan:
1. Prompt yang hanya berisi "jangan menebak" membuat model terlalu konservatif. Kriteria eksplisit per jenis (permintaan, komitmen, langkah lanjut) dan arahan "utamakan kelengkapan, kode yang memverifikasi" memperbaiki recall.
2. Reasoning medium memakai kira-kira 10 kali token output, sehingga terkena batas Groq free tier untuk `openai/gpt-oss-20b` sebesar 8.000 token per menit (pesan 429 dari API), dan kadang budget output habis sebelum JSON selesai (400 `json_validate_failed`). Default ekstraksi dikembalikan ke low; `json_validate_failed` dicoba ulang sekali.
3. Bug: teks chunk untuk ekstraksi dipotong di 600 karakter, sehingga kutipan di ujung chunk tidak pernah lolos verifikasi. Ekstraksi sekarang menerima chunk utuh.
4. Presisi penanggung jawab: model mengisi label speaker pengusul sebagai penanggung jawab ("pengadaan pelatihan ..."). Aturan baru di kode: label speaker hanya dianggap jelas bila kutipan adalah komitmen orang pertama dari speaker itu ("I will", "saya akan"); ajakan bersama ("let's") dan usulan ditandai ambigu.
5. Pada Rapat Evaluasi, banyak item yang diekstrak sebenarnya usulan kebijakan, bukan tugas. Presisi action items terhadap label manusia diukur di Tahap 4 (belum diukur).

Setelah perbaikan, pertanyaan yang sama menghasilkan 4 action items dengan kutipan dan timestamp, satu ditandai ambigu, dalam 2 iterasi, 10,0 detik, 3.729 token input, 775 token output, estimasi 0,00051 USD (trace `8d0ff652c1a94472a2df95470856fe1e`).

## Data

Empat meeting disalin read-only dari volume Docker W6 ke `backend/data` (folder ini di-ignore git):

| meeting_id | Judul | Sumber |
|---|---|---|
| 0653d0f8-0c12-47c9-8dc8-5855fad68819 | Rapat Evaluasi Kinerja Pegawai, Kelompok 1 | URL YouTube belum tercatat |
| 5c8ff57e-e6b9-4d21-ad36-cf517117ec6e | Business Meeting, Ginger Cola Launch | URL YouTube belum tercatat |
| 3b24bd74-a645-4a83-b48a-2c3487f2c9a3 | Weekly Meeting Example | URL YouTube belum tercatat |
| c69b07e4-27e4-4e7c-8cb8-8eef47475245 | Sprint review Portal Mitra | Sintetis, dibuat di W6 |
