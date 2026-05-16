"""Generate ``j_reit_holding_proxy_v1`` packets (Wave 93 #9 of 10).

業種 (JSIC major) ごとに J-REIT 保有 proxy 兆候 (採択密度 proxy) を集計し、
descriptive sectoral J-REIT holding proxy indicator として packet 化する。実際
の J-REIT 銘柄 / オフィス特化 / 住居特化 / 物流特化 / 商業特化 / ホテル特化 /
ヘルスケア特化 / 総合型 / 投資口価格 / 分配金利回り / NAV / LTV / スポンサー
関係 判断は 東証 REIT 市場 + EDINET 投資法人 有価証券報告書 + 投信協会 +
不動産鑑定士 + 金商法 担当弁護士 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "j_reit_holding_proxy_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 J-REIT holding proxy packet は jpi_adoption_records 業種別 採択"
    "密度 を集計した descriptive proxy で、実際の J-REIT 銘柄 / オフィス"
    "特化 / 住居特化 / 物流特化 / 商業特化 / ホテル特化 / ヘルスケア"
    "特化 / 総合型 / 投資口価格 / 分配金利回り / NAV / LTV / スポンサー"
    "関係 / 運用会社 / アセットマネジャー (AM) / 物件入替 (POs) 判断は"
    " 東証 REIT 市場 + EDINET 投資法人 有価証券報告書 + 投信協会 + "
    "不動産鑑定士 + 金商法 担当弁護士 一次確認が前提です (投資信託及び"
    "投資法人に関する法律 §2 §187-§225, 金融商品取引法 §2 §24 §66 §157,"
    " 不動産投資信託及び不動産投資法人に関する規則 (内閣府令), 不動産"
    "鑑定評価基準, 東京証券取引所 上場規程・有価証券上場規程 §1101-2,"
    " 投資信託協会 規則 (J-REIT)。一般投資家への助言は金商法 §29 投資"
    "助言業登録が必要で、本 packet は単なる descriptive proxy です。)"
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
                "J-REIT 銘柄 / オフィス特化 / 住居特化 / 物流特化"
                " / 商業特化 / ホテル特化 / ヘルスケア特化 / 総合"
                "型 / 投資口価格 / 分配金利回り / NAV / LTV / スポ"
                "ンサー関係 / 運用会社 / AM / 物件入替 判断は 東証"
                " REIT 市場 + EDINET 投資法人 有価証券報告書 + 投信"
                "協会 + 不動産鑑定士 + 金商法 担当弁護士 一次確認が"
                "前提"
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
            "source_url": "https://www.jpx.co.jp/equities/products/reits/",
            "source_fetched_at": None,
            "publisher": "東京証券取引所 REIT 市場",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.toushin.or.jp/statistics/statistics/",
            "source_fetched_at": None,
            "publisher": "投資信託協会 J-REIT 統計",
            "license": "proprietary",
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
