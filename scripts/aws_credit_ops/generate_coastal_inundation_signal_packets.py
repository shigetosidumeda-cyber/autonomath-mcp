#!/usr/bin/env python3
"""Generate ``coastal_inundation_signal_v1`` packets (Wave 83 #6 of 10).

業種 (JSIC major) ごとに 沿岸 inundation × 事業所 (採択密度 proxy) を集計し、
descriptive sectoral coastal inundation signal indicator として packet 化
する。海面上昇 / 高潮 / 高波 / 沿岸侵食 / 港湾施設 損傷 / 防潮堤 / 海岸保全
施設 / 沿岸事業所 浸水 risk / 気候変動 海面上昇 projection (RCP 2.6 / 8.5)
判断は国交省 港湾局 + 国交省 水管理・国土保全局 海岸 + 気象庁 + 内閣府防災 +
気候変動適応センター + 海洋研究開発機構 (JAMSTEC) + 沿岸工学専門家の一次
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

PACKAGE_KIND: Final[str] = "coastal_inundation_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 coastal inundation signal packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、海面上昇 / 高潮 / 高波 / "
    "沿岸侵食 / 港湾施設 損傷 / 防潮堤 / 海岸保全施設 / 沿岸事業所 浸水 / "
    "気候変動 海面上昇 projection 判断は国交省 港湾局 + 国交省 海岸 + 気象庁 + "
    "内閣府防災 + 気候変動適応センター + JAMSTEC + 沿岸工学専門家の一次確認"
    "が前提です (海岸法 §1, 港湾法 §1, 気候変動適応法 §3, IPCC AR6, "
    "気象庁 潮位観測, 海洋研究開発機構 海洋モデル)。"
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
                "海面上昇 / 高潮 / 高波 / 沿岸侵食 / 港湾施設 損傷 / 防潮堤 / "
                "海岸保全施設 / 沿岸事業所 浸水 / 気候変動 海面上昇 projection "
                "判断は国交省 港湾局 + 国交省 海岸 + 気象庁 + 内閣府防災 + "
                "気候変動適応センター + JAMSTEC + 沿岸工学専門家の一次確認"
                "が前提"
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
            "source_url": "https://www.mlit.go.jp/kowan/kowan_fr3_000016.html",
            "source_fetched_at": None,
            "publisher": "国土交通省 港湾局",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/tideandcurrent.php",
            "source_fetched_at": None,
            "publisher": "気象庁 潮位・海面水温データベース",
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
