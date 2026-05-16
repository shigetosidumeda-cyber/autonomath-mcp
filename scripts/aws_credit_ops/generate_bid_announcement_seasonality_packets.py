#!/usr/bin/env python3
"""Generate ``bid_announcement_seasonality_v1`` packets (Wave 56 #8 of 10).

入札公告 (``jpi_bids``) の announcement_date を ministry / procuring_entity 単位
で月別季節性ヒストグラム化し、ピーク月 + 直近 12ヶ月推移を packet 化。

Cohort
------
::

    cohort = ministry
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

PACKAGE_KIND: Final[str] = "bid_announcement_seasonality_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 bid announcement seasonality packet は jpi_bids の announcement_date を"
    "ministry × 月で集計した descriptive 季節性指標です。個別入札参加判断は"
    "所管官庁の公示の一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_bids"):
        return
    ministries: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT ministry FROM jpi_bids "
            " WHERE ministry IS NOT NULL AND ministry != ''"
        ):
            ministries.append(str(r["ministry"]))

    for emitted, m in enumerate(ministries):
        monthly: dict[str, int] = {f"{i:02d}": 0 for i in range(1, 13)}
        total = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT announcement_date, COUNT(*) AS c "
                "  FROM jpi_bids "
                " WHERE ministry = ? AND announcement_date IS NOT NULL "
                "   AND length(announcement_date) >= 7 "
                " GROUP BY announcement_date",
                (m,),
            ):
                d = str(r["announcement_date"])
                if len(d) >= 7:
                    mm = d[5:7]
                    if mm in monthly:
                        c = int(r["c"] or 0)
                        monthly[mm] += c
                        total += c
        peak_month = max(monthly, key=lambda x: monthly[x])
        record = {
            "ministry": m,
            "monthly_distribution": monthly,
            "total_bids": total,
            "peak_month": peak_month,
            "peak_count": monthly[peak_month],
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    m = str(row.get("ministry") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(m)}"
    monthly = dict(row.get("monthly_distribution", {}))
    total = int(row.get("total_bids") or 0)
    active_months = sum(1 for v in monthly.values() if v > 0)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "公告データの鮮度は jpi_bids fetch 時点に依存",
        }
    ]
    if total == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 ministry で公告観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 (GEPS)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "ministry", "id": m},
        "ministry": m,
        "monthly_distribution": monthly,
        "peak_month": str(row.get("peak_month") or ""),
        "peak_count": int(row.get("peak_count") or 0),
        "total_bids": total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": m, "ministry": m},
        metrics={
            "total_bids": total,
            "active_months": active_months,
            "peak_count": int(row.get("peak_count") or 0),
        },
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, max(active_months, 1 if total > 0 else 0)


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
