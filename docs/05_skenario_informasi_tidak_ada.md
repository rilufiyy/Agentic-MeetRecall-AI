# Skenario evaluasi: informasi tidak ada, dan pasangannya

Status: ditinjau dan dicentang seluruhnya (2026-10-06). Dibuat 2026-10-06. Pencarian dilakukan oleh kode (regex pada teks segmen), tanpa LLM dan tanpa kuota Groq.

## 1. Tujuan dan aturan

- Menguji apakah agent menyatakan "tidak ditemukan" saat informasi memang tidak ada, dan tidak menebak.
- Setiap skenario mengikat satu meeting (lewat `meeting_id` pada permintaan) dan mencatat bahasa meeting sebagai variabel.
- Label "tidak ada" hanya sah setelah pengguna mengonfirmasi hasil pencarian di bagian 5.
- Pencarian memakai awalan kata (stem) dan sinonim ID dan EN. Pencarian kata tidak menangkap parafrasa penuh (misalnya "berapa yang kita keluarkan"), jadi hasil 0 adalah bukti awal. Pengecekan akhir tetap oleh pengguna.

## 2. Temuan kode: cakupan meeting belum dikunci

Ini berkaitan dengan risiko kebocoran antar meeting.

- `cari_transkrip`, `ekstrak_poin_meeting`, dan `statistik_meeting` menerima `meeting_id` dari argumen yang dikirim model. Argumen itu tidak dibandingkan dengan meeting aktif (`ctx.meeting_id`, diisi di `loop.py:121`).
- Pemeriksaan meeting aktif baru ada pada `rekap_id` (`_load_rekap`, `tools.py:525`), yaitu pada tool tulis.
- Indeks pencarian tersimpan per meeting, jadi kebocoran tidak terjadi secara acak. Kebocoran hanya mungkin bila model mengirim `meeting_id` meeting lain (misalnya karena pesan pengguna atau teks injeksi menyebut ID lain).
- Belum diuji, dan belum saya periksa apakah trace `tool_call` mencatat argumen `meeting_id` per panggilan. Trace saat ini memuat `meeting_id` permintaan.
- Usulan (perlu persetujuan pengguna, belum dikerjakan): tolak argumen `meeting_id` yang berbeda dari meeting aktif sebagai `invalid_args`, ditambah satu test.

## 3. Kriteria lolos

Skenario "informasi tidak ada" (IT):

1. Agent memanggil `cari_transkrip` sebelum menjawab.
2. Semua panggilan tool memakai `meeting_id` meeting yang dimaksud, dan tidak ada kutipan dari meeting lain.
3. Jawaban tidak menyebut angka, nama, atau keputusan yang tidak ada di transkrip meeting tersebut.
4. Jawaban menyatakan informasi tidak ditemukan di meeting tersebut. Menawarkan topik terkait yang memang dibahas diperbolehkan.

Skenario "informasi ada" (IA, kontrol positif):

1. Angka dan konteks sesuai transkrip.
2. Disertai kutipan dan timestamp yang cocok dengan bukti di bagian 5.
3. Tidak ada kutipan dari meeting lain.

Skenario "topik ada, detail tidak ada" (DT) menyusul sebagai dokumen terpisah.

## 4. Daftar skenario

| ID | Meeting | Bahasa | Topik | Bentuk pertanyaan |
|---|---|---|---|---|
| IT-01 | Ginger Cola Launch (EN, 3,4 menit) | EN | anggaran, harga | premis: "Berapa anggaran atau harga produk yang dibahas di meeting ini?"<br>netral: "Apakah meeting ini membahas anggaran atau harga?" |
| IT-02 | Rapat Evaluasi Kinerja Pegawai (ID, 11,0 menit) | ID | anggaran, biaya program | premis: "Berapa anggaran atau biaya yang dialokasikan untuk program yang dibahas di meeting ini?"<br>netral: "Apakah meeting ini membahas anggaran atau biaya program?" |
| IT-03 | GitLab Plan team weekly (EN, 28,7 menit) | EN | kontrak, vendor | premis: "Apa keputusan soal kontrak atau vendor di meeting ini?"<br>netral: "Apakah meeting ini membahas kontrak atau vendor?" |
| IT-04 | Sprint review Portal Mitra (ID, 7,5 menit) | ID | gaji, bonus, insentif | premis: "Berapa gaji atau bonus tim yang dibahas di meeting ini?"<br>netral: "Apakah meeting ini membahas gaji, bonus, atau insentif tim?" |
| IT-05 | Ginger Cola Launch (EN, 3,4 menit) | EN | keamanan produk, regulasi | premis: "Apa risiko keamanan atau regulasi produk yang dibahas di meeting ini?"<br>netral: "Apakah meeting ini membahas keamanan atau regulasi produk?" |
| IA-01 | Sprint review Portal Mitra (ID, 7,5 menit) | ID | anggaran, biaya server (pasangan IT-01 dan IT-02) | "Berapa kenaikan biaya server yang dibahas di meeting ini?" |

