"""
Rekap store: the structured result of a meeting analysis, one JSON file per
rekap in data/agent/rekap/{rekap_id}.json.

Extraction tools write here; the final recap, the PDF and the tasks are built
from this file by code, so structured data never passes through free LLM text.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from agent import config
from agent.guardrails import normalize

ID_PREFIX = {"action_items": "A", "keputusan": "K", "isu_terbuka": "I", "ringkasan": "R"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RekapStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or config.REKAP_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, rekap_id: str) -> Path:
        if not rekap_id.isalnum():
            raise ValueError("rekap_id tidak valid")
        return self.root / f"{rekap_id}.json"

    def create(self, meeting_id: str, trace_id: str) -> Dict:
        rekap = {
            "rekap_id": uuid.uuid4().hex[:12],
            "meeting_id": meeting_id,
            "dibuat": _now(),
            "diperbarui": _now(),
            "trace_ids": [trace_id],
            "bagian": {},
        }
        self.save(rekap)
        return rekap

    def load(self, rekap_id: str) -> Optional[Dict]:
        try:
            path = self._path(rekap_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, rekap: Dict) -> None:
        rekap["diperbarui"] = _now()
        self._path(rekap["rekap_id"]).write_text(
            json.dumps(rekap, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_items(self, rekap: Dict, jenis: str, items: List[Dict], fokus: Optional[str]) -> List[Dict]:
        """
        Merge verified items into a section, skipping quotes already stored.
        Returns the items that were added (with their new ids).
        """
        section = rekap["bagian"].setdefault(jenis, {"status": "tidak_ditemukan", "items": [], "fokus": []})
        if fokus and fokus not in section["fokus"]:
            section["fokus"].append(fokus)
        seen = {normalize(i["kutipan"]) for i in section["items"]}
        added = []
        for item in items:
            key = normalize(item["kutipan"])
            if key in seen:
                continue
            seen.add(key)
            item = {"id": f"{ID_PREFIX[jenis]}{len(section['items']) + 1}", **item}
            section["items"].append(item)
            added.append(item)
        if section["items"]:
            section["status"] = "ok"
        self.save(rekap)
        return added
