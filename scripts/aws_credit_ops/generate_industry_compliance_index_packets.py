#!/usr/bin/env python3
"""Generate ``industry_compliance_index_v1`` packets (Wave 60 #1 of 10).

業種 (JSIC major) ごとに行政処分 / 排他ルール / 認証 / 環境compliance signal を
集約し、descriptive compliance index packet として書き出す。判定や格付けは
含まれない (¥3/req JPCIR envelope 内の cohort 内 frequency のみ)。

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

PACKAGE_KIND: Final[str] = "industry_compliance_index_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 industry compliance index packet は jpi_pc_enforcement_industry_distribution + "
    "jpi_exclusion_rules + adoption_records industry_jsic_medium から業種別の "
    "compliance signal 観測数を集計した descriptive 指標です。compliance 評価判断は "
    "所管官庁 + 行政書士 + 社労士 の一次確認が前提 (行政書士法 §1 / 社労士法 §27)。"
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
        enforcement_n = 0
        exclusion_n = 0
        adoption_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_pc_enforcement_industry_distribution "
                " WHERE industry_jsic = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                enforcement_n = int(row["c"] or 0)
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["c"] or 0)
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_exclusion_rules "
                " WHERE kind IN ('exclude', 'absolute', 'mutual_exclusion') "
                "   AND (description LIKE ? OR extra_json LIKE ?)",
                (f"%{jsic_name}%", f'%"{jsic_code}"%'),
            ).fetchone()
            if row:
                exclusion_n = int(row["c"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "enforcement_distribution_n": enforcement_n,
            "exclusion_rule_n": exclusion_n,
            "adoption_n": adoption_n,
        }
        if enforcement_n + exclusion_n + adoption_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    enforcement_n = int(row.get("enforcement_distribution_n") or 0)
    exclusion_n = int(row.get("exclusion_rule_n") or 0)
    adoption_n = int(row.get("adoption_n") or 0)
    rows_in_packet = enforcement_n + exclusion_n + adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "compliance 評価判断は所管官庁 + 行政書士 + 社労士 の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で compliance signal 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.soumu.go.jp/main_content/000290720.pdf",
            "source_fetched_at": None,
            "publisher": "総務省 JSIC",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "enforcement_distribution_n": enforcement_n,
        "exclusion_rule_n": exclusion_n,
        "adoption_n": adoption_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "enforcement_distribution_n": enforcement_n,
            "exclusion_rule_n": exclusion_n,
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
