"""
Transcription router.

Endpoints:
  POST   /api/transcribe              - upload file, queue a transcription job
  GET    /api/jobs                    - transcription jobs (antre, diproses, selesai, gagal)
  GET    /api/jobs/{job_id}           - one job
  GET    /api/status/{meeting_id}     - lightweight status poll
  GET    /api/transcript/{meeting_id} - full transcript (only when completed)
  GET    /api/meetings                - list all meetings (newest first)
  DELETE /api/transcript/{meeting_id} - remove meeting and its data
  POST   /api/transcript/import       - import a text/JSON transcript (no audio)
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from models.schemas import MeetingInfo, SpeakerUpdate, TranscriptionResult
from agent import sources
from services.storage import StaleSpeakersError, storage_service
from services.transcript_import import parse_transcript
from services.transcription_jobs import JobRunner, JobStore
from services.transcription import transcription_service
from services.vector_store import vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Transcription"])

_UPLOAD_DIR = Path("uploads")
_UPLOAD_DIR.mkdir(exist_ok=True)

_ALLOWED_EXT = {".mp4", ".mkv", ".mov", ".avi", ".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac"}


# Transcription job (deterministic workflow, see services/transcription_jobs.py)

def _pipeline(meeting_id: str, audio_path: Path, filename: str, provider: str) -> None:
    """Transcribe -> save -> index. Runs in the job worker thread; raises on failure."""
    segments, full_text, duration = asyncio.run(
        transcription_service.transcribe(audio_path, provider=provider)
    )
    result = TranscriptionResult(
        meeting_id=meeting_id,
        filename=filename,
        duration=duration,
        segments=segments,
        full_text=full_text,
        provider=provider,
        created_at=datetime.utcnow(),
        status="completed",
    )
    storage_service.save_meeting(result)

    # Build FAISS index so RAG, retrieval and the agent are immediately available
    vector_store.index_segments(meeting_id, segments)
    logger.info(f"Pipeline completed for meeting {meeting_id}.")


job_runner = JobRunner(JobStore(), _pipeline, storage_service.update_status, storage_service.load_meeting)


# Endpoints

@router.post("/transcribe", status_code=202)
async def upload_and_transcribe(
    file: UploadFile = File(...),
    provider: str = Form("local"),
    source_url: str = Form(""),
):
    """
    Upload an audio/video file and start transcription in the background.

    - **provider**: `groq` (Groq Whisper + Pyannote), `groq_fast` (Groq Whisper only),
      or `local` (local Whisper + Pyannote, heavy on CPU).
    - Returns a `meeting_id` immediately; poll `/api/jobs/{meeting_id}` for progress.
    - Jobs run one at a time; a notification email goes to REPORT_EMAIL_TO when done.
    - **source_url** (optional): YouTube link of the video. Only metadata (title, channel, link)
      for reports; the file is still the one uploaded here. Rejected with 400 when not a YouTube link.
    """
    if provider not in transcription_service.PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}'. Use one of {transcription_service.PROVIDERS}.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(_ALLOWED_EXT)}")

    if source_url.strip():
        try:
            sources.parse_youtube_url(source_url)   # validate before the file is stored
        except sources.InvalidSourceUrl as exc:
            raise HTTPException(400, f"source_url: {exc}")

    meeting_id = str(uuid.uuid4())
    save_path = _UPLOAD_DIR / f"{meeting_id}{ext}"

    try:
        with save_path.open("wb") as buf:
            shutil.copyfileobj(file.file, buf)
    except Exception as exc:
        raise HTTPException(500, f"File save failed: {exc}")

    # Register placeholder so status endpoint works immediately
    storage_service.create_meeting(
        MeetingInfo(
            meeting_id=meeting_id,
            filename=file.filename or "upload",
            duration=0.0,
            provider=provider,
            created_at=datetime.utcnow(),
            status="queued",
        )
    )
    source = None
    if source_url.strip():
        # oEmbed is a short network call; keep it off the event loop.
        source = await asyncio.to_thread(sources.register, meeting_id, source_url)
    job = job_runner.submit(meeting_id, save_path, file.filename or "upload", provider)

    return {
        "source": source,
        "meeting_id": meeting_id,
        "status": "queued",
        "job_status": job["status"],
        "provider": provider,
        "message": "Upload received. Transcription job queued.",
    }


@router.get("/jobs")
async def list_jobs(limit: int = 50):
    """Transcription jobs, newest first."""
    return job_runner.store.list(min(max(limit, 1), 200))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_runner.store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job

@router.get("/providers")
async def list_providers():
    """Transcription providers and whether each is configured in backend/.env."""
    from services.llm import llm_service
    return {"transcription": transcription_service.availability(),
            "llm": llm_service.backend_name()}


@router.post("/transcript/import", status_code=201)
async def import_transcript(file: UploadFile = File(...)):
    """
    Import an existing transcript (.txt or .json) as a completed meeting.

    Skips ASR and diarization, then builds the FAISS index directly, so the
    RAG chat and the retrieval experiments can run without an audio file.
    Line format: `[hh:mm:ss] Speaker: text` (timestamp optional).
    """
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        segments, duration = parse_transcript(raw)
    except Exception as exc:
        raise HTTPException(400, f"Cannot parse transcript: {exc}")
    if not segments:
        raise HTTPException(400, "No segments found. Expected lines like '[00:01:05] Rina: ...'.")

    meeting_id = str(uuid.uuid4())
    result = TranscriptionResult(
        meeting_id=meeting_id,
        filename=file.filename or "imported_transcript.txt",
        duration=duration,
        segments=segments,
        full_text=" ".join(s.text for s in segments),
        provider="import",
        created_at=datetime.utcnow(),
        status="completed",
    )
    storage_service.save_meeting(result)
    vector_store.index_segments(meeting_id, segments)
    return {"meeting_id": meeting_id, "num_segments": len(segments), "status": "completed"}


@router.get("/status/{meeting_id}")
async def get_status(meeting_id: str):
    """Poll this endpoint to check transcription progress."""
    info = storage_service.get_meeting_info(meeting_id)
    if not info:
        raise HTTPException(404, "Meeting not found.")
    return {
        "meeting_id": info.meeting_id,
        "status": info.status,
        "filename": info.filename,
        "duration": info.duration,
        "provider": info.provider,
        "num_speakers": info.num_speakers,
    }

@router.get("/transcript/{meeting_id}", response_model=TranscriptionResult)
async def get_transcript(meeting_id: str):
    """Return the full transcript (only available when status = completed)."""
    info = storage_service.get_meeting_info(meeting_id)
    if not info:
        raise HTTPException(404, "Meeting not found.")
    if info.status in ("processing", "queued"):
        raise HTTPException(409, "Transcription still in progress.")
    if info.status == "failed":
        raise HTTPException(500, "Transcription failed. Please re-upload.")

    result = storage_service.load_meeting(meeting_id)
    if not result:
        raise HTTPException(404, "Transcript data not found.")
    return result


_MAX_SPEAKER_LABEL = 60


@router.put("/transcript/{meeting_id}/speakers", response_model=TranscriptionResult)
async def update_speakers(meeting_id: str, body: SpeakerUpdate):
    """
    Correct speaker labels: one label per segment, in transcript order.

    Automatic diarization can split one person into several labels (or merge
    two people), so the Results page lets users fix labels by hand. Giving two
    labels the same name merges them. The FAISS index is rebuilt so chat and
    retrieval use the new labels immediately.
    """
    info = storage_service.get_meeting_info(meeting_id)
    if not info:
        raise HTTPException(404, "Meeting not found.")
    if info.status != "completed":
        raise HTTPException(409, "Transcription is not completed yet.")

    speakers = [s.strip() for s in body.speakers]
    if any(not s for s in speakers):
        raise HTTPException(400, "Speaker labels must not be empty.")
    if any(len(s) > _MAX_SPEAKER_LABEL for s in speakers):
        raise HTTPException(400, f"Speaker labels must be at most {_MAX_SPEAKER_LABEL} characters.")
    try:
        result = storage_service.update_speakers(meeting_id, speakers, body.expected_speakers)
    except StaleSpeakersError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not result:
        raise HTTPException(404, "Transcript data not found.")

    vector_store.index_segments(meeting_id, result.segments)
    logger.info(f"Updated speaker labels and re-indexed meeting {meeting_id}.")
    return result


@router.get("/meetings", response_model=list[MeetingInfo])
async def list_meetings():
    """List all meetings ordered by newest first."""
    return storage_service.list_meetings()

@router.delete("/transcript/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str):
    """Delete a meeting and all associated data (transcript, FAISS index)."""
    info = storage_service.get_meeting_info(meeting_id)
    if not info:
        raise HTTPException(404, "Meeting not found.")
    storage_service.delete_meeting(meeting_id)
    # Remove FAISS files
    from services.vector_store import _FAISS_DIR
    (_FAISS_DIR / f"{meeting_id}.index").unlink(missing_ok=True)
    (_FAISS_DIR / f"{meeting_id}_chunks.pkl").unlink(missing_ok=True)
    return Response(status_code=204)   # W78: a JSON body ("null") broke the 204 response