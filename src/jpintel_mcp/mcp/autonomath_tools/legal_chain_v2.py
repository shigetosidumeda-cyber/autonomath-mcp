"""legal_chain_v2 — MCP wrapper for the legal/chain Dim B 5-layer API.

Single tool registered at import time when both
``AUTONOMATH_LEGAL_CHAIN_V2_ENABLED`` (default ON) and
``settings.autonomath_enabled`` are truthy:

  * ``legal_chain_am``
      Returns the 5-layer causal chain (budget → law → cabinet →
      enforcement → case) anchored on one program in a single call.

Hard constraints:

  * NO LLM call. Pure SQLite SELECT + Python dict shaping.
  * Cross-DB reads: jpintel.db (programs anchor) + autonomath.db
    (am_legal_chain).
  * 弁護士法 §72 / 行政書士法 §1 / 税理士法 §52 disclaimer envelope.
  * 3 unit (¥9 / 9.90 incl tax) per call.
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
from .snapshot_helper import attach_corpus_snapshot

logger = logging.getLogger("jpintel.mcp.autonomath.legal_chain_v2")

_ENABLED = os.environ.get("AUTONOMATH_LEGAL_CHAIN_V2_ENABLED", "1") == "1"


def _open_jpintel_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db. Returns conn or error envelope on failure."""
    try:
        from jpintel_mcp.db.session import connect

        return connect()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["list_open_programs"],
        )


def _legal_chain_am_impl(
    program_id: str,
    include: list[str] | None = None,
    max_per_layer: int = 10,
) -> dict[str, Any]:
    """Compose the 5-layer chain bundle in-process."""
    from jpintel_mcp.api import legal_chain_v2 as _lc

    if not isinstance(program_id, str) or not _lc._PROGRAM_ID_RE.match(program_id):
        return make_error(
            code="invalid_input",
            message=f"program_id must match prefix-suffix shape; got {program_id!r}",
            field="program_id",
        )

    try:
        max_n = int(max_per_layer)
    except (TypeError, ValueError):
        return make_error(
            code="invalid_input",
            message="max_per_layer must be an integer",
            field="max_per_layer",
        )
    if max_n < 1 or max_n > _lc._HARD_MAX_PER_LAYER:
        return make_error(
            code="out_of_range",
            message=(f"max_per_layer must be in [1, {_lc._HARD_MAX_PER_LAYER}]; got {max_n}"),
            field="max_per_layer",
        )

    try:
        requested = _lc._parse_include(include)
    except Exception as exc:  # noqa: BLE001
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
        prog_row = _lc._fetch_program_row(conn, program_id)
        if prog_row is None:
            return make_error(
                code="not_found",
                message=f"program not found: {program_id}",
                field="program_id",
            )
        anchor = _lc._shape_program_anchor(prog_row)

        am_conn = _lc._open_autonomath_ro()
        bundle, am_present = _lc._fetch_pre_warmed_chain(
            am_conn,
            program_id=program_id,
            requested_layers=requested,
            max_n=max_n,
        )

        presence: dict[str, bool] = dict.fromkeys(_lc._ALL_LAYERS, am_present)
        pre_warmed = am_present and any(len(rows) > 0 for rows in bundle.values())

        coverage = _lc._build_coverage(
            bundle,
            table_presence=presence,
            pre_warmed=pre_warmed,
        )

        body: dict[str, Any] = {
            "anchor": anchor,
            "layers": {
                "budget": bundle["budget"],
                "law": bundle["law"],
                "cabinet": bundle["cabinet"],
                "enforcement": bundle["enforcement"],
                "case": bundle["case"],
            },
            "coverage_summary": coverage,
            "_billing_unit": 3,
            "_disclaimer": _lc._LEGAL_CHAIN_DISCLAIMER,
        }
        attach_corpus_snapshot(body)
        return body
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def legal_chain_am(
        program_id: Annotated[
            str,
            Field(
                description=(
                    "Program id (`UNI-...` / `NTA-...` / `MUNI-...` / etc.). "
                    "Returned by `list_open_programs` / `search_*` tools."
                ),
                min_length=4,
                max_length=96,
            ),
        ],
        include: Annotated[
            list[str] | None,
            Field(
                default=None,
                description=(
                    "Subset of layers. Allowed: "
                    "`budget` / `law` / `cabinet` / `enforcement` / `case`. "
                    "Default = all 5."
                ),
            ),
        ] = None,
        max_per_layer: Annotated[
            int,
            Field(
                default=10,
                ge=1,
                le=50,
                description="Cap per layer. Hard ceiling 50.",
            ),
        ] = 10,
    ) -> dict[str, Any]:
        """[LEGAL-CHAIN] 制度 (program_id) を巡る 5-layer 因果関係を 1 call で追跡: 予算成立 (budget) + 該当法令 article (law) + 関連 閣議決定 (cabinet) + 行政処分 history (enforcement) + 該当採択事例 (case). 各 layer に evidence_url 必須 (一次資料 only, aggregator 禁止). 出力は citation のみで法令解釈 (弁護士法 §72) ・官公署提出書類作成 (行政書士法 §1) ・税務代理 (税理士法 §52) ではない。3 unit billing (重 chain query). 各 layer の evidence_url で原典確認必須。"""
        return _legal_chain_am_impl(
            program_id=program_id,
            include=include,
            max_per_layer=max_per_layer,
        )


__all__ = [
    "_legal_chain_am_impl",
]
