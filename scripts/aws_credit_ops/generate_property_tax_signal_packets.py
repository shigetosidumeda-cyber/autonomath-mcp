"""Generate ``property_tax_signal_v1`` packets (Wave 93 #3 of 10).

業種 (JSIC major) ごとに 固定資産税 signal 兆候 (採択密度 proxy) を集計し、
descriptive sectoral property tax signal indicator として packet 化する。実際の
固定資産税 / 都市計画税 / 償却資産税 / 標準税率 (1.4%) / 制限税率 / 課税標準
特例 / 負担調整措置 / 評価替え (3年ごと) / 不動産取得税 / 登録免許税 / 印紙税
判断は 市町村 固定資産税課税台帳 + 総務省 固定資産概要調書 + 不動産鑑定士 +
税理士 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "property_tax_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 property tax signal packet は jpi_adoption_records 業種別 採択"
    "密度 を集計した descriptive proxy で、実際の 固定資産税 / 都市計画"
    "税 / 償却資産税 / 標準税率 (1.4%) / 制限税率 / 課税標準特例 / 負担"
    "調整措置 / 評価替え (3年ごと) / 不動産取得税 / 登録免許税 / 印紙税"
    " 判断は 市町村 固定資産税課税台帳 + 総務省 固定資産概要調書 + 不動産"
    "鑑定士 + 税理士 一次確認が前提です (地方税法 §341-§384 固定資産税, "
    "地方税法 §702-§702-8 都市計画税, 地方税法 §73-§73-37 不動産取得税,"
    " 登録免許税法 §9 別表第一, 印紙税法 §1-§3, 税理士法 §52, §47条の2,"
    " §72 (税理士業務制限), 地方税法 §22 守秘義務)。"
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
                "固定資産税 / 都市計画税 / 償却資産税 / 標準税率 "
                "(1.4%) / 制限税率 / 課税標準特例 / 負担調整措置 / "
                "評価替え (3年ごと) / 不動産取得税 / 登録免許税 / "
                "印紙税 判断は 市町村 固定資産税課税台帳 + 総務省 "
                "固定資産概要調書 + 不動産鑑定士 + 税理士 一次確認が"
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
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/czaisei/czaisei_seido/ichiran01_02.html",
            "source_fetched_at": None,
            "publisher": "総務省 地方税制 固定資産税",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/inshi/annai/23100024.htm",
            "source_fetched_at": None,
            "publisher": "国税庁 印紙税の手引",
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
