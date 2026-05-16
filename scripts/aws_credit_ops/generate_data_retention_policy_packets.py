#!/usr/bin/env python3
"""Generate ``data_retention_policy_v1`` packets (Wave 66 #8 of 10).

業種 (JSIC major) ごとに 個人データ保存期間 (個情法 §22 正確性確保 + 不要時消去
+ 業界 specific 保存義務 [税法 7 年 / 商法 10 年 / 医療法 5 年 etc.]) policy
disclosure proxy を集計し、descriptive sectoral data retention policy density
indicator として packet 化する。個社の保存期間設定の妥当性判定ではなく、業種
全体の policy shape のみ。

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

PACKAGE_KIND: Final[str] = "data_retention_policy_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 data retention policy packet は jpi_adoption_records を業種別に集計した"
    " descriptive policy 密度 proxy で、個情法 §22 正確性確保 + 不要時消去義務 "
    "+ 業界保存義務 (税法 §72 / 商法 §19 / 医療法施行規則 §20 等) 適合判断は "
    "個人情報保護委員会 + 業界主務官庁 + 顧問弁護士の一次確認が前提 (弁護士法"
    " §72)。"
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
                "個情法 §22 + 業界保存義務 (税法 7 年 / 商法 10 年 / 医療法 5 年"
                " 等) 適合判断は PPC + 業界主務官庁 + 顧問弁護士の一次確認が前提"
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
            "source_url": "https://www.ppc.go.jp/personalinfo/legal/guidelines_tsusoku/",
            "source_fetched_at": None,
            "publisher": "個人情報保護委員会 通則編ガイドライン",
            "license": "gov_standard",
        },
        {
            "source_url": "https://elaws.e-gov.go.jp/document?lawid=415AC0000000057",
            "source_fetched_at": None,
            "publisher": "e-Gov 個人情報の保護に関する法律",
            "license": "cc_by_4.0",
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
