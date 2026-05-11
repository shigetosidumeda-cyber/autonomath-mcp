#!/usr/bin/env python3
"""Wave 21 G3: Anthropic Claude Project re-submission + follow-up via xrea SMTP.

Builds on ``submit_claude_project_mail.py`` (Wave 16) — same SMTP wire, but the
mail body is a **follow-up** drafted against jpcite v0.3.4 LIVE state
(120 tools / 28 resources / AX 44/44 / Journey 10/10 / 4,786 companion .md
/ 503,930 entities / 6.12M facts).

Three submission modes:

  * ``--mode resubmit``   — resend the v0.3.4 LIVE confirmation to the
                            ``partnerships@anthropic.com`` address used in W16.
  * ``--mode followup``   — politely ask for review status of the W16 thread.
  * ``--mode press``      — push to the press@anthropic.com inbox with the
                            same body (alternate review channel).

Default mode is **dry-run** (prints envelope + body). Pass ``--send`` to
actually deliver via xrea SMTP (``s374.xrea.com:587``, STARTTLS,
``XREA_SMTP_PASSWORD`` from ``.env.local``).

Operator-only, ``tools/offline/`` per memory ``feedback_no_operator_llm_api`` —
no LLM SDK import here, ``smtplib`` only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import smtplib
import ssl
import sys
from email.message import EmailMessage

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_LOCAL = REPO_ROOT / ".env.local"
INBOX_DIR = REPO_ROOT / "tools/offline/_inbox"

# xrea constants (memory `reference_bookyou_mail`).
SMTP_HOST = "s374.xrea.com"
SMTP_PORT = 587
FROM_ADDR = "info@bookyou.net"
SMTP_USER = "info@bookyou.net"

ROUTING: dict[str, str] = {
    "resubmit": "partnerships@anthropic.com",
    "followup": "partnerships@anthropic.com",
    "press": "press@anthropic.com",
}

SUBJECT_TEMPLATE: dict[str, str] = {
    "resubmit": (
        "[MCP Server — re-submission] jpcite v0.3.4 LIVE (120 tools / 28 resources "
        "/ 4,786 companion .md / AX 44/44)"
    ),
    "followup": (
        "[follow-up] jpcite MCP server review status — re: W16 submission "
        "(now v0.3.4 LIVE, 120 tools)"
    ),
    "press": (
        "[press inquiry] jpcite — Japanese public-program evidence API for AI agents "
        "(120 tools / 503,930 entities)"
    ),
}


# ---------------------------------------------------------------------------
# Body builders
# ---------------------------------------------------------------------------


def _stamp_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resubmit_body() -> str:
    return f"""Hello Anthropic Partnerships team,

I am writing to **re-submit** jpcite for review as an MCP server entry.
The W16 (2026-04-25) submission has progressed substantially — the
v0.3.4 release is now LIVE on the public MCP registry and we have
verified the entire agent journey end-to-end.

Snapshot as of {_stamp_iso()}:

  * MCP tools:         120 (default gate) — verified via `mcp.list_tools()`
  * MCP resources:     28  (programs / laws / cases / enforcement / catalog)
  * MCP prompts:       7   (monthly-review / DD / etc.)
  * AX 4-pillar score: 44/44 (Access + Context + Tools + Orchestration)
  * Agent Journey:     10/10 step coverage (discovery → onboarding → outcome)
  * SEO companion:     4,786 .md (10,259 generated, top-N indexed)
  * Knowledge graph:   503,930 entities · 6.12M facts · 177,381 edges
  * Public registry:   https://registry.modelcontextprotocol.io/servers/jpcite
  * Discovery JSON:    https://jpcite.com/.well-known/mcp.json
  * OpenAPI v0.3.4:    https://api.jpcite.com/openapi.json (182 paths)
  * Streamable HTTP:   https://api.jpcite.com/mcp  (2025-06-18 protocol)
  * Stdio launcher:    `pip install autonomath-mcp && autonomath-mcp`
  * Sponsorship:       solo + zero-touch (no sales, no DPA, no CS team)
  * Pricing:           ¥3/req fully metered (税込 ¥3.30); anon 3 req/day free

Distinguishing properties vs other MCP servers:

  1. **No hallucination** — every response carries a `source_url` (一次資料)
     plus `fetched_at` (UTC ISO 8601). Aggregator-derived rows are banned.
  2. **業法 fence (legal-territory boundaries)** — every sensitive tool
     ships an envelope `_disclaimer` referencing 税理士法 §52 / 行政書士法 §1
     / 司法書士法 §3 / 弁護士法 §72 etc. so the AI client knows when to defer.
  3. **No LLM-on-LLM** — the operator does not call Claude (or any LLM) from
     production; consumer LLMs read jpcite responses verbatim. We are pure
     evidence pipe + structured fence registry.

We would be honored to be considered as an Anthropic-recommended MCP
server for the Japanese public-program / 補助金・法令・適格事業者 axis.

Documentation:

  * Onboarding:  https://jpcite.com/onboarding
  * Recipes:     https://jpcite.com/recipes/  (30 task-shaped walkthroughs)
  * Cookbook:    https://jpcite.com/docs/cookbook/
  * Status:      https://status.jpcite.com/
  * Registry:    https://jpcite.com/.well-known/mcp.json

I am happy to attend any review call or supply additional benchmarks.
Reply to <info@bookyou.net> at any time.

Thank you for the deep work you do on the MCP ecosystem.

— Shigeri Umeda (梅田茂利)
   Bookyou株式会社 — T8010001213708
   info@bookyou.net  |  https://jpcite.com
"""


def _followup_body() -> str:
    return f"""Hello again,

