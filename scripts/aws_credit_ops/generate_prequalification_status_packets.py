"""Generate ``prequalification_status_v1`` packets (Wave 87 #6 of 10).

業種 (JSIC major) ごとに 経審 (建設業 経営事項審査) prequalification
status (採択密度 proxy) を集計し、descriptive sectoral prequalification
status indicator として packet 化する。経審総合評点 P / 完成工事高 X1 /
自己資本額 X2 / 利益額 / 経営状況分析 Y / 経営規模等評価 / 技術職員数 Z
/ 元請完成工事高 / 社会性等 W / ISO 9001 / ISO 14001 / 防災活動協定 /
法令順守 等 加点・減点 判断は 国交省 不動産・建設経済局 + 各都道府県
建設業課 + 経審分析機関 + 公認会計士 + 弁護士・行政書士 + 建設業経営者
+ 工事業協会の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "prequalification_status_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 prequalification status packet は jpi_adoption_records 業種別 採"
    "択密度 を集計した descriptive proxy で、実際の 経審総合評点 P / 完"
    "成工事高 X1 / 自己資本額 X2 / 利益額 / 経営状況分析 Y / 経営規模等"
    "評価 / 技術職員数 Z / 元請完成工事高 / 社会性等 W / ISO 9001 / "
    "ISO 14001 / 防災活動協定 / 法令順守 等 加点・減点 判断は 国交省 不"
    "動産・建設経済局 + 各都道府県 建設業課 + 経審分析機関 + 公認会計士"
    " + 弁護士・行政書士 + 建設業経営者 + 工事業協会の一次確認が前提"
    "です (建設業法 §27条の23 経審, 建設業法施行規則 §19条の5-19条の6, "
    "経審評定要領 国交省告示)。"
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
                "経審総合評点 P / 完成工事高 X1 / 自己資本額 X2 / 利益額"
                " / 経営状況分析 Y / 経営規模等評価 / 技術職員数 Z / 元請"
                "完成工事高 / 社会性等 W / ISO 9001 / ISO 14001 / 防災"
                "活動協定 / 法令順守 等 加点・減点 判断は 国交省 + 各都"
                "道府県 建設業課 + 経審分析機関 + 公認会計士 + 弁護士・"
                "行政書士 + 建設業経営者 + 工事業協会の一次確認が前提"
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
            "source_url": "https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000091.html",
            "source_fetched_at": None,
            "publisher": "国交省 経営事項審査 (経審)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.ciic.or.jp/",
            "source_fetched_at": None,
            "publisher": "(財) 建設業情報管理センター CIIC",
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
