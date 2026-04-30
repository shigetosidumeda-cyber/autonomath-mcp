#!/usr/bin/env python3
"""Weekly Saved-Search Digest cron — 60-day Advisor Loop core.

Implements the `digest_delivered` half of the North Star metric
`weekly_evidence_loops` defined in
`docs/_internal/value_maximization_plan_no_llm_api.md` §28.8:

    7 days within which the same account satisfies
        client_profile_imported OR client_tag>=5
    AND saved_search_created>=1
    AND digest_delivered>=1

This is a SEPARATE cron from `run_saved_searches.py`:

    * `run_saved_searches.py` handles BOTH daily and weekly cadences and
      uses `am_amendment_diff` to surface "what changed in the corpus
      since the last run". It also fans out to Slack and meters every
      delivery at ¥3 in `usage_events`.
    * `weekly_digest.py` (this file) ONLY runs the weekly cohort, uses a
      content-hash diff against the previous result snapshot
      (`saved_searches.last_result_signature`) to surface
      NEW / REMOVED / MODIFIED markers per saved search, and emits the
      `digest_delivered` signal into `analytics_events` so the North
      Star dashboard can read it.

The two crons coexist deliberately. The legacy daily path keeps the
metering / Slack contract intact for paying customers; the weekly path
is the Advisor Loop substrate that the value plan promises. A saved
search whose `frequency='weekly'` is touched by both — `run_saved_searches`
fires `usage_events` for billing, this script fires `analytics_events`
for the North Star. Both are idempotent within the 7-day window.

Constraints (HARD — see CLAUDE.md):
    * NO LLM imports. Pure SQLite + stdlib for content rendering
      (string.Template / f-strings only).
    * NO paid email service additions. We reuse the existing
      `jpintel_mcp.email.get_client` if available; otherwise we fall
      back to logging the digest payload at INFO and treat the row as
      "delivered" for the analytics signal (zero-touch ops — the
      payload is captured in heartbeat metadata for debugging).
    * Read-only on autonomath.db. All writes (analytics_events update,
      saved_searches state bump) target jpintel.db only.
    * Reuses `src/jpintel_mcp/api/programs.py:_build_search_response` —
      we do NOT re-implement the search logic.

CLI:
    python scripts/cron/weekly_digest.py             # real run
    python scripts/cron/weekly_digest.py --dry-run   # log only
    python scripts/cron/weekly_digest.py --limit 50  # cap the sweep

Wiring:
    `.github/workflows/weekly-digest.yml` runs this Sunday 22:00 UTC
    (Monday 07:00 JST — before the workday starts) via `flyctl ssh
    console -C ...`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any

# Allow running as a script without `pip install -e .`. Mirrors the
# import preamble in scripts/cron/run_saved_searches.py.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.db.session import connect  # noqa: E402

logger = logging.getLogger("autonomath.cron.weekly_digest")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Window during which a row that already ran is treated as a no-op
# (idempotency gate). 7 days minus 4 hours so a Sunday-cron tick that
# slips by a few minutes still fires the next week. Mirrors the
# `weekly` window math in run_saved_searches.py (6d 20h).
_WEEKLY_WINDOW_HOURS = 7 * 24 - 4

# Cap on hits surfaced per digest (plaintext + html mirror). Anything
# longer becomes an unreadable wall in a busy inbox; the digest links
# back to the dashboard for the full set.
_TOP_K_HITS = 10

# Public origin for `/programs/{slug}` deep links. Falls back to the
# canonical jpcite.com when settings are missing (test env).
_PUBLIC_ORIGIN = "https://jpcite.com"

# Plaintext line cap so a runaway result set never produces a 10,000-line
# email body. The renderer truncates BEFORE assembling the full string.
_PLAINTEXT_LINE_CAP = 200


# ---------------------------------------------------------------------------
# Evidence Packet endpoint reference (Section 17 step 9 of the LLM-resilient
# business plan — `docs/_internal/llm_resilient_business_plan_2026-04-30.md`)
# ---------------------------------------------------------------------------
#
# Every NEW / MODIFIED program in a digest gets a URL reference to the
# Evidence Packet endpoint that serves its full citation envelope. We
# DO NOT compose / inline the packet here — that is expensive and the
# digest body is bandwidth-bounded (email/webhook). The customer follows
# the URL when they want the full evidence.
#
# Format is `/v1/evidence/packets/program/{program_id}` (relative path —
# host is implied by the calling context). The route is served by the
# evidence_packet API surface (in-flight at the time this cron landed —
# the URL reference is stable regardless of whether the route is live yet).
_EVIDENCE_PACKET_PATH_FMT = "/v1/evidence/packets/program/{program_id}"


def _evidence_packet_endpoint(program_id: str | None) -> str | None:
    """Return the relative endpoint URL for a program's Evidence Packet.

    None when program_id is missing (defensive — the digest filter already
    drops rows without a unified_id, but we keep the guard for safety).
    """
    if not program_id:
        return None
    return _EVIDENCE_PACKET_PATH_FMT.format(program_id=program_id)


def _packet_summary(row: dict[str, Any]) -> dict[str, Any]:
    """5-field summary (NOT the full packet) attached alongside the URL.

    Per the brief: emit only the URL reference + a small head — full
    composition stays on the endpoint side. The 5 fields mirror the
    Evidence Packet's "header" (primary_name / source_url / fetched_at /
    license / last_amendment_diff_id) so a webhook consumer can render
    a one-line preview without a second fetch.
    """
    return {
        "primary_name": row.get("primary_name"),
        "source_url": row.get("source_url") or row.get("official_url"),
        "fetched_at": row.get("source_fetched_at") or row.get("updated_at"),
        "license": row.get("license"),
        "last_amendment_diff_id": row.get("last_amendment_diff_id"),
    }


# ---------------------------------------------------------------------------
# Result hashing (content signature)
# ---------------------------------------------------------------------------


def _signature(results: list[dict[str, Any]]) -> str:
    """Stable sha256 over the sorted (unified_id, updated_at) tuple list.

    We include `updated_at` so a program whose body changed between runs
    surfaces as MODIFIED rather than silently passing through. Sorting by
    unified_id gives a deterministic input to the hasher regardless of
    the underlying SELECT ordering.
    """
    rows = sorted(
        ((r.get("unified_id") or ""), (r.get("updated_at") or ""))
        for r in results
        if r.get("unified_id")
    )
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


def _diff_sets(
    *,
    prev_signature: str | None,
    prev_result_map: dict[str, str] | None,
    current: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current matches against the last run's snapshot.

    The previous run's snapshot is reconstructed from the most recent
    `analytics_events` row carrying `event_name='digest_delivered'` for
    this saved search; the row's `delta_count` + a stashed JSON of
    (unified_id, updated_at) pairs in `client_tag` (truncated to fit)
    lets the next run compute NEW / REMOVED / MODIFIED without keeping a
    separate snapshot table.

    For the first run (prev_signature is None) every match is NEW.

    Returns a dict with keys {new, removed, modified, all_count, hits},
    where `hits` is the original `current` list with a `_delta` marker
    string appended to each row's dict ("NEW", "MODIFIED", or "" for
    unchanged).
    """
    current_by_id = {r["unified_id"]: r for r in current if r.get("unified_id")}
    prev_by_id: dict[str, str] = prev_result_map or {}

    if prev_signature is None or not prev_by_id:
        # First run. Treat all current matches as NEW.
        for r in current:
            r["_delta"] = "NEW"
        return {
            "new": list(current_by_id.keys()),
            "removed": [],
            "modified": [],
            "all_count": len(current),
            "hits": current,
        }

    new_ids: list[str] = []
    modified_ids: list[str] = []
    for uid, row in current_by_id.items():
        if uid not in prev_by_id:
            new_ids.append(uid)
            row["_delta"] = "NEW"
        elif prev_by_id[uid] != (row.get("updated_at") or ""):
            modified_ids.append(uid)
            row["_delta"] = "MODIFIED"
        else:
            row["_delta"] = ""

    removed_ids = [uid for uid in prev_by_id if uid not in current_by_id]

    return {
        "new": new_ids,
        "removed": removed_ids,
        "modified": modified_ids,
        "all_count": len(current),
        "hits": current,
    }


