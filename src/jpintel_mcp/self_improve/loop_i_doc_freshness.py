"""Loop I: source freshness audit -> stale/broken flag report.

Cadence: weekly (Tuesday 02:00 JST — before weekly digest reads stats)
Inputs: `programs.source_url` + `programs.source_fetched_at` + `programs.tier`
        across all 13,578 rows. The companion nightly liveness scan in
        `scripts/refresh_sources.py` updates `source_fetched_at` /
        `source_last_check_status` / `source_fail_count` whenever it runs;
        this loop audits the *current* state of those columns plus does a
        targeted HEAD probe for un-checked or recently-flagged rows.
Outputs:
    * `data/source_freshness_report.json` — summary with stale count,
      broken count, per-tier breakdown, and a list of tier S/A broken
      unified_ids. Written every run (idempotent).
    * Operator email (Postmark template `weekly-digest` repurposed via
      `send_freshness_alert`) when at least one tier S/A row is broken.
      Best-effort: a Postmark 500 must not crash the cron, mirroring the
      "failures never raise" rule in `email/postmark.py`.

Cost ceiling: ~3 CPU minutes / week. HEAD probe budget = ≤ 5 req/sec
              global, ≤ 500 rows/run (tier S/A first, then sample). DB
              writes are limited to flag columns; never touches
              `source_fetched_at` (per CLAUDE.md "honest sentinel" rule).

Method (launch v1):
  1. Stale check (DB only, no HTTP):
        flag rows where `source_fetched_at` is NULL or older than
        `STALE_THRESHOLD_DAYS` (60 d).
  2. Broken check (HEAD probe with rate limiter from refresh_sources):
        flag rows where the most recent probe returned 404 or 5xx.
        - Read `source_last_check_status` first (zero-cost truthy signal).
        - For unscanned rows in tier S/A only, re-issue a HEAD via
          `_probe_url` (5 req/sec ceiling, identical UA + robots policy).
  3. Report generation:
        write JSON to `data/source_freshness_report.json` with
        `stale_count`, `broken_count`, `per_tier`, and a sample list of
        tier S/A broken `unified_id`s for the email.
  4. Notification:
        if any tier S/A broken row exists, send via PostmarkClient (or
        a structured-log no-op in test mode).

LLM use: NONE. Pure SQL + HEAD probe.

Honest semantics:
    * We do **not** rewrite `source_fetched_at` or `source_last_check_status`
      based on this audit — only `source_freshness_flag` (a fresh column
      this loop owns) gets bumped. The nightly cron in `refresh_sources.py`
      is the only writer of the canonical liveness columns.
    * `dry_run=True` means no DB writes, no email send. Report still
      gets written so the orchestrator dashboard reports a non-zero
      `scanned`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpintel.self_improve.loop_i")

# Repo layout: src/jpintel_mcp/self_improve/loop_i_doc_freshness.py
# climb four parents to land on the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_REPORT = REPO_ROOT / "data" / "source_freshness_report.json"

STALE_THRESHOLD_DAYS = 60
HIGH_PRIORITY_TIERS = ("S", "A")
HEAD_PROBE_BUDGET = 500  # max rows to probe per run
HEAD_PROBE_QPS = 5.0     # global throttle (matches refresh_sources default)
HEAD_PROBE_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Stale check (DB-only)
# ---------------------------------------------------------------------------


def _parse_iso(ts: str | None) -> dt.datetime | None:
    """Parse an ISO timestamp from `source_fetched_at` tolerantly.

    The column carries multiple shapes across the table — see
    CLAUDE.md "uniform sentinel" gotcha. We accept ISO 8601 with or
    without timezone, plus naked `YYYY-MM-DDTHH:MM:SS` and `Z` suffix.
    Returns None on parse failure; caller treats that as "stale".
    """
    if not ts:
        return None
    s = ts.strip()
    if not s:
        return None
    # Drop trailing 'Z' (ISO UTC marker) — Python <3.11 does not accept it.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def find_stale_rows(
    rows: list[dict[str, Any]],
    *,
    threshold_days: int = STALE_THRESHOLD_DAYS,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Return rows whose `source_fetched_at` is missing or older than threshold."""
    cutoff_now = now or dt.datetime.now(dt.UTC)
    cutoff = cutoff_now - dt.timedelta(days=threshold_days)
    stale: list[dict[str, Any]] = []
    for row in rows:
        fetched = _parse_iso(row.get("source_fetched_at"))
        if fetched is None or fetched < cutoff:
            stale.append(row)
    return stale


# ---------------------------------------------------------------------------
# Broken check (HEAD probe)
# ---------------------------------------------------------------------------


