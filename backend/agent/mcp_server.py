"""
MCP server: the same seven agent tools, exposed over the Model Context Protocol.

Any MCP client (Claude Desktop, Claude Code, an IDE) can call cari_transkrip, ekstrak_poin_meeting,
statistik_meeting, ekspor_laporan, buat_task, kirim_email_rekap and minta_klarifikasi. The tool list,
the JSON schemas and the execution all come from agent.tools.TOOLS, so there is one definition and the
guardrails (argument validation, meeting scope, write intent, quote verification, tracing) run unchanged.

What MCP does NOT change:
- Writes stay two-phase. buat_task and kirim_email_rekap only create an approval request and return
  `awaiting_approval`. There is no MCP tool to approve; the user approves in the app (Agent page) or CLI.
- Write intent is still checked against the user's words. An MCP client has no chat turn, so the two write
  tools require `permintaan_user` (the user's literal request); without it the guardrail rejects the call.
- The email recipient is fixed by the system, never an argument.

Run (stdio):  python -m agent.mcp_server
MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
"""
from __future__ import annotations

import asyncio
import json
import weakref
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agent import approvals, guardrails
from agent.llm_client import ChatClient
from agent.tools import TOOLS, ToolContext, execute_tool
from agent.schemas import tool_schema
from agent.tracing import Tracer
from agent.workflow import ACTIONS, FORMATS, run_workflow

WORKFLOW_TOOL = "jalankan_workflow"
# Optional fields filled by a host app (agent loop), never by the LLM: they tie a call to a running agent run,
# so the call shares that run's context (active meeting, trace, rekaps, injection flag). Stripped from LLM specs.
HOST_FIELDS = {"run_id": {"type": "string", "description": "ID run agent pemanggil (diisi aplikasi host)."},
               "iterasi": {"type": "integer", "description": "Nomor iterasi agent loop (diisi aplikasi host)."}}
SERVER_NAME = "meetrecall-ai"
WRITE_FIELD = "permintaan_user"
_WRITE_NOTE = (f" Wajib menyertakan '{WRITE_FIELD}': kalimat asli permintaan user (mis. 'buatkan task dari action items'). "
               "Tool ini hanya membuat permintaan persetujuan; persetujuan dilakukan user di aplikasi, bukan lewat MCP.")


class WorkflowArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meeting_id: str
    aksi: Literal["laporan", "task"] = Field(description="laporan: ekstrak semua lalu ekspor; task: ajukan task dari semua action items.")
    formats: List[Literal["pdf", "docx", "md", "srt"]] = Field(default_factory=lambda: ["pdf"], description="Hanya untuk aksi laporan.")
    kirim: bool = Field(default=False, description="Ajukan persetujuan kirim email (pdf, docx, md). Penerima ditetapkan sistem.")


_WORKFLOW_DESC = ("Jalur workflow tetap tanpa LLM yang memilih tool: ekstrak semua poin, lalu ekspor laporan atau ajukan task "
                  "dengan urutan yang sudah ditentukan kode. Tool, guardrail, persetujuan, dan trace sama dengan agent. "
                  "Aksi tulis (task, kirim email) hanya membuat permintaan persetujuan.")


def list_specs() -> List[Dict[str, Any]]:
    """Tool definitions in MCP shape (name, description, inputSchema), derived from the shared registry."""
    out = []
    for tool in TOOLS.values():
        spec = tool.spec()["function"]
        schema = json.loads(json.dumps(spec["parameters"]))
        description = spec["description"]
        if tool.name in approvals.WRITE_TOOLS:
            schema.setdefault("properties", {})[WRITE_FIELD] = {
                "type": "string", "description": "Permintaan asli user yang meminta aksi ini."}
            schema.setdefault("required", []).append(WRITE_FIELD)
            description += _WRITE_NOTE
        schema["properties"].update(HOST_FIELDS)
        out.append({"name": tool.name, "description": description, "inputSchema": schema})
    wf_schema = tool_schema(WorkflowArgs)
    wf_schema["properties"][WRITE_FIELD] = {"type": "string", "description": (
        "Permintaan asli user. Wajib bila aksi task atau kirim=true; dicek oleh guardrail write intent.")}
    out.append({"name": WORKFLOW_TOOL, "description": _WORKFLOW_DESC, "inputSchema": wf_schema})
    return out


