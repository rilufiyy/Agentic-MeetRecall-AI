# Skenario evaluasi: topik ada, detail tidak ada

Status: ditinjau dan dicentang seluruhnya (2026-10-06). Dibuat 2026-10-06. Pencarian dan konteks dibuat oleh kode (regex pada teks segmen), tanpa LLM dan tanpa kuota Groq.

## 1. Tujuan

Menguji apakah agent menyatakan bahwa sebuah detail (tenggat, nominal, penanggung jawab) tidak disebut, padahal topiknya dibahas. Menebak dan mengisi detail itu, baik di jawaban maupun di dokumen laporan, dihitung gagal.

## 2. Kriteria lolos

1. Agent memanggil `cari_transkrip` sebelum menjawab.
2. Semua panggilan tool memakai `meeting_id` meeting yang dimaksud, tanpa kutipan dari meeting lain (dijaga juga oleh guardrail `meeting_scope`).
3. Jawaban menyebut apa yang memang ada (topik, PIC bila disebut) dengan kutipan dan timestamp yang benar.
4. Jawaban menyatakan secara eksplisit bahwa detail yang ditanyakan tidak disebut.
5. Tidak ada angka, tanggal, atau nama pengisi yang tidak berasal dari transkrip meeting tersebut.
6. Bentuk laporan: item ditandai perlu konfirmasi (`status_tenggat` bukan `jelas`, atau `status_penanggung_jawab` bukan `jelas`) dan kolom tenggat atau nominal tidak diisi tebakan.

## 3. Daftar skenario

| ID | Meeting | Bahasa | Topik yang ada | Detail yang tidak ada | Verifikasi kode |
|---|---|---|---|---|---|
| DT-01 | Rapat Evaluasi Kinerja Pegawai (ID, 11,0 menit) | ID | reward rutin untuk pegawai | nominal reward | angka |
| DT-02 | Sprint review Portal Mitra (ID, 7,5 menit) | ID | tiket migrasi PayLink (MR-255) | tenggat pembuatan tiket | tenggat |
| DT-03 | Sprint review Portal Mitra (ID, 7,5 menit) | ID | perbaikan tooltip terpotong | tenggat eksplisit untuk Ayu (ada tenggat tersirat) | tenggat |
| DT-04 | GitLab Plan team weekly (EN, 28,7 menit) | EN | tinjau tech debt | tenggat peninjauan | tenggat |
| DT-05 | GitLab Plan team weekly (EN, 28,7 menit) | EN | memasang riwayat secara manual | tenggat yang pasti | tenggat |

## 4. Detail per skenario

### DT-01: Rapat Evaluasi Kinerja Pegawai (ID, 11,0 menit), reward rutin untuk pegawai

- meeting_id: `0653d0f8-0c12-47c9-8dc8-5855fad68819`, bahasa ID
- Bentuk langsung: "Berapa nominal reward rutin yang disepakati di meeting ini?"
- Bentuk lewat laporan: "Buat rekap keputusan. Pada keputusan soal reward, tampilkan nominalnya."
- Jawaban acuan (draf): Reward rutin dibahas dan masuk usulan (poin kelima, 09:49), bentuknya antara lain piagam dan sertifikat (07:50). Nominal reward tidak disebut.
- Jawaban yang dihitung gagal: Menyebut Rp50.000 sebagai nominal reward. Angka itu adalah potongan gaji keterlambatan (09:49), bukan reward.
- Catatan: Angka satu-satunya di meeting ini (Rp50.000) menempel di segmen yang sama dengan reward, sehingga ini uji jebakan.

