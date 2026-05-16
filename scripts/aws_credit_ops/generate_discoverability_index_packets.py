#!/usr/bin/env python3
"""Generate ``discoverability_index_v1`` packets (Wave 100 #1 of 10).

Per published program tier, derive a Discoverability index from
proxy signals that live in autonomath.db today:

* ``aliases_json`` non-empty count (alias-density proxy for organic
  long-tail LLM hit-share — Wave 21 D9 lifted to 9,996 rows).
* ``source_url`` host diversity (publisher diversification proxy).
* tier (S/A/B/C) as a baseline visibility weight.

This is a **descriptive proxy** — not a real organic search rank or LLM
mention share. It seeds the Wave 51 funnel `Discoverability` axis
(memory `feedback_agent_funnel_6_stages.md`) with a per-tier scalar
that downstream organic-aggregator can join against. NO LLM call.

Cohort
------
::

    cohort = program tier (S / A / B / C)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "discoverability_index_v1"

#: Per-tier program sampling cap (descriptive, not exhaustive).
_MAX_PROGRAMS_PER_TIER: Final[int] = 60

DEFAULT_DISCLAIMER: Final[str] = (
    "本 discoverability index packet は jpi_programs の alias 密度 / publisher "
    "多様性 / tier weight から組み立てた descriptive proxy で、実 LLM mention "
    "share や organic search rank の代替ではない。実値は Wave 49 G1 organic "
    "aggregator + Smithery/Glama download metric の到達後に上書きされる前提。"
    "顧客 acquisition 助言は 行政書士法 §1の2 / 税理士法 §52 の射程外。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_programs"):
        return

    tiers: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT tier FROM jpi_programs "
            " WHERE tier IN ('S','A','B','C') AND excluded = 0 "
            " ORDER BY tier"
        ):
            tiers.append(str(r["tier"]))

    for emitted, tier in enumerate(tiers):
        programs: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT id, name, source_url, aliases_json "
                "  FROM jpi_programs "
                " WHERE tier = ? AND excluded = 0 "
                " ORDER BY id "
                " LIMIT ?",
                (tier, _MAX_PROGRAMS_PER_TIER),
            ):
                aliases_json = str(r["aliases_json"] or "")
                alias_n = aliases_json.count('"') // 2 if aliases_json else 0
                src = str(r["source_url"] or "")
                host = ""
                if "://" in src:
                    host = src.split("://", 1)[1].split("/", 1)[0]
                programs.append(
                    {
                        "program_id": str(r["id"] or ""),
                        "name": str(r["name"] or ""),
                        "publisher_host": host,
                        "alias_n": alias_n,
                    }
                )
        if not programs:
            continue
        host_n = len({p["publisher_host"] for p in programs if p["publisher_host"]})
        avg_alias = (
            round(sum(p["alias_n"] for p in programs) / max(len(programs), 1), 2)
            if programs
            else 0.0
        )
        tier_weight = {"S": 1.0, "A": 0.75, "B": 0.5, "C": 0.25}.get(tier, 0.1)
        yield {
            "tier": tier,
            "programs": programs,
            "host_diversity_n": host_n,
            "avg_alias_n": avg_alias,
            "tier_weight": tier_weight,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    tier = str(row.get("tier") or "X")
    programs = list(row.get("programs") or [])
    rows_in_packet = len(programs)
    package_id = f"{PACKAGE_KIND}:tier_{safe_packet_id_segment(tier)}"

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "alias_n / publisher_host は jpi_programs snapshot 由来で、"
                "実 LLM mention share / SERP rank の to-the-day 値ではない"
            ),
        },
        {
            "code": "no_hit_not_absence",
            "description": "host=空 は source_url 未登録、organic 不在の証明ではない",
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/agent-funnel/discoverability/",
            "source_fetched_at": None,
            "publisher": "jpcite docs",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "program_tier", "id": tier},
        "tier": tier,
        "programs": programs[:_MAX_PROGRAMS_PER_TIER],
        "host_diversity_n": int(row.get("host_diversity_n") or 0),
        "avg_alias_n": float(row.get("avg_alias_n") or 0.0),
        "tier_weight": float(row.get("tier_weight") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": f"tier_{tier}", "tier": tier},
        metrics={
            "program_n": rows_in_packet,
            "host_diversity_n": int(row.get("host_diversity_n") or 0),
            "avg_alias_n": float(row.get("avg_alias_n") or 0.0),
            "tier_weight": float(row.get("tier_weight") or 0.0),
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
