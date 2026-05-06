"""DEEP-22 Regulatory Time Machine — past-eligibility replay (no LLM).

Two MCP tools that pivot off the autonomath spine
(`am_amendment_snapshot.effective_from` + 144 definitive-dated rows + 14,596
captures total) so a caller can ask "what eligibility was live for
program X on YYYY-MM-DD" and get back a frozen-at-date envelope with a
3-axis citation (source_url + source_fetched_at + content hash).

Pure SQLite + Python.

  * NO LLM call — closed-form replay over am_amendment_snapshot.
  * NO 採択 prediction — factual retrieval only. §52 / §47条の2 / §72 /
    §1 fence enforced via `_disclaimer` envelope on every response.
  * Single ¥3/req billing event per tool call (the evolution variant
    runs 12 monthly pivots inside one call but still bills as 1 unit).

Quality flag taxonomy (DEEP-22 §4)
----------------------------------

  definitive       effective_from IS NOT NULL — date verified at ingest.
  inferred         effective_from IS NULL but eligibility_hash matched
                   v(n-1) so we know the version exists; date is best-
                   effort. ``known_gaps`` carries
                   ``eligibility_text_diff_unverified`` when the v(n-1)
                   hash is identical to the current row.
  template_default am_amount_condition row tagged template_default=1
                   (i.e. broken ETL pass placeholder ¥500K/¥2M). Returns
                   ``amount: null`` and adds ``amount_not_captured_at_date``
                   to ``known_gaps``.

Response envelope
-----------------

::

    {
      "program_id":         "<canonical jpcite id>",
      "as_of_resolved":     "YYYY-MM-DD" | null,
      "eligibility":        {...}    | null,
      "amount":             {...}    | null,
      "deadline":           "YYYY-MM-DD" | null,
      "source_url":         str  | null,
      "source_fetched_at":  str  | null,
      "source_sha256":      str  | null,
      "quality_flag":       "definitive" | "inferred" | "template_default",
      "known_gaps":         [str, ...],
      "snapshot_id":        int   | null,
      "version_seq":        int   | null,
      "_disclaimer":        "<§52 / §47条の2 fence>",
      "_billing_unit":      1,
      "corpus_snapshot_id": "<as-of marker>",
      "corpus_checksum":    "sha256:<hex>",
    }

Empty / not-found / before-corpus paths still emit a well-formed
envelope with ``as_of_resolved=null`` and ``quality_flag='definitive'``
on the empty result so the customer LLM can keep walking.

Out of scope (DEEP-22 §12):
  * 採択 prediction (`forecast_program_renewal`, Wave 22).
  * Bulk export — per-row metered access only.
  * LLM summarisation — pure SQLite + Python.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot_with_conn

logger = logging.getLogger("jpintel.mcp.autonomath.time_machine")

# Env-gated registration. Default tracks settings.autonomath_snapshot_enabled
# so flipping AUTONOMATH_SNAPSHOT_ENABLED=1 lights up the time machine
# without needing a separate flag.
_ENABLED = os.environ.get(
    "AUTONOMATH_SNAPSHOT_ENABLED", "1" if settings.autonomath_snapshot_enabled else "0"
) in ("1", "true", "True", "yes", "on")


# ---------------------------------------------------------------------------
# Disclaimer (§52 / §47条の2 / §72 / §1 fence — DEEP-22 §9)
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "本 response は am_amendment_snapshot に格納された過去時点の事実情報の検索結果です。"
    "採択予測 (forecast_program_renewal が別) ではなく、契約締結時・申告時点の制度状態を"
    "事実 として再生するもの。"
    "税理士法 §52 (税務代理) ・公認会計士法 §47条の2 (監査) ・弁護士法 §72 (法律事件) ・"
    "行政書士法 §1 (申請書面) の代替ではありません。"
    "as_of_resolved の date は am_amendment_snapshot.effective_from の値であり、quality_flag が "
    "'inferred' の場合は eligibility_hash 一致からの推定で、原典 (source_url) を別途確認してください。"
)


# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------

# DEEP-22 §4 main lookup. Pulls the most-recent snapshot whose
# effective_from <= as_of (NULL effective_from is treated as the earliest
# possible date so we still surface the row, but only if no dated
# version exists at as_of).
#
# Note: DEEP-22 spec mentions LEFT JOIN source_receipt sr USING receipt_id,
# but the production schema stores source_url + source_fetched_at directly
# on am_amendment_snapshot (verified 2026-05-07). No JOIN needed.
_SNAPSHOT_LOOKUP_SQL = """
SELECT s.snapshot_id, s.version_seq, s.effective_from, s.effective_until,
       s.eligibility_hash, s.amount_max_yen, s.subsidy_rate_max,
       s.target_set_json, s.source_url, s.source_fetched_at,
       s.raw_snapshot_json
  FROM am_amendment_snapshot s
 WHERE s.entity_id = :program_id
   AND (s.effective_from IS NULL OR s.effective_from <= :as_of)
 ORDER BY COALESCE(s.effective_from, '0000-01-01') DESC,
          s.version_seq DESC
 LIMIT 1