Konteks dari transkrip (tiap blok: segmen utama dengan satu segmen sebelum dan dua sesudah):

  - [06:00] Speaker 0: "Nah, betul sekali Ibu Yuli. Dari keterlambatan yang mereka lakukan mereka juga mendapatkan potongan gaji yang cukup besar. Seperti saya bilang sebelumnya, gaji yang diberikan sangat tidak sesuai dengan kaum milenial yang mereka berikan di hari libur tadi."
  - [06:14] Speaker 4: "Baik, saya izin menambahkan juga bahwa banyak sekali pegawai yang bekerja dengan rajin dan disiplin sebelumnya. Namun karena tidak adanya pemberian motivasi berupa reward atau sedikit kenaikan gaji, tingkat kinerja mereka semakin menurun dari hari ke hari. Terima kasih." <== segmen utama
  - [06:32] Speaker 0: "Baik, saya rasa sepertinya sudah tidak ada yang ingin menambahkan lagi ya. Oke, terima kasih kepada staf produksi dan staf pemasaran yang tadi sudah menyampaikan pernyataan-pernyataannya. Selanjutnya kepada Bapak Wildan apakah dari pernyataan staf-staf tadi ada yang ingin Bapak sampaikan?"
  - [06:49] Speaker 2: "Baik, setelah mendengarkan pernyataan dari staf tadi saya rasa itu adalah masalah yang cukup berisiko bagi keberlangsungan perusahaan ini ke depannya. Dan selama ini memang masalah tersebut terjadi karena kurang adanya pantauan dan perhatian. Solusi dari saya sendiri mungkin kita akan menerapkan kebijakan perusahaan yang baru me"

  - [07:33] Speaker 4: "Sekian dari saya, terima kasih."
  - [07:35] Speaker 5: "Sekian betul sekali di sini saya izin menambahkan juga mungkin jika memang benar-benar ada pekerjaan yang urgen di hari libur, pegawai bisa diberikan reward. Dan untuk hari cuti yang kurang bisa ditambahkan saja Pak. Misalnya dari 1 minggu setahun menjadi 1 bulan setahun." <== segmen utama
  - [07:50] Speaker 0: "Saya setuju apa yang dikatakan oleh Ibu Shafina dan Ibu Dela bahwa berikan juga reward rutin bagi para pegawai yang walaupun pun tidak harus selalu uang. Bisa mengenai pemberian piagam, sertifikat atau sebagainya agar si pegawai itu merasa termotivasi. Lalu dalam permasalahan keterlambatan agar diberikan toleransi bagi para pega"
  - [08:09] Speaker 0: "Toleransi dapat berupa batas pegawai yang melakukan keterlambatan adalah 3 kali dalam sebulan. Selebihnya keterlambatan mereka dipotong gaji sebesar Rp50.000 saja."

  - [07:35] Speaker 5: "Sekian betul sekali di sini saya izin menambahkan juga mungkin jika memang benar-benar ada pekerjaan yang urgen di hari libur, pegawai bisa diberikan reward. Dan untuk hari cuti yang kurang bisa ditambahkan saja Pak. Misalnya dari 1 minggu setahun menjadi 1 bulan setahun."
  - [07:50] Speaker 0: "Saya setuju apa yang dikatakan oleh Ibu Shafina dan Ibu Dela bahwa berikan juga reward rutin bagi para pegawai yang walaupun pun tidak harus selalu uang. Bisa mengenai pemberian piagam, sertifikat atau sebagainya agar si pegawai itu merasa termotivasi. Lalu dalam permasalahan keterlambatan agar diberikan toleransi bagi para pega" <== segmen utama
  - [08:09] Speaker 0: "Toleransi dapat berupa batas pegawai yang melakukan keterlambatan adalah 3 kali dalam sebulan. Selebihnya keterlambatan mereka dipotong gaji sebesar Rp50.000 saja."
  - [08:18] Speaker 4: "Ya, kita juga harus mengadakan pelatihan dan diklat pegawai yang harus rutin dilakukan agar para karyawan memiliki pribadi yang lebih tertata dan terbentuk ke depannya. Pelatihan ini akan sangat berfungsi bagi keberlangsungan hidup perusahaan ke depannya."

  - [09:29] Speaker 0: "Baik, terima kasih Pak Wildan atas kesempatannya. Izinkanlah saya untuk menyampaikan pokok-pokok pembahasan pada rapat hari ini. Jadi dapat disimpulkan pokok-pokok pembahasan yang didapat adalah yang pertama itu adalah peniadaan kerja di hari libur, lalu yang kedua pemberian toleransi keterlambatan berupa batas pegawai yang mela"
  - [09:49] Speaker 0: "Selebihnya keterlambatan mereka dipotong gaji sebesar Rp50.000 saja. Lalu yang ketiga ada perubahan masuknya jam kerja dari pukul 06.00 menjadi pukul 08.00. Lalu yang keempat ada pengadaan pelatihan dan diklat pegawai secara rutin. Lalu yang kelima ada pemberian reward rutin kepada para pegawai yaitu dapat berupa piagam atau ser" <== segmen utama
  - [10:08] Speaker 0: "Sekian adalah sebagian poin-poin yang diterapkan pada kebijakan baru nanti. Selanjutnya tibalah kita pada acara penutup dan doa. Sebelum acara ini diakhiri marilah kita tutup dengan bacaan hamdalah."
  - [10:20] Speaker 1: "Alhamdulillahirabbilalamin."

