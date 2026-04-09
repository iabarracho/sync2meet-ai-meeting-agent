"""Participant directory and SMTP email helpers for task assignment notifications."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _norm(name: str) -> str:
    return name.strip().casefold()


# In-memory participant directory (name -> email). Edit to match your team.
PARTICIPANTS: list[dict[str, str]] = [
    {"name": "Alice", "email": "alice@email.com"},
    {"name": "Bob", "email": "bob@email.com"},
]

_NAME_TO_EMAIL: dict[str, str] = {_norm(p["name"]): p["email"] for p in PARTICIPANTS}


def get_email_by_name(name: str) -> str | None:
    """Resolve email for a display name; None if unknown or empty."""
    if not name or not str(name).strip():
        return None
    return _NAME_TO_EMAIL.get(_norm(name))


def send_email(to_email: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP. Uses env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM."""
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        logger.warning("SMTP_HOST not set; skipping email to %s", to_email)
        return

    port = int(os.getenv("SMTP_PORT", "587"))
    user = (os.getenv("SMTP_USER") or "").strip() or None
    password = os.getenv("SMTP_PASSWORD") or None
    from_addr = (os.getenv("SMTP_FROM") or user or "noreply@localhost").strip()

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email

    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        if user is not None and password is not None:
            server.login(user, password)
        server.send_message(msg)


def _participant_set(participants: list[str]) -> set[str]:
    return {_norm(p) for p in participants if p and str(p).strip()}


def _short_summary(summary: str, max_chars: int = 900) -> str:
    s = summary.strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def resolve_assignee_email(
    assignee: str,
    *,
    email_overrides: dict[str, str] | None = None,
) -> str | None:
    """Resolve email: request overrides first (normalized name), then in-memory PARTICIPANTS."""
    if not assignee or not str(assignee).strip():
        return None
    key = _norm(assignee)
    if email_overrides:
        addr = (email_overrides.get(key) or "").strip()
        if addr:
            return addr
    return get_email_by_name(assignee)


def notify_assignees_for_tasks(
    *,
    meeting_title: str,
    meeting_date: str | None,
    summary: str,
    action_items: list,  # list of objects with .task, .assignee, .deadline
    notion_page_url: str | None,
    participants: list[str],
    email_overrides: dict[str, str] | None = None,
) -> None:
    """
    For each action item: if assignee is set, matches a participant name, and has an email, send one email.
    email_overrides maps normalized participant name -> email from the API request (takes priority over PARTICIPANTS).
    Does not raise on SMTP errors; logs warnings instead.
    """
    if not participants:
        return

    allowed = _participant_set(participants)
    if not allowed:
        return

    short = _short_summary(summary)

    for item in action_items:
        assignee = getattr(item, "assignee", None)
        if not assignee or not str(assignee).strip():
            continue
        if _norm(assignee) not in allowed:
            continue

        to_email = resolve_assignee_email(assignee, email_overrides=email_overrides)
        if not to_email:
            logger.warning("No email for assignee %r (add email for this name in the request or PARTICIPANTS)", assignee)
            continue

        task = getattr(item, "task", "") or ""
        deadline = getattr(item, "deadline", None)
        lines = [
            f"You have been assigned a follow-up from the meeting: {meeting_title}",
            "",
            "Task:",
            task,
            "",
        ]
        if deadline:
            lines.extend(["Deadline:", str(deadline), ""])
        lines.extend(
            [
                "Meeting summary (excerpt):",
                short,
                "",
            ]
        )
        if notion_page_url:
            lines.extend(["Notion notes:", notion_page_url, ""])

        body = "\n".join(lines)
        subject = f"[Meeting action] {meeting_title}"[:200]

        try:
            send_email(to_email, subject, body)
            logger.info("Sent task email to %s (%s)", to_email, assignee)
        except OSError as e:
            logger.warning("Failed to send email to %s: %s", to_email, e)


def notify_participants_meeting_report(
    *,
    meeting_title: str,
    meeting_date: str | None,
    summary: str,
    notion_page_url: str | None,
    participants: list[str],
    recipient_emails: list[str] | None = None,
    email_overrides: dict[str, str] | None = None,
) -> None:
    """
    Send a final meeting report email (with Notion link) to all provided participants with emails.
    Does not raise on SMTP errors; logs warnings instead.
    """
    if not participants and not recipient_emails:
        return

    sent_to: set[str] = set()
    short = _short_summary(summary)
    for name in participants:
        person = (name or "").strip()
        if not person:
            continue
        to_email = resolve_assignee_email(person, email_overrides=email_overrides)
        if not to_email:
            logger.warning("No email for participant %r (add email in request or PARTICIPANTS)", person)
            continue
        email_key = to_email.casefold()
        if email_key in sent_to:
            continue
        sent_to.add(email_key)

        lines = [
            f"Meeting report: {meeting_title}",
            "",
            f"Participant: {person}",
            "",
        ]
        if meeting_date:
            lines.extend([f"Date: {meeting_date}", ""])
        lines.extend(["Summary (excerpt):", short, ""])
        if notion_page_url:
            lines.extend(["Notion page:", notion_page_url, ""])

        body = "\n".join(lines)
        subject = f"[Meeting report] {meeting_title}"[:200]
        try:
            send_email(to_email, subject, body)
            logger.info("Sent meeting report email to %s (%s)", to_email, person)
        except OSError as e:
            logger.warning("Failed to send meeting report to %s: %s", to_email, e)

    # Also send to any direct emails provided in the request, even without a name.
    for addr in recipient_emails or []:
        to_email = (addr or "").strip()
        if not to_email:
            continue
        email_key = to_email.casefold()
        if email_key in sent_to:
            continue
        sent_to.add(email_key)

        lines = [f"Meeting report: {meeting_title}", ""]
        if meeting_date:
            lines.extend([f"Date: {meeting_date}", ""])
        lines.extend(["Summary (excerpt):", short, ""])
        if notion_page_url:
            lines.extend(["Notion page:", notion_page_url, ""])

        body = "\n".join(lines)
        subject = f"[Meeting report] {meeting_title}"[:200]
        try:
            send_email(to_email, subject, body)
            logger.info("Sent meeting report email to %s", to_email)
        except OSError as e:
            logger.warning("Failed to send meeting report to %s: %s", to_email, e)
