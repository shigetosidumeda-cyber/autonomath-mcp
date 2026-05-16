#!/usr/bin/env python3
"""Generate ``adoption_fiscal_cycle_v1`` packets (Wave 56 #3 of 10).

採択事例の会計年度 cycle (FY) × JSIC 業種別に件数・金額・unique 法人を集計、
当年度と前年度の比較を packet 化する。

Cohort
------
::

    cohort = jsic_major (JSIC 大分類)
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

PACKAGE_KIND: Final[str] = "adoption_fiscal_cycle_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 adoption fiscal cycle packet は jpi_adoption_records を業種 × 会計年度で"
    "集計した descriptive 指標です。個別採択判断は一次資料 (Jグランツ / 各自治体公報)"
    "確認が必要。"
)


def _fy_from_iso(value: str | None) -> str:
    if not isinstance(value, str) or len(value) < 7:
        return "UNKNOWN"
    y = value[:4]
    m = value[5:7]
    if not (y.isdigit() and m.isdigit()):
        return "UNKNOWN"
    yi = int(y)
    fy = yi - 1 if int(m) < 4 else yi
    return f"FY{fy}"


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    jsic_majors: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT substr(industry_jsic_medium, 1, 1) AS j "
            "  FROM jpi_adoption_records "
            " WHERE industry_jsic_medium IS NOT NULL "
            "   AND industry_jsic_medium != '' "
            " ORDER BY j"
        ):
            j = str(r["j"] or "")
            if j and j != "0":
                jsic_majors.append(j)

    for emitted, jsic in enumerate(jsic_majors):
        per_fy: dict[str, dict[str, int]] = {}
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT announced_at, "
                "       COUNT(*) AS c, "
                "       COUNT(DISTINCT houjin_bangou) AS uh, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS s "
                "  FROM jpi_adoption_records "
                " WHERE substr(industry_jsic_medium, 1, 1) = ? "
                "   AND announced_at IS NOT NULL "
                " GROUP BY announced_at",
                (jsic,),
            ):
                fy = _fy_from_iso(str(r["announced_at"]))
                bucket = per_fy.setdefault(
                    fy,
                    {"count": 0, "unique_houjin": 0, "total_amount_yen": 0},
                )
                bucket["count"] += int(r["c"] or 0)
                bucket["unique_houjin"] += int(r["uh"] or 0)
                bucket["total_amount_yen"] += int(r["s"] or 0)
        fy_list_sorted = sorted(per_fy.keys(), reverse=True)[:PER_AXIS_RECORD_CAP]
        record: dict[str, Any] = {
            "jsic_major": jsic,
            "fiscal_years": [
                {"fiscal_year": fy, **per_fy[fy]} for fy in fy_list_sorted
            ],
            "total_count": sum(b["count"] for b in per_fy.values()),
            "total_amount_yen": sum(b["total_amount_yen"] for b in per_fy.values()),
        }
        if record["total_count"] > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic = str(row.get("jsic_major") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic)}"
    fys = list(row.get("fiscal_years", []))
    rows_in_packet = len(fys)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "会計年度集計の鮮度は jpi_adoption_records fetch 時点に依存",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 JSIC 大分類で会計年度 cycle 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "fiscal_year_count": rows_in_packet,
        "total_count": int(row.get("total_count") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic},
        "jsic_major": jsic,
        "fiscal_years": fys,
        "total_count": int(row.get("total_count") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic, "jsic_major": jsic},
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
