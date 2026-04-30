#!/usr/bin/env python3
"""scripts/cron/send_daily_kpi_digest.py

Daily 06:00 JST operator KPI email digest.

Composes a single email per day to ``info@bookyou.net`` summarising the
KPIs surfaced by ``scripts/ops_quick_stats.py --json`` /
``GET /v1/admin/kpi``:

  * MAU (anon + paid), MRR + W/W Δ, ¥/customer, cap usage
  * Trial signups (24h) + 30d trial→paid conversion
  * Churn (7d), past-due subs, unsynced metered events (>1h),
    reconcile drift %
  * GEO citation rate
  * Sentry / Stripe cached rows

Severity rollup is rendered Sentry-style at the top:

  - critical → red banner ``!! CRITICAL: <metric_list>``
  - warn     → yellow banner ``!  WARN: <metric_list>``
  - all ok   → no banner

Usage:
    python scripts/cron/send_daily_kpi_digest.py            # send
    python scripts/cron/send_daily_kpi_digest.py --dry-run  # render only
    python scripts/cron/send_daily_kpi_digest.py --to alt@example.com

Env vars:
    POSTMARK_API_TOKEN     — same token as the rest of the email pipeline
    POSTMARK_FROM          — defaults to ``info@bookyou.net``
    OPERATOR_EMAIL         — defaults to ``info@bookyou.net``
    JPINTEL_DB_PATH        — defaults to repo ``data/jpintel.db``
    DRY_RUN=1              — equivalent to ``--dry-run``

Cron entry (06:00 JST = 21:00 UTC):

    SHELL=/bin/bash
    PATH=/usr/bin:/bin:/usr/local/bin
    0 21 * * * cd /opt/autonomath && \
      .venv/bin/python scripts/cron/send_daily_kpi_digest.py >> \
      /var/log/autonomath/kpi_digest.log 2>&1

GitHub Actions equivalent: schedule cron ``'0 21 * * *'`` (UTC).

Constraints honoured (memory):
- READ-ONLY on Stripe — payload is sourced from local DB + JSON files,
  no Stripe HTTP API call (``feedback_autonomath_no_api_use``).
- Email-only outbound (``feedback_zero_touch_solo``).
- Brand: ``jpcite``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3  # noqa: TC003 (runtime: connection return type)
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Locate the package + the standalone CLI helpers.
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

_OPS_SCRIPT = _REPO / "scripts" / "ops_quick_stats.py"
_TEMPLATE_DIR = (
    _REPO / "src" / "jpintel_mcp" / "email" / "templates"
)
_TEMPLATE_HTML = _TEMPLATE_DIR / "daily_kpi_digest.html"
_TEMPLATE_TXT = _TEMPLATE_DIR / "daily_kpi_digest.txt"

POSTMARK_API_TOKEN = os.environ.get("POSTMARK_API_TOKEN", "")
POSTMARK_FROM = os.environ.get("POSTMARK_FROM", "info@bookyou.net")
OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL", "info@bookyou.net")


# ---------------------------------------------------------------------------
# KPI collection — re-uses ops_quick_stats.collect_payload by file
# import so the CLI / API / cron all read one source of truth.
# ---------------------------------------------------------------------------
def _load_ops_module() -> Any:
    spec = importlib.util.spec_from_file_location("_ops_for_cron", _OPS_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {_OPS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_kpi() -> dict[str, Any]:
    ops = _load_ops_module()
    db_path = ops.resolve_db_path()
    conn: sqlite3.Connection = ops.connect_ro(db_path)
    try:
        return ops.collect_payload(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Render — fill the html / txt templates with the KPI payload.
# ---------------------------------------------------------------------------
def _fmt_yen(n: int | None) -> str:
    if n is None:
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}¥{abs(n):,}"


def _fmt_yen_signed(n: int | None) -> str:
    if n is None:
        return "—"
    if n > 0:
        return f"+¥{n:,}"
    if n < 0:
        return f"-¥{abs(n):,}"
    return "¥0"


def _fmt_pct(n: float | None, digits: int = 1) -> str:
    if n is None:
        return "—"
    return f"{n:+.{digits}f}%" if digits > 0 and n != 0 else f"{n:.{digits}f}%"


def _fmt_pct_unsigned(n: float | None, digits: int = 1) -> str:
    if n is None:
        return "—"
    return f"{n:.{digits}f}%"


def _fmt_drift(n: float | None) -> str:
    if n is None:
        return "(no report)"
    return f"{n * 100:.3f}% (raw {n:.5f})"


def _sev_color(sev: str) -> str:
    return {
        "critical": "color:#b91c1c;",
        "warn": "color:#a16207;",
        "ok": "",
    }.get(sev, "")


def _sev_pill(sev: str) -> str:
    """Inline-style HTML pill — Postmark / Gmail safe."""
    if sev == "critical":
        return ('<span style="display:inline-block;padding:1px 7px;border-radius:999px;'
                'background:#fee2e2;color:#b91c1c;font-size:10px;font-weight:600;'
                'letter-spacing:0.05em;text-transform:uppercase;">critical</span>')
    if sev == "warn":
        return ('<span style="display:inline-block;padding:1px 7px;border-radius:999px;'
                'background:#fef9c3;color:#a16207;font-size:10px;font-weight:600;'
                'letter-spacing:0.05em;text-transform:uppercase;">warn</span>')
    return ""


def _sev_text(sev: str) -> str:
    if sev == "critical":
        return "[!! CRITICAL]"
    if sev == "warn":
        return "[!  WARN]"
    return ""


def _banner_block_html(severity: dict[str, str]) -> str:
    crits = [k for k, v in severity.items() if v == "critical"]
    warns = [k for k, v in severity.items() if v == "warn"]
    if crits:
        return (
            '<div style="margin:0 0 18px;padding:12px 14px;border-radius:8px;'
            'background:#fee2e2;border:1px solid #fca5a5;color:#991b1b;font-size:13px;font-weight:600;">'
            f"!! CRITICAL: {', '.join(crits)}"
            '</div>'
        )
    if warns:
        return (
            '<div style="margin:0 0 18px;padding:12px 14px;border-radius:8px;'
            'background:#fef9c3;border:1px solid #fde047;color:#854d0e;font-size:13px;font-weight:600;">'
            f"!  WARN: {', '.join(warns)}"
            '</div>'
        )
    return ""


def _banner_block_text(severity: dict[str, str]) -> str:
    crits = [k for k, v in severity.items() if v == "critical"]
    warns = [k for k, v in severity.items() if v == "warn"]
    if crits:
        return f"!! CRITICAL: {', '.join(crits)}\n"
    if warns:
        return f"!  WARN: {', '.join(warns)}\n"
    return "(all systems green)\n"


def _placeholders(payload: dict[str, Any]) -> dict[str, str]:
    sev = payload.get("severity") or {}

    drift_pct = payload.get("reconcile_drift_pct")
    geo_pct = payload.get("geo_citation_rate_pct")

    return {
        "{{date_jst}}": payload.get("date_jst", ""),
        "{{generated_at}}": payload.get("generated_at", ""),
        "{{banner_block}}": _banner_block_html(sev),
        "{{banner_block_text}}": _banner_block_text(sev),
        # Audience
        "{{mau_total}}": str(payload.get("mau_total", 0)),
        "{{mau_anon}}": str(payload.get("mau_anon", 0)),
        "{{mau_paid}}": str(payload.get("mau_paid", 0)),
        # Revenue
        "{{mrr_yen}}": _fmt_yen(payload.get("mrr_yen", 0)),
        "{{mrr_per_customer_yen}}": _fmt_yen(payload.get("mrr_per_customer_yen", 0)),
        "{{mrr_wow_delta_yen}}": _fmt_yen_signed(payload.get("mrr_wow_delta_yen", 0)),
        "{{mrr_wow_pct}}": _fmt_pct(payload.get("mrr_wow_pct", 0.0)),
        "{{mrr_wow_pill}}": _sev_pill(sev.get("mrr_wow_pct", "ok")),
        "{{mrr_wow_color}}": _sev_color(sev.get("mrr_wow_pct", "ok")),
        "{{mrr_wow_sev_text}}": _sev_text(sev.get("mrr_wow_pct", "ok")),
        # Caps
        "{{cap_set}}": str(payload.get("cap_set", 0)),
        "{{cap_reached}}": str(payload.get("cap_reached", 0)),
        # Trial
        "{{trial_signups_24h}}": str(payload.get("trial_signups_24h", 0)),
        "{{trial_to_paid_30d_pct}}": _fmt_pct_unsigned(
            payload.get("trial_to_paid_30d_pct", 0.0)
        ),
        # Health
        "{{churn_7d}}": str(payload.get("churn_7d", 0)),
        "{{churn_pill}}": _sev_pill(sev.get("churn_7d", "ok")),
        "{{churn_color}}": _sev_color(sev.get("churn_7d", "ok")),
        "{{churn_sev_text}}": _sev_text(sev.get("churn_7d", "ok")),
        "{{past_due_count}}": str(payload.get("past_due_count", 0)),
        "{{past_due_pill}}": _sev_pill(sev.get("past_due_count", "ok")),
        "{{past_due_color}}": _sev_color(sev.get("past_due_count", "ok")),
        "{{past_due_sev_text}}": _sev_text(sev.get("past_due_count", "ok")),
        "{{unsynced_metered_events}}": str(payload.get("unsynced_metered_events", 0)),
        "{{unsynced_pill}}": _sev_pill(sev.get("unsynced_metered_events", "ok")),
        "{{unsynced_color}}": _sev_color(sev.get("unsynced_metered_events", "ok")),
        "{{unsynced_sev_text}}": _sev_text(sev.get("unsynced_metered_events", "ok")),
        "{{reconcile_drift_pct}}": _fmt_drift(drift_pct),
        "{{drift_pill}}": _sev_pill(sev.get("reconcile_drift_pct", "ok")),
        "{{drift_color}}": _sev_color(sev.get("reconcile_drift_pct", "ok")),
        "{{drift_sev_text}}": _sev_text(sev.get("reconcile_drift_pct", "ok")),
        # GEO
        "{{geo_citation_rate_pct}}": _fmt_pct_unsigned(geo_pct),
        "{{geo_probes_total}}": str(payload.get("geo_probes_total", 0)),
        # External rows
        "{{sentry_row}}": payload.get("sentry_row", "—"),
        "{{stripe_row}}": payload.get("stripe_row", "—"),
    }


def _fill(template: str, ph: dict[str, str]) -> str:
    out = template
    for needle, value in ph.items():
        out = out.replace(needle, value)
    return out


def render(payload: dict[str, Any]) -> tuple[str, str]:
    """Return ``(html_body, text_body)`` for the given KPI payload."""
    html_tmpl = _TEMPLATE_HTML.read_text(encoding="utf-8")
    txt_tmpl = _TEMPLATE_TXT.read_text(encoding="utf-8")
    ph = _placeholders(payload)
    return _fill(html_tmpl, ph), _fill(txt_tmpl, ph)


def render_subject(payload: dict[str, Any]) -> str:
    sev = payload.get("severity") or {}
    crits = [k for k, v in sev.items() if v == "critical"]
    warns = [k for k, v in sev.items() if v == "warn"]
    tag = "[CRIT]" if crits else "[WARN]" if warns else "[OK]"
    date = payload.get("date_jst", "")
    paid = payload.get("mau_paid", 0)
    mrr = payload.get("mrr_yen", 0)
    return f"{tag} jpcite 日次KPI {date} (paid {paid} / MRR ¥{mrr:,})"


# ---------------------------------------------------------------------------
# Email send (Postmark REST API via urllib — same pattern as
# scripts/weekly_digest.py to avoid pulling extra deps).
# ---------------------------------------------------------------------------
def send_email(
    subject: str,
    html_body: str,
    text_body: str,
    recipient: str,
) -> tuple[int, str]:
    """Send via Postmark.  Returns ``(status_code, response_body)``.

    When ``POSTMARK_API_TOKEN`` is unset we treat this as dry-run (the
    cron will print the rendered email to stdout instead of sending).
    Returning ``(0, "skipped")`` makes the unset-token path a soft
    no-op so a misconfigured environment never crashes the cron.
    """
    if not POSTMARK_API_TOKEN:
        return 0, "skipped (POSTMARK_API_TOKEN unset)"

    payload = json.dumps(
        {
            "From": POSTMARK_FROM,
            "To": recipient,
            "Subject": subject,
            "HtmlBody": html_body,
            "TextBody": text_body,
            "MessageStream": "outbound",
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.postmarkapp.com/email",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": POSTMARK_API_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:300]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")[:300]
    except OSError as exc:
        return -1, f"network error: {exc}"


# ---------------------------------------------------------------------------
# Main — parse args, collect, render, (optionally) send.
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "0") == "1",
        help="Render to stdout, do not send.",
    )
    p.add_argument(
        "--to", default=OPERATOR_EMAIL,
        help=f"Override recipient (default {OPERATOR_EMAIL}).",
    )
    p.add_argument(
        "--mock", action="store_true",
        help="Use a mock KPI payload instead of querying the DB. "
             "Useful for previewing the email without local data.",
    )
    p.add_argument(
        "--out-html", type=Path, default=None,
        help="Write the rendered HTML body to this path "
             "(in addition to stdout in dry-run).",
    )
    p.add_argument(
        "--out-txt", type=Path, default=None,
        help="Write the rendered text body to this path.",
    )
    return p.parse_args(argv)


def _mock_payload() -> dict[str, Any]:
    """A representative KPI payload with non-trivial values + a couple of
    warn-level signals.  Used for ``--mock`` preview rendering and also
    by the unit tests + sample digest emitted at build time.
    """
    now = datetime.now(UTC)
    jst = now + timedelta(hours=9)
    payload = {
        "generated_at": now.isoformat(),
        "date_jst": jst.strftime("%Y-%m-%d"),
        "mau_total": 234,
        "mau_anon": 198,
        "mau_paid": 36,
        "mrr_yen": 47250,
        "mrr_per_customer_yen": 1313,
        "mrr_wow_this_week_yen": 12_300,
        "mrr_wow_last_week_yen": 9_090,
        "mrr_wow_delta_yen": 3_210,
        "mrr_wow_pct": 35.31,
        "cap_set": 12,
        "cap_reached": 3,
        "churn_7d": 1,
        "past_due_count": 1,
        "unsynced_metered_events": 0,
        "reconcile_drift_pct": 0.0023,
        "reconcile_source_file": "stripe_reconcile_2026-04-29.json",
        "trial_signups_24h": 4,
        "trial_to_paid_30d_pct": 18.18,
        "geo_citation_rate_pct": 28.3,
        "geo_probes_total": 60,
        "geo_source_file": "geo_baseline_2026-04-29.jsonl",
        "sentry_row": "0 unresolved critical / 2 resolved",
        "stripe_row": "1 dispute in pending (¥3,510)",
    }
    ops = _load_ops_module()
    payload["severity"] = ops.classify(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with heartbeat("send_daily_kpi_digest") as hb:
        payload = _mock_payload() if args.mock else collect_kpi()
        html_body, text_body = render(payload)
        subject = render_subject(payload)

        if args.out_html:
            args.out_html.write_text(html_body, encoding="utf-8")
        if args.out_txt:
            args.out_txt.write_text(text_body, encoding="utf-8")

        if args.dry_run:
            print(f"Subject: {subject}")
            print()
            print(text_body)
            hb["metadata"] = {
                "dry_run": True,
                "severity": (payload or {}).get("severity"),
            }
            return 0

        status, body = send_email(subject, html_body, text_body, args.to)
        hb["metadata"] = {
            "to": args.to,
            "http_status": status,
            "severity": (payload or {}).get("severity"),
        }
        if status == 0:
            # POSTMARK_API_TOKEN unset → soft no-op.  Echo the email to
            # stdout so the cron log still has the day's snapshot.
            print(f"[warn] {body}")
            print(text_body)
            hb["rows_skipped"] = 1
            return 0
        if status >= 200 and status < 300:
            print(f"[info] sent to {args.to} (HTTP {status})")
            hb["rows_processed"] = 1
            return 0
        print(f"[error] postmark HTTP {status}: {body}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
