"""
Unit tests for correcting speaker labels (Results page -> PUT /speakers).

Run from backend/:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.schemas import TranscriptionResult, TranscriptSegment  # noqa: E402
from services import storage  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(storage, "_MEETINGS_DIR", tmp_path / "meetings")
    monkeypatch.setattr(storage, "_INDEX_PATH", tmp_path / "meetings.json")
    svc = storage.StorageService()
    # Diarization split one person ("Yes, of course, Tony." + "No problem.") in two
    segs = [("Speaker 0", "Jason, can you please take the minutes today?"),
            ("Speaker 1", "Yes, of course, Tony."),
            ("Speaker 2", "No problem."),
            ("Speaker 0", "Thanks.")]
    svc.save_meeting(TranscriptionResult(
        meeting_id="m1", filename="meeting.mp4", duration=10.0, full_text="",
        segments=[TranscriptSegment(start_time=i, end_time=i + 1, speaker=s, text=t)
                  for i, (s, t) in enumerate(segs)]))
    return svc


def test_renumber_speakers_closes_gaps_only_for_generic_labels():
    assert storage.renumber_speakers(["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 3"]) == \
        ["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 2"]
    assert storage.renumber_speakers(["Speaker 1", "Speaker 3", "Speaker 1"]) == \
        ["Speaker 1", "Speaker 2", "Speaker 1"]          # keeps the lowest number
    assert storage.renumber_speakers(["Tony", "Speaker 2", "Carrie"]) == \
        ["Tony", "Speaker 2", "Carrie"]                  # custom names untouched
    assert storage.renumber_speakers(["Speaker 10", "Speaker 2"]) == ["Speaker 3", "Speaker 2"]


def test_merge_renumbers_later_speakers(store):
    store.update_speakers("m1", ["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 3"])
    assert [s.speaker for s in store.load_meeting("m1").segments] == \
        ["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 2"]


def test_merging_labels_updates_segments_and_speaker_count(store):
    assert store.get_meeting_info("m1").num_speakers == 3
    result = store.update_speakers("m1", ["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 0"])
    assert [s.speaker for s in result.segments] == ["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 0"]
    # persisted, and the meeting index counts 2 speakers now
    assert [s.speaker for s in store.load_meeting("m1").segments][2] == "Speaker 1"
    assert store.get_meeting_info("m1").num_speakers == 2
    assert store.get_meeting_info("m1").num_segments == 4


def test_renaming_keeps_text_and_times(store):
    before = store.load_meeting("m1")
    after = store.update_speakers("m1", ["Tony", "Jason", "Jason", "Tony"])
    assert [(s.start_time, s.end_time, s.text) for s in after.segments] == \
           [(s.start_time, s.end_time, s.text) for s in before.segments]
    assert store.get_meeting_info("m1").num_speakers == 2


def test_stale_edit_is_rejected(store):
    loaded = [s.speaker for s in store.load_meeting("m1").segments]
    merged = ["Speaker 0", "Speaker 1", "Speaker 1", "Speaker 0"]
    store.update_speakers("m1", merged, expected=loaded)
    # a second submit built from the old labels must not overwrite the newer ones
    with pytest.raises(storage.StaleSpeakersError):
        store.update_speakers("m1", ["Speaker 0", "Other", "Other", "Speaker 0"], expected=loaded)
    assert [s.speaker for s in store.load_meeting("m1").segments] == merged


def test_label_count_must_match_segments(store):
    with pytest.raises(ValueError):
        store.update_speakers("m1", ["Speaker 0"])
    assert store.update_speakers("missing", ["x"]) is None
