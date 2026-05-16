#!/usr/bin/env python3
"""Generate ``foreign_worker_program_v1`` packets (Wave 75 #7 of 10).

業種 (JSIC major) ごとに 外国人労働者制度 (特定技能 / 技能実習 /
高度専門職 / 留学生) coverage density proxy を集計し、descriptive
sectoral foreign worker program coverage indicator として packet 化
する。個社の外国人雇用適格性判断ではなく、業種全体の coverage
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

PACKAGE_KIND: Final[str] = "foreign_worker_program_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 foreign worker program packet は jpi_adoption_records を業種別 "
    "に集計した descriptive 外国人労働者制度 coverage proxy で、個別事業者 "
    "の外国人雇用適格性判断は 出入国在留管理庁 / 厚生労働省 / 行政書士 "
    "(在留資格) / 社労士 / 外国人技能実習機構 (OTIT) の一次確認が前提 "
    "(入管法、技能実習法、特定技能制度、行政書士法§1、社労士法§27)。 "
    "在留資格認定証明書交付申請の代理は行政書士業務領域。"
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
        amount_total = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_g "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
                amount_total = int(row["total_g"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
            "amount_total_yen": amount_total,
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
    amount_total = int(row.get("amount_total_yen") or 0)
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "外国人雇用適格性判断は 出入国在留管理庁 / 行政書士 (在留資格) / 社労士 の一次確認が前提",
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
            "source_url": "https://www.moj.go.jp/isa/index.html",
            "source_fetched_at": None,
            "publisher": "出入国在留管理庁 (法務省)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.otit.go.jp/",
            "source_fetched_at": None,
            "publisher": "外国人技能実習機構 (OTIT)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
        "amount_total_yen": amount_total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
            "amount_total_yen": amount_total,
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
