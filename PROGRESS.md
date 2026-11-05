# PROGRESS: W78 Agentic AI, MeetRecall Agent (Demo project)

Ringkasan ini dibuat pada 28 Oktober 2026 dari riwayat sesi Claude Code di folder ini (6 sampai 27 Oktober 2026). Rincian teknis yang lebih lengkap ada di `docs/HANDOFF_PROMPT.md` (terakhir diperbarui 16 Oktober) dan `docs/09_catatan_sesi_evaluasi.md`. File ini menambahkan apa yang terjadi setelah HANDOFF terakhir diperbarui.

Untuk sesi baru, cukup buka dengan: "Baca PROGRESS.md dulu, lalu docs/HANDOFF_PROMPT.md, lalu lanjutkan dari bagian Langkah berikutnya."

## 1. Tujuan dan scope

Task onboarding W7-W8 "Agentic AI & AI Orchestration":

- Key challenge: memahami best practice implementasi agent, serta tools dan function calling.
- Goal: mampu mendesain AI workflow atau agent untuk proses bisnis.
- Deliverable: agent end-to-end untuk demo ke tim, dokumentasi desain, dan hasil evaluasi sebagai bahan artikel Wiki.
- Project: MeetRecall AI (RAG chatbot W6) dikembangkan menjadi agent meeting follow-up: analisis meeting, rangkum keputusan, ekstrak action items, buat task, dan kirim laporan ke email sendiri, dengan approval dua fase oleh pengguna.

## 2. Yang sudah selesai

### Aplikasi

- Agent `openai/gpt-oss-20b` di Groq dengan loop function calling manual (`backend/agent/loop.py`), 7 tool, guardrail di kode, approval dua fase untuk aksi tulis, tracing JSONL di `backend/data/traces/`.
- Workflow pembanding (`backend/agent/workflow.py`) dengan urutan tool dikunci di kode.
- Laporan PDF, DOCX, Markdown, SRT dengan palet Tritronik dan waktu WIB. Email lewat Gmail SMTP hanya ke alamat sendiri.
- Email notifikasi job transkripsi melampirkan SRT (keputusan nomor 3). Isi email laporan dirapikan (keputusan nomor 4).
- Penguncian `meeting_id` di `_check_meeting_scope` supaya agent tidak mengutip meeting lain.
- Cache model dipindah dari drive C ke folder `hf-cache/` di project (drive D).
- Perbaikan pasca-evaluasi sudah diterapkan di `backend/`: glyph U+2011 di PDF, urutan ID action item, aturan prompt penanggung jawab dan tenggat, isian simulasi harness.

### MCP (ditambahkan 16 Oktober atas masukan GM)

- `backend/agent/mcp_server.py`: server MCP `meetrecall-ai` dengan 8 tool (7 tool agent ditambah satu untuk aplikasi lain).
- MCP menyatu di alur utama, dipilih lewat `AGENT_TOOL_TRANSPORT` di `.env` root project (`local` default, `mcp` untuk jalur MCP). Saat ini aktif `mcp`. Event `mcp_call` tercatat di trace.
- Terhubung ke Claude Desktop lewat `docker exec -i meetrecall-agent-backend python -m agent.mcp_server` (entri `meetrecall` di `claude_desktop_config.json`). Sudah diuji dengan `statistik_meeting` dari Claude Desktop dan jawabannya benar.
- Penjelasan yang tepat untuk demo: tool MeetRecall bisa dipakai dari aplikasi lain lewat MCP. Jangan menyebut "MeetRecall Agent bisa diakses dari Claude Desktop", karena loop, guardrail, dan verifikasi jawaban agent tidak ikut berjalan di sana.

### Rujukan sumber di halaman Agent (16 Oktober)

- Expander "Sumber (N)" di bawah jawaban agent, berisi potongan transkrip yang dibaca agent, tanpa penomoran.
- Atribusi kutipan dicek oleh kode (bukan LLM): kutipan dicari di segmen transkrip, speaker dan waktu dikoreksi bila berbeda, baris "Lokasi di transkrip" ditampilkan. Tercatat di dokumen 09 bagian 29.2 sampai 29.5.

