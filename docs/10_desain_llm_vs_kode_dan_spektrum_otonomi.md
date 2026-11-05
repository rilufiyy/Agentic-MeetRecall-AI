# Desain: pembagian kerja LLM vs kode, dan spektrum otonomi

Status: DRAF, dibuat 2026-10-07, menunggu verifikasi pengguna. Berkas ini baru; dokumen 01 sampai 09 tidak diubah.

Dokumen ini menjawab dua pertanyaan desain untuk task W7-W8: apa yang diserahkan ke LLM dan apa yang dikunci di kode, dan di titik mana MeetRecall berada pada spektrum otonomi. Setiap klaim diberi penanda sumber dalam kurung siku. Format penanda:

- `[kode: berkas:baris]` berarti klaim dapat dibaca langsung di kode (nomor baris per 2026-10-07; dapat bergeser bila kode berubah).
- `[trace: event/nama]` berarti kejadian itu ditulis ke `backend/data/traces/*.jsonl` (kolom `event`, dan `nama` untuk kejadian `guardrail`).
- `[dok: berkas bagian]` berarti klaim bersumber dari catatan pengamatan di dokumen proyek, bukan dari kode.
- `[belum diverifikasi]` berarti klaim tidak dapat dibuktikan dari kode atau trace.

Dokumen ini tidak memuat angka evaluasi. Jawaban evaluasi belum dinilai (lihat dokumen 09).

## 1. Hubungan dengan evaluasi

Keputusan yang tidak berubah: gelombang 1 dijalankan dalam dua sesi, tanpa perubahan kode atau konfigurasi di antaranya [dok: HANDOFF_PROMPT.md, aturan pembekuan; dokumen 09 bagian 1]. Sesi A sudah selesai. Karena itu:

- Dokumen ini hanya menambah satu berkas di `docs/`. Tidak ada berkas di `backend/` yang disentuh.
- Planner eksplisit dan self-check TIDAK diimplementasikan. Keduanya ditulis sebagai rencana pengembangan lanjut (bagian 6) dengan alasan menjaga perbandingan evaluasi tetap valid: sesi A dan sesi B harus memakai kode dan konfigurasi yang sama (sidik jari kode `815dee68864de752`, konfigurasi `48956add792c0b16`) [dok: dokumen 09 bagian 1].
- Folder `docs/` tidak termasuk dalam 41 berkas sidik jari. Yang dihitung hanya `agent/*.py`, `services/*.py`, `routers/*.py`, `scripts/*.py`, `scripts/skenario_tahap4.json`, dan `main.py` di bawah `backend/` `[kode: scripts/eval_harness.py:129-139 code_fingerprint]`. Menambah berkas ini tidak mengubah sidik jari. Hasil pemeriksaan sidik jari sebelum sesi B dicatat di `docs/11_pemeriksaan_sebelum_sesi_B.md`.

## 2. Posisi MeetRecall: agent dengan otonomi terbatas

Pernyataan posisi, apa adanya: MeetRecall adalah agent dengan otonomi terbatas. LLM memilih tool, urutan, dan argumen di dalam sebuah loop; kode menentukan batas loop, memverifikasi hasil, dan mengunci semua aksi yang berisiko di balik persetujuan pengguna. MeetRecall bukan agent otonom penuh, dan bukan sekadar workflow tetap.

Dasar pernyataan:

| Ciri | Bukti |
|---|---|
| LLM memilih tool berikutnya dari tujuh tool yang terdaftar | `[kode: loop.py, loop for iterasi dan self.llm.chat(..., tools=self.tools); tools.py:677 TOOLS]` |
| Hasil tool dikembalikan ke LLM sebagai pesan `tool` dan dipakai di iterasi berikutnya | `[kode: loop.py, messages.append({"role": "tool", ...})]` |
| Loop dibatasi kode: 8 iterasi, berhenti setelah 2 error tool beruntun | `[kode: config.py MAX_ITERATIONS, MAX_CONSECUTIVE_TOOL_ERRORS]` `[trace: guardrail/tool_error_limit, guardrail/max_iterations]` |
| Aksi tulis tidak dieksekusi oleh LLM atau oleh tool; tool hanya membuat permintaan persetujuan | `[kode: tools.py buat_task, kirim_email_rekap mengembalikan status awaiting_approval]` `[trace: approval dengan keputusan_user "menunggu"]` |
| Eksekusi terjadi hanya di `approvals.decide` setelah pengguna setuju | `[kode: approvals.py:232 decide]` `[trace: approval dengan mode "approval", keputusan_user "setuju" atau "tolak"]` |
| Penerima email bukan argumen LLM | `[kode: schemas.py KirimEmailRekapArgs (tanpa field penerima); mailer.py:34 report_recipient]` |

