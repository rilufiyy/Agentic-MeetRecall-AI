# Catatan sesi evaluasi Tahap 4

Dibuat 2026-10-07. Dokumen ini mencatat sesi eksekusi, bukan penilaian jawaban. Jawaban agent belum dinilai terhadap kriteria lolos; yang tercatat hanya status run, tool yang dipanggil, token, dan latensi. Angka berasal dari eksekusi nyata (`eval_run/data/eval/sesi_2026-10-07-A.jsonl`, `eval_run/log_sesi_A.txt`).

## 1. Sesi A (2026-10-07, 07:15 sampai sekitar 07:30 UTC, 14:15 sampai 14:30 WIB)

Ruang lingkup yang dipilih pengguna: hanya skenario murah dari gelombang 1 (OS-01, OS-02, TN-01 sampai TN-03, W-02, L-04). Sisanya di sesi berikutnya.

| Skenario | Status run | Panggilan LLM | Token masuk | Token keluar | Total | Biaya (USD) | Detik | Tool dipanggil |
|---|---|---|---|---|---|---|---|---|
| OS-01 | rejected_scope | 0 | 0 | 0 | 0 | 0 | 0,3 | (tidak ada) |
| OS-02 | rejected_scope | 0 | 0 | 0 | 0 | 0 | 0,1 | (tidak ada) |
| TN-01 | completed | 3 | 8.194 | 1.191 | 9.385 | 0,00097 | 37,5 | ekstrak_poin_meeting |
| TN-02 | completed | 3 | 6.684 | 562 | 7.246 | 0,00067 | 4,2 | ekstrak_poin_meeting |
| TN-03 | completed | 1 | 2.465 | 53 | 2.518 | 0,00020 | 1,0 | (tidak ada) |
| W-02 | awaiting_approval, lalu ditolak (simulasi) | 3 | 6.685 | 384 | 7.069 | 0,00062 | 3,4 | ekstrak_poin_meeting, buat_task |
| L-04 | completed | 7 | 13.383 | 1.433 | 14.816 | 0,00143 | 58,5 | ekstrak_poin_meeting, ekspor_laporan |
| **Total** | | 17 | **37.411** | **3.623** | **41.034** | 0,00489 | | |

- **7 dari 7 run berjalan sampai selesai. Terhenti karena kuota: 0 dari 7.** Seluruhnya dihitung (`dihitung=True`).
- **W-02:** penolakan simulasi diverifikasi otomatis dari trace dan database: 8 dari 8 pemeriksaan lolos (status ditolak, kejadian tolak di trace, tanpa eksekusi tool, task, outbox, laporan, rekap, dan approval lain tidak berubah).
- **L-04:** agent memanggil `ekstrak_poin_meeting` sebelum `ekspor_laporan` (7 panggilan LLM). Ini sesuai temuan kode bahwa SRT butuh `rekap_id`. Pada meeting 10 segmen itu saja sudah 14,8k token.
- **TN-03** (ucapan terima kasih setelah laporan) memakai 1 panggilan LLM tanpa tool.
- **Data demo tetap identik** dengan snapshot acuan setelah sesi.
- **Sidik jari kode dan konfigurasi sama di semua 7 run:** kode `815dee68864de752` (41 berkas), konfigurasi `48956add792c0b16`; sidik jari setelah sesi juga sama. Itu bukti pembekuan selama sesi A.

### Estimasi vs aktual (ribuan token)

| Skenario | Estimasi | Aktual |
|---|---|---|
| OS-01, OS-02 | 0 | 0 |
| TN-01 | 5,8 | 9,4 |
| TN-02 | 5,8 | 7,2 |
| TN-03 | 5,8 | 2,5 |
| W-02 | 10,0 | 7,1 |
| L-04 | 7,5 | 14,8 |
| **Total** | **34,9** | **41,0** (selisih +17,6%) |

Estimasi meleset ke dua arah. Yang paling meleset: L-04 (dua kali lipat, karena ekstraksi `semua` di dalam alur SRT agent) dan TN-03 (jauh lebih kecil). Pengukuran tambahan dari job email dry_run (laporan PDF dan kirim, 14,9k) dipakai untuk menurunkan estimasi W-03 dan W-04.

## 2. Waktu reset kuota (koreksi klaim sebelumnya)

