#!/usr/bin/env python3
"""scripts/weekly_digest.py

Monday 09:00 JST weekly digest of AutonoMath query telemetry.
Runs as a GitHub Actions scheduled workflow:

  on:
    schedule:
      - cron: '0 0 * * 1'  # Monday 00:00 UTC = 09:00 JST

Downloads the last 7 days of telemetry archives from Cloudflare R2,
loads them into DuckDB, runs standard queries, and emails a plain-text
report to info@bookyou.net via Postmark.

Required env vars:
  POSTMARK_API_TOKEN     — transactional email (same as main app)
  CLOUDFLARE_API_TOKEN   — R2 read access
  CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID
  R2_BUCKET              — defaults to "autonomath-telemetry"
  OPERATOR_EMAIL         — defaults to "info@bookyou.net"

Optional:
  POSTMARK_FROM          — defaults to "info@bookyou.net"
  DRY_RUN                — set to "1" to print report instead of emailing
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
R2_BUCKET = os.environ.get("R2_BUCKET", "autonomath-telemetry")
OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL", "info@bookyou.net")
POSTMARK_API_TOKEN = os.environ.get("POSTMARK_API_TOKEN", "")
POSTMARK_FROM = os.environ.get("POSTMARK_FROM", "info@bookyou.net")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
TODAY = datetime.date.today()

# ---------------------------------------------------------------------------
# R2 download helpers
# ---------------------------------------------------------------------------


def _date_range_keys(days: int = 7) -> list[str]:
    """Return R2 object keys for the last `days` days (YYYY-MM-DD.json.gz)."""
    return [
        f"{(TODAY - datetime.timedelta(days=i)).isoformat()}.json.gz"
        for i in range(1, days + 1)
    ]


def _download_from_r2(key: str, dest: str) -> bool:
    """Download a single R2 object via wrangler. Returns True on success."""
    if not shutil.which("wrangler"):
        print(f"[warn] wrangler not in PATH; cannot download {key}", file=sys.stderr)
        return False
    result = subprocess.run(
        ["wrangler", "r2", "object", "get", f"{R2_BUCKET}/{key}", "--file", dest],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[warn] wrangler get {key} failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def download_telemetry(tmpdir: str, days: int = 7) -> list[str]:
    """Download telemetry archives for the last `days` days. Returns local paths."""
    paths: list[str] = []
    for key in _date_range_keys(days):
        dest = os.path.join(tmpdir, key)
        if _download_from_r2(key, dest):
            paths.append(dest)
        else:
            print(f"[info] skipping missing archive: {key}", file=sys.stderr)
    return paths


# ---------------------------------------------------------------------------
# DuckDB analysis
# ---------------------------------------------------------------------------

# Schema: ts, channel, endpoint, params_shape, result_count, latency_ms, status, error_class


def _load_telemetry(con: duckdb.DuckDBPyConnection, paths: list[str]) -> int:
    """Load gzipped JSON-lines files into a 'telemetry' view. Returns row count."""
    if not paths:
        return 0
    glob_pattern = "{" + ",".join(paths) + "}"
    con.execute(f"""
        CREATE OR REPLACE VIEW telemetry AS
        SELECT *
        FROM read_json_auto('{glob_pattern}',
            format='newline_delimited',
            compression='gzip',
            ignore_errors=true)
    """)
    row_count = con.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]  # type: ignore[index]
    return int(row_count)


def _fmt_table(rows: list[tuple], headers: list[str]) -> str:
    """Format a list of tuples as a plain-text table."""
    col_widths = [len(h) for h in headers]
    str_rows = [[str(v) if v is not None else "NULL" for v in row] for row in rows]
    for row in str_rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))
    sep = "  ".join("-" * w for w in col_widths)
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    lines = [header_line, sep]
    for row in str_rows:
        lines.append("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def run_queries(con: duckdb.DuckDBPyConnection) -> str:
    """Run all standard digest queries and return a plain-text report."""
    sections: list[str] = []

    def section(title: str, body: str) -> None:
        sections.append(f"{'=' * 60}\n{title}\n{'=' * 60}\n{body}")

    # ── 1. Top 20 REST endpoints by call count ──────────────────────────────
    rows = con.execute("""
        SELECT endpoint, COUNT(*) AS calls
        FROM telemetry
        WHERE channel = 'rest'
        GROUP BY endpoint
        ORDER BY calls DESC
        LIMIT 20
    """).fetchall()
    section(
        "Top 20 REST endpoints (by call count)",
        _fmt_table(rows, ["endpoint", "calls"]) if rows else "(no data)",
    )

    # ── 2. Top 20 MCP tools by call count ───────────────────────────────────
    rows = con.execute("""
        SELECT endpoint AS tool_name, COUNT(*) AS calls
        FROM telemetry
        WHERE channel = 'mcp'
        GROUP BY endpoint
        ORDER BY calls DESC
        LIMIT 20
    """).fetchall()
    section(
        "Top 20 MCP tools (by call count)",
        _fmt_table(rows, ["tool_name", "calls"]) if rows else "(no data)",
    )

    # ── 3. Zero-result query rate ────────────────────────────────────────────
    zr = con.execute("""
        SELECT
          channel,
          COUNT(*) FILTER (WHERE result_count = 0) AS zero_result,
          COUNT(*) AS total,
          ROUND(100.0 * COUNT(*) FILTER (WHERE result_count = 0) / NULLIF(COUNT(*), 0), 2) AS pct
        FROM telemetry
        GROUP BY channel
        ORDER BY channel
    """).fetchall()
    section(
        "Zero-result query rate (by channel)",
        _fmt_table(zr, ["channel", "zero_result", "total", "pct_%"]) if zr else "(no data)",
    )

    # ── 4. Top 20 failing queries (status != 200) ───────────────────────────
    fail_rows = con.execute("""
        SELECT status, endpoint, error_class, COUNT(*) AS occurrences
        FROM telemetry
        WHERE status < 200 OR status > 299
        GROUP BY status, endpoint, error_class
        ORDER BY occurrences DESC
        LIMIT 20
    """).fetchall()
    section(
        "Top 20 failing queries (status not 2xx)",
        _fmt_table(fail_rows, ["status", "endpoint", "error_class", "occurrences"])
        if fail_rows
        else "(none — all requests succeeded)",
    )

    # ── 5. P50/P95/P99 latency by endpoint ──────────────────────────────────
    lat_rows = con.execute("""
        SELECT
          channel,
          endpoint,
          ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms), 1) AS p50_ms,
          ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms), 1) AS p95_ms,
          ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms), 1) AS p99_ms,
          COUNT(*) AS n
        FROM telemetry
        WHERE latency_ms IS NOT NULL
        GROUP BY channel, endpoint
        ORDER BY p95_ms DESC
        LIMIT 30
    """).fetchall()
    section(
        "P50/P95/P99 latency by endpoint (ms) — top 30 by P95",
        _fmt_table(lat_rows, ["ch", "endpoint", "p50", "p95", "p99", "n"])
        if lat_rows
        else "(no latency data)",
    )

    # ── 6. New query terms vs prior 7 days (params_shape vocabulary) ─────────
    # We compare the current week's endpoint+params_shape combos with prior week.
    # (Full 30-day comparison requires 30 days of archives; use 7d vs prior 7d here)
    new_terms = con.execute("""
        WITH this_week AS (
            SELECT DISTINCT params_shape
            FROM telemetry
            WHERE ts >= (CURRENT_TIMESTAMP - INTERVAL 7 DAY)
              AND params_shape IS NOT NULL
        ),
        prior_week AS (
            SELECT DISTINCT params_shape
            FROM telemetry
            WHERE ts < (CURRENT_TIMESTAMP - INTERVAL 7 DAY)
              AND params_shape IS NOT NULL
        )
        SELECT tw.params_shape
        FROM this_week tw
        LEFT JOIN prior_week pw ON tw.params_shape = pw.params_shape
        WHERE pw.params_shape IS NULL
        LIMIT 30
    """).fetchall()
    body = (
        "\n".join(r[0] for r in new_terms)
        if new_terms
        else "(no new param shapes vs prior 7-day window)"
    )
    section(f"New query param shapes this week vs prior 7d ({len(new_terms)} new)", body)

    # ── 7. Anonymous quota exhaustion events (429 rate) ─────────────────────
    q429 = con.execute("""
        SELECT
          COUNT(*) FILTER (WHERE status = 429) AS throttled,
          COUNT(*) AS total,
          ROUND(100.0 * COUNT(*) FILTER (WHERE status = 429) / NULLIF(COUNT(*), 0), 3) AS pct
        FROM telemetry
    """).fetchone()
    body_429 = (
        f"throttled={q429[0]}  total={q429[1]}  rate={q429[2]}%"
        if q429
        else "(no data)"
    )
    section("Anonymous quota exhaustion (429)", body_429)

    # ── 8. Stripe billable request count (7-day total) ───────────────────────
    # Billable = authenticated requests (non-anonymous) with status 2xx
    billable = con.execute("""
        SELECT COUNT(*) AS billable_requests
        FROM telemetry
        WHERE status BETWEEN 200 AND 299
          AND (params_shape NOT LIKE '%anon%' OR params_shape IS NULL)
    """).fetchone()
    body_bill = (
        f"Estimated billable requests (7d): {billable[0]}"
        if billable
        else "(no data)"
    )
    note = "(Note: verify exact count in Stripe Dashboard → Billing → Meters)"
    section("Stripe billable requests (7-day estimate)", f"{body_bill}\n{note}")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def send_email(subject: str, body: str) -> None:
    """Send plain-text email via Postmark REST API using urllib (no extra deps)."""
    import urllib.request

    if not POSTMARK_API_TOKEN:
        print("[warn] POSTMARK_API_TOKEN not set — printing email to stdout", file=sys.stderr)
        print(f"Subject: {subject}\n\n{body}")
        return

    payload = json.dumps(
        {
            "From": POSTMARK_FROM,
            "To": OPERATOR_EMAIL,
            "Subject": subject,
            "TextBody": body,
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
            status = resp.status
    except Exception as exc:
        print(f"[error] email send failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if status >= 400:
        print(f"[error] Postmark returned HTTP {status}", file=sys.stderr)
        sys.exit(1)
    print(f"[info] digest email sent to {OPERATOR_EMAIL} (HTTP {status})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    week_label = TODAY.strftime("W%Y-%V")
    subject = f"[AutonoMath] Weekly digest {week_label} ({TODAY.isoformat()})"

    with tempfile.TemporaryDirectory(prefix="autonomath-digest-") as tmpdir:
        print("[info] downloading telemetry archives from R2 …")
        paths = download_telemetry(tmpdir, days=7)
        if not paths:
            body = (
                f"Weekly digest for {week_label}\n\n"
                "No telemetry archives found in R2 for the past 7 days.\n"
                "Either the nightly archive_telemetry.sh has not run yet, "
                "or the R2 bucket is empty.\n"
            )
            if DRY_RUN:
                print(body)
            else:
                send_email(subject, body)
            return

        con = duckdb.connect(database=":memory:")
        row_count = _load_telemetry(con, paths)
        print(f"[info] loaded {row_count:,} rows from {len(paths)} archives")

        report = run_queries(con)
        con.close()

    header = (
        f"AutonoMath — Weekly Telemetry Digest\n"
        f"Week: {week_label}  |  Generated: {TODAY.isoformat()}\n"
        f"Archives analyzed: {len(paths)} days  |  Total events: {row_count:,}\n"
        f"Operator: Bookyou株式会社 <{OPERATOR_EMAIL}>\n"
    )
    full_body = f"{header}\n\n{report}\n"

    if DRY_RUN:
        print(full_body)
        return

    send_email(subject, full_body)


if __name__ == "__main__":
    main()
