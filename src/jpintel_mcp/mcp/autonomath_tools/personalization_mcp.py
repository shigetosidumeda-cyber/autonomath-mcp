"""personalization_mcp — MCP wrapper for Dim H personalization recommendations.

Wave 46 dim 19 SFGH booster (2026-05-12)
========================================

Single tool registered at import time when both
``AUTONOMATH_PERSONALIZATION_MCP_ENABLED`` (default ON) and
``settings.autonomath_enabled`` are truthy:

  * ``personalization_recommendations_am``
      MCP wrapper over the REST surface at
      ``GET /v1/me/recommendations`` (api/personalization_v2.py, Wave 43.2.8).
      Returns top-N program recommendations per
      (consultant api_key_hash × client_profiles.profile_id), backed by
      ``am_personalization_score`` (mig 264, autonomath.db) joined with
      jpintel ``programs`` and ``client_profiles``.

Hard constraints (CLAUDE.md):

  * NO LLM call. Pure SQLite SELECT + Python dict shaping. Scores are
    precomputed nightly by ``scripts/cron/refresh_personalization_daily.py``
    — this MCP tool only READS the materialized scores.
  * Cross-DB read: jpintel.db (programs anchor + client_profiles auth)
    + autonomath.db (am_personalization_score).
  * 1 ¥3/req billing unit per call.
  * 弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 / 公認会計士法 §47条の2
    non-substitution disclaimer envelope.
  * api_key_hash MUST come from the FastMCP request context — anonymous
    sessions return a "no client_profiles" error envelope instead of
    leaking another tenant's data.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.personalization_mcp")

_ENABLED = (
    os.environ.get("AUTONOMATH_PERSONALIZATION_MCP_ENABLED", "1") == "1"
)

_MAX_LIMIT = 25
_DEFAULT_LIMIT = 10

_DISCLAIMER = (
    "本 personalization_recommendations_am tool は (顧問先 × 制度) の "
    "適合度スコアを autonomath.am_personalization_score (migration 264, "
    "夜次バッチ更新) から READ-ONLY で集約します。スコアは"
    "ヒューリスティック で確定的な採択可否ではなく、最終確認は "
    "programs.source_url の一次資料で必ず行ってください。"
    "本 MCP tool は弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 / "
    "公認会計士法 §47条の2 等の資格独占役務には該当しません。"
)


def _open_jpintel_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db RO. Returns conn or error envelope on failure."""
    try:
        from jpintel_mcp.db.session import connect

        return connect()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["list_open_programs"],
        )


