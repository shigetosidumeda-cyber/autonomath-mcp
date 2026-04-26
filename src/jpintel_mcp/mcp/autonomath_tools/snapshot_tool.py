"""query_at_snapshot — R8 dataset versioning + audit-trail MCP tool.

Pins a query to the dataset state at a historical date so the caller can
reproduce the exact ``programs`` rows that were live at that timestamp.
Drives the **法廷証拠 (court-admissible evidence) reproducibility** value
prop for tax accountants / 行政書士 / 弁護士 who need 申告時点の制度状態
fixed for audit (電子帳簿保存法 §4-3 真実性確保).

Schema dependency: migration 067 added ``valid_from`` / ``valid_until``
columns to the 8 core jpintel.db tables. This tool reads ``programs`` only
and uses the canonical bitemporal predicate::

    valid_from <= as_of_date AND (valid_until IS NULL OR valid_until > as_of_date)

Response shape (envelope)::

    {
      "results": [ { unified_id, primary_name, tier, ..., source_url,
                     source_fetched_at, valid_from, valid_until }, ... ],
      "snapshot_at": "2026-04-25",
      "audit_trail": {
        "source_url":        "<row[0].source_url>",
        "fetched_at":        "<row[0].source_fetched_at>",
        "valid_from":        "<row[0].valid_from>",
        "predicate":         "valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)",
        "table":             "programs",
        "schema_migration":  "067_dataset_versioning.sql",
      },
      "total": <int>,
      "limit": <int>,
      "offset": 0,
      "_disclaimer": "<法廷証拠注記>"
    }

The ``audit_trail`` block carries the 3-axis timestamp triple
(``source_url`` + ``fetched_at`` + ``valid_from``) the operator needs to
reconstruct provenance during a tax audit / litigation. ``predicate``
echoes the exact SQL fragment so the auditor can replay the query
deterministically against a snapshot of the DB.

Gating: respects ``settings.r8_versioning_enabled`` (env
``AUTONOMATH_R8_VERSIONING_ENABLED``). When disabled, returns a
``subsystem_unavailable`` error envelope and points back to
``search_programs`` for the live-only path.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import Settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.snapshot")

# Disclaimer text. Tracks the 法廷証拠 framing in
# docs/compliance/data_governance.md §「法廷証拠 reproducibility 保証」.
_DISCLAIMER = (
    "本 response は R8 dataset versioning に基づく as-of スナップショットです。"
    "valid_from / valid_until / source_fetched_at / source_url の 4 軸で再現可能"
    "(電子帳簿保存法 §4-3 真実性確保 + 個情法 26 条) ですが、最終的な制度該当性"
    "判断は一次資料 (source_url) と税理士 / 弁護士確認を優先してください。"
)

_PREDICATE_SQL = "valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)"


def _validate_iso_date(s: str) -> str:
    """Return canonical YYYY-MM-DD or raise ValueError."""
    return _dt.date.fromisoformat(s).isoformat()


@mcp.tool(annotations=_READ_ONLY)
def query_at_snapshot(
    query_payload: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Search filters. Recognised keys: `q` (free-text), "
                "`tier` (list of S/A/B/C), `prefecture` (str), "
                "`authority_level` (str), `program_kind` (str), "
                "`limit` (int, default 20, max 100). Unknown keys are "
                "ignored. Filter shape mirrors GET /v1/programs/search."
            ),
        ),
    ],
    as_of_date: Annotated[
        str,
        Field(
            description=(
                "Snapshot pivot, ISO-8601 YYYY-MM-DD. The result set is "
                "the rows whose `valid_from` <= as_of_date AND "
                "(`valid_until` IS NULL OR `valid_until` > as_of_date). "
                "Rejected with `invalid_date_format` if not parseable."
            ),
            min_length=10,
            max_length=10,
        ),
    ],
) -> dict[str, Any]:
    """[AUDIT] R8 — pin programs query to historical dataset state. Returns rows + 3-axis audit trail (source_url + fetched_at + valid_from) for 法廷証拠 reproducibility.

    WHAT: Replays the search filter set in ``query_payload`` against
    ``programs`` with the bitemporal predicate ``valid_from <= as_of_date
    AND (valid_until IS NULL OR valid_until > as_of_date)``. Returns the
    matching rows + a single ``audit_trail`` block with the 3-axis
    timestamp triple (``source_url`` + ``fetched_at`` + ``valid_from``)
    drawn from the first result row.

    WHEN:
      - 「2026-03-15 申告時点で公募中だった補助金リスト」(tax filing audit)
      - 「弁護士 due-diligence: 契約締結時の規制状態を再現」
      - 「税理士: 過去 3 年分の制度該当判定を 2027 年に検証」

    WHEN NOT:
      - 現時点 live のみ知りたい → search_programs (R8 不要、cache hit)
      - 制度の effective_until を知りたい → list_tax_sunset_alerts
      - 単一 unified_id の as-of 取得 → REST GET /v1/programs/{id}?as_of_date=...

    RETURNS (envelope on success):
      {
        results: [ { unified_id, primary_name, tier, prefecture,
                     authority_level, program_kind, official_url,
                     source_url, source_fetched_at,
                     valid_from, valid_until }, ... ],
        snapshot_at: "YYYY-MM-DD",
        audit_trail: {
          source_url: str|null,
          fetched_at: str|null,
          valid_from: str|null,
          predicate: "valid_from <= ? AND (valid_until IS NULL OR valid_until > ?)",
          table: "programs",
          schema_migration: "067_dataset_versioning.sql",
        },
        total, limit, offset: 0,
        _disclaimer: "<本 response は R8 dataset versioning ...>",
      }

    On invalid date / disabled subsystem returns the canonical error
    envelope (``code`` ∈ {``invalid_date_format``,
    ``subsystem_unavailable``, ``db_unavailable``}).
    """
    # Subsystem gate. Default True; flip env "0" / "false" for one-flag
    # rollback. Memory: zero-touch, no UI, this is the API-only kill.
    if not Settings().r8_versioning_enabled:
        return make_error(
            code="subsystem_unavailable",
            message="R8 dataset versioning disabled (AUTONOMATH_R8_VERSIONING_ENABLED=0).",
            hint=(
                "Operator has temporarily disabled snapshot pinning. Use "
                "search_programs for live-only queries; retry once the env "
                "flag is restored."
            ),
            retry_with=["search_programs"],
        )

    # Date validation. Closed enum 'invalid_date_format' so the LLM can
    # pattern-match instead of parsing the message string.
    try:
        as_of_iso = _validate_iso_date(as_of_date)
    except (TypeError, ValueError) as exc:
        return make_error(
            code="invalid_date_format",
            message=f"as_of_date must be ISO-8601 YYYY-MM-DD ({exc}).",
            hint="Pass a string like '2026-03-15'. Year must be ≥ 1900.",
            field="as_of_date",
        )

    # Pull whitelisted filters out of payload. Unknown keys are
    # intentionally ignored — we keep the surface area small so the LLM
    # cannot accidentally smuggle SQL fragments.
    payload = query_payload or {}
    q = payload.get("q")
    tier = payload.get("tier")
    prefecture = payload.get("prefecture")
    authority_level = payload.get("authority_level")
    program_kind = payload.get("program_kind")
    limit = int(payload.get("limit", 20) or 20)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    where: list[str] = ["excluded = 0", "COALESCE(tier,'X') != 'X'"]
    params: list[Any] = []
    if q:
        like = f"%{q}%"
        where.append("(primary_name LIKE ? OR aliases_json LIKE ?)")
        params.extend([like, like])
    if isinstance(tier, list) and tier:
        placeholders = ",".join("?" * len(tier))
        where.append(f"tier IN ({placeholders})")
        params.extend([str(t) for t in tier])
    elif isinstance(tier, str):
        where.append("tier = ?")
        params.append(tier)
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    if authority_level:
        where.append("authority_level = ?")
        params.append(authority_level)
    if program_kind:
        where.append("program_kind = ?")
        params.append(program_kind)

    # Bitemporal predicate (the whole point of R8).
    where.append(_PREDICATE_SQL)
    params.extend([as_of_iso, as_of_iso])

    where_sql = " AND ".join(where)
    sql = (
        "SELECT unified_id, primary_name, tier, prefecture, authority_level, "
        "program_kind, official_url, source_url, source_fetched_at, "
        "valid_from, valid_until "
        f"FROM programs WHERE {where_sql} "
        "ORDER BY tier, primary_name LIMIT ?"
    )
    params.append(limit)

    # Use the same db_path the REST API uses. Avoids cross-DB drift in
    # tests where conftest sets JPINTEL_DB_PATH before any import.
    db_path = Settings().db_path
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.exception("query_at_snapshot db error")
        return make_error(
            code="db_unavailable",
            message=str(exc)[:120],
            hint="jpintel.db unreachable; retry later or fall back to search_programs.",
            retry_with=["search_programs"],
        )
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass

    results = [dict(r) for r in rows]
    first = results[0] if results else {}
    audit_trail = {
        "source_url": first.get("source_url"),
        "fetched_at": first.get("source_fetched_at"),
        "valid_from": first.get("valid_from"),
        "predicate": _PREDICATE_SQL,
        "table": "programs",
        "schema_migration": "067_dataset_versioning.sql",
    }

    return {
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "results": results,
        "snapshot_at": as_of_iso,
        "audit_trail": audit_trail,
        "_disclaimer": _DISCLAIMER,
    }
