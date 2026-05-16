#!/usr/bin/env python3
"""Generate ``cross_prefecture_arbitrage_v1`` packets (Wave 57 #4 of 10).

都道府県間の制度差を arbitrage 機会として抽出。同一業種 (JSIC) で都道府県別の
unique 制度数を出し、密度差が ≥2× の組合せを示す。

Cohort
------
::

    cohort = jsic_major
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

PACKAGE_KIND: Final[str] = "cross_prefecture_arbitrage_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10
ARBITRAGE_RATIO: Final[float] = 2.0

DEFAULT_DISCLAIMER: Final[str] = (
    "本 cross prefecture arbitrage packet は jpi_adoption_records を業種 × 都道府県"
    "で密度比較し、≥2x の差を arbitrage 候補とした descriptive 指標です。"
    "実際の申請判断は都道府県公示の一次確認が必須。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    jsic_majors: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT substr(industry_jsic_medium, 1, 1) AS j "
            "  FROM jpi_adoption_records "
            " WHERE industry_jsic_medium IS NOT NULL AND industry_jsic_medium != ''"
        ):
            j = str(r["j"] or "")
            if j and j != "0":
                jsic_majors.append(j)

    for emitted, jsic in enumerate(jsic_majors):
        per_pref: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT prefecture, COUNT(*) AS adoptions, "
                "       COUNT(DISTINCT program_id) AS unique_program_count "
                "  FROM jpi_adoption_records "
                " WHERE substr(industry_jsic_medium, 1, 1) = ? "
                "   AND prefecture IS NOT NULL AND prefecture != '' "
                " GROUP BY prefecture ORDER BY adoptions DESC",
                (jsic,),
            ):
                per_pref.append(dict(r))
        if not per_pref:
            continue
        top = per_pref[0]
        arb_candidates: list[dict[str, Any]] = []
        top_adoptions = int(top["adoptions"] or 0)
        for p in per_pref[1:]:
            adoptions = int(p["adoptions"] or 0)
            if adoptions > 0 and top_adoptions / adoptions >= ARBITRAGE_RATIO:
                arb_candidates.append(
                    {
                        "prefecture_low": p["prefecture"],
                        "prefecture_high": top["prefecture"],
                        "low_adoptions": adoptions,
                        "high_adoptions": top_adoptions,
                        "ratio": round(top_adoptions / adoptions, 2),
                    }
                )
        record = {
            "jsic_major": jsic,
            "top_prefecture": top["prefecture"],
            "top_adoptions": top_adoptions,
            "arbitrage_candidates": arb_candidates[:PER_AXIS_RECORD_CAP],
        }
        if arb_candidates:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic = str(row.get("jsic_major") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic)}"
    arb = list(row.get("arbitrage_candidates", []))
    rows_in_packet = len(arb)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "arbitrage signal は密度のみ。実際の申請可否は都道府県個別確認",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 JSIC 大分類で arbitrage 候補無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic},
        "jsic_major": jsic,
        "top_prefecture": str(row.get("top_prefecture") or ""),
        "top_adoptions": int(row.get("top_adoptions") or 0),
        "arbitrage_candidates": arb,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic, "jsic_major": jsic},
        metrics={
            "candidate_count": rows_in_packet,
            "top_adoptions": int(row.get("top_adoptions") or 0),
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
