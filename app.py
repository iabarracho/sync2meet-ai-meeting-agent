"""
Streamlit UI for the AI Meeting Agent.

From the project folder:  streamlit run app.py
"""

from __future__ import annotations

import html
import json
from datetime import date

import httpx
import pandas as pd
import streamlit as st

DEFAULT_API = "http://127.0.0.1:8000"

# Simple professional styling (typography, spacing, cards)
_UI_CSS = """
<style>
    .block-container {
        max-width: 52rem;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }
    div.app-hero {
        margin-bottom: 1.75rem;
        padding-bottom: 1.25rem;
        border-bottom: 1px solid #e2e8f0;
    }
    div.app-hero h1 {
        font-size: 1.65rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em;
        color: #0f172a !important;
        margin-bottom: 0.35rem !important;
    }
    div.app-hero p {
        color: #64748b;
        font-size: 0.95rem;
        line-height: 1.5;
        margin: 0;
    }
    h2.step-heading {
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #475569 !important;
        margin-top: 1.5rem !important;
        margin-bottom: 0.5rem !important;
    }
    div.result-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem 1.15rem;
        margin: 0.75rem 0;
    }
    div.result-box h4 {
        margin: 0 0 0.5rem 0;
        font-size: 0.85rem;
        color: #334155;
        font-weight: 600;
    }
    [data-testid="stSidebar"] {
        background: #f8fafc;
    }
</style>
"""


