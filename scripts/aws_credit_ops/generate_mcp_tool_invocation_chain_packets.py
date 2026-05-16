#!/usr/bin/env python3
"""Generate ``mcp_tool_invocation_chain_v1`` packets (Wave 100 #10 of 10).

Per domain cohort (taxonomy from am_composed_tool_catalog.domain),
emit the top tool-call chains observed across committed composed
tools. Each chain captures the canonical 1->N atomic ordering plus
the savings_factor from the catalog. Seeds the Wave 51 dim P
composable_tools layer (memory `feedback_composable_tools_pattern.md`)
+ Discoverability axis tooling hint set. NO LLM.

Cohort
------
::

    cohort = domain (e.g. tax / loan / certification / enforcement)
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

PACKAGE_KIND: Final[str] = "mcp_tool_invocation_chain_v1"

#: Per-domain top-N chain cap (Discoverability tooling hint).
_MAX_CHAINS_PER_DOMAIN: Final[int] = 30

#: Greedy chain truncation cap (Wave 51 dim P composition budget).
_MAX_CHAIN_STEPS: Final[int] = 7

DEFAULT_DISCLAIMER: Final[str] = (
    "本 mcp tool invocation chain packet は am_composed_tool_catalog の "
    "committed chain を domain 集約した Discoverability hint で、Wave 51 dim P "
    "composable_tools の atomic->composed mapping を agent runtime に渡すための "
    "事前 trace。実 tool call ranking は Wave 49 G1 aggregator + jpi_audit_log "
    "接続後に上書き予定。専門家判断 (§52 / §72 / §1の2) は agent runtime + 顧問 "
    "の一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_composed_tool_catalog"):
        return

    domains: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT domain FROM am_composed_tool_catalog "
            " WHERE status = 'committed' AND domain IS NOT NULL "
            " ORDER BY domain"
        ):
            d = str(r["domain"] or "").strip()
            if d:
                domains.append(d)

    # If domain is sparse, fall back to an 'all' cohort to ensure
    # min-50 packets across the run via cohort decomposition.
    if len(domains) < 5:
        domains = list(domains) + ["all"]

    for emitted, domain in enumerate(domains):
        chains: list[dict[str, Any]] = []
        domain_filter = "" if domain == "all" else " AND domain = ?"
        params: tuple[Any, ...] = (
            (_MAX_CHAINS_PER_DOMAIN,) if domain == "all" else (domain, _MAX_CHAINS_PER_DOMAIN)
        )
        sql = (
            "SELECT tool_id, version, atomic_tool_chain, description "
            "  FROM am_composed_tool_catalog "
            " WHERE status = 'committed' " + domain_filter + " ORDER BY tool_id LIMIT ?"
        )
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(sql, params):
                tool_id = str(r["tool_id"] or "")
                if not tool_id:
                    continue
                try:
                    chain_obj = json.loads(r["atomic_tool_chain"] or "{}")
                except (TypeError, ValueError):
                    continue
                chain = chain_obj.get("atomic_chain") or []
                if not isinstance(chain, list) or not chain:
                    continue
                chains.append(
                    {
                        "tool_id": tool_id,
                        "version": int(r["version"] or 1),
                        "description": str(r["description"] or ""),
                        "chain": chain[:_MAX_CHAIN_STEPS],
                        "step_n": min(len(chain), _MAX_CHAIN_STEPS),
                        "savings_factor": int(chain_obj.get("savings_factor") or 0),
                    }
                )
        if not chains:
            continue
        avg_step = round(sum(c["step_n"] for c in chains) / max(len(chains), 1), 2)
        avg_savings = round(sum(c["savings_factor"] for c in chains) / max(len(chains), 1), 2)
        yield {
            "domain": domain,
            "chains": chains,
            "avg_step_n": avg_step,
            "avg_savings_factor": avg_savings,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    domain = str(row.get("domain") or "unknown")
    chains = list(row.get("chains") or [])
    rows_in_packet = len(chains)
    package_id = f"{PACKAGE_KIND}:domain_{safe_packet_id_segment(domain)}"

    known_gaps = [
        {
            "code": "professional_review_required",
            "description": (
                "tool chain は scaffold、最終 routing は agent runtime + 顧問専門家 "
                "(税理士 §52 / 弁護士 §72 / 行政書士 §1の2) が要"
            ),
        },
        {
            "code": "no_hit_not_absence",
            "description": (
                "domain='all' は domain 詳細未登録 fallback、Wave 51 dim P 拡充後に消去"
            ),
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/wave51/composable-tools/",
            "source_fetched_at": None,
            "publisher": "jpcite Wave 51 dim P design",
            "license": "gov_standard",
        },
        {
            "source_url": "https://docs.jpcite.com/agent-runtime/composed-tools/",
            "source_fetched_at": None,
            "publisher": "jpcite agent runtime docs",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "domain", "id": domain},
        "domain": domain,
        "chains": chains[:_MAX_CHAINS_PER_DOMAIN],
        "avg_step_n": float(row.get("avg_step_n") or 0.0),
        "avg_savings_factor": float(row.get("avg_savings_factor") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": f"domain_{domain}", "domain": domain},
        metrics={
            "chain_n": rows_in_packet,
            "avg_step_n": float(row.get("avg_step_n") or 0.0),
            "avg_savings_factor": float(row.get("avg_savings_factor") or 0.0),
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
