"""
Word error rate (WER) and speaker accuracy of a stored transcript against a human reference.

    python scripts/eval_wer.py --meeting-id <id> --reference ../docs/eval/acuan_xxx.txt [--json out.json]

The reference file format is described in docs/eval/template_teks_acuan.txt.
Both texts go through the same normalization (see normalize), then WER is
(substitutions + deletions + insertions) / reference words, from a word-level
edit distance. No LLM and no API calls: this measures the ASR transcript only.

Speaker accuracy: each reference turn is matched to the system segment whose start time
is closest (within SPEAKER_TOLERANCE seconds); it counts as correct when the labels are equal.
Labels from a diarizer are arbitrary names, so this is only meaningful when the reference
uses the same label space as the system transcript.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

SPEAKER_TOLERANCE = 3.0
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "meetings"
_HEADER = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(Speaker\s+\d+)\b(.*)$", re.IGNORECASE)


def normalize(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r"(?<=\d)[.,](?=\d)", "", text)   # 50.000 -> 50000, 06.00 -> 0600
    text = text.replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return text.split()


def edit_counts(ref: List[str], hyp: List[str]) -> Dict[str, int]:
    """Word-level Levenshtein with a backtrace that counts substitutions, deletions, insertions."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    i, j, sub, dele, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            sub += 0 if ref[i - 1] == hyp[j - 1] else 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return {"substitusi": sub, "penghapusan": dele, "penyisipan": ins, "jumlah_kata_acuan": n}


def wer(ref: List[str], hyp: List[str]) -> Dict[str, float]:
    c = edit_counts(ref, hyp)
    errors = c["substitusi"] + c["penghapusan"] + c["penyisipan"]
    return {**c, "wer": round(errors / c["jumlah_kata_acuan"], 4) if ref else float("nan")}


def parse_reference(path: Path) -> List[Dict]:
    turns: List[Dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _HEADER.match(line.strip())
        if m:
            turns.append({"mulai": int(m.group(1)) * 60 + int(m.group(2)), "speaker": m.group(3).title().replace("  ", " "),
                          "teks": ""})
        elif turns:
            turns[-1]["teks"] = (turns[-1]["teks"] + " " + line.strip()).strip()
    if not turns:
        raise SystemExit("Tidak ada giliran bicara di file acuan. Cek format di template.")
    return turns


def differences(ref: List[str], hyp: List[str], limit: int = 40) -> List[Tuple[str, str, str]]:
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append(({"replace": "ganti", "delete": "hilang", "insert": "tambah"}[tag],
                        " ".join(ref[i1:i2]), " ".join(hyp[j1:j2])))
    return out[:limit]


def evaluate(segments: List[Dict], turns: List[Dict]) -> Dict:
    start, last = turns[0]["mulai"], turns[-1]["mulai"]
    window = [s for s in segments if start - 1 <= s["start_time"] <= last + 1]
    ref_words = normalize(" ".join(t["teks"] for t in turns))
    hyp_words = normalize(" ".join(s["text"] for s in window))
    result = wer(ref_words, hyp_words)
    result["jumlah_kata_sistem"] = len(hyp_words)
    result["jumlah_segmen_sistem"] = len(window)
    result["jumlah_giliran_acuan"] = len(turns)
    # per turn WER: reference turn against system segments that start inside the turn
    per_turn = []
    starts = [t["mulai"] for t in turns]
    for k, t in enumerate(turns):
        # a system segment belongs to the last reference turn that starts at or before it (3 s tolerance)
        owned = [s for s in window if max(i for i, st in enumerate(starts) if st <= s["start_time"] + SPEAKER_TOLERANCE) == k]
        h = normalize(" ".join(s["text"] for s in owned))
        r = normalize(t["teks"])
        per_turn.append({"mulai": f"{t['mulai'] // 60:02d}:{t['mulai'] % 60:02d}", "speaker_acuan": t["speaker"],
                         **wer(r, h)})
    result["per_giliran"] = per_turn
    # speaker accuracy
    correct, rows = 0, []
    for t in turns:
        near = min(window or segments, key=lambda s: abs(s["start_time"] - t["mulai"]))
        ok = abs(near["start_time"] - t["mulai"]) <= SPEAKER_TOLERANCE and near["speaker"].title() == t["speaker"]
        correct += ok
        rows.append({"mulai": f"{t['mulai'] // 60:02d}:{t['mulai'] % 60:02d}", "acuan": t["speaker"],
                     "sistem": near["speaker"], "selisih_detik": round(abs(near["start_time"] - t["mulai"]), 1), "benar": ok})
    result["akurasi_speaker"] = round(correct / len(turns), 4)
    result["speaker_rinci"] = rows
    result["perbedaan"] = differences(ref_words, hyp_words)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meeting-id", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--json")
    args = ap.parse_args()
    meeting = json.loads((DATA_DIR / f"{args.meeting_id}.json").read_text(encoding="utf-8"))
    res = evaluate(meeting["segments"], parse_reference(Path(args.reference)))
    res["meeting_id"], res["provider"] = args.meeting_id, meeting.get("provider")
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("per_giliran", "speaker_rinci", "perbedaan")},
                     ensure_ascii=False, indent=2))
    print("\nPer giliran:")
    for p in res["per_giliran"]:
        print(f"  {p['mulai']} {p['speaker_acuan']:10s} WER {p['wer']:.3f}  (S{p['substitusi']} H{p['penghapusan']} T{p['penyisipan']} dari {p['jumlah_kata_acuan']} kata)")
    print("\nSpeaker:")
    for r in res["speaker_rinci"]:
        print(f"  {r['mulai']} acuan={r['acuan']} sistem={r['sistem']} selisih={r['selisih_detik']}s {'OK' if r['benar'] else 'BEDA'}")
    print("\nPerbedaan kata (acuan -> sistem):")
    for tag, a, b in res["perbedaan"]:
        print(f"  [{tag}] '{a}' -> '{b}'")


if __name__ == "__main__":
    sys.exit(main())
