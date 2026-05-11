#!/usr/bin/env python3
"""Submit jpcite article to Qiita via API v2.

Usage:
    QIITA_TOKEN=xxx python scripts/publish/submit_qiita.py

Token acquisition (~30 sec):
    https://qiita.com/settings/applications → "個人用アクセストークン" → 発行
    scope: write_qiita (read+write)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "announce" / "zenn_jpcite_mcp.md"


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text if end == -1 else text[end + 4 :].lstrip("\n")


def main() -> int:
    token = os.environ.get("QIITA_TOKEN")
    if not token:
        print(
            "ERROR: QIITA_TOKEN not set. Acquire at https://qiita.com/settings/applications",
            file=sys.stderr,
        )
        return 2

    body = strip_frontmatter(SRC.read_text(encoding="utf-8"))
    title = "jpcite MCP — 日本の補助金 11,601+ / 法令 9,484+ を Claude Code から横断検索する"
    # Qiita tag schema: list of {"name": "Foo", "versions": []}
    tags = [
        {"name": "MCP", "versions": []},
        {"name": "ClaudeCode", "versions": []},
        {"name": "Python", "versions": []},
        {"name": "FastAPI", "versions": []},
        {"name": "RAG", "versions": []},
    ]
    payload = {
        "title": title,
        "body": body,
        "tags": tags,
        "private": False,
        "tweet": False,
    }
    req = urllib.request.Request(
        "https://qiita.com/api/v2/items",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
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
