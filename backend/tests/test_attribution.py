"""
Quote location and attribution: where a quote really is, and the "(Speaker, time)" written after it checked by code.

Run from backend/:  python -m pytest tests/test_attribution.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent import MID, ScriptedLLM, completion, make_agent, tmp_dirs  # noqa: E402,F401

from agent import guardrails  # noqa: E402
from agent.tools import fmt_ts  # noqa: E402


def seg(start, end, speaker, text):
    return SimpleNamespace(start_time=start, end_time=end, speaker=speaker, text=text)


# The Ginger Cola case: the quote runs over two segments of Speaker 2, after a question by Speaker 0.
SEGS = [
    seg(41, 51, "Speaker 0", "Carrie, can you please give us an update on the marketing strategy?"),
    seg(51, 59, "Speaker 2", "Yes, Tony. Well, we have decided to pitch the new Ginger Cola"),
    seg(59, 62, "Speaker 2", "as a health and energy drink."),
    seg(62, 65, "Speaker 0", "Fantastic."),
    seg(200, 205, "Speaker 1", "Fantastic."),
]
QUOTE = "We have decided to pitch the new Ginger Cola as a health and energy drink."


def test_quote_over_two_segments_is_located_to_its_own_speaker_and_time():
    hits = guardrails.locate_quote(QUOTE, SEGS)
    assert hits == [{"speakers": ["Speaker 2"], "start": 51, "end": 62}]


def test_wrong_speaker_and_chunk_range_are_corrected_in_place():
    answer = f'Dipasarkan sebagai minuman energi. "{QUOTE}" (Speaker 0, 00:41-01:18) Itu keputusannya.'
    fixed, rec = guardrails.check_attribution(answer, SEGS, fmt_ts)
    assert '(Speaker 2, 00:51-01:02) Itu keputusannya.' in fixed and "Speaker 0, 00:41" not in fixed
    assert rec[0]["dikoreksi"] and rec[0]["ditulis"] == "Speaker 0, 00:41-01:18" and rec[0]["speaker"] == "Speaker 2"


def test_correct_attribution_is_left_untouched():
    for attr in ("(Speaker 2, 00:55)", "(Speaker 2, 00:51-01:02)", "(Speaker 2, 00:49-01:05)", "(Speaker 2)", "(01:00)"):
        answer = f'"{QUOTE}" {attr}'
        fixed, rec = guardrails.check_attribution(answer, SEGS, fmt_ts)
        assert fixed == answer and not rec[0]["dikoreksi"], attr


def test_right_speaker_but_chunk_wide_range_is_narrowed_without_alarm():
    # as seen live: Speaker 2 is right, the range 00:42-01:18 is the whole chunk (written with a non-breaking hyphen)
    answer = f'"{QUOTE}" (Speaker 2, 00:42‑01:18).'
    fixed, rec = guardrails.check_attribution(answer, SEGS, fmt_ts)
    assert fixed == f'"{QUOTE}" (Speaker 2, 00:51-01:02).'
    assert rec[0]["dirapikan"] and not rec[0]["dikoreksi"]


def test_wrong_time_only_is_corrected():
    fixed, rec = guardrails.check_attribution(f'"{QUOTE}" (Speaker 2, 03:15)', SEGS, fmt_ts)
    assert fixed.endswith("(Speaker 2, 00:51-01:02)") and rec[0]["dikoreksi"]


def test_claims_that_cannot_be_judged_are_not_touched():
    # a person's name is not a label in this transcript, so the speaker part is not judged; no attribution at all either
    for tail in (" (Carrie)", " (menurut Carrie, sekitar menit ke-1)", ""):
        answer = f'"{QUOTE}"{tail}'
        fixed, rec = guardrails.check_attribution(answer, SEGS, fmt_ts)
        assert fixed == answer and rec[0]["ditemukan"] and not rec[0]["dikoreksi"]


def test_invented_quote_is_not_located_and_not_touched():
    answer = '"anggaran naik dua kali lipat bulan ini" (Speaker 2, 00:55)'
    fixed, rec = guardrails.check_attribution(answer, SEGS, fmt_ts)
    assert fixed == answer and rec == [{"kutipan": "anggaran naik dua kali lipat bulan ini", "ditemukan": False}]


def test_repeated_quote_is_corrected_to_the_occurrence_nearest_the_claimed_time():
    segs = SEGS + [seg(300, 305, "Speaker 2", "We will revisit the budget next quarter.")] \
        + [seg(400, 405, "Speaker 1", "We will revisit the budget next quarter.")]
    fixed, rec = guardrails.check_attribution('"We will revisit the budget next quarter." (Speaker 0, 06:45)', segs, fmt_ts)
    assert fixed.endswith("(Speaker 1, 06:40-06:45)") and rec[0]["ambigu"]
    same, rec2 = guardrails.check_attribution('"We will revisit the budget next quarter."', segs, fmt_ts)
    assert same.startswith('"We will') and rec2[0]["ambigu"] and rec2[0]["speaker"] == "Speaker 2"


def test_final_answer_over_the_loop_is_corrected_and_explained(tmp_dirs):
    # test_agent transcript: "Saya akan menyiapkan dokumen rilis sebelum 12 Oktober" is Speaker 1, 10s-25s
    answer = 'Dokumen rilis disiapkan. "Saya akan menyiapkan dokumen rilis sebelum 12 Oktober" (Speaker 0, 00:00-00:10)'
    script = ScriptedLLM(completion(tool_calls=[("cari_transkrip", {"meeting_id": MID, "query": "dokumen rilis"})]),
                         completion(answer))
    res = make_agent(script).run("Siapa yang menyiapkan dokumen rilis?", MID)
    assert "(Speaker 1, 00:10-00:25)" in res.answer
    assert "tertulis (Speaker 0, 00:00-00:10), seharusnya (Speaker 1, 00:10-00:25)" in res.answer
    assert res.verifikasi["atribusi_dikoreksi"] == 1
    assert res.verifikasi["kutipan"][0]["speaker"] == "Speaker 1" and res.verifikasi["kutipan"][0]["dikoreksi"]
    assert any(e["event"] == "guardrail" and e.get("nama") == "atribusi_kutipan" and e.get("hasil") == "fail"
               for e in res.steps)


def test_meeting_title_in_quotes_is_a_name_not_a_quote(tmp_dirs):
    # live false alarm: the title of the meeting (its file name) is not in the transcript and was flagged
    answer = ('Laporan untuk rapat \u201crapat.mp4\u201d dibuat: \u201crapat - Rekap.docx\u201d. '
              'Speaker 1 berkata "Saya akan menyiapkan dokumen rilis sebelum 12 Oktober" (Speaker 1, 00:10).')
    script = ScriptedLLM(completion(tool_calls=[("cari_transkrip", {"meeting_id": MID, "query": "dokumen rilis"})]),
                         completion(answer))
    res = make_agent(script).run("Siapa yang menyiapkan dokumen rilis?", MID)
    assert "tidak ditemukan persis" not in res.answer   # no false alarm
    v = res.verifikasi
    assert (v["kutipan_total"], v["kutipan_tidak_ditemukan"]) == (1, 0)   # only the real quote is counted


def test_names_are_matched_loosely_but_real_quotes_still_checked():
    names = ["Business Meeting - Ginger Cola Launch.mp4", "Business Meeting - Ginger Cola Launch"]
    assert guardrails.is_name_not_quote("Business Meeting \u2013 Ginger Cola Launch", names)       # en dash
    assert guardrails.is_name_not_quote("Business Meeting - Ginger Cola Launch - Rekap.docx", names)
    assert not guardrails.is_name_not_quote("we have decided to pitch the new Ginger Cola", names)
    # an invented quote that merely mentions the title in the middle is still checked
    assert not guardrails.is_name_not_quote("anggaran Business Meeting - Ginger Cola Launch naik dua kali", names)
    bad = guardrails.unverified_quotes('"Business Meeting - Ginger Cola Launch" dan "anggaran naik dua kali lipat bulan ini"',
                                       "teks lain", names)
    assert bad == ["anggaran naik dua kali lipat bulan ini"]
