"""
Email delivery shared by the agent (approved report email) and the
transcription workflow (job notification).

The only recipient is REPORT_EMAIL_TO from the environment; no caller passes
an address. EMAIL_MODE=dry_run writes an .eml file to data/agent/outbox,
EMAIL_MODE=smtp sends with smtplib.

Gmail SMTP: smtp.gmail.com, 465 (SSL) or 587 (TLS), App Password login.
  https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app
  https://support.google.com/accounts/answer/185833
smtplib: https://docs.python.org/3/library/smtplib.html
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Dict

from agent import config

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(Exception):
    """Email cannot be prepared or sent (configuration missing or SMTP failure)."""


def report_recipient() -> str:
    to = (os.getenv("REPORT_EMAIL_TO") or "").strip()
    if not _EMAIL_RE.match(to):
        raise MailError("REPORT_EMAIL_TO belum diset atau bukan alamat email yang valid.")
    return to


def sender_address() -> str:
    """From header: display name (MAIL_FROM_NAME, default "MeetRecall AI") plus the SMTP login address.
    Gmail only sends as the authenticated address, so only the display name is configurable."""
    address = os.getenv("SMTP_USER") or "meetrecall-agent@localhost"
    name = (os.getenv("MAIL_FROM_NAME") or "MeetRecall AI").strip()
    return formataddr((name, address))


def mask_email(address: str) -> str:
    local, _, domain = (address or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def deliver(msg: EmailMessage, outbox_name: str) -> Dict:
    """Send or write the message according to EMAIL_MODE. Never logs credentials."""
    mode = config.EMAIL_MODE
    if mode == "dry_run":
        out = Path(config.OUTBOX_DIR) / f"{outbox_name}.eml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(msg.as_bytes())
        return {"mode": "dry_run", "path": out.as_posix()}
    if mode != "smtp":
        raise MailError(f"EMAIL_MODE tidak dikenal: {mode}")
    user = os.getenv("SMTP_USER") or ""
    password = os.getenv("SMTP_APP_PASSWORD") or ""
    if not (user and password):
        raise MailError("EMAIL_MODE=smtp tetapi SMTP_USER atau SMTP_APP_PASSWORD belum diset.")
    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context,
                                  timeout=config.SMTP_TIMEOUT_S)
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_S)
        server.starttls(context=context)
    with server:
        server.login(user, password)
        server.send_message(msg)
    return {"mode": "smtp", "host": config.SMTP_HOST}
