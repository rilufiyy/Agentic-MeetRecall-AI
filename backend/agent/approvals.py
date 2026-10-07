"""
Two-phase write actions (human in the loop).

Phase 1, inside the agent run: a write tool (buat_task, kirim_email_rekap)
validates its arguments, stores an approval request here and returns
`awaiting_approval`. The loop stops. Nothing is written or sent yet.

Phase 2, outside the LLM: the user approves or rejects with the approval_id
(CLI). Code executes the stored, already validated request. The LLM has no
tool to approve anything, so text in a transcript cannot trigger a write.

Storage: SQLite (stdlib) in data/agent/agent.db, tables `approvals` and `tasks`.
Python sqlite3: https://docs.python.org/3/library/sqlite3.html
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from agent import config, mailer, reporting
from agent.guardrails import normalize
from agent.tracing import Tracer

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    trace_id    TEXT NOT NULL,
    meeting_id  TEXT NOT NULL,
    rekap_id    TEXT NOT NULL,
    tool        TEXT NOT NULL,
    argumen     TEXT NOT NULL,
    preview     TEXT NOT NULL,
    status      TEXT NOT NULL,          -- menunggu, diproses, ditolak, dieksekusi, gagal
    dibuat      TEXT NOT NULL,
    diputuskan  TEXT,
    hasil       TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id              TEXT NOT NULL,
    rekap_id                TEXT NOT NULL,
    item_id                 TEXT NOT NULL,
    tugas                   TEXT NOT NULL,
    penanggung_jawab        TEXT NOT NULL,
    sumber_penanggung_jawab TEXT NOT NULL,   -- transkrip or user
    tenggat                 TEXT NOT NULL,
    sumber_tenggat          TEXT NOT NULL,   -- transkrip, user or kosong
    kutipan                 TEXT NOT NULL,
    kutipan_norm            TEXT NOT NULL,
    mulai                   TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'open',
    approval_id             TEXT NOT NULL,
    dibuat                  TEXT NOT NULL,
    UNIQUE (meeting_id, kutipan_norm)        -- the same commitment never becomes two tasks
);
"""

WRITE_TOOLS = ("buat_task", "kirim_email_rekap")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(text: str) -> str:
    """Stored instead of the address itself, so the trace never holds the recipient."""
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


def needs_owner(item: Dict) -> bool:
    return item.get("status_penanggung_jawab") != "jelas"


def needs_deadline(item: Dict) -> bool:
    return item.get("status_tenggat") != "jelas"


class ApprovalError(Exception):
    """Request cannot be approved or executed (unknown id, already decided, config missing)."""


class InvalidInput(ApprovalError):
    """User-typed values are not acceptable. The approval stays pending so the user can correct them."""


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_deadline(text: str, today: Optional[date] = None) -> Tuple[str, Optional[str]]:
    """
    Deadline typed by the user: empty, or a valid date as YYYY-MM-DD.
    Returns (value, warning). A past date is accepted with a warning; a malformed
    or impossible date (2026-02-30) raises InvalidInput.
    """
    value = (text or "").strip()
    if not value:
        return "", None
    if not _ISO_DATE.match(value):
        raise InvalidInput(f"Tenggat '{value}' harus berformat YYYY-MM-DD (contoh 2026-10-31) atau dikosongkan.")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise InvalidInput(f"Tenggat '{value}' bukan tanggal yang valid.") from None
    if day < (today or date.today()):
        return value, f"Tenggat {value} sudah lewat."
    return value, None


def check_isian(isian: Dict[str, Dict[str, str]], today: Optional[date] = None) -> List[str]:
    """Validate every typed deadline before anything runs; returns warnings, raises InvalidInput on errors."""
    warnings: List[str] = []
    for item_id, fill in (isian or {}).items():
        if "tenggat" in fill:
            try:
                _, warning = check_deadline(fill["tenggat"], today)
            except InvalidInput as exc:
                raise InvalidInput(f"{item_id}: {exc}") from None
            if warning:
                warnings.append(f"{item_id}: {warning}")
    return warnings


class ApprovalStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or config.AGENT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            with con:            # commit on success, rollback on exception
                yield con
        finally:
            con.close()

    # Approvals

    def create(self, trace_id: str, meeting_id: str, rekap_id: str, tool: str,
               argumen: Dict, preview: Dict) -> str:
        approval_id = "AP" + uuid.uuid4().hex[:10]
        with self._conn() as con:
            # Every agent run makes a fresh request. Older ones for the same meeting and action would stay
            # clickable (a second click could send the email again), so they are closed as superseded.
            con.execute(
                "UPDATE approvals SET status = 'kedaluwarsa', diputuskan = ?, hasil = ? "
                "WHERE meeting_id = ? AND tool = ? AND status = 'menunggu'",
                (_now(), json.dumps({"status": "kedaluwarsa", "digantikan_oleh": approval_id}), meeting_id, tool))
            con.execute(
                "INSERT INTO approvals (approval_id, trace_id, meeting_id, rekap_id, tool, argumen, preview,"
                " status, dibuat) VALUES (?, ?, ?, ?, ?, ?, ?, 'menunggu', ?)",
                (approval_id, trace_id, meeting_id, rekap_id, tool,
                 json.dumps(argumen, ensure_ascii=False), json.dumps(preview, ensure_ascii=False), _now()))
        return approval_id

    def get(self, approval_id: str) -> Optional[Dict]:
        with self._conn() as con:
            row = con.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return _approval_row(row) if row else None

    def pending(self, meeting_id: Optional[str] = None) -> List[Dict]:
        sql, params = "SELECT * FROM approvals WHERE status = 'menunggu'", []
        if meeting_id:
            sql, params = sql + " AND meeting_id = ?", [meeting_id]
        with self._conn() as con:
            return [_approval_row(r) for r in con.execute(sql + " ORDER BY dibuat", params)]

    def _claim(self, approval_id: str) -> None:
        """Move menunggu -> diproses atomically, so a request runs at most once."""
        with self._conn() as con:
            cur = con.execute("UPDATE approvals SET status = 'diproses' WHERE approval_id = ? AND status = 'menunggu'",
                              (approval_id,))
            if cur.rowcount != 1:
                raise ApprovalError(f"Approval {approval_id} tidak ada atau sudah diputuskan.")

    def _close(self, approval_id: str, status: str, hasil: Dict) -> None:
        with self._conn() as con:
            con.execute("UPDATE approvals SET status = ?, diputuskan = ?, hasil = ? WHERE approval_id = ?",
                        (status, _now(), json.dumps(hasil, ensure_ascii=False), approval_id))

    # Tasks

    def existing_task_quotes(self, meeting_id: str) -> Dict[str, str]:
        """kutipan_norm -> task label, for items that are already tasks."""
        with self._conn() as con:
            rows = con.execute("SELECT id, kutipan_norm FROM tasks WHERE meeting_id = ?", (meeting_id,))
            return {r["kutipan_norm"]: f"T{r['id']}" for r in rows}

    def insert_task(self, row: Dict) -> Optional[str]:
        """Insert one task; returns its label (T<id>) or None when it already exists."""
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._conn() as con:
            cur = con.execute(f"INSERT OR IGNORE INTO tasks ({cols}) VALUES ({marks})", list(row.values()))
            return f"T{cur.lastrowid}" if cur.rowcount == 1 else None

    def tasks(self, meeting_id: Optional[str] = None, rekap_id: Optional[str] = None) -> List[Dict]:
        sql, params = "SELECT * FROM tasks WHERE 1 = 1", []
        if meeting_id:
            sql, params = sql + " AND meeting_id = ?", params + [meeting_id]
        if rekap_id:
            sql, params = sql + " AND rekap_id = ?", params + [rekap_id]
        with self._conn() as con:
            return [{**dict(r), "task_id": f"T{r['id']}"} for r in con.execute(sql + " ORDER BY id", params)]


def _approval_row(row: sqlite3.Row) -> Dict:
    out = dict(row)
    for key in ("argumen", "preview", "hasil"):
        if out.get(key):
            out[key] = json.loads(out[key])
    return out


# Phase 2: decision and execution by code