Following up on my MCP server submission from 2026-04-25 (the W16
thread) — gentle ping in case the original mail or any attachment was
filtered.

The product (jpcite) has shipped two more releases since then and is now
v0.3.4 LIVE on the public MCP registry. Snapshot {_stamp_iso()}:

  * 120 MCP tools (was 89 at W16 submission)
  * 28 resources, 7 prompts
  * AX 44/44, Journey 10/10
  * Streamable HTTP transport live at https://api.jpcite.com/mcp
  * Registry entry: https://registry.modelcontextprotocol.io/servers/jpcite

Could you let me know whether the W16 application is still in queue, or
whether you need any additional material from us? Even a one-line "still
queued" or "out-of-scope" reply would be enormously helpful for our
planning.

Thank you, and best regards.

— Shigeri Umeda (梅田茂利)
   Bookyou株式会社 — T8010001213708
   info@bookyou.net  |  https://jpcite.com
"""


def _press_body() -> str:
    return f"""Hello Anthropic press team,

I am the founder of Bookyou株式会社 and the operator of jpcite, a
Japanese public-program (補助金・法令・適格事業者・行政処分 etc.) evidence API
that is exposed as both a REST endpoint and an MCP server. We just shipped
v0.3.4 LIVE on the public MCP registry.

If you are tracking notable MCP server launches for the Japan market, I
think jpcite would be a useful data point. Key differentiators:

  * 120 MCP tools — broadest Japanese-public-data MCP surface area
  * 6.12M structured facts + 503,930 entities + 177,381 relation edges
  * 100% organic acquisition; solo + zero-touch operations
  * 業法 fence (税理士法 / 行政書士法 / 司法書士法 / 弁護士法) baked into every
    sensitive tool envelope so AI assistants know when to defer
  * AX (Agent eXperience) score 44/44 across 4 pillars (Access / Context /
    Tools / Orchestration)

A 30-minute video walkthrough is available on request; happy to also
send the openapi.json and a recipe deck.

Press kit:   https://jpcite.com/press
Registry:    https://jpcite.com/.well-known/mcp.json
Recipes:     https://jpcite.com/recipes/
Contact:     info@bookyou.net

Snapshot timestamp: {_stamp_iso()}.

Thank you for considering.

— Shigeri Umeda (梅田茂利)
   Bookyou株式会社 — T8010001213708
"""


BUILDERS = {
    "resubmit": _resubmit_body,
    "followup": _followup_body,
    "press": _press_body,
}


# ---------------------------------------------------------------------------
# Mail / SMTP plumbing (shared shape with W16 script for operator memory).
# ---------------------------------------------------------------------------


def _load_env_local() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_LOCAL.exists():
        return env
    for raw in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _compose(mode: str, to_addr: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = to_addr
    msg["Reply-To"] = FROM_ADDR
    msg["Subject"] = SUBJECT_TEMPLATE[mode]
    msg["Date"] = _dt.datetime.now(_dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["X-Mailer"] = "jpcite-offline/submit_claude_project_v2"
    msg["X-jpcite-mode"] = mode
    msg.set_content(body, charset="utf-8")
    return msg


def _archive(msg: EmailMessage, send_result: dict[str, object], mode: str) -> pathlib.Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{ts}_claude_project_{mode}_v2"
    eml_path = INBOX_DIR / f"{stem}.eml"
    eml_path.write_bytes(bytes(msg))
    meta_path = INBOX_DIR / f"{stem}.meta.json"
    meta_path.write_text(
        json.dumps(send_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return eml_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=list(BUILDERS), default="followup")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--to", default=None, help="Override recipient.")
    parser.add_argument("--smtp-host", default=SMTP_HOST)
    parser.add_argument("--smtp-port", type=int, default=SMTP_PORT)
    args = parser.parse_args(argv)

    to_addr = args.to or ROUTING[args.mode]
    body = BUILDERS[args.mode]()
    msg = _compose(args.mode, to_addr, body)

    print(f"[v2] mode    : {args.mode}")
    print(f"[v2] From    : {FROM_ADDR}")
    print(f"[v2] To      : {to_addr}")
    print(f"[v2] Subject : {SUBJECT_TEMPLATE[args.mode]}")
    print(f"[v2] Body    : {len(body)} bytes")
    print(f"[v2] SMTP    : {args.smtp_host}:{args.smtp_port} (STARTTLS)")
    print()

    if not args.send:
        print("[dry-run] No SMTP connection opened. Pass --send to deliver.")
        print()
        print("---- BEGIN BODY PREVIEW (first 1500 chars) ----")
        print(body[:1500])
        print("---- END BODY PREVIEW ----")
        return 0

    env = _load_env_local()
    password = env.get("XREA_SMTP_PASSWORD") or os.environ.get("XREA_SMTP_PASSWORD")
    if not password:
        print("ERROR: XREA_SMTP_PASSWORD missing in .env.local / env.", file=sys.stderr)
        return 2

    send_result: dict[str, object] = {
        "mode": args.mode,
        "to": to_addr,
        "smtp_host": args.smtp_host,
        "smtp_port": args.smtp_port,
        "attempted_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(args.smtp_host, args.smtp_port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(SMTP_USER, password)
            refused = s.send_message(msg)
            send_result["status"] = "sent"
            send_result["refused"] = refused or {}
    except Exception as exc:  # pragma: no cover - operator surface
        send_result["status"] = "error"
        send_result["error"] = repr(exc)
        eml = _archive(msg, send_result, args.mode)
        print(f"[send] FAILED: {exc!r}", file=sys.stderr)
        print(f"[send] archived to {eml}", file=sys.stderr)
        return 1

    eml = _archive(msg, send_result, args.mode)
    print("[send] OK")
    print(f"[send] archived to {eml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
