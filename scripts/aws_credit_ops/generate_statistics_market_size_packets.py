#!/usr/bin/env python3
"""Generate ``statistics_market_size_v1`` packets (Wave 53.3 #7).

JSIC × 都道府県 × 市場規模 (e-Stat 経済センサス) packet. For each
(jsic_major × prefecture) cell, computes descriptive market-size signals
from ``houjin_master`` aggregates + ``am_entities`` statistic rows when
available. Output is a market-context table, not a forecasted figure.

Cohort
------

::

    cohort = (jsic_major × prefecture)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "statistics_market_size_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 statistics market size packet は houjin_master JSIC × 都道府県 +"
    "公開統計 の descriptive 集約です。経済センサス確報・産業連関表の正本は "
    "総務省統計局 / 経産省を一次確認、市場規模の意思決定は専門家確認の上で。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    with contextlib.suppress(Exception):
        for row in primary_conn.execute(
            "SELECT COALESCE(jsic_major, 'UNKNOWN') AS jsic_major, "
            "       prefecture, "
            "       COUNT(*) AS n, "
            "       SUM(total_received_yen) AS total_program_yen, "
            "       SUM(total_adoptions) AS total_adoptions, "
            "       AVG(total_received_yen) AS mean_received_yen "
            "  FROM houjin_master "
            " WHERE prefecture IS NOT NULL "
            " GROUP BY jsic_major, prefecture "
            " HAVING n > 0"
        ):
            jsic = str(row["jsic_major"] or "UNKNOWN")
            pref = str(row["prefecture"] or "UNKNOWN")
            cells[(jsic, pref)] = {
                "houjin_count": int(row["n"] or 0),
                "total_program_yen": int(row["total_program_yen"] or 0),
                "total_adoptions": int(row["total_adoptions"] or 0),
                "mean_received_yen": float(row["mean_received_yen"] or 0),
            }

    industry_stats_rows: list[dict[str, Any]] = []
    if table_exists(primary_conn, "industry_stats"):
        with contextlib.suppress(Exception):
            for s in primary_conn.execute(
                "SELECT * FROM industry_stats LIMIT 200"
            ):
                industry_stats_rows.append(dict(s))

    for emitted, ((jsic, pref), cell) in enumerate(
        sorted(cells.items(), key=lambda kv: -kv[1]["total_program_yen"])
    ):
        cohort_id = f"{jsic}.{pref}"
        # Filter industry_stats by JSIC if column present
        filtered_stats = [
            s
            for s in industry_stats_rows
            if any(jsic == str(s.get(k) or "") for k in s)
        ][:PER_AXIS_RECORD_CAP]
        record: dict[str, Any] = {
            "cohort_id": cohort_id,
            "jsic_major": jsic,
            "prefecture": pref,
            "market_cell": cell,
            "industry_stat_refs": filtered_stats,
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cohort_id = str(row.get("cohort_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    cell = row.get("market_cell") or {}
    stat_refs = list(row.get("industry_stat_refs", []))
    rows_in_packet = 1 + len(stat_refs)  # cell aggregate always counts as 1

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "市場規模 estimate は補助金採択 + 法人公表データの proxy です。"
                "経済センサスの正本確認推奨。"
            ),
        }
    ]
    if int(cell.get("houjin_count") or 0) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "houjin observations 無し = 産業がゼロを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.e-stat.go.jp/stat-search/files?stat_infid=000040003213",
            "source_fetched_at": None,
            "publisher": "e-Stat 経済センサス活動調査",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/statistics/",
            "source_fetched_at": None,
            "publisher": "経済産業省 統計",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "houjin_count": int(cell.get("houjin_count") or 0),
        "total_program_yen": int(cell.get("total_program_yen") or 0),
        "total_adoptions": int(cell.get("total_adoptions") or 0),
        "mean_received_yen": round(float(cell.get("mean_received_yen") or 0), 2),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "cohort", "id": cohort_id},
        "market_cell": cell,
        "industry_stat_refs": stat_refs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": cohort_id,
            "jsic_major": row.get("jsic_major"),
            "prefecture": row.get("prefecture"),
        },
        metrics=metrics,
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