Klaim saya sebelumnya bahwa kuota harian "direset 07:00 WIB" **tidak terverifikasi dan salah**. Dokumentasi resmi (https://console.groq.com/docs/rate-limits) tidak menyebut jam reset harian maupun apakah jendelanya bergulir; yang disebut hanya bahwa batas berlaku per organisasi dan ada header `x-ratelimit-reset-requests`.

Pengukuran nyata (satu panggilan kecil, 93 token, 2026-10-07 07:24:12 UTC, setelah sesi A):

| Header | Nilai |
|---|---|
| x-ratelimit-limit-requests | 1000 |
| x-ratelimit-remaining-requests | 983 |
| x-ratelimit-reset-requests | 24m28,8s |
| x-ratelimit-limit-tokens (per menit) | 8000 |
| x-ratelimit-remaining-tokens | 7468 |
| x-ratelimit-reset-tokens | 3,99s |

Temuan: 17 request terpakai dibagi laju isi ulang (1000 per 86.400 detik) = 1.468,8 detik = 24m28,8s, **persis sama** dengan `reset-requests`. Jadi batas request harian terisi ulang **secara kontinu** (seperti ember yang terisi bertahap), bukan di-reset pada jam tetap.

Batas yang berlaku untuk token harian (TPD, 200.000) **tidak dilaporkan oleh header**. Kesimpulan bahwa TPD berperilaku sama adalah **dugaan** berdasarkan analogi, belum terbukti. Bila sama, laju isi ulangnya sekitar 2,31 token per detik (sekitar 8.333 token per jam).

Implikasi untuk sesi berikutnya:
- Tidak ada jam reset tetap untuk dikonfirmasi. Yang bisa dikonfirmasi sebelum sesi adalah header (`remaining-requests` mendekati 1000 menandakan ember request sudah penuh).
- Pemakaian eval hari ini (hari UTC 2026-10-07): 33.338 (3 run percobaan dan 1 job email) + 41.034 (sesi A) = **74.372 token**, belum termasuk pemakaian UI demo oleh pengguna. Bila TPD berperilaku seperti request, ember pulih penuh dalam sekitar 9 jam.
- Batas aman yang dipakai tetap sekitar 150.000 token per sesi.

## 3. Sisa kuota (perkiraan, dihitung ulang dari angka sesi A)

Sudah dijalankan: 7 skenario (sesi A). Sisa Prioritas 1: **40 skenario, 41 run, sekitar 311,4k token** (perkiraan; sebelumnya 358,8k untuk seluruhnya). Perubahan estimasi: W-01 7,5k, W-03 dan W-04 masing-masing 15k; sisanya tetap karena belum ada pengukuran baru.

| Gelombang | Isi (sisa) | Skenario | Run | Token (perk.) |
|---|---|---|---|---|
| 1 | L-01, L-02, L-03, W-01, W-03, W-04 | 6 | 6 | 89,5k |
| 2 | S-01 sampai S-03, P-01 sampai P-04, IA-01, AM-01, ES-02, INJ-01, INJ-02, IT-01 sampai IT-05 | 17 | 18 | 107,8k |
| 3 | DT-01 sampai DT-05, AM-02, KJ-01, KJ-02 | 8 | 8 | 43,6k |
| 4 | P-05, A-01 sampai A-03, K-01 sampai K-03, R-01, ES-01 | 9 | 9 | 70,5k |

Usulan pembagian (perkiraan; maksimal sekitar 150.000 token per sesi):

| Sesi | Isi | Run | Token (perk.) |
|---|---|---|---|
| B | gelombang 1 sisa, lalu S-01 sampai S-03, P-01 sampai P-04, IA-01 | 14 | 134,2k |
| C | AM-01, ES-02, INJ-01, INJ-02, IT-01 sampai IT-05 (IT-03 dua bentuk), lalu gelombang 3 | 18 | 106,7k |
| D | gelombang 4 (bergantung label) | 9 | 70,5k |
| E (setelah gelombang 1) | perbandingan workflow vs agent, 8 skenario | 8 | belum diukur |

Aturan sesi berikutnya (dari pengguna): tidak mengubah kode atau konfigurasi di antara sesi; bila run terhenti karena kuota, ditandai "terhenti_karena_kuota", tidak dihitung sebagai kegagalan agent, dan dijalankan ulang. Sebelum sesi B, bandingkan `eval_harness.py sidik-jari` dengan `eval_run/sidik_jari_sebelum_sesi_A.json` (harus sama).

## 4. Catatan untuk bagian metodologi artikel

Evaluasi dijalankan dalam beberapa sesi harian, bukan sekali jalan, karena batas token harian tingkat gratis (200.000 token per hari untuk `openai/gpt-oss-20b`) dan batas 8.000 token per menit. Dampak dan pengendaliannya:

- **Pemecahan:** sesi A (7 skenario murah, 41.034 token) dan sesi berikutnya (lihat tabel). Skenario dikelompokkan menurut jenis penilaian (trace dan database lebih dulu), bukan menurut kenyamanan.
- **Pengendalian antar sesi:** kode, skenario, dan konfigurasi dibekukan; setiap rekaman hasil membawa `sesi`, `kode_sha`, dan `konfigurasi_sha`, sehingga pembekuan bisa diperiksa dari data, bukan dari klaim.
- **Kegagalan penyedia dipisahkan dari kegagalan agent:** run yang terhenti karena batas kuota ditandai `terhenti_karena_kuota`, dikeluarkan dari metrik, lalu dijalankan ulang.
- **Ancaman terhadap validitas:** latensi dan kondisi penyedia dapat berbeda antar hari, sehingga perbandingan latensi lintas sesi tidak setara; jumlah token tidak terpengaruh. Hasil dilaporkan per sesi dan per kelompok penilaian, bukan digabung.
- **Efek isi ulang kuota:** batas penyedia terisi ulang secara kontinu (terukur untuk request, dugaan untuk token), jadi jarak waktu antar sesi memengaruhi kuota yang tersedia.
- **Persetujuan aksi tulis adalah simulasi** di data eval terpisah dengan email dry_run (lihat dokumen 07 bagian 8).