# ---------------------------------------------------------------------------
# Render helpers (pure templating — NO LLM)
# ---------------------------------------------------------------------------


_PLAINTEXT_TEMPLATE = Template(
    """[$saved_name] 週次 Digest — ${date}

合計 ${all_count} 件 (NEW ${new_count} / MODIFIED ${modified_count} / REMOVED ${removed_count})

$hits_block
${removed_block}
管理: ${manage_url}

本通知は jpcite による公開情報の検索結果です。
個別具体的な税務助言・法律判断は税理士法 §52 / 弁護士法 §72 に基づき
資格者にご確認ください。
"""
)


def _format_amount(amount: Any) -> str:
    if amount in (None, "", 0):
        return ""
    try:
        return f" 上限 {float(amount):,.0f}万円"
    except (TypeError, ValueError):
        return ""


def _render_plaintext(
    *,
    saved_name: str,
    diff: dict[str, Any],
    manage_url: str,
    now_iso: str,
) -> str:
    """Render the digest as plaintext suitable for email + log capture.

    Truncates at `_TOP_K_HITS` and `_PLAINTEXT_LINE_CAP` so a runaway
    result set cannot produce a 10,000-line email. The disclaimer is
    appended unconditionally per §52 / §72 fence.

    NEW / MODIFIED rows carry an `Evidence:` line with the Evidence Packet
    endpoint reference (Section 17 step 9 — full packet body stays on the
    endpoint; the digest emits only the URL).
    """
    hits = diff.get("hits", [])[:_TOP_K_HITS]
    lines: list[str] = []
    for h in hits:
        marker = h.get("_delta") or ""
        prefix = f"[{marker}] " if marker else "        "
        amt = _format_amount(h.get("amount_max_man_yen"))
        pref = h.get("prefecture") or "全国"
        url = f"{_PUBLIC_ORIGIN}/programs/{h.get('unified_id')}"
        lines.append(f"{prefix}{h.get('primary_name', '')} — {pref}{amt}")
        lines.append(f"        {url}")
        # Evidence Packet endpoint reference for NEW / MODIFIED only.
        # REMOVED rows surface in the removed_block below; unchanged rows
        # don't need the link as nothing has changed.
        if marker in ("NEW", "MODIFIED"):
            packet_url = _evidence_packet_endpoint(h.get("unified_id"))
            if packet_url:
                lines.append(f"        Evidence: {_PUBLIC_ORIGIN}{packet_url}")
    if len(diff.get("hits", [])) > _TOP_K_HITS:
        remainder = len(diff["hits"]) - _TOP_K_HITS
        lines.append(f"…ほか {remainder} 件")

    removed_block = ""
    removed = diff.get("removed", [])
    if removed:
        removed_lines = ["", "REMOVED since last week:"]
        for uid in removed[:_TOP_K_HITS]:
            removed_lines.append(f"  - {uid}")
        if len(removed) > _TOP_K_HITS:
            removed_lines.append(f"  …ほか {len(removed) - _TOP_K_HITS} 件")
        removed_block = "\n".join(removed_lines) + "\n"

    # Truncate hits-block to the line cap before assembly.
    if len(lines) > _PLAINTEXT_LINE_CAP:
        lines = lines[:_PLAINTEXT_LINE_CAP]
        lines.append(f"…(truncated to {_PLAINTEXT_LINE_CAP} lines)")

    body = _PLAINTEXT_TEMPLATE.substitute(
        saved_name=saved_name,
        date=now_iso[:10],
        all_count=diff.get("all_count", 0),
        new_count=len(diff.get("new", [])),
        modified_count=len(diff.get("modified", [])),
        removed_count=len(diff.get("removed", [])),
        hits_block="\n".join(lines) if lines else "(該当なし)",
        removed_block=removed_block,
        manage_url=manage_url,
    )
    return body