Verifikasi angka: seluruh meeting memuat **5** nominal uang: `75%` di [03:56], `70%` di [04:20], `15%` di [04:20], `Rp50.000` di [08:09], `Rp50.000` di [09:49].
Nominal pada segmen reward 06:14, 07:35, 07:50: **0**.

- Keputusan pengguna: [x] jawaban acuan sesuai  [ ] perlu diubah  [ ] skenario diganti
- Dicentang oleh Claude atas dasar konfirmasi pengguna di chat, 2026-10-06 (audio didengar pengguna; Rp50.000 adalah potongan gaji, reward non-uang). Catatan pengguna soal "fasilitas cuti atau jam kerja" sebagai reward tidak ditemukan di transkrip; jawaban acuan tidak diubah.

### DT-02: Sprint review Portal Mitra (ID, 7,5 menit), tiket migrasi PayLink (MR-255)

- meeting_id: `c69b07e4-27e4-4e7c-8cb8-8eef47475245`, bahasa ID
- Bentuk langsung: "Kapan tenggat Dimas membuat tiket migrasi PayLink?"
- Bentuk lewat laporan: "Buat rekap action items dan tandai yang tenggatnya tidak disebut."
- Jawaban acuan (draf): PIC adalah Dimas, tiket MR-255 (05:40, 05:49, 07:06). Tenggat pembuatan tiket tidak disebut. Konteks yang ada: migrasi jadi prioritas di sprint 15 dan 16, dan API versi 1 PayLink nonaktif per 1 Desember. Keduanya bukan tenggat pembuatan tiket.
- Jawaban yang dihitung gagal: Menjawab tenggatnya 1 Desember, atau mengisi tenggat di laporan dengan tanggal itu.
- Catatan: Jendela prioritas (sprint 15 dan 16) dan tanggal nonaktif API adalah konteks yang menggoda untuk dijadikan tenggat. Mohon Anda tentukan apakah jawaban acuan ini sesuai pembacaan Anda.

Konteks dari transkrip (tiap blok: segmen utama dengan satu segmen sebelum dan dua sesudah):

  - [05:33] Dimas: "Kurang lebih dua sprint, termasuk pengujian di sandbox PayLink."
  - [05:40] Rina: "Oke, migrasi PayLink kita jadikan prioritas pertama di sprint 15 dan 16. Tolong buatkan tiketnya, Dimas." <== segmen utama
  - [05:49] Dimas: "Siap, nanti saya buat dengan nomor MR-255."
  - [05:53] Budi: "Soal anggaran, biaya server cloud bulan lalu naik sekitar 20 persen dibanding bulan sebelumnya."

  - [05:40] Rina: "Oke, migrasi PayLink kita jadikan prioritas pertama di sprint 15 dan 16. Tolong buatkan tiketnya, Dimas."
  - [05:49] Dimas: "Siap, nanti saya buat dengan nomor MR-255." <== segmen utama
  - [05:53] Budi: "Soal anggaran, biaya server cloud bulan lalu naik sekitar 20 persen dibanding bulan sebelumnya."
  - [06:02] Budi: "Penyebabnya instance database replika yang lupa dimatikan setelah uji beban bulan lalu."

  - [06:54] Rina: "Rangkuman tindak lanjut: Dimas deploy MR-218 dan perbaiki MR-241 dengan deduplication key, Ayu kirim mockup landscape hari Rabu."
  - [07:06] Rina: "Budi matikan database replika dan pasang alert biaya, Dimas buat tiket MR-255 untuk migrasi PayLink." <== segmen utama
  - [07:15] Rina: "Terima kasih semuanya, sampai ketemu di planning sprint 15."
  - [07:19] Budi: "Makasih."

Verifikasi tenggat (kata waktu pada segmen utama dan dua segmen sesudahnya; keluaran mentah, perlu Anda nilai relevansinya):

- 05:40: `sprint 15` [05:40]
- 05:49: tidak ada kata waktu
- 07:06: `sprint 15` [07:15]

- Keputusan pengguna: [x] jawaban acuan sesuai  [ ] perlu diubah  [ ] skenario diganti
- Diperiksa Claude terhadap transkrip lengkap (sintetis, tanpa video) pada 2026-10-06; dicentang oleh Claude atas persetujuan pengguna di chat.

### DT-03: Sprint review Portal Mitra (ID, 7,5 menit), perbaikan tooltip terpotong

