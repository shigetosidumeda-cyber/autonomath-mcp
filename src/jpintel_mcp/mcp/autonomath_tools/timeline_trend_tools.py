"""timeline_trend_tools — R8 (2026-05-07) timeline + trend MCP wrappers.

Three MCP tools that mirror the REST surface in
``jpintel_mcp.api.timeline_trend``:

  * ``program_timeline_am`` — per-program annual adoption rollup +
    next_round (closest open / upcoming am_application_round).
  * ``cases_timeline_trend_am`` — JSIC × prefecture × N-year adoption
    trend with least-squares-derived trend_flag.
  * ``upcoming_rounds_for_my_profile_am`` — fan-out match against the
    calling key's client_profiles. Authenticated MCP keys only.

These wrappers reuse the pure-Python builders from the REST module so
both surfaces share the same data contract and the same disclaimer
fence. The REST module owns billing + sealing — the MCP tool here is
read-only and emits a ``_billing_unit: 1`` envelope so customer LLMs
keep accurate cost accounting.

NO LLM. ¥3 / call (one-shot). §52 / §47条の2 / §1 fence on the trend
surfaces; §1 only on upcoming-rounds (pure schedule data).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.api.timeline_trend import (
    _build_cases_trend,
    _build_program_timeline,
    _build_upcoming_rounds_for_profile,
)
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.timeline_trend")

_ENABLED = get_flag("JPCITE_TIMELINE_TREND_ENABLED", "AUTONOMATH_TIMELINE_TREND_ENABLED", "1") == "1"


def _open_jpintel_ro() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only — soft-fail to error envelope."""
    db_path = get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH", "data/jpintel.db")
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_acceptance_stats_am", "case_cohort_match_am"],
        )


def program_timeline_impl(program_id: str, years: int = 5) -> dict[str, Any]:
    """Per-program timeline (adoption rollup + next_round)."""
    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="missing_required_arg",
            message="program_id must be non-empty.",
            field="program_id",
        )
    if years < 1 or years > 20:
        return make_error(
            code="out_of_range",
            message=f"years must be in [1, 20], got {years}.",
            field="years",
        )
    conn_or_err = _open_jpintel_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        body = _build_program_timeline(conn, program_id=pid, years=years)
    finally:
        conn.close()
    body = attach_corpus_snapshot(body)
    return body


def cases_timeline_trend_impl(
    industry: str | None = None,
    prefecture: str | None = None,
    years: int = 5,
) -> dict[str, Any]:
    """業種 × 地域 × 時間 trend rollup."""
    if years < 1 or years > 20:
        return make_error(
            code="out_of_range",
            message=f"years must be in [1, 20], got {years}.",
            field="years",
        )
    body = _build_cases_trend(
        industry=industry,
        prefecture=prefecture,
        years=years,
    )
    body = attach_corpus_snapshot(body)
    return body


