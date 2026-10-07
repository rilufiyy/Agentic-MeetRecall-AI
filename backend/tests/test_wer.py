import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import eval_wer  # noqa: E402


def test_normalize_keeps_numbers_whole_and_drops_punctuation():
    assert eval_wer.normalize("Dipotong gaji Rp50.000 saja, pukul 06.00!") == ["dipotong", "gaji", "rp50000", "saja", "pukul", "0600"]
    assert eval_wer.normalize("pokok-pokok") == ["pokok", "pokok"]


def test_wer_counts_substitution_deletion_and_insertion():
    r = eval_wer.wer("a b c d".split(), "a x c".split())
    assert (r["substitusi"], r["penghapusan"], r["penyisipan"]) == (1, 1, 0) and r["wer"] == 0.5
    assert eval_wer.wer("a b".split(), "a b c".split())["penyisipan"] == 1
    assert eval_wer.wer("a b".split(), "a b".split())["wer"] == 0.0


def test_parse_reference_and_speaker_accuracy(tmp_path):
    ref = tmp_path / "ref.txt"
    ref.write_text("# komentar\n00:00 - Speaker 0 (A)\nHalo semuanya.\n\n00:10 - Speaker 1 (B)\nSiap pak.\n", encoding="utf-8")
    turns = eval_wer.parse_reference(ref)
    assert [t["speaker"] for t in turns] == ["Speaker 0", "Speaker 1"] and turns[1]["mulai"] == 10
    segs = [{"start_time": 0.0, "speaker": "Speaker 0", "text": "Halo semuanya"},
            {"start_time": 10.5, "speaker": "Speaker 0", "text": "Siap pak"}]
    res = eval_wer.evaluate(segs, turns)
    assert res["wer"] == 0.0 and res["akurasi_speaker"] == 0.5
