#!/usr/bin/env python3
"""Generate ``outcome_chain_routing_v1`` packets (Wave 99 #1 of 10).

am_composed_tool_catalog の committed chain を起点に、対象 outcome ごとに
top-N greedy chain (≤ 7 step) を replay し、cheapest_sufficient_route hint と
ともに routing 控制 packet 化する。Wave 51 L3 ``cross_outcome_routing`` の
follow-on で、agent runtime が next-call を経済化するための事前 trace。

Cohort
------
::

    cohort = composed_tool_id (am_composed_tool_catalog.tool_id)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import contextlib
import json
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

PACKAGE_KIND: Final[str] = "outcome_chain_routing_v1"

#: Greedy chain truncation cap; matches the agent runtime composition
#: budget envelope (7-step ceiling per Wave 51 dim P).
_MAX_CHAIN_STEPS: Final[int] = 7

DEFAULT_DISCLAIMER: Final[str] = (
    "本 outcome chain routing packet は am_composed_tool_catalog の "
    "committed atomic_chain (savings_factor proxy 込み) を replay した "
    "control-plane hint で、税理士法 §52 / 弁護士法 §72 / 行政書士法 §1の2 "
    "の専門家判断を代替しない。実 outcome の cheapest_sufficient_route は "
    "agent runtime + 顧問専門家の一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_composed_tool_catalog"):
        return
    rows: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT tool_id, version, atomic_tool_chain, domain, description, status "
            "  FROM am_composed_tool_catalog "
            " WHERE status = 'committed' "
            " ORDER BY tool_id, version DESC"
        ):
            rows.append(dict(r))

    seen_tool_ids: set[str] = set()
    emitted = 0
    for r in rows:
        tool_id = str(r.get("tool_id") or "")
        if not tool_id or tool_id in seen_tool_ids:
            continue
        seen_tool_ids.add(tool_id)
        try:
            chain_obj = json.loads(r.get("atomic_tool_chain") or "{}")
        except (TypeError, ValueError):
            continue
        chain = chain_obj.get("atomic_chain") or []
        if not isinstance(chain, list):
            continue
        # Greedy keep ≤ _MAX_CHAIN_STEPS.
        chain = chain[:_MAX_CHAIN_STEPS]
        savings_factor = int(chain_obj.get("savings_factor") or 0)
        record = {
            "tool_id": tool_id,
            "version": int(r.get("version") or 1),
            "domain": str(r.get("domain") or ""),
            "description": str(r.get("description") or ""),
            "chain": chain,
            "savings_factor": savings_factor,
        }
        yield record
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    tool_id = str(row.get("tool_id") or "UNKNOWN")
    version = int(row.get("version") or 1)
    chain = list(row.get("chain") or [])
    savings_factor = int(row.get("savings_factor") or 0)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(tool_id)}:v{version}"
    rows_in_packet = len(chain)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "cheapest_sufficient_route の最終判断は agent runtime + 顧問 "
                "専門家 (税理士 §52 / 弁護士 §72 / 行政書士 §1の2) が要"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 composed tool で atomic_chain 観測無し",
            }
        )
    if rows_in_packet >= _MAX_CHAIN_STEPS:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"chain step >{_MAX_CHAIN_STEPS} で打切、全 step は "
                    "am_composed_tool_catalog 直接参照が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://docs.jpcite.com/agent-runtime/composed-tools/",
            "source_fetched_at": None,
            "publisher": "jpcite agent runtime docs",
            "license": "gov_standard",
        },
        {
            "source_url": "https://docs.jpcite.com/wave51/cross-outcome-routing/",
            "source_fetched_at": None,
            "publisher": "jpcite Wave 51 L3 cross_outcome_routing",
            "license": "gov_standard",
        },
    ]

    body: dict[str, Any] = {
        "subject": {"kind": "composed_tool", "id": tool_id},
        "tool_id": tool_id,
        "version": version,
        "domain": str(row.get("domain") or ""),
        "description": str(row.get("description") or ""),
        "chain": chain,
        "chain_step_n": rows_in_packet,
        "savings_factor": savings_factor,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": tool_id, "tool_id": tool_id, "version": version},
        metrics={"chain_step_n": rows_in_packet, "savings_factor": savings_factor},
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