Status akhir sebuah run dan siapa yang memutuskannya `[kode: loop.py, docstring dan fungsi finish]`:

| Status run_end | Diputuskan oleh |
|---|---|
| `completed` | LLM (menjawab tanpa tool call); kode hanya menambah catatan bila kutipan tidak terverifikasi |
| `awaiting_approval` | Kode (tool aksi tulis mengembalikan status itu; teks permintaan disusun `approvals.format_request`, bukan LLM) |
| `needs_human` | LLM memilih memanggil `minta_klarifikasi`; teks pertanyaan diteruskan apa adanya |
| `rejected_input`, `rejected_scope` | Kode, sebelum ada panggilan LLM `[trace: guardrail/input, guardrail/scope]` |
| `max_iterations`, `tool_error`, `llm_error` | Kode |

## 3. Desain: pembagian kerja LLM vs kode

Prinsip yang dipakai (dirumuskan dari struktur kode, bukan klaim dari sumber luar): LLM dipakai di tempat yang membutuhkan pemahaman bahasa; kode dipakai di tempat yang harus selalu benar, bisa diperiksa, atau tidak bisa dibatalkan.

### 3.1 Yang diserahkan ke LLM

| Keputusan atau pekerjaan | Tempat | Sumber |
|---|---|---|
| Memilih tool mana, dalam urutan apa, dengan argumen apa | loop agent | `[kode: loop.py]` `[trace: tool_call, kolom tool dan argumen]` |
| Mengekstrak ringkasan, keputusan, action items, isu terbuka dari potongan transkrip | satu panggilan LLM terpisah di dalam `ekstrak_poin_meeting`, dengan output terstruktur | `[kode: tools.py:411 purpose="ekstrak_poin_meeting:<jenis>"]` `[trace: llm_call dengan purpose itu]` |
| Memutuskan perlu bertanya ke pengguna atau tidak (`minta_klarifikasi`) | loop agent | `[kode: tools.py minta_klarifikasi; loop.py needs_human]` |
| Menyusun kalimat jawaban akhir | loop agent | `[kode: loop.py, result.content]` |

### 3.2 Yang dikunci di kode (tanpa LLM)

| Pekerjaan | Mekanisme | Sumber |
|---|---|---|
| Verifikasi kutipan dan timestamp tiap item ekstraksi | `quote_in_text` (kutipan harus ada persis di teks chunk, mengabaikan huruf besar, tanda baca, dan kata ulang), lalu `snap_quote` yang mengembalikan potongan kata asli pembicara | `[kode: guardrails.py:41, :67; tools.py:290 _verify]` `[trace: guardrail/kutipan_terverifikasi]` |
| Status penanggung jawab dan tenggat | `owner_status`, `deadline_status` | `[kode: guardrails.py:145, :169]` |
| Statistik (durasi, waktu bicara) | `compute_statistics` | `[kode: tools.py:459]` |
| Isi dan format laporan PDF, DOCX, MD, SRT | `reporting.export` | `[kode: tools.py ekspor_laporan; reporting.py]` |
| Penerima email | `REPORT_EMAIL_TO` dibaca kode, bukan argumen tool | `[kode: mailer.py:34; schemas.py KirimEmailRekapArgs]` |
| Persetujuan dua fase dan eksekusi | `ApprovalStore`, `decide` | `[kode: approvals.py]` |
| Kunci meeting aktif | `_check_meeting_scope` menolak `meeting_id` berbeda | `[kode: tools.py:726, :729]` `[trace: guardrail/meeting_scope]` |
| Niat menulis | `write_intent` memeriksa pesan pengguna (bukan teks transkrip) sebelum tool aksi tulis berjalan | `[kode: guardrails.py:262; tools.py:532]` `[trace: guardrail/write_intent]` |
| Pencatatan | `Tracer` | `[kode: tracing.py]` |

### 3.3 Verifikasi deterministik, bukan refleksi LLM

Dua pemeriksaan sering disebut "agent memeriksa dirinya". Di MeetRecall keduanya dilakukan kode dan tidak memanggil LLM. Keduanya bukan refleksi atau self-check LLM.

**Pemeriksaan kutipan.** Ada dua tempat:

