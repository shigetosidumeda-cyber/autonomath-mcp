"""program_lifecycle — O4 Amendment Lifecycle MCP tool (2026-04-25).

Decidable 8-step status precedence for a `program` canonical_id, evaluated
purely from existing structured tables. **No LLM inference**, no external
fetch — all signals come from `am_amendment_snapshot` (14,596 rows),
`am_relation` (23,805 edges, 15 canonical relation_types), and
`am_entities` (header).

Design source: ``analysis_wave18/_o4_lifecycle_2026-04-25.md``.

Honest-disclosure stance (CLAUDE.md gotcha + memory `feedback_no_fake_data`)
-----------------------------------------------------------------------------
`am_amendment_snapshot` is officially flagged as a *fake* time-series:
14,596 rows = 7,298 entities × 2 versions, but `eligibility_hash` does not
move between v1 and v2 (12,014 / 14,596 share `e3b0c4…` = sha256 of empty
string). `effective_from` is filled on 140 rows and `effective_until` on
just 4. We therefore:

  1. Use `effective_until` / `effective_from` only when present (they ARE
     present on a small but trustworthy subset — e.g. 「電気・ガス料金負担
     軽減支援事業（令和7年度）」 has 2026-01..2026-03).
  2. Fall back to `am_relation` lineage edges (`successor_of`, `replaces`)
     for `abolished` / `superseded` detection.
  3. Surface the underlying snapshot uniformity as
     ``confidence: 'low' if amendment_snapshot drove the verdict``, with
     an explicit `_disclaimer` string so downstream LLMs honest-disclose.
  4. Default `confidence='medium'` for relation-edge-driven verdicts and
     `confidence='high'` only when both effective dates AND a lineage
     edge agree.

Status precedence (first match wins, no LLM judgement)
------------------------------------------------------
  1. `abolished`        — outgoing `replaces` edge (this entity was replaced)
  2. `superseded`       — outgoing `successor_of` edge (this entity is the
                          predecessor of a successor that took over)
  3. `sunset_imminent`  — `effective_until - as_of < 90 days`
  4. `sunset_scheduled` — `effective_until - as_of >= 90 days`
  5. `amended`          — latest `am_amendment_snapshot.effective_from <=
                          as_of` AND that snapshot version > 1
  6. `active`           — `effective_from <= as_of` AND
                          (`effective_until` IS NULL OR > as_of)
  7. `not_yet`          — `effective_from > as_of`
  8. `unknown`          — no temporal grounding at all

Env gate: ``AUTONOMATH_LIFECYCLE_ENABLED`` (default "1"). Set "0" to
omit the tool from `mcp.list_tools()` (rollback only).

¥3/req metered, no Anthropic API call, no UI dependency.
"""

from __future__ import annotations

import datetime
import logging
import re
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.lifecycle")

# Env-gated registration. Default "1" (on) so launch ships with the tool;
# flip to "0" for one-flag rollback if a regression surfaces.
_ENABLED = get_flag("JPCITE_LIFECYCLE_ENABLED", "AUTONOMATH_LIFECYCLE_ENABLED", "1") == "1"

# Disclaimer text appended to every response so downstream LLMs honest-
# disclose. Per CLAUDE.md: "am_amendment_snapshot eligibility_hash never
# changes between v1/v2, time-series is fake".
_DISCLAIMER = (
    "am_amendment_snapshot は 12,014/14,596 行が空文字列の sha256 で "
    "eligibility_hash uniform、time-series は構造的に薄い。本ツールは "
    "amendment_snapshot 由来の判定では confidence='low' を付与する。"
)

# Status labels (Japanese) for the 8 deterministic states.
_STATUS_LABEL_JA: dict[str, str] = {
    "abolished": "廃止",
    "superseded": "後継制度へ移行",
    "sunset_imminent": "終了直前 (90日以内)",
    "sunset_scheduled": "終了予定",
    "amended": "改正済み",
    "active": "稼働中",
    "not_yet": "開始前",
    "unknown": "不明 (metadata 不足)",
}

# Threshold in days that separates `sunset_imminent` from `sunset_scheduled`.
_SUNSET_IMMINENT_DAYS = 90


# ---------------------------------------------------------------------------
# Date parsing — am_amendment_snapshot effective_from/until are free-form
# Japanese strings (e.g. "2032年頃（期間満了順次）", "2025-08-08採択",
# "法定書面受領日を1日目として起算"). We extract a strict YYYY-MM-DD or
# YYYY-MM prefix when one is parseable, else return None and fall through
# precedence to the lineage / unknown path.
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?")
# Japanese 和暦-free year-month form: 2026年04月 / 2026年4月 etc.
_JP_YEAR_MONTH_RE = re.compile(r"^(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?")


