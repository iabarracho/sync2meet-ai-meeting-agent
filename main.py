import io
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from notifications import (
    _norm as _participant_name_key,
    notify_assignees_for_tasks,
    notify_participants_meeting_report,
)

logger = logging.getLogger(__name__)

# Same folder as main.py — works no matter which terminal starts uvicorn
load_dotenv(Path(__file__).resolve().parent / ".env")

app = FastAPI(title="AI Meeting Agent")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

SYSTEM_PROMPT = """You extract structured business insights from meeting transcripts.

Output: exactly one JSON object (no markdown code fences, no text before or after).

Grounding (critical): Only include facts that are clearly stated or clearly implied in the transcript. If something is unclear, missing, or ambiguous, do not guess, infer, or invent details—omit it or say so briefly in the summary (e.g. that owners or dates were not specified). Never fabricate names, numbers, dates, commitments, or risks. Use empty arrays when there is nothing grounded to report.

Schema:
- "meeting_title" (string): A short page title (max ~100 characters) reflecting what was mostly discussed—the dominant theme or purpose. Base it only on the transcript; no generic titles like "Meeting notes".
- "meeting_date" (string or null): ISO date YYYY-MM-DD only if the transcript clearly states when the meeting happened or a clear calendar date; otherwise null.
- "summary" (string): Clear, concise overview using bullet points. Start each line with "• " or "- ". Cover only what the transcript actually supports; note gaps if the content is thin. Professional, scannable tone.
- "action_items" (array of objects): End-of-meeting style task list. Each object MUST have:
  - "task" (string): Must be a clear, actionable task (verb + object/outcome where possible). Not vague or generic—avoid placeholders like "follow up", "discuss more", "look into it" unless the transcript names the specific deliverable; prefer concrete actions grounded in what was said (e.g. "Send the Q2 budget spreadsheet to Finance" not "Handle budget stuff").
  - "assignee" (string or null): Who is responsible—only if a person or role is clearly stated; otherwise null.
  - "deadline" (string or null): When it is due—only if a date, day, or timeframe is clearly stated; otherwise null.
  Include every actionable follow-up that is grounded in the transcript; do not invent owners or deadlines. Omit items that cannot be phrased as a specific action from the text.
- "decisions" (array of strings): Only decisions or commitments clearly expressed in the text. One clear line per item.
- "risks" (array of strings): Only risks or open issues actually raised; one line per item.

Rules: Be structured and business-oriented; avoid fluff; use empty arrays when a section has nothing relevant or nothing grounded.
Language: English only for every field and list item, regardless of transcript language."""


class ParticipantEntry(BaseModel):
    name: str = Field(default="", description="Name as it should match the assignee in the transcript")
    email: str = Field(
        default="",
        description="Email for task notifications for this person (optional if using server PARTICIPANTS only)",
    )


def _names_and_email_overrides(
    entries: list[ParticipantEntry],
) -> tuple[list[str], dict[str, str], list[str]]:
    """Build participant names, per-request name->email map, and raw recipient emails."""
    names: list[str] = []
    overrides: dict[str, str] = {}
    recipient_emails: list[str] = []
    for p in entries:
        n = (p.name or "").strip()
        em = (p.email or "").strip()
        if n:
            names.append(n)
        if em:
            recipient_emails.append(em)
            if n:
                overrides[_participant_name_key(n)] = em
    return names, overrides, recipient_emails


class ProcessMeetingRequest(BaseModel):
    transcript: str = Field(
        ...,
        description="Meeting transcript text. For audio, transcribe first or use /process-meeting-audio.",
    )
    meeting_date: str | None = Field(
        None,
        description="Optional meeting date YYYY-MM-DD if known and not in the transcript.",
    )
    participants: list[ParticipantEntry] = Field(
        default_factory=list,
        description="People in the meeting: names (for matching assignees) and optional emails for task notifications.",
    )

    @field_validator("participants", mode="before")
    @classmethod
    def _coerce_participants(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return v
        out: list[dict[str, str]] = []
        for item in v:
            if isinstance(item, str):
                out.append({"name": item, "email": ""})
            elif isinstance(item, dict):
                out.append(
                    {
                        "name": str(item.get("name", "") or ""),
                        "email": str(item.get("email", "") or ""),
                    }
                )
        return out

    @field_validator("meeting_date")
    @classmethod
    def validate_meeting_date(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        date.fromisoformat(v)
        return v


class ActionItem(BaseModel):
    task: str = Field(
        ...,
        description="Clear, actionable task (not vague or generic); verb + concrete outcome when possible",
    )
    assignee: str | None = Field(
        None,
        description="Who owns it, only if clearly stated in the transcript",
    )
    deadline: str | None = Field(
        None,
        description="Due date or timeframe, only if clearly stated",
    )


class ProcessMeetingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meeting_title: str = Field(..., description="Title aligned with the main discussion theme")
    meeting_date: str | None = Field(
        None,
        description="Date used (YYYY-MM-DD): from request or transcript",
    )
    summary: str = Field(..., description="Meeting summary")
    action_items: list[ActionItem] = Field(
        ...,
        description="Tasks: what, who, deadline",
    )
    decisions: list[str]
    risks: list[str]
    notion_page_url: str | None = Field(
        None,
        description="Created Notion page URL (always set on success; Notion is required)",
    )


def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "OPENAI_API_KEY is not set. Add it to a .env file in the project folder "
                "(OPENAI_API_KEY=sk-...) or set the environment variable in the same terminal "
                "that runs uvicorn."
            ),
        )
    return OpenAI(api_key=api_key)


