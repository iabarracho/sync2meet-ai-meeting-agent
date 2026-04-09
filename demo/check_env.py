"""
Verify required environment variables for a full demo (no secrets printed).
Run from repo root: python demo/check_env.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def main() -> int:
    checks: list[tuple[str, str]] = [
        ("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "").strip()),
        ("NOTION_API_KEY or NOTION_TOKEN", (os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN") or "").strip()),
        ("NOTION_PARENT_PAGE_ID", os.getenv("NOTION_PARENT_PAGE_ID", "").strip()),
    ]
    ok = True
    for label, val in checks:
        if val:
            print(f"[OK] {label} is set")
        else:
            print(f"[MISSING] {label}")
            ok = False
    smtp = os.getenv("SMTP_HOST", "").strip()
    if smtp:
        print(f"[OK] SMTP_HOST is set (task emails can be sent)")
    else:
        print(f"[INFO] SMTP_HOST empty — task emails will be skipped (analysis + Notion still run)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
