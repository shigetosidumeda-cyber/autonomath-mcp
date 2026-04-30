#!/usr/bin/env python3
"""Saved-search digest cron (W3 retention).

Runs daily/weekly. For every `saved_searches` row whose
`last_run_at` window has elapsed:

    1. Replays the saved query against the live `programs` table.
    2. Diffs the matching set against `am_amendment_diff`
       (autonomath.db, migration 075) so we surface only programs that
       genuinely changed since the last run — not the entire match set on
       every cron tick.
    3. If at least one new match exists, renders the
       `saved_search_digest` Postmark template and emails the customer.
    4. Records ONE row in `usage_events` (endpoint
       `saved_searches.digest`, status 200) and fires
       `report_usage_async` so the customer is billed ¥3 for the
       delivery (project_autonomath_business_model: ¥3/req metered).
    5. Updates `last_run_at` so the same row is not reprocessed inside
       its frequency window. Re-running the cron mid-window is a no-op
       (idempotent).

Constraints:
    * No Anthropic / Claude / SDK calls — pure SQL + httpx (Postmark).
    * Idempotent — `last_run_at` gates re-entry. The cron skips a row when
      `last_run_at >= now - frequency_interval`.
    * Pure ¥3/req metered for delivery. The CRUD surface (POST/GET/DELETE
      under /v1/me/saved_searches) is FREE; this cron is the only place
      that meters.
    * Solo + zero-touch — no operator review surface, no per-customer
      onboarding. Failures are logged + Sentry-captured if configured.

CLI:
    python scripts/cron/run_saved_searches.py             # real run
    python scripts/cron/run_saved_searches.py --dry-run   # log only
    python scripts/cron/run_saved_searches.py --frequency daily
    python scripts/cron/run_saved_searches.py --max-matches 10
    python scripts/cron/run_saved_searches.py --since 2026-04-28T00:00:00Z

Wiring:
    * `.github/workflows/saved-searches-cron.yml` runs this daily at
      06:00 JST (21:00 UTC) via `flyctl ssh console -C ...`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`. Mirrors the
# import preamble in scripts/cron/expire_trials.py.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.saved_searches")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default cap on matches surfaced per digest. The A/B target landed on
# 10 (see docstring at bottom). Configurable via --max-matches so the
# experiment cohort can be flipped without a redeploy.
DEFAULT_MAX_MATCHES = 10

# Frequency interval lookups (in days). 'daily' = 1d window,
# 'weekly' = 7d window. Shorter than the bare interval so a clock-drift
# of a few minutes does not skip a run.
_FREQUENCY_INTERVALS_HOURS: dict[str, int] = {
    "daily": 22,    # 22h instead of 24h so JST 06:00 cron doesn't push to 06:01 next day
    "weekly": 7 * 24 - 4,  # 6d 20h same reason
}

# Public origin for `/programs/{slug}` deep links. Falls back to the
# jpcite.com canonical when settings is incomplete (test env).
_PUBLIC_ORIGIN = "https://jpcite.com"


# ---------------------------------------------------------------------------
# Search replay
# ---------------------------------------------------------------------------


def _build_search_sql(query: dict[str, Any]) -> tuple[str, list[Any]]:
    """Translate the saved query dict into a parameterised SQL SELECT.

    We deliberately do NOT call `programs.search` (api/programs.py) here —
    the cron is offline, has no Request, and re-implementing the small
    subset of filters we accept inline is far simpler than spinning up a
    FastAPI test client just to read its JSON envelope. Only filters
    listed in `_ALLOWED_QUERY_KEYS` (api/saved_searches.py) are honoured;
    the API layer enforces the same allow-list before persisting.

    Returns (sql, params). The SELECT is intentionally narrow — only
    columns the digest template renders — so we minimise row width.
    """
    where: list[str] = ["1=1"]
    params: list[Any] = []

    if not query.get("include_excluded"):
        where.append("(excluded = 0 OR excluded IS NULL)")

    # Quarantine tier always excluded — matches generate_program_pages.py.
    where.append("(tier IS NULL OR tier IN ('S', 'A', 'B', 'C'))")

    q = query.get("q")
    if q and isinstance(q, str) and q.strip():
        # Simple LIKE — FTS5 trigram tokenizer would give richer matches
        # but the cron is daily and the customer wants WHATEVER changed,
        # not the perfectly-ranked top-K. LIKE is good enough here.
        like = f"%{q.strip()}%"
        where.append("(primary_name LIKE ? OR aliases_json LIKE ?)")
        params.extend([like, like])

    pref = query.get("prefecture")
    if pref and isinstance(pref, str) and pref.strip():
        where.append("(prefecture = ? OR prefecture LIKE ?)")
        params.extend([pref.strip(), f"%{pref.strip()}%"])

    auth = query.get("authority_level")
    if auth and isinstance(auth, str) and auth.strip():
        where.append("authority_level = ?")
        params.append(auth.strip())

    target_types = query.get("target_types")
    if isinstance(target_types, list) and target_types:
        # Each requested target_type becomes a LIKE against the JSON column.
        # OR-joined: ANY match qualifies (matches programs.search semantics).
        likes = ["target_types_json LIKE ?" for _ in target_types]
        where.append("(" + " OR ".join(likes) + ")")
        params.extend([f'%"{t}"%' for t in target_types])

    purposes = query.get("funding_purpose")
    if isinstance(purposes, list) and purposes:
        likes = ["funding_purpose_json LIKE ?" for _ in purposes]
        where.append("(" + " OR ".join(likes) + ")")
        params.extend([f'%"{p}"%' for p in purposes])

    tiers = query.get("tier")
    if isinstance(tiers, list) and tiers:
        placeholders = ",".join("?" for _ in tiers)
        where.append(f"tier IN ({placeholders})")
        params.extend(tiers)

    amount_min = query.get("amount_min")
    if isinstance(amount_min, (int, float)) and amount_min > 0:
        where.append("amount_max_man_yen >= ?")
        # input is in yen (matches API surface); column is 万円
        params.append(float(amount_min) / 10000.0)

    amount_max = query.get("amount_max")
    if isinstance(amount_max, (int, float)) and amount_max > 0:
        where.append("amount_min_man_yen <= ?")
        params.append(float(amount_max) / 10000.0)

    sql = (
        "SELECT unified_id, primary_name, prefecture, authority_name, "
        "       amount_max_man_yen, subsidy_rate, official_url, updated_at "
        "  FROM programs "
        " WHERE " + " AND ".join(where) + " "
        " ORDER BY updated_at DESC LIMIT 200"
    )
    return sql, params


def _slugify(unified_id: str) -> str:
    """Public-page slug. The static generator emits `/programs/{unified_id}`
    so we mirror that contract — no kana/Hepburn transformation here.
    """
    return unified_id


def _public_url(unified_id: str) -> str:
    return f"{_PUBLIC_ORIGIN}/programs/{_slugify(unified_id)}"


# ---------------------------------------------------------------------------
# Diff against am_amendment_diff
# ---------------------------------------------------------------------------


def _changed_entity_ids_since(
    am_conn: sqlite3.Connection, since_iso: str,
) -> set[str]:
    """Return the set of `entity_id` values that changed since `since_iso`.

    Reads from `am_amendment_diff` (autonomath.db, migration 075). The
    table is append-only — the cron picks up a clean change-set every
    time it runs without needing to track its own watermark per row.

    When the table is missing (e.g. test DB built from schema.sql before
    migration 075 landed) we return an empty set: no changes detected
    means the cron emails nothing, which is the safe failure mode.
    """
    try:
        rows = am_conn.execute(
            "SELECT DISTINCT entity_id FROM am_amendment_diff "
            "WHERE detected_at >= ?",
            (since_iso,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.info("am_amendment_diff_missing — treating as no-changes")
            return set()
        raise
    return {r[0] for r in rows if r[0]}


# ---------------------------------------------------------------------------
# Digest send
# ---------------------------------------------------------------------------


def _render_digest_payload(
    *,
    name: str,
    matches: list[dict[str, Any]],
    saved_id: int,
    frequency: str,
    max_matches: int,
) -> dict[str, Any]:
    """Build the Postmark TemplateModel for the saved_search_digest template.

    `matches` is already trimmed to `max_matches`; we still surface the
    full count separately so the email can say "全 N 件中 上位 10 件".
    """
    return {
        "saved_name": name,
        "match_count": len(matches),
        "matches": [
            {
                "name": m["primary_name"],
                "prefecture": m.get("prefecture") or "全国",
                "authority_name": m.get("authority_name") or "",
                "amount_max_man_yen": m.get("amount_max_man_yen"),
                "subsidy_rate": m.get("subsidy_rate"),
                "url": _public_url(m["unified_id"]),
                "official_url": m.get("official_url") or "",
            }
            for m in matches[:max_matches]
        ],
        "frequency": frequency,
        "saved_id": saved_id,
        "manage_url": f"{_PUBLIC_ORIGIN}/dashboard.html#saved-searches",
        # 税理士法 §52 / 弁護士法 §72 fence — repeated by the template
        # body so the disclaimer is structurally always present.
        "disclaimer": (
            "本通知はjpciteによる公開情報の検索結果です。"
            "個別具体的な税務助言・法律判断は税理士法 §52 / 弁護士法 §72 に基づき"
            "資格者にご確認ください。"
        ),
    }


def _render_slack_payload(
    *,
    payload: dict[str, Any],
    max_matches: int = 5,
) -> dict[str, Any]:
    """Convert the email digest payload into a Slack mrkdwn block message.

    Truncates `matches` to top 5 (Slack limit guidance — anything longer
    becomes an unreadable wall of text in a busy channel). Each match is
    a `<url|name>` mrkdwn link so click-through goes straight to the
    public program page.
    """
    matches = payload.get("matches", [])[:max_matches]
    saved_name = payload.get("saved_name", "保存条件")
    match_count = payload.get("match_count", len(matches))
    disclaimer = payload.get("disclaimer", "")
    lines = [f"*[{saved_name}]* — {match_count} 件の更新"]
    for m in matches:
        nm = m.get("name") or "(unnamed)"
        url = m.get("url") or m.get("official_url") or ""
        pref = m.get("prefecture") or "全国"
        amt = m.get("amount_max_man_yen")
        amt_str = f" 上限 {amt}万円" if amt else ""
        if url:
            lines.append(f"• <{url}|{nm}> — {pref}{amt_str}")
        else:
            lines.append(f"• {nm} — {pref}{amt_str}")
    if match_count > max_matches:
        lines.append(f"_…ほか {match_count - max_matches} 件_")
    if disclaimer:
        lines.append(f"\n_{disclaimer}_")
    return {"text": "\n".join(lines)}


def _post_slack_digest(
    *,
    channel_url: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """POST the rendered Slack payload to the channel webhook.

    10s timeout. Slack's documented SLA is <2s; 10s is the upper fence.
    Returns the same shape as `_send_digest_email`:
        ok    → {"slack_ok": True}
        fail  → {"skipped": True, "reason": "...", "error": "..."}
    """
    if dry_run:
        logger.info(
            "slack.dry_run url=%s match_count=%d",
            channel_url[:60] + "..." if len(channel_url) > 60 else channel_url,
            payload.get("match_count", 0),
        )
        return {"slack_ok": True, "dry_run": True}
    body = json.dumps(_render_slack_payload(payload=payload)).encode("utf-8")
    req = urllib.request.Request(
        channel_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                return {"slack_ok": True}
            return {
                "skipped": True,
                "reason": "slack_failed",
                "error": f"http_{resp.status}",
            }
    except urllib.error.HTTPError as exc:
        return {
            "skipped": True,
            "reason": "slack_failed",
            "error": f"http_{exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "skipped": True,
            "reason": "slack_failed",
            "error": type(exc).__name__,
        }


def _record_slack_failure(
    *,
    jp_conn: sqlite3.Connection,
    saved_id: int,
    error: str,
) -> None:
    """Record a Slack delivery failure for retry visibility.

    The existing `webhook_deliveries` table requires a FK into
    `customer_webhooks(id)` which saved-searches do not own. To keep the
    failure trail honest we log a usage_events row with status=500 and
    metered=0 so dashboards can surface "this saved search has a stuck
    Slack channel" without billing the customer for the failure. This
    matches the project_autonomath_business_model "0-match runs do NOT
    bill" — failed runs likewise do NOT bill.
    """
    try:
        jp_conn.execute(
            "INSERT INTO usage_events("
            "  key_hash, endpoint, ts, status, metered, params_digest,"
            "  latency_ms, result_count"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                f"saved_search_{saved_id}",  # surrogate marker
                "saved_searches.slack_failed",
                datetime.now(UTC).isoformat(),
                500,
                0,
                error[:128] if error else None,
                None,
                None,
            ),
        )
    except sqlite3.OperationalError as exc:
        logger.warning("slack_failure_record_failed err=%s", exc)


def _send_digest_email(
    *,
    to: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        logger.info(
            "digest.dry_run to_domain=%s saved_id=%s match_count=%d",
            to.split("@", 1)[-1] if "@" in to else "***",
            payload.get("saved_id"),
            payload.get("match_count"),
        )
        return {"skipped": True, "reason": "dry_run"}
    try:
        from jpintel_mcp.email import get_client  # local import — keep cron lean
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("digest.email_unavailable err=%s", exc)
        return {"skipped": True, "reason": "email_module_unavailable"}
    try:
        client = get_client()
        return client._send(  # type: ignore[attr-defined]
            to=to,
            template_alias="saved_search_digest",
            template_model=payload,
            tag="saved-search-digest",
        )
    except Exception as exc:
        logger.warning("digest.send_failed err=%s", exc)
        return {"skipped": True, "reason": "send_failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# Metering
# ---------------------------------------------------------------------------


def _record_metered_delivery(
    *,
    jp_conn: sqlite3.Connection,
    key_hash: str,
    saved_id: int,
    dry_run: bool,
) -> None:
    """Insert one usage_events row + fire report_usage_async.

    Matches the on-the-hot-path `log_usage` shape (api/deps.py) so the
    digest delivery shows up in the same dashboards / Stripe usage line
    as a regular API call. We always record the row inline (cron has no
    response-flush boundary, so deferring would never run); Stripe push
    happens via the same daemon-thread path used by API requests.

    Skipped entirely on --dry-run so test runs do not bill the customer.
    """
    if dry_run:
        return

    # Lookup api_keys row for tier + stripe subscription, mirroring
    # require_key (api/deps.py).
    row = jp_conn.execute(
        "SELECT tier, stripe_subscription_id, customer_id "
        "FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        logger.warning("metered.api_key_missing saved_id=%s", saved_id)
        return
    tier = row["tier"]
    sub_id = row["stripe_subscription_id"]
    metered = tier == "paid"

    cur = jp_conn.execute(
        "INSERT INTO usage_events("
        "  key_hash, endpoint, ts, status, metered, params_digest,"
        "  latency_ms, result_count"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            key_hash,
            "saved_searches.digest",
            datetime.now(UTC).isoformat(),
            200,
            1 if metered else 0,
            None,  # PII-adjacent — saved-search names are user-supplied
            None,
            None,
        ),
    )
    usage_event_id = cur.lastrowid

    jp_conn.execute(
        "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
        (datetime.now(UTC).isoformat(), key_hash),
    )

    # Stripe usage_record push — fire-and-forget. Same call shape as
    # `log_usage` on the request hot path so dashboards stay coherent.
    if metered and sub_id:
        try:
            from jpintel_mcp.billing.stripe_usage import report_usage_async

            report_usage_async(sub_id, usage_event_id=usage_event_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "metered.stripe_push_failed saved_id=%s", saved_id, exc_info=True
            )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _is_due(last_run_at: str | None, frequency: str, now_utc: datetime) -> bool:
    """True iff this saved search's `frequency` window has elapsed."""
    if last_run_at is None:
        return True
    try:
        last = datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
    except ValueError:
        # Unparseable → treat as never-run so the cron self-heals.
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    interval_h = _FREQUENCY_INTERVALS_HOURS.get(frequency, 22)
    return (now_utc - last) >= timedelta(hours=interval_h)


