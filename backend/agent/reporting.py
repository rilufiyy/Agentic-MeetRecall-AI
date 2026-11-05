"""
Report export built by code from a stored rekap. No LLM call here; the LLM
only picks the rekap_id and the format.

One document model (a list of blocks) is rendered to PDF, DOCX or Markdown,
so the three formats always carry the same content. SRT is the transcript
itself as subtitles, built from the segment timestamps.

File names follow the title of the uploaded video (or the source title in
data/sources.json), for example "Business Meeting - Ginger Cola Launch - Rekap.pdf".

fpdf2 Unicode fonts: https://py-pdf.github.io/fpdf2/Unicode.html
fpdf2 tables:        https://py-pdf.github.io/fpdf2/Tables.html
python-docx:         https://python-docx.readthedocs.io/en/latest/
Email message API:   https://docs.python.org/3/library/email.examples.html
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agent import config

SECTIONS = [
    ("ringkasan", "Ringkasan"),
    ("keputusan", "Keputusan"),
    ("action_items", "Action items"),
    ("isu_terbuka", "Isu terbuka"),
]
FORMATS = {
    # format: (file suffix, label in the file name, MIME type)
    "pdf": (".pdf", "Rekap", "application/pdf"),
    "docx": (".docx", "Rekap", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "md": (".md", "Rekap", "text/markdown"),
    "srt": (".srt", "Transkrip", "application/x-subrip"),
}
_STATUS_PJ = {"jelas": "jelas", "ambigu": "ambigu, perlu konfirmasi"}
_STATUS_TENGGAT = {"jelas": "tanggal jelas", "relatif": "relatif", "tidak_disebut": "tidak disebut",
                   "tidak_terverifikasi": "tidak terverifikasi"}


class ExportError(Exception):
    """The requested export cannot be built from the available data."""


# Source and file names

def load_source(meeting_id: str) -> Dict:
    """Title and URL of the source video from data/sources.json, or an explicit 'belum tercatat'."""
    try:
        sources = json.loads(Path(config.SOURCES_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sources = {}
    src = sources.get(meeting_id) or {}
    return {"judul": src.get("judul") or "", "url": src.get("url") or "",
            "catatan": src.get("catatan") or ("" if src.get("url") else "URL sumber belum tercatat")}


def display_title(meeting) -> str:
    """Source title when registered, else the uploaded file name without its extension."""
    title = load_source(meeting.meeting_id)["judul"]
    if title:
        return title
    name = meeting.filename or "meeting"
    return Path(name).stem if Path(name).suffix.lower() in config.MEDIA_SUFFIXES else name


_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_filename(title: str, max_len: int = 80) -> str:
    """File-system safe on Windows and Linux; keeps spaces, letters and dashes."""
    clean = " ".join(_UNSAFE.sub(" ", title).split()).strip(" .")
    return (clean[:max_len].rstrip(" .") or "meeting")


def export_dir(rekap_id: str) -> Path:
    if not rekap_id.isalnum():
        raise ValueError("rekap_id tidak valid")
    return Path(config.REPORT_DIR) / rekap_id


def export_path(rekap_id: str, meeting, fmt: str) -> Path:
    suffix, label, _ = FORMATS[fmt]
    return export_dir(rekap_id) / f"{safe_filename(display_title(meeting))} - {label}{suffix}"


def list_exports(rekap_id: str) -> List[Dict]:
    folder = export_dir(rekap_id)
    if not folder.exists():
        return []
    by_suffix = {v[0]: k for k, v in FORMATS.items()}
    return [{"nama_file": p.name, "format": by_suffix.get(p.suffix, p.suffix.lstrip(".")),
             "ukuran_kb": round(p.stat().st_size / 1024, 1),
             "dibuat": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
            for p in sorted(folder.iterdir()) if p.is_file() and p.suffix in by_suffix]


def section_status(rekap: Dict, jenis: str) -> str:
    """'belum_dianalisis', 'tidak_ditemukan' or 'ok'."""
    section = rekap.get("bagian", {}).get(jenis)
    if section is None:
        return "belum_dianalisis"
    return "ok" if section.get("items") else "tidak_ditemukan"


# Tritronik palette, read from https://tritronik.com/ (theme-color and computed colours).
BLUE = (78, 114, 194)        # #4E72C2 brand blue: title, links, timestamps
NAVY = (52, 69, 116)         # #344574 dominant dark blue: section bands, headings
MID = (95, 138, 207)         # #5F8ACF quote rule
PALE = (245, 250, 254)       # #F5FAFE table header background
INK = (33, 43, 70)           # body text, dark navy
GRAY = (94, 99, 110)         # #5E636E secondary text
RULE = (194, 201, 214)       # #C2C9D6 thin lines
WARN = (180, 83, 9)
WHITE = (255, 255, 255)
BAND_TEXT = {"ringkasan": "Ringkasan", "keputusan": "Keputusan", "action_items": "Action Items",
             "isu_terbuka": "Isu Terbuka"}


def _seconds(mulai: str) -> int:
    """'28:21' or '1:02:03' -> seconds, for ordering items by when they were said."""
    try:
        parts = [int(p) for p in (mulai or "0").split(":")]
    except ValueError:
        return 0
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def _mmss(seconds: float) -> str:
    s = int(round(seconds or 0))
    return f"{s // 60:02d}:{s % 60:02d}"


def _count_text(rekap: Dict, jenis: str, unit: str) -> str:
    status = section_status(rekap, jenis)
    if status == "ok":
        return f"{len(rekap['bagian'][jenis]['items'])} {unit}"
    return "belum dianalisis" if status == "belum_dianalisis" else "tidak ditemukan"


def _executive_summary(rekap: Dict, stats: Dict) -> List[str]:
    """Plain sentences built from counts; no LLM."""
    first = (f"Rekap ini disusun dari transkrip meeting berdurasi {stats['durasi']} dengan "
             f"{stats['jumlah_speaker']} pembicara. Ringkasan: {_count_text(rekap, 'ringkasan', 'poin')}. "
             f"Keputusan: {_count_text(rekap, 'keputusan', 'keputusan')}. "
             f"Action items: {_count_text(rekap, 'action_items', 'item')}. "
             f"Isu terbuka: {_count_text(rekap, 'isu_terbuka', 'isu')}.")
    paragraphs = [first]
    note = confirmation_note(rekap)
    if note:
        paragraphs.append(note)
    return paragraphs


def confirmation_note(rekap: Dict) -> str:
    """'Perlu konfirmasi: ...' sentence for action items with unclear owner or no deadline; '' when none. Shared by PDF/DOCX and email."""
    items = (rekap.get("bagian", {}).get("action_items") or {}).get("items", [])
    unclear = [i["id"] for i in items if i.get("status_penanggung_jawab") != "jelas"]
    no_deadline = [i["id"] for i in items if i.get("status_tenggat") in ("tidak_disebut", "tidak_terverifikasi")]
    notes = []
    if unclear:
        notes.append(f"penanggung jawab belum jelas pada {', '.join(unclear)}")
    if no_deadline:
        notes.append(f"tenggat tidak disebut pada {', '.join(no_deadline)}")
    return "Perlu konfirmasi: " + "; ".join(notes) + "." if notes else ""


def _item_model(jenis: str, item: Dict) -> Dict:
    info: List[Dict] = []
    if jenis == "action_items":
        owner_ok = item.get("status_penanggung_jawab") == "jelas"
        info.append({"label": "Penanggung jawab", "nilai": item.get("penanggung_jawab") or "belum jelas",
                     "catatan": "" if owner_ok else "perlu konfirmasi", "warn": not owner_ok})
        deadline = item.get("tenggat") or "tidak disebut"
        status = item.get("status_tenggat")
        note = {"relatif": "relatif, tanpa tanggal", "tidak_disebut": "", "tidak_terverifikasi": "tidak terverifikasi"}.get(status, "")
        info.append({"label": "Tenggat", "nilai": deadline, "catatan": note, "warn": status == "tidak_terverifikasi"})
    return {"no": item["id"], "judul": item.get("isi") or "(tanpa isi)", "info": info,
            "kutipan": item["kutipan"], "waktu": item["mulai"], "speaker": item.get("speaker_kutipan") or ""}


TURN_MAX_SECONDS = 45


def _transcript_turns(meeting) -> List[Dict]:
    """Segments merged into readable turns: same speaker in a row, at most TURN_MAX_SECONDS long."""
    turns: List[Dict] = []
    for seg in meeting.segments:
        text = seg.text.strip()
        if not text:
            continue
        last = turns[-1] if turns else None
        if last and last["speaker"] == seg.speaker and seg.start_time - last["_start"] < TURN_MAX_SECONDS:
            last["teks"] += " " + text
        else:
            turns.append({"waktu": _mmss(seg.start_time), "speaker": seg.speaker, "teks": text,
                          "_start": seg.start_time})
    return turns


def build_document(rekap: Dict, meeting, stats: Dict, tasks: Optional[List[Dict]] = None,
                   trace_id: str = "", include_transcript: bool = True) -> Dict:
    source = load_source(rekap["meeting_id"])
    sections = []
    for jenis, _ in SECTIONS:
        status = section_status(rekap, jenis)
        entry: Dict = {"kunci": jenis, "judul": BAND_TEXT[jenis], "items": [], "kosong": ""}
        if status == "belum_dianalisis":
            entry["kosong"] = "Belum dianalisis untuk rekap ini."
        elif status == "tidak_ditemukan":
            entry["kosong"] = "Tidak ditemukan dalam transkrip."
        else:
            ordered = sorted(rekap["bagian"][jenis]["items"], key=lambda i: _seconds(i["mulai"]))
            entry["items"] = [_item_model(jenis, i) for i in ordered]
            if jenis != "action_items":
                # Readable 1..n in time order. Action items keep A1, A2: tasks refer to those ids.
                for n, model in enumerate(entry["items"], 1):
                    model["no"] = str(n)
        sections.append(entry)
    speakers = [{"speaker": s["speaker"], "waktu": _mmss(s["detik_bicara"]),
                 "proporsi": f"{s['proporsi_bicara'] * 100:.1f}".replace(".", ",") + "%",
                 "giliran": str(s["giliran"]), "kata": str(s["jumlah_kata"])} for s in stats["per_speaker"]]
    return {
        "judul": display_title(meeting),
        "sumber": source["url"] or source["catatan"],
        "sumber_url": source["url"],
        "durasi": stats["durasi"],
        "jumlah_speaker": stats["jumlah_speaker"],
        "dibuat": config.local_time(datetime.now(timezone.utc)),
        "transkrip": _transcript_turns(meeting) if include_transcript else [],
        "rekap_id": rekap["rekap_id"],
        "trace_id": trace_id or "-",
        "ringkasan_eksekutif": _executive_summary(rekap, stats),
        "sections": sections,
        "tasks": [{"task": t["task_id"], "item": t["item_id"], "tugas": t["tugas"],
                   "pj": t["penanggung_jawab"] or "-", "tenggat": t["tenggat"] or "-"} for t in (tasks or [])],
        "statistik": speakers,
        "catatan_statistik": ("Statistik dihitung kode dari transkrip. Proporsi waktu per topik: "
                              + stats["proporsi_topik"] + "."),
        "catatan_metode": ("Kutipan dicocokkan dengan transkrip oleh kode, dan timestamp berasal dari data "
                           "transkrip, bukan dari model."),
    }


# PDF

def _font_files() -> Optional[Dict[str, Path]]:
    """Regular, bold, italic, bold italic of the first installed font family; None -> core fonts."""
    candidates = [
        (Path(config.PDF_FONT_DIR), ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
                                     "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu"), ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
                                                    "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf")),
    ]
    for folder, names in candidates:
        paths = [folder / n for n in names]
        if all(p.exists() for p in paths):
            return dict(zip(("", "B", "I", "BI"), paths))
    return None


def _make_pdf_class():
    from fpdf import FPDF

    class ReportPDF(FPDF):
        family = "helvetica"
        running_title = ""
        footer_left = ""

        def header(self):
            if self.page_no() == 1:
                return
            self.set_font(self.family, "", 8)
            self.set_text_color(*GRAY)
            self.set_y(8)
            self.cell(0, 5, self.running_title)
            self.set_draw_color(*RULE)
            self.line(self.l_margin, 14, self.w - self.r_margin, 14)
            self.set_y(18)

        def footer(self):
            self.set_y(-14)
            self.set_draw_color(*RULE)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.set_font(self.family, "", 7.5)
            self.set_text_color(*GRAY)
            self.set_y(-12)
            half = (self.w - self.l_margin - self.r_margin) / 2
            self.cell(half, 5, self.footer_left)
            self.cell(half, 5, f"Halaman {self.page_no()} dari {{nb}}", align="R")

    return ReportPDF


def _render_pdf(doc: Dict, path: Path) -> Dict:
    from fpdf.enums import TableBordersLayout, TableCellFillMode, XPos, YPos
    from fpdf.fonts import FontFace

    pdf = _make_pdf_class()(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.alias_nb_pages()
    fonts = _font_files()
    latin1 = fonts is None
    if fonts:
        for style, file in fonts.items():
            pdf.add_font("report", style, str(file))
        pdf.family = "report"
    pdf.running_title = f"Rekap Meeting: {doc['judul']}"[:110]
    pdf.footer_left = f"MeetRecall AI | dibuat {doc['dibuat']} | rekap {doc['rekap_id']}"
    fam = pdf.family
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.add_page()

    def t(text: str) -> str:
        # Models sometimes write a non-breaking hyphen (U+2011); the bold and italic report fonts have no glyph for it,
        # so "MR-230" and "11-13" lost the hyphen in the PDF. It is replaced by a plain hyphen at render time only.
        text = text.replace("‐", "-").replace("‑", "-")
        return text.encode("latin-1", "replace").decode("latin-1") if latin1 else text

    def write(text, size=10, style="", color=INK, h=None, width=0, align="L", gap=0.0):
        pdf.set_font(fam, style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(width, h or size * 0.5, t(text), align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if gap:
            pdf.ln(gap)

    def lines_needed(text, size, style="", width=0):
        pdf.set_font(fam, style, size)
        return len(pdf.multi_cell(width or usable, size * 0.5, t(text), dry_run=True, output="LINES"))

    # Title block
    write("Rekap Meeting", 24, "B", BLUE, h=11, gap=1)
    write(doc["judul"], 12.5, "", GRAY, h=6.5, gap=1)
    write(f"Dibuat {doc['dibuat']}", 8.5, "", GRAY, h=5, gap=2)
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    for label, value, link in (("Sumber", doc["sumber"], doc["sumber_url"]),
                               ("Durasi", doc["durasi"], ""),
                               ("Pembicara", f"{doc['jumlah_speaker']} orang", "")):
        pdf.set_font(fam, "", 9)
        pdf.set_text_color(*GRAY)
        pdf.cell(26, 5.5, label)
        pdf.set_font(fam, "", 9.5)
        pdf.set_text_color(*(BLUE if link else INK))
        pdf.cell(0, 5.5, t(value), link=link or None, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    # Executive summary
    write("Ringkasan Eksekutif", 12, "B", INK, h=6, gap=1.5)
    for paragraph in doc["ringkasan_eksekutif"]:
        write(paragraph, 10.5, "", INK, h=5.6, gap=2)
    pdf.ln(3)

    def item_height(it: Dict) -> float:
        title = f"{it['no']}. {it['judul']}"
        quote = f"\"{it['kutipan']}\""
        return (lines_needed(title, 10, "B") * 5 + len(it["info"]) * 4.6 +
                lines_needed(quote, 9, "I", usable - 6) * 4.6 + 10)

    def band(title: str, need: float = 30) -> None:
        # `need` is the room the band and what must follow it require; a band is never left alone at a page bottom.
        if pdf.will_page_break(need):
            pdf.add_page()
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(*WHITE)
        pdf.set_font(fam, "B", 10.5)
        pdf.cell(0, 7.5, t(f"  {title}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

    def item(it: Dict) -> None:
        title = f"{it['no']}. {it['judul']}"
        quote = f"\"{it['kutipan']}\""
        if pdf.will_page_break(item_height(it)):
            pdf.add_page()
        write(title, 10, "B", INK, h=5, gap=0.8)
        for info in it["info"]:
            pdf.set_font(fam, "", 8.5)
            pdf.set_text_color(*GRAY)
            pdf.cell(32, 4.6, info["label"])
            pdf.set_font(fam, "B" if info["warn"] else "", 8.5)
            pdf.set_text_color(*(WARN if info["warn"] else INK))
            text = info["nilai"] + (f"  ({info['catatan']})" if info["catatan"] else "")
            pdf.cell(0, 4.6, t(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)
        top = pdf.get_y()
        pdf.set_x(pdf.l_margin + 5)
        write(quote, 9, "I", (71, 85, 105), h=4.6, width=usable - 5)
        pdf.set_x(pdf.l_margin + 5)
        write(f"{it['speaker'] or 'Pembicara'}, {it['waktu']}", 8, "", GRAY, h=4.4, width=usable - 5)
        pdf.set_draw_color(*MID)
        pdf.set_line_width(0.5)
        pdf.line(pdf.l_margin + 1.5, top, pdf.l_margin + 1.5, pdf.get_y() - 0.5)
        pdf.set_line_width(0.2)
        pdf.ln(4)

    for section in doc["sections"]:
        # Band (about 11 mm) plus the first item, so the heading and its first item always share a page.
        band(section["judul"], need=30 if section["kosong"] else 11 + item_height(section["items"][0]))
        if section["kosong"]:
            write(section["kosong"], 9.5, "", GRAY, h=5, gap=5)
            continue
        for it in section["items"]:
            item(it)
        pdf.ln(2)

    pdf.set_text_color(*INK)
    pdf.set_fill_color(*WHITE)      # the band's blue fill must not carry into the table cells
    if doc["tasks"]:
        band("Task yang Dibuat")
        pdf.set_text_color(*INK)
        pdf.set_fill_color(*WHITE)
        with pdf.table(col_widths=(10, 8, 52, 18, 12), text_align=("LEFT",) * 5, line_height=5,
                       borders_layout=TableBordersLayout.HORIZONTAL_LINES,
                       cell_fill_mode=TableCellFillMode.NONE, headings_style=FontFace(emphasis="BOLD", color=INK, fill_color=PALE)) as table:
            pdf.set_font(fam, "", 8.5)
            head = table.row()
            for h in ("Task", "Item", "Tugas", "Penanggung jawab", "Tenggat"):
                head.cell(h)
            for task in doc["tasks"]:
                row = table.row()
                for key in ("task", "item", "tugas", "pj", "tenggat"):
                    row.cell(t(str(task[key])))
        pdf.ln(5)

    band("Statistik Pembicara")
    pdf.set_text_color(*INK)
    pdf.set_fill_color(*WHITE)
    with pdf.table(col_widths=(34, 22, 18, 14, 14), text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
                   line_height=5.5, borders_layout=TableBordersLayout.HORIZONTAL_LINES,
                   cell_fill_mode=TableCellFillMode.NONE, headings_style=FontFace(emphasis="BOLD", color=INK, fill_color=PALE)) as table:
        pdf.set_font(fam, "", 9)
        head = table.row()
        for h in ("Pembicara", "Waktu bicara", "Proporsi", "Giliran", "Kata"):
            head.cell(h)
        for s in doc["statistik"]:
            row = table.row()
            for key in ("speaker", "waktu", "proporsi", "giliran", "kata"):
                row.cell(t(s[key]))
    pdf.ln(2)
    write(doc["catatan_statistik"], 8, "", GRAY, h=4.2, gap=4)
    write(doc["catatan_metode"] + f" trace_id: {doc['trace_id']}", 8, "", GRAY, h=4.2)
    if doc["transkrip"]:
        pdf.ln(6)
        band("Transkrip")
        for turn in doc["transkrip"]:
            body_lines = lines_needed(turn["teks"], 9.5, "", usable)
            if pdf.will_page_break(5 + min(body_lines, 2) * 4.8):
                pdf.add_page()
            pdf.set_font(fam, "B", 9)
            pdf.set_text_color(*BLUE)
            pdf.cell(13, 4.8, turn["waktu"])
            pdf.set_text_color(*INK)
            pdf.cell(0, 4.8, t(turn["speaker"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            write(turn["teks"], 9.5, "", INK, h=4.8, gap=2.6)
    pdf.output(str(path))
    return {"halaman": pdf.page_no()}


# DOCX: same page, fonts, colours and structure as the PDF, so editing in Word and exporting to PDF
# from Word gives the same look. Real Word styles (Heading 1/2) keep the navigation pane useful.

def _hex(rgb) -> str:
    return "%02X%02X%02X" % tuple(rgb)


# Word rejects some files whose child elements are out of the order the OOXML schema prescribes
# (ECMA-376 CT_PPr, CT_TblPr), so extra elements are inserted at their proper place, not appended.
_PPR_ORDER = ("pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd "
              "tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi "
              "adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc "
              "textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange").split()
_TBLPR_ORDER = ("tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc "
                "tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook").split()
_PBDR_ORDER = "top left bottom right between bar".split()


def _insert_ordered(parent, child, order) -> None:
    from docx.oxml.ns import qn
    rank = {qn(f"w:{name}"): i for i, name in enumerate(order)}
    mine = rank[child.tag]
    for existing in list(parent):
        if rank.get(existing.tag, -1) > mine:
            existing.addprevious(child)
            return
    parent.append(child)


def _render_docx(doc: Dict, path: Path) -> Dict:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    FONT = "Arial"
    CONTENT_MM = 174            # 210 mm page minus 2 x 18 mm margins, as in the PDF

    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)          # A4 (python-docx defaults to Letter)
    sec.left_margin = sec.right_margin = Mm(18)
    sec.top_margin, sec.bottom_margin = Mm(18), Mm(18)
    sec.header_distance, sec.footer_distance = Mm(8), Mm(8)
    sec.different_first_page_header_footer = True                # running header from page 2, like the PDF

    def set_font(style, size, bold=None, color=INK):
        style.font.name = FONT
        style.font.size = Pt(size)
        if bold is not None:
            style.font.bold = bold
        style.font.color.rgb = RGBColor(*color)
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            fonts.set(qn(attr), FONT)

    set_font(d.styles["Normal"], 10)
    d.styles["Normal"].paragraph_format.space_after = Pt(0)
    d.styles["Normal"].paragraph_format.line_spacing = 1.15
    set_font(d.styles["Heading 1"], 24, True, BLUE)
    set_font(d.styles["Heading 2"], 10.5, True, WHITE)
    for name in ("Heading 1", "Heading 2"):
        style = d.styles[name]
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(0)

    def shade(par, rgb):
        ppr = par._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), _hex(rgb))
        _insert_ordered(ppr, shd, _PPR_ORDER)

    def border(par, side, rgb, size=4, space=1):
        ppr = par._p.get_or_add_pPr()
        bdr = ppr.find(qn("w:pBdr"))
        if bdr is None:
            bdr = OxmlElement("w:pBdr")
            _insert_ordered(ppr, bdr, _PPR_ORDER)
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), str(size))
        edge.set(qn("w:space"), str(space))
        edge.set(qn("w:color"), _hex(rgb))
        _insert_ordered(bdr, edge, _PBDR_ORDER)

    def run(par, text, size=10, bold=False, italic=False, color=INK):
        r = par.add_run(text)
        r.font.name = FONT
        r.font.size = Pt(size)
        r.bold, r.italic = bold, italic
        r.font.color.rgb = RGBColor(*color)
        return r

    def para(text="", size=10, bold=False, italic=False, color=INK, before=0, after=4, indent_mm=0.0,
             keep_next=False, style=None):
        p = d.add_paragraph(style=style)
        if text:
            run(p, text, size, bold, italic, color)
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        if indent_mm:
            pf.left_indent = Mm(indent_mm)
        pf.keep_with_next = keep_next
        return p

    def field(par, code, size=7.5, color=GRAY):
        """Word field (PAGE, NUMPAGES): the number is filled in by Word when the file is opened or printed."""
        for kind, text in (("begin", None), (None, code), ("separate", None), (None, "1"), ("end", None)):
            r = par.add_run()
            r.font.size = Pt(size)
            r.font.color.rgb = RGBColor(*color)
            if kind:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), kind)
                r._r.append(el)
            elif text == code:
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = f" {code} "
                r._r.append(el)
            else:
                r.text = text

    def hyperlink(par, url, text, size=9.5):
        rid = par.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                                 is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), rid)
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        for tag, val in (("w:color", _hex(BLUE)), ("w:sz", str(int(size * 2)))):
            el = OxmlElement(tag)
            el.set(qn("w:val"), val)
            rpr.append(el)
        r.append(rpr)
        t = OxmlElement("w:t")
        t.text = text
        r.append(t)
        link.append(r)
        par._p.append(link)

    # Header (pages 2+) and footer (all pages)
    head = sec.header.paragraphs[0]
    run(head, f"Rekap Meeting: {doc['judul']}"[:110], 8, color=GRAY)
    border(head, "bottom", RULE, 4, 4)
    for footer in (sec.footer, sec.first_page_footer):
        f = footer.paragraphs[0]
        f.paragraph_format.tab_stops.add_tab_stop(Mm(CONTENT_MM), WD_TAB_ALIGNMENT.RIGHT)
        border(f, "top", RULE, 4, 4)
        run(f, f"MeetRecall AI | dibuat {doc['dibuat']} | rekap {doc['rekap_id']}\tHalaman ", 7.5, color=GRAY)
        field(f, "PAGE")
        run(f, " dari ", 7.5, color=GRAY)
        field(f, "NUMPAGES")

    # Title block
    d.add_paragraph("Rekap Meeting", style="Heading 1").paragraph_format.space_after = Pt(2)
    para(doc["judul"], 12.5, color=GRAY, after=2)
    para(f"Dibuat {doc['dibuat']}", 8.5, color=GRAY, after=4)
    rule = para(after=6)
    border(rule, "bottom", RULE, 4, 1)
    for label, value, link in (("Sumber", doc["sumber"], doc["sumber_url"]), ("Durasi", doc["durasi"], ""),
                               ("Pembicara", f"{doc['jumlah_speaker']} orang", "")):
        p = para(after=2)
        p.paragraph_format.tab_stops.add_tab_stop(Mm(26))
        run(p, label + "\t", 9, color=GRAY)
        if link:
            hyperlink(p, link, value)
        else:
            run(p, value, 9.5)
    rule = para(after=8)
    border(rule, "bottom", RULE, 4, 1)

    para("Ringkasan Eksekutif", 12, bold=True, after=4, keep_next=True)
    for paragraph in doc["ringkasan_eksekutif"]:
        para(paragraph, 10.5, after=5)

    def band(title):
        p = d.add_paragraph(style="Heading 2")
        run(p, f"  {title}", 10.5, bold=True, color=WHITE)
        shade(p, NAVY)
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(8)
        return p

    for section in doc["sections"]:
        band(section["judul"])
        if section["kosong"]:
            para(section["kosong"], 9.5, color=GRAY, after=8)
        for it in section["items"]:
            para(f"{it['no']}. {it['judul']}", 10, bold=True, after=2, keep_next=True)
            for info in it["info"]:
                p = para(after=1, keep_next=True)
                p.paragraph_format.tab_stops.add_tab_stop(Mm(32))
                run(p, info["label"] + "\t", 8.5, color=GRAY)
                text = info["nilai"] + (f"  ({info['catatan']})" if info["catatan"] else "")
                run(p, text, 8.5, bold=info["warn"], color=WARN if info["warn"] else INK)
            quote = para(f"\"{it['kutipan']}\"", 9, italic=True, color=(71, 85, 105), before=3, after=0,
                         indent_mm=5, keep_next=True)
            border(quote, "left", MID, 12, 6)
            cap = para(f"{it['speaker'] or 'Pembicara'}, {it['waktu']}", 8, color=GRAY, after=10, indent_mm=5)
            border(cap, "left", MID, 12, 6)

    def table(headers, rows, widths_mm, right_cols=()):
        t = d.add_table(rows=1, cols=len(headers))
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        t.autofit = False
        tblpr = t._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "bottom", "insideH"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), _hex(MID))
            borders.append(el)
        _insert_ordered(tblpr, borders, _TBLPR_ORDER)

        def fill_row(row, values, header=False):
            for i, (cell, value) in enumerate(zip(row.cells, values)):
                cell.width = Mm(widths_mm[i])
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(2)
                if i in right_cols:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                run(p, str(value), 9, bold=header)
                if header:
                    tcpr = cell._tc.get_or_add_tcPr()
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:color"), "auto")
                    shd.set(qn("w:fill"), _hex(PALE))
                    tcpr.append(shd)

        fill_row(t.rows[0], headers, header=True)
        for values in rows:
            fill_row(t.add_row(), values)
        return t

    if doc["tasks"]:
        band("Task yang Dibuat")
        table(("Task", "Item", "Tugas", "Penanggung jawab", "Tenggat"),
              [(x["task"], x["item"], x["tugas"], x["pj"], x["tenggat"]) for x in doc["tasks"]],
              (17, 14, 90, 31, 22))
        para(after=6)

    band("Statistik Pembicara")
    table(("Pembicara", "Waktu bicara", "Proporsi", "Giliran", "Kata"),
          [(s["speaker"], s["waktu"], s["proporsi"], s["giliran"], s["kata"]) for s in doc["statistik"]],
          (58, 38, 30, 24, 24), right_cols=(1, 2, 3, 4))
    para(doc["catatan_statistik"], 8, color=GRAY, before=6, after=4)
    para(doc["catatan_metode"] + f" trace_id: {doc['trace_id']}", 8, color=GRAY, after=4)

    if doc["transkrip"]:
        band("Transkrip")
        for turn in doc["transkrip"]:
            head_p = para(after=0, keep_next=True)
            run(head_p, turn["waktu"] + "  ", 9, bold=True, color=BLUE)
            run(head_p, turn["speaker"], 9, bold=True)
            para(turn["teks"], 9.5, after=7)
    d.save(str(path))
    return {}


# Markdown

def _render_md(doc: Dict, path: Path) -> Dict:
    out: List[str] = [f"# Rekap Meeting: {doc['judul']}", "",
                      f"Dibuat {doc['dibuat']}", "",
                      f"- Sumber: {doc['sumber']}", f"- Durasi: {doc['durasi']}",
                      f"- Pembicara: {doc['jumlah_speaker']} orang", "",
                      "## Ringkasan Eksekutif", ""]
    for paragraph in doc["ringkasan_eksekutif"]:
        out += [paragraph, ""]
    for section in doc["sections"]:
        out += [f"## {section['judul']}", ""]
        if section["kosong"]:
            out += [section["kosong"], ""]
        for it in section["items"]:
            out.append(f"**{it['no']}. {it['judul']}**")
            out.append("")
            for info in it["info"]:
                out.append(f"- {info['label']}: {info['nilai']}" + (f" ({info['catatan']})" if info["catatan"] else ""))
            out += [f"- Kutipan ({it['speaker'] or 'Pembicara'}, {it['waktu']}): \"{it['kutipan']}\"", ""]
    if doc["tasks"]:
        out += ["## Task yang Dibuat", "", "| Task | Item | Tugas | Penanggung jawab | Tenggat |", "|---|---|---|---|---|"]
        out += [f"| {x['task']} | {x['item']} | {x['tugas']} | {x['pj']} | {x['tenggat']} |" for x in doc["tasks"]]
        out.append("")
    out += ["## Statistik Pembicara", "", "| Pembicara | Waktu bicara | Proporsi | Giliran | Kata |",
            "|---|---:|---:|---:|---:|"]
    out += [f"| {s['speaker']} | {s['waktu']} | {s['proporsi']} | {s['giliran']} | {s['kata']} |" for s in doc["statistik"]]
    out += ["", f"_{doc['catatan_statistik']}_", "",
            f"_{doc['catatan_metode']} trace_id: {doc['trace_id']}_"]
    if doc["transkrip"]:
        out += ["", "## Transkrip", ""]
        for turn in doc["transkrip"]:
            out += [f"**[{turn['waktu']}] {turn['speaker']}**", "", turn["teks"], ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {}


def _srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_text(meeting) -> Tuple[str, int]:
    """Numbered cues 'hh:mm:ss,mmm --> hh:mm:ss,mmm' with 'Speaker: text', one per segment. Returns (text, cue count)."""
    segs = [s for s in meeting.segments if s.text.strip()]
    if not segs or not any(s.end_time > s.start_time for s in segs):
        raise ExportError("Transkrip tidak punya timestamp yang bisa dipakai untuk SRT.")
    cues = []
    for n, s in enumerate(segs, 1):
        end = s.end_time if s.end_time > s.start_time else s.start_time + 1.0
        cues.append(f"{n}\n{_srt_time(s.start_time)} --> {_srt_time(end)}\n{s.speaker}: {s.text.strip()}\n")
    return "\n".join(cues), len(cues)


def srt_filename(meeting) -> str:
    suffix, label, _ = FORMATS["srt"]
    return f"{safe_filename(display_title(meeting))} - {label}{suffix}"


def _render_srt(meeting, path: Path) -> Dict:
    text, count = srt_text(meeting)
    path.write_text(text, encoding="utf-8")
    return {"jumlah_cue": count}


def export(rekap: Dict, meeting, stats: Dict, fmt: str, tasks: Optional[List[Dict]] = None,
           trace_id: str = "", include_transcript: bool = True) -> Dict:
    """Write one export file. Returns {path, nama_file, format, ...}."""
    if fmt not in FORMATS:
        raise ExportError(f"Format {fmt} tidak didukung. Pilihan: {sorted(FORMATS)}.")
    path = export_path(rekap["rekap_id"], meeting, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "srt":
        extra = _render_srt(meeting, path)
    else:
        doc = build_document(rekap, meeting, stats, tasks, trace_id, include_transcript)
        extra = {"pdf": _render_pdf, "docx": _render_docx, "md": _render_md}[fmt](doc, path)
    return {"path": path.as_posix(), "nama_file": path.name, "format": fmt,
            "ukuran_kb": round(path.stat().st_size / 1024, 1), **extra}


# Email for an approved report

def _email_item_line(item: Dict) -> Tuple[str, bool]:
    """One action item line. Flag rule matches the PDF: unclear owner or an unverified deadline needs confirmation."""
    owner_ok = item.get("status_penanggung_jawab") == "jelas"
    status = item.get("status_tenggat")
    notes = []
    if not owner_ok:
        notes.append("penanggung jawab belum jelas")
    if status == "tidak_terverifikasi":
        notes.append("tenggat tidak terverifikasi")
    elif status == "relatif":
        notes.append("tenggat relatif, tanpa tanggal")
    warn = not owner_ok or status == "tidak_terverifikasi"
    line = (f"- {'[PERLU KONFIRMASI] ' if warn else ''}{item['id']} {item['isi']} "
            f"(PJ: {item.get('penanggung_jawab') or 'belum jelas'}, tenggat: {item.get('tenggat') or 'tidak disebut'}, {item['mulai']})")
    if notes:
        line += f" Catatan: {'; '.join(notes)}."
    return line, warn


def build_email(rekap: Dict, meeting, attachments: List[Path], sender: str, recipient: str,
                approval_id: str) -> EmailMessage:
    source = load_source(rekap["meeting_id"])
    title = display_title(meeting)
    lines = [f"Rekap meeting: {title}", f"Sumber: {source['url'] or source['catatan']}", ""]
    for jenis, judul in SECTIONS:
        status = section_status(rekap, jenis)
        if status == "ok":
            lines.append(f"{judul}: {len(rekap['bagian'][jenis]['items'])} poin")
        else:
            lines.append(f"{judul}: {'belum dianalisis' if status == 'belum_dianalisis' else 'tidak ditemukan'}")
    note = confirmation_note(rekap)
    if note:
        lines += ["", note]
    if section_status(rekap, "action_items") == "ok":
        lines += ["", "Action items:"]
        flagged = False
        for item in rekap["bagian"]["action_items"]["items"]:
            line, warn = _email_item_line(item)
            lines.append(line)
            flagged = flagged or warn
        if flagged:
            lines += ["", "[PERLU KONFIRMASI] berarti penanggung jawab atau tenggat belum jelas; tanda yang sama ada di lampiran."]
    names = ", ".join(a.name for a in attachments)
    # Technical ids go last: the reader needs the content first, the ids only for tracing.
    lines += ["", f"Detail beserta kutipan dan timestamp ada di lampiran: {names}.", "Dikirim setelah persetujuan Anda.",
              "", "---", f"Informasi teknis (untuk penelusuran): approval_id {approval_id}; rekap_id {rekap['rekap_id']}."]

    msg = EmailMessage()
    msg["Subject"] = email_subject(meeting)
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content("\n".join(lines))
    for attachment in attachments:
        mime = next(v[2] for v in FORMATS.values() if v[0] == attachment.suffix)
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(attachment.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment.name)
    return msg


def email_subject(meeting) -> str:
    return f"[MeetRecall] Rekap meeting: {display_title(meeting)}"[:150]
