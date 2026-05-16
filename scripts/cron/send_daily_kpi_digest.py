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
_TEMPLATE_DIR = _REPO / "src" / "jpintel_mcp" / "email" / "templates"
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
        return (
            '<span style="display:inline-block;padding:1px 7px;border-radius:999px;'
            "background:#fee2e2;color:#b91c1c;font-size:10px;font-weight:600;"
            'letter-spacing:0.05em;text-transform:uppercase;">critical</span>'
        )
    if sev == "warn":
        return (
            '<span style="display:inline-block;padding:1px 7px;border-radius:999px;'
            "background:#fef9c3;color:#a16207;font-size:10px;font-weight:600;"
            'letter-spacing:0.05em;text-transform:uppercase;">warn</span>'
        )
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
            "</div>"
        )
    if warns:
        return (
            '<div style="margin:0 0 18px;padding:12px 14px;border-radius:8px;'
            'background:#fef9c3;border:1px solid #fde047;color:#854d0e;font-size:13px;font-weight:600;">'
            f"!  WARN: {', '.join(warns)}"
            "</div>"
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
        "{{trial_to_paid_30d_pct}}": _fmt_pct_unsigned(payload.get("trial_to_paid_30d_pct", 0.0)),
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
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
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
        "--to",
        default=OPERATOR_EMAIL,
        help=f"Override recipient (default {OPERATOR_EMAIL}).",
    )
    p.add_argument(
        "--mock",
        action="store_true",
        help="Use a mock KPI payload instead of querying the DB. "
        "Useful for previewing the email without local data.",
    )
    p.add_argument(
        "--out-html",
        type=Path,
        default=None,
        help="Write the rendered HTML body to this path (in addition to stdout in dry-run).",
    )
    p.add_argument(
        "--out-txt",
        type=Path,
        default=None,
        help="Write the rendered text body to this path.",
    )
    # Wave 26: customer-facing Slack digest fan-out. ``--target email``
    # preserves the existing operator-mail behaviour; ``--target slack``
    # additionally POSTs a Block Kit payload to ``--webhook-url`` (per
    # docs/integrations/slack_digest.md). ``--target both`` runs both
    # paths sequentially. Slack delivery is best-effort: a non-2xx does
    # NOT change the script's exit code so the cron pipeline keeps
    # email working when Slack rotates the webhook URL.
    p.add_argument(
        "--target",
        choices=("email", "slack", "both"),
        default=os.environ.get("DIGEST_TARGET", "email"),
        help="Where to send the digest. email (default) / slack / both.",
    )
    p.add_argument(
        "--webhook-url",
        default=os.environ.get("DIGEST_SLACK_WEBHOOK_URL"),
        help="Slack incoming webhook URL when --target includes slack.",
    )
    p.add_argument(
        "--customer-key",
        default=os.environ.get("DIGEST_CUSTOMER_KEY"),
        help=(
            "Customer key label echoed in the Slack payload (audit only,"
            " not used for billing — that happens via dispatch_webhooks)."
        ),
    )
    return p.parse_args(argv)


def _render_slack_blocks(payload: dict[str, Any], customer_key: str | None) -> dict[str, Any]:
    """Render the 3-section Block Kit payload documented in
    ``docs/integrations/slack_digest.md`` (Wave 26).

    Three sections are mandatory — empty ones still render with a
    "変化なし" body so the agent / human reader can tell the section
    was checked.
    """
    date_jst = payload.get("date_jst", "")
    mrr = payload.get("mrr_yen", 0)
    sentry = payload.get("sentry_row", "")
    return {
        "text": f"jpcite daily digest {date_jst}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"jpcite daily digest {date_jst}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*補助金*\n"
                        f"• MAU合計={payload.get('mau_total', 0)} 課金={payload.get('mau_paid', 0)} "
                        f"trial24h={payload.get('trial_signups_24h', 0)}\n"
                        f"• MRR={mrr:,}円 (W/W Δ={payload.get('mrr_wow_delta_yen', 0):+,}円)"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*インボイス*\n"
                        f"• 未同期 metered={payload.get('unsynced_metered_events', 0)} "
                        f"reconcile={payload.get('reconcile_drift_pct', 0):.4f}%\n"
                        f"• past-due={payload.get('past_due_count', 0)} churn7d={payload.get('churn_7d', 0)}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*法令*\n"
                        f"• GEO citation rate={payload.get('geo_citation_rate_pct', 0):.1f}% / "
                        f"probes={payload.get('geo_probes_total', 0)}\n"
                        f"• Sentry: {sentry}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "jpcite · §52 ご利用上の注意付き · "
                            f"customer={customer_key or 'operator'}"
                        ),
                    }
                ],
            },
        ],
    }


def _post_slack_block_kit(webhook_url: str, payload: dict[str, Any]) -> tuple[int, str]:
    """POST the Block Kit payload to a Slack incoming webhook.

    Returns ``(status, body)``. Slack expects a 200 on success;
    anything else is logged but does not change the cron exit code.
    Uses urllib so the script keeps zero extra runtime deps.
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, f"slack webhook unreachable: {exc!r}"


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

        # Wave 26 — Slack target rendering happens regardless of dry-run
        # so previews work without configuring a webhook URL.
        slack_blocks: dict[str, Any] | None = None
        if args.target in ("slack", "both"):
            slack_blocks = _render_slack_blocks(payload, args.customer_key)

        if args.dry_run:
            print(f"Subject: {subject}")
            print()
            print(text_body)
            if slack_blocks is not None:
                print()
                print("--- slack block kit (dry-run) ---")
                print(json.dumps(slack_blocks, ensure_ascii=False, indent=2))
            hb["metadata"] = {
                "dry_run": True,
                "severity": (payload or {}).get("severity"),
                "target": args.target,
            }
            return 0

        # Slack fan-out runs first when requested so the operator email
        # below still carries the canonical exit status.
        slack_status: int | None = None
        if slack_blocks is not None and args.webhook_url:
            slack_status, slack_body = _post_slack_block_kit(args.webhook_url, slack_blocks)
            if slack_status and 200 <= slack_status < 300:
                print(f"[info] slack ok HTTP {slack_status}")
            else:
                print(
                    f"[warn] slack non-2xx ({slack_status}): {slack_body}",
                    file=sys.stderr,
                )
        elif slack_blocks is not None:
            print(
                "[warn] --target includes slack but --webhook-url is unset; skipping",
                file=sys.stderr,
            )

        if args.target == "slack":
            # Slack-only mode: do not call Postmark. Heartbeat with the
            # Slack status so cron observability still records the run.
            hb["metadata"] = {
                "target": "slack",
                "slack_status": slack_status,
                "severity": (payload or {}).get("severity"),
            }
            hb["rows_processed"] = 1 if (slack_status or 0) // 100 == 2 else 0
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