1. Di dalam `ekstrak_poin_meeting`: setiap item ditolak bila kutipannya tidak ditemukan di chunk, kecuali berhasil diperbaiki ke kata asli lewat `snap_quote` `[kode: tools.py:290-337]`. Hasilnya tercatat `[trace: guardrail/kutipan_terverifikasi, detail lolos, ditolak, diperbaiki_ke_kata_asli]`.
2. Pada jawaban akhir: `unverified_quotes` mencari teks dalam tanda kutip dan membandingkannya dengan seluruh transkrip `[kode: guardrails.py:206; loop.py]` `[trace: guardrail/kutipan_jawaban_akhir]`. Batasannya: pemeriksaan ini hanya menambahkan "Catatan sistem" ke jawaban dan status tetap `completed`. Ia tidak memblokir jawaban dan tidak meminta LLM mengulang `[kode: loop.py, blok if bad]`.

**Penolakan laporan tidak lengkap.** `ekspor_laporan` untuk format pdf, docx, atau md melempar `ToolFailure("not_found", ...)` bila ada bagian yang berstatus `belum_dianalisis` `[kode: tools.py:551-555]`. Yang tercatat di trace adalah kejadian `tool_call` dengan `status: not_found` `[trace: tool_call/status=not_found]`; tidak ada kejadian `guardrail` dengan nama sendiri untuk kasus ini `[kode: tidak ada pemanggilan tracer.guardrail di fungsi itu]`. Pesan penolakan dikirim ke LLM sebagai hasil tool, sehingga LLM yang memutuskan memanggil `ekstrak_poin_meeting` dulu; penolakannya sendiri adalah keputusan kode.

Dua batasan yang perlu diketahui pembaca:

- Argumen `izinkan_bagian_kosong` dapat diisi LLM. Bila diisi `true`, pemeriksaan dilewati `[kode: tools.py:551; schemas.py EksporLaporanArgs]`. Deskripsi field menyuruh LLM mengisinya hanya bila pengguna meminta laporan sebagian. Kepatuhan pada deskripsi itu belum diukur [belum diverifikasi].
- `write_intent` adalah pencocokan kata kunci pada pesan pengguna saat ini dan pesan pengguna sebelumnya `[kode: guardrails.py:262; loop.py ctx.user_message]`. Kata seperti "buat" memenuhi syarat `buat_task` `[kode: guardrails.py _WRITE_INTENT]`. Ia menahan aksi yang tidak diminta sama sekali, tetapi tidak membuktikan maksud pengguna secara tepat. Persetujuan klik tetap menjadi lapis terakhir.

### 3.4 Alasan pembagian ini (argumen desain)

- Pengambilan kutipan dan timestamp harus bisa diperiksa. Kode dapat memeriksa kesamaan teks; LLM tidak dapat dipercaya memeriksa dirinya sendiri. Aturan 2 di system prompt menyuruh LLM mengutip persis `[kode: loop.py SYSTEM_PROMPT]`, tetapi kepatuhan dijamin pemeriksaan kode, bukan prompt.
- Aksi yang tidak bisa dibatalkan (kirim email, membuat task) memerlukan keputusan manusia. Karena itu tool aksi tulis hanya membuat permintaan `[kode: tools.py:677 TOOLS, flag writes=True]`.
- Catatan pengamatan proyek: model tidak selalu patuh pada aturan di system prompt (contoh: aturan "ekstrak keempat jenis dulu" diabaikan), sehingga aturan penting dijadikan pemeriksaan di kode `[dok: HANDOFF_PROMPT.md, bagian "Temuan lama yang tetap berlaku"]`.

## 4. Contoh function calling: skema tool dan validasi di sisi penyedia

Temuan ini diamati nyata pada 2026-10-06 `[dok: 04_job_ekspor_ui.md bagian 12]`. Ringkasan yang dapat diverifikasi:

