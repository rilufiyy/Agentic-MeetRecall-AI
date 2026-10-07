"""
Deterministic workflow baseline for the workflow vs agent comparison (stage 4).

Same tools, same guardrails, same approval and tracing code as the agent, but the ORDER of the tools is fixed in
code and no LLM decides what to call next. The only LLM calls left are the ones inside `ekstrak_poin_meeting`.

    laporan: extract all kinds -> export the requested formats [-> request the email approval]
    task:    extract all kinds -> request the task approval for every action item

What the user would otherwise say in a sentence ("buatkan laporan PDF dan kirim ke email saya") arrives here as
explicit parameters (aksi, formats, kirim), the way a button or a form would send them. The write-intent guardrail
still runs; it is fed a fixed phrase that matches the explicit choice. Write actions still stop at
`awaiting_approval`: the workflow never executes a write.

SRT only needs a rekap id, not the content of a rekap, so the workflow creates an empty rekap directly and skips the
LLM extraction. The agent cannot do that: it has to call `ekstrak_poin_meeting` to obtain a rekap_id.

Trace events use mode "workflow", so agent and workflow runs of the same scenario can be compared from the trace.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Dict, List, Optional

from agent import approvals, config
from agent.llm_client import ChatClient
from agent.loop import AgentResult
from agent.tools import ToolContext, execute_tool
from agent.tracing import Tracer

ACTIONS = ("laporan", "task")
FORMATS = ("pdf", "docx", "md", "srt")
_INTENT = {"task": "buatkan task dari action items", "kirim": "kirim laporan ke email saya"}


def run_workflow(meeting_id: str, aksi: str, formats: Optional[List[str]] = None, kirim: bool = False,
                 ctx_factory: Optional[Callable] = None, llm: Optional[ChatClient] = None,
                 scenario_id: Optional[str] = None) -> AgentResult:
    if aksi not in ACTIONS:
        raise ValueError(f"aksi harus salah satu dari {ACTIONS}, bukan {aksi!r}")
    formats = list(dict.fromkeys(formats or ["pdf"])) if aksi == "laporan" else []
    if aksi == "laporan" and not set(formats) <= set(FORMATS):
        raise ValueError(f"format tidak dikenal: {sorted(set(formats) - set(FORMATS))}")
    mail_formats = [f for f in formats if f != "srt"]
    if kirim and (aksi != "laporan" or not mail_formats):
        raise ValueError("kirim butuh aksi laporan dengan setidaknya satu format pdf, docx, atau md")

    t0 = time.perf_counter()
    llm = llm or ChatClient()
    tracer = Tracer(meeting_id, mode="workflow", scenario_id=scenario_id)
    ctx = (ctx_factory or (lambda tr, lm: ToolContext(tracer=tr, llm=lm)))(tracer, llm)
    ctx.meeting_id = meeting_id
    ctx.user_message = _INTENT["task"] if aksi == "task" else (_INTENT["kirim"] if kirim else "buatkan laporan")
    tracer.log("run_start", aksi=aksi, formats=formats, kirim=kirim, model=llm.model, tools=[])
    called: List[str] = []

    def finish(status: str, answer: str, approval_id: Optional[str] = None) -> AgentResult:
        latency = round((time.perf_counter() - t0) * 1000, 1)
        totals = tracer.totals()
        active = ctx.rekap_ids.get(meeting_id)
        tracer.log("run_end", status=status, jumlah_iterasi=0, tools_dipanggil=called, rekap_id=active,
                   approval_id=approval_id, total_latency_ms=latency, jawaban=answer[:1000], **totals)
        return AgentResult(status, answer, tracer.trace_id, 0, called, active, approval_id, totals, latency, list(tracer.events))

    def step(tool: str, args: Dict) -> Dict:
        called.append(tool)
        return execute_tool(tool, json.dumps(args), ctx, iterasi=len(called))

    def fail(tool: str, out: Dict) -> AgentResult:
        return finish("workflow_error", f"Langkah {tool} gagal ({out.get('status')}): {out.get('pesan', '')}")

    # 1. a rekap id: full extraction, or an empty rekap when only SRT is wanted
    if aksi == "laporan" and formats == ["srt"]:
        rekap = ctx.rekaps.create(meeting_id, tracer.trace_id)
        ctx.rekap_ids[meeting_id] = rekap["rekap_id"]
        rekap_id = rekap["rekap_id"]
    else:
        out = step("ekstrak_poin_meeting", {"meeting_id": meeting_id, "jenis": "semua"})
        if out.get("status") != "ok":
            return fail("ekstrak_poin_meeting", out)
        rekap_id = out["rekap_id"]

    # 2. the action
    if aksi == "laporan":
        out = step("ekspor_laporan", {"rekap_id": rekap_id, "formats": formats})
        if out.get("status") != "ok":
            return fail("ekspor_laporan", out)
        names = ", ".join(f["nama_file"] for f in out["files"])
        if not kirim:
            return finish("completed", f"Laporan dibuat: {names}.")
        out = step("kirim_email_rekap", {"rekap_id": rekap_id, "formats": mail_formats})
    else:
        rekap = ctx.rekaps.load(rekap_id)
        ids = [i["id"] for i in (rekap["bagian"].get("action_items") or {}).get("items", [])][: config.MAX_TASK_ITEMS]
        if not ids:
            return finish("completed", "Tidak ada action item di meeting ini, jadi tidak ada task yang diajukan.")
        out = step("buat_task", {"rekap_id": rekap_id, "item_ids": ids})
    if out.get("status") != "awaiting_approval":
        return fail(called[-1], out)
    approval = ctx.approvals.get(out["approval_id"])
    return finish("awaiting_approval", approvals.format_request(approval), out["approval_id"])
