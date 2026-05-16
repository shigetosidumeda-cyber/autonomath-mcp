#!/usr/bin/env python3
"""Generate ``drought_water_supply_risk_v1`` packets (Wave 83 #5 of 10).

業種 (JSIC major) ごとに 渇水 × 水源 supply risk (採択密度 proxy) を集計し、
descriptive sectoral drought water-supply risk indicator として packet 化
する。渇水確率 / ダム貯水率 / 取水制限 / 工業用水 上水 / 農業用水 / 河川流量 /
地下水位 / 渇水対策節水 / 降水量変動 (気候変動) 判断は国交省 水管理・国土
保全局 + 水資源機構 (JWA) + 都道府県 水道事業者 + 経産省 工業用水 + 農水省 +
水文学専門家 + 気候適応センターの一次確認が前提。

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

PACKAGE_KIND: Final[str] = "drought_water_supply_risk_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 drought water supply risk packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、渇水確率 / ダム貯水率 / "
    "取水制限 / 工業用水 上水 / 農業用水 / 河川流量 / 地下水位 / 渇水対策 "
    "節水 / 降水量変動 判断は国交省 水管理・国土保全局 + 水資源機構 (JWA) + "
    "都道府県 水道事業者 + 経産省 工業用水 + 農水省 + 水文学専門家 + 気候"
    "適応センターの一次確認が前提です (水循環基本法 §13, 工業用水法 §2, "
    "水道法 §1, 河川法 §1, 気候変動適応法 §3)。"
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
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n FROM jpi_adoption_records  WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
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
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "渇水確率 / ダム貯水率 / 取水制限 / 工業用水 上水 / 農業用水 / "
                "河川流量 / 地下水位 / 渇水対策 節水 / 降水量変動 判断は国交省 + "
                "水資源機構 (JWA) + 都道府県 水道事業者 + 経産省 + 農水省 + "
                "水文学専門家 + 気候適応センターの一次確認が前提"
            ),
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
            "source_url": "https://www.mlit.go.jp/mizukokudo/mizsei/index.html",
            "source_fetched_at": None,
            "publisher": "国土交通省 水資源政策",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.water.go.jp/",
            "source_fetched_at": None,
            "publisher": "独立行政法人 水資源機構 (JWA)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
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