### Evaluasi

- 47 skenario di dokumen 07 (disetujui 7 Oktober), label acuan di dokumen 08 (A-02 ditulis Fiya, label tingkat 2 diverifikasi Fiya).
- Evaluasi dijalankan sesi A (7 Okt), B1 (8 Okt), Jumat (9 Okt), dan hari kedua (10 Okt) dengan kode `815dee68864de752`.
- Penilaian manual Fiya ada di `eval_run/daftar_penilaian_manual.md` dan dianggap final.
- Hasil utama agent: **36 dari 44 skenario lulus (81,8%)**, atau 36 dari 43 bila ES-01 dikeluarkan karena premisnya tidak terpenuhi. Per jenis meeting: nyata EN 20/27, nyata ID 5/5, sintetis ID 10/11, sintetis EN 1/1. Angka ini wajib disebut sebagai gabungan penilaian otomatis (rekaman kode `815dee68`) dan vonis manual (pengujian langsung pada kode terkini). Tercatat di dokumen 09 bagian 28.3.
- WER Rapat Evaluasi sampel 06:00 sampai 10:20: 0,94% (batas bawah, karena acuan disusun dengan mengoreksi transkrip sistem).

### Dokumen

| Dokumen | Isi |
|---|---|
| `docs/01` sampai `docs/04` | Desain, MVP, penguatan, job ekspor dan UI |
| `docs/05`, `docs/06` | Skenario informasi tidak ada dan topik ada detail tidak ada, seluruhnya tercentang |
| `docs/07`, `docs/08` | Set skenario Tahap 4 dan lembar pelabelan |
| `docs/09_catatan_sesi_evaluasi.md` | Catatan seluruh sesi evaluasi, hasil, temuan, dan bagian 29 tentang MCP dan rujukan sumber |
| `docs/10_desain_llm_vs_kode_dan_spektrum_otonomi.md` | Desain LLM vs kode dan spektrum otonomi (planner eksplisit dan self-check ditulis sebagai rencana pengembangan, kode tidak diubah) |
| `docs/11_pemeriksaan_sebelum_sesi_B.md` | Pemeriksaan sebelum sesi B |
| `docs/12_alur_end_to_end.md` dan `.pdf` | Alur end-to-end termasuk MCP |
| `docs/13_bahan_ppt.md` | Prompt dan bahan untuk membuat PPT di Claude web |
| `docs/flowchart_end_to_end.png` | Flowchart terbaru dengan lapisan MCP (versi lama: `flowchart_end_to_end_sebelum_mcp.png`) |

Artikel Wiki ditulis di Claude web, bukan di sesi ini.

## 3. Keputusan penting dan alasannya

- **Tidak menambah otonomi demi terlihat "lebih agentic".** MeetRecall disebut "sistem AI agent dengan arsitektur agentic: otonom di langkah aman, human-in-the-loop di langkah berisiko". Jangan mengklaim "otonom penuh" atau "punya memory persisten".
- **Aksi tulis tidak dijalankan LLM.** Approval dua fase, klik oleh pengguna.
- **Pembuatan PDF dan Word sepenuhnya kode Python**, bukan LLM.
- **Gemini ditunda** (keputusan nomor 5). Perbandingan workflow vs agent memakai `gpt-oss-20b`.
- **Duplikat GitLab:** `42ca5f94` disimpan, `65c34785` dipindah ke `arsip\2026-10-06_hapus_65c34785\`.
- **Approval Ginger Cola `APba178333eb`** ditolak lewat UI dan diverifikasi 8 dari 8 pemeriksaan.
- **Sidik jari evaluasi diabaikan** setelah 16 Oktober atas permintaan Fiya, supaya rujukan sumber bisa ditambahkan. Sidik jari `20c906c4ae637427` sudah usang.
- **Git:** remote `https://gitops.tritronik.com/sri.lutfiya/MeetRecall-Agentic-AI.git`. Fiya yang commit dan push sendiri lewat terminal Ubuntu; Claude hanya memberi instruksi.

