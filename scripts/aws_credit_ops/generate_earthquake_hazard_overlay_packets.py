#!/usr/bin/env python3
"""Generate ``earthquake_hazard_overlay_v1`` packets (Wave 83 #2 of 10).

業種 (JSIC major) ごとに 地震ハザード × 事業所 (採択密度 proxy) を集計し、
descriptive sectoral earthquake hazard overlay indicator として packet 化
する。確率論的地震動予測地図 / 震度別 影響評価 / 活断層帯 直下 / 長周期
地震動 / 液状化 危険度 / 耐震診断 / 制震免震 / 設備固定 判断は内閣府防災 +
気象庁 + 防災科学技術研究所 (NIED) + J-SHIS + 地震本部 + 構造設計者 +
損害保険専門家の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "earthquake_hazard_overlay_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 earthquake hazard overlay packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、確率論的地震動予測地図 / "
    "震度別 影響 / 活断層直下 / 長周期地震動 / 液状化危険度 / 耐震診断 / "
    "制震免震 / 設備固定 判断は内閣府防災 + 気象庁 + 防災科学技術研究所 "
    "(NIED) + J-SHIS + 地震本部 + 構造設計者 + 損害保険専門家の一次確認が"
    "前提です (地震防災対策特別措置法 §3, 建築物の耐震改修の促進に関する"
    "法律 §1, 南海トラフ地震防災対策推進地域 / 首都直下地震緊急対策区域)。"
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
                "確率論的地震動予測地図 / 震度別 影響 / 活断層直下 / 長周期"
                "地震動 / 液状化 / 耐震 / 制震免震 / 設備固定 判断は内閣府"
                "防災 + 気象庁 + NIED + J-SHIS + 地震本部 + 構造設計者 + "
                "損害保険専門家の一次確認が前提"
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
            "source_url": "https://www.j-shis.bosai.go.jp/",
            "source_fetched_at": None,
            "publisher": "防災科学技術研究所 (NIED) J-SHIS 地震ハザードステーション",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jishin.go.jp/",
            "source_fetched_at": None,
            "publisher": "地震調査研究推進本部 (地震本部)",
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
