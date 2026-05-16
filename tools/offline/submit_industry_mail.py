#!/usr/bin/env python3
"""Submit jpcite press release to multiple industry outlets via xrea SMTP.

Operator-only offline tool. Used for jpcite Wave 38 + Wave 41 organic-outreach
to industry-trade publications. Pure ``smtplib`` — no LLM SDK imports, so this
file does NOT violate the ``test_no_llm_in_production`` guard rail.

Reads the SMTP credential from ``.env.local`` (``XREA_SMTP_PASSWORD``) and
each mail body from a Markdown draft under ``docs/announce/``.

Default mode is **dry-run** — prints each envelope + body preview without
opening an SMTP connection. Pass ``--send`` to actually deliver. Pass
``--only <slug>`` (repeatable) to restrict the run to specific outlets.

Outlets are declared in the ``OUTLETS`` table below. Wave 38 sent 5 outlets
(zeirishi_shimbun / tkc_journal / gyosei_kaiho / ma_online / shindanshi_kaiho).
Wave 41 adds 2 more (bengoshi_dotcom / shinkin_monthly).

Usage::

    python3 tools/offline/submit_industry_mail.py                          # dry-run all
    python3 tools/offline/submit_industry_mail.py --send                   # real send
    python3 tools/offline/submit_industry_mail.py --only bengoshi_dotcom --only shinkin_monthly --send
    python3 tools/offline/submit_industry_mail.py --to info@bookyou.net --send  # self-test
"""

from __future__ import annotations

import argparse
import contextlib
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
ANNOUNCE_DIR = REPO_ROOT / "docs/announce"
INBOX_DIR = REPO_ROOT / "tools/offline/_inbox"

# xrea SMTP constants (reference_bookyou_mail)
SMTP_HOST = "s374.xrea.com"
SMTP_PORT = 587

FROM_ADDR = "info@bookyou.net"
SMTP_USER = "info@bookyou.net"  # xrea = full local + domain user

# Outlet registry — slug → (mail-target, subject, draft-path under docs/announce/).
# Mail addresses for industry outlets are the canonical editorial-desk
# addresses listed on each publication's public masthead / 寄稿 page.
# These are public information for press-release submission, not personal
# data. Editorial desks accept Japanese editorial submissions via these.
OUTLETS: dict[str, dict[str, str]] = {
    # ---- Wave 38 (already sent 2026-05-11) ----
    "zeirishi_shimbun": {
        "to": "editorial@zeirishi-shimbun.co.jp",
        "subject": (
            "[寄稿 / 業界紙] 顧問先 100 社の月次 review を月額 ¥5,940 で自動化する "
            "公的情報 AI — jpcite (Bookyou株式会社)"
        ),
        "draft": "zeirishi_shimbun_jpcite.md",
    },
    "tkc_journal": {
        "to": "henshu@tkcnf.or.jp",
        "subject": (
            "[寄稿 / 業界誌] TKC会員事務所向け 顧問先月次 review 公的情報 artifact API "
            "— jpcite (Bookyou株式会社)"
        ),
        "draft": "tkc_journal_jpcite.md",
    },
    "gyosei_kaiho": {
        "to": "henshu@gyosei.or.jp",
        "subject": (
            "[寄稿 / 業界誌] 行政書士事務所向け 公的情報 retrieval 自動化 — "
            "jpcite (Bookyou株式会社)"
        ),
        "draft": "gyosei_kaiho_jpcite.md",
    },
    "ma_online": {
        "to": "editorial@maonline.jp",
        "subject": (
            "[寄稿 / 業界誌] 中小 M&A の公開情報 DD を 5 分で artifact 化する手順 — "
            "jpcite recipe r03 (Bookyou株式会社)"
        ),
        "draft": "ma_online_jpcite.md",
    },
    "shindanshi_kaiho": {
        "to": "henshu@j-smeca.jp",
        "subject": (
            "[寄稿 / 業界誌] 中小企業診断士による事業性評価伴走で公的情報 artifact を "
            "活用する手順 — jpcite (Bookyou株式会社)"
        ),
        "draft": "shindanshi_kaiho_jpcite.md",
    },
    # ---- Wave 41 (this run) ----
    "bengoshi_dotcom": {
        "to": "press@bengo4.com",
        "subject": (
            "[寄稿 / 業界メディア] 弁護士業務における公的情報 retrieval 自動化 "
            "— jpcite (Bookyou株式会社)"
        ),
        "draft": "bengoshi_dotcom_jpcite.md",
    },
    "shinkin_monthly": {
        "to": "editorial@shinkin-monthly.co.jp",
        "subject": (
            "[寄稿 / 業界誌] 信用金庫渉外の月次伴走を公的情報 artifact API で生産性 10 倍に "
            "— jpcite (Bookyou株式会社)"
        ),
        "draft": "shinkin_monthly_jpcite.md",
    },
}


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
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _extract_body(draft_path: pathlib.Path) -> str:
    """Use the Markdown draft verbatim as plain-text mail body.

    The drafts under ``docs/announce/`` are already plain Japanese with the
    expected structure (lead + sections + ROI + recipe + closing). We avoid
    any LLM rewrite — same draft an editor sees, same body the recipient
    sees, so the SOT stays in the docs/ tree.
    """
    if not draft_path.exists():
        raise SystemExit(f"draft not found: {draft_path}")
    return draft_path.read_text(encoding="utf-8").rstrip() + "\n"


