#!/usr/bin/env python3
"""Generate ``landslide_geotechnical_risk_v1`` packets (Wave 83 #7 of 10).

業種 (JSIC major) ごとに 土砂災害 × geotechnical risk (採択密度 proxy) を
集計し、descriptive sectoral landslide / geotechnical risk indicator として
packet 化する。土砂災害警戒区域 (イエロー) / 特別警戒区域 (レッド) / 急傾斜地 /
土石流 / 地すべり / 深層崩壊 / 地盤調査 / 擁壁 / 法面 補強 / 雨量警報 判断は
国交省 砂防部 + 都道府県 土砂災害防止法担当 + 国立研究開発法人 防災科学技術
研究所 (NIED) + 地盤工学専門家 + 土砂災害コンサル + 林野庁 (山地災害) の一次
確認が前提。

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

PACKAGE_KIND: Final[str] = "landslide_geotechnical_risk_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 landslide geotechnical risk packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、土砂災害警戒区域 (イエロー) / "
    "特別警戒区域 (レッド) / 急傾斜地 / 土石流 / 地すべり / 深層崩壊 / 地盤"
    "調査 / 擁壁 / 法面 補強 / 雨量警報 判断は国交省 砂防部 + 都道府県 + "
    "NIED + 地盤工学専門家 + 土砂災害コンサル + 林野庁の一次確認が前提です "
    "(土砂災害防止法 §6 §9, 急傾斜地法 §3, 地すべり等防止法 §3, "
    "国交省 重ねるハザードマップ 土砂災害)。"
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
                "土砂災害警戒区域 / 特別警戒区域 / 急傾斜地 / 土石流 / 地"
                "すべり / 深層崩壊 / 地盤調査 / 擁壁 / 法面 / 雨量警報 判断"
                "は国交省 砂防部 + 都道府県 + NIED + 地盤工学専門家 + 土砂"
                "災害コンサル + 林野庁の一次確認が前提"
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
            "source_url": "https://www.mlit.go.jp/river/sabo/index.html",
            "source_fetched_at": None,
            "publisher": "国土交通省 砂防部",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.bosai.go.jp/",
            "source_fetched_at": None,
            "publisher": "防災科学技術研究所 (NIED)",
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
