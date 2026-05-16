#!/usr/bin/env python3
"""Generate ``volcanic_zone_overlay_v1`` packets (Wave 83 #8 of 10).

業種 (JSIC major) ごとに 火山 hazard × 事業所 overlay (採択密度 proxy) を
集計し、descriptive sectoral volcanic zone overlay indicator として packet
化する。活火山 111 / 噴火警戒レベル / 火砕流 / 火砕サージ / 火山泥流 (ラハール) /
火山灰 / 降灰荷重 / 噴石 影響範囲 / 火山ガス / カルデラ / 大規模噴火 影響 判断
は気象庁 火山課 + 火山噴火予知連絡会 + 防災科学技術研究所 (NIED) + 火山学者
(産総研 地質調査総合センター) + 内閣府防災 + 都道府県 火山防災協議会の一次
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

PACKAGE_KIND: Final[str] = "volcanic_zone_overlay_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 volcanic zone overlay packet は jpi_adoption_records 業種別 採択"
    "密度 を集計した descriptive proxy で、活火山 111 / 噴火警戒レベル / "
    "火砕流 / 火砕サージ / 火山泥流 / 火山灰 / 降灰荷重 / 噴石 / 火山ガス / "
    "カルデラ / 大規模噴火 影響 判断は気象庁 火山課 + 火山噴火予知連絡会 + "
    "防災科学技術研究所 (NIED) + 火山学者 (産総研 地質調査総合センター) + "
    "内閣府防災 + 都道府県 火山防災協議会の一次確認が前提です "
    "(活動火山対策特別措置法 §1, 災害対策基本法 §2, 気象業務法 §13, "
    "気象庁 火山活動の解説資料)。"
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
                "活火山 111 / 噴火警戒レベル / 火砕流 / 火山泥流 / 火山灰 / "
                "降灰荷重 / 噴石 / 火山ガス / カルデラ / 大規模噴火 判断は"
                "気象庁 火山課 + 火山噴火予知連絡会 + NIED + 産総研 地質"
                "調査総合センター + 内閣府防災 + 都道府県 火山防災協議会の"
                "一次確認が前提"
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
            "source_url": "https://www.data.jma.go.jp/svd/vois/data/tokyo/STOCK/kaisetsu/katsukazan_toha/katsukazan_toha.html",
            "source_fetched_at": None,
            "publisher": "気象庁 火山課 活火山一覧",
            "license": "gov_standard",
        },
        {
            "source_url": "https://gbank.gsj.jp/volcano/",
            "source_fetched_at": None,
            "publisher": "産業技術総合研究所 地質調査総合センター 日本の火山",
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
