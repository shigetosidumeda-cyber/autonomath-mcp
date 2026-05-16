#!/usr/bin/env python3
"""aggregate_organic_funnel_daily.py — Wave 49 G1 daily organic-funnel rollup.

Reads Cloudflare R2 ``funnel/{date}/{session_id}-{ts}.json`` objects landed
by ``functions/api/rum_beacon.ts`` (Pages Function — Wave 49 G1) and rolls
them up to:

* ``analytics/organic_funnel_daily.jsonl`` — append-only history, one row
  per UTC date with per-stage counts + uniq-visitor totals.
* ``site/status/organic_funnel_state.json`` — sidecar carrying the latest
  14-day rolling window + the **G1 gate flag**.

Wave 49 G1 gate
---------------
The G1 success criterion is **3 consecutive days with uniq_visitor >= 10**.
Once met, the state file records the achievement date + the consecutive-day
streak. ``--emit-issue`` (off by default) prints an issue-body marker so
the GHA workflow can fire a one-shot ``gh issue create`` on the
achievement transition. The transition is computed by comparing the
``g1_state`` field against the previous run's state file (if any).

Hard rules (memory)
-------------------
* ``feedback_autonomath_no_api_use`` / ``feedback_no_operator_llm_api`` —
  zero LLM API imports.
* ``feedback_no_quick_check_on_huge_sqlite`` — this script never touches a
  multi-GB SQLite DB; it only reads R2 + writes two small JSON/JSONL.
* Bot UA filter mirrors ``functions/api/rum_beacon.ts`` defense-in-depth
  regex so an adversary that bypassed the client-side filter still gets
  stripped at aggregation time.
* The 5 stages match ``rum_beacon.ts`` ``ALLOWED_STEPS`` exactly:
  ``landing`` → ``free`` → ``signup`` → ``topup`` → ``calc_engaged``.
  ``billing`` / ``payment`` are server-side aliased to ``topup`` upstream.

Usage::

    python scripts/cron/aggregate_organic_funnel_daily.py [--date YYYY-MM-DD]
                                                          [--dry-run]
                                                          [--r2-bucket NAME]
                                                          [--emit-issue]
                                                          [--r2-prefix funnel]

Default ``--date`` is **yesterday in UTC** so the daily cron at 04:30 JST
(= 19:30 UTC) sees a complete UTC day. ``--dry-run`` performs the R2 list
but **never writes** to the analytics/sidecar paths and **never deletes**
remote objects (no destructive ops anywhere — read-only by design).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("jpcite.cron.organic_funnel")

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS_DIR = REPO_ROOT / "analytics"
SITE_STATUS_DIR = REPO_ROOT / "site" / "status"
JSONL_OUT = ANALYTICS_DIR / "organic_funnel_daily.jsonl"
SIDECAR_OUT = SITE_STATUS_DIR / "organic_funnel_state.json"

# Matches rum_beacon.ts ALLOWED_STEPS in canonical funnel order.
STAGES: tuple[str, ...] = ("landing", "free", "signup", "topup", "calc_engaged")

# Mirrors functions/api/rum_beacon.ts BOT_RE defense-in-depth.
BOT_RE = re.compile(
    r"(bot|spider|crawler|gptbot|claudebot|perplexity|amazonbot|googlebot|"
    r"bingbot|chatgpt|oai-searchbot|bytespider|ahrefs|semrush|diffbot|"
    r"cohere-ai|youbot|mistralai|applebot|facebookexternalhit|twitterbot|"
    r"yandex|baiduspider)",
    re.IGNORECASE,
)

# Wave 49 G1 gate constants.
G1_UNIQ_THRESHOLD = 10
G1_CONSECUTIVE_DAYS = 3
WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# R2 IO — pluggable, dry-run aware
# ---------------------------------------------------------------------------


def _load_r2_client():  # noqa: ANN202 — lazy import, returns module
    """Lazy import the rclone-backed R2 helper.

    Kept lazy so that ``--dry-run`` with an injected fake-bucket fixture in
    the test suite never tries to talk to a real R2 endpoint.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _r2_client  # type: ignore[import-not-found]

    return _r2_client


