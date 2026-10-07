"""
Transcription jobs: a deterministic workflow, not an agent.

Upload -> job "antre" -> one worker thread takes jobs in order -> "diproses"
-> "selesai" or "gagal" -> notification email to REPORT_EMAIL_TO.

Why one in-process worker instead of FastAPI BackgroundTasks alone: background
tasks start right away, so several uploads would run ASR at the same time on a
CPU laptop and there is no real "antre" state. A queue with a single worker
gives an honest status and runs one heavy job at a time. Trade-off: the queue
lives in memory, so jobs that were waiting when the server stopped are marked
"gagal" at startup and must be uploaded again. A broker (Redis, RQ, Celery)
would avoid that, at the cost of another service to run.

Job rows live in SQLite (data/jobs.db). Every state change is also traced to
data/traces/ with mode "workflow", so monitoring sees jobs and agent runs
in the same format.
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

from agent import config, mailer
from agent.tracing import Tracer

logger = logging.getLogger(__name__)

# Job status (Indonesian, shown in the UI) -> MeetingInfo.status used by the W6 code.
STATUS_MEETING = {"antre": "queued", "diproses": "processing", "selesai": "completed", "gagal": "failed"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,          -- same as meeting_id
    filename    TEXT NOT NULL,
    provider    TEXT NOT NULL,
    status      TEXT NOT NULL,             -- antre, diproses, selesai, gagal
    dibuat      TEXT NOT NULL,
    mulai       TEXT,
    selesai     TEXT,
    durasi_proses_detik REAL,
    error       TEXT,
    notifikasi  TEXT                       -- terkirim (dry_run/smtp), dilewati: ..., gagal: ...
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or config.JOBS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def add(self, job_id: str, filename: str, provider: str) -> None:
        with self._conn() as con:
            con.execute("INSERT INTO jobs (job_id, filename, provider, status, dibuat) VALUES (?, ?, ?, 'antre', ?)",
                        (job_id, filename, provider, _now()))

    def update(self, job_id: str, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as con:
            con.execute(f"UPDATE jobs SET {cols} WHERE job_id = ?", [*fields.values(), job_id])

    def get(self, job_id: str) -> Optional[Dict]:
        with self._conn() as con:
            row = con.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50) -> List[Dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM jobs ORDER BY dibuat DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def unfinished(self) -> List[Dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM jobs WHERE status IN ('antre', 'diproses')").fetchall()
        return [dict(r) for r in rows]


def build_notification(job: Dict, meeting=None) -> EmailMessage:
    """Plain-text email about a finished job. Built by code from the job row."""
    from agent.reporting import display_title
    title = display_title(meeting) if meeting is not None else Path(job["filename"]).stem
    done = job["status"] == "selesai"
    lines = [f"Transkripsi {'selesai' if done else 'gagal'}: {title}", "",
             f"File: {job['filename']}", f"Provider: {job['provider']}",
             f"Diunggah: {config.local_time(job['dibuat'])}", f"Selesai: {config.local_time(job['selesai'])}",
             f"Lama proses: {job['durasi_proses_detik']} detik"]
    if done and meeting is not None:
        speakers = len({s.speaker for s in meeting.segments})
        lines += [f"Durasi meeting: {meeting.duration / 60:.1f} menit", f"Jumlah speaker: {speakers}",
                  "", f"Buka MeetRecall untuk analisis dengan agent: {config.UI_URL}",
                  f"meeting_id: {job['job_id']}"]
    elif not done:
        lines += ["", f"Penyebab: {(job.get('error') or '-')[:500]}", "Silakan upload ulang file tersebut."]
    srt = None
    if done and meeting is not None:
        # The transcript goes along as SRT, built by code from the stored transcript (no LLM, no approval).
        # The recipient stays REPORT_EMAIL_TO, so no data leaves to any other address.
        from agent.reporting import ExportError, srt_filename, srt_text
        try:
            srt = (srt_filename(meeting), srt_text(meeting)[0])
            lines += ["", f"Transkrip lengkap dengan timestamp ada di lampiran: {srt[0]}."]
        except ExportError as exc:
            lines += ["", f"Transkrip tidak dilampirkan: {exc}"]
    msg = EmailMessage()
    msg["Subject"] = f"[MeetRecall] Transkripsi {'selesai' if done else 'gagal'}: {title}"[:150]
    msg["From"] = mailer.sender_address()
    msg["To"] = mailer.report_recipient()
    msg.set_content("\n".join(lines))
    if srt:
        msg.add_attachment(srt[1].encode("utf-8"), maintype="application", subtype="x-subrip", filename=srt[0])
    return msg


class JobRunner:
    """
    `pipeline(job_id, audio_path, filename, provider)` does the actual work and
    raises on failure. `set_meeting_status` mirrors the job status into the W6
    meeting index. Both are injected so tests run without ASR.
    """

    def __init__(self, store: JobStore, pipeline: Callable[[str, Path, str, str], None],
                 set_meeting_status: Callable[[str, str], None],
                 load_meeting: Callable[[str], object] = lambda _id: None,
                 trace_dir: Optional[Path] = None) -> None:
        self.store = store
        self.pipeline = pipeline
        self.set_meeting_status = set_meeting_status
        self.load_meeting = load_meeting
        self.trace_dir = trace_dir
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _tracer(self, job_id: str) -> Tracer:
        # One trace per job, so all its events share a trace_id.
        return Tracer(job_id, mode="workflow", trace_dir=self.trace_dir, trace_id=f"job-{job_id}")

    def recover(self) -> int:
        """Jobs left 'antre' or 'diproses' by a stopped server cannot resume (their queue was in memory)."""
        stale = self.store.unfinished()
        for job in stale:
            self.store.update(job["job_id"], status="gagal", selesai=_now(),
                              error="Server dimulai ulang sebelum job selesai. Upload ulang file.")
            self.set_meeting_status(job["job_id"], STATUS_MEETING["gagal"])
        return len(stale)

    def submit(self, job_id: str, audio_path: Path, filename: str, provider: str, start: bool = True) -> Dict:
        self.store.add(job_id, filename, provider)
        self.set_meeting_status(job_id, STATUS_MEETING["antre"])
        self._queue.put((job_id, audio_path, filename, provider))
        tracer = self._tracer(job_id)
        tracer.log("job", fase="antre", filename=filename, provider=provider, posisi_antrean=self._queue.qsize())
        if start:
            self._ensure_worker()
        return self.store.get(job_id)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="transcription-worker", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        while True:
            self.run_next(block=True)

    def run_next(self, block: bool = False) -> Optional[Dict]:
        """Process one queued job. Returns the final job row, or None when the queue is empty."""
        try:
            job_id, audio_path, filename, provider = self._queue.get(block=block)
        except queue.Empty:
            return None
        tracer = self._tracer(job_id)
        t0 = time.perf_counter()
        self.store.update(job_id, status="diproses", mulai=_now())
        self.set_meeting_status(job_id, STATUS_MEETING["diproses"])
        tracer.log("job", fase="diproses")
        try:
            self.pipeline(job_id, audio_path, filename, provider)
            status, error = "selesai", None
        except Exception as exc:   # the job fails; the worker keeps running
            logger.error(f"Job {job_id} gagal: {exc}")
            status, error = "gagal", f"{type(exc).__name__}: {str(exc)[:300]}"
            self.set_meeting_status(job_id, STATUS_MEETING["gagal"])
        finally:
            Path(audio_path).unlink(missing_ok=True)
            self._queue.task_done()
        elapsed = round(time.perf_counter() - t0, 1)
        self.store.update(job_id, status=status, selesai=_now(), durasi_proses_detik=elapsed, error=error)
        tracer.log("job", fase=status, durasi_proses_detik=elapsed, error=error)
        notifikasi = self._notify(self.store.get(job_id))
        self.store.update(job_id, notifikasi=notifikasi)
        tracer.log("notifikasi", hasil=notifikasi)
        return self.store.get(job_id)

    def _notify(self, job: Dict) -> str:
        try:
            mailer.report_recipient()
        except mailer.MailError:
            return "dilewati: REPORT_EMAIL_TO kosong"
        try:
            meeting = self.load_meeting(job["job_id"]) if job["status"] == "selesai" else None
            sent = mailer.deliver(build_notification(job, meeting), f"job-{job['job_id']}")
            return f"terkirim ({sent['mode']})"
        except Exception as exc:
            return f"gagal: {type(exc).__name__}: {str(exc)[:150]}"
