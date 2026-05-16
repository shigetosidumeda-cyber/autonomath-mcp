#!/usr/bin/env python3
"""Submit jpcite article to note.com via Playwright (no public API).

note.com does not expose an official public publish API. Their internal
`/api/v2/notes/<key>/publish` endpoint exists but TOS forbids automated
posting via reverse-engineered endpoints. The accepted path is to drive
the editor in a real browser — Playwright with the user's session cookie
satisfies that.

Usage:
    NOTE_SESSION_COOKIE=<value-of-_note_session_v5> \
    NOTE_USER_AGENT="Mozilla/5.0 ..." \
    .venv/bin/python scripts/publish/submit_note.py

Cookie acquisition (~30 sec):
    1. Sign in at https://note.com in Chrome
    2. DevTools → Application → Cookies → https://note.com
    3. Copy the value of `_note_session_v5`
    4. Export the User-Agent string from `navigator.userAgent` for the same session
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "announce" / "note_jpcite_mcp.md"


def main() -> int:
    cookie = os.environ.get("NOTE_SESSION_COOKIE")
    ua = os.environ.get("NOTE_USER_AGENT")
    if not cookie or not ua:
        print(
            "ERROR: NOTE_SESSION_COOKIE / NOTE_USER_AGENT not set.\n"
            "  Sign in at note.com in Chrome → DevTools Application → Cookies →\n"
            "  copy `_note_session_v5` to NOTE_SESSION_COOKIE,\n"
            "  copy navigator.userAgent to NOTE_USER_AGENT. (~30 sec)",
            file=sys.stderr,
        )
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed. .venv/bin/pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 3

    text = SRC.read_text(encoding="utf-8")
    title = "Claude Code から日本の補助金 DB を 1 行で呼べる時代 — jpcite MCP β 公開"
    # note.com editor accepts pasted markdown via blocks; for full fidelity we paste line-by-line
    body_lines = [ln for ln in text.splitlines() if not ln.startswith("# ")]
    body = "\n".join(body_lines).strip()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=ua, locale="ja-JP")
        ctx.add_cookies(
            [
                {
                    "name": "_note_session_v5",
                    "value": cookie,
                    "domain": ".note.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = ctx.new_page()
        page.goto("https://note.com/notes/new", wait_until="networkidle", timeout=45_000)

        # Title input — note.com editor uses a contenteditable for title and body.
        # Field structure last verified 2026-05 (will need refresh if editor refactors).
        page.wait_for_selector(
            "input[placeholder*='タイトル'], textarea[placeholder*='タイトル']", timeout=30_000
        )
        try:
            page.fill("input[placeholder*='タイトル']", title)
        except Exception:
            page.fill("textarea[placeholder*='タイトル']", title)

        # Body — paste markdown text
        body_sel = "[contenteditable='true']:not([placeholder*='タイトル'])"
        page.click(body_sel)
        page.keyboard.insert_text(body)
        page.wait_for_timeout(2_000)

        # Publish — click 公開 button (note editor exposes 「公開設定」 → 「公開」)
        publish_btn = page.locator(
            "button:has-text('公開設定'), button:has-text('公開に進む')"
        ).first
        publish_btn.click(timeout=15_000)
        page.wait_for_timeout(2_000)
        final_btn = page.locator("button:has-text('投稿')", has_not_text="下書き").first
        final_btn.click(timeout=15_000)
        page.wait_for_url("**/n/**", timeout=30_000)
        url = page.url
        print(f"OK url={url}")
        browser.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
