#!/usr/bin/env python3
"""Submit jpcite to Anthropic partnerships via xrea SMTP.

Operator-only offline tool (NOT inside src/ — does not violate the
``test_no_llm_in_production`` guard rail; this script does NOT import any
LLM SDK either, it is pure ``smtplib``).

Reads SMTP credential from ``.env.local`` (``XREA_SMTP_PASSWORD``) and the
mail body from ``docs/_internal/claude_project_submission.md`` §2-3.

Default mode is **dry-run** — prints the message envelope + body without
opening an SMTP connection. Pass ``--send`` to actually deliver.

Re-usable: the same module powers any future partner / press outreach via
xrea SMTP. See ``reference_bookyou_mail`` memory: xrea host
``s374.xrea.com:587`` STARTTLS, SMTP user = local part of the From address.

Usage::

    python3 tools/offline/submit_claude_project_mail.py            # dry-run
    python3 tools/offline/submit_claude_project_mail.py --send     # real send
    python3 tools/offline/submit_claude_project_mail.py --to me@example.com  # custom recipient (verify)
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
SUBMISSION_DOC = REPO_ROOT / "docs/_internal/claude_project_submission.md"
INBOX_DIR = REPO_ROOT / "tools/offline/_inbox"

# xrea constants (reference_bookyou_mail)
SMTP_HOST = "s374.xrea.com"
SMTP_PORT = 587

FROM_ADDR = "info@bookyou.net"
SMTP_USER = "info@bookyou.net"  # xrea = full local + domain user
DEFAULT_TO = "partnerships@anthropic.com"

SUBJECT = (
    "[MCP Server Submission] jpcite — Japanese public-program evidence "
    "(139 tools / 8.29GB unified DB)"
)


def _load_env_local() -> dict[str, str]:
    """Parse ``.env.local`` into a flat dict (no shell, no python-dotenv)."""
    env: dict[str, str] = {}
    if not ENV_LOCAL.exists():
        return env
    for raw in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # strip surrounding quotes if any
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _extract_body_from_doc(doc_path: pathlib.Path) -> str:
    """Extract the fenced-code block under §2-3 in the submission doc.

    The submission doc keeps the canonical mail body inside a single fenced
    code block under ``### 2-3. Body (en + ja 併記)``. We pull that block
    verbatim so the doc remains the SOT and the script stays a thin shipper.
    """
    text = doc_path.read_text(encoding="utf-8")
    marker = "### 2-3. Body (en + ja 併記)"
    if marker not in text:
        raise SystemExit(
            f"Submission doc {doc_path} is missing the §2-3 body marker."
        )
    after = text.split(marker, 1)[1]
    # find the first fenced ``` ... ``` block after the marker
    if "```" not in after:
        raise SystemExit("No fenced code block found after §2-3 marker.")
    _, fenced = after.split("```", 1)
    body, _ = fenced.split("```", 1)
    # body starts with a newline; keep it
    return body.lstrip("\n").rstrip() + "\n"


def _compose(to_addr: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = to_addr
    msg["Reply-To"] = FROM_ADDR
    msg["Subject"] = SUBJECT
    msg["Date"] = _dt.datetime.now(_dt.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S %z"
    )
    msg["X-Mailer"] = "jpcite-offline/submit_claude_project_mail"
    msg.set_content(body, charset="utf-8")
    return msg


def _archive(msg: EmailMessage, send_result: dict[str, object]) -> pathlib.Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{ts}_claude_project_submission"
    eml_path = INBOX_DIR / f"{stem}.eml"
    eml_path.write_bytes(bytes(msg))
    meta_path = INBOX_DIR / f"{stem}.meta.json"
    meta_path.write_text(
        json.dumps(send_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return eml_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send via xrea SMTP. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--to",
        default=DEFAULT_TO,
        help=f"Override recipient (default: {DEFAULT_TO}).",
    )
    parser.add_argument(
        "--smtp-host",
        default=SMTP_HOST,
        help=f"SMTP host (default: {SMTP_HOST}).",
    )
    parser.add_argument(
        "--smtp-port",
        type=int,
        default=SMTP_PORT,
        help=f"SMTP port (default: {SMTP_PORT}).",
    )
    args = parser.parse_args()

    env = _load_env_local()
    password = env.get("XREA_SMTP_PASSWORD") or os.environ.get("XREA_SMTP_PASSWORD")
    if not password and args.send:
        print("ERROR: XREA_SMTP_PASSWORD missing in .env.local / env.", file=sys.stderr)
        return 2

    body = _extract_body_from_doc(SUBMISSION_DOC)
    msg = _compose(args.to, body)

    print(f"[compose] From   : {FROM_ADDR}")
    print(f"[compose] To     : {args.to}")
    print(f"[compose] Subject: {SUBJECT}")
    print(f"[compose] Body   : {len(body)} bytes")
    print(f"[compose] SMTP   : {args.smtp_host}:{args.smtp_port} (STARTTLS)")
    print()

    if not args.send:
        print("[dry-run] No SMTP connection opened. Pass --send to deliver.")
        print()
        print("---- BEGIN BODY PREVIEW (first 1200 chars) ----")
        print(body[:1200])
        print("---- END BODY PREVIEW ----")
        return 0

    send_result: dict[str, object] = {
        "to": args.to,
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
        eml = _archive(msg, send_result)
        print(f"[send] FAILED: {exc!r}", file=sys.stderr)
        print(f"[send] archived to {eml}", file=sys.stderr)
        return 1

    eml = _archive(msg, send_result)
    print("[send] OK")
    print(f"[send] archived to {eml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
