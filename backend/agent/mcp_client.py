"""
MCP client for the agent loop and the workflow (AGENT_TOOL_TRANSPORT=mcp).

The loop discovers its tools with MCP `tools/list` and runs each call as MCP `tools/call`, against the same
server code external clients use (agent.mcp_server). The transport is in-process memory streams: the app and the
tool server share one trust boundary, and the run's tracer, token totals and state stay in one place. An external
client (Claude Desktop, an IDE) reaches the same server over stdio instead.

Everything the guardrails need travels with the call: `run_id` points the server to this run's ToolContext (active
meeting, user message, rekaps, injection flag, tracer), so validation, meeting scope, write intent and tracing behave
as in the local path. The LLM never sees `run_id` or `iterasi`; they are removed from the specs it receives.

With AGENT_TOOL_TRANSPORT=local (default) no MCP bridge is started and tools are called directly.
"""
from __future__ import annotations

import asyncio
import copy
import json
import threading
import time
from typing import Any, Dict, List, Optional

from agent import approvals, config
from agent.tools import TOOLS, ToolContext, execute_tool, tool_specs

CALL_TIMEOUT_S = 180


class McpBridge:
    """One MCP client/server pair on a background event loop, shared by all runs of the process."""

    def __init__(self) -> None:
        from agent.mcp_server import McpSession
        self.session = McpSession()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._client = None
        self._tools: Optional[List[Dict]] = None
        threading.Thread(target=self._run, name="mcp-bridge", daemon=True).start()
        if not self._ready.wait(30) or self._error is not None:
            raise RuntimeError(f"MCP bridge gagal start: {self._error!r}")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        from mcp.shared.memory import create_connected_server_and_client_session
        from agent.mcp_server import build_server
        try:
            async with create_connected_server_and_client_session(build_server(self.session)) as client:
                self._client = client
                self._ready.set()
                await asyncio.Event().wait()   # serve until the process exits
        except BaseException as exc:   # surfaced to the thread that started the bridge
            self._error = exc
            self._ready.set()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(CALL_TIMEOUT_S)

    def list_tools(self) -> List[Dict]:
        if self._tools is None:
            self._tools = [t.model_dump() for t in self._submit(self._client.list_tools()).tools]
        return self._tools

    def call(self, name: str, arguments: Dict[str, Any]) -> List[str]:
        res = self._submit(self._client.call_tool(name, arguments))
        return [b.text for b in res.content if getattr(b, "type", "") == "text"]


_bridge: Optional[McpBridge] = None
_lock = threading.Lock()


def get_bridge() -> McpBridge:
    global _bridge
    with _lock:
        if _bridge is None:
            _bridge = McpBridge()
        return _bridge


def using_mcp() -> bool:
    return config.TOOL_TRANSPORT == "mcp"


def _llm_spec(tool: Dict) -> Dict:
    """MCP tool definition -> the function spec the LLM gets, without host-only fields or the host note."""
    from agent.mcp_server import HOST_FIELDS, WRITE_FIELD, _WRITE_NOTE
    hidden = set(HOST_FIELDS) | {WRITE_FIELD}
    schema = copy.deepcopy(tool["inputSchema"])
    for key in hidden:
        schema.get("properties", {}).pop(key, None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r not in hidden]
        if not schema["required"]:
            del schema["required"]
    return {"type": "function", "function": {"name": tool["name"],
                                             "description": tool["description"].replace(_WRITE_NOTE, ""),
                                             "parameters": schema}}


def agent_specs(names: Optional[List[str]] = None) -> List[Dict]:
    """Tool specs for the LLM: discovered over MCP, or the local registry. Only the agent's own tools
    (not jalankan_workflow, a fixed pipeline offered to external clients)."""
    if not using_mcp():
        return tool_specs(names)
    found = {t["name"]: t for t in get_bridge().list_tools()}
    return [_llm_spec(found[n]) for n in TOOLS if n in found and (names is None or n in names)]


def _parse(blocks: List[str]) -> Dict:
    result = json.loads(blocks[0])
    if len(blocks) > 1:
        text, head, tail = blocks[1], "<transkrip_data>\n", "\n</transkrip_data>"
        result["_transkrip"] = text[len(head):-len(tail)] if text.startswith(head) and text.endswith(tail) else text
    return result


def dispatch(name: str, raw_args: str, ctx: ToolContext, iterasi: Optional[int] = None) -> Dict:
    """Run one tool call for the loop or the workflow: through MCP when configured, else directly.
    Same contract as execute_tool: never raises, failures are a result with an error status."""
    if not using_mcp():
        return execute_tool(name, raw_args, ctx, iterasi=iterasi)
    try:
        args = json.loads(raw_args or "{}")
        if not isinstance(args, dict) or name not in TOOLS:
            raise ValueError   # bad JSON or unknown tool: the local path produces the standard failure result
    except ValueError:
        return execute_tool(name, raw_args, ctx, iterasi=iterasi)
    from agent.mcp_server import WRITE_FIELD
    bridge = get_bridge()
    args["run_id"] = bridge.session.register_run(ctx)
    if iterasi is not None:
        args["iterasi"] = iterasi
    if name in approvals.WRITE_TOOLS:
        args[WRITE_FIELD] = ctx.user_message or ""   # satisfies the published schema; the run's ctx is what is checked
    t0 = time.perf_counter()
    try:
        result = _parse(bridge.call(name, args))
    except Exception as exc:
        result = {"status": "error", "pesan": f"Tool gagal lewat MCP: {type(exc).__name__}: {str(exc)[:200]}"}
    ctx.tracer.log("mcp_call", tool=name, iterasi=iterasi, status=result.get("status"),
                   latency_ms=round((time.perf_counter() - t0) * 1000, 1))
    return result