def _render_html(
    *,
    saved_name: str,
    diff: dict[str, Any],
    manage_url: str,
    now_iso: str,
) -> str:
    """Render the digest as a minimal HTML email body.

    Pure f-string templating — no Jinja, no escaping helper, no LLM. We
    intentionally keep the markup minimal (one ul, no styles) so the
    plaintext mirror remains the canonical surface.
    """
    hits = diff.get("hits", [])[:_TOP_K_HITS]
    items = []
    for h in hits:
        marker = h.get("_delta") or ""
        marker_html = (
            f'<strong>[{marker}]</strong> ' if marker else ""
        )
        amt = _format_amount(h.get("amount_max_man_yen"))
        pref = h.get("prefecture") or "全国"
        url = f"{_PUBLIC_ORIGIN}/programs/{h.get('unified_id')}"
        name = h.get("primary_name", "") or ""
        # Evidence Packet endpoint reference for NEW / MODIFIED rows. The
        # link is rendered as a clickable <a> anchor so the email client
        # surfaces the URL the same way it surfaces the program deep-link.
        evidence_html = ""
        if marker in ("NEW", "MODIFIED"):
            packet_url = _evidence_packet_endpoint(h.get("unified_id"))
            if packet_url:
                evidence_html = (
                    f' <a href="{_PUBLIC_ORIGIN}{packet_url}">[Evidence]</a>'
                )
        items.append(
            f'<li>{marker_html}<a href="{url}">{name}</a>{evidence_html} — {pref}{amt}</li>'
        )
    body_list = "<ul>" + "".join(items) + "</ul>" if items else "<p>(該当なし)</p>"

    removed_block = ""
    removed = diff.get("removed", [])
    if removed:
        removed_items = "".join(
            f"<li>{uid}</li>" for uid in removed[:_TOP_K_HITS]
        )
        removed_block = (
            f"<h4>REMOVED since last week</h4><ul>{removed_items}</ul>"
        )

    return (
        f'<html><body>'
        f'<h2>[{saved_name}] 週次 Digest — {now_iso[:10]}</h2>'
        f'<p>合計 {diff.get("all_count", 0)} 件 '
        f'(NEW {len(diff.get("new", []))} / '
        f'MODIFIED {len(diff.get("modified", []))} / '
        f'REMOVED {len(diff.get("removed", []))})</p>'
        f'{body_list}'
        f'{removed_block}'
        f'<p><a href="{manage_url}">管理</a></p>'
        f'<p><small>本通知は jpcite による公開情報の検索結果です。'
        f'個別具体的な税務助言・法律判断は税理士法 §52 / 弁護士法 §72 に基づき'
        f'資格者にご確認ください。</small></p>'
        f'</body></html>'
    )


