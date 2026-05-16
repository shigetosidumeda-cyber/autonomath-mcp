#!/usr/bin/env python3
"""Generate ``kpi_funding_correlation_v1`` packets (Wave 60 #5 of 10).

業種 (JSIC major) ごとに採択件数 × 平均交付額 × 行政処分密度 × 制度カバレッジ の
4 軸 cohort indicator を集計し、descriptive KPI correlation proxy として packet
化する。因果分析や予測は含まれず観測値のみ。

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

PACKAGE_KIND: Final[str] = "kpi_funding_correlation_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 KPI funding correlation packet は jpi_adoption_records + "
    "jpi_pc_enforcement_industry_distribution + jpi_pc_top_subsidies_by_industry を "
    "業種別に 4 軸集計した descriptive 指標です。因果分析・予測 は含まれず観測値のみ。"
    "事業性分析判断は中小企業診断士 + 税理士の一次確認が前提 (税理士法 §52)。"
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
        avg_granted = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n, "
                "       COALESCE(AVG(NULLIF(amount_granted_yen, 0)), 0) AS avg_g "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
                avg_granted = int(row["avg_g"] or 0)
        enforcement_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c "
                "  FROM jpi_pc_enforcement_industry_distribution "
                " WHERE industry_jsic = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                enforcement_n = int(row["c"] or 0)
        coverage_programs = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c "
                "  FROM jpi_pc_top_subsidies_by_industry "
                " WHERE industry_jsic = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                coverage_programs = int(row["c"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
            "avg_granted_yen": avg_granted,
            "enforcement_distribution_n": enforcement_n,
            "program_coverage_n": coverage_programs,
        }
        if adoption_n + enforcement_n + coverage_programs > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    adoption_n = int(row.get("adoption_n") or 0)
    enforcement_n = int(row.get("enforcement_distribution_n") or 0)
    coverage_n = int(row.get("program_coverage_n") or 0)
    rows_in_packet = adoption_n + enforcement_n + coverage_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "因果ではなく観測値、事業性分析は中小企業診断士 + 税理士の一次確認が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で 4 軸 KPI 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
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
        "adoption_n": adoption_n,
        "avg_granted_yen": int(row.get("avg_granted_yen") or 0),
        "enforcement_distribution_n": enforcement_n,
        "program_coverage_n": coverage_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
            "avg_granted_yen": int(row.get("avg_granted_yen") or 0),
            "enforcement_distribution_n": enforcement_n,
            "program_coverage_n": coverage_n,
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
