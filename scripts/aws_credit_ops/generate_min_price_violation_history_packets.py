"""Generate ``min_price_violation_history_v1`` packets (Wave 87 #5 of 10).

業種 (JSIC major) ごとに 最低価格 (minimum price) 違反 / 低入札価格調査
履歴 (採択密度 proxy) を集計し、descriptive sectoral minimum price
violation history indicator として packet 化する。低入札価格調査基準 / 失
格判定基準 / ダンピング受注 / 公契約条例 (賃金下限) 違反 / 不当廉売 / 入
札保証金 不足 / 履行能力不足 / 履行確認時 不適合 / 下請単価 法定最低賃金
割れ / 公正取引委員会 違反 判断は 各府省 契約情報公開 + 入札監視委員会
+ 各自治体 公契約担当 + 厚労省 賃金課 + 公取委 + 弁護士・社労士 + 監査
法人の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "min_price_violation_history_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 min price violation history packet は jpi_adoption_records 業種"
    "別 採択密度 を集計した descriptive proxy で、実際の 低入札価格調査"
    "基準 / 失格判定基準 / ダンピング受注 / 公契約条例 (賃金下限) 違反 "
    "/ 不当廉売 / 入札保証金 不足 / 履行能力不足 / 履行確認時 不適合 / "
    "下請単価 法定最低賃金割れ / 公正取引委員会 違反 判断は 各府省 契約"
    "情報公開 + 入札監視委員会 + 各自治体 公契約担当 + 厚労省 賃金課 + "
    "公取委 + 弁護士・社労士 + 監査法人の一次確認が前提です (会計法 §"
    "29条の6, 予決令 §85-86 低入札価格調査, 公契約条例 各自治体, 独占"
    "禁止法 §19 不当廉売)。"
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
                "低入札価格調査基準 / 失格判定基準 / ダンピング受注 / "
                "公契約条例 (賃金下限) 違反 / 不当廉売 / 入札保証金 不足"
                " / 履行能力不足 / 履行確認時 不適合 / 下請単価 法定最低"
                "賃金割れ / 公正取引委員会 違反 判断は 各府省 契約情報"
                "公開 + 入札監視委員会 + 各自治体 公契約担当 + 厚労省 + "
                "公取委 + 弁護士・社労士 + 監査法人の一次確認が前提"
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
            "source_url": "https://www.jftc.go.jp/dk/guideline/unyoukijun/futoubaiyaku.html",
            "source_fetched_at": None,
            "publisher": "公正取引委員会 不当廉売ガイドライン",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/minimumichiran/index.html",
            "source_fetched_at": None,
            "publisher": "厚生労働省 最低賃金",
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