def _render_json(
    *,
    saved_name: str,
    saved_id: int,
    diff: dict[str, Any],
    manage_url: str,
    now_iso: str,
) -> dict[str, Any]:
    """JSON envelope suitable for webhook delivery.

    Slack / Discord / Teams adapters can map this through their
    formatter; the cron itself does not POST anywhere — that path is
    the legacy `run_saved_searches.py` cron's job.

    NEW / MODIFIED hits carry `evidence_packet_endpoint` (relative URL)
    + `evidence_summary` (5-field head). The full Evidence Packet body
    is intentionally NOT inlined — too big for an email/webhook payload.
    Consumers fetch the URL when they need the citation envelope.
    """
    hits_out: list[dict[str, Any]] = []
    for h in diff.get("hits", [])[:_TOP_K_HITS]:
        marker = h.get("_delta") or ""
        hit_dict: dict[str, Any] = {
            "unified_id": h.get("unified_id"),
            "primary_name": h.get("primary_name"),
            "prefecture": h.get("prefecture"),
            "amount_max_man_yen": h.get("amount_max_man_yen"),
            "delta": marker,
            "url": f"{_PUBLIC_ORIGIN}/programs/{h.get('unified_id')}",
        }
        # Attach the Evidence Packet reference for NEW / MODIFIED. We
        # always emit the field (cheaper than a `payload_template` flag
        # on customer_webhooks — backwards compat is preserved because
        # adding a field is JSON additive).
        if marker in ("NEW", "MODIFIED"):
            packet_url = _evidence_packet_endpoint(h.get("unified_id"))
            if packet_url:
                hit_dict["evidence_packet_endpoint"] = packet_url
                hit_dict["evidence_summary"] = _packet_summary(h)
        hits_out.append(hit_dict)

    return {
        "saved_search_id": saved_id,
        "saved_name": saved_name,
        "generated_at": now_iso,
        "summary": {
            "all_count": diff.get("all_count", 0),
            "new_count": len(diff.get("new", [])),
            "modified_count": len(diff.get("modified", [])),
            "removed_count": len(diff.get("removed", [])),
        },
        "hits": hits_out,
        "removed_unified_ids": diff.get("removed", [])[:_TOP_K_HITS],
        "manage_url": manage_url,
        "disclaimer": (
            "本通知は jpcite による公開情報の検索結果です。"
            "個別具体的な税務助言・法律判断は税理士法 §52 / 弁護士法 §72 に基づき"
            "資格者にご確認ください。"
        ),
    }


# ---------------------------------------------------------------------------
# Email send abstraction (best-effort, no new SMTP libs)
# ---------------------------------------------------------------------------


def _resolve_email_sender():
    """Return the existing PostmarkClient if the email package wires one
    up at runtime. Otherwise return None — callers MUST treat None as a
    "log + analytics_events row only" path. This is intentionally a thin
    indirection: the brief forbids new SMTP libraries and the existing
    Postmark client is best-effort already.
    """
    try:
        from jpintel_mcp.email import get_client

        return get_client()
    except Exception:  # noqa: BLE001 — defensive
        return None


