"""Generate ``prefecture_procurement_match_v1`` packets (Wave 87 #3 of 10).

業種 (JSIC major) ごとに 都道府県 procurement match / 自治体調達適合度
(採択密度 proxy) を集計し、descriptive sectoral prefecture procurement
match indicator として packet 化する。47 都道府県別 調達カテゴリ / 入札
資格 等級 (A/B/C/D) / 物品・役務・工事 区分 / 地元中小企業優先 / SME
random pick / 入札参加資格審査 (経審含む) / 共同企業体 JV 参加 / 過去
落札実績 / 地域ブロック発注 判断は 47 都道府県 入札公告 + 各市区町村
契約担当 + 各都道府県 中小企業担当 + 全国知事会 + 各市町村 議会 + 弁護
士・行政書士 + 入札専門家の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "prefecture_procurement_match_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 prefecture procurement match packet は jpi_adoption_records 業種"
    "別 採択密度 を集計した descriptive proxy で、実際の 47 都道府県別 "
    "調達カテゴリ / 入札資格 等級 (A/B/C/D) / 物品・役務・工事 区分 / "
    "地元中小企業優先 / 入札参加資格審査 (経審含む) / 共同企業体 JV 参加"
    " / 過去落札実績 / 地域ブロック発注 判断は 47 都道府県 入札公告 + "
    "各市区町村 契約担当 + 各都道府県 中小企業担当 + 全国知事会 + 各市町"
    "村 議会 + 弁護士・行政書士 + 入札専門家の一次確認が前提です (地方"
    "自治法 §234, 地方自治法施行令 §167, 中小企業者に関する国等の契約"
    "の方針 §1, 入札契約適正化法 §2)。"
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
                "47 都道府県別 調達カテゴリ / 入札資格 等級 (A/B/C/D) / "
                "物品・役務・工事 区分 / 地元中小企業優先 / 入札参加資格"
                "審査 (経審含む) / 共同企業体 JV 参加 / 過去落札実績 / "
                "地域ブロック発注 判断は 47 都道府県 入札公告 + 各市区町"
                "村 契約担当 + 各都道府県 中小企業担当 + 全国知事会 + 弁"
                "護士・行政書士 + 入札専門家の一次確認が前提"
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
            "source_url": "https://www.chusho.meti.go.jp/keiei/torihiki/2024/240628keiyaku.html",
            "source_fetched_at": None,
            "publisher": "中小企業庁 国等の契約の方針",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nga.gr.jp/",
            "source_fetched_at": None,
            "publisher": "全国知事会",
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
