#!/usr/bin/env python3
"""Generate ``accessibility_endpoint_health_v1`` packets (Wave 100 #4 of 10).

Per public API endpoint family (REST + MCP tool), emit an availability /
uptime proxy from canonical route catalog + manifest tool list. The
real uptime metric will be sourced from monitoring/sla.json + Wave 49
G1 aggregator; this packet seeds the Wave 51 funnel `Accessibility`
axis (memory `feedback_agent_funnel_6_stages.md`) with the structural
endpoint surface. NO LLM.

Cohort
------
::

    cohort = endpoint_family (rest_v1 / mcp_tool / well_known / static)
"""

from __future__ import annotations

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

PACKAGE_KIND: Final[str] = "accessibility_endpoint_health_v1"

_MAX_ENDPOINTS_PER_PACKET: Final[int] = 120

DEFAULT_DISCLAIMER: Final[str] = (
    "本 accessibility endpoint health packet は canonical endpoint family の "
    "descriptive proxy で、実 uptime / p95 latency / 5xx rate は Wave 49 G1 "
    "RUM beacon aggregator + Fly health metric から上書き予定。本 packet 単体 "
    "で SLA を構成しない。"
)


# Endpoint families with hand-curated canonical sample list. Real
# uptime SLO comes from monitoring/sla.json — out of packet scope.
_ENDPOINT_FAMILIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "rest_v1",
        (
            "/v1/programs",
            "/v1/programs/{program_id}",
            "/v1/cases",
            "/v1/laws",
            "/v1/tax_rules",
            "/v1/court_decisions",
            "/v1/bids",
            "/v1/invoice_registrants",
            "/v1/enforcement",
            "/v1/me/client_profiles",
            "/v1/me/courses",
            "/v1/am/annotations/{entity_id}",
            "/v1/am/validate",
            "/v1/am/provenance/{entity_id}",
            "/v1/am/provenance/fact/{fact_id}",
            "/v1/am/health/deep",
        ),
    ),
    (
        "mcp_tool",
        (
            "search_programs",
            "get_program",
            "search_cases",
            "search_loans",
            "search_tax_incentives",
            "search_certifications",
            "list_open_programs",
            "active_programs_at",
            "graph_traverse",
            "unified_lifecycle_calendar",
            "program_lifecycle",
            "rule_engine_check",
            "related_programs",
            "apply_eligibility_chain_am",
            "find_complementary_programs_am",
            "simulate_application_am",
            "track_amendment_lineage_am",
            "program_active_periods_am",
        ),
    ),
    (
        "well_known",
        (
            "/.well-known/llms.txt",
            "/.well-known/mcp-server.json",
            "/.well-known/openapi.json",
            "/.well-known/security.txt",
            "/.well-known/agent.json",
            "/llms.txt",
            "/llms-full.txt",
            "/sitemap.xml",
            "/robots.txt",
            "/openapi.json",
        ),
    ),
    (
        "static",
        (
            "/",
            "/docs/",
            "/site/",
            "/audiences/construction.html",
            "/audiences/manufacturing.html",
            "/audiences/real_estate.html",
            "/healthz",
            "/readyz",
            "/version",
            "/pricing.html",
        ),
    ),
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    # primary_conn used for cross-ref (still want non-empty DB).
    if not table_exists(primary_conn, "am_entities"):
        return

    for emitted, (family, endpoints) in enumerate(_ENDPOINT_FAMILIES):
        endpoint_records: list[dict[str, Any]] = [
            {
                "endpoint": ep,
                "method": "GET" if family != "mcp_tool" else "INVOKE",
                "stable_since_marker": "Wave 50 RC1 (2026-05-16)",
            }
            for ep in endpoints
        ]
        # Heuristic uptime baseline (NOT real measurement).
        baseline_uptime = {
            "rest_v1": 0.999,
            "mcp_tool": 0.999,
            "well_known": 0.9995,
            "static": 0.9999,
        }.get(family, 0.99)
        yield {
            "family": family,
            "endpoints": endpoint_records,
            "baseline_uptime_proxy": baseline_uptime,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    family = str(row.get("family") or "unknown")
    endpoints = list(row.get("endpoints") or [])
    rows_in_packet = len(endpoints)
    package_id = f"{PACKAGE_KIND}:family_{safe_packet_id_segment(family)}"

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "baseline_uptime_proxy は SLO 目標、実測 uptime は monitoring/"
                "sla.json + Wave 49 G1 aggregator 経由で fill 予定"
            ),
        },
        {
            "code": "no_hit_not_absence",
            "description": "list 外の private endpoint も内部に存在、本 packet は public のみ",
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/agent-funnel/accessibility/",
            "source_fetched_at": None,
            "publisher": "jpcite docs",
            "license": "gov_standard",
        },
        {
            "source_url": "https://api.jpcite.com/.well-known/openapi.json",
            "source_fetched_at": None,
            "publisher": "jpcite api",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "endpoint_family", "id": family},
        "endpoint_family": family,
        "endpoints": endpoints[:_MAX_ENDPOINTS_PER_PACKET],
        "baseline_uptime_proxy": float(row.get("baseline_uptime_proxy") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": f"family_{family}", "endpoint_family": family},
        metrics={
            "endpoint_n": rows_in_packet,
            "baseline_uptime_proxy": float(row.get("baseline_uptime_proxy") or 0.0),
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