def decide(store: ApprovalStore, approval_id: str, setuju: bool,
           isian: Optional[Dict[str, Dict[str, str]]] = None,
           rekaps=None, storage=None, trace_dir: Optional[Path] = None) -> Dict:
    """
    Record the user's decision and, when approved, execute the stored request.
    `isian` holds values typed by the user at approval time for buat_task:
    {item_id: {"penanggung_jawab": "...", "tenggat": "..."}}.
    The decision is traced as its own trace (mode "approval") that points back
    to the request with trace_id_permintaan.
    """
    approval = store.get(approval_id)
    if approval is None:
        raise ApprovalError(f"Approval {approval_id} tidak ditemukan.")
    # Checked before the approval is claimed, so a typo does not use up the request.
    warnings = check_isian(isian) if setuju and approval["tool"] == "buat_task" else []
    store._claim(approval_id)

    tracer = Tracer(approval["meeting_id"], mode="approval", trace_dir=trace_dir)
    created = datetime.fromisoformat(approval["dibuat"])
    tracer.log("approval", approval_id=approval_id, tool=approval["tool"],
               keputusan_user="setuju" if setuju else "tolak",
               trace_id_permintaan=approval["trace_id"],
               latency_ms=round((datetime.now(timezone.utc) - created).total_seconds() * 1000, 1))

    if not setuju:
        result = {"status": "rejected", "pesan": "Ditolak user. Tidak ada yang dieksekusi."}
        store._close(approval_id, "ditolak", result)
        return result

    if rekaps is None:
        from agent.rekap_store import RekapStore
        rekaps = RekapStore()
    if storage is None:
        from services.storage import storage_service
        storage = storage_service

    t0 = time.perf_counter()
    try:
        if approval["tool"] == "buat_task":
            result = _execute_buat_task(store, approval, isian or {}, rekaps)
            if warnings:
                result["peringatan"] = warnings
        elif approval["tool"] == "kirim_email_rekap":
            result = _execute_kirim_email(approval, rekaps, storage)
        else:
            raise ApprovalError(f"Tool {approval['tool']} tidak bisa dieksekusi lewat approval.")
        status = "dieksekusi"
    except Exception as exc:
        result = {"status": "error", "pesan": f"{type(exc).__name__}: {str(exc)[:200]}"}
        status = "gagal"
    store._close(approval_id, status, result)
    tracer.log("tool_call", tool=approval["tool"], fase="eksekusi", approval_id=approval_id,
               argumen=approval["argumen"], status=result["status"],
               error=result.get("pesan") if result["status"] == "error" else None,
               latency_ms=round((time.perf_counter() - t0) * 1000, 1),
               ringkasan_output={k: v for k, v in result.items() if k not in ("tasks",)})
    return result


def _load_rekap(rekaps, approval: Dict) -> Dict:
    rekap = rekaps.load(approval["rekap_id"])
    if rekap is None or rekap["meeting_id"] != approval["meeting_id"]:
        raise ApprovalError("Rekap tidak ditemukan untuk meeting ini.")
    return rekap


def _execute_buat_task(store: ApprovalStore, approval: Dict, isian: Dict, rekaps) -> Dict:
    rekap = _load_rekap(rekaps, approval)
    items = {i["id"]: i for i in rekap["bagian"].get("action_items", {}).get("items", [])}
    created, skipped = [], []
    for item_id in approval["argumen"]["item_ids"]:
        item = items.get(item_id)
        if item is None:
            skipped.append({"item_id": item_id, "alasan": "item_tidak_ada"})
            continue
        fill = isian.get(item_id, {})
        owner, owner_src = item.get("penanggung_jawab", ""), "transkrip"
        if needs_owner(item) or fill.get("penanggung_jawab"):
            owner, owner_src = (fill.get("penanggung_jawab") or "").strip(), "user"
        if not owner:
            skipped.append({"item_id": item_id, "alasan": "penanggung_jawab_belum_diisi"})
            continue
        deadline, deadline_src = item.get("tenggat", ""), "transkrip" if item.get("tenggat") else "kosong"
        if fill.get("tenggat"):
            deadline, deadline_src = fill["tenggat"].strip(), "user"
        label = store.insert_task({
            "meeting_id": approval["meeting_id"], "rekap_id": rekap["rekap_id"], "item_id": item_id,
            "tugas": item.get("isi", ""), "penanggung_jawab": owner[:100],
            "sumber_penanggung_jawab": owner_src, "tenggat": deadline[:100], "sumber_tenggat": deadline_src,
            "kutipan": item["kutipan"], "kutipan_norm": normalize(item["kutipan"]), "mulai": item["mulai"],
            "approval_id": approval["approval_id"], "dibuat": _now(),
        })
        if label is None:
            skipped.append({"item_id": item_id, "alasan": "sudah_menjadi_task"})
        else:
            created.append({"task_id": label, "item_id": item_id, "penanggung_jawab": owner,
                            "tenggat": deadline or "-"})
    return {"status": "ok" if created else "not_found", "jumlah_dibuat": len(created),
            "tasks": created, "dilewati": skipped}


