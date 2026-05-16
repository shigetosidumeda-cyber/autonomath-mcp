#!/usr/bin/env python3
"""Generate ``sensitive_data_handling_v1`` packets (Wave 66 #10 of 10).

業種 (JSIC major) ごとに 要配慮個人情報 (個情法 §2条第 3 項 [人種 / 信条 / 病歴 /
犯歴 / 障害 / 健診結果 / 保健指導等]) handling proxy を集計し、descriptive
sectoral sensitive data handling density indicator として packet 化する。
個社の取得時本人同意 + 第三者提供制限適合判定ではなく、業種全体の handling
shape のみ。

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

PACKAGE_KIND: Final[str] = "sensitive_data_handling_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 sensitive data handling packet は jpi_adoption_records を業種別に集計"
    "した descriptive handling 密度 proxy で、個情法 §2条第 3 項 要配慮個人情報 "
    "(人種 / 信条 / 病歴 / 犯歴 / 障害 / 健診 / 保健指導等) 取得時本人同意 "
    "(§20条第 2 項) + 第三者提供制限 (§27条第 2 項オプトアウト不可) 適合判断は"
    " 個人情報保護委員会 + 業界主務官庁 + 顧問弁護士の一次確認が前提 (弁護士法"
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
                "SELECT COUNT(*) AS n FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
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
                "個情法 §2 第 3 項 要配慮個人情報 + §20 第 2 項取得同意 + §27 第"
                " 2 項オプトアウト不可 適合判断は PPC + 業界主務官庁 + 顧問弁護士"
                "の一次確認が前提"
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
            "publisher": "個人情報保護委員会 通則編ガイドライン (要配慮個人情報)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.ppc.go.jp/personalinfo/legal/guidelines_iryou/",
            "source_fetched_at": None,
            "publisher": "個人情報保護委員会 医療・介護関係事業者ガイダンス",
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