def main() -> None:
    st.set_page_config(
        page_title="AI Meeting Agent",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    st.markdown(_UI_CSS, unsafe_allow_html=True)

    st.markdown(
        """
        <div class="app-hero">
            <h1>AI Meeting Agent</h1>
            <p>Upload your meeting audio. The server transcribes it (Whisper), analyzes the content, and creates a Notion page with summary, tasks, and risks.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown("### Server connection")
        api_base = st.text_input(
            "API base URL",
            value=DEFAULT_API,
            help="Where the FastAPI app runs (uvicorn). Usually http://127.0.0.1:8010",
            label_visibility="visible",
        )
        st.markdown("---")
        st.markdown("**Before you start**")
        st.markdown(
            """
1. In a terminal: `uvicorn main:app --host 127.0.0.1 --port <port>`  
2. Configure `.env` with OpenAI and Notion  
3. Then click **Process meeting** on this page  
            """
        )
        with st.expander("What happens when I process?"):
            st.markdown(
                """
1. Audio is sent to the API  
2. **Transcription** (OpenAI Whisper)  
3. **Analysis** (summary, tasks, decisions, risks)  
4. **Notion page** created (required on the server)  
5. **Task emails** if SMTP is set and participants have emails  
                """
            )

    st.markdown('<h2 class="step-heading">Step 1 · Meeting audio</h2>', unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "MP3, MP4 or M4A file",
        type=["mp3", "mp4", "m4a"],
        help="Recording of the meeting to analyze",
        label_visibility="collapsed",
    )
    if uploaded:
        st.caption(f"File: **{uploaded.name}**")

    st.markdown('<h2 class="step-heading">Step 2 · Participants (optional)</h2>', unsafe_allow_html=True)
    st.caption(
        "One row per person. **Name** should match how people are referred to in the recording. "
        "**Email** is used to send each person their assigned tasks."
    )
    df = st.data_editor(
        pd.DataFrame([{"Name": "", "Email": ""}]),
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Email": st.column_config.TextColumn("Email", width="medium"),
        },
        key="participants_table",
    )

    st.markdown('<h2 class="step-heading">Step 3 · Meeting date (optional)</h2>', unsafe_allow_html=True)
    meeting_date = st.text_input(
        "Date (YYYY-MM-DD)",
        placeholder="e.g. 2026-04-02 or leave empty",
        label_visibility="collapsed",
        help="Optional if you know the date and it is not in the conversation",
    )

    st.markdown('<h2 class="step-heading">Step 4 · Run</h2>', unsafe_allow_html=True)
    run = st.button("Process meeting", type="primary", use_container_width=True)

    if run:
        if uploaded is None:
            st.error("Please upload an MP3, MP4 or M4A file first.")
            return

        participant_payload: list[dict[str, str]] = []
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                raw_name = row.get("Name", "")
                raw_email = row.get("Email", "")
                name = "" if pd.isna(raw_name) else str(raw_name).strip()
                email = "" if pd.isna(raw_email) else str(raw_email).strip()
                if not name and not email:
                    continue
                participant_payload.append({"name": name, "email": email})

        if not participant_payload:
            st.info("No participants in the table — analysis still runs; task emails only if you add names.")

        md = meeting_date.strip()
        if md:
            try:
                date.fromisoformat(md)
            except ValueError:
                st.error("Invalid date. Use YYYY-MM-DD or leave empty.")
                return

        url = f"{api_base.rstrip('/')}/process-meeting-audio"
        file_bytes = uploaded.getvalue()
        mime = uploaded.type or "application/octet-stream"
        files = {"audio": (uploaded.name, file_bytes, mime)}
        data = {
            "participants": json.dumps(participant_payload),
            "meeting_date": md,
        }

        with st.spinner("Processing… transcription → analysis → Notion page"):
            try:
                with httpx.Client(timeout=600.0) as client:
                    r = client.post(url, files=files, data=data)
            except httpx.RequestError as e:
                st.error(
                    f"Could not reach the API at `{api_base}`. "
                    f"Make sure the server is running (same port as API base URL): "
                    f"`uvicorn main:app --host 127.0.0.1 --port <port>`\n\nDetail: {e!s}"
                )
                return

        if r.status_code != 200:
            detail: str
            try:
                body = r.json()
                detail = body.get("detail", r.text)
                if isinstance(detail, list):
                    detail = json.dumps(detail, ensure_ascii=False)
            except Exception:
                detail = r.text or str(r.status_code)
            st.error(f"API error ({r.status_code}):\n\n{detail}")
            return

        try:
            payload = r.json()
        except json.JSONDecodeError:
            st.error("Invalid JSON response from the API.")
            return

        st.success("Done.")
        _render_results(payload)


def _render_results(payload: dict) -> None:
    st.markdown("---")
    st.markdown("### Results")

    title = html.escape(str(payload.get("meeting_title") or "—"))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div class="result-box"><h4>Meeting title</h4><p style="margin:0;font-size:1.05rem;">{title}</p></div>',
            unsafe_allow_html=True,
        )
    md = payload.get("meeting_date")
    with c2:
        if md:
            md_e = html.escape(str(md))
            st.markdown(
                f'<div class="result-box"><h4>Date</h4><p style="margin:0;font-size:1.05rem;">{md_e}</p></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="result-box"><h4>Date</h4><p style="margin:0;color:#94a3b8;">Not specified</p></div>',
                unsafe_allow_html=True,
            )

    summary = html.escape(str(payload.get("summary") or ""))
    st.markdown(
        f'<div class="result-box"><h4>Summary</h4><p style="margin:0;white-space:pre-wrap;line-height:1.55;">{summary}</p></div>',
        unsafe_allow_html=True,
    )

    st.markdown("##### Action items")
    items = payload.get("action_items") or []
    if not items:
        st.info("No action items identified.")
    else:
        rows = []
        for it in items:
            if isinstance(it, dict):
                rows.append(
                    {
                        "Task": it.get("task", ""),
                        "Assignee": it.get("assignee") or "—",
                        "Deadline": it.get("deadline") or "—",
                    }
                )
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
        )

    notion = payload.get("notion_page_url")
    if notion:
        st.markdown("##### Notion")
        st.link_button("Open Notion page", notion, use_container_width=False, type="secondary")
    else:
        st.warning("No Notion URL in the response.")


if __name__ == "__main__":
    main()
