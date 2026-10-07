# Hasil Evaluasi Retrieval (k = 3)

Jumlah pertanyaan: 26 (22 dapat dijawab, 4 di luar cakupan).
Konfigurasi: `{"fusion": "rrf", "alpha": 0.5, "rrf_k": 60, "candidate_k": 20, "rerank": false, "min_score": 0.4}`

Metrik peringkat dihitung tanpa ambang penolakan; ambang (min_score) dinilai terpisah lewat akurasi penolakan (pertanyaan di luar cakupan) dan salah tolak (pertanyaan yang seharusnya bisa dijawab).

| Mode | Hit@3 | Recall@3 | MRR@3 | Akurasi penolakan | Salah tolak | Latensi rata-rata (ms) |
|---|---|---|---|---|---|---|
| Full-text (BM25) | 0.636 | 0.591 | 0.515 | 1.000 | 0.455 | 0.180 |
| Vector (FAISS) | 0.636 | 0.545 | 0.530 | 1.000 | 0.000 | 29.390 |
| Hybrid | 0.818 | 0.705 | 0.614 | 1.000 | 0.000 | 27.250 |

## Hit@3 per kategori pertanyaan

| Kategori | n | Full-text (BM25) | Vector (FAISS) | Hybrid |
|---|---|---|---|---|
| campuran | 6 | 0.667 | 0.500 | 0.833 |
| kata_kunci | 6 | 1.000 | 0.667 | 0.833 |
| lintas_bahasa | 2 | 0.000 | 0.500 | 0.500 |
| parafrase | 8 | 0.500 | 0.750 | 0.875 |

## Pertanyaan yang gagal (relevan tidak muncul di top-k)

- [Full-text (BM25)] q08 (parafrase): Kenapa pelanggan menerima surel duplikat?  relevan=[18, 19] diambil=[]
- [Full-text (BM25)] q10 (parafrase): Mengapa tagihan infrastruktur membengkak?  relevan=[43, 44] diambil=[]
- [Full-text (BM25)] q13 (parafrase): Berapa banyak skenario pengujian yang tidak lolos?  relevan=[16] diambil=[40]
- [Full-text (BM25)] q14 (parafrase): Apa usulan tampilan agar tabel dengan banyak kolom tetap terbaca?  relevan=[12] diambil=[34, 35, 11]
- [Full-text (BM25)] q17 (campuran): Bagaimana cara Dimas mencegah notifikasi ganda MR-241?  relevan=[19] diambil=[32, 17, 51]
- [Full-text (BM25)] q19 (campuran): Berapa jumlah sampel mitra di analisis retensi?  relevan=[27] diambil=[24, 25, 38]
- [Full-text (BM25)] q21 (lintas_bahasa): Who will fix the duplicate email notification bug?  relevan=[19, 51] diambil=[20, 17]
- [Full-text (BM25)] q22 (lintas_bahasa): When is version 2.4.1 going to be released?  relevan=[31] diambil=[]
- [Vector (FAISS)] q01 (kata_kunci): Apa isu yang dicatat di tiket MR-241?  relevan=[17] diambil=[3, 42, 52]
- [Vector (FAISS)] q02 (kata_kunci): Berapa target p95 untuk MR-218?  relevan=[4, 5] diambil=[3, 42, 51]
- [Vector (FAISS)] q07 (parafrase): Siapa yang bertanggung jawab membereskan halaman masuk yang lamban sampai naik ke production?  relevan=[8] diambil=[7, 3, 14]
- [Vector (FAISS)] q10 (parafrase): Mengapa tagihan infrastruktur membengkak?  relevan=[43, 44] diambil=[36, 37, 38]
- [Vector (FAISS)] q17 (campuran): Bagaimana cara Dimas mencegah notifikasi ganda MR-241?  relevan=[19] diambil=[17, 42, 3]
- [Vector (FAISS)] q18 (campuran): Apa dampaknya kalau migrasi PayLink terlambat?  relevan=[38] diambil=[41, 52, 39]
- [Vector (FAISS)] q19 (campuran): Berapa jumlah sampel mitra di analisis retensi?  relevan=[27] diambil=[25, 39, 6]
- [Vector (FAISS)] q22 (lintas_bahasa): When is version 2.4.1 going to be released?  relevan=[31] diambil=[28, 8, 33]
- [Hybrid] q01 (kata_kunci): Apa isu yang dicatat di tiket MR-241?  relevan=[17] diambil=[3, 32, 52]
- [Hybrid] q10 (parafrase): Mengapa tagihan infrastruktur membengkak?  relevan=[43, 44] diambil=[36, 37, 38]
- [Hybrid] q17 (campuran): Bagaimana cara Dimas mencegah notifikasi ganda MR-241?  relevan=[19] diambil=[17, 32, 42]
- [Hybrid] q22 (lintas_bahasa): When is version 2.4.1 going to be released?  relevan=[31] diambil=[28, 8, 33]
