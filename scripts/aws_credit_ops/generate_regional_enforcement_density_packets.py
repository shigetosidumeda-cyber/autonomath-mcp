#!/usr/bin/env python3
"""Generate ``regional_enforcement_density_v1`` packets (Wave 57 #6 of 10).

地域別 行政処分密度。jpi_enforcement_cases + am_enforcement_detail を都道府県
で集計、処分種別 (event_type / enforcement_kind) 別の積算 + 直近 12ヶ月推移。

Cohort
------
::

    cohort = prefecture
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

PACKAGE_KIND: Final[str] = "regional_enforcement_density_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regional enforcement density packet は jpi_enforcement_cases を都道府県 × "
    "処分種別で集計した descriptive 密度指標です。個別 case の判断は官報原文 + "
    "所管官庁の一次確認が必須。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_enforcement_cases"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_enforcement_cases "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        kind_dist: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT event_type, COUNT(*) AS c, "
                "       COALESCE(SUM(amount_yen), 0) AS sum_amount "
                "  FROM jpi_enforcement_cases "
                " WHERE prefecture = ? "
                " GROUP BY event_type ORDER BY c DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                kind_dist.append(dict(r))
        total = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_enforcement_cases "
                " WHERE prefecture = ?",
                (pref,),
            ).fetchone()
            if row:
                total = int(row[0] or 0)
        record = {
            "prefecture": pref,
            "enforcement_kind_distribution": kind_dist,
            "total_cases": total,
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    kinds = list(row.get("enforcement_kind_distribution", []))
    total = int(row.get("total_cases") or 0)
    rows_in_packet = len(kinds)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "個別 case の judgment は弁護士・行政書士の専門判断が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で処分 case 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://kanpou.npb.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報 (国立印刷局)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "enforcement_kind_distribution": kinds,
        "total_cases": total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"kind_buckets": rows_in_packet, "total_cases": total},
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