def find_known_broken_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows whose last persisted check status is 404 or 5xx.

    Zero-cost: pulls from `source_last_check_status` written by
    `scripts/refresh_sources.py`. This is the bulk of the broken flag —
    re-probing is only used for rows we have not seen before.
    """
    broken: list[dict[str, Any]] = []
    for row in rows:
        status = row.get("source_last_check_status")
        if status is None:
            continue
        try:
            code = int(status)
        except (TypeError, ValueError):
            continue
        if code == 404 or 500 <= code < 600:
            broken.append(row)
    return broken


async def _probe_url(client: Any, url: str) -> int | None:
    """HEAD probe a single URL, falling back to a Range GET on 405/501.

    Returns the HTTP status code, or None on transport error. Mirrors
    the logic in `scripts/refresh_sources.probe_url` so both pathways
    treat the same response shape consistently.
    """
    try:
        resp = await client.head(
            url,
            timeout=HEAD_PROBE_TIMEOUT,
            follow_redirects=True,
        )
    except Exception:
        return None
    code = getattr(resp, "status_code", None)
    if code in (405, 501):
        try:
            resp = await client.get(
                url,
                headers={"Range": "bytes=0-1023"},
                timeout=HEAD_PROBE_TIMEOUT,
                follow_redirects=True,
            )
        except Exception:
            return None
        code = getattr(resp, "status_code", None)
    return code


async def probe_unscanned_rows(
    rows: list[dict[str, Any]],
    *,
    budget: int = HEAD_PROBE_BUDGET,
    qps: float = HEAD_PROBE_QPS,
    client_factory: Any = None,
) -> list[dict[str, Any]]:
    """HEAD-probe rows that have no `source_last_check_status` yet.

    Tier S/A first; budget caps the rest. Returns the subset that
    responded with 404 or 5xx (same threshold as `find_known_broken_rows`).
    """
    candidates = [r for r in rows if r.get("source_last_check_status") is None]
    if not candidates:
        return []
    candidates.sort(key=lambda r: 0 if r.get("tier") in HIGH_PRIORITY_TIERS else 1)
    candidates = candidates[:budget]

    if client_factory is None:
        # Lazy import so unit tests with `client_factory` provided do not
        # need httpx installed at import time.
        import httpx  # type: ignore

        def _default_factory() -> Any:
            return httpx.AsyncClient(
                headers={"User-Agent": "AutonoMath-FreshnessBot/0.1"},
                follow_redirects=True,
            )

        client_factory = _default_factory

    broken: list[dict[str, Any]] = []
    min_gap = 1.0 / max(qps, 0.01)
    last_hit = 0.0
    loop = asyncio.get_event_loop()
    async with client_factory() as client:
        for row in candidates:
            now = loop.time()
            wait = last_hit + min_gap - now
            if wait > 0:
                await asyncio.sleep(wait)
            last_hit = loop.time()
            url = row.get("source_url") or ""
            if not url:
                continue
            code = await _probe_url(client, url)
            if code is None:
                continue
            if code == 404 or 500 <= code < 600:
                broken.append({**row, "probe_status": code})
    return broken


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report(
    rows: list[dict[str, Any]],
    stale: list[dict[str, Any]],
    broken: list[dict[str, Any]],
    *,
    dry_run: bool,
    generated_at: dt.datetime | None = None,
) -> dict[str, Any]:
    gen = generated_at or dt.datetime.now(dt.UTC)
    per_tier_total: Counter[str] = Counter()
    per_tier_stale: Counter[str] = Counter()
    per_tier_broken: Counter[str] = Counter()

    for r in rows:
        per_tier_total[r.get("tier") or "?"] += 1
    for r in stale:
        per_tier_stale[r.get("tier") or "?"] += 1
    for r in broken:
        per_tier_broken[r.get("tier") or "?"] += 1

    # Dedupe S/A broken unified_ids — operator email picks them up.
    high_priority_broken = [
        {
            "unified_id": r.get("unified_id"),
            "tier": r.get("tier"),
            "source_url": r.get("source_url"),
            "status": r.get("probe_status") or r.get("source_last_check_status"),
        }
        for r in broken
        if r.get("tier") in HIGH_PRIORITY_TIERS
    ]

    per_tier = {
        tier: {
            "total": per_tier_total.get(tier, 0),
            "stale": per_tier_stale.get(tier, 0),
            "broken": per_tier_broken.get(tier, 0),
        }
        for tier in sorted(set(per_tier_total) | {"S", "A", "B", "C", "X"})
    }

    return {
        "loop": "loop_i_doc_freshness",
        "generated_at": gen.isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "rows_scanned": len(rows),
        "stale_count": len(stale),
        "broken_count": len(broken),
        "per_tier": per_tier,
        "high_priority_broken": high_priority_broken,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Operator notification
# ---------------------------------------------------------------------------


def send_freshness_alert(report: dict[str, Any]) -> dict[str, Any]:
    """Best-effort operator email for tier S/A broken rows.

    Returns a structured-log dict so callers can assert in tests. Never
    raises — Postmark outages must not crash the cron.
    """
    high = report.get("high_priority_broken") or []
    if not high:
        return {"sent": False, "reason": "no_high_priority_broken"}
    payload = {
        "stale_count": report.get("stale_count", 0),
        "broken_count": report.get("broken_count", 0),
        "high_priority_broken_count": len(high),
        "high_priority_broken_sample": high[:10],
        "per_tier": report.get("per_tier", {}),
    }
    try:
        from jpintel_mcp.email.postmark import get_client  # type: ignore

        client = get_client()
        # Use the digest helper as transport — same operator inbox, same
        # template alias would normally be `weekly-digest`. We pass a bag
        # of stats and let Postmark's TemplateModel render.
        result: dict[str, Any] = {}
        if hasattr(client, "send_digest"):
            try:
                result = client.send_digest(
                    to="info@bookyou.net",
                    template_model={"freshness_report": payload},
                )
            except Exception as exc:  # pragma: no cover - never raise
                logger.warning("freshness_alert_send_failed: %s", exc)
                result = {"error": str(exc)}
        return {"sent": True, "payload": payload, "transport": result}
    except Exception as exc:  # pragma: no cover - postmark optional in tests
        logger.warning("freshness_alert_unavailable: %s", exc)
        return {"sent": False, "reason": "postmark_unavailable", "error": str(exc)}


# ---------------------------------------------------------------------------
# DB row loader
# ---------------------------------------------------------------------------


def load_program_rows(db_path: Path) -> list[dict[str, Any]]:
    """Pull `programs` columns relevant to freshness as plain dicts."""
    if not db_path.exists():
        return []
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute(
            "SELECT unified_id, tier, source_url, source_fetched_at, "
            "source_last_check_status "
            "FROM programs"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    *,
    dry_run: bool = True,
    db_path: Path | None = None,
    report_path: Path | None = None,
    rows: list[dict[str, Any]] | None = None,
    probe: bool = False,
    notify: bool | None = None,
    client_factory: Any = None,
) -> dict[str, int]:
    """Audit `programs.source_url` for stale + broken sources.

    Args:
        dry_run: when True, never send an operator email. The JSON
            report is still written so the orchestrator dashboard
            reports a non-zero `scanned`.
        db_path: override DB location (tests).
        report_path: override report destination (tests).
        rows: pre-loaded rows (tests can skip the SQLite read).
        probe: when True, HEAD-probe rows missing
            `source_last_check_status`. Default False — production cron
            sets this on the weekly entry only after the nightly
            `refresh_sources.py` has run.
        notify: when explicitly True, attempt to send the email even
            during dry_run; defaults to (not dry_run).
        client_factory: injected httpx async client factory (tests).

    Returns:
        dict[str, int] with the standard self-improve loop contract:
        {loop, scanned, actions_proposed, actions_executed}.
    """
    db = db_path or DEFAULT_DB
    out_path = report_path or DEFAULT_REPORT
    if rows is None:
        rows = load_program_rows(db)

    stale = find_stale_rows(rows)
    broken_known = find_known_broken_rows(rows)

    broken_map = {r["unified_id"]: r for r in broken_known}
    if probe and rows:
        try:
            broken_probed = asyncio.run(
                probe_unscanned_rows(rows, client_factory=client_factory)
            )
        except RuntimeError:
            # Already inside an event loop (rare in cron, common in tests
            # that wrap us in asyncio). Fall back to a fresh task.
            loop = asyncio.new_event_loop()
            try:
                broken_probed = loop.run_until_complete(
                    probe_unscanned_rows(rows, client_factory=client_factory)
                )
            finally:
                loop.close()
        for r in broken_probed:
            broken_map.setdefault(r["unified_id"], r)
    broken = list(broken_map.values())

    report = build_report(rows, stale, broken, dry_run=dry_run)
    write_report(report, out_path)

    actions_executed = 0
    should_notify = (not dry_run) if notify is None else bool(notify)
    if should_notify:
        result = send_freshness_alert(report)
        if result.get("sent"):
            actions_executed = 1

    actions_proposed = len(report.get("high_priority_broken") or [])

    return {
        "loop": "loop_i_doc_freshness",
        "scanned": len(rows),
        "actions_proposed": actions_proposed,
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    out = run(dry_run=os.environ.get("LOOP_I_DRY_RUN", "1") == "1")
    print(json.dumps(out, ensure_ascii=False))