1. Skema tool dibuat dari model Pydantic `[kode: schemas.py tool_schema]`. Skema yang dikirim ke penyedia adalah kontrak yang juga divalidasi oleh penyedia.
2. Pada versi lama, skema `rekap_id` memuat `pattern` (huruf dan angka saja). Penyedia (Groq) memvalidasi argumen tool terhadap skema di sisinya dan menjawab 400 ("Tool call validation failed") sebelum kode kita berjalan, sehingga pesan koreksi dari tool tidak pernah sampai ke LLM `[dok: 04 bagian 12, poin 2]`. Pernyataan bahwa validasi terjadi di sisi Groq bersumber dari pengamatan itu; dokumentasi resmi Groq untuk perilaku ini belum saya verifikasi [belum diverifikasi].
3. Perbaikan, tiga lapis `[dok: 04 bagian 12, bagian Perbaikan]`:
   - Aturan format `rekap_id` dihapus dari skema yang dikirim; skema kini hanya `min_length` dan `max_length` dengan deskripsi `[kode: schemas.py _rekap_id_field]`. Format diperiksa kode di `_load_rekap`, yang mengembalikan `invalid_args` dengan pesan yang menerangkan perbedaan `rekap_id` dan `meeting_id` `[kode: tools.py:523]`.
   - Konteks yang selalu dilihat LLM menyebut "Belum ada rekap aktif" bila memang belum ada `[kode: loop.py _meeting_context]`.
   - Penolakan argumen oleh penyedia dianggap kesalahan yang dapat dipulihkan: loop menambah pesan koreksi (`TOOL_CORRECTION`) dan mencoba lagi, maksimal 2 kali per run `[kode: loop.py MAX_TOOL_CORRECTIONS]` `[trace: guardrail/tool_call_ditolak_provider]`.
4. Validasi sisi kode tetap ada setelah skema: `execute_tool` memvalidasi argumen dengan Pydantic (`extra="forbid"`) dan mencatat `guardrail/arg_validation` bila gagal `[kode: tools.py:739-755; schemas.py _Args]` `[trace: guardrail/arg_validation, tool_call/status=invalid_args]`.

Pelajaran desain (dirumuskan dari temuan di atas): skema tool adalah kontrak dengan penyedia, bukan hanya dokumentasi untuk LLM. Aturan yang terlalu ketat di skema dapat membuat kesalahan LLM tidak bisa dikoreksi; aturan itu lebih baik diperiksa di kode, yang bisa mengembalikan pesan perbaikan yang dapat dibaca LLM.

## 5. Spektrum otonomi

Dasar pembedaan workflow dan agent adalah artikel "Building Effective AI Agents" (Anthropic, 19 Desember 2024), https://www.anthropic.com/engineering/building-effective-agents `[dok: referensi 1, bagian 8]`. Menurut artikel itu, workflow adalah sistem yang LLM dan tool-nya diorkestrasi lewat jalur kode yang sudah ditetapkan, sedangkan agent adalah sistem yang LLM-nya mengarahkan sendiri proses dan pemakaian tool-nya (parafrasa saya). Judul, tanggal, dan pembedaan itu saya periksa dengan membuka halamannya pada 2026-10-07.

Kerangka empat tingkat di bawah ini adalah rumusan sendiri untuk dokumen ini, bukan kerangka dari artikel itu. Artikel hanya menyediakan pembedaan dua kelompok; pembagian menjadi empat tingkat, pemetaan ke kode proyek, dan penempatan MeetRecall di tingkat 3 adalah interpretasi penulis dokumen ini. Dengan definisi artikel, tingkat 1 dan 2 termasuk workflow dan tingkat 3 termasuk agent, dengan pembatas yang ditambahkan proyek ini (guardrail dan persetujuan).

| Tingkat | Siapa yang menentukan langkah berikutnya | Contoh di proyek ini |
|---|---|---|
| 1. Workflow tetap | Kode, seluruhnya | Job transkripsi dan antrean `[kode: config.py, komentar JOBS_DB "transcription jobs (workflow, not agent)"]` |
| 2. Workflow dengan LLM di langkah tertentu | Kode menentukan urutan; LLM mengerjakan satu langkah | `run_workflow` (mode `workflow`): urutan tool dikunci, LLM hanya di dalam `ekstrak_poin_meeting` `[kode: workflow.py docstring]` `[trace: mode="workflow"]` |
| 3. Agent dengan guardrail dan persetujuan | LLM memilih tool dan urutan; kode membatasi loop, memverifikasi, mengunci aksi tulis | `MeetingAgent.run` (mode `agent`) `[kode: loop.py]` `[trace: mode="agent"]` |
| 4. Agent otonom penuh | LLM, termasuk aksi tidak terbalikkan, tanpa persetujuan | Tidak ada di proyek ini |

MeetRecall berada di tingkat 3. Penjelasan pilihan ini untuk proses bisnis tindak lanjut meeting (argumen desain, bukan hasil evaluasi):

- Permintaan pengguna beragam (pertanyaan spesifik, rekap, laporan, task, email), sehingga urutan tool tidak tunggal. Itu alasan memakai loop LLM dan bukan satu workflow tetap.
- Bagian yang urutannya pasti, yaitu laporan dan task, sudah punya padanan workflow tetap di tingkat 2 untuk dibandingkan `[kode: workflow.py ACTIONS = ("laporan", "task")]`. Hanya 8 skenario evaluasi yang punya padanan itu `[dok: HANDOFF_PROMPT.md, bagian Status teknis]`.
- Aksi tidak terbalikkan (email, task) tidak diserahkan ke LLM, sehingga tingkat 4 sengaja tidak dipakai.

