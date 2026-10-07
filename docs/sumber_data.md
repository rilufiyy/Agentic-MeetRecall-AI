# Sumber data meeting

Judul, kanal, dan durasi diverifikasi pada 2026-10-05 lewat YouTube oEmbed dan metadata halaman video. Isi video belum ditonton; kecocokan untuk skenario (ada keputusan atau tidak, kejelasan audio) baru bisa dipastikan setelah transkripsi.

## Sudah ditranskripsi (W6)

| meeting_id | Judul file | Durasi | URL |
|---|---|---|---|
| 5c8ff57e-e6b9-4d21-ad36-cf517117ec6e | Business Meeting - Ginger Cola Launch | 3,4 menit | https://youtu.be/z-8o9sp8YIA (Pocket Passport) |
| 3b24bd74-a645-4a83-b48a-2c3487f2c9a3 | Weekly Meeting Example | 1,6 menit | https://youtu.be/3WrZMzqpFTc (WakeUpNYCTV) |
| 0653d0f8-0c12-47c9-8dc8-5855fad68819 | RAPAT EVALUASI KINERJA PEGAWAI - KELOMPOK 1 | 11,0 menit | https://youtu.be/nhmcJFQBtu8 (BANTENG OTKP 2) |
| 65c34785-5cb8-4ebc-b555-8e22a86eabf7 | 20180822 Plan team - Weekly meeting (GitLab) | 28,7 menit, 240 segmen, 4.890 kata, 3 speaker, provider gemini | https://www.youtube.com/watch?v=5DSN14BZTSA |
| c69b07e4-27e4-4e7c-8cb8-8eef47475245 | Sprint review Portal Mitra | 7,5 menit | sintetis (W6), bukan video |

README W6 mencantumkan https://www.youtube.com/live/qGFoZ8yodc4 ("[REC] Key Meeting - Engineering (Public Stream)", GitLab Unfiltered, 24 menit), tetapi transkripnya tidak ada di volume data W6.

## Kandidat baru

| Video | Kanal | Bahasa | Durasi | Catatan |
|---|---|---|---|---|
| https://www.youtube.com/watch?v=5DSN14BZTSA "20180822 Plan team - Weekly meeting" | GitLab (playlist Plan team) | EN | 28 menit | Rapat tim nyata, di bawah batas 30 menit Gemini dengan diarization |
| https://www.youtube.com/watch?v=qGFoZ8yodc4 "[REC] Key Meeting - Engineering (Public Stream)" | GitLab Unfiltered | EN | 24 menit | Sudah dirujuk di W6 |
| https://www.youtube.com/watch?v=ZuG_j87yGEc "KOMISI XIII DPR RI RAPAT DENGAR PENDAPAT DENGAN KEPALA BPIP" | TVR PARLEMEN | ID | 84 menit | Perlu dipotong ke maksimal 30 menit |
| https://www.youtube.com/watch?v=i3XeRro9_hA "KOMISI III DPR RI RAPAT KERJA DENGAN KETUA KOMISI YUDISIAL RI" | TVR PARLEMEN | ID | 112 menit | Alternatif, perlu dipotong |
| https://www.youtube.com/watch?v=cEdKpEQfDik "Virtual Team Meeting Role Play" | Madelaine Sanvictores Indino | EN | 22 menit | Role play mahasiswa |
| https://www.youtube.com/watch?v=Otj9tQXQbWg "Business Meeting Role Play" | Sumit Jha Motivation | EN | 6 menit | Pendek |
| https://www.youtube.com/watch?v=mNXnlKM1tUc "QI project team meeting role play 1" | ELFT QI | EN | 4 menit | Pendek |

## Batas transkripsi Gemini

- `gemini-3.5-transcribe`: file sampai 1 jam, tetapi maksimal 30 menit bila diarization atau timestamp per kata aktif. Sumber: https://ai.google.dev/gemini-api/docs/transcribe
- Free tier: input dan output "Free of charge"; konten free tier dapat dipakai Google untuk meningkatkan produk. Tier berbayar: input 0,003 USD per menit audio, output 0,002 USD per menit. Sumber: https://ai.google.dev/gemini-api/docs/pricing
- Batas kuota (RPM, TPM, RPD) tidak dicantumkan angkanya di dokumentasi; dilihat per project di https://aistudio.google.com/rate-limit. Sumber: https://ai.google.dev/gemini-api/docs/rate-limits
- Audio dihitung 32 token per detik untuk audio understanding Gemini (https://ai.google.dev/gemini-api/docs/audio). Halaman Transcribe tidak menyebut cara hitung token, jadi angka ini hanya perkiraan untuk model transcribe.

## Rencana data evaluasi Tahap 4 (keputusan 2026-10-05)

URL tiga video asli diberikan pengguna; judul dan kanal dicocokkan lewat YouTube oEmbed, dan Ginger Cola dicocokkan lagi lewat durasi halaman video (205 detik, sama dengan 03:25 di transkrip).

| No | Data | Peran | Status |
|---|---|---|---|
| 1 | Business Meeting - Ginger Cola Launch (EN, 3,4 menit) | Meeting normal dengan keputusan dan action item | Ada |
| 2 | Weekly Meeting Example (EN, 1,6 menit) | Meeting pendek | Ada |
| 3 | Rapat Evaluasi Kinerja Pegawai (ID, 11 menit) | Bahasa Indonesia, banyak usulan kebijakan | Ada |
| 4 | GitLab Plan team weekly (EN, 28,7 menit) | Meeting panjang, uji retrieval | Sudah ditranskripsi (Gemini, 94 detik) dari file lokal pengguna |
| 5 | Diskusi panel atau podcast berbahasa Indonesia tanpa keputusan atau action item | Uji negatif | Menunggu URL dari pengguna |
| 6 | Transkrip sintetis W6 (sprint review) | Skenario injection dan kutipan | Ada |

Rapat DPR tidak dipakai (keputusan pengguna). Kriteria untuk data 5: netral (bukan politik atau tokoh publik yang sensitif), maksimal 30 menit atau bisa dipotong, audio jelas, minimal 2 pembicara, tanpa kesepakatan atau penugasan eksplisit. Saya mencari kandidat lewat web search dan tidak menemukan yang layak diverifikasi, jadi pemilihannya diserahkan ke pengguna.
