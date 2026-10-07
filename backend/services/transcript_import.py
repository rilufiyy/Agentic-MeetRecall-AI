"""
Import an existing text transcript as a meeting, without audio processing.

Useful for retrieval experiments: the same transcript can be indexed and
evaluated repeatedly without running Whisper/Pyannote every time.

Accepted line formats (one segment per line, blank lines and lines starting
with '#' are ignored):
    [00:01:05] Rina: Kita mulai dari status tiket MR-218.
    [01:05] SPEAKER_01: Oke, saya lanjut.
    Rina: Tanpa timestamp juga boleh.

A JSON file with {"segments": [{speaker, start_time, end_time, text}, ...]}
(the same shape as TranscriptionResult) is also accepted.
"""
from __future__ import annotations

import json
import re
from typing import List, Tuple

from models.schemas import TranscriptSegment

_LINE_RE = re.compile(
    r"^\s*(?:\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]\s*)?"
    r"(?P<speaker>[^:\[\]]{1,40}):\s*(?P<text>.+?)\s*$"
)
_DEFAULT_SEGMENT_SECONDS = 8.0


def _to_seconds(ts: str) -> float:
    parts = [float(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def parse_transcript(raw: str) -> Tuple[List[TranscriptSegment], float]:
    """Return (segments, duration_seconds)."""
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        data = json.loads(stripped)
        segs = [TranscriptSegment(**s) for s in data.get("segments", [])]
        duration = max((s.end_time for s in segs), default=0.0)
        return segs, float(data.get("duration", duration))

    rows = []
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        start = _to_seconds(m.group("ts")) if m.group("ts") else None
        rows.append((start, m.group("speaker").strip(), m.group("text").strip()))

    segments: List[TranscriptSegment] = []
    clock = 0.0
    for i, (start, speaker, text) in enumerate(rows):
        start = clock if start is None else start
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        end = nxt if (nxt is not None and nxt > start) else start + _DEFAULT_SEGMENT_SECONDS
        segments.append(TranscriptSegment(start_time=start, end_time=end,
                                          speaker=speaker, text=text))
        clock = end
    duration = segments[-1].end_time if segments else 0.0
    return segments, duration