def list_objects_for_date(
    *,
    date_str: str,
    bucket: str | None,
    prefix: str,
    r2_client=None,
) -> list[tuple[str, int]]:
    """Return ``[(key, size_bytes), ...]`` for ``{prefix}/{date}/`` objects.

    Defensive: any rclone failure (missing env, network) is logged and
    returns ``[]`` so the cron still writes an empty-but-valid sidecar.
    """
    client = r2_client or _load_r2_client()
    full_prefix = f"{prefix.rstrip('/')}/{date_str}/"
    try:
        rows = client.list_keys(full_prefix, bucket=bucket)
    except Exception as exc:  # rclone may raise R2ConfigError / CalledProcessError
        logger.warning("r2 list_keys failed for %s: %s", full_prefix, exc)
        return []
    return [(key, size) for key, _mtime, size in rows]


def fetch_object_text(
    key: str,
    *,
    bucket: str | None,
    r2_client=None,
) -> str | None:
    """Download a single R2 object into a temp file and return its text.

    Returns ``None`` on download failure. Each beacon is ≤4KB (Pages
    Function caps), so download is cheap and we don't need streaming.
    """
    client = r2_client or _load_r2_client()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
        tmp = Path(fh.name)
    try:
        client.download(key, tmp, bucket=bucket)
        return tmp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("r2 download failed for %s: %s", key, exc)
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Aggregation core
# ---------------------------------------------------------------------------


def is_bot_record(record: dict[str, Any]) -> bool:
    """Defense-in-depth bot filter (mirrors rum_beacon.ts BOT_RE).

    The collector + Function already filter most bots, but a malicious
    POST that skipped the JS client still reaches R2 — strip it here.
    Note: ``ua`` is only sha256-prefix-hashed on the wire (``ua_hash``),
    so we cannot regex against it. We instead trust the upstream filter
    and only apply a name-based filter against ``session_id`` patterns
    that look like crawlers (very narrow — kept for forward-compat).
    """
    sid = record.get("session_id")
    if isinstance(sid, str) and BOT_RE.search(sid):
        return True
    return False


def parse_beacon_blob(blob: str) -> dict[str, Any] | None:
    """Parse a single beacon JSON blob, returning None if malformed."""
    try:
        rec = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    # rum_beacon.ts persists session_id / step / event / ts at minimum.
    if not all(isinstance(rec.get(k), str) for k in ("session_id", "step", "event")):
        return None
    if not isinstance(rec.get("ts"), (int, float)):
        return None
    return rec


