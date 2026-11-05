# Bahan PPT: materi W7-W8 dan proyek MeetRecall AI

Dipakai di Claude web. Lampirkan berkas di bagian 3, lalu tempel prompt di bagian 1. Kerangka slide di bagian 2 sudah ada di dalam prompt.

## 1. Prompt untuk Claude web

```
Buatkan presentasi PowerPoint (.pptx) berbahasa Indonesia, rasio 16:9, untuk dipresentasikan oleh Fiya di Tritronik.
Topik: materi W7-W8 "Agentic AI dan AI Orchestration" dan proyek MeetRecall AI sebagai penerapannya.

Sumber: hanya berkas yang saya lampirkan. Jangan menambah angka, fakta, atau nama yang tidak ada di sana.
Bila sebuah angka tidak ada di lampiran, tulis "(isi dari dokumen 09)" daripada menebak.

Gaya:
- Satu pesan per slide, judul berupa kalimat yang menyatakan pesan itu.
- Teks singkat (maksimal 5 butir, tiap butir satu baris). Detail masuk ke catatan pembicara (speaker notes), 3 sampai 5 kalimat per slide.
- Tampilkan angka hasil dalam bentuk tabel atau kartu angka, bukan paragraf.
- Pakai gambar docs/flowchart_end_to_end.png apa adanya di slide arsitektur (jangan digambar ulang).
- Tanpa teks tebal berlebihan; hierarki lewat ukuran huruf dan warna. Palet tenang: biru tua, abu, satu warna aksen.
- Jangan membuat klaim yang lebih kuat dari dokumen. Bila dokumen menyebut batas atau syarat, tampilkan.

Kerangka (sekitar 18 slide):
1. Judul
2. Masalah: tindak lanjut meeting dikerjakan manual dan mudah terlewat
3. Materi: spektrum otonomi (workflow, agent, multi-agent) dan kapan memilih yang mana
4. Posisi proyek di spektrum: agent dengan batas, bukan otonom penuh
5. Arsitektur end-to-end (gambar flowchart)
6. Pembagian kerja: apa yang diputuskan LLM, apa yang dikerjakan kode
7. Tujuh tool agent
8. Guardrail
9. Aksi tulis dua fase: persetujuan manusia di luar LLM
10. Anti-halusinasi: kutipan diverifikasi kode, sumber dan lokasi kutipan ditampilkan (contoh kasus Ginger Cola: atribusi speaker dikoreksi kode)
11. Workflow sebagai pembanding agent
12. MCP: apa itu, perannya di proyek, kapan perlu dan kapan tidak (pakai tabel dari docs/12)
13. Desain evaluasi: skenario, rekaman, penilaian otomatis dan manual, label terkunci hash
14. Hasil evaluasi: kartu angka dan tabel per jenis meeting
15. Yang tidak lulus dan penyebabnya
16. Temuan dan perbaikan setelah evaluasi
17. Batas dan keterbatasan (validitas hasil)
18. Alur demo dan rencana lanjutan

Setelah selesai, beri daftar singkat angka yang Anda pakai beserta berkas sumbernya, supaya saya bisa memeriksa.
```

## 2. Catatan isi per slide (untuk memeriksa hasil Claude)

Angka berikut dari docs/09 bagian 28.3. Evaluasi dijalankan pada kode sebelum MCP dan sebelum fitur sumber, dengan jalur tool langsung (local).

| Slide | Isi yang benar |
|---|---|
| 3-4 | Spektrum dan posisi proyek: docs/10. Proyek termasuk tingkat menengah dengan sifat enterprise (guardrail, persetujuan). |
| 6 | LLM: memilih tool, mengekstrak butir, menulis jawaban. Kode: verifikasi kutipan, statistik, susunan laporan, persetujuan, penerima email, meeting scope, write intent. |
| 7 | cari_transkrip, ekstrak_poin_meeting, statistik_meeting, ekspor_laporan, buat_task, kirim_email_rekap, minta_klarifikasi. |
| 8 | Input dan scope, validasi argumen, meeting scope, write intent, kutipan terverifikasi, transkrip sebagai data (deteksi injeksi), batas iterasi (8) dan error beruntun (2). |
| 9 | buat_task dan kirim_email_rekap hanya membuat permintaan persetujuan. User menyetujui di UI, kode mengeksekusi. Email hanya ke alamat milik user. Tidak ada tool persetujuan di MCP. |
| 10 | Kasus Ginger Cola: jawaban benar, tetapi speaker di kurung ditulis Speaker 0 padahal Speaker 2 (00:51-01:01). Kode kini mencari lokasi asli kutipan dan mengoreksi atribusi yang salah. |
| 12 | MCP memperluas jangkauan tool (satu server, banyak klien), bukan menambah otonomi. Saat ini dipakai dalam aplikasi lewat transport dalam proses. Claude Desktop dan Claude Code sudah tersambung ke server yang sama lewat stdio dan diuji dengan tool statistik_meeting (hasilnya cocok dengan transkrip). |
| 13 | 44 skenario agent, 54 rekaman (46 agent dan 8 workflow). Penilaian otomatis ditambah vonis manual. Label dikunci dengan hash SHA-256 sebelum hasil dilihat. |
| 14 | 36 dari 44 lulus (81,8%). Tanpa ES-01 (premis tidak terpenuhi): 36 dari 43 (83,7%). Per jenis meeting (penyebut 44): nyata berbahasa Inggris 20 dari 27 (74,1%); nyata berbahasa Indonesia 5 dari 5; sintesis berbahasa Indonesia 10 dari 11 (90,9%); sintesis berbahasa Inggris 1 dari 1. |
| 15 | Tidak lulus: W-01 dan IT-03 (otomatis), TN-03, K-03, DT-04, AM-02 (vonis pengguna), ES-02 (tidak teruji), ES-01 (premis tidak terpenuhi). |
| 16 | Perbaikan setelah evaluasi: aturan prompt penanggung jawab dan tenggat, urutan ID rekap mengikuti waktu, karakter PDF, simulasi isian persetujuan di harness. Penambahan setelahnya: MCP, sumber dan lokasi kutipan, koreksi atribusi. |
| 17 | Hasil gabungan memakai penilaian otomatis atas rekaman dan vonis manual dari pengujian langsung pada kode saat itu. Perbaikan dan rerun paket 2 belum dijalankan; hasilnya akan dilaporkan terpisah. |

## 3. Berkas yang dilampirkan di Claude web

1. docs/12_alur_end_to_end.pdf (alur, MCP, tabel kapan agentic saja atau MCP)
2. docs/flowchart_end_to_end.png (gambar slide 5)
3. docs/10_desain_llm_vs_kode_dan_spektrum_otonomi.md (slide 3, 4, 6)
4. docs/09_catatan_sesi_evaluasi.md (slide 13 sampai 17; bagian 18, 22 sampai 29)
5. docs/07_set_skenario_tahap4.md (daftar skenario dan kriteria)

Berkas 4 panjang. Kalau Claude web membatasi ukuran, lampirkan hanya bagian 28.3 sampai 29.4 dan minta ia menanyakan bagian lain bila perlu.

## 4. Setelah draf jadi

- Periksa semua angka terhadap tabel di bagian 2.
- Pastikan slide 17 tampil. Bagian itu yang menjaga klaim tetap jujur.
- Jangan mencantumkan kata "pasti" atau "terbukti" untuk hasil evaluasi; penyebutnya kecil dan sebagian vonis manual.
