#!/usr/bin/env python3
"""Generate ``prefecture_x_industry_density_v1`` packets (Wave 70 #2 of 10).

Houjin universal key carrying (prefecture × industry_jsic_medium) density
proxy. Wave 70 #2 — fills the canonical moat hole where prefecture cohort
and industry cohort packets carry no shared key (Wave 67 Q12+Q14 EMPTY).

Cohort
------
::

    cohort = (houjin_bangou, prefecture, industry_jsic_medium)
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

PACKAGE_KIND: Final[str] = "prefecture_x_industry_density_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 prefecture × industry × houjin density packet は jpi_adoption_records を "
    "(houjin, prefecture, industry_jsic_medium) 軸で名寄せした descriptive "
    "density proxy で、houjin universal key として記録する。"
    "個社判断は M&A advisor / 公認会計士 一次確認が前提 (税理士法 §52)。"
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
        " ORDER BY adoption_n DESC, houjin_bangou "
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
            "description": (
                "density proxy は集計指標であり、個別 houjin の経営判断には "
                "M&A advisor / 公認会計士 一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 houjin の adoption observation 無し",
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
            "source_url": "https://www.e-stat.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Stat 都道府県別統計",
            "license": "cc_by_4.0",
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
