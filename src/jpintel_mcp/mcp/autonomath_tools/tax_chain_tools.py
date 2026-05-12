"""tax_chain_tools — MCP wrapper for the tax_rules full_chain API.

Single tool registered at import time when both
``AUTONOMATH_TAX_CHAIN_ENABLED`` (default ON) and
``settings.autonomath_enabled`` are truthy:

  * ``tax_rule_full_chain``
      Bundles 税制 + 根拠条文 + 関連通達 + 裁決事例 + 判例 + 改正履歴
      for one ``tax_rulesets`` row in a single call. Wraps the same
      in-process logic as ``GET /v1/tax_rules/{rule_id}/full_chain``.

Hard constraints (memory ``feedback_no_operator_llm_api`` +
``feedback_autonomath_no_api_use``):

  * NO LLM call. Pure SQLite SELECT + Python dict shaping.
  * Cross-DB reads: jpintel.db (tax_rulesets / laws / court_decisions) +
    autonomath.db (nta_tsutatsu_index / nta_saiketsu). CLAUDE.md forbids
    cross-DB JOIN — we open both connections, pull separately, and merge
    in Python.
  * 税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47条の2 disclaimer
    envelope on every response.
  * Single ¥3 / req billing event regardless of how many citations
    surface.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.tax_chain")

# Env gate. Default ON; flip to "0" to roll back without a redeploy.
_ENABLED = get_flag("JPCITE_TAX_CHAIN_ENABLED", "AUTONOMATH_TAX_CHAIN_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _open_jpintel_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db. Returns conn or error envelope on failure."""
    try:
        from jpintel_mcp.db.session import connect

        return connect()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_tax_incentives"],
        )


def _tax_rule_full_chain_impl(
    rule_id: str,
    include: list[str] | None = None,
    max_per_axis: int = 10,
) -> dict[str, Any]:
    """Compose the chain bundle in-process.

    Delegates the SQL + shaping logic to ``api.tax_chain`` so the REST
    endpoint and the MCP tool stay in lock-step. The endpoint helpers are
    pure Python over a sqlite3.Connection — no FastAPI dependency leaks
    into the MCP path.
    """
    from jpintel_mcp.api import tax_chain as _tx

    # 422-equivalent input validation. We surface the same shape the REST
    # handler returns (HTTPException -> error envelope here).
    if not isinstance(rule_id, str) or not _tx._UNIFIED_ID_RE.match(rule_id):
        return make_error(
            code="invalid_input",
            message=f"rule_id must match TAX-<10 lowercase hex>, got {rule_id!r}",
            field="rule_id",
        )

    try:
        max_n = int(max_per_axis)
    except (TypeError, ValueError):
        return make_error(
            code="invalid_input",
            message="max_per_axis must be an integer",
            field="max_per_axis",
        )
    if max_n < 1 or max_n > _tx._HARD_MAX_PER_AXIS:
        return make_error(
            code="out_of_range",
            message=(f"max_per_axis must be in [1, {_tx._HARD_MAX_PER_AXIS}]; got {max_n}"),
            field="max_per_axis",
        )

    try:
        requested = _tx._parse_include(include)
    except Exception as exc:  # noqa: BLE001 — surface as envelope, not raise
        return make_error(
            code="invalid_enum",
            message=str(exc),
            field="include",
        )

    conn_or_err = _open_jpintel_safe()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err

    try:
        rule_row = _tx._fetch_rule_row(conn, rule_id)
        if rule_row is None:
            return make_error(
                code="not_found",
                message=f"tax_ruleset not found: {rule_id}",
                field="rule_id",
            )
        rule = _tx._shape_rule_row(rule_row)
        rule_name = str(rule["ruleset_name"] or "")
        tax_category = rule["tax_category"]
        law_ids = _tx._parse_law_ids(rule_row["related_law_ids_json"])

        bundle: dict[str, list[dict[str, Any]]] = {axis: [] for axis in _tx._ALL_AXES}
        presence: dict[str, bool] = dict.fromkeys(_tx._ALL_AXES, True)

        if "laws" in requested:
            rows, present = _tx._fetch_laws(conn, law_ids=law_ids, max_n=max_n)
            bundle["laws"] = rows
            presence["laws"] = present
        if "hanrei" in requested:
            rows, present = _tx._fetch_hanrei(
                conn, law_ids=law_ids, rule_name=rule_name, max_n=max_n
            )
            bundle["hanrei"] = rows
            presence["hanrei"] = present
        if "history" in requested:
            rows, present = _tx._fetch_history(conn, rule_row=rule_row, max_n=max_n)
            bundle["history"] = rows
            presence["history"] = present

        needs_am = bool({"tsutatsu", "saiketsu"} & requested)
        am_conn = _tx._open_autonomath_ro() if needs_am else None
        if "tsutatsu" in requested:
            rows, present = _tx._fetch_tsutatsu(am_conn, rule_name=rule_name, max_n=max_n)
            bundle["tsutatsu"] = rows
            presence["tsutatsu"] = present
        if "saiketsu" in requested:
            rows, present = _tx._fetch_saiketsu(
                am_conn,
                rule_name=rule_name,
                tax_category=tax_category,
                max_n=max_n,
            )
            bundle["saiketsu"] = rows
            presence["saiketsu"] = present
        # autonomath thread-local conn is shared — do NOT close.

        coverage = _tx._build_coverage(bundle, table_presence=presence)

        body: dict[str, Any] = {
            "rule": rule,
            "laws": bundle["laws"],
            "tsutatsu": bundle["tsutatsu"],
            "saiketsu": bundle["saiketsu"],
            "hanrei": bundle["hanrei"],
            "history": bundle["history"],
            "coverage_summary": coverage,
            "_billing_unit": 1,
            "_disclaimer": _tx._TAX_CHAIN_DISCLAIMER,
        }
        attach_corpus_snapshot(body)
        return body
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def tax_rule_full_chain(
        rule_id: Annotated[
            str,
            Field(
                description=(
                    "Tax ruleset id (`TAX-<10 lowercase hex>`). Returned by "
                    "`search_tax_incentives` / REST `/v1/tax_rulesets/search`."
                ),
                min_length=14,
                max_length=14,
            ),
        ],
        include: Annotated[
            list[str] | None,
            Field(
                default=None,
                description=(
                    "Subset of axes to return. Allowed: "
                    "`laws` / `tsutatsu` / `saiketsu` / `hanrei` / `history`. "
                    "Default = all 5."
                ),
            ),
        ] = None,
        max_per_axis: Annotated[
            int,
            Field(
                default=10,
                ge=1,
                le=50,
                description="Cap per axis. Hard ceiling 50.",
            ),
        ] = 10,
    ) -> dict[str, Any]:
        """[TAX-CHAIN] 税制 (TAX-*) を巡る解釈一式を 1 call で取得: 規定本文 + 根拠条文 (laws) + 通達 (nta_tsutatsu_index) + 裁決事例 (nta_saiketsu) + 判例 (court_decisions) + 改正履歴 (sibling tax_rulesets). 出力は citation のみで税務助言 (税理士法 §52) ・法令解釈 (弁護士法 §72) ・監査意見 (公認会計士法 §47条の2) ではない。各 row source_url で原典確認必須。"""
        return _tax_rule_full_chain_impl(
            rule_id=rule_id,
            include=include,
            max_per_axis=max_per_axis,
        )


__all__ = [
    "_tax_rule_full_chain_impl",
]