def _compose(to_addr: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = to_addr
    msg["Reply-To"] = FROM_ADDR
    msg["Subject"] = subject
    msg["Date"] = _dt.datetime.now(_dt.UTC).strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["X-Mailer"] = "jpcite-offline/submit_industry_mail"
    msg.set_content(body, charset="utf-8")
    return msg


def _archive(slug: str, msg: EmailMessage, result: dict[str, object]) -> pathlib.Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{ts}_industry_mail_{slug}"
    eml_path = INBOX_DIR / f"{stem}.eml"
    eml_path.write_bytes(bytes(msg))
    meta_path = INBOX_DIR / f"{stem}.meta.json"
    meta_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
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
        "--only",
        action="append",
        default=[],
        help="Restrict to one or more outlet slugs (repeatable).",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Override recipient (single address; for verify). Applies to all picked outlets.",
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

    # Resolve picked outlets
    if args.only:
        unknown = sorted(set(args.only) - set(OUTLETS.keys()))
        if unknown:
            print(
                f"ERROR: unknown outlet slug(s): {', '.join(unknown)}\n"
                f"  known: {', '.join(sorted(OUTLETS.keys()))}",
                file=sys.stderr,
            )
            return 2
        picked = [(slug, OUTLETS[slug]) for slug in args.only]
    else:
        picked = list(OUTLETS.items())

    print(f"[plan] outlets={len(picked)}  mode={'SEND' if args.send else 'dry-run'}")
    print()

    overall_status = 0
    summary: list[dict[str, object]] = []

    if args.send:
        # Re-use one SMTP connection across all outlets — xrea handles a few-msg burst fine
        ctx = ssl.create_default_context()
        try:
            smtp = smtplib.SMTP(args.smtp_host, args.smtp_port, timeout=30)
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(SMTP_USER, password)
        except Exception as exc:  # pragma: no cover - operator surface
            print(f"[smtp] login FAILED: {exc!r}", file=sys.stderr)
            return 1
    else:
        smtp = None

    try:
        for slug, cfg in picked:
            draft_path = ANNOUNCE_DIR / cfg["draft"]
            to_addr = args.to or cfg["to"]
            subject = cfg["subject"]
            body = _extract_body(draft_path)
            msg = _compose(to_addr, subject, body)

            print(f"[{slug}] To     : {to_addr}")
            print(f"[{slug}] Subject: {subject}")
            print(f"[{slug}] Body   : {len(body)} bytes  draft={cfg['draft']}")

            result: dict[str, object] = {
                "slug": slug,
                "to": to_addr,
                "subject": subject,
                "draft": cfg["draft"],
                "smtp_host": args.smtp_host,
                "smtp_port": args.smtp_port,
                "attempted_at_utc": _dt.datetime.now(_dt.UTC).isoformat(),
                "mode": "send" if args.send else "dry-run",
            }

            if smtp is None:
                # dry-run
                preview = "\n".join(body.splitlines()[:6])
                print(f"[{slug}] PREVIEW (first 6 lines):")
                print(preview)
                result["status"] = "dry-run"
                summary.append(result)
                print()
                continue

            try:
                refused = smtp.send_message(msg)
                result["status"] = "sent"
                result["refused"] = refused or {}
                eml = _archive(slug, msg, result)
                print(f"[{slug}] sent OK -> archived {eml}")
            except Exception as exc:  # pragma: no cover
                result["status"] = "error"
                result["error"] = repr(exc)
                eml = _archive(slug, msg, result)
                print(f"[{slug}] FAILED: {exc!r}  archived {eml}", file=sys.stderr)
                overall_status = 1
            summary.append(result)
            print()
    finally:
        if smtp is not None:
            with contextlib.suppress(Exception):
                smtp.quit()

    # Final summary line for grep-ability in CI logs
    if args.send:
        ok = sum(1 for r in summary if r.get("status") == "sent")
        err = sum(1 for r in summary if r.get("status") == "error")
        print(f"[summary] sent={ok} errors={err} total={len(summary)}")
    else:
        print(f"[summary] dry-run={len(summary)} (use --send to deliver)")

    return overall_status


if __name__ == "__main__":
    raise SystemExit(main())
