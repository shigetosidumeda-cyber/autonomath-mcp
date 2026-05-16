#!/usr/bin/env python3
"""Submit jpcite article to dev.to via API.

Usage:
    DEVTO_API_KEY=xxx python scripts/publish/submit_devto.py

Token acquisition (~30 sec):
    https://dev.to/settings/extensions → "DEV Community API Keys" → Generate New Token
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "publication" / "submit" / "devto_jpcite.md"


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"')
    return fm, body


def main() -> int:
    token = os.environ.get("DEVTO_API_KEY")
    if not token:
        print(
            "ERROR: DEVTO_API_KEY not set. Acquire at https://dev.to/settings/extensions",
            file=sys.stderr,
        )
        return 2

    text = SRC.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    title = fm.get("title", "jpcite MCP server")
    tags_raw = fm.get("tags", "mcp,ai,rag,python,showdev")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    canonical = fm.get("canonical_url", "https://jpcite.com")
    payload = {
        "article": {
            "title": title,
            "body_markdown": body,
            "published": True,
            "tags": tags,
            "canonical_url": canonical,
        }
    }
    req = urllib.request.Request(
        "https://dev.to/api/articles",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": token,
            "Content-Type": "application/json",
            "Accept": "application/vnd.forem.api-v1+json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"OK status={resp.status} id={data.get('id')} url={data.get('url')}")
            return 0
    except urllib.error.HTTPError as e:
        print(f"HTTPError {e.code}: {e.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
