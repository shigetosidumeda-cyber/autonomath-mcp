#!/usr/bin/env python3
"""Generate ``competitor_subsidy_uptake_v1`` packets (Wave 60 #2 of 10).

業種 (JSIC major) ごとに公開された採択件数を集計して descriptive 競合 uptake
proxy として packet 化する。法人個社の identifying analysis は含まれず、
業種 cohort 内 frequency と top program proxy のみ。

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

PACKAGE_KIND: Final[str] = "competitor_subsidy_uptake_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 competitor subsidy uptake packet は jpi_adoption_records の業種別件数 + "
    "上位採択 program proxy を集計した descriptive 指標です。競合分析判断は "
    "中小企業診断士 + 行政書士 の一次確認が前提 (中小企業診断士法 / 行政書士法 §1)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        total = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                total = int(row["c"] or 0)
        top_programs: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COALESCE(NULLIF(program_id_hint,''), program_name_raw) AS k, "
                "       COUNT(*) AS c "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ? "
                " GROUP BY k HAVING c > 0 ORDER BY c DESC LIMIT ?",
                (jsic_code, PER_AXIS_RECORD_CAP),
            ):
                k = str(r["k"] or "")
                if k:
                    top_programs.append({"program_proxy": k, "adoption_count": int(r["c"] or 0)})
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "total_adoptions": total,
            "top_programs": top_programs,
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    top_programs = list(row.get("top_programs", []))
    total = int(row.get("total_adoptions") or 0)
    rows_in_packet = len(top_programs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "競合分析判断は中小企業診断士 + 行政書士 の一次確認が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で採択 proxy 観測無し",
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
            "source_url": "https://www.chusho.meti.go.jp/",
            "source_fetched_at": None,
            "publisher": "中小企業庁",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "total_adoptions": total,
        "top_programs": top_programs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "total_adoptions": total,
            "top_program_count": rows_in_packet,
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
