"""GET /v1/intel/timeline/{program_id} — 1-program annual timeline.

Single-call timeline that fans out across the four event substrates the
audit / 顧問 customer LLM otherwise has to assemble itself:

  * `am_amendment_diff`              (program field-level updates)
  * `am_adoption_trend_monthly`      (monthly adoption count rollup,
                                      industry-level — joined via the
                                      program's dominant JSIC major)
  * `am_enforcement_anomaly`         (z-score-flagged enforcement events,
                                      prefecture × JSIC slice)
  * `am_adopted_company_features`    (大型 individual adoption events
                                      filtered to the program's
                                      jpi_adoption_records cohort)
  * `am_program_narrative_full.generated_at`  (narrative refresh events)

All five sources are merged into a unified `events[]` envelope sorted by
date desc. Each event carries `{date, type, severity, title, summary,
evidence_url?, source_table}` so the customer LLM can inline the timeline
into a 月次レポート / 監査調書 without a follow-up call.

Hard constraints (memory `feedback_no_operator_llm_api`)
--------------------------------------------------------
* NO LLM call inside this endpoint. Pure SQLite SELECT + Python sort.
* Pure read — never writes to autonomath.db.
* Graceful degradation — when a substrate table is missing on a fresh
  dev DB, the corresponding events stream is empty and the table name
  is added to `data_quality.missing_tables` rather than 500ing.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_timeline")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# Allowed event types. The customer LLM filters via `?include_types=...`
# repeated query params; we validate against this enum.
_ALLOWED_TYPES: frozenset[str] = frozenset(
    {"amendment", "adoption", "enforcement", "narrative_update"}
)
_DEFAULT_TYPES: tuple[str, ...] = (
    "amendment",
    "adoption",
    "enforcement",
    "narrative_update",
)

# Severity heuristics. Pure deterministic enum mapping — no LLM reasoning.
# Amendments to high-impact fields (eligibility / amount / deadline) are
# 'high'; everything else is 'med'. Enforcement anomalies with anomaly_flag=1
# are 'high'; z>1 is 'med'; rest 'low'. Adoption events follow batch size.
_HIGH_IMPACT_AMENDMENT_FIELDS: frozenset[str] = frozenset(
    {
        "eligibility_text",
        "eligibility_predicate",
        "amount_max_yen",
        "amount_min_yen",
        "amount_max_man_yen",
        "amount_min_man_yen",
        "deadline",
        "application_window",
        "application_window_json",
        "subsidy_rate",
        "tier",
    }
)


_TIMELINE_DISCLAIMER = (
    "本 timeline は am_amendment_diff / am_adoption_trend_monthly / "
    "am_enforcement_anomaly / am_adopted_company_features / "
    "am_program_narrative_full の各テーブルに対する機械的検索照合の集約であり、"
    "税理士法 §52 (税務代理) ・行政書士法 §1の2 (申請代理) ・弁護士法 §72 "
    "(法律事務) の代替ではない。severity / type は決定論的 enum マッピングであり、"
    "LLM 推論は含まれない。確定判断は資格を有する士業へ。"
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _resolve_program_aliases(
    am_conn: sqlite3.Connection,
    program_id: str,
) -> tuple[set[str], str | None, str | None]:
    """Resolve program_id to (all-known-id-forms, primary_name, jsic_major).

    The customer can pass either form:
      * `UNI-...` (jpintel canonical) — used by `programs` and
        `am_program_narrative_full`.
      * `program:...` (autonomath canonical) — used by
        `am_amendment_diff`.

    Returns:
        ids: set of known equivalents (always includes the input).
        primary_name: from am_entities (fallback None on miss).
        jsic_major: dominant JSIC major code (A-T, fallback None) used to
                    join the industry-level `am_adoption_trend_monthly`
                    rollup back to this program.
    """
    ids: set[str] = {program_id}
    primary_name: str | None = None
    jsic_major: str | None = None

    if _table_exists(am_conn, "entity_id_map"):
        try:
            # Walk both directions of the map.
            rows = am_conn.execute(
                "SELECT jpi_unified_id, am_canonical_id FROM entity_id_map "
                "WHERE jpi_unified_id = ? OR am_canonical_id = ?",
                (program_id, program_id),
            ).fetchall()
            for r in rows:
                jpi = r["jpi_unified_id"] if isinstance(r, sqlite3.Row) else r[0]
                am = r["am_canonical_id"] if isinstance(r, sqlite3.Row) else r[1]
                if jpi:
                    ids.add(jpi)
                if am:
                    ids.add(am)
        except sqlite3.Error as exc:
            logger.warning("entity_id_map lookup failed: %s", exc)

    if _table_exists(am_conn, "am_entities"):
        try:
            row = am_conn.execute(
                "SELECT primary_name FROM am_entities "
                "WHERE canonical_id IN ("
                + ",".join("?" for _ in ids)
                + ") AND record_kind='program' LIMIT 1",
                tuple(ids),
            ).fetchone()
            if row and row["primary_name"]:
                primary_name = str(row["primary_name"])
        except sqlite3.Error as exc:
            logger.warning("am_entities lookup failed: %s", exc)

    if _table_exists(am_conn, "am_industry_jsic"):
        # Best-effort: pull JSIC major from any program-keyed industry row.
        try:
            row = am_conn.execute(
                "SELECT jsic_major FROM am_industry_jsic "
                "WHERE program_canonical_id IN (" + ",".join("?" for _ in ids) + ") LIMIT 1",
                tuple(ids),
            ).fetchone()
            if row and row["jsic_major"]:
                jsic_major = str(row["jsic_major"])
        except sqlite3.Error:
            # `program_canonical_id` may not be a column in this schema —
            # fall through silently. JSIC may be left None which downstream
            # handles by emitting zero adoption events.
            pass

    return ids, primary_name, jsic_major


def _year_bounds(year: int) -> tuple[str, str]:
    """Return (start_iso, end_iso_exclusive) for the given year."""
    start = f"{year:04d}-01-01T00:00:00"
    end = f"{year + 1:04d}-01-01T00:00:00"
    return start, end


def _amendment_severity(field_name: str) -> str:
    return "high" if field_name in _HIGH_IMPACT_AMENDMENT_FIELDS else "med"


def _events_amendment(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    year: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    if not _table_exists(am_conn, "am_amendment_diff"):
        missing.append("am_amendment_diff")
        return []
    start, end = _year_bounds(year)
    out: list[dict[str, Any]] = []
    placeholders = ",".join("?" for _ in program_ids)
    try:
        rows = am_conn.execute(
            f"SELECT entity_id, field_name, prev_value, new_value, "
            f"       detected_at, source_url "
            f"  FROM am_amendment_diff "
            f" WHERE entity_id IN ({placeholders}) "
            f"   AND detected_at >= ? AND detected_at < ? "
            f" ORDER BY detected_at DESC LIMIT 500",
            (*program_ids, start, end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_amendment_diff query failed: %s", exc)
        return []
    for r in rows:
        field = r["field_name"] or ""
        prev = r["prev_value"]
        new = r["new_value"]
        # Truncate very long values into a readable summary.
        summary_parts: list[str] = []
        if prev is not None:
            summary_parts.append(f"prev={str(prev)[:80]}")
        if new is not None:
            summary_parts.append(f"new={str(new)[:80]}")
        summary = " → ".join(summary_parts) or "field cleared"
        out.append(
            {
                "date": r["detected_at"],
                "type": "amendment",
                "severity": _amendment_severity(field),
                "title": f"field amended: {field}",
                "summary": summary,
                "evidence_url": r["source_url"],
                "source_table": "am_amendment_diff",
            }
        )
    return out


def _events_adoption(
    am_conn: sqlite3.Connection,
    *,
    jsic_major: str | None,
    year: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    if not _table_exists(am_conn, "am_adoption_trend_monthly"):
        missing.append("am_adoption_trend_monthly")
        return []
    if not jsic_major:
        return []
    out: list[dict[str, Any]] = []
    try:
        rows = am_conn.execute(
            "SELECT year_month, adoption_count, distinct_houjin_count, "
            "       distinct_program_count, trend_flag "
            "  FROM am_adoption_trend_monthly "
            " WHERE jsic_major = ? AND substr(year_month, 1, 4) = ? "
            " ORDER BY year_month DESC",
            (jsic_major, f"{year:04d}"),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_adoption_trend_monthly query failed: %s", exc)
        return []
    for r in rows:
        ym = r["year_month"]
        # Convert YYYY-MM to a canonical month-end ISO date.
        try:
            yy, mm = ym.split("-")
            iso = f"{int(yy):04d}-{int(mm):02d}-01T00:00:00"
        except (ValueError, AttributeError):
            iso = f"{year:04d}-12-31T00:00:00"
        adoption_count = int(r["adoption_count"] or 0)
        distinct_houjin = int(r["distinct_houjin_count"] or 0)
        # Severity: large monthly batches are 'high', moderate 'med', else 'low'.
        if adoption_count >= 100:
            severity = "high"
        elif adoption_count >= 20:
            severity = "med"
        else:
            severity = "low"
        trend = r["trend_flag"] or "n/a"
        out.append(
            {
                "date": iso,
                "type": "adoption",
                "severity": severity,
                "title": f"{ym} 採択 {adoption_count} 件 (JSIC {jsic_major})",
                "summary": (f"{distinct_houjin} 法人 · trend={trend}"),
                "evidence_url": None,
                "source_table": "am_adoption_trend_monthly",
            }
        )
    return out


def _events_enforcement(
    am_conn: sqlite3.Connection,
    *,
    jsic_major: str | None,
    year: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    """Enforcement anomaly events surfaced for the program's industry slice.

    The `am_enforcement_anomaly` table is computed by a periodic cron with
    `last_updated` reflecting the last refresh moment. When that timestamp
    falls inside the requested year the row contributes one event. We do
    NOT replay historical enforcement — only the current anomaly snapshot,
    so the timeline reflects "as of last_updated" anomaly state for the
    industry.
    """
    if not _table_exists(am_conn, "am_enforcement_anomaly"):
        missing.append("am_enforcement_anomaly")
        return []
    if not jsic_major:
        return []
    start, end = _year_bounds(year)
    out: list[dict[str, Any]] = []
    try:
        rows = am_conn.execute(
            "SELECT prefecture_code, jsic_major, enforcement_count, "
            "       z_score, anomaly_flag, dominant_violation_kind, "
            "       last_updated "
            "  FROM am_enforcement_anomaly "
            " WHERE jsic_major = ? "
            "   AND last_updated >= ? AND last_updated < ? "
            " ORDER BY anomaly_flag DESC, z_score DESC LIMIT 100",
            (jsic_major, start, end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_enforcement_anomaly query failed: %s", exc)
        return []
    for r in rows:
        flag = int(r["anomaly_flag"] or 0)
        z = float(r["z_score"] or 0.0)
        if flag:
            severity = "high"
        elif abs(z) >= 1.0:
            severity = "med"
        else:
            severity = "low"
        pref = r["prefecture_code"]
        kind = r["dominant_violation_kind"] or "unknown"
        count = int(r["enforcement_count"] or 0)
        out.append(
            {
                "date": r["last_updated"],
                "type": "enforcement",
                "severity": severity,
                "title": (f"行政処分異常検知 {pref} JSIC {jsic_major} ({count} 件 · z={z:.2f})"),
                "summary": f"dominant_violation={kind} · anomaly_flag={flag}",
                "evidence_url": None,
                "source_table": "am_enforcement_anomaly",
            }
        )
    return out


def _events_narrative_update(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    year: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    if not _table_exists(am_conn, "am_program_narrative_full"):
        missing.append("am_program_narrative_full")
        return []
    start, end = _year_bounds(year)
    placeholders = ",".join("?" for _ in program_ids)
    out: list[dict[str, Any]] = []
    try:
        rows = am_conn.execute(
            f"SELECT program_id, generated_at, model_used, content_hash "
            f"  FROM am_program_narrative_full "
            f" WHERE program_id IN ({placeholders}) "
            f"   AND generated_at >= ? AND generated_at < ? "
            f" ORDER BY generated_at DESC LIMIT 200",
            (*program_ids, start, end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_narrative_full query failed: %s", exc)
        return []
    for r in rows:
        ch = r["content_hash"]
        out.append(
            {
                "date": r["generated_at"],
                "type": "narrative_update",
                "severity": "low",
                "title": "narrative regenerated",
                "summary": (
                    f"model={r['model_used'] or 'n/a'}" + (f" · hash={ch[:12]}" if ch else "")
                ),
                "evidence_url": None,
                "source_table": "am_program_narrative_full",
            }
        )
    return out


def _events_adopted_company(
    am_conn: sqlite3.Connection,
    *,
    program_ids: set[str],
    year: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    """Large individual adoption events filtered to the program's cohort.

    `am_adopted_company_features` aggregates per houjin (not per program),
    but its `last_adoption_at` is the freshest signal we have for "this
    company adopted SOMETHING recently". To keep the event tied to *this*
    program we filter via `jpi_adoption_records` if available; otherwise
    we skip (no industry-only fallback — too noisy).
    """
    if not _table_exists(am_conn, "am_adopted_company_features"):
        missing.append("am_adopted_company_features")
        return []
    if not _table_exists(am_conn, "jpi_adoption_records"):
        return []
    start, end = _year_bounds(year)
    placeholders = ",".join("?" for _ in program_ids)
    out: list[dict[str, Any]] = []
    try:
        rows = am_conn.execute(
            f"SELECT acf.houjin_bangou, acf.adoption_count, "
            f"       acf.last_adoption_at, acf.dominant_prefecture, "
            f"       acf.credibility_score "
            f"  FROM am_adopted_company_features acf "
            f"  JOIN jpi_adoption_records jar "
            f"    ON jar.houjin_bangou = acf.houjin_bangou "
            f" WHERE jar.program_id IN ({placeholders}) "
            f"   AND acf.last_adoption_at >= ? "
            f"   AND acf.last_adoption_at < ? "
            f" GROUP BY acf.houjin_bangou "
            f" ORDER BY acf.adoption_count DESC LIMIT 50",
            (*program_ids, start, end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("adopted_company join failed: %s", exc)
        return []
    for r in rows:
        n = int(r["adoption_count"] or 0)
        score = r["credibility_score"]
        # Severity: 5+ adoptions = high, 2-4 = med, 1 = low.
        if n >= 5:
            severity = "high"
        elif n >= 2:
            severity = "med"
        else:
            severity = "low"
        score_str = f"score={float(score):.2f} · " if score is not None else ""
        out.append(
            {
                "date": r["last_adoption_at"],
                "type": "adoption",
                "severity": severity,
                "title": (f"法人採択 houjin={r['houjin_bangou']} ({n} 件 累計)"),
                "summary": (f"{score_str}pref={r['dominant_prefecture'] or 'n/a'}"),
                "evidence_url": None,
                "source_table": "am_adopted_company_features",
            }
        )
    return out


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open autonomath.db read-only — None on missing/empty file."""
    try:
        from jpintel_mcp.config import settings

        p = settings.autonomath_db_path
        if not p.exists() or p.stat().st_size == 0:
            return None
        uri = f"file:{p}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn
    except (sqlite3.Error, AttributeError, OSError) as exc:
        logger.warning("autonomath open failed: %s", exc)
        return None