def _transcribe_audio(data: bytes, filename: str) -> str:
    """Transcribe audio with OpenAI Whisper (uses OPENAI_API_KEY)."""
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    client = _openai_client()
    buf = io.BytesIO(data)
    buf.name = filename or "audio.mp3"
    try:
        transcription = client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=buf,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Whisper transcription failed: {e!s}",
        ) from e
    text = getattr(transcription, "text", None) or ""
    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=502,
            detail="Transcription returned empty text. Try another format or file.",
        )
    return text


def _notion_token() -> str | None:
    return os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN")


def _notion_parent_page_id() -> str | None:
    return os.getenv("NOTION_PARENT_PAGE_ID")


def _require_notion_config() -> str:
    """Notion parent page id; raises if Notion is not fully configured (required for every run)."""
    token = _notion_token()
    parent_raw = _notion_parent_page_id()
    parent_id = (parent_raw or "").strip()
    if not token or not parent_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "Notion is required: set NOTION_API_KEY (or NOTION_TOKEN) and NOTION_PARENT_PAGE_ID "
                "in your .env. Create an integration at notion.so/my-integrations, share the parent "
                "page with it, and paste that page's ID."
            ),
        )
    return parent_id


def _truncate(text: str, max_len: int = 2000) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _rich_text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": _truncate(content)}}]


def _block_paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _block_heading(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text)},
    }


def _block_bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _block_to_do(text: str, *, checked: bool = False) -> dict[str, Any]:
    """Notion checkbox / to-do block."""
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "rich_text": _rich_text(text),
            "checked": checked,
        },
    }


def _summary_bullets(summary: str) -> list[str]:
    lines = [ln.strip() for ln in summary.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln:
            continue
        out.append(re.sub(r"^[•\-\*]\s*", "", ln).strip() or ln)
    return out if out else [_truncate(summary)]


def _notion_page_title(meeting_title: str, meeting_date: str | None) -> str:
    base = _truncate(meeting_title, 200)
    if meeting_date:
        return _truncate(f"{base} — {meeting_date}", 200)
    return base


def _build_notion_children(
    meeting_date: str | None,
    summary: str,
    action_items: list[ActionItem],
    decisions: list[str],
    risks: list[str],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    if meeting_date:
        blocks.append(_block_paragraph(f"Meeting date: {meeting_date}"))
    else:
        blocks.append(
            _block_paragraph(
                "Meeting date: not stated in the transcript (you can send meeting_date in the request)."
            )
        )

    blocks.append(_block_heading("Summary"))
    for line in _summary_bullets(summary):
        blocks.append(_block_bullet(line))

    blocks.append(_block_heading("Tasks"))
    if not action_items:
        blocks.append(_block_paragraph("(No tasks identified from the text.)"))
    else:
        for it in action_items:
            parts = [it.task]
            extra: list[str] = []
            if it.assignee:
                extra.append(f"Assignee: {it.assignee}")
            if it.deadline:
                extra.append(f"Deadline: {it.deadline}")
            if extra:
                parts.append("(" + " · ".join(extra) + ")")
            blocks.append(_block_to_do(" ".join(parts), checked=False))

    blocks.append(_block_heading("Decisions"))
    if not decisions:
        blocks.append(_block_bullet("(No explicit decisions identified.)"))
    else:
        for d in decisions:
            blocks.append(_block_bullet(d))

    blocks.append(_block_heading("Risks / open issues"))
    if not risks:
        blocks.append(_block_bullet("(No explicit risks identified.)"))
    else:
        for r in risks:
            blocks.append(_block_bullet(r))

    return blocks


def _create_notion_page(
    parent_page_id: str,
    title: str,
    children: list[dict[str, Any]],
) -> str:
    token = _notion_token()
    if not token:
        raise HTTPException(status_code=500, detail="NOTION_API_KEY is not set")

    # Notion allows up to 100 blocks per create; chunk if needed
    first_batch = children[:100]
    rest = children[100:]

    body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id.strip()},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": _truncate(title, 200)}}],
            },
        },
        "children": first_batch,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{NOTION_API}/pages", headers=headers, json=body)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Notion create page failed: {r.status_code} {r.text}",
            )
        data = r.json()
        page_id = data.get("id")
        if not page_id:
            raise HTTPException(
                status_code=502,
                detail="Notion create page returned no page id",
            )
        url = data.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"

        # Append remaining blocks
        while rest:
            batch = rest[:100]
            rest = rest[100:]
            patch = client.patch(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=headers,
                json={"children": batch},
            )
            if patch.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Notion append blocks failed: {patch.status_code} {patch.text}",
                )

    return url