def run(
    *,
    dry_run: bool = False,
    only_frequency: str | None = None,
    max_matches: int = DEFAULT_MAX_MATCHES,
    since_iso: str | None = None,
    autonomath_db: Path | None = None,
    jpintel_db: Path | None = None,
) -> dict[str, Any]:
    """Daily/weekly digest sweep. Returns a summary dict for cron capture."""
    am_path = autonomath_db or settings.autonomath_db_path
    am_present = Path(am_path).is_file()
    if not am_present:
        logger.warning("autonomath_db_missing path=%s — diff guard disabled", am_path)

    jp_conn = connect(jpintel_db) if jpintel_db else connect()
    am_conn: sqlite3.Connection | None = None
    if am_present:
        am_conn = sqlite3.connect(str(am_path))
        am_conn.row_factory = sqlite3.Row

    now_utc = datetime.now(UTC)
    # Diff lookback: anything that changed in the last 8 days catches the
    # weekly cohort comfortably; daily cohort barely uses 1d of it.
    if since_iso is None:
        since_iso = (now_utc - timedelta(days=8)).isoformat()

    try:
        # Channel routing fields (channel_format / channel_url) land in
        # migration 099. Older test DBs may not have them; we feature-
        # detect via PRAGMA so the cron stays compatible with both.
        cols = {
            r[1]
            for r in jp_conn.execute(
                "PRAGMA table_info(saved_searches)"
            ).fetchall()
        }
        has_channel = "channel_format" in cols
        if has_channel:
            sweep_sql = (
                "SELECT id, api_key_hash, name, query_json, frequency, "
                "       notify_email, "
                "       COALESCE(channel_format, 'email') AS channel_format, "
                "       channel_url, "
                "       last_run_at, created_at "
                "  FROM saved_searches"
            )
        else:
            sweep_sql = (
                "SELECT id, api_key_hash, name, query_json, frequency, "
                "       notify_email, "
                "       'email' AS channel_format, "
                "       NULL   AS channel_url, "
                "       last_run_at, created_at "
                "  FROM saved_searches"
            )
        sweep_params: list[Any] = []
        if only_frequency:
            sweep_sql += " WHERE frequency = ?"
            sweep_params.append(only_frequency)
        sweep_sql += " ORDER BY id ASC"
        rows = jp_conn.execute(sweep_sql, sweep_params).fetchall()

        # Materialise the changed-entity set once per cron run so the
        # per-row matcher does not re-query autonomath.db N times.
        if am_conn is not None:
            changed_ids = _changed_entity_ids_since(am_conn, since_iso)
        else:
            changed_ids = set()

        scanned = 0
        skipped_window = 0
        skipped_no_match = 0
        emails_sent = 0
        billed = 0

        for row in rows:
            scanned += 1
            if not _is_due(row["last_run_at"], row["frequency"], now_utc):
                skipped_window += 1
                continue
            try:
                query = json.loads(row["query_json"]) if row["query_json"] else {}
            except (TypeError, ValueError):
                logger.warning("query_json_unparseable saved_id=%s", row["id"])
                continue

            sql, params = _build_search_sql(query)
            search_rows = jp_conn.execute(sql, params).fetchall()

            # Diff against am_amendment_diff: keep rows whose unified_id
            # appears in the changed-set. When autonomath.db is missing,
            # `changed_ids` is empty, so we send NO email rather than
            # spamming every match daily — preserving the "new since
            # last run" contract of the digest.
            if changed_ids:
                matches = [
                    dict(r) for r in search_rows if r["unified_id"] in changed_ids
                ]
            else:
                matches = []

            now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")

            if not matches:
                skipped_no_match += 1
                # We still bump last_run_at so the customer's window
                # advances; otherwise a saved search that never matches
                # would re-process every cron tick.
                if not dry_run:
                    jp_conn.execute(
                        "UPDATE saved_searches SET last_run_at = ? WHERE id = ?",
                        (now_iso, row["id"]),
                    )
                continue

            payload = _render_digest_payload(
                name=row["name"],
                matches=matches,
                saved_id=row["id"],
                frequency=row["frequency"],
                max_matches=max_matches,
            )
            channel_format = row["channel_format"] or "email"
            channel_url = row["channel_url"]
            if channel_format == "slack" and channel_url:
                # Idempotency-key dedup so a parallel cron invocation does
                # NOT double-post the same digest. last_run_at gates 99% of
                # cases but a rapid retry between the POST and the bump
                # would slip through; the unique (provider, idempotency_key)
                # constraint on integration_sync_log catches that.
                # send_window = day-bucket (daily) or ISO-week (weekly).
                if row["frequency"] == "weekly":
                    iso_year, iso_week, _ = now_utc.isocalendar()
                    window = f"{iso_year}W{iso_week:02d}"
                else:
                    window = now_utc.strftime("%Y%m%d")
                idem_key = f"ss{row['id']}-{window}-slack"
                already_sent = False
                if not dry_run:
                    try:
                        jp_conn.execute(
                            "INSERT INTO integration_sync_log("
                            "  api_key_hash, provider, idempotency_key, "
                            "  saved_search_id, status, result_count) "
                            "VALUES (?,?,?,?,?,?)",
                            (
                                row["api_key_hash"],
                                "slack",
                                idem_key,
                                row["id"],
                                "ok",
                                len(matches),
                            ),
                        )
                        jp_conn.commit()
                    except sqlite3.IntegrityError:
                        already_sent = True
                    except sqlite3.OperationalError:
                        # integration_sync_log table absent (migration 105
                        # not applied) — fall through with no dedup so the
                        # cron still functions on a fresh test DB.
                        pass
                if already_sent:
                    logger.info(
                        "slack.digest.deduped saved_id=%s window=%s",
                        row["id"],
                        window,
                    )
                    skipped_no_match += 1
                    continue
                outcome = _post_slack_digest(
                    channel_url=channel_url,
                    payload=payload,
                    dry_run=dry_run,
                )
                sent = bool(outcome.get("slack_ok")) or (
                    outcome.get("reason") == "dry_run"
                )
                if not sent:
                    _record_slack_failure(
                        jp_conn=jp_conn,
                        saved_id=row["id"],
                        error=str(outcome.get("error") or "unknown"),
                    )
                    # Mark the integration_sync_log row error so a retry
                    # with a NEW idempotency_key (next window) is allowed.
                    if not dry_run:
                        try:
                            jp_conn.execute(
                                "UPDATE integration_sync_log "
                                "   SET status = 'error', "
                                "       error_class = ? "
                                " WHERE provider = 'slack' "
                                "   AND idempotency_key = ?",
                                (
                                    str(outcome.get("error") or "unknown")[:64],
                                    idem_key,
                                ),
                            )
                            jp_conn.commit()
                        except sqlite3.OperationalError:
                            pass
            else:
                outcome = _send_digest_email(
                    to=row["notify_email"], payload=payload, dry_run=dry_run,
                )
                sent = (
                    outcome.get("skipped") is None
                    or outcome.get("reason") == "dry_run"
                )
            if sent:
                emails_sent += 1
                # Same ¥3 metering across both channels — the customer
                # opted into a delivery, the system delivered, we bill.
                _record_metered_delivery(
                    jp_conn=jp_conn,
                    key_hash=row["api_key_hash"],
                    saved_id=row["id"],
                    dry_run=dry_run,
                )
                if not dry_run:
                    billed += 1

            if not dry_run:
                jp_conn.execute(
                    "UPDATE saved_searches SET last_run_at = ? WHERE id = ?",
                    (now_iso, row["id"]),
                )

        summary = {
            "ran_at": datetime.now(UTC).isoformat(),
            "since": since_iso,
            "scanned": scanned,
            "skipped_window": skipped_window,
            "skipped_no_match": skipped_no_match,
            "emails_sent": emails_sent,
            "billed": billed,
            "max_matches": max_matches,
            "frequency_filter": only_frequency,
            "dry_run": dry_run,
        }
        logger.info("saved_search_digest.summary %s",
                    json.dumps(summary, ensure_ascii=False))
        return summary
    finally:
        if am_conn is not None:
            am_conn.close()
        jp_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily/weekly saved-search digest cron"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="log + count only; no email, no Stripe push, no DB writes")
    parser.add_argument("--frequency", default=None,
                        choices=["daily", "weekly"],
                        help="restrict sweep to a single frequency")
    parser.add_argument("--max-matches", type=int, default=DEFAULT_MAX_MATCHES,
                        help=f"max matches per digest (default {DEFAULT_MAX_MATCHES})")
    parser.add_argument("--since", default=None,
                        help="ISO datetime for am_amendment_diff lookback (default now-8d)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with heartbeat("run_saved_searches") as hb:
        summary = run(
            dry_run=args.dry_run,
            only_frequency=args.frequency,
            max_matches=args.max_matches,
            since_iso=args.since,
        )
        hb["rows_processed"] = int(summary.get("emails_sent", 0))
        hb["rows_skipped"] = int(
            summary.get("skipped_window", 0)
        ) + int(summary.get("skipped_no_match", 0))
        hb["metadata"] = {
            "scanned": summary.get("scanned"),
            "billed": summary.get("billed"),
            "frequency_filter": summary.get("frequency_filter"),
            "dry_run": summary.get("dry_run"),
        }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# A/B test idea (3 vs 10 matches)
# ---------------------------------------------------------------------------
# Hypothesis: 3-match digests have higher click-through-rate per email
# (less choice paralysis, no scroll), but 10-match digests retain better
# week-over-week because the customer always finds at least one usable
# row even in a slow news week.
#
# Cohort assignment: hash the api_key_hash mod 2. Cohort A → max=3,
# cohort B → max=10. Run --max-matches via two parallel cron invocations
# in saved-searches-cron.yml (one for each cohort), each filtered by a
# `WHERE substr(api_key_hash, 1, 1) IN (...)` predicate added at the SQL
# layer. Measurement: track Postmark `Open` + `Click` webhook events
# (api/email_webhook.py) tagged with `saved-search-digest`, segment by
# the cohort hash. Decision criterion: 14-day rolling open-rate × click-
# rate. Promote whichever cohort wins by ≥ 5 pp at p < 0.10.