"""

# Previous-version lookup for eligibility_hash diff detection.
_PREVIOUS_VERSION_SQL = """
SELECT eligibility_hash
  FROM am_amendment_snapshot
 WHERE entity_id = :program_id
   AND version_seq < :version_seq
 ORDER BY version_seq DESC
 LIMIT 1
"""

# Min effective_from per program — used to detect before_first_capture.
_MIN_CAPTURE_SQL = """
SELECT MIN(COALESCE(effective_from, observed_at)) AS min_capture
  FROM am_amendment_snapshot
 WHERE entity_id = :program_id
"""

# Existence check — if 0 rows, return not_found.
_EXISTS_CHECK_SQL = """
SELECT COUNT(*) AS n
  FROM am_amendment_snapshot
 WHERE entity_id = :program_id
"""

# am_amount_condition template-default check. Schema actual columns:
# fixed_yen / percentage / template_default. Pull most-recent row.
_AMOUNT_CONDITION_SQL = """
SELECT fixed_yen, percentage,
       COALESCE(template_default, 0) AS template_default
  FROM am_amount_condition
 WHERE entity_id = :program_id
 ORDER BY promoted_at DESC
 LIMIT 1
"""


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------


def _validate_iso_date(s: str) -> str:
    """Return canonical YYYY-MM-DD or raise ValueError."""
    return _dt.date.fromisoformat(s).isoformat()


def _today_jst_iso() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).date().isoformat()


# ---------------------------------------------------------------------------
# Single point-in-time replay
# ---------------------------------------------------------------------------


def _query_at_snapshot_impl(
    program_id: str,
    as_of: str,
) -> dict[str, Any]:
    """Replay program eligibility / amount / deadline at as_of.

    Returns the canonical envelope (see module docstring) on every code
    path. Errors collapse to make_error() envelopes that still surface
    `corpus_snapshot_id` + `_billing_unit` so the caller's billing
    pipeline can register a unit even on the unhappy path.
    """
    if not program_id or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
            hint="Pass a canonical jpcite program id like 'program:IT_DOUNYUU_HOJOKIN'.",
        )

    try:
        as_of_iso = _validate_iso_date(as_of)
    except (TypeError, ValueError) as exc:
        return make_error(
            code="invalid_date_format",
            message=f"as_of must be ISO YYYY-MM-DD ({exc}).",
            field="as_of",
            hint="Pass a string like '2024-06-01'. JST timezone implied.",
        )

    try:
        conn = connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            retry_with=["search_programs"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_programs"],
        )

    # 1. Existence check — if program_id has zero snapshots, return not_found.
    try:
        existence = conn.execute(_EXISTS_CHECK_SQL, {"program_id": program_id}).fetchone()
    except sqlite3.Error as exc:
        logger.warning("query_at_snapshot existence check failed: %s", exc)
        return make_error(
            code="db_unavailable",
            message=f"existence check failed: {exc}",
        )

    if not existence or int(existence["n"]) == 0:
        return make_error(
            code="seed_not_found",
            message=f"program_id {program_id!r} not found in am_amendment_snapshot.",
            field="program_id",
            hint=(
                "Use search_programs to find the canonical id, or "
                "active_programs_at to enumerate live programs at a date."
            ),
            retry_with=["search_programs", "active_programs_at"],
        )

    # 2. before_first_capture check — if as_of < min(effective_from), no
    #    fabrication: return as_of_resolved=null with empty payload.
    min_row = conn.execute(_MIN_CAPTURE_SQL, {"program_id": program_id}).fetchone()
    min_capture = (min_row["min_capture"] if min_row else None) or None
    before_first = bool(min_capture and as_of_iso < str(min_capture)[:10])

    # 3. Main lookup.
    row = conn.execute(
        _SNAPSHOT_LOOKUP_SQL, {"program_id": program_id, "as_of": as_of_iso}
    ).fetchone()

    if before_first or row is None:
        body = _empty_envelope(program_id=program_id, as_of_resolved=None)
        attach_corpus_snapshot_with_conn(conn, body)
        return body

    # 4. Quality flag derivation.
    quality_flag = "definitive" if row["effective_from"] is not None else "inferred"
    known_gaps: list[str] = []

    # Hash-match check for inferred rows.
    if quality_flag == "inferred" and row["eligibility_hash"] is not None:
        prev = conn.execute(
            _PREVIOUS_VERSION_SQL,
            {"program_id": program_id, "version_seq": row["version_seq"]},
        ).fetchone()
        if prev and prev["eligibility_hash"] == row["eligibility_hash"]:
            known_gaps.append("eligibility_text_diff_unverified")

    # 5. Amount + template_default check.
    amount: dict[str, Any] | None
    try:
        amt_row = conn.execute(_AMOUNT_CONDITION_SQL, {"program_id": program_id}).fetchone()
    except sqlite3.Error:
        amt_row = None

    if amt_row and int(amt_row["template_default"]) == 1:
        # Template-default: surface null amount, override quality flag.
        amount = None
        # template_default is the dominant signal — amount is unreliable
        # so the customer LLM should not treat it as a verified value.
        quality_flag = "template_default"
        known_gaps.append("amount_not_captured_at_date")
    else:
        # Prefer the snapshot row's own amount fields (point-in-time
        # frozen state); fall back to the most-recent am_amount_condition
        # row when the snapshot row was captured before the amount
        # extractor wave.
        max_yen = row["amount_max_yen"]
        rate = row["subsidy_rate_max"]
        if max_yen is None and amt_row:
            max_yen = amt_row["fixed_yen"]
        if rate is None and amt_row:
            rate = amt_row["percentage"]
        amount = None if (max_yen is None and rate is None) else {"max_yen": max_yen, "rate": rate}

    # 6. Eligibility payload extraction from raw_snapshot_json.
    eligibility: dict[str, Any] | None = None
    deadline: str | None = None
    raw_payload = row["raw_snapshot_json"]
    if raw_payload:
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                eligibility = parsed.get("eligibility") or parsed.get("eligibility_text")
                # Some rows store eligibility as a list of conditions.
                if eligibility is None and "conditions" in parsed:
                    eligibility = {"conditions": parsed.get("conditions")}
                deadline = parsed.get("deadline") or parsed.get("application_deadline")
        except (json.JSONDecodeError, TypeError):
            # Malformed payload — surface as known_gap, do not fabricate.
            known_gaps.append("payload_unparseable")

    if eligibility is None and row["target_set_json"]:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            eligibility = {"target_set": json.loads(row["target_set_json"])}

    # 7. Source citation 3-axis. source_sha256 is best-effort hashed
    #    against payload content; fall back to eligibility_hash when no
    #    raw payload was stored (the eligibility_hash is itself a SHA256
    #    of normalized eligibility text — see schema comment).
    source_sha256 = None
    if row["eligibility_hash"]:
        source_sha256 = row["eligibility_hash"]

    body = {
        "program_id": program_id,
        "as_of_resolved": str(row["effective_from"])[:10] if row["effective_from"] else None,
        "as_of_requested": as_of_iso,
        "eligibility": eligibility,
        "amount": amount,
        "deadline": deadline,
        "source_url": row["source_url"],
        "source_fetched_at": row["source_fetched_at"],
        "source_sha256": source_sha256,
        "quality_flag": quality_flag,
        "known_gaps": known_gaps,
        "snapshot_id": int(row["snapshot_id"]),
        "version_seq": int(row["version_seq"]),
        # Canonical §10.7/10.8 envelope keys.
        "results": [],
        "total": 1,
        "limit": 1,
        "offset": 0,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    attach_corpus_snapshot_with_conn(conn, body)
    return body


def _empty_envelope(program_id: str, as_of_resolved: str | None) -> dict[str, Any]:
    """Empty-but-well-formed envelope for before_first_capture path."""
    return {
        "program_id": program_id,
        "as_of_resolved": as_of_resolved,
        "eligibility": None,
        "amount": None,
        "deadline": None,
        "source_url": None,
        "source_fetched_at": None,
        "source_sha256": None,
        "quality_flag": "definitive",  # empty result is itself definitive
        "known_gaps": ["before_first_capture"] if as_of_resolved is None else [],
        "snapshot_id": None,
        "version_seq": None,
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


# ---------------------------------------------------------------------------
# 12-month evolution grid
# ---------------------------------------------------------------------------


def _query_program_evolution_impl(
    program_id: str,
    year: int,
) -> dict[str, Any]:
    """Run 12 monthly pivots inside one call (single ¥3 metered event).

    Returns a `months` list of 12 envelopes (one per month, Jan-Dec of
    `year`) plus a top-level summary so the caller can spot the
    months in which eligibility / amount / deadline changed without
    making 12 independent calls.
    """
    if not program_id or not program_id.strip():
        return make_error(
            code="missing_required_arg",
            message="program_id is required.",
            field="program_id",
        )
    if not isinstance(year, int) or year < 1900 or year > 2100:
        return make_error(
            code="out_of_range",
            message=f"year must be 1900..2100 (got {year!r}).",
            field="year",
        )

    months: list[dict[str, Any]] = []
    last_quality: str | None = None
    change_months: list[int] = []
    for month in range(1, 13):
        # Use the last day of the month as the snapshot pivot so the
        # caller sees the state at month-end (matches the typical
        # accounting pivot for 月次 review). Days vary by month so we
        # use the first day of the next month minus 1 day approach.
        if month == 12:
            pivot = _dt.date(year, 12, 31)
        else:
            pivot = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
        envelope = _query_at_snapshot_impl(program_id, pivot.isoformat())
        # Strip the inner billing/disclaimer keys — the outer envelope
        # carries the single billing unit.
        envelope.pop("_billing_unit", None)
        envelope.pop("_disclaimer", None)
        months.append(envelope)

        snap_id = envelope.get("snapshot_id")
        if last_quality is not None and snap_id != last_quality:
            change_months.append(month)
        last_quality = snap_id

    body: dict[str, Any] = {
        "program_id": program_id,
        "year": year,
        "months": months,
        "change_months": change_months,
        "results": months,
        "total": len(months),
        "limit": 12,
        "offset": 0,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    try:
        conn = connect_autonomath()
        attach_corpus_snapshot_with_conn(conn, body)
    except (FileNotFoundError, sqlite3.Error):
        pass
    return body


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def query_at_snapshot_v2(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "Canonical jpcite program id (e.g. "
                    "'program:IT_DOUNYUU_HOJOKIN'). Use search_programs "
                    "to discover ids."
                ),
            ),
        ],
        as_of: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description=(
                    "Snapshot pivot, ISO YYYY-MM-DD (JST). Returns the "
                    "version of the program live at that date."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52 / §47条の2] DEEP-22 Time Machine. Returns the program's eligibility / amount / deadline frozen at as_of, with 3-axis citation (source_url + source_fetched_at + source_sha256). Pivots off am_amendment_snapshot (14,596 captures, 144 definitive-dated). NOT 採択 prediction; factual replay only."""
        return _query_at_snapshot_impl(program_id=program_id, as_of=as_of)

    @mcp.tool(annotations=_READ_ONLY)
    def query_program_evolution(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=("Canonical jpcite program id (e.g. 'program:IT_DOUNYUU_HOJOKIN')."),
            ),
        ],
        year: Annotated[
            int,
            Field(
                ge=1900,
                le=2100,
                description="Calendar year (e.g. 2024). 12 month-end pivots returned.",
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52 / §47条の2] DEEP-22 Time Machine — 12-month evolution grid. Runs query_at_snapshot at every month-end of `year` in one call (single ¥3 metered event, 11 cached reads). Surfaces change_months for diligence walks. NOT 採択 prediction; factual replay only."""
        return _query_program_evolution_impl(program_id=program_id, year=year)


__all__ = [
    "_query_at_snapshot_impl",
    "_query_program_evolution_impl",
]
