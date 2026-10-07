"""
Agent settings. Everything can be overridden with environment variables;
credentials are only ever read from the environment, never from code.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _env(name: str, default: str) -> str:
    """Environment value, or the default when unset or empty."""
    return os.getenv(name) or default


AGENT_MODEL: str = _env("AGENT_MODEL", "openai/gpt-oss-20b")
# gpt-oss models accept reasoning_effort = low | medium | high on Groq.
AGENT_REASONING_EFFORT: str = _env("AGENT_REASONING_EFFORT", "low")
AGENT_TEMPERATURE: float = float(_env("AGENT_TEMPERATURE", "0.2"))
AGENT_MAX_COMPLETION_TOKENS: int = int(_env("AGENT_MAX_COMPLETION_TOKENS", "2048"))

# Extraction call inside ekstrak_poin_meeting. "low" with explicit criteria in the
# prompt was stable in testing; "medium" used about 10x more output tokens, hit the
# free-tier TPM limit and sometimes ran out of budget before the JSON (docs/02_mvp.md).
EXTRACT_REASONING_EFFORT: str = _env("EXTRACT_REASONING_EFFORT", "low")
EXTRACT_TEMPERATURE: float = float(_env("EXTRACT_TEMPERATURE", "0"))
EXTRACT_MAX_COMPLETION_TOKENS: int = int(_env("EXTRACT_MAX_COMPLETION_TOKENS", "2048"))

MAX_ITERATIONS: int = int(_env("AGENT_MAX_ITERATIONS", "8"))
MAX_CONSECUTIVE_TOOL_ERRORS: int = int(_env("AGENT_MAX_TOOL_ERRORS", "2"))
MAX_LLM_RETRIES: int = 1          # retries for a failed LLM request inside one iteration
MAX_USER_MESSAGE_CHARS: int = 2000

# Retrieval settings used by the tools. Fixed in code so the LLM cannot weaken them.
RETRIEVAL_MODE = "hybrid"
RETRIEVAL_FUSION = "rrf"
RETRIEVAL_MIN_SCORE = 0.40        # tuned in W6 on the sample eval set
TOOL_CHUNK_MAX_CHARS = 600        # chunk text shown to the LLM per hit
EXTRACT_MAX_CHUNKS = 12           # chunks per extraction call (keeps one call small)
EXTRACT_MAX_CALLS = 3             # long meetings: up to this many calls, most relevant chunks first

# USD per 1M tokens (input, output).
# Source: https://console.groq.com/docs/model/openai/gpt-oss-20b (checked 2026-10-05).
# Models without an entry get cost = null in the trace instead of a guess.
PRICES_PER_MTOK = {
    "openai/gpt-oss-20b": (0.075, 0.30),
}

# Times shown to people (reports, emails, job table) use this fixed offset. Indonesia has no DST,
# so a fixed offset is exact and needs no tz database. Stored data and traces stay in UTC.
LOCAL_TZ_LABEL: str = _env("REPORT_TZ_LABEL", "WIB")
LOCAL_TZ = timezone(timedelta(hours=float(_env("REPORT_TZ_OFFSET_HOURS", "7"))))

DATA_DIR = Path("data")
TRACE_DIR = DATA_DIR / "traces"
REKAP_DIR = DATA_DIR / "agent" / "rekap"
AGENT_DB = DATA_DIR / "agent" / "agent.db"          # approvals and tasks (SQLite, stdlib)
REPORT_DIR = DATA_DIR / "agent" / "laporan"         # PDF reports
OUTBOX_DIR = DATA_DIR / "agent" / "outbox"          # .eml files written in dry-run mode
SOURCES_FILE = DATA_DIR / "sources.json"            # meeting_id -> YouTube title and URL
JOBS_DB = DATA_DIR / "jobs.db"                      # transcription jobs (workflow, not agent)
# Extensions stripped from the uploaded file name to get the report title.
MEDIA_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac",
                  ".txt", ".json"}
# Link to the UI, written into the job notification email.
UI_URL: str = _env("UI_URL", "http://localhost:8503")

# PDF font: Liberation Sans (Arial-compatible, installed by Dockerfile.agent). DejaVu from the
# base image is the fallback; with neither, core fonts are used and text is reduced to latin-1.
PDF_FONT_DIR = Path(_env("PDF_FONT_DIR", "/usr/share/fonts/truetype/liberation"))

# Email delivery. dry_run writes an .eml file to OUTBOX_DIR; smtp sends for real.
# The recipient is never an LLM argument: it is REPORT_EMAIL_TO, read here.
# Gmail SMTP: smtp.gmail.com, 465 (SSL) or 587 (TLS), login with an App Password.
# Sources: https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app
#          https://support.google.com/accounts/answer/185833
EMAIL_MODE: str = _env("EMAIL_MODE", "dry_run")
SMTP_HOST: str = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(_env("SMTP_PORT", "465"))
SMTP_TIMEOUT_S: int = 30
MAX_TASK_ITEMS: int = 20


def local_time(value, with_seconds: bool = False) -> str:
    """datetime or ISO string (UTC if naive) -> '2026-10-06 09:56 WIB'."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    fmt = "%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M"
    return f"{value.astimezone(LOCAL_TZ):{fmt}} {LOCAL_TZ_LABEL}"


def estimate_cost(model: str, input_tokens, output_tokens):
    price = PRICES_PER_MTOK.get(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1_000_000, 8)
