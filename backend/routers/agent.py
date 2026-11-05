"""
Agent router (W78): the HTTP face of backend/agent for the Streamlit page.

Endpoints:
  POST /api/agent/chat/{meeting_id}            run the agent once (returns answer + trace steps)
  GET  /api/agent/approvals                    pending approval requests (?meeting_id=)
  GET  /api/agent/approvals/{approval_id}      one approval request
  POST /api/agent/approvals/{approval_id}      phase 2: user decision, executed by code
  GET  /api/agent/rekap/{rekap_id}             stored rekap (validated items)
  GET  /api/agent/exports/{rekap_id}           export files of a rekap
  GET  /api/agent/exports/{rekap_id}/{file}    download one export file
  GET  /api/agent/tasks                        created tasks (?meeting_id=)
  GET  /api/agent/suggestions/{meeting_id}     proactive next-step suggestions (?rekap_id=)

The approval endpoint is called by the UI button, never by the LLM: the agent
has no tool that reaches it.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent import approvals, reporting, suggestions
from agent.loop import MeetingAgent
from agent.rekap_store import RekapStore

router = APIRouter(prefix="/api/agent", tags=["Agent"])

_agent: Optional[MeetingAgent] = None


def _get_agent() -> MeetingAgent:
    global _agent
    if _agent is None:
        _agent = MeetingAgent()
    return _agent


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[Dict[str, str]] = Field(default_factory=list)
    rekap_id: Optional[str] = Field(None, max_length=64)


class ApprovalDecision(BaseModel):
    setuju: bool
    # {item_id: {"penanggung_jawab": "...", "tenggat": "..."}} typed by the user for buat_task
    isian: Dict[str, Dict[str, str]] = Field(default_factory=dict)


@router.post("/chat/{meeting_id}")
def agent_chat(meeting_id: str, body: AgentChatRequest):
    """Sync endpoint: FastAPI runs it in its thread pool, so a long agent run does not block the event loop."""
    result = _get_agent().run(body.message, meeting_id, history=body.history, rekap_id=body.rekap_id)
    out = asdict(result)
    if result.approval_id:
        out["approval"] = approvals.ApprovalStore().get(result.approval_id)
    out["exports"] = reporting.list_exports(result.rekap_id) if result.rekap_id else []
    return out


@router.get("/approvals")
def pending_approvals(meeting_id: Optional[str] = None):
    return approvals.ApprovalStore().pending(meeting_id)


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str):
    approval = approvals.ApprovalStore().get(approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found.")
    return approval


@router.post("/approvals/{approval_id}")
def decide_approval(approval_id: str, body: ApprovalDecision):
    store = approvals.ApprovalStore()
    try:
        result = approvals.decide(store, approval_id, setuju=body.setuju, isian=body.isian)
    except approvals.InvalidInput as exc:
        raise HTTPException(422, str(exc))   # approval stays pending; the user corrects and resubmits
    except approvals.ApprovalError as exc:
        raise HTTPException(409, str(exc))
    return {"approval": store.get(approval_id), "hasil": result}


@router.get("/rekap/{rekap_id}")
def get_rekap(rekap_id: str):
    rekap = RekapStore().load(rekap_id)
    if rekap is None:
        raise HTTPException(404, "Rekap not found.")
    return rekap


@router.get("/exports/{rekap_id}")
def list_exports(rekap_id: str):
    try:
        return reporting.list_exports(rekap_id)
    except ValueError:
        raise HTTPException(400, "Invalid rekap_id.")


@router.get("/exports/{rekap_id}/{nama_file}")
def download_export(rekap_id: str, nama_file: str):
    # Only names that list_exports returns are served, so a crafted path cannot leave the folder.
    try:
        files = {f["nama_file"]: f for f in reporting.list_exports(rekap_id)}
    except ValueError:
        raise HTTPException(400, "Invalid rekap_id.")
    if nama_file not in files:
        raise HTTPException(404, "File not found.")
    mime = reporting.FORMATS[files[nama_file]["format"]][2]
    return FileResponse(reporting.export_dir(rekap_id) / nama_file, media_type=mime, filename=nama_file)


@router.get("/tasks")
def list_tasks(meeting_id: Optional[str] = None):
    return approvals.ApprovalStore().tasks(meeting_id)


@router.get("/suggestions/{meeting_id}")
def get_suggestions(meeting_id: str, rekap_id: Optional[str] = None):
    """Next steps offered after a recap. Text only: a click sends the suggested sentence as a normal chat message."""
    rekap = RekapStore().load(rekap_id) if rekap_id else None
    if rekap is None or rekap["meeting_id"] != meeting_id:
        return []
    store = approvals.ApprovalStore()
    return suggestions.suggest(rekap, reporting.list_exports(rekap_id), store.existing_task_quotes(meeting_id),
                               store.for_rekap(rekap_id))