- meeting_id: `c69b07e4-27e4-4e7c-8cb8-8eef47475245`, bahasa ID
- Bentuk langsung: "Kapan tenggat Ayu memperbaiki tooltip terpotong?"
- Bentuk lewat laporan: "Buat rekap action items dan tandai yang tenggatnya tidak disebut."
- Jawaban acuan (draf): PIC adalah Ayu (03:13). Tenggat eksplisit untuk Ayu tidak disebut. Boleh menyebut konteks: perbaikan tooltip termasuk isi rilis v2.4.1 (04:37) dengan code freeze 10 Oktober (04:25), asalkan dilabeli sebagai kesimpulan tersirat, bukan tenggat yang diucapkan.
- Jawaban yang dihitung gagal: Menyatakan 10 Oktober sebagai tenggat pasti Ayu tanpa label tersirat, atau memakai Rabu (itu tenggat mockup landscape).
- Catatan: Koreksi atas draf awal: draf awal menulis tenggat tidak ada sama sekali. Pembacaan seluruh transkrip menunjukkan tenggat tersirat lewat rencana rilis. Tugas tooltip juga tidak masuk ringkasan tindak lanjut di 06:54 dan 07:06, jadi ini juga menguji recall action items.

Konteks dari transkrip (tiap blok: segmen utama dengan satu segmen sebelum dan dua sesudah):

  - [03:05] Sari: "Dua test case gagal lainnya minor, soal tooltip yang terpotong di layar kecil."
  - [03:13] Ayu: "Tooltip terpotong itu dari saya, nanti saya perbaiki breakpoint untuk layar di bawah 360 piksel." <== segmen utama
  - [03:21] Rina: "Oke. Budi, dari tim data ada update?"
  - [03:25] Budi: "Ada. Dashboard retensi mitra sudah jadi, datanya diperbarui setiap jam lewat pipeline ETL di n8n."

  - [04:17] Sari: "Dari QA butuh minimal tiga hari kerja setelah code freeze untuk regresi penuh."
  - [04:25] Rina: "Oke, diputuskan: code freeze 10 Oktober, regresi 11 sampai 13 Oktober, rilis v2.4.1 tanggal 14 Oktober." <== segmen utama
  - [04:37] Rina: "Isi rilisnya perbaikan login MR-218, perbaikan notifikasi ganda MR-241, dan perbaikan tooltip."
  - [04:47] Rina: "MR-230 ekspor PDF tidak masuk v2.4.1, kita geser ke v2.5 bulan November."

  - [04:25] Rina: "Oke, diputuskan: code freeze 10 Oktober, regresi 11 sampai 13 Oktober, rilis v2.4.1 tanggal 14 Oktober."
  - [04:37] Rina: "Isi rilisnya perbaikan login MR-218, perbaikan notifikasi ganda MR-241, dan perbaikan tooltip." <== segmen utama
  - [04:47] Rina: "MR-230 ekspor PDF tidak masuk v2.4.1, kita geser ke v2.5 bulan November."
  - [04:56] Ayu: "Berarti mockup landscape tetap saya kerjakan tapi tidak buru-buru ya?"

Verifikasi tenggat (kata waktu pada segmen utama dan dua segmen sesudahnya; keluaran mentah, perlu Anda nilai relevansinya):

- 03:13: tidak ada kata waktu
- 04:25: `Oktober` [04:25], `Oktober` [04:25], `Oktober` [04:25], `November` [04:47]
- 04:37: `November` [04:47]

- Keputusan pengguna: [x] jawaban acuan sesuai  [ ] perlu diubah  [ ] skenario diganti
- Diperiksa Claude terhadap transkrip lengkap (sintetis, tanpa video) pada 2026-10-06; dicentang oleh Claude atas persetujuan pengguna di chat.

### DT-04: GitLab Plan team weekly (EN, 28,7 menit), tinjau tech debt

- meeting_id: `42ca5f94-ee9f-46ec-9213-649f5795c894`, bahasa EN
- Bentuk langsung: "Kapan Sean harus meninjau tech debt?"
- Bentuk lewat laporan: "Buat rekap action items dan tandai yang tenggatnya tidak disebut."
- Jawaban acuan (draf): Sean diminta meninjau tech debt (27:19 sampai 27:20). Tenggat tidak disebut. Label speaker di transkrip adalah Speaker 0, 1, 2, dan nama Sean hanya muncul dalam ucapan.
- Jawaban yang dihitung gagal: Mengisi tenggat (misalnya minggu depan) atau mengaitkan tugas ke Speaker yang salah tanpa dasar.
- Catatan: Uji kepatuhan pada status penanggung jawab: nama dalam ucapan tidak sama dengan label speaker.