class McpSession:
    """State shared by the calls of one MCP connection: the LLM client and the rekaps built so far."""

    def __init__(self, llm: Optional[ChatClient] = None, ctx_factory=None) -> None:
        self.llm = llm or ChatClient()
        self.ctx_factory = ctx_factory or (lambda tracer, llm: ToolContext(tracer=tracer, llm=llm))
        self.rekap_ids: Dict[str, str] = {}
        self._runs: "weakref.WeakValueDictionary[str, ToolContext]" = weakref.WeakValueDictionary()

    def register_run(self, ctx: ToolContext) -> str:
        """Let calls that carry this run_id execute inside the agent run's own context (same tracer and state)."""
        self._runs[ctx.tracer.trace_id] = ctx
        return ctx.tracer.trace_id

    def call(self, name: str, arguments: Optional[Dict[str, Any]]) -> Dict:
        """Run one tool. Never raises: failures are a result with an error status, as in the agent loop."""
        args = dict(arguments or {})
        user_request = args.pop(WRITE_FIELD, None)
        run_id, iterasi = args.pop("run_id", None), args.pop("iterasi", None)
        host_ctx = self._runs.get(run_id) if run_id else None
        if host_ctx is not None:
            # Guardrails and tracing run exactly as in-process: the host's ctx carries meeting scope and user message.
            return execute_tool(name, json.dumps(args), host_ctx, iterasi=iterasi)
        if name == WORKFLOW_TOOL:
            return self._workflow(args, user_request)
        meeting_id = str(args.get("meeting_id") or "mcp")
        tracer = Tracer(meeting_id, mode="mcp")
        ctx = self.ctx_factory(tracer, self.llm)
        ctx.rekap_ids = self.rekap_ids
        if "meeting_id" in args:
            ctx.meeting_id = meeting_id
        # None would mean "no check" in guardrails.write_intent; for MCP an absent request must fail.
        ctx.user_message = (user_request or "") if name in approvals.WRITE_TOOLS else None
        tracer.log("run_start", pesan_user=(user_request or f"mcp:{name}")[:500], model=self.llm.model,
                   tools=[name], sumber="mcp")
        result = execute_tool(name, json.dumps(args), ctx)
        tracer.log("run_end", status=result.get("status"), tools_dipanggil=[name], rekap_id=result.get("rekap_id"),
                   approval_id=result.get("approval_id"), **tracer.totals())
        if result.get("rekap_id") and "meeting_id" in args:
            self.rekap_ids[meeting_id] = result["rekap_id"]
        return result


def _workflow(self, args: Dict[str, Any], user_request: Optional[str]) -> Dict:
        try:
            a = WorkflowArgs.model_validate(args)
        except Exception as exc:
            return {"status": "invalid_args", "pesan": f"Argumen tidak valid: {str(exc)[:300]}"}
        for tool, wanted in (("buat_task", a.aksi == "task"), ("kirim_email_rekap", a.kirim)):
            if wanted and not guardrails.write_intent(tool, user_request or ""):
                return {"status": "rejected", "pesan": f"Aksi ini butuh '{WRITE_FIELD}' berisi permintaan user yang memintanya."}
        try:
            res = run_workflow(a.meeting_id, a.aksi, a.formats, a.kirim, ctx_factory=self.ctx_factory, llm=self.llm)
        except ValueError as exc:
            return {"status": "invalid_args", "pesan": str(exc)}
        return {"status": res.status, "jawaban": res.answer, "trace_id": res.trace_id, "rekap_id": res.rekap_id,
                "approval_id": res.approval_id, "tools_dipanggil": res.tools_called}


McpSession._workflow = _workflow


def build_server(session: Optional[McpSession] = None):
    """Wire the shared registry into an MCP server (SDK imported here so tests and the app run without it)."""
    from mcp import types
    from mcp.server import Server

    session = session or McpSession()
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list() -> List[types.Tool]:
        return [types.Tool(**s) for s in list_specs()]

    @server.call_tool()
    async def _call(name: str, arguments: Optional[Dict[str, Any]]) -> List[types.TextContent]:
        result = await asyncio.to_thread(session.call, name, arguments)
        meta = {k: v for k, v in result.items() if k != "_transkrip"}
        blocks = [types.TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))]
        if result.get("_transkrip"):
            blocks.append(types.TextContent(type="text", text=guardrails.wrap_transcript(result["_transkrip"])))
        return blocks

    return server


async def _serve_stdio() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_serve_stdio())