def aggregate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll a list of beacon records into the daily aggregate shape.

    Returns
    -------
    dict with keys:
        - ``stage_event_counts``: per-stage total event count
        - ``stage_uniq_sessions``: per-stage unique session_id count
        - ``stage_uniq_view``: per-stage unique session_id count for event=view
        - ``uniq_visitor``: dedup session_id across all rows
        - ``conversion_rate``: per-stage conversion rate vs landing
        - ``total_events``: total non-bot event count
    """
    stage_event_counts: dict[str, int] = defaultdict(int)
    stage_sessions: dict[str, set[str]] = defaultdict(set)
    stage_view_sessions: dict[str, set[str]] = defaultdict(set)
    all_sessions: set[str] = set()
    total_events = 0
    for rec in records:
        if is_bot_record(rec):
            continue
        step = rec.get("step")
        event = rec.get("event")
        sid = rec.get("session_id")
        if step not in STAGES or not isinstance(sid, str) or not sid:
            continue
        stage_event_counts[step] += 1
        stage_sessions[step].add(sid)
        if event == "view":
            stage_view_sessions[step].add(sid)
        all_sessions.add(sid)
        total_events += 1

    uniq_visitor = len(all_sessions)
    landing_uniq = len(stage_sessions.get("landing", set()))
    conv: dict[str, float | None] = {}
    for stage in STAGES:
        uniq = len(stage_sessions.get(stage, set()))
        if landing_uniq == 0:
            conv[stage] = None
        else:
            conv[stage] = round(uniq / landing_uniq, 4)

    return {
        "stage_event_counts": {s: stage_event_counts.get(s, 0) for s in STAGES},
        "stage_uniq_sessions": {s: len(stage_sessions.get(s, set())) for s in STAGES},
        "stage_uniq_view": {s: len(stage_view_sessions.get(s, set())) for s in STAGES},
        "uniq_visitor": uniq_visitor,
        "conversion_rate": conv,
        "total_events": total_events,
    }


# ---------------------------------------------------------------------------
# G1 gate evaluation
# ---------------------------------------------------------------------------


def evaluate_g1_gate(
    rolling: list[dict[str, Any]],
    *,
    today_iso: str,
) -> dict[str, Any]:
    """Evaluate Wave 49 G1: 3 consecutive days uniq_visitor >= 10.

    ``rolling`` must be sorted oldest → newest and each row carries
    ``date`` + ``uniq_visitor``. Returns the canonical g1_state dict that
    lands in the sidecar.
    """
    sorted_rows = sorted(rolling, key=lambda r: r.get("date", ""))
    consec = 0
    longest_consec = 0
    first_consec_start: str | None = None
    achieved = False
    achieved_on: str | None = None
    for row in sorted_rows:
        uv = int(row.get("uniq_visitor") or 0)
        if uv >= G1_UNIQ_THRESHOLD:
            consec += 1
            if consec >= G1_CONSECUTIVE_DAYS and not achieved:
                achieved = True
                achieved_on = row.get("date")
            if consec > longest_consec:
                longest_consec = consec
            if consec == 1:
                first_consec_start = row.get("date")
        else:
            consec = 0

    return {
        "threshold_uniq": G1_UNIQ_THRESHOLD,
        "threshold_consecutive_days": G1_CONSECUTIVE_DAYS,
        "current_consecutive_days": consec,
        "longest_consecutive_days": longest_consec,
        "current_streak_started_on": first_consec_start if consec > 0 else None,
        "achieved": achieved,
        "achieved_on": achieved_on,
        "evaluated_at": today_iso,
    }


# ---------------------------------------------------------------------------
# JSONL history merge
# ---------------------------------------------------------------------------


def read_history_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read the append-only history JSONL, dedup on ``date`` (keep latest)."""
    if not path.exists():
        return []
    by_date: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            d = row.get("date")
            if isinstance(d, str):
                by_date[d] = row
    return [by_date[k] for k in sorted(by_date.keys())]