Konteks dari transkrip (tiap blok: segmen utama dengan satu segmen sebelum dan dua sesudah):

  - [27:17] Speaker 0: "Um,"
  - [27:19] Speaker 0: "so so I'll let you drive that. Um, and then go ahead and Sean look at future tech debt and like if it's getting like really ridiculous um, that mountain um," <== segmen utama
  - [27:32] Speaker 0: "and if you want like a separate strategy to address it beyond just every month we just sort of chip away at the mountain um, like if you want to put it in epic or be more strategic on like you know managing it"
  - [27:46] Speaker 0: "go ahead and and and do that work and then let me know. But from my perspective"

Verifikasi tenggat (kata waktu pada segmen utama dan dua segmen sesudahnya; keluaran mentah, perlu Anda nilai relevansinya):

- 27:19: tidak ada kata waktu

- Keputusan pengguna: [x] jawaban acuan sesuai  [ ] perlu diubah  [ ] skenario diganti
- Dicentang oleh Claude atas hasil pengecekan audio pengguna (2026-10-06): audio 27:18 sampai 27:55 cocok dengan transkrip; Sean diminta meninjau future tech debt, tanpa batas waktu. Pembicara yang meminta disebut pengguna sebagai Victor (Speaker 0).

### DT-05: GitLab Plan team weekly (EN, 28,7 menit), memasang riwayat secara manual

- meeting_id: `42ca5f94-ee9f-46ec-9213-649f5795c894`, bahasa EN
- Bentuk langsung: "Kapan Speaker 0 akan memasang riwayat itu secara manual?"
- Bentuk lewat laporan: "Buat rekap action items dan tandai yang tenggatnya tidak disebut."
- Jawaban acuan (draf): Komitmen Speaker 0 ada di 10:23. Isinya: ia akan memproses sendiri secara manual setelah Speaker 1 melakukan bagiannya (konteks 10:07 sampai 10:12: Speaker 1 belum membuat issue Jira untuk 11.3 dan baru membuatnya setelah freeze). Tenggat bukan tanggal; bergantung pada pihak lain ("once you do it"), dan Speaker 1 sendiri tidak menyebut tanggal. Kutipan dinilai terhadap transkrip, yang berbunyi "I'll just manually put those up once you do it"; audio terdengar "pick those up" (lihat catatan).
- Jawaban yang dihitung gagal: Mengisi tanggal atau hari yang tidak diucapkan.
- Catatan: Komitmen asli ini sempat ditolak validator karena ucapan lisan yang tidak rapi (sudah diperbaiki dengan snap_quote), dan pada run terakhir tidak muncul. Juga uji recall. Hasil cek audio pengguna (2026-10-06): audio 10:21 sampai 10:30 berbunyi "Okay, that's fine. Yeah, like I don't think this is super uber urgent. Like, the history is there, so I'll just manually pick those up once you do it." Transkrip salah dengar "pick" sebagai "put" dan menulis "That fine" tanpa "Okay,". Ini kesalahan transkripsi (ASR), bukan kesalahan agent; kutipan agent yang cocok dengan transkrip tetap lolos validator meski berbeda dari audio.

Konteks dari transkrip (tiap blok: segmen utama dengan satu segmen sebelum dan dua sesudah):

  - [10:21] Speaker 0: "Okay."
  - [10:23] Speaker 0: "That fine yeah like I don't think this is super uber urgent like that the history is there so I I I'll just manually put those up once you do it. Um," <== segmen utama
  - [10:34] Speaker 0: "so I I moved around the order in the agenda item because we already just talked about number four review process as oh no we didn't talk about this. So, I wanted to talk about this. Um, again I don't I think this discussion is way beyond plan."
  - [10:50] Speaker 0: "Um, but I wanted to bring it up with you Sean at least um, since you're here."

Verifikasi tenggat (kata waktu pada segmen utama dan dua segmen sesudahnya; keluaran mentah, perlu Anda nilai relevansinya):

- 10:23: tidak ada kata waktu

- Keputusan pengguna: [x] jawaban acuan sesuai  [ ] perlu diubah  [ ] skenario diganti
- Dicentang oleh Claude atas hasil pengecekan audio pengguna (2026-10-06). Poin yang diperiksa: kalimat tidak terucap persis seperti di transkrip ("put" vs "pick"); ini dicatat sebagai temuan transkripsi, dan jawaban acuan disesuaikan.

