#!/usr/bin/env python3
"""Generate ``regional_industry_subsidy_match_v1`` packets (Wave 70 #3 of 10).

地域 × 業種 × 補助金受給 houjin matrix を houjin universal key で結合。
``jpi_adoption_records.amount_granted_yen`` がある行のみを採用し、補助金
受給実績を持つ法人の地域×業種 intersection を houjin で記録。

Cohort
------
::

    cohort = (houjin_bangou, prefecture, industry_jsic_medium, amount_total_yen)
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

PACKAGE_KIND: Final[str] = "regional_industry_subsidy_match_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regional × industry × subsidy 受給 houjin packet は "
    "jpi_adoption_records から amount_granted_yen を持つ行のみ抽出した "
    "descriptive 補助金受給 intersection で、給付資格判断は管轄省庁・"
    "公認会計士・税理士の一次確認が前提 (税理士法 §52)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    sql = (
        "SELECT houjin_bangou, prefecture, industry_jsic_medium, "
        "       COUNT(*) AS adoption_n, "
        "       COALESCE(SUM(amount_granted_yen), 0) AS amt "
        "  FROM jpi_adoption_records "
        " WHERE houjin_bangou IS NOT NULL "
        "   AND prefecture IS NOT NULL "
        "   AND industry_jsic_medium IS NOT NULL "
        " GROUP BY houjin_bangou, prefecture, industry_jsic_medium "
        " ORDER BY amt DESC, adoption_n DESC, houjin_bangou "
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    emitted = 0
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(sql):
            yield {
                "houjin_bangou": str(r["houjin_bangou"]),
                "prefecture": str(r["prefecture"]),
                "industry_jsic_medium": str(r["industry_jsic_medium"]),
                "adoption_n": int(r["adoption_n"] or 0),
                "amt": int(r["amt"] or 0),
            }
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    houjin = str(row.get("houjin_bangou") or "UNKNOWN")
    prefecture = str(row.get("prefecture") or "UNKNOWN")
    industry = str(row.get("industry_jsic_medium") or "UNKNOWN")
    adoption_n = int(row.get("adoption_n") or 0)
    amt = int(row.get("amt") or 0)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(houjin)}"
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "補助金受給判断は管轄省庁・税理士の一次確認が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 houjin の subsidy 受給観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": (
                "https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id=" + houjin
            ),
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/sme/",
            "source_fetched_at": None,
            "publisher": "経済産業省 中小企業庁",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": houjin},
        "houjin_bangou": houjin,
        "prefecture": prefecture,
        "industry_jsic_medium": industry,
        "adoption_n": adoption_n,
        "amount_total_yen": amt,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": f"{prefecture}|{industry}|{houjin}",
            "houjin_bangou": houjin,
            "prefecture": prefecture,
            "industry_jsic_medium": industry,
        },
        metrics={
            "adoption_n": adoption_n,
            "amount_total_yen": amt,
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
