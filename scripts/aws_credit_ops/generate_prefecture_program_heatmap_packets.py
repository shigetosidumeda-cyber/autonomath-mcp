#!/usr/bin/env python3
"""Generate ``prefecture_program_heatmap_v1`` packets (Wave 57 #1 of 10).

47都道府県 × 制度 (jpi_programs) の密度ヒートマップ。tier × authority_level の
切り口で複合的に集計する。

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

PACKAGE_KIND: Final[str] = "prefecture_program_heatmap_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 prefecture program heatmap packet は jpi_programs を tier × authority_level "
    "× 都道府県で集計した descriptive 密度ヒートマップです。実際の申請可否は"
    "Jグランツ + 各自治体公報を一次確認。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_programs"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_programs "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        tier_counts: dict[str, int] = {}
        authority_counts: dict[str, int] = {}
        total = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT tier, COUNT(*) AS c FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? GROUP BY tier",
                (pref,),
            ):
                t = str(r["tier"] or "_unknown")
                c = int(r["c"] or 0)
                tier_counts[t] = c
                total += c
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT authority_level, COUNT(*) AS c FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? GROUP BY authority_level",
                (pref,),
            ):
                a = str(r["authority_level"] or "_unknown")
                c = int(r["c"] or 0)
                authority_counts[a] = c
        record = {
            "prefecture": pref,
            "tier_distribution": tier_counts,
            "authority_distribution": authority_counts,
            "total_programs": total,
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    tiers = dict(row.get("tier_distribution", {}))
    auths = dict(row.get("authority_distribution", {}))
    total = int(row.get("total_programs") or 0)
    rows_in_packet = len(tiers) + len(auths)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "密度ヒートマップは jpi_programs snapshot 時点に依存",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で制度密度 0 — 一次官公庁公示確認が必要",
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
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "tier_distribution": tiers,
        "authority_distribution": auths,
        "total_programs": total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "total_programs": total,
            "tier_buckets": len(tiers),
            "authority_buckets": len(auths),
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
