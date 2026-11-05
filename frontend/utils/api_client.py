"""
Thin HTTP client for the MeetRecall AI backend.
All methods return the parsed JSON dict (or a {"error": "..."} dict on failure).
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote

import requests

_BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


class APIClient:
    def __init__(self, base_url: str = _BACKEND_URL) -> None:
        self.base = base_url.rstrip("/")
        self._session = requests.Session()

    # ── Transcription ─────────────────────────────────────────────────────────

    def upload_file(self, file_obj, provider: str = "local", source_url: str = "") -> dict:
        """
        Upload an audio/video file to start transcription.
        provider: "gemini" | "groq" | "groq_fast" | "local" (Whisper + Pyannote)
        """
        try:
            resp = self._session.post(
                f"{self.base}/api/transcribe",
                files={"file": (file_obj.name, file_obj, "application/octet-stream")},
                data={"provider": provider, "source_url": source_url.strip()},
                timeout=120,
            )
            if resp.status_code >= 400:
                try:
                    return {"error": resp.json().get("detail", resp.text)}
                except ValueError:
                    return {"error": resp.text}
            return resp.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def providers(self) -> dict:
        """Which transcription providers / LLM backend are configured."""
        try:
            resp = self._session.get(f"{self.base}/api/providers", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return {}

    def get_status(self, meeting_id: str) -> dict:
        """Poll transcription status.
        Timeout is generous (60 s) because the single uvicorn worker may be
        busy loading HuggingFace models and temporarily slow to respond.
        A ReadTimeout is treated as still-processing so the caller keeps polling.
        """
        try:
            resp = self._session.get(f"{self.base}/api/status/{meeting_id}", timeout=60)
            if resp.status_code == 404:
                return {"error": "Meeting not found."}
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            return {"status": "processing"}
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def get_transcript(self, meeting_id: str) -> dict:
        """Retrieve full transcript.
        Returns {"status": "processing"} (HTTP 409 or Timeout) or
        {"status": "failed"} (HTTP 500) so callers can distinguish states
        without a separate status call.
        Timeout is 60 s to accommodate slow HuggingFace model responses.
        """
        try:
            resp = self._session.get(f"{self.base}/api/transcript/{meeting_id}", timeout=60)
            if resp.status_code == 404:
                return {"error": "Meeting not found."}
            if resp.status_code == 409:
                return {"status": "processing"}
            if resp.status_code == 500:
                detail = resp.json().get("detail", "Transcription failed.")
                return {"status": "failed", "error": detail}
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            return {"status": "processing"}
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def update_speakers(self, meeting_id: str, speakers: list[str],
                        expected: list[str] | None = None) -> dict:
        """Save corrected speaker labels (one per segment); the backend re-indexes.
        expected: the labels the edit started from (stale edits are rejected)."""
        try:
            resp = self._session.put(
                f"{self.base}/api/transcript/{meeting_id}/speakers",
                json={"speakers": speakers, "expected_speakers": expected}, timeout=120,
            )
            if resp.status_code >= 400:
                return {"error": resp.json().get("detail", resp.text)}
            return resp.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def list_meetings(self) -> list:
        """List all meetings (newest first)."""
        try:
            resp = self._session.get(f"{self.base}/api/meetings", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            return []

    def delete_meeting(self, meeting_id: str) -> bool:
        try:
            resp = self._session.delete(f"{self.base}/api/transcript/{meeting_id}", timeout=10)
            return resp.status_code == 204
        except requests.RequestException:
            return False

    # ── RAG Chat ──────────────────────────────────────────────────────────────

    def rag_chat(
        self, meeting_id: str, query: str, top_k: int = 3,
        history: list | None = None, retrieval: dict | None = None,
    ) -> dict:
        """Ask a question grounded in the meeting transcript.
        Pass history=[{"question":...,"answer":...}] for follow-up question support.
        retrieval: optional settings, e.g. {"retrieval_mode": "hybrid", "min_score": 0.40}.
        """
        payload: dict = {"query": query, "top_k": top_k, **(retrieval or {})}
        if history:
            payload["history"] = history
        try:
            resp = self._session.post(
                f"{self.base}/api/rag/chat/{meeting_id}",
                json=payload,
                timeout=600,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}

    # ── Retrieval experiments ─────────────────────────────────────────────────

    def import_transcript(self, file_obj) -> dict:
        """Import a .txt/.json transcript as a completed meeting (no audio)."""
        try:
            resp = self._session.post(
                f"{self.base}/api/transcript/import",
                files={"file": (file_obj.name, file_obj, "text/plain")},
                timeout=300,
            )
            if resp.status_code >= 400:
                return {"error": resp.json().get("detail", resp.text)}
            return resp.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def compare_retrieval(self, meeting_id: str, payload: dict) -> dict:
        """Run one query through several retrieval modes (no LLM)."""
        try:
            resp = self._session.post(
                f"{self.base}/api/rag/retrieve/{meeting_id}", json=payload, timeout=300
            )
            if resp.status_code >= 400:
                return {"error": resp.json().get("detail", resp.text)}
            return resp.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def evaluate_retrieval(self, meeting_id: str, payload: dict) -> dict:
        """Run a labelled evaluation set and get Hit@k / Recall@k / MRR@k per mode."""
        try:
            resp = self._session.post(
                f"{self.base}/api/rag/evaluate/{meeting_id}", json=payload, timeout=900
            )
            if resp.status_code >= 400:
                return {"error": resp.json().get("detail", resp.text)}
            return resp.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}

    # ── Transcription jobs (W78) ──────────────────────────────────────────────

    def list_jobs(self, limit: int = 30) -> list:
        try:
            resp = self._session.get(f"{self.base}/api/jobs", params={"limit": limit}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return []

    def get_job(self, job_id: str) -> dict:
        try:
            resp = self._session.get(f"{self.base}/api/jobs/{job_id}", timeout=15)
            if resp.status_code == 404:
                return {"error": "Job tidak ditemukan."}
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            return {"status": "diproses"}
        except requests.RequestException as exc:
            return {"error": str(exc)}

    # ── Agent (W78) ───────────────────────────────────────────────────────────

    def _json(self, resp) -> dict:
        if resp.status_code >= 400:
            try:
                return {"error": resp.json().get("detail", resp.text), "status_code": resp.status_code}
            except ValueError:
                return {"error": resp.text, "status_code": resp.status_code}
        return resp.json()

    def agent_chat(self, meeting_id: str, message: str, history: list | None = None,
                   rekap_id: str | None = None) -> dict:
        """One agent run. Can take a minute: several LLM calls plus Groq rate-limit waits."""
        try:
            resp = self._session.post(
                f"{self.base}/api/agent/chat/{meeting_id}",
                json={"message": message, "history": history or [], "rekap_id": rekap_id},
                timeout=600,
            )
            return self._json(resp)
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def decide_approval(self, approval_id: str, setuju: bool, isian: dict | None = None) -> dict:
        try:
            resp = self._session.post(
                f"{self.base}/api/agent/approvals/{approval_id}",
                json={"setuju": setuju, "isian": isian or {}}, timeout=120,
            )
            return self._json(resp)
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def pending_approvals(self, meeting_id: str) -> list:
        try:
            resp = self._session.get(f"{self.base}/api/agent/approvals",
                                     params={"meeting_id": meeting_id}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return []

    def get_rekap(self, rekap_id: str) -> dict:
        try:
            return self._json(self._session.get(f"{self.base}/api/agent/rekap/{rekap_id}", timeout=15))
        except requests.RequestException as exc:
            return {"error": str(exc)}

    def list_exports(self, rekap_id: str) -> list:
        try:
            resp = self._session.get(f"{self.base}/api/agent/exports/{rekap_id}", timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return []

    def download_export(self, rekap_id: str, nama_file: str) -> bytes | None:
        try:
            resp = self._session.get(f"{self.base}/api/agent/exports/{rekap_id}/{quote(nama_file)}", timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException:
            return None

    def suggestions(self, meeting_id: str, rekap_id: str) -> list:
        try:
            resp = self._session.get(f"{self.base}/api/agent/suggestions/{meeting_id}",
                                     params={"rekap_id": rekap_id}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return []

    def list_tasks(self, meeting_id: str) -> list:
        try:
            resp = self._session.get(f"{self.base}/api/agent/tasks",
                                     params={"meeting_id": meeting_id}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return []

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        try:
            resp = self._session.get(f"{self.base}/health", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return {"status": "unreachable"}


api_client = APIClient()