#!/usr/bin/env python3
"""Generate ``revenue_volatility_subsidy_offset_v1`` packets (Wave 61 #8 of 10).

業種 (JSIC major) ごとに 売上変動 × 補助金 offset effect proxy の cohort
indicator を descriptive に集計する。個社 offset 判定ではない。

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

PACKAGE_KIND: Final[str] = "revenue_volatility_subsidy_offset_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 revenue volatility subsidy offset packet は jpi_adoption_records の "
    "amount_granted_yen 分布から業種別 offset proxy を descriptive に集計。"
    "売上変動は推定 proxy、個社 offset 判定は税理士・公認会計士の一次確認が前提"
    " (税理士法 §52、会計士法 §47条の2)。"
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
        avg_grant = 0
        max_grant = 0
        min_grant = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n, "
                "       COALESCE(AVG(NULLIF(amount_granted_yen, 0)), 0) AS avg_g, "
                "       COALESCE(MAX(amount_granted_yen), 0) AS max_g, "
                "       COALESCE(MIN(NULLIF(amount_granted_yen, 0)), 0) AS min_g "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
                avg_grant = int(row["avg_g"] or 0)
                max_grant = int(row["max_g"] or 0)
                min_grant = int(row["min_g"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
            "avg_grant_yen": avg_grant,
            "max_grant_yen": max_grant,
            "min_grant_yen": min_grant,
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
    avg_g = int(row.get("avg_grant_yen") or 0)
    max_g = int(row.get("max_grant_yen") or 0)
    min_g = int(row.get("min_grant_yen") or 0)
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "offset 判定は税理士・公認会計士の一次確認が前提",
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
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-stat.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Stat 政府統計",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
        "avg_grant_yen": avg_g,
        "max_grant_yen": max_g,
        "min_grant_yen": min_g,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
            "avg_grant_yen": avg_g,
            "max_grant_yen": max_g,
            "min_grant_yen": min_g,
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
