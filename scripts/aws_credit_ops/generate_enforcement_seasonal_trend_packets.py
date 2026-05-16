#!/usr/bin/env python3
"""Generate ``enforcement_seasonal_trend_v1`` packets (Wave 56 #2 of 10).

行政処分 (``jpi_enforcement_cases`` + ``am_enforcement_detail``) を都道府県別 ×
月別の季節性ヒストグラムにまとめ、年内のピーク月と直近 12ヶ月の推移を packet 化。

Cohort
------
::

    cohort = prefecture (都道府県)

Constraints — see other Wave 56 generators.
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

PACKAGE_KIND: Final[str] = "enforcement_seasonal_trend_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 enforcement seasonal trend packet は jpi_enforcement_cases + "
    "am_enforcement_detail を都道府県 × 月で集計した descriptive 季節性指標です。"
    "個別 disposal 判断は所管官庁・公報の一次確認が必須。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_enforcement_cases"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_enforcement_cases "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        monthly_buckets: dict[str, int] = {f"{i:02d}": 0 for i in range(1, 13)}
        total = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT disclosed_date, COUNT(*) AS c "
                "  FROM jpi_enforcement_cases "
                " WHERE prefecture = ? AND disclosed_date IS NOT NULL "
                "   AND length(disclosed_date) >= 7 "
                " GROUP BY disclosed_date",
                (pref,),
            ):
                d = str(r["disclosed_date"])
                if len(d) >= 7:
                    mm = d[5:7]
                    if mm in monthly_buckets:
                        c = int(r["c"] or 0)
                        monthly_buckets[mm] += c
                        total += c
        peak_month = max(monthly_buckets, key=lambda m: monthly_buckets[m])
        record = {
            "prefecture": pref,
            "monthly_distribution": monthly_buckets,
            "total_cases": total,
            "peak_month": peak_month,
            "peak_count": monthly_buckets[peak_month],
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    monthly = dict(row.get("monthly_distribution", {}))
    total = int(row.get("total_cases") or 0)
    rows_in_packet = sum(1 for v in monthly.values() if v > 0)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "個別 disposal の鮮度は 公報 fetch 時点に依存",
        }
    ]
    if total == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で disposal 観測無し — 公報確認必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://kanpou.npb.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報 (国立印刷局)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "monthly_distribution": monthly,
        "peak_month": str(row.get("peak_month") or ""),
        "peak_count": int(row.get("peak_count") or 0),
        "total_cases": total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "total_cases": total,
            "peak_count": int(row.get("peak_count") or 0),
            "active_months": rows_in_packet,
        },
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, max(rows_in_packet, 1 if total > 0 else 0)


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