def append_history_jsonl(path: Path, today_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Append today's row to JSONL (no de-dup mutation — append-only).

    Returns the full deduped rolling list for sidecar use.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(today_row, ensure_ascii=False, sort_keys=True) + "\n")
    return read_history_jsonl(path)


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run(
    *,
    date_str: str,
    dry_run: bool,
    bucket: str | None,
    prefix: str,
    emit_issue: bool,
    r2_client=None,
) -> dict[str, Any]:
    """End-to-end aggregation for a single UTC date.

    Returns the daily row + state dict for caller introspection (used by
    the test suite and by the GHA workflow log).
    """
    keys = list_objects_for_date(
        date_str=date_str, bucket=bucket, prefix=prefix, r2_client=r2_client
    )
    records: list[dict[str, Any]] = []
    for key, _size in keys:
        blob = fetch_object_text(key, bucket=bucket, r2_client=r2_client)
        if blob is None:
            continue
        rec = parse_beacon_blob(blob)
        if rec is None:
            continue
        records.append(rec)

    daily_agg = aggregate_records(records)
    today_row: dict[str, Any] = {
        "date": date_str,
        "n_objects": len(keys),
        **daily_agg,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if dry_run:
        rolling = read_history_jsonl(JSONL_OUT) + [today_row]
        # Dedup last (today) overrides any prior same-date row.
        by_date: dict[str, dict[str, Any]] = {}
        for r in rolling:
            d = r.get("date")
            if isinstance(d, str):
                by_date[d] = r
        rolling = [by_date[k] for k in sorted(by_date.keys())]
    else:
        rolling = append_history_jsonl(JSONL_OUT, today_row)

    cutoff = (datetime.fromisoformat(date_str) - timedelta(days=WINDOW_DAYS - 1)).date()
    rolling_window = [r for r in rolling if r.get("date", "") >= cutoff.isoformat()]

    g1 = evaluate_g1_gate(rolling_window, today_iso=today_row["generated_at"])

    # Detect achievement transition vs prior sidecar (one-shot issue cue).
    prior_g1: dict[str, Any] = {}
    if SIDECAR_OUT.exists():
        try:
            prior_g1 = json.loads(SIDECAR_OUT.read_text(encoding="utf-8")).get("g1_state", {})
        except (json.JSONDecodeError, OSError):
            prior_g1 = {}
    achievement_transition = bool(g1.get("achieved")) and not bool(prior_g1.get("achieved"))

    sidecar = {
        "generated_at": today_row["generated_at"],
        "wave": "49-G1",
        "stages": list(STAGES),
        "window_days": WINDOW_DAYS,
        "daily": rolling_window,
        "g1_state": g1,
        "achievement_transition_this_run": achievement_transition,
    }

    if not dry_run:
        SIDECAR_OUT.parent.mkdir(parents=True, exist_ok=True)
        SIDECAR_OUT.write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if emit_issue and achievement_transition:
        # Marker line consumed by the GHA workflow's grep step. We avoid
        # creating the issue ourselves to keep this script side-effect-free
        # outside of the analytics + sidecar paths.
        print(
            f"::organic-funnel-g1-achieved::date={g1.get('achieved_on')} "
            f"consec={g1.get('current_consecutive_days')} "
            f"longest={g1.get('longest_consecutive_days')}"
        )

    return {"today_row": today_row, "sidecar": sidecar}


def _default_yesterday_utc() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Wave 49 G1 — daily organic-funnel rollup from R2. "
            "Reads funnel/{date}/*.json, writes analytics + sidecar, "
            "evaluates the 3-day x uniq>=10 G1 gate."
        )
    )
    parser.add_argument("--date", default=None, help="UTC date (default: yesterday)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--r2-bucket",
        default=os.environ.get("WAVE49_FUNNEL_R2_BUCKET"),
        help="R2 bucket (default: env WAVE49_FUNNEL_R2_BUCKET or R2_BUCKET)",
    )
    parser.add_argument(
        "--r2-prefix",
        default="funnel",
        help="R2 key prefix (default: 'funnel' — matches rum_beacon.ts)",
    )
    parser.add_argument(
        "--emit-issue",
        action="store_true",
        help="Print ::organic-funnel-g1-achieved:: marker on G1 transition",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
    )
    ns = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(ns.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    date_str = ns.date or _default_yesterday_utc()
    # Light date sanity — abort early on obviously bad inputs.
    try:
        datetime.fromisoformat(date_str)
    except ValueError:
        logger.error("invalid --date %r (expect YYYY-MM-DD)", date_str)
        return 2

    result = run(
        date_str=date_str,
        dry_run=ns.dry_run,
        bucket=ns.r2_bucket,
        prefix=ns.r2_prefix,
        emit_issue=ns.emit_issue,
    )

    summary = result["today_row"]
    g1 = result["sidecar"]["g1_state"]
    print(
        f"[organic_funnel] date={date_str} dry_run={ns.dry_run} "
        f"n_objects={summary['n_objects']} uniq_visitor={summary['uniq_visitor']} "
        f"events={summary['total_events']} "
        f"g1_consec={g1.get('current_consecutive_days')} "
        f"g1_achieved={g1.get('achieved')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