Apakah tingkat 3 memberi nilai tambah dibanding tingkat 2 belum diukur. Jawaban evaluasi belum dinilai dan workflow belum pernah dijalankan dengan LLM sungguhan `[dok: HANDOFF_PROMPT.md; dokumen 09]`. Hasilnya, apa pun arahnya, dilaporkan apa adanya.

### Apa yang belum ada pada tingkat 3 ini

Tidak ada langkah perencanaan eksplisit: sistem tidak meminta LLM menulis rencana sebelum bertindak, dan tidak ada kejadian trace untuk rencana `[kode: loop.py; tracing.py (jenis kejadian: run_start, llm_call, tool_call, guardrail, approval, run_end)]`. "Perencanaan" hanya terjadi implisit lewat pilihan tool per iterasi dan petunjuk di system prompt (aturan 6 dan 11). Tidak ada pula langkah yang meminta LLM menilai sendiri kelengkapan jawabannya; satu-satunya pemeriksaan sebelum jawaban akhir adalah verifikasi kutipan oleh kode (bagian 3.3).

## 6. Rencana pengembangan lanjut (tidak diimplementasikan)

Dua tambahan di bawah ini sengaja TIDAK dikerjakan sekarang. Alasan: mengubah kode atau system prompt di antara sesi A dan sesi B akan membuat hasil kedua sesi tidak sebanding, dan perbandingan workflow vs agent kehilangan dasar yang sama `[dok: HANDOFF_PROMPT.md, aturan pembekuan]`.

| Rencana | Gagasan | Titik sentuh bila kelak dikerjakan | Cara menilai |
|---|---|---|---|
| Planner eksplisit | Untuk permintaan multi-langkah, LLM menulis rencana singkat dahulu; rencana dicatat sebagai kejadian trace baru | `loop.py SYSTEM_PROMPT` dan kejadian trace baru di `tracing.py` | Bandingkan dengan sidik jari lama; jalankan skenario yang sama; laporkan "x dari y" terpisah dari hasil evaluasi saat ini |
| Self-check kelengkapan | Sebelum jawaban akhir, periksa bahwa semua bagian permintaan sudah dikerjakan. Bila diimplementasikan sebagai LLM, ia berbeda jenis dari verifikasi deterministik di bagian 3.3 dan harus diberi nama berbeda | `loop.py`, sebelum `finish("completed", ...)` | Sama seperti di atas |

Syarat sebelum dikerjakan: persetujuan pengguna, dan seluruh gelombang evaluasi yang direncanakan sudah selesai (atau pengguna memutuskan evaluasi berikutnya dimulai dari konfigurasi baru dan dicatat sebagai eksperimen terpisah). Kandidat pengembangan lain yang sudah tercatat: jalur lintas meeting dengan daftar yang diizinkan `[kode: tools.py:726 komentar]`, dan model pembanding Gemini (keputusan 5, ditunda) `[dok: HANDOFF_PROMPT.md]`.

## 7. Batasan dokumen ini

- Satu-satunya sumber luar yang dirujuk adalah referensi 1 di bagian 8. Isinya hanya dipakai untuk pembedaan workflow vs agent.
- Nomor baris diambil dari kode per 2026-10-07 dan dapat bergeser.
- Pernyataan tentang perilaku sisi penyedia (Groq) bersumber dari satu pengamatan proyek (dokumen 04 bagian 12), bukan dari dokumentasi resmi.
- Cara kerja di dalam panggilan ekstraksi (prompt dan skema output ekstraksi) tidak dibahas di sini; lihat `backend/agent/tools.py` dan dokumen 02 untuk rinciannya.
- Belum ada klaim tentang mutu jawaban agent. Evaluasi belum dinilai.

## 8. Referensi

1. Anthropic, "Building Effective AI Agents", 19 Desember 2024. https://www.anthropic.com/engineering/building-effective-agents. Diperiksa 2026-10-07 dengan membuka halaman: judul dan tanggal terbaca sesuai, dan halaman membedakan workflow (jalur kode yang ditetapkan) dari agent (LLM mengarahkan sendiri prosesnya). Dipakai hanya sebagai dasar pembedaan itu, bukan untuk empat tingkat di bagian 5.
