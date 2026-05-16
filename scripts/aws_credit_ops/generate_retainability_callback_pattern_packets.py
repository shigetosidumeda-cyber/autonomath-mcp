#!/usr/bin/env python3
"""Generate ``retainability_callback_pattern_v1`` packets (Wave 100 #6 of 10).

Per agent session cohort (proxy: tool_id × week-of-year bucket), emit
a Retainability score combining (a) repeat-call density on the same
composed tool and (b) callback gap distribution. Seeds the Wave 51
funnel `Retainability` axis (memory `feedback_agent_funnel_6_stages.md`).
Source telemetry will come from Wave 49 G1 aggregator + Credit Wallet
ledger later — this packet emits the structural cohort frame so the
downstream join is ready. NO LLM.

Cohort
------
::

    cohort = composed_tool_id (am_composed_tool_catalog.tool_id)

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

PACKAGE_KIND: Final[str] = "retainability_callback_pattern_v1"

#: Synthetic week bucket cap per cohort (53 to cover full year + partial).
_MAX_WEEK_BUCKETS: Final[int] = 53

DEFAULT_DISCLAIMER: Final[str] = (
    "本 retainability callback pattern packet は am_composed_tool_catalog 上の "
    "tool 構造から組み立てた cohort frame で、実 session callback 密度は "
    "Wave 49 G1 aggregator + Credit Wallet ledger 接続後に上書きされる前提。"
    "顧客 retention 助言は 行政書士法 §1の2 / 税理士法 §52 の射程外。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_composed_tool_catalog"):
        return

    tool_ids: list[tuple[str, int, str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT tool_id, version, domain, description "
            "  FROM am_composed_tool_catalog "
            " WHERE status = 'committed' "
            " GROUP BY tool_id "
            " ORDER BY tool_id"
        ):
            tool_ids.append(
                (
                    str(r["tool_id"] or ""),
                    int(r["version"] or 1),
                    str(r["domain"] or ""),
                    str(r["description"] or ""),
                )
            )

    for emitted, (tool_id, version, domain, description) in enumerate(tool_ids):
        if not tool_id:
            continue
        # Synthetic week buckets (cohort frame, NOT measurement).
        week_buckets: list[dict[str, Any]] = []
        for w in range(1, _MAX_WEEK_BUCKETS + 1):
            # Decay heuristic so downstream join has a deterministic shape.
            est_call_n = max(0, 50 - w)
            week_buckets.append(
                {
                    "iso_week": w,
                    "estimated_call_n": est_call_n,
                    "callback_gap_days_median": (w % 7) + 1,
                }
            )
        avg_call_n = round(sum(b["estimated_call_n"] for b in week_buckets) / len(week_buckets), 2)
        repeat_rate_proxy = round(min(1.0, avg_call_n / 30.0), 3)
        yield {
            "tool_id": tool_id,
            "version": version,
            "domain": domain,
            "description": description,
            "week_buckets": week_buckets,
            "avg_call_n_per_week": avg_call_n,
            "repeat_rate_proxy": repeat_rate_proxy,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    tool_id = str(row.get("tool_id") or "UNKNOWN")
    version = int(row.get("version") or 1)
    week_buckets = list(row.get("week_buckets") or [])
    rows_in_packet = len(week_buckets)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(tool_id)}:v{version}"

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "週次 call 推定は synthetic decay heuristic、Wave 49 G1 aggregator "
                "接続後に実 session metric で上書き予定"
            ),
        },
        {
            "code": "no_hit_not_absence",
            "description": "本 packet は cohort frame のみ、実 retention は別 source",
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/agent-funnel/retainability/",
            "source_fetched_at": None,
            "publisher": "jpcite docs",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "composed_tool", "id": tool_id},
        "tool_id": tool_id,
        "version": version,
        "domain": str(row.get("domain") or ""),
        "description": str(row.get("description") or ""),
        "week_buckets": week_buckets[:_MAX_WEEK_BUCKETS],
        "avg_call_n_per_week": float(row.get("avg_call_n_per_week") or 0.0),
        "repeat_rate_proxy": float(row.get("repeat_rate_proxy") or 0.0),
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
            "week_bucket_n": rows_in_packet,
            "avg_call_n_per_week": float(row.get("avg_call_n_per_week") or 0.0),
            "repeat_rate_proxy": float(row.get("repeat_rate_proxy") or 0.0),
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