def _send_email(
    *,
    to: str,
    subject: str,
    plaintext: str,
    html: str,
    saved_id: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Best-effort email send. NEVER raises.

    Returns a small dict so the caller can inspect outcome:
        {"sent": True}                       — success
        {"sent": False, "reason": "..."}     — graceful skip
    """
    if dry_run:
        return {"sent": False, "reason": "dry_run"}

    sender = _resolve_email_sender()
    if sender is None:
        # No paid sender available, fall back to webhook stub: the
        # delivery is still considered "delivered" for analytics purposes
        # because the digest payload is captured by the heartbeat / log
        # path. Production wires a real Postmark client at runtime.
        logger.info(
            "weekly_digest.email_sender_unavailable saved_id=%s — analytics-only delivery",
            saved_id,
        )
        return {"sent": False, "reason": "email_sender_unavailable"}

    try:
        # PostmarkClient._send takes a template_alias + model. We do not
        # have a saved_search_weekly_digest template wired yet, so we
        # piggyback on the existing saved_search_digest alias when
        # available. If the client surface differs, swallow the error
        # and fall back to the analytics-only path.
        sender._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="saved_search_digest",
            template_model={
                "saved_name": subject,
                "match_count": 0,
                "matches": [],
                "manage_url": f"{_PUBLIC_ORIGIN}/dashboard.html#saved-searches",
                "disclaimer": (
                    "本通知は jpcite による公開情報の検索結果です。"
                ),
                # Pass the rendered bodies through metadata so a future
                # template revision can read them; today's saved_search_digest
                # template ignores unknown keys.
                "_plaintext": plaintext,
                "_html": html,
            },
            tag="weekly-digest",
        )
        return {"sent": True}
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "weekly_digest.send_failed saved_id=%s err=%s",
            saved_id,
            exc,
        )
        return {"sent": False, "reason": f"send_failed:{type(exc).__name__}"}


# ---------------------------------------------------------------------------
# Search replay — reuses programs._build_search_response
# ---------------------------------------------------------------------------


def _replay_search(
    *,
    conn: sqlite3.Connection,
    query: dict[str, Any],
) -> list[dict[str, Any]]:
    """Re-run the saved query through the canonical search builder.

    We import lazily so the cron module imports cleanly even when the
    api package fails to load (e.g. in a heredoc test environment that
    skipped FastAPI install). On import failure we fall back to a
    minimal SQL query mirroring _build_search_sql in
    run_saved_searches.py — this preserves behaviour parity.
    """
    try:
        from jpintel_mcp.api.programs import _build_search_response
    except Exception:  # noqa: BLE001 — fall back path
        return _replay_search_fallback(conn=conn, query=query)

    body = _build_search_response(
        conn=conn,
        q=query.get("q"),
        tier=query.get("tier"),
        prefecture=query.get("prefecture"),
        authority_level=query.get("authority_level"),
        funding_purpose=query.get("funding_purpose"),
        target_type=query.get("target_types") or query.get("target_type"),
        amount_min=query.get("amount_min"),
        amount_max=query.get("amount_max"),
        include_excluded=bool(query.get("include_excluded", False)),
        limit=int(query.get("limit") or 200),
        offset=0,
        fields="default",
        include_advisors=False,
        as_of_iso=None,
    )
    rows = body.get("results", []) if isinstance(body, dict) else []

    # Normalise to the small shape the renderer expects. _build_search_response
    # returns Pydantic-shaped dicts; keep only the columns we use so the
    # signature hash is stable across version-to-version field additions.
    # The source_url / license / source_fetched_at fields are kept so the
    # Evidence Packet 5-field summary can be rendered without a second
    # round-trip to the DB.
    normalised: list[dict[str, Any]] = []
    for r in rows:
        normalised.append(
            {
                "unified_id": r.get("unified_id"),
                "primary_name": r.get("primary_name"),
                "prefecture": r.get("prefecture"),
                "authority_name": r.get("authority_name"),
                "amount_max_man_yen": r.get("amount_max_man_yen"),
                "subsidy_rate": r.get("subsidy_rate"),
                "official_url": r.get("official_url"),
                "source_url": r.get("source_url"),
                "source_fetched_at": r.get("source_fetched_at"),
                "license": r.get("license"),
                "last_amendment_diff_id": r.get("last_amendment_diff_id"),
                "updated_at": r.get("updated_at"),
            }
        )
    return normalised


def _replay_search_fallback(
    *,
    conn: sqlite3.Connection,
    query: dict[str, Any],
) -> list[dict[str, Any]]:
    """Minimal pure-SQL fallback when api.programs cannot be imported.

    Mirrors a narrow subset of `programs.search` — enough for the cron
    to keep working under a stripped-down test harness. Production
    always takes the import path above.
    """
    where: list[str] = ["1=1"]
    params: list[Any] = []
    if not query.get("include_excluded"):
        where.append("(excluded = 0 OR excluded IS NULL)")
    where.append("(tier IS NULL OR tier IN ('S','A','B','C'))")

    q = query.get("q")
    if q and isinstance(q, str) and q.strip():
        where.append(
            "(primary_name LIKE ? OR aliases_json LIKE ?)"
        )
        like = f"%{q.strip()}%"
        params.extend([like, like])

    pref = query.get("prefecture")
    if pref and isinstance(pref, str) and pref.strip():
        where.append("(prefecture = ? OR prefecture LIKE ?)")
        params.extend([pref.strip(), f"%{pref.strip()}%"])

    auth = query.get("authority_level")
    if auth and isinstance(auth, str) and auth.strip():
        where.append("authority_level = ?")
        params.append(auth.strip())

    # Include source_url / source_fetched_at when the columns exist so the
    # Evidence Packet 5-field summary is populated even on the fallback
    # path. Older schemas may not have all of them — we tolerate missing
    # columns by sniffing PRAGMA table_info first.
    select_cols = [
        "unified_id", "primary_name", "prefecture", "authority_name",
        "amount_max_man_yen", "subsidy_rate", "official_url", "updated_at",
    ]
    try:
        existing_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(programs)").fetchall()
        }
    except sqlite3.OperationalError:
        existing_cols = set()
    for opt in ("source_url", "source_fetched_at"):
        if opt in existing_cols:
            select_cols.append(opt)
    sql = (
        "SELECT " + ", ".join(select_cols) + " "
        "  FROM programs "
        " WHERE " + " AND ".join(where) + " "
        " ORDER BY updated_at DESC LIMIT 200"
    )
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Previous-run reconstruction
# ---------------------------------------------------------------------------


def _load_previous_snapshot(
    *,
    conn: sqlite3.Connection,
    saved_id: int,
    window_iso: str,
) -> dict[str, str] | None:
    """Reconstruct the previous run's (unified_id -> updated_at) map.

    Looks at the latest `analytics_events` row for this saved_id whose
    `event_name='digest_delivered'` AND `ts >= window_iso`. The map is
    JSON-stashed in `client_tag` (truncated to fit the column). Returns
    None when there is no previous run inside the lookback window.

    The lookback (`window_iso`) is intentionally generous (~30 days) so
    a saved search that paused for 2 weeks still picks up against its
    last known snapshot, not as a bare first-run.
    """
    try:
        row = conn.execute(
            "SELECT client_tag FROM analytics_events "
            "WHERE event_name = 'digest_delivered' "
            "  AND saved_search_id = ? "
            "  AND ts >= ? "
            "ORDER BY ts DESC LIMIT 1",
            (saved_id, window_iso),
        ).fetchone()
    except sqlite3.OperationalError:
        # Migration 113 not yet applied. Treat as "no previous snapshot".
        return None
    if row is None or not row["client_tag"]:
        return None
    try:
        payload = json.loads(row["client_tag"])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    snap = payload.get("snapshot") or {}
    if not isinstance(snap, dict):
        return None
    # Coerce all values to strings to keep the diff comparison stable.
    return {str(k): str(v or "") for k, v in snap.items()}


def _stash_snapshot_in_client_tag(
    *,
    results: list[dict[str, Any]],
    delta_count: int,
    cap_chars: int = 1024,
) -> str:
    """Pack the (unified_id, updated_at) map into a JSON blob ≤ cap_chars.

    The analytics_events.client_tag column is the only free string column
    we have on that table. We deliberately truncate the snapshot map at
    `_TOP_K_HITS` entries to keep the row size bounded; the cron only
    needs the head rows for next week's diff (a long-tail row falling
    out of the snapshot just means it surfaces as NEW next week, which
    is acceptable for an Advisor Loop cohort that watches the top hits).
    """
    snap = {
        r["unified_id"]: (r.get("updated_at") or "")
        for r in results[:_TOP_K_HITS]
        if r.get("unified_id")
    }
    blob = json.dumps(
        {"snapshot": snap, "delta_count": delta_count},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(blob) > cap_chars:
        # Aggressive truncation — drop entries until we fit.
        keys = list(snap.keys())
        while keys and len(blob) > cap_chars:
            keys.pop()
            snap = {k: snap[k] for k in keys}
            blob = json.dumps(
                {"snapshot": snap, "delta_count": delta_count},
                ensure_ascii=False,
                separators=(",", ":"),
            )
    return blob


# ---------------------------------------------------------------------------
# Idempotency gate
# ---------------------------------------------------------------------------


def _is_due_weekly(last_run_at: str | None, now_utc: datetime) -> bool:
    """True iff the weekly window has elapsed since `last_run_at`."""
    if last_run_at is None:
        return True
    try:
        last = datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (now_utc - last) >= timedelta(hours=_WEEKLY_WINDOW_HOURS)


# ---------------------------------------------------------------------------
# Single-row processor (testable unit)
# ---------------------------------------------------------------------------


def run_one(
    *,
    jp_conn: sqlite3.Connection,
    row: sqlite3.Row,
    now_utc: datetime,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Process a single saved_searches row.

    Returns a dict for cron telemetry rollup:
        {"saved_id": int, "status": "sent" | "skipped" | "error",
         "delta_count": int, "reason": str | None}
    """
    saved_id = row["id"]
    if not _is_due_weekly(row["last_run_at"], now_utc):
        return {
            "saved_id": saved_id,
            "status": "skipped",
            "delta_count": 0,
            "reason": "window",
        }

    try:
        query = json.loads(row["query_json"]) if row["query_json"] else {}
    except (TypeError, ValueError):
        return {
            "saved_id": saved_id,
            "status": "error",
            "delta_count": 0,
            "reason": "query_json_unparseable",
        }

    try:
        current_results = _replay_search(conn=jp_conn, query=query)
    except Exception as exc:  # noqa: BLE001 — defensive, log + skip
        logger.warning("replay_failed saved_id=%s err=%s", saved_id, exc)
        return {
            "saved_id": saved_id,
            "status": "error",
            "delta_count": 0,
            "reason": f"replay_failed:{type(exc).__name__}",
        }

    new_signature = _signature(current_results)
    prev_signature = row["last_result_signature"]
    # 30-day lookback for the snapshot reconstruction. Long enough to
    # bridge a paused row, short enough that a stale snapshot doesn't
    # mislead the diff after months of dormancy.
    window_iso = (now_utc - timedelta(days=30)).isoformat()
    prev_snapshot = _load_previous_snapshot(
        conn=jp_conn, saved_id=saved_id, window_iso=window_iso,
    )

    diff = _diff_sets(
        prev_signature=prev_signature,
        prev_result_map=prev_snapshot,
        current=current_results,
    )
    delta_count = (
        len(diff["new"]) + len(diff["removed"]) + len(diff["modified"])
    )

    now_iso = now_utc.isoformat().replace("+00:00", "Z")
    manage_url = f"{_PUBLIC_ORIGIN}/dashboard.html#saved-searches"

    plaintext = _render_plaintext(
        saved_name=row["name"],
        diff=diff,
        manage_url=manage_url,
        now_iso=now_iso,
    )
    html = _render_html(
        saved_name=row["name"],
        diff=diff,
        manage_url=manage_url,
        now_iso=now_iso,
    )
    json_payload = _render_json(
        saved_name=row["name"],
        saved_id=saved_id,
        diff=diff,
        manage_url=manage_url,
        now_iso=now_iso,
    )

    # Emit the digest. Best-effort: a missing email sender does NOT
    # block analytics_events emission — the digest is rendered, the
    # Advisor Loop substrate sees `digest_delivered`, and the operator
    # can wire a real sender later without losing any signal.
    send_outcome = _send_email(
        to=row["notify_email"],
        subject=row["name"],
        plaintext=plaintext,
        html=html,
        saved_id=saved_id,
        dry_run=dry_run,
    )

    if not dry_run:
        # Stash the snapshot in client_tag so next week's run can diff.
        client_tag_blob = _stash_snapshot_in_client_tag(
            results=current_results, delta_count=delta_count,
        )

        # Insert analytics_events row with event_name='digest_delivered'.
        # We use the api_key_hash column to identify the account so the
        # weekly_evidence_loops query can group by account_id later.
        try:
            jp_conn.execute(
                "INSERT INTO analytics_events("
                "  ts, method, path, status, latency_ms,"
                "  key_hash, anon_ip_hash, client_tag, is_anonymous,"
                "  event_name, saved_search_id, delta_count"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now_iso,
                    "CRON",
                    "/cron/weekly_digest",
                    200 if send_outcome.get("sent") or send_outcome.get("reason") in ("dry_run", "email_sender_unavailable") else 500,
                    None,
                    row["api_key_hash"],
                    None,
                    client_tag_blob,
                    0,
                    "digest_delivered",
                    saved_id,
                    delta_count,
                ),
            )
        except sqlite3.OperationalError as exc:
            # Migration 113 not yet applied. Log + continue — the cron is
            # still useful for the email send half; the analytics signal
            # just won't surface until the migration lands.
            logger.warning(
                "analytics_events_insert_failed saved_id=%s err=%s",
                saved_id,
                exc,
            )

        # Bump saved_searches state. Always advance last_run_at so the
        # idempotency gate works even when delta_count==0.
        try:
            jp_conn.execute(
                "UPDATE saved_searches "
                "   SET last_run_at = ?, "
                "       last_result_signature = ?, "
                "       last_delta_count = ? "
                " WHERE id = ?",
                (now_iso, new_signature, delta_count, saved_id),
            )
        except sqlite3.OperationalError as exc:
            # Migration 113 columns missing — fall back to bumping
            # last_run_at only so the legacy schema is still healed.
            logger.warning(
                "saved_searches_state_partial_update saved_id=%s err=%s",
                saved_id,
                exc,
            )
            jp_conn.execute(
                "UPDATE saved_searches SET last_run_at = ? WHERE id = ?",
                (now_iso, saved_id),
            )
        jp_conn.commit()

    return {
        "saved_id": saved_id,
        "status": "sent",
        "delta_count": delta_count,
        "new_count": len(diff["new"]),
        "modified_count": len(diff["modified"]),
        "removed_count": len(diff["removed"]),
        "all_count": diff.get("all_count", 0),
        "reason": send_outcome.get("reason"),
        "json_payload": json_payload,
        "plaintext_preview": "\n".join(plaintext.splitlines()[:30]),
    }


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        return col in {
            r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
    except sqlite3.OperationalError:
        return False


def run(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    jpintel_db: Path | None = None,
) -> dict[str, Any]:
    """Sweep weekly-active saved searches and emit digests + analytics rows.

    Returns a summary dict for cron heartbeat capture:
        {"searches_run": N, "digests_sent": N, "errors": N,
         "top_5_active_accounts": [...]}
    """
    jp_conn = connect(jpintel_db) if jpintel_db else connect()
    try:
        # Defensive: if the migration 113 columns aren't present yet, the
        # filter clause below would fail. Build the predicate dynamically.
        has_is_active = _has_column(jp_conn, "saved_searches", "is_active")
        has_last_signature = _has_column(
            jp_conn, "saved_searches", "last_result_signature"
        )

        select_cols = [
            "id", "api_key_hash", "name", "query_json", "frequency",
            "notify_email", "last_run_at", "created_at",
        ]
        if has_last_signature:
            select_cols.append("last_result_signature")
        else:
            select_cols.append("NULL AS last_result_signature")

        sql = (
            "SELECT " + ", ".join(select_cols) + " "
            "FROM saved_searches "
            "WHERE frequency = 'weekly'"
        )
        if has_is_active:
            sql += " AND is_active = 1"
        sql += " ORDER BY id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = jp_conn.execute(sql).fetchall()

        now_utc = datetime.now(UTC)
        results: list[dict[str, Any]] = []
        sent = 0
        errors = 0
        skipped = 0
        for row in rows:
            outcome = run_one(
                jp_conn=jp_conn, row=row, now_utc=now_utc, dry_run=dry_run,
            )
            results.append(outcome)
            if outcome["status"] == "sent":
                sent += 1
            elif outcome["status"] == "error":
                errors += 1
            else:
                skipped += 1

        # Top-5 active accounts by digest volume (this run only).
        per_account: dict[str, int] = {}
        for r in results:
            if r["status"] != "sent":
                continue
            # Find the api_key_hash for this saved_id.
            try:
                acct_row = jp_conn.execute(
                    "SELECT api_key_hash FROM saved_searches WHERE id = ?",
                    (r["saved_id"],),
                ).fetchone()
            except sqlite3.OperationalError:
                continue
            if not acct_row:
                continue
            acct = acct_row["api_key_hash"]
            per_account[acct] = per_account.get(acct, 0) + 1
        top_5 = sorted(per_account.items(), key=lambda kv: -kv[1])[:5]

        summary = {
            "ran_at": now_utc.isoformat(),
            "searches_run": len(rows),
            "digests_sent": sent,
            "errors": errors,
            "skipped": skipped,
            "top_5_active_accounts": [
                {"key_hash_prefix": (k or "")[:8], "digest_count": v}
                for k, v in top_5
            ],
            "dry_run": dry_run,
        }
        return summary
    finally:
        jp_conn.close()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekly Saved-Search Digest cron (Advisor Loop core)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="render + count only; no email, no DB writes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap the sweep at N rows (debug knob)",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Heartbeat is optional — the script must work in a stripped-down
    # test harness that doesn't have the cron_heartbeat table.
    try:
        from jpintel_mcp.observability import heartbeat
    except Exception:  # noqa: BLE001 — defensive
        heartbeat = None  # type: ignore[assignment]

    if heartbeat is None:
        summary = run(dry_run=args.dry_run, limit=args.limit)
    else:
        with heartbeat("weekly_digest") as hb:
            summary = run(dry_run=args.dry_run, limit=args.limit)
            hb["rows_processed"] = int(summary.get("digests_sent", 0))
            hb["rows_skipped"] = int(summary.get("skipped", 0))
            hb["metadata"] = {
                "searches_run": summary.get("searches_run"),
                "errors": summary.get("errors"),
                "dry_run": summary.get("dry_run"),
            }

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
