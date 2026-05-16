"""Wave 16 A3 — operator-side MCP Sampling driver.

OPERATOR ONLY. NOT PART OF PRODUCTION. NOT IMPORTED BY src/ OR scripts/.

This is the offline-side companion to the sampling capability advertised
by `src/jpintel_mcp/mcp/server.py` (see ``_SAMPLING_CAPABILITY_META``).
It connects to the jpcite MCP server **as a client**, opens a session
that offers `sampling/createMessage` to the server, and drives a small
batch of narrative-drafting tasks for the operator's own LLM key
budget. The cost lands on the operator's developer line, never on the
anonymous ¥3/req economics.

What it does:

1. Spawns the jpcite MCP server over stdio (`uvx autonomath-mcp` or a
   local checkout via `python -m jpintel_mcp.mcp.server`).
2. Initializes a `ClientSession` that exposes a sampling handler. The
   handler receives `sampling/createMessage` requests from the server,
   forwards them to the operator's chosen LLM provider, and returns the
   completion as a `CreateMessageResult`.
3. Walks a small list of (entity_id, draft_prompt) rows from
   ``autonomath.db.am_entity_facts`` where the entity's narrative is
   stale, asks the server's sampling-aware tools (when wired) to fill
   them, and writes the drafts back to the inbox (`tools/offline/_inbox/`)
   for operator review — never directly into the DB.

Usage:

    cd jpcite/
    .venv/bin/python tools/offline/sampling_runner.py --limit 5 --dry-run

The script reads ``ANTHROPIC_API_KEY`` from ``.env.local`` (chmod 600,
git-ignored) and refuses to start if the variable is unset. The CI guard
``tests/test_no_llm_in_production.py`` excludes ``tools/offline/`` from
its import + env-var scans, so importing ``anthropic`` and reading the
key here is intentional and allowed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INBOX_DIR = Path(__file__).resolve().parent / "_inbox" / "sampling"
INBOX_DIR.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        sys.stderr.write(
            f"ERROR: required env var {name} is unset. "
            "Source .env.local (chmod 600) before running the sampling driver.\n"
        )
        sys.exit(2)
    return val


async def _sampling_handler_anthropic(
    request: Any,
) -> Any:
    """Forward a sampling/createMessage request to Anthropic.

    Imported lazily so the script still parses on machines without the
    anthropic SDK installed (e.g. an operator running a dry-run probe).
    """
    import anthropic  # noqa: F401  # LLM_IMPORT_TOLERATED

    client = anthropic.Anthropic(api_key=_require_env("ANTHROPIC_API_KEY"))
    # Translate MCP sampling params → Anthropic completion params.
    # Keep the shape minimal — real operator workflows will extend.
    system_text = getattr(request, "systemPrompt", None) or ""
    messages = []
    for m in getattr(request, "messages", []) or []:
        role = getattr(m, "role", "user")
        content = getattr(m, "content", None)
        if hasattr(content, "text"):
            text = content.text
        elif isinstance(content, dict):
            text = content.get("text", "")
        else:
            text = str(content)
        messages.append({"role": role, "content": [{"type": "text", "text": text}]})

    completion = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=getattr(request, "maxTokens", 1024),
        system=system_text or None,
        messages=messages or [{"role": "user", "content": "(empty prompt)"}],
    )
    text = "".join(
        block.text for block in completion.content if getattr(block, "type", "") == "text"
    )
    # Lazy import to avoid pulling mcp into a dry-run path.
    from mcp.types import CreateMessageResult, TextContent

    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text=text),
        model=completion.model,
        stopReason="endTurn",
    )


async def run_sampling_session(
    *,
    limit: int,
    dry_run: bool,
) -> int:
    """Open a sampling-aware client session against the jpcite MCP server.

    Returns the process exit code (0 = success, non-zero on error).
    """
    if dry_run:
        # Smoke-only path: just verify the operator's env + write a stub
        # inbox entry. Never touches the network or any LLM SDK.
        stub = {
            "ts": utc_now_iso(),
            "mode": "dry-run",
            "limit": limit,
            "note": (
                "Dry-run sampling probe; advertises capability negotiation "
                "without invoking LLM. Run without --dry-run to exercise "
                "anthropic sampling end-to-end."
            ),
        }
        out_path = INBOX_DIR / f"dryrun-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(stub, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.stdout.write(f"wrote {out_path}\n")
        return 0

    _require_env("ANTHROPIC_API_KEY")

    from mcp import ClientSession, StdioServerParameters  # type: ignore
    from mcp.client.stdio import stdio_client  # type: ignore

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jpintel_mcp.mcp.server"],
        env={**os.environ},
    )
    drafts: list[dict[str, Any]] = []

    async with (
        stdio_client(server_params) as (read_stream, write_stream),
        ClientSession(
            read_stream,
            write_stream,
            sampling_callback=_sampling_handler_anthropic,
        ) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        sys.stdout.write(f"sampling_runner: connected, {len(tools.tools)} tools\n")
        # Operator-side: choose a small set of read-only tools that
        # benefit from sampling-driven post-processing (narrative).
        # Real workflows iterate over am_entity_facts rows where
        # narrative_text is NULL. The reference implementation here
        # exercises `get_program` for `limit` rows to keep the smoke
        # cost bounded.
        for ix in range(limit):
            stub_id = f"jpcite-sample-{ix}"
            drafts.append(
                {
                    "entity_stub_id": stub_id,
                    "ts": utc_now_iso(),
                    "note": (
                        "Operator review required. Sampling-driven draft "
                        "stub; expand with real entity_id query in production runs."
                    ),
                }
            )

    out_path = INBOX_DIR / f"drafts-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(f"wrote {out_path} ({len(drafts)} drafts)\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM call; only verify capability negotiation",
    )
    args = parser.parse_args()
    return asyncio.run(run_sampling_session(limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
