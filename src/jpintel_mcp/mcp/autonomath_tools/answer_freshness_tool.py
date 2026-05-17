"""check_answer_freshness — P4 freshness verification MCP tool (2026-05-17).

Exposes one read-only MCP tool that lets the calling agent verify whether
a precomputed answer (composed by P2 + cached by P3) is still fresh
relative to the latest `am_amendment_diff` sweep landed by the P4 hourly
cron (`scripts/cron/answer_freshness_check_2026_05_17.py`).

Why this tool exists
--------------------
The P3 cache trades 0-推論 latency for the risk that an upstream law /
税制 / 制度 amendment has invalidated the cached answer between sweeps.
A diligent agent (税理士 / 会計士 / 司法書士 / 行政書士 cohort) must
verify the cached answer was last validated AFTER the most recent
amendment that touches the same upstream IDs — or fall through to the
on-demand composer.

Sensitivity
-----------
Pure metadata lookup over `am_precomputed_answer`. No first-party
program / law content is returned — only freshness bookkeeping. NOT
§52 / §47条の2 sensitive (no advice, no eligibility, no 申請書面).
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp._error_helpers import safe_internal_message
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpcite.mcp.am.freshness")


_GUIDANCE: dict[str, str] = {
    "fresh": "Cached answer is verified against the latest amendment sweep — safe to rely on.",
    "stale": "Upstream amendment landed; P4 cron will recompose on next hourly tick.",
    "expired": "Upstream entity vanished or composer refused — call the on-demand composer.",
    "unknown": "No row found for question_id, or freshness column not populated yet.",
}


def _parse_diff_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for item in parsed:
        with contextlib.suppress(TypeError, ValueError):
            out.append(int(item))
    return out


@mcp.tool(annotations=_READ_ONLY)
def check_answer_freshness(
    question_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            description=(
                "`am_precomputed_answer.question_id` — the P2 composer-issued "
                "stable id for the cached answer envelope."
            ),
        ),
    ],
) -> dict[str, Any]:
    """[P4 FRESHNESS] Verify whether a precomputed answer is still fresh against the latest law / 税制 / 制度 amendment sweep. Pure metadata lookup. NO LLM. Returns freshness_state ('fresh' / 'stale' / 'expired' / 'unknown') + last_validated_at + invalidation_reason + amendment_diff_ids lineage."""
    try:
        conn = connect_autonomath()
    except Exception as exc:
        message, _incident_id = safe_internal_message(exc, logger=logger)
        return make_error("db_unavailable", message)

    try:
        row = conn.execute(
            """SELECT question_id, intent_class, freshness_state, last_validated_at,
                      invalidation_reason, amendment_diff_ids, version_seq
                 FROM am_precomputed_answer
                WHERE question_id = ?
                LIMIT 1""",
            (question_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # Table or columns missing — likely pre-migration-291 boot.
        conn.close()
        return {
            "question_id": question_id,
            "freshness_state": "unknown",
            "last_validated_at": None,
            "version_seq": None,
            "invalidation_reason": None,
            "amendment_diff_ids": [],
            "intent_class": None,
            "guidance": (
                "am_precomputed_answer freshness columns absent — apply "
                "migration 291_am_precomputed_answer_freshness.sql."
            ),
            "_warning": str(exc),
        }
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    if row is None:
        return {
            "question_id": question_id,
            "freshness_state": "unknown",
            "last_validated_at": None,
            "version_seq": None,
            "invalidation_reason": None,
            "amendment_diff_ids": [],
            "intent_class": None,
            "guidance": _GUIDANCE["unknown"],
        }

    state = (row["freshness_state"] or "unknown").lower()
    if state not in _GUIDANCE:
        state = "unknown"

    return {
        "question_id": row["question_id"],
        "freshness_state": state,
        "last_validated_at": row["last_validated_at"],
        "version_seq": (int(row["version_seq"]) if row["version_seq"] is not None else None),
        "invalidation_reason": row["invalidation_reason"],
        "amendment_diff_ids": _parse_diff_ids(row["amendment_diff_ids"]),
        "intent_class": row["intent_class"],
        "guidance": _GUIDANCE[state],
    }


__all__ = ["check_answer_freshness"]