def _resolve_program_name_jpintel(conn: sqlite3.Connection, program_id: str) -> str | None:
    """Best-effort program name lookup against jpintel.db `programs.primary_name`."""
    try:
        row = conn.execute(
            "SELECT primary_name FROM programs WHERE unified_id = ? LIMIT 1",
            (program_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row and row["primary_name"]:
        return str(row["primary_name"])
    return None


def _build_timeline(
    conn: sqlite3.Connection,
    *,
    program_id: str,
    year: int,
    include_types: tuple[str, ...],
) -> dict[str, Any]:
    """Pure-SQL timeline assembly. Returns the body dict (pre-envelope)."""
    program_name = _resolve_program_name_jpintel(conn, program_id) or program_id
    missing: list[str] = []
    am_conn = _open_autonomath_ro()
    events: list[dict[str, Any]] = []
    try:
        if am_conn is None:
            missing.append("autonomath_db")
            program_ids: set[str] = {program_id}
            jsic_major: str | None = None
        else:
            program_ids, am_name, jsic_major = _resolve_program_aliases(am_conn, program_id)
            if am_name:
                program_name = am_name

            if "amendment" in include_types:
                events.extend(
                    _events_amendment(
                        am_conn,
                        program_ids=program_ids,
                        year=year,
                        missing=missing,
                    )
                )
            if "adoption" in include_types:
                # Two adoption streams: industry-level monthly rollup +
                # individual large-cohort houjin events.
                events.extend(
                    _events_adoption(
                        am_conn,
                        jsic_major=jsic_major,
                        year=year,
                        missing=missing,
                    )
                )
                events.extend(
                    _events_adopted_company(
                        am_conn,
                        program_ids=program_ids,
                        year=year,
                        missing=missing,
                    )
                )
            if "enforcement" in include_types:
                events.extend(
                    _events_enforcement(
                        am_conn,
                        jsic_major=jsic_major,
                        year=year,
                        missing=missing,
                    )
                )
            if "narrative_update" in include_types:
                events.extend(
                    _events_narrative_update(
                        am_conn,
                        program_ids=program_ids,
                        year=year,
                        missing=missing,
                    )
                )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    # Sort by date desc — push events with missing date to the bottom.
    def _key(e: dict[str, Any]) -> str:
        d = e.get("date")
        return d if isinstance(d, str) else ""

    events.sort(key=_key, reverse=True)

    summary_stats = {
        "amendments": sum(1 for e in events if e["type"] == "amendment"),
        "adoptions": sum(1 for e in events if e["type"] == "adoption"),
        "enforcement_actions": sum(1 for e in events if e["type"] == "enforcement"),
        "anomalies_flagged": sum(
            1 for e in events if e["type"] == "enforcement" and e["severity"] == "high"
        ),
        "narrative_updates": sum(1 for e in events if e["type"] == "narrative_update"),
    }

    body: dict[str, Any] = {
        "program_id": program_id,
        "program_name": program_name,
        "year": year,
        "include_types": list(include_types),
        "events": events,
        "summary_stats": summary_stats,
        "data_quality": {
            "missing_tables": missing,
            "event_count": len(events),
        },
        "_disclaimer": _TIMELINE_DISCLAIMER,
        "_billing_unit": 1,
    }
    return body


def _current_year() -> int:
    return datetime.now(UTC).year


@router.get(
    "/timeline/{program_id}",
    summary="Annual timeline — amendment + adoption + enforcement + narrative events",
    description=(
        "Returns the unified events timeline for a single program over one "
        "calendar year. Cross-joins `am_amendment_diff` (program updates), "
        "`am_adoption_trend_monthly` (industry monthly rollup), "
        "`am_enforcement_anomaly` (anomaly detection), "
        "`am_adopted_company_features` (大型 individual adoption events), "
        "and `am_program_narrative_full.generated_at` (narrative refreshes). "
        "Events sorted by date desc.\n\n"
        "**Pricing:** ¥3 / call (1 unit total) regardless of event count.\n\n"
        "**Sensitive:** §52 / §1 / §72 disclaimer envelope. NO LLM call. "
        "Severity / type are deterministic enum mappings."
    ),
)
def get_intel_timeline(
    program_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=200,
            description=(
                "Program canonical id. Accepts either the jpintel "
                "`UNI-...` form or the autonomath `program:...` form; "
                "the lookup walks `entity_id_map` to bridge both."
            ),
        ),
    ],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    year: Annotated[
        int,
        Query(
            ge=2000,
            le=2100,
            description=(
                "Calendar year for the timeline window (default = current year). Bounds 2000-2100."
            ),
        ),
    ] = 0,
    include_types: Annotated[
        list[str] | None,
        Query(
            description=(
                "Event types to include. Repeat the param to multi-select "
                "(e.g. `?include_types=amendment&include_types=adoption`). "
                "Allowed: amendment, adoption, enforcement, narrative_update. "
                "Defaults to all four when omitted."
            ),
        ),
    ] = None,
) -> JSONResponse:
    _t0 = time.perf_counter()

    pid = program_id.strip()
    if not pid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_program_id",
                "field": "program_id",
                "message": "program_id must be non-empty.",
            },
        )

    yr = year if year else _current_year()

    requested = tuple(include_types) if include_types else _DEFAULT_TYPES
    bad = [t for t in requested if t not in _ALLOWED_TYPES]
    if bad:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_include_types",
                "field": "include_types",
                "message": (
                    f"include_types contains unknown values: {bad}. "
                    f"Allowed: {sorted(_ALLOWED_TYPES)}."
                ),
            },
        )
    # Dedupe while preserving order of first appearance.
    seen: list[str] = []
    for t in requested:
        if t not in seen:
            seen.append(t)
    include_tuple = tuple(seen)

    body = _build_timeline(
        conn,
        program_id=pid,
        year=yr,
        include_types=include_tuple,
    )
    body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.timeline",
        latency_ms=latency_ms,
        result_count=len(body.get("events") or []),
        params={
            "program_id": pid,
            "year": yr,
            "include_types": list(include_tuple),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.timeline",
        request_params={
            "program_id": pid,
            "year": yr,
            "include_types": list(include_tuple),
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    # Compact-envelope projection (opt-in). Customer LLMs that pipe straight
    # into context can save 30-50% bytes via `?compact=true` or
    # `X-JPCite-Compact: 1`.
    if wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


__all__ = ["router"]
