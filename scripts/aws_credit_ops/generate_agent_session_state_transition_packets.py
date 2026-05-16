#!/usr/bin/env python3
"""Generate ``agent_session_state_transition_v1`` packets (Wave 100 #7 of 10).

Per composed tool cohort, emit a canonical multi-turn state-transition
graph (init -> fetch -> validate -> enrich -> respond) as a synthetic
state machine. Wave 51 dim L file-backed session_context は 24h TTL +
3 endpoint の design SOT (memory `feedback_session_context_design.md`);
this packet renders the structural transition layer for downstream
agent runtime trace. NO LLM call.

Cohort
------
::

    cohort = composed_tool_id (am_composed_tool_catalog.tool_id)
"""

from __future__ import annotations

import contextlib
import sys
from typing import TYPE_CHECKING, Any, Final

from scripts.aws_credit_ops._packet_base import (
    jpcir_envelope,
    safe_packet_id_segment,
    table_exists,
)
from scripts.aws_credit_ops._packet_runner import run_generator

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "agent_session_state_transition_v1"

_MAX_TRANSITIONS_PER_PACKET: Final[int] = 24

DEFAULT_DISCLAIMER: Final[str] = (
    "本 agent session state transition packet は Wave 51 dim L "
    "session_context (24h TTL + 3 endpoint) の structural transition layer で、"
    "実 session 行動 trace は jpi_audit_log + Stripe metered の接続後に "
    "上書き予定。本 packet 単体で 個人情報保護法 §27 の取扱判断を代替しない。"
)


# Canonical state machine per Wave 51 dim L design.
_CANONICAL_STATES: Final[tuple[str, ...]] = (
    "init",
    "fetch_evidence",
    "validate_eligibility",
    "enrich_context",
    "compose_response",
    "respond",
    "callback",
    "settle_billing",
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_composed_tool_catalog"):
        return

    tool_ids: list[tuple[str, int, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT tool_id, version, domain FROM am_composed_tool_catalog "
            " WHERE status = 'committed' GROUP BY tool_id ORDER BY tool_id"
        ):
            tool_ids.append(
                (
                    str(r["tool_id"] or ""),
                    int(r["version"] or 1),
                    str(r["domain"] or ""),
                )
            )

    for emitted, (tool_id, version, domain) in enumerate(tool_ids):
        if not tool_id:
            continue
        transitions: list[dict[str, Any]] = []
        for i in range(len(_CANONICAL_STATES) - 1):
            transitions.append(
                {
                    "from": _CANONICAL_STATES[i],
                    "to": _CANONICAL_STATES[i + 1],
                    "transition_probability_proxy": round(0.95 - i * 0.05, 3),
                    "median_dwell_ms_proxy": (i + 1) * 150,
                }
            )
        # Add edge back-loops (callback -> fetch_evidence).
        transitions.append(
            {
                "from": "callback",
                "to": "fetch_evidence",
                "transition_probability_proxy": 0.25,
                "median_dwell_ms_proxy": 80,
            }
        )
        avg_dwell = round(
            sum(t["median_dwell_ms_proxy"] for t in transitions) / len(transitions),
            1,
        )
        yield {
            "tool_id": tool_id,
            "version": version,
            "domain": domain,
            "transitions": transitions,
            "state_n": len(_CANONICAL_STATES),
            "avg_dwell_ms": avg_dwell,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    tool_id = str(row.get("tool_id") or "UNKNOWN")
    version = int(row.get("version") or 1)
    transitions = list(row.get("transitions") or [])
    rows_in_packet = len(transitions)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(tool_id)}:v{version}"

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "transition_probability / dwell_ms は design heuristic、実 trace は "
                "Wave 49 G1 aggregator + jpi_audit_log 接続後に上書き"
            ),
        },
        {
            "code": "source_receipt_incomplete",
            "description": "callback back-loop は 1 edge のみ exemplify",
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/wave51/session-context/",
            "source_fetched_at": None,
            "publisher": "jpcite Wave 51 dim L design",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "composed_tool", "id": tool_id},
        "tool_id": tool_id,
        "version": version,
        "domain": str(row.get("domain") or ""),
        "states": list(_CANONICAL_STATES),
        "transitions": transitions[:_MAX_TRANSITIONS_PER_PACKET],
        "state_n": int(row.get("state_n") or len(_CANONICAL_STATES)),
        "avg_dwell_ms": float(row.get("avg_dwell_ms") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": tool_id,
            "tool_id": tool_id,
            "version": version,
        },
        metrics={
            "transition_n": rows_in_packet,
            "state_n": int(row.get("state_n") or len(_CANONICAL_STATES)),
            "avg_dwell_ms": float(row.get("avg_dwell_ms") or 0.0),
        },
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, rows_in_packet


def main(argv: Sequence[str] | None = None) -> int:
    return run_generator(
        argv=argv,
        package_kind=PACKAGE_KIND,
        default_db="autonomath.db",
        aggregate=_aggregate,
        render=_render,
        needs_jpintel=False,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
