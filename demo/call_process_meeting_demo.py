"""
POST /process-meeting with demo transcript + sample participants.
Requires: uvicorn running (e.g. http://127.0.0.1:8000) and valid .env

Usage:
  python demo/call_process_meeting_demo.py
  set DEMO_API_URL=http://localhost:8000   # optional
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

DEMO_DIR = Path(__file__).resolve().parent
ROOT = DEMO_DIR.parent


def main() -> int:
    api = os.environ.get("DEMO_API_URL", "http://127.0.0.1:8000").rstrip("/")
    transcript = (DEMO_DIR / "sample_transcript.txt").read_text(encoding="utf-8")
    meta = json.loads((DEMO_DIR / "sample_request.json").read_text(encoding="utf-8"))
    payload = {
        "transcript": transcript,
        "meeting_date": meta.get("meeting_date"),
        "participants": meta.get("participants", []),
    }
    url = f"{api}/process-meeting"
    print(f"POST {url}")
    try:
        r = httpx.post(url, json=payload, timeout=300.0)
    except httpx.RequestError as e:
        print(f"Request failed: {e}")
        print("Is the API running?  uvicorn main:app --host 127.0.0.1 --port 8000")
        return 1
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(r.text[:2000])
        return 1
    data = r.json()
    print("\n--- meeting_title ---\n", data.get("meeting_title"))
    print("\n--- notion_page_url ---\n", data.get("notion_page_url"))
    print("\n--- action_items (count) ---\n", len(data.get("action_items") or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