def _open_autonomath_ro_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only. Returns conn or error envelope."""
    try:
        am_path = settings.autonomath_db_path
        if not am_path or not os.path.exists(str(am_path)):
            return make_error(
                code="subsystem_unavailable",
                message="autonomath.db not present in this deployment",
                retry_with=["personalization_recommendations_rest"],
            )
        conn = sqlite3.connect(
            f"file:{am_path}?mode=ro", uri=True,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="subsystem_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )


def _personalization_recommendations_am_impl(
    client_id: int,
    api_key_hash: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Top-N personalised recommendations for one 顧問先 (client_profiles row).

    Mirrors REST GET /v1/me/recommendations.
    """
    if not api_key_hash:
        return make_error(
            code="missing_required_arg",
            message=(
                "personalization_recommendations_am requires an authenticated "
                "MCP session — api_key_hash missing from request context."
            ),
            field="api_key_hash",
            retry_with=["search_programs"],
        )
    if not 1 <= int(limit) <= _MAX_LIMIT:
        return make_error(
            code="invalid_input",
            message=f"limit must be in [1, {_MAX_LIMIT}]",
            field="limit",
        )

    jp = _open_jpintel_safe()
    if isinstance(jp, dict):
        return jp
    am = _open_autonomath_ro_safe()
    if isinstance(am, dict):
        with contextlib.suppress(Exception):
            jp.close()
        return am

    try:
        # Auth fetch — confirm the (api_key_hash, client_id) pairs to a
        # client_profiles row this caller actually owns.
        profile_row = jp.execute(
            "SELECT profile_id, name_label "
            "FROM client_profiles "
            "WHERE profile_id = ? AND api_key_hash = ?",
            (client_id, api_key_hash),
        ).fetchone()
        if profile_row is None:
            return make_error(
                code="not_found",
                message="client_id not found for this api_key",
                field="client_id",
            )

        score_rows = am.execute(
            "SELECT program_id, score, score_breakdown_json, "
            "       reasoning_json, refreshed_at "
            "FROM am_personalization_score "
            "WHERE api_key_hash = ? AND client_id = ? "
            "ORDER BY score DESC, program_id ASC "
            "LIMIT ?",
            (api_key_hash, client_id, int(limit)),
        ).fetchall()

        program_ids = [r["program_id"] for r in score_rows]
        program_meta: dict[str, sqlite3.Row] = {}
        if program_ids:
            placeholders = ",".join(["?"] * len(program_ids))
            rows = jp.execute(
                f"SELECT unified_id, primary_name, tier, prefecture, "
                f"       program_kind, source_url "
                f"FROM programs "
                f"WHERE unified_id IN ({placeholders}) "
                f"  AND excluded = 0 "
                f"  AND tier IN ('S','A','B','C')",
                program_ids,
            ).fetchall()
            program_meta = {r["unified_id"]: r for r in rows}

        items: list[dict[str, Any]] = []
        refreshed_at: str | None = None
        for r in score_rows:
            meta = program_meta.get(r["program_id"])
            if meta is None:
                # excluded / non-tiered programs are skipped silently
                continue
            items.append({
                "program_id": r["program_id"],
                "name": meta["primary_name"],
                "tier": meta["tier"],
                "prefecture": meta["prefecture"],
                "program_kind": meta["program_kind"],
                "source_url": meta["source_url"],
                "score": int(r["score"]),
                "refreshed_at": r["refreshed_at"],
            })
            if refreshed_at is None:
                refreshed_at = r["refreshed_at"]

        return {
            "client_id": client_id,
            "client_label": profile_row["name_label"],
            "items": items,
            "total": len(items),
            "refreshed_at": refreshed_at,
            "_billing_unit": 1,
            "_disclaimer": _DISCLAIMER,
        }
    finally:
        with contextlib.suppress(Exception):
            am.close()
        with contextlib.suppress(Exception):
            jp.close()


# ----- MCP tool registration ------------------------------------------------

if _ENABLED and getattr(settings, "autonomath_enabled", True):

    @mcp.tool(
        name="personalization_recommendations_am",
        annotations=_READ_ONLY,
    )
    def personalization_recommendations_am(
        client_id: Annotated[
            int, Field(description="client_profiles.profile_id"),
        ],
        api_key_hash: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Caller api_key_hash. Injected by the FastMCP request "
                    "context; anonymous sessions yield an error envelope."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT,
                  description="Top-N cap (1..25)"),
        ] = _DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Top-N personalised program recommendations for one 顧問先.

        NO LLM. Reads materialized nightly scores from
        ``am_personalization_score`` (migration 264) joined with jpintel
        ``programs`` for primary_name / tier / source_url. ¥3/req unit.
        """
        return _personalization_recommendations_am_impl(
            client_id=client_id,
            api_key_hash=api_key_hash,
            limit=limit,
        )

    logger.info(
        "personalization_recommendations_am tool registered "
        "(AUTONOMATH_PERSONALIZATION_MCP_ENABLED=%s)",
        os.environ.get("AUTONOMATH_PERSONALIZATION_MCP_ENABLED", "1"),
    )
else:
    logger.info(
        "personalization_recommendations_am tool NOT registered "
        "(enabled=%s autonomath_enabled=%s)",
        _ENABLED,
        getattr(settings, "autonomath_enabled", None),
    )