def _run_analysis(
    transcript: str,
    request_meeting_date: str | None,
    participant_entries: list[ParticipantEntry] | None = None,
) -> ProcessMeetingResponse:
    """Run transcript analysis: LLM + Notion page (required) + optional task emails."""
    notion_parent_id = _require_notion_config()

    client = _openai_client()
    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n\n{transcript}"},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {e!s}") from e

    raw = completion.choices[0].message.content
    if not raw:
        raise HTTPException(status_code=502, detail="Empty model response")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {e!s}") from e

    # Defensive normalization: models occasionally return equivalent shapes
    # (e.g. summary as list instead of string). Coerce to schema-compatible types.
    if isinstance(data.get("summary"), list):
        lines = [str(x).strip() for x in data["summary"] if str(x).strip()]
        data["summary"] = "\n".join(lines)
    if isinstance(data.get("decisions"), str):
        data["decisions"] = [data["decisions"]]
    if isinstance(data.get("risks"), str):
        data["risks"] = [data["risks"]]

    resolved_date = request_meeting_date or data.get("meeting_date")
    if resolved_date is not None and resolved_date == "":
        resolved_date = None
    if isinstance(resolved_date, str):
        try:
            date.fromisoformat(resolved_date)
        except ValueError:
            resolved_date = None

    data["meeting_date"] = resolved_date

    try:
        result = ProcessMeetingResponse.model_validate(
            {
                **data,
                "notion_page_url": None,
            }
        )
    except ValidationError as e:
        raise HTTPException(status_code=502, detail=f"Invalid model output: {e!s}") from e

    title = _notion_page_title(result.meeting_title, result.meeting_date)
    children = _build_notion_children(
        result.meeting_date,
        result.summary,
        result.action_items,
        result.decisions,
        result.risks,
    )
    notion_url = _create_notion_page(notion_parent_id, title, children)

    result = result.model_copy(update={"notion_page_url": notion_url})

    entries = participant_entries or []
    names, email_overrides, recipient_emails = _names_and_email_overrides(entries)
    if names:
        try:
            notify_assignees_for_tasks(
                meeting_title=result.meeting_title,
                meeting_date=result.meeting_date,
                summary=result.summary,
                action_items=result.action_items,
                notion_page_url=result.notion_page_url,
                participants=names,
                email_overrides=email_overrides or None,
            )
        except Exception:
            logger.exception("Task notification emails failed")
        try:
            notify_participants_meeting_report(
                meeting_title=result.meeting_title,
                meeting_date=result.meeting_date,
                summary=result.summary,
                notion_page_url=result.notion_page_url,
                participants=names,
                recipient_emails=recipient_emails,
                email_overrides=email_overrides or None,
            )
        except Exception:
            logger.exception("Meeting report emails failed")

    return result


@app.post("/process-meeting", response_model=ProcessMeetingResponse)
def process_meeting(body: ProcessMeetingRequest) -> ProcessMeetingResponse:
    return _run_analysis(body.transcript, body.meeting_date, body.participants)


@app.post("/process-meeting-audio", response_model=ProcessMeetingResponse)
async def process_meeting_audio(
    audio: Annotated[
        UploadFile,
        File(description="Meeting audio (e.g. mp3, mp4, wav, m4a)"),
    ],
    meeting_date: Annotated[
        str | None,
        Form(description="Optional meeting date YYYY-MM-DD"),
    ] = None,
    participants: Annotated[
        str,
        Form(
            description='JSON array: names only ["A","B"] or objects [{"name":"...","email":"..."},...]',
        ),
    ] = "[]",
) -> ProcessMeetingResponse:
    """Transcribe audio with OpenAI Whisper, then run the same analysis as /process-meeting."""
    contents = await audio.read()
    filename = audio.filename or "audio.mp3"
    transcript = _transcribe_audio(contents, filename)
    if meeting_date is not None and meeting_date != "":
        try:
            date.fromisoformat(meeting_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="meeting_date must be YYYY-MM-DD.",
            ) from None
    else:
        meeting_date = None

    try:
        raw_list = json.loads(participants or "[]")
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"participants must be valid JSON: {e!s}",
        ) from e
    if not isinstance(raw_list, list):
        raise HTTPException(status_code=422, detail="participants must be a JSON array.")

    parsed_entries: list[ParticipantEntry] = []
    for item in raw_list:
        if isinstance(item, str):
            parsed_entries.append(ParticipantEntry(name=item, email=""))
        elif isinstance(item, dict):
            parsed_entries.append(
                ParticipantEntry(
                    name=str(item.get("name", "") or ""),
                    email=str(item.get("email", "") or ""),
                )
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="Each participant must be a string (name) or an object with name and optional email.",
            )

    return _run_analysis(transcript, meeting_date, parsed_entries)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