def upcoming_rounds_for_my_profile_impl(
    api_key_hash: str | None = None,
    horizon_days: int = 60,
) -> dict[str, Any]:
    """Fan-out upcoming rounds matching client_profiles for the calling key.

    The MCP transport injects the calling key's hash via the
    ``api_key_hash`` argument (supplied by the FastMCP dispatcher when
    the tool is invoked over an authenticated session). Anonymous calls
    return an envelope with ``profile_count: 0`` and an empty match
    list — there are no profiles to match against.
    """
    if horizon_days < 1 or horizon_days > 180:
        return make_error(
            code="out_of_range",
            message=f"horizon_days must be in [1, 180], got {horizon_days}.",
            field="horizon_days",
        )
    if not api_key_hash:
        return {
            "as_of": None,
            "horizon_days": horizon_days,
            "profile_count": 0,
            "matches": [],
            "summary_stats": {
                "total_matches": 0,
                "total_unique_rounds": 0,
                "profiles_with_match": 0,
            },
            "data_quality": {
                "missing_tables": ["client_profiles_for_key"],
                "no_profiles": True,
                "anonymous": True,
            },
            "_disclaimer": (
                "anonymous MCP session — no client_profiles available; "
                "subscribe via REST POST /v1/me/client_profiles/bulk_import."
            ),
            "_billing_unit": 1,
        }
    conn_or_err = _open_jpintel_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        body = _build_upcoming_rounds_for_profile(
            conn,
            key_hash=api_key_hash,
            horizon_days=horizon_days,
        )
    finally:
        conn.close()
    body = attach_corpus_snapshot(body)
    return body


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def program_timeline_am(
        program_id: Annotated[
            str,
            Field(
                description=(
                    "Program canonical id (jpintel `UNI-...` or autonomath "
                    "`program:...`). entity_id_map bridges both forms."
                ),
                min_length=1,
                max_length=200,
            ),
        ],
        years: Annotated[
            int,
            Field(
                ge=1,
                le=20,
                description=(
                    "Number of past years (inclusive of current year) to roll "
                    "up. Default 5. Bounded [1, 20]."
                ),
            ),
        ] = 5,
    ) -> dict[str, Any]:
        """[TIMELINE] Per-program annual adoption rollup + next_round (closest open / upcoming am_application_round) + competition_proxy (adoption_per_round). Reads jpi_adoption_records (201,845) + am_application_round (1,256). Single ¥3/req. NO LLM. §52 / §47条の2 / §1 sensitive — information retrieval, not 申請代理 / 税務助言."""
        return program_timeline_impl(program_id=program_id, years=years)

    @mcp.tool(annotations=_READ_ONLY)
    def cases_timeline_trend_am(
        industry: Annotated[
            str | None,
            Field(
                description=(
                    "JSIC industry code prefix (e.g. 'E' for 製造業, 'E29' "
                    "for 食料品製造業). Prefix-matches industry_jsic_medium. "
                    "None = all industries."
                ),
                max_length=8,
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(
                description=("都道府県 exact match (e.g. '東京都', '大阪府'). None = nationwide."),
                max_length=20,
            ),
        ] = None,
        years: Annotated[
            int,
            Field(
                ge=1,
                le=20,
                description=(
                    "Number of past years (inclusive of current year). Default 5. Bounded [1, 20]."
                ),
            ),
        ] = 5,
    ) -> dict[str, Any]:
        """[TIMELINE-TREND] 業種 (JSIC prefix) × 地域 (prefecture) × 時間 (year) trend over jpi_adoption_records: yearly adoption_count / distinct_houjin / distinct_program_count / total_amount_yen + trend_flag (least-squares slope). Single ¥3/req. NO LLM. §52 / §47条の2 / §1 sensitive."""
        return cases_timeline_trend_impl(
            industry=industry,
            prefecture=prefecture,
            years=years,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def upcoming_rounds_for_my_profile_am(
        api_key_hash: Annotated[
            str | None,
            Field(
                description=(
                    "Caller's api_keys.key_hash. The MCP dispatcher "
                    "injects this for authenticated sessions; anonymous "
                    "callers omit it and receive an empty-match envelope."
                ),
                max_length=128,
            ),
        ] = None,
        horizon_days: Annotated[
            int,
            Field(
                ge=1,
                le=180,
                description=("Lookahead window in days (JST). Default 60. Bounded [1, 180]."),
            ),
        ] = 60,
    ) -> dict[str, Any]:
        """[UPCOMING-ROUNDS] Match every am_application_round closing in the next horizon_days against the calling key's client_profiles via JSIC × prefecture × target_types × last_active_program overlap. Authenticated only — anon receives empty match list. Single ¥3/req. NO LLM. 行政書士法 §1 sensitive — pure schedule data, not 申請代理."""
        return upcoming_rounds_for_my_profile_impl(
            api_key_hash=api_key_hash,
            horizon_days=horizon_days,
        )
