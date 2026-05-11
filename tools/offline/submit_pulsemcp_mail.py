#!/usr/bin/env python3
"""Submit jpcite to PulseMCP via xrea SMTP (operator-only offline tool).

PulseMCP's `/submit` form lives behind a Cloudflare-gated SPA; direct
`curl` POST is not feasible (Wave 23 2026-05-11 probe). The fallback path
is an email follow-up using the canonical body in
``docs/_internal/mcp_registry_submissions/pulsemcp_submission.md`` § Mail.

Default mode is **dry-run** — prints the message envelope + body without
opening an SMTP connection. Pass ``--send`` to actually deliver.

The PulseMCP support email is CF-obfuscated in their footer; the script
resolves it at runtime via ``--discover-to`` (decodes the
``data-cfemail`` attribute on the page) and otherwise expects you to pass
``--to`` explicitly. We do **not** hard-code the address here to avoid
stale-cache poisoning.

Reads SMTP credential from ``.env.local`` (``XREA_SMTP_PASSWORD``).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import re
import smtplib
import ssl
import sys
import urllib.request
from email.message import EmailMessage

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_LOCAL = REPO_ROOT / ".env.local"
SUBMISSION_DOC = (
    REPO_ROOT
    / "docs/_internal/mcp_registry_submissions/pulsemcp_submission.md"
)
INBOX_DIR = REPO_ROOT / "tools/offline/_inbox"

SMTP_HOST = "s374.xrea.com"
SMTP_PORT = 587
FROM_ADDR = "info@bookyou.net"
SMTP_USER = "info@bookyou.net"

SUBJECT = "jpcite — Japanese public-program evidence MCP (server submission)"


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


def _extract_body_from_doc(doc_path: pathlib.Path) -> str:
    """Pull the canonical mail body out of the first fenced block under
    `## Mail / form body (canonical)` or `## Mail body (canonical)`.
    """
    text = doc_path.read_text(encoding="utf-8")
    markers = (
        "## Mail / form body (canonical)",
        "## Mail body (canonical)",
    )
    for marker in markers:
        if marker in text:
            after = text.split(marker, 1)[1]
            break
    else:
        raise SystemExit(
            f"Submission doc {doc_path} is missing a `## Mail body` marker."
        )
    if "```" not in after:
        raise SystemExit("No fenced code block found after the Mail body marker.")
    _, fenced = after.split("```", 1)
    body, _ = fenced.split("```", 1)
    return body.lstrip("\n").rstrip() + "\n"


def _discover_pulsemcp_email() -> str | None:
    """Resolve PulseMCP's CF-obfuscated support email at runtime."""
    try:
        req = urllib.request.Request(
            "https://www.pulsemcp.com/",
            headers={"User-Agent": "Mozilla/5.0 jpcite-offline"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        print(f"[discover] FAILED: {exc!r}", file=sys.stderr)
        return None
    # Pattern 1: data-cfemail="<hex>"
    m = re.search(r'data-cfemail="([0-9a-f]+)"', html)
    if not m:
        m = re.search(r"/cdn-cgi/l/email-protection#([0-9a-f]+)", html)
    if not m:
        return None
    hex_str = m.group(1)
    key = int(hex_str[:2], 16)
    return "".join(
        chr(int(hex_str[i : i + 2], 16) ^ key) for i in range(2, len(hex_str), 2)
    )


def _compose(to_addr: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = to_addr
    msg["Reply-To"] = FROM_ADDR
    msg["Subject"] = SUBJECT
    msg["Date"] = _dt.datetime.now(_dt.timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S %z"
    )
    msg["X-Mailer"] = "jpcite-offline/submit_pulsemcp_mail"
    msg.set_content(body, charset="utf-8")
    return msg


def _archive(msg: EmailMessage, send_result: dict[str, object]) -> pathlib.Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{ts}_pulsemcp_submission"
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
        help="Actually send via xrea SMTP. Default: dry-run.",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Recipient email. If omitted with --discover-to, resolved live.",
    )
    parser.add_argument(
        "--discover-to",
        action="store_true",
        help="Resolve PulseMCP's CF-obfuscated email from the live footer.",
    )
    parser.add_argument(
        "--smtp-host", default=SMTP_HOST, help=f"SMTP host (default: {SMTP_HOST})."
    )
    parser.add_argument(
        "--smtp-port",
        type=int,
        default=SMTP_PORT,
        help=f"SMTP port (default: {SMTP_PORT}).",
    )
    args = parser.parse_args()

    to_addr = args.to
    if args.discover_to and not to_addr:
        to_addr = _discover_pulsemcp_email()
        if to_addr:
            print(f"[discover] resolved PulseMCP email -> {to_addr}")
        else:
            print(
                "[discover] could not resolve email; pass --to explicitly.",
                file=sys.stderr,
            )
            return 2
    if not to_addr:
        print(
            "ERROR: pass --to <addr> or --discover-to (PulseMCP email is "
            "CF-obfuscated; we do NOT hard-code it).",
            file=sys.stderr,
        )
        return 2

    env = _load_env_local()
    password = env.get("XREA_SMTP_PASSWORD") or os.environ.get("XREA_SMTP_PASSWORD")
    if not password and args.send:
        print("ERROR: XREA_SMTP_PASSWORD missing in .env.local / env.", file=sys.stderr)
        return 2

    body = _extract_body_from_doc(SUBMISSION_DOC)
    msg = _compose(to_addr, body)

    print(f"[compose] From   : {FROM_ADDR}")
    print(f"[compose] To     : {to_addr}")
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
    except Exception as exc:
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