## 4. Masalah yang ditemukan dan statusnya

| Masalah | Status |
|---|---|
| MCP di Claude Desktop "disconnected" atau "failed" | Penyebabnya container `meetrecall-agent-backend` belum jalan saat Claude Desktop dibuka. Urutan aman: nyalakan Docker, `docker compose up -d`, tunggu backend `healthy`, baru buka Claude Desktop |
| Daftar meeting di UI kosong setelah backend di-restart | Bukan data hilang. Tekan F5. Pesan "backend belum siap" belum dibuat |
| Entri meeting gagal `d1d8417c` (Ginger Cola) di sidebar | Belum dibersihkan, rencananya sebelum demo |
| Error `torchcodec` saat transkripsi lokal Whisper dan pyannote | Sudah diperbaiki di image |
| Perintah `tail` dan `Get-Content` gagal di `cmd.exe` | Pakai PowerShell untuk memantau trace |
| Kesalahan ASR "put those up" (audio: "pick those up") di GitLab 10:23 | Dicatat sebagai temuan, kutipan dinilai terhadap transkrip |
| `cari_transkrip` memberi relevansi rendah di beberapa skenario (`min_score=0.40`) | Belum disetel |

## 5. Yang belum selesai dan langkah berikutnya

1. Rerun paket 2 (11 skenario, sekitar 126,7k token terkoreksi) untuk memverifikasi perbaikan. Butuh izin Fiya. Hitung ulang sidik jari dulu karena kode sudah berubah.
2. Keputusan kecil di dokumen 09 bagian 28 (ES-01, ES-02, W-01, IT-03), kriteria W-05 dan uji C (ditulis Fiya sendiri, jangan dibuatkan draf).
3. Cari video atau podcast Indonesia tanpa keputusan untuk slot MTK-01 (Fiya yang mencari dan mengunggah).
4. Uji cepat alur demo sebelum tampil: ekstrak action items, laporan PDF, kartu persetujuan task. Cek sisa kuota Groq harian.
5. Bersihkan entri `d1d8417c` sebelum demo, lalu ambil snapshot data baru (jangan menimpa yang lama).
6. Commit dan push perubahan terbaru (MCP, rujukan sumber, flowchart, dokumen) oleh Fiya.
7. Perbarui `docs/HANDOFF_PROMPT.md` dengan status setelah 16 Oktober (MCP aktif, rujukan sumber, koneksi Claude Desktop).
8. Ditunda: fitur kustomisasi laporan di `backend_dev/` (167 test lulus, belum diterapkan ke `backend/`), uji model lokal, planner dan self-check.

## 6. Aturan yang berlaku

- Folder sumber W6 dan W5 read-only, jangan diubah.
- Jangan membaca atau menampilkan `backend/.env`, API key, atau App Password. Alamat email ditulis tersamar.
- Email hanya ke alamat Fiya sendiri, tanpa Cc atau Bcc.
- Jangan commit atau push tanpa persetujuan Fiya.
- Jangan menjalankan skenario evaluasi atau run yang memakai kuota Groq tanpa izin. Tanya dulu soal kuota dan waktu (batas harian Groq 200.000 token, waktu reset tidak tetap).
- Label acuan manual milik Fiya. Jangan membuat draf A-02, dan jangan mencentang atas nama Fiya kecuali atas keputusan yang ditulis di chat.
- Angka evaluasi hanya dari eksekusi nyata, ditulis "x dari y" per jenis meeting. Perkiraan diberi label perkiraan.
- Klaim best practice atau API merujuk dokumentasi resmi dengan URL.
- Jalankan semuanya lewat Docker, tanpa venv, tanpa file besar di drive C. Jangan hapus image dan volume W6, dan jangan hapus `C:\Users\tritr\.cache\huggingface` (dipakai W5).
- Setiap kali backend di-restart, beri tahu Fiya (daftar meeting kosong sampai F5).
- Dokumentasi tanpa em dash, tanpa emoji, dan tanpa teks tebal di flowchart.
- Pekerjaan bertahap, laporan singkat dan jujur, hemat token.
