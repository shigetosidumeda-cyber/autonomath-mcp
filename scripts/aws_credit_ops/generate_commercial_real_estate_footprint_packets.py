"""Generate ``commercial_real_estate_footprint_v1`` packets (Wave 93 #1 of 10).

業種 (JSIC major) ごとに 商業不動産 footprint signal 兆候 (採択密度 proxy) を
集計し、descriptive sectoral commercial real estate footprint indicator として
packet 化する。実際の 保有不動産 / 賃貸契約 / 床面積 / オフィス・店舗・倉庫
内訳 / 含み損益 判断は 有価証券報告書 (EDINET) 「設備の状況」 + 法務局
不動産登記 + 国交省 法人土地・建物 基本調査 + 固定資産税課税台帳 + 不動産
鑑定士 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "commercial_real_estate_footprint_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 commercial real estate footprint packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、実際の 保有不動産 / 賃貸契約"
    " / 床面積 / オフィス・店舗・倉庫 内訳 / 含み損益 / 投資不動産 判断は"
    " 有価証券報告書 (EDINET) 「設備の状況」 + 法務局 不動産登記 + 国交省"
    " 法人土地・建物 基本調査 + 固定資産税課税台帳 + 不動産鑑定士 一次確認"
    "が前提です (不動産登記法 §3 §44, 不動産鑑定評価基準, 不動産鑑定士法,"
    " 地価公示法 §2-§7, 国土利用計画法 §23, 借地借家法 §3 §26-§29, 区分所有"
    "法 §6-§17, 都市計画法 §29 開発許可, 建築基準法 §6-§7-2 建築確認, 宅建"
    "業法 §35 重要事項説明, IFRS 16 / IAS 40 投資不動産, 企業会計基準第28号"
    "「公正価値測定」)。"
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
                "保有不動産 / 賃貸契約 / 床面積 / オフィス・店舗・倉庫"
                " 内訳 / 含み損益 / 投資不動産 判断は 有価証券報告書 "
                "(EDINET) 「設備の状況」 + 法務局 不動産登記 + 国交省"
                " 法人土地・建物 基本調査 + 固定資産税課税台帳 + 不動産"
                "鑑定士 一次確認が前提"
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
            "source_url": "https://disclosure2.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET 有価証券報告書 (設備の状況)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mlit.go.jp/totikensangyo/totikensangyo_tk5_000086.html",
            "source_fetched_at": None,
            "publisher": "国土交通省 法人土地・建物基本調査",
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
