from agent import reporting

SECTIONS = ("Ringkasan", "Keputusan", "Action Items", "Isu Terbuka")


def make_item(n, speaker="Speaker 0"):
    return {"no": n, "judul": f"Butir nomor {n} dengan judul yang cukup panjang untuk satu baris penuh",
            "kutipan": "this is a quote that is long enough to be a real quote from the transcript " * 5,
            "info": [{"label": "Penanggung jawab", "nilai": "Jason", "warn": False, "catatan": ""},
                     {"label": "Tenggat", "nilai": "tidak disebut", "warn": False, "catatan": ""}],
            "speaker": speaker, "waktu": "00:20"}


def make_doc(filler_lines):
    return {
        "judul": "Rapat uji", "dibuat": "2026-11-02 15:18 WIB", "rekap_id": "abc123", "sumber": "uji", "sumber_url": "",
        "durasi": "03:25", "jumlah_speaker": 3,
        "ringkasan_eksekutif": ["Baris ringkasan eksekutif. " * 6 for _ in range(filler_lines)],
        "sections": [{"judul": name, "kosong": "", "items": [make_item(1), make_item(2)]} for name in SECTIONS],
        "tasks": [], "statistik": [{"speaker": "Speaker 0", "waktu": "01:31", "proporsi": "66,2%", "giliran": "5", "kata": "217"}],
        "catatan_statistik": "Statistik dihitung kode.", "catatan_metode": "Kutipan dicocokkan kode.", "trace_id": "t1",
        "transkrip": [],
    }


def test_a_section_heading_is_never_left_alone_at_the_bottom_of_a_page(monkeypatch, tmp_path):
    base = reporting._make_pdf_class()
    cells = []

    class Spy(base):
        def cell(self, *a, **k):
            text = (a[2] if len(a) > 2 else k.get("text", "")).strip()
            if text in SECTIONS or text == "Penanggung jawab":
                cells.append((self.page_no(), text))
            return super().cell(*a, **k)

    monkeypatch.setattr(reporting, "_make_pdf_class", lambda: Spy)
    bands = 0
    for filler in range(0, 40):
        cells.clear()
        reporting._render_pdf(make_doc(filler), tmp_path / f"r{filler}.pdf")
        for i, (page, text) in enumerate(cells):
            if text in SECTIONS:
                first_item = next(c for c in cells[i + 1:] if c[1] == "Penanggung jawab")
                assert first_item[0] == page, (f"filler={filler}: '{text}' is on page {page} "
                                               f"but its first item starts on page {first_item[0]}")
                bands += 1
    assert bands == 4 * 40