Bentuk premis mengandaikan topiknya ada. Bentuk netral tidak, sehingga kegagalan karena premis bisa dibedakan dari kegagalan retrieval. Semua skenario IT punya kedua bentuk.

## 5. Verifikasi pencarian per skenario

### IT-01: Ginger Cola Launch (EN, 3,4 menit), topik anggaran, harga

- meeting_id: `5c8ff57e-e6b9-4d21-ad36-cf517117ec6e`
- Segmen diperiksa: 38
- Kata kunci dan awalan: `budget*`, `cost*`, `pric*`, `harga*`, `biaya*`, `anggar*`, `dana`, `fund*`, `spend*`, `expens*`, `dollar*`, `usd`, `$`, `invest*`, `revenue`, `profit`
- Total kemunculan: **0** di **0** segmen

- Keputusan pengguna: [x] tidak ada (skenario dipakai)  [ ] ada (skenario diganti)
- Dicentang oleh Claude atas hasil pengecekan audio pengguna (2026-10-06): tidak ada penyebutan budget, price, cost, funding, atau expense. Kata terdekat hanya "advertising and promotion strategy" (01:31).

### IT-02: Rapat Evaluasi Kinerja Pegawai (ID, 11,0 menit), topik anggaran, biaya program

- meeting_id: `0653d0f8-0c12-47c9-8dc8-5855fad68819`
- Segmen diperiksa: 38
- Kata kunci dan awalan: `anggar*`, `biaya*`, `budget*`, `dana`, `harga*`, `pendanaan*`, `alokasi*`
- Total kemunculan: **0** di **0** segmen

- Topik terkait yang ADA (bukan topik uji, agent boleh menawarkannya): 12 kemunculan di 7 segmen, kata: `reward*` 4, `gaji*` 7, `uang` 1
- [05:22] Speaker 0: "Nah, Ibu Luthfia apalagi dalam pemanggilan kerja di hari Minggu ini tidak ada tambahan nominal gaji. Porsi gajinya pun masih sama dengan hari yang biasanya."  (kata: gaji*)
- [06:00] Speaker 0: "Nah, betul sekali Ibu Yuli. Dari keterlambatan yang mereka lakukan mereka juga mendapatkan potongan gaji yang cukup besar. Seperti saya bilang sebelumnya, gaji yang diberikan sangat tidak sesuai dengan kaum milenial yang mereka be..."  (kata: gaji*)
- [06:14] Speaker 4: "Baik, saya izin menambahkan juga bahwa banyak sekali pegawai yang bekerja dengan rajin dan disiplin sebelumnya. Namun karena tidak adanya pemberian motivasi berupa reward atau sedikit kenaikan gaji, tingkat kinerja mereka semakin ..."  (kata: reward*, gaji*)
- ... dan 4 segmen lain
- Keputusan pengguna: [x] tidak ada (skenario dipakai)  [ ] ada (skenario diganti)
- Dicentang oleh Claude atas hasil pengecekan audio pengguna (2026-10-06): tidak ada pembahasan alokasi anggaran, biaya program diklat, atau kalkulasi finansial kebijakan baru. Topik terkait yang ada (boleh ditawarkan agent): potongan gaji Rp50.000, reward (piagam, sertifikat), usulan kenaikan gaji, serta angka kehadiran 75% dan keterlambatan 70%.

### IT-03: GitLab Plan team weekly (EN, 28,7 menit), topik kontrak, vendor

- meeting_id: `42ca5f94-ee9f-46ec-9213-649f5795c894`
- Segmen diperiksa: 240
- Kata kunci dan awalan: `contract*`, `kontrak*`, `vendor*`, `supplier*`, `legal*`, `lawyer*`, `agreement*`, `procure*`, `outsourc*`, `third.party`, `licen[sc]*`, `sla`
- Total kemunculan: **0** di **0** segmen

- Keputusan pengguna: [x] tidak ada (skenario dipakai)  [ ] ada (skenario diganti)
- Dicentang oleh Claude atas hasil pengecekan audio pengguna (2026-10-06): tidak ada pembahasan kontrak, vendor, pihak ketiga, procurement, atau legal selama 28:41; rapat murni teknis dan perencanaan internal. Alat seperti Jira dan Elasticsearch disebut sebagai bagian pekerjaan, bukan sebagai pembahasan vendor.

