#!/usr/bin/env python3
"""visual_audit.py — operator-side screenshot audit for ETL Playwright fallbacks.

Why
---
The ETL / cron layer runs the Playwright fallback unattended on GHA
runners. When a static fetch fails and Playwright renders the page,
the helper writes a screenshot under `/tmp/etl_screenshots/` so the
operator can debug the fallback after the fact. This tool walks that
directory from a local operator session (Claude Code), lists what is
there, optionally drives a fresh fallback against a single URL so the
operator can `Read` the resulting PNG, and verifies every screenshot
is `Read`-safe (long axis ≤ 1600 px) per memory feedback_image_resize.

Production ETL is **unattended** — this tool is debug-only. The fast
path is: `python tools/offline/visual_audit.py list` to see what was
captured, then `Read /tmp/etl_screenshots/<file>.png` from Claude Code.

Constraints
-----------
* No LLM API import (memory feedback_no_operator_llm_api). The audit
  is structural; the operator drives the Vision LLM via `Read`.
* No aggregator URLs (CLAUDE.md "Data hygiene"). The helper already
  refuses them — this tool re-validates.
* Screenshots > 1600 px crash CLI `Read`; we always sips-resize after
  capture and verify before listing.

Usage
-----
    # 1) List captured screenshots
    python tools/offline/visual_audit.py list

    # 2) Drive a one-shot Playwright capture (operator debug)
    python tools/offline/visual_audit.py capture <url> [--etl-name NAME]

    # 3) Audit every screenshot for CLI-Read safety
    python tools/offline/visual_audit.py audit

    # 4) Prune captures older than N days
    python tools/offline/visual_audit.py prune --days 7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.etl._image_helper import (  # noqa: E402
    MAX_CLI_SAFE_PX,
    is_cli_safe,
    sips_resize_inplace,
)
from scripts.etl._playwright_helper import (  # noqa: E402
    AggregatorRefusedError,
    PlaywrightFallbackError,
    fetch_with_fallback,
    is_banned_url,
    screenshot_path_for,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("jpcite.tools.visual_audit")

DEFAULT_SCREENSHOT_DIR = Path("/tmp/etl_screenshots")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _human_age(ts: float) -> str:
    delta = time.time() - ts
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86_400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86_400)}d ago"


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    if not root.exists():
        print(f"no screenshots yet under {root}")
        return 0
    pngs = sorted(root.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pngs:
        print(f"empty directory: {root}")
        return 0
    print(f"# {len(pngs)} screenshot(s) under {root}")
    for p in pngs[: args.limit]:
        stat = p.stat()
        safe = "ok" if is_cli_safe(p) else "OVERSIZE"
        print(
            f"{p}  {stat.st_size:>9}B  {_human_age(stat.st_mtime):>8}  {safe}",
        )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    if not root.exists():
        print(json.dumps({"ok": True, "count": 0, "oversized": []}, indent=2))
        return 0
    pngs = sorted(root.glob("*.png"))
    oversized: list[str] = []
    for p in pngs:
        if not is_cli_safe(p):
            oversized.append(str(p))
            if args.fix:
                sips_resize_inplace(p, max_width=MAX_CLI_SAFE_PX)
                if is_cli_safe(p):
                    logger.info("resized %s -> CLI-safe", p)
                else:
                    logger.warning("could not resize %s (no sips/Pillow)", p)
    report: dict[str, Any] = {
        "ok": not oversized or args.fix,
        "count": len(pngs),
        "oversized": oversized,
        "ceiling_px": MAX_CLI_SAFE_PX,
        "fix_applied": args.fix,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_capture(args: argparse.Namespace) -> int:
    url: str = args.url
    if is_banned_url(url):
        print(json.dumps({"ok": False, "reason": "aggregator_refused", "url": url}))
        return 2
    etl_name = args.etl_name or "operator_debug"
    out_dir = Path(args.dir)
    _ensure_dir(out_dir)
    out_path = screenshot_path_for(etl_name, root=str(out_dir))

    async def _drive() -> dict[str, Any]:
        try:
            result = await fetch_with_fallback(
                url,
                static_fetcher=None,
                screenshot_path=out_path,
                timeout_ms=args.timeout * 1000,
            )
            return {
                "ok": True,
                "source": result.source,
                "status_code": result.status_code,
                "url": result.url,
                "body_len": len(result.body),
                "screenshot": result.screenshot_path,
            }
        except AggregatorRefusedError as exc:
            return {"ok": False, "reason": "aggregator_refused", "error": str(exc)}
        except PlaywrightFallbackError as exc:
            return {"ok": False, "reason": "playwright_failed", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "unknown", "error": f"{type(exc).__name__}: {exc}"}

    report = asyncio.run(_drive())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("ok") else 1


def cmd_prune(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    if not root.exists():
        print(json.dumps({"removed": 0}))
        return 0
    cutoff = time.time() - args.days * 86_400
    removed: list[str] = []
    for p in root.glob("*.png"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            removed.append(str(p))
    print(json.dumps({"removed": len(removed), "files": removed}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_SCREENSHOT_DIR),
        help=f"screenshot dir (default {DEFAULT_SCREENSHOT_DIR})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list captured screenshots")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_audit = sub.add_parser("audit", help="verify every PNG is Read-safe")
    p_audit.add_argument("--fix", action="store_true", help="auto-resize oversized images")
    p_audit.set_defaults(func=cmd_audit)

    p_cap = sub.add_parser("capture", help="drive a one-shot Playwright capture")
    p_cap.add_argument("url")
    p_cap.add_argument("--etl-name", default=None)
    p_cap.add_argument("--timeout", type=int, default=30, help="seconds")
    p_cap.set_defaults(func=cmd_capture)

    p_prune = sub.add_parser("prune", help="remove old PNGs")
    p_prune.add_argument("--days", type=int, default=7)
    p_prune.set_defaults(func=cmd_prune)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