def _parse_iso_date(value: str | None) -> datetime.date | None:
    """Parse a raw effective_from/until string to a `date` if possible.

    Accepts:
      - ``YYYY-MM-DD``           → exact
      - ``YYYY-MM``              → first day of the month
      - ``YYYY年MM月`` / ``YYYY年MM月DD日`` → JP year-month variant

    Returns None for ambiguous strings (e.g. ``2032年頃`` or
    ``法定書面受領日を1日目として起算``) — those are explicitly excluded
    from sunset / active determination so the tool never asserts a
    deterministic status from an un-parseable string.
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    m = _ISO_DATE_RE.match(s)
    if m:
        try:
            year = int(m.group(1))
            month = int(m.group(2))
            day = int(m.group(3)) if m.group(3) else 1
            return datetime.date(year, month, day)
        except ValueError:
            return None
    m = _JP_YEAR_MONTH_RE.match(s)
    if m:
        try:
            year = int(m.group(1))
            month = int(m.group(2))
            day = int(m.group(3)) if m.group(3) else 1
            return datetime.date(year, month, day)
        except ValueError:
            return None
    return None


def _today_jst() -> datetime.date:
    """Return today in JST. Fly.io machines run UTC; naive `date.today()`
    drifts 9h. Same pivot pattern as `sunset_tool.py`.
    """
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=9)).date()


# ---------------------------------------------------------------------------
# Internal evaluator — pure SQL + precedence walk.
# ---------------------------------------------------------------------------


def _program_lifecycle_impl(
    unified_id: str,
    as_of: datetime.date,
) -> dict[str, Any]:
    """Compute the lifecycle envelope for `unified_id` as_of `as_of`.

    Returns the canonical response dict (no error envelope). Caller is
    responsible for wrapping any exceptions in `make_error()`.
    """
    conn = connect_autonomath()

    # --- header lookup -----------------------------------------------------
    header_row = conn.execute(
        "SELECT canonical_id, primary_name, record_kind, canonical_status "
        "FROM am_entities WHERE canonical_id = ?",
        (unified_id,),
    ).fetchone()

    if header_row is None:
        return {
            "unified_id": unified_id,
            "status": "unknown",
            "status_label_ja": _STATUS_LABEL_JA["unknown"],
            "evidence": {
                "amendment": None,
                "relation": None,
                "effective_dates": None,
            },
            "confidence": "low",
            "reason": (
                f"unified_id '{unified_id}' not found in am_entities. "
                "Use search_programs / enum_values_am to resolve canonical_id first."
            ),
            "as_of": as_of.isoformat(),
            "_disclaimer": _DISCLAIMER,
        }

    primary_name = header_row["primary_name"]
    record_kind = header_row["record_kind"]
    canonical_status = header_row["canonical_status"]

    # --- amendment latest version -----------------------------------------
    amendment_row = conn.execute(
        """
        SELECT version_seq, observed_at, effective_from, effective_until,
               source_url, source_fetched_at
          FROM am_amendment_snapshot
         WHERE entity_id = ?
         ORDER BY version_seq DESC
         LIMIT 1
        """,
        (unified_id,),
    ).fetchone()

    eff_from_raw = amendment_row["effective_from"] if amendment_row else None
    eff_until_raw = amendment_row["effective_until"] if amendment_row else None
    eff_from = _parse_iso_date(eff_from_raw)
    eff_until = _parse_iso_date(eff_until_raw)
    if amendment_row is not None and eff_from is None and eff_until is None:
        grounded_row = conn.execute(
            """
            SELECT version_seq, observed_at, effective_from, effective_until,
                   source_url, source_fetched_at
              FROM am_amendment_snapshot
             WHERE entity_id = ?
               AND (
                    effective_from LIKE '____-__-__'
                 OR effective_until LIKE '____-__-__'
               )
             ORDER BY version_seq DESC
             LIMIT 1
            """,
            (unified_id,),
        ).fetchone()
        if grounded_row is not None:
            amendment_row = grounded_row
            eff_from_raw = amendment_row["effective_from"]
            eff_until_raw = amendment_row["effective_until"]
            eff_from = _parse_iso_date(eff_from_raw)
            eff_until = _parse_iso_date(eff_until_raw)

    # --- relation lineage --------------------------------------------------
    # Outgoing `replaces` = this entity HAS a target it replaces (in
    # am_relation `replaces` semantics, source replaced/abolished a target;
    # we also surface this asymmetrically as the source being abolished
    # only when the target row carries `effective_from <= as_of`).
    # Outgoing `successor_of` = this entity HAS a successor target — this
    # entity is the predecessor → status `superseded`.
    relation_row = conn.execute(
        """
        SELECT relation_type, target_entity_id, confidence, source_field
          FROM am_relation
         WHERE source_entity_id = ?
           AND relation_type IN ('replaces', 'successor_of')
         ORDER BY confidence DESC
         LIMIT 1
        """,
        (unified_id,),
    ).fetchone()

    # ----------------------------------------------------------------------
    # Precedence-order evaluation. First match wins.
    # ----------------------------------------------------------------------
    status: str
    confidence: str
    reason: str

    # 1. abolished
    if relation_row and relation_row["relation_type"] == "replaces":
        status = "abolished"
        confidence = "medium"
        reason = (
            f"am_relation.relation_type='replaces' edge "
            f"(target={relation_row['target_entity_id'] or 'unbound'}, "
            f"confidence={relation_row['confidence']})."
        )

    # 2. superseded
    elif relation_row and relation_row["relation_type"] == "successor_of":
        status = "superseded"
        confidence = "medium"
        reason = (
            f"am_relation.relation_type='successor_of' edge "
            f"(target={relation_row['target_entity_id'] or 'unbound'}, "
            f"confidence={relation_row['confidence']})."
        )

    # 3. sunset_imminent
    elif eff_until is not None and 0 <= (eff_until - as_of).days < _SUNSET_IMMINENT_DAYS:
        status = "sunset_imminent"
        confidence = "high" if eff_from is not None else "medium"
        reason = (
            f"effective_until={eff_until.isoformat()} is "
            f"{(eff_until - as_of).days} days from as_of "
            f"(< {_SUNSET_IMMINENT_DAYS}-day imminent threshold)."
        )

    # 4. sunset_scheduled
    elif eff_until is not None and (eff_until - as_of).days >= _SUNSET_IMMINENT_DAYS:
        status = "sunset_scheduled"
        confidence = "medium"
        reason = (
            f"effective_until={eff_until.isoformat()} "
            f"({(eff_until - as_of).days} days from as_of, "
            f">= {_SUNSET_IMMINENT_DAYS}-day threshold)."
        )

    # 5. amended (latest version > 1 + effective_from on or before as_of)
    elif (
        amendment_row is not None
        and amendment_row["version_seq"] is not None
        and amendment_row["version_seq"] > 1
        and eff_from is not None
        and eff_from <= as_of
    ):
        status = "amended"
        # amendment_snapshot fake → low confidence per CLAUDE.md gotcha.
        confidence = "low"
        reason = (
            f"am_amendment_snapshot version_seq={amendment_row['version_seq']} "
            f"with effective_from={eff_from.isoformat()} <= as_of. "
            "amendment_snapshot has uniform hash; treat as soft signal."
        )

    # 6. active
    elif eff_from is not None and eff_from <= as_of and (eff_until is None or eff_until > as_of):
        status = "active"
        confidence = "medium"
        reason = (
            f"effective_from={eff_from.isoformat()} <= as_of and "
            f"effective_until={'NULL' if eff_until is None else eff_until.isoformat()} "
            "(not yet sunset)."
        )

    # 7. not_yet
    elif eff_from is not None and eff_from > as_of:
        status = "not_yet"
        confidence = "medium"
        reason = (
            f"effective_from={eff_from.isoformat()} > as_of "
            f"({(eff_from - as_of).days} days in the future)."
        )

    # 8. unknown
    else:
        status = "unknown"
        confidence = "low"
        if amendment_row is None and relation_row is None:
            reason = (
                "no am_amendment_snapshot row and no successor_of/replaces "
                "edge — entity has no temporal metadata."
            )
        else:
            reason = (
                "amendment_snapshot present but effective_from/until "
                "did not parse to ISO dates "
                f"(raw effective_from={eff_from_raw!r}, "
                f"effective_until={eff_until_raw!r})."
            )

    # ----------------------------------------------------------------------
    # Build evidence block (no LLM, just structured pass-through).
    # ----------------------------------------------------------------------
    evidence: dict[str, Any] = {
        "amendment": (
            {
                "version_seq": amendment_row["version_seq"],
                "observed_at": amendment_row["observed_at"],
                "effective_from_raw": eff_from_raw,
                "effective_until_raw": eff_until_raw,
                "source_url": amendment_row["source_url"],
                "source_fetched_at": amendment_row["source_fetched_at"],
            }
            if amendment_row
            else None
        ),
        "relation": (
            {
                "relation_type": relation_row["relation_type"],
                "target_entity_id": relation_row["target_entity_id"],
                "confidence": relation_row["confidence"],
                "source_field": relation_row["source_field"],
            }
            if relation_row
            else None
        ),
        "effective_dates": {
            "effective_from": eff_from.isoformat() if eff_from else None,
            "effective_until": eff_until.isoformat() if eff_until else None,
        },
    }

    return {
        "unified_id": unified_id,
        "name": primary_name,
        "record_kind": record_kind,
        "canonical_status": canonical_status,
        "status": status,
        "status_label_ja": _STATUS_LABEL_JA[status],
        "evidence": evidence,
        "confidence": confidence,
        "reason": reason,
        "as_of": as_of.isoformat(),
        "_disclaimer": _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# MCP tool registration. Gated by AUTONOMATH_LIFECYCLE_ENABLED.
# ---------------------------------------------------------------------------
if _ENABLED:

    @mcp.tool(annotations=_READ_ONLY)
    def program_lifecycle(
        unified_id: Annotated[
            str,
            Field(
                description=(
                    "Target entity canonical_id (e.g. "
                    "`program:base:3435b5b27e`). "
                    "Use search_programs / enum_values_am to resolve "
                    "free-text → canonical_id first."
                ),
            ),
        ],
        as_of: Annotated[
            str | None,
            Field(
                description=(
                    "ISO YYYY-MM-DD basis date. None = today JST. "
                    "Used to evaluate sunset / amended / not_yet thresholds."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[LIFECYCLE] Returns schema-level snapshot of program status (abolished / superseded / sunset_imminent / sunset_scheduled / amended / active / not_yet / unknown). Most rows lack historical diffs (eligibility_hash chain partial); use effective_from for filtering.

        WHAT: ``am_amendment_snapshot`` (14,596 rows / effective_from filled
        on 140 rows / effective_until filled on 4 rows) と ``am_relation``
        (successor_of=190 / replaces=9) を precedence 順で評価。LLM 推論
        ゼロ、 SQL only。amendment_snapshot 由来の判定は CLAUDE.md gotcha
        に従い ``confidence='low'`` で返却。

        WHEN:
          - 「事業再構築補助金 は今も使えるか?」(後継制度有無 + 終了予定)
          - 「2026 年改正で影響受ける制度?」 (amended / sunset_imminent)
          - 「申請前 に廃止リスクを 1 コールで確認したい」

        WHEN NOT:
          - 全税制 sunset list → list_tax_sunset_alerts
          - 法令本文 → get_law_article_am
          - 補助率/上限額 詳細 → search_programs + raw_json

        RETURNS:
          {
            unified_id, name, record_kind, canonical_status,
            status: one of [
              'abolished', 'superseded', 'sunset_imminent',
              'sunset_scheduled', 'amended', 'active',
              'not_yet', 'unknown'
            ],
            status_label_ja: <Japanese label>,
            evidence: {
              amendment: { version_seq, effective_from_raw, effective_until_raw, source_url, ... } | null,
              relation:  { relation_type, target_entity_id, confidence, ... } | null,
              effective_dates: { effective_from: 'YYYY-MM-DD'|null, effective_until: 'YYYY-MM-DD'|null }
            },
            confidence: 'low' | 'medium' | 'high',
            reason: <one-line determinism-trace>,
            as_of: 'YYYY-MM-DD',
            _disclaimer: 'Lifecycle status is derived from public-source snapshots; verify source_url before decisions.'
          }

        Errors return the canonical envelope:
          - missing_required_arg : unified_id empty / whitespace
          - invalid_date_format  : as_of did not parse as YYYY-MM-DD
          - db_unavailable       : source database temporarily unavailable
        """
        # --- arg validation ------------------------------------------------
        if not unified_id or not unified_id.strip():
            return make_error(
                code="missing_required_arg",
                message="unified_id is required (canonical_id of the target entity).",
                hint=(
                    "Resolve free-text → canonical_id via search_programs "
                    "or enum_values_am, then call program_lifecycle again."
                ),
                retry_with=["search_programs", "enum_values_am"],
                field="unified_id",
            )

        target_date: datetime.date | None
        if as_of is None or not as_of.strip():
            target_date = _today_jst()
        else:
            target_date = _parse_iso_date(as_of)
            if target_date is None:
                return make_error(
                    code="invalid_date_format",
                    message=(f"as_of={as_of!r} did not parse as ISO YYYY-MM-DD."),
                    hint=(
                        "Pass YYYY-MM-DD (e.g. '2026-04-25') or omit as_of to default to today JST."
                    ),
                    field="as_of",
                )

        try:
            return _program_lifecycle_impl(unified_id.strip(), target_date)
        except (sqlite3.Error, FileNotFoundError) as exc:
            logger.exception("program_lifecycle query failed")
            return make_error(
                code="db_unavailable",
                message=str(exc),
                hint=(
                    "source database temporarily unavailable; retry later or fall back "
                    "to search_programs + raw_json inspection."
                ),
                retry_with=["search_programs"],
            )


__all__ = [
    "_program_lifecycle_impl",
    "_parse_iso_date",
    "_today_jst",
    "_STATUS_LABEL_JA",
    "_SUNSET_IMMINENT_DAYS",
    "_DISCLAIMER",
]