def attachments_of(preview: Dict) -> List[Dict]:
    """Attachment list of an email approval. Requests made before multi-format support hold one file."""
    att = preview["lampiran"]
    if isinstance(att, list):
        return att
    return [{"path": att, "nama_file": preview.get("nama_file") or Path(att).name,
             "ukuran_kb": preview.get("ukuran_kb"), "sha256": preview.get("sha256")}]


def _execute_kirim_email(approval: Dict, rekaps, storage) -> Dict:
    rekap = _load_rekap(rekaps, approval)
    folder = reporting.export_dir(rekap["rekap_id"]).resolve()
    attachments = []
    for att in attachments_of(approval["preview"]):
        path = Path(att["path"])
        if path.resolve().parent != folder or not path.exists():
            raise ApprovalError(f"Lampiran {att['nama_file']} tidak ada di folder laporan rekap ini.")
        if file_sha256(path) != att["sha256"]:
            raise ApprovalError(f"Lampiran {att['nama_file']} berubah setelah permintaan persetujuan dibuat. "
                                "Buat permintaan baru.")
        attachments.append(path)
    recipient = mailer.report_recipient()
    if text_sha256(recipient) != approval["argumen"]["penerima_sha256"]:
        raise ApprovalError("REPORT_EMAIL_TO berubah setelah permintaan dibuat. Buat permintaan baru.")
    meeting = storage.load_meeting(approval["meeting_id"])
    msg = reporting.build_email(rekap, meeting, attachments, sender=mailer.sender_address(),
                                recipient=recipient, approval_id=approval["approval_id"])
    sent = mailer.deliver(msg, approval["approval_id"])
    return {"status": "ok", "penerima": mailer.mask_email(recipient),
            "lampiran": [p.name for p in attachments], **sent}


# Text shown to the user, built by code (not by the LLM)

def format_request(approval: Dict) -> str:
    p = approval["preview"]
    lines = [f"Menunggu persetujuan Anda (approval_id {approval['approval_id']}).", ""]
    if approval["tool"] == "buat_task":
        lines.append(f"Akan dibuat {len(p['items'])} task dari rekap {approval['rekap_id']}:")
        for it in p["items"]:
            pj = it["penanggung_jawab"] or "belum jelas"
            tg = it["tenggat"] or "tidak disebut"
            note = []
            if it["perlu_isi_penanggung_jawab"]:
                note.append("penanggung jawab perlu Anda isi")
            if it["perlu_cek_tenggat"]:
                note.append("tenggat perlu dicek")
            lines.append(f"- {it['id']} {it['isi']} | PJ: {pj} | tenggat: {tg} | {it['mulai']}"
                         + (f" ({'; '.join(note)})" if note else ""))
        if p.get("sudah_jadi_task"):
            lines.append(f"Dilewati karena sudah menjadi task: {', '.join(p['sudah_jadi_task'])}")
    elif approval["tool"] == "kirim_email_rekap":
        lines += [f"Kirim rekap {approval['rekap_id']} ke `{p['penerima']}` (mode {p['mode']}):", "",
                  f"- Subjek: {p['subjek']}"] + [f"- Lampiran: {a['nama_file']} ({a['ukuran_kb']} KB)"
                                                for a in attachments_of(p)]
    if p.get("peringatan"):
        lines += ["", "Peringatan: " + p["peringatan"]]
    lines += ["", "Tidak ada yang dijalankan sebelum Anda setuju."]
    return "\n".join(lines)
