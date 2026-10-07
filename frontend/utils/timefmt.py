"""
Timestamp helpers so transcript segments and RAG citations can be checked
against the original recording.
"""
from __future__ import annotations


def fmt_ts(seconds: float, hours: bool = False) -> str:
    """73.8 -> '01:13' (or '00:01:13' with hours=True, or when >= 1 hour)."""
    total = int(max(seconds or 0.0, 0.0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if hours or h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_range(start: float, end: float) -> str:
    """'01:13 - 01:20'; only the start when the end is missing."""
    if end and end > start:
        return f"{fmt_ts(start)} - {fmt_ts(end)}"
    return fmt_ts(start)


def transcript_to_txt(segments: list, header: list[str] | None = None) -> str:
    """
    One line per segment: '[hh:mm:ss] Speaker: text'.

    This is the format POST /api/transcript/import accepts ('#' lines are
    ignored), so a downloaded transcript can be imported again.
    """
    lines = [f"# {h}" for h in (header or [])]
    for seg in segments:
        ts = fmt_ts(seg.get("start_time", 0.0), hours=True)
        lines.append(f"[{ts}] {seg.get('speaker', 'Unknown')}: {seg.get('text', '').strip()}")
    return "\n".join(lines) + "\n"
