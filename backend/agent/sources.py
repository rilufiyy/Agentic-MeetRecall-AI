"""
Source of a meeting video: the YouTube URL the user pastes at upload.

Only metadata. The video itself is never downloaded here (YouTube's terms
restrict downloading outside what the service offers); the user uploads the
file as before. The URL gives the report its title and source line:
title and channel come from YouTube oEmbed, a documented public endpoint
(https://oembed.com/ , https://www.youtube.com/oembed).

The pasted URL is never requested. Only the 11-character video id is taken
from it, and the oEmbed request is built from that id against youtube.com,
so a crafted URL cannot make the server call another host.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from agent import config

_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LOCK = threading.Lock()
OEMBED_TIMEOUT_S = 6


class InvalidSourceUrl(ValueError):
    """The text is not a YouTube video link."""


def parse_youtube_url(url: str) -> str:
    """Video id from youtu.be/ID, youtube.com/watch?v=ID, /live/ID, /shorts/ID or /embed/ID."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in _HOSTS:
        raise InvalidSourceUrl("Bukan tautan YouTube (youtube.com atau youtu.be).")
    parts = [p for p in parsed.path.split("/") if p]
    candidate = ""
    if host == "youtu.be":
        candidate = parts[0] if parts else ""
    elif parts and parts[0] == "watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    elif len(parts) >= 2 and parts[0] in ("live", "shorts", "embed"):
        candidate = parts[1]
    if not _ID.match(candidate):
        raise InvalidSourceUrl("Tautan YouTube ini tidak memuat ID video yang valid.")
    return candidate


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def fetch_oembed(video_id: str) -> Dict:
    """{'title', 'author_name'} from YouTube oEmbed, or {} when it cannot be fetched (private, offline)."""
    target = "https://www.youtube.com/oembed?format=json&url=" + quote(canonical_url(video_id), safe="")
    try:
        with urlopen(Request(target, headers={"User-Agent": "MeetRecall-Agent/1.0"}),
                     timeout=OEMBED_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"title": str(data.get("title") or "")[:200], "author_name": str(data.get("author_name") or "")[:100]}
    except (URLError, OSError, ValueError):
        return {}


def register(meeting_id: str, url: str, fetch: Callable[[str], Dict] = fetch_oembed) -> Dict:
    """Validate the URL and write the entry to sources.json. Raises InvalidSourceUrl before touching any file."""
    video_id = parse_youtube_url(url)
    meta = fetch(video_id)
    today = datetime.now(timezone.utc).date().isoformat()
    entry = {
        "judul": meta.get("title", ""),
        "url": canonical_url(video_id),
        "kanal": meta.get("author_name", ""),
        "catatan": (f"Judul dan kanal dari YouTube oEmbed, diisi saat upload ({today})" if meta
                    else f"Judul tidak bisa diambil dari YouTube ({today}); laporan memakai nama file"),
    }
    path = Path(config.SOURCES_FILE)
    with _LOCK:
        try:
            sources = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sources = {}
        sources[meeting_id] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)   # a crash never leaves a half-written sources.json
    return entry