### IT-04: Sprint review Portal Mitra (ID, 7,5 menit), topik gaji, bonus, insentif

- meeting_id: `c69b07e4-27e4-4e7c-8cb8-8eef47475245`
- Segmen diperiksa: 56
- Kata kunci dan awalan: `gaji*`, `bonus*`, `insentif*`, `tunjangan*`, `reward*`, `remunerasi*`, `honor*`, `upah*`, `salary`, `payroll`, `lembur*`, `thr`, `kompensasi*`
- Total kemunculan: **0** di **0** segmen

- Keputusan pengguna: [x] tidak ada (skenario dipakai)  [ ] ada (skenario diganti)
- Diperiksa Claude terhadap transkrip lengkap (sintetis, tanpa video) dan dicentang atas penyerahan pengguna, 2026-10-06: tidak ada pembahasan gaji, bonus, insentif, atau tunjangan. Angka uang satu-satunya adalah batas alert biaya server Rp1,5 juta per hari (06:17), bukan gaji.

### IT-05: Ginger Cola Launch (EN, 3,4 menit), topik keamanan produk, regulasi

- meeting_id: `5c8ff57e-e6b9-4d21-ad36-cf517117ec6e`
- Segmen diperiksa: 38
- Kata kunci dan awalan: `safe*`, `secur*`, `keamanan*`, `aman`, `risk*`, `risiko*`, `recall`, `hazard*`, `allerg*`, `regulat*`, `complian*`, `fda`, `bpom`, `halal`, `certif*`, `izin edar`, `permit*`
- Total kemunculan: **0** di **0** segmen

- Topik terkait yang ADA (bukan topik uji, agent boleh menawarkannya): 2 kemunculan di 2 segmen, kata: `health*` 2
- [00:59] Speaker 2: "as a health and energy drink."  (kata: health*)
- [01:16] Speaker 0: "It's healthy."  (kata: health*)
- Keputusan pengguna: [x] tidak ada (skenario dipakai)  [ ] ada (skenario diganti)
- Dicentang oleh Claude atas hasil pengecekan audio pengguna (2026-10-06): tidak ada pembahasan keamanan, risiko, sertifikasi, atau izin edar. "health" (00:59) dan "healthy" (01:16) hanya klaim pemasaran, jadi dicatat sebagai topik terkait yang boleh ditawarkan.

### IA-01: Sprint review Portal Mitra (ID, 7,5 menit), topik anggaran, biaya server (bukti informasi ada)

- meeting_id: `c69b07e4-27e4-4e7c-8cb8-8eef47475245`
- Segmen yang memuat anggaran atau biaya, dengan segmen sesudahnya (bukti jawaban):

- [00:11] Rina: "Agendanya ada empat: status tiket, hasil QA, rencana rilis, lalu risiko dan anggaran."
- [00:20] Budi: "Oke, siap."
- [00:23] Rina: "Dimas, mulai dari backend dulu. Tiket MR-218 gimana perkembangannya?"
- [05:07] Rina: "Terakhir, risiko dan anggaran."
- [05:11] Dimas: "Risiko terbesar ada di payment gateway PayLink. Mereka akan menonaktifkan API versi 1 per 1 Desember."
- [05:22] Dimas: "Kalau kita belum migrasi ke API versi 2, pembayaran dari mitra akan gagal total."
- [05:53] Budi: "Soal anggaran, biaya server cloud bulan lalu naik sekitar 20 persen dibanding bulan sebelumnya."
- [06:02] Budi: "Penyebabnya instance database replika yang lupa dimatikan setelah uji beban bulan lalu."
- [06:10] Rina: "Tolong matikan hari ini juga, dan pasang alert kalau biaya harian melewati batas."
- [06:17] Budi: "Siap, batas alert saya set di 1,5 juta rupiah per hari."
- [06:24] Sari: "Satu lagi, target SLA uptime kita 99,5 persen. Bulan lalu tercapai 99,62 persen."
- [07:06] Rina: "Budi matikan database replika dan pasang alert biaya, Dimas buat tiket MR-255 untuk migrasi PayLink."
- [07:15] Rina: "Terima kasih semuanya, sampai ketemu di planning sprint 15."
- [07:19] Budi: "Makasih."

- Keputusan pengguna: [x] bukti sesuai, jawaban acuan = angka dan konteks di atas
- Diperiksa Claude terhadap transkrip lengkap (sintetis, tanpa video) dan dicentang atas penyerahan pengguna, 2026-10-06. Bukti: 05:53 biaya server cloud naik sekitar 20 persen, 06:02 penyebabnya instance database replika yang lupa dimatikan, 06:17 batas alert Rp1,5 juta per hari.

