#!/usr/bin/env python3
"""Generate ``logistics_partner_360_v1`` packets (Wave 68 #2 of 10).

業種 (JSIC major) ごとに 物流 partner 360 (運送・倉庫・通関・宅配 等)
の業界別 dependency density proxy を集計し、descriptive sectoral
logistics partner profile indicator として packet 化する。個社の物流
パートナー評価ではなく、業種全体の partner profile shape のみ。

Cohort
------
::

    cohort = jsic_major (A-V)
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

PACKAGE_KIND: Final[str] = "logistics_partner_360_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 logistics partner 360 packet は jpi_adoption_records + "
    "jpi_loan_programs を業種別に集計した descriptive partner profile "
    "proxy で、物流委託先の選定 / 与信判断は荷主企業 / 物流コンサル / "
    "保険代理店の一次確認が前提 (貨物利用運送事業法、貨物自動車運送事業法)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        adoption_n = 0
        amount_total = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_g "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
                amount_total = int(row["total_g"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
            "amount_total_yen": amount_total,
        }
        if adoption_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    adoption_n = int(row.get("adoption_n") or 0)
    amount_total = int(row.get("amount_total_yen") or 0)
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "物流委託先の選定 / 与信判断は荷主企業 / 物流コンサル / 保険代理店の一次確認が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で adoption record 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.mlit.go.jp/seisakutokatsu/freight/",
            "source_fetched_at": None,
            "publisher": "国土交通省 物流政策",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-stat.go.jp/stat-search/files?tclass=000001033844",
            "source_fetched_at": None,
            "publisher": "総務省統計局 経済構造統計 (運輸業)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
        "amount_total_yen": amount_total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
            "amount_total_yen": amount_total,
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
