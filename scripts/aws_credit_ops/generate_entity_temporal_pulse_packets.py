#!/usr/bin/env python3
"""Generate ``entity_temporal_pulse_v1`` packets (Wave 69 #9 of 10).

法人 × all time-series events. Yearly bucketed counts across all
data axes (adoption / enforcement / bid / invoice change) — a "pulse"
proxy of public-record activity by year for the houjin.

Cohort
------

::

    cohort = houjin_bangou (13-digit, canonical subject.kind = "houjin")
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

PACKAGE_KIND: Final[str] = "entity_temporal_pulse_v1"
YEAR_CAP: Final[int] = 20

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity temporal pulse packet は法人の年次活動 proxy (event count) "
    "です。実体的成長や財務指標の代理ではない — 各年の事象詳細は他 360 "
    "packet で個別確認してください。"
)


def _bump(buckets: dict[str, dict[str, int]], year: str, axis: str) -> None:
    bucket = buckets.setdefault(year, {})
    bucket[axis] = bucket.get(axis, 0) + 1


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    cap = int(limit) if limit is not None else 100000
    # Seed from adoption density — temporal pulse requires at least one
    # year-bucketed event, which adoption_records guarantees.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, COUNT(a.id) AS adopt_count "
        "  FROM jpi_adoption_records AS a "
        "  JOIN houjin_master AS h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " ORDER BY adopt_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        buckets: dict[str, dict[str, int]] = {}
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT substr(announced_at,1,4) AS y "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? AND announced_at IS NOT NULL",
                    (bangou,),
                ):
                    y = str(r["y"] or "")
                    if y:
                        _bump(buckets, y, "adoption")
        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT substr(issuance_date,1,4) AS y "
                    "  FROM am_enforcement_detail "
                    " WHERE houjin_bangou = ? AND issuance_date IS NOT NULL",
                    (bangou,),
                ):
                    y = str(r["y"] or "")
                    if y:
                        _bump(buckets, y, "enforcement")
        if table_exists(primary_conn, "jpi_bids"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT substr(decision_date,1,4) AS y "
                    "  FROM jpi_bids "
                    " WHERE winner_houjin_bangou = ? "
                    "   AND decision_date IS NOT NULL",
                    (bangou,),
                ):
                    y = str(r["y"] or "")
                    if y:
                        _bump(buckets, y, "bid_won")
        if not buckets:
            continue
        # Keep up to YEAR_CAP most recent years.
        ordered = sorted(buckets.items(), reverse=True)[:YEAR_CAP]
        timeline: list[dict[str, Any]] = []
        for year, axes_map in ordered:
            timeline.append(
                {
                    "year": year,
                    "axes": axes_map,
                    "event_total": sum(axes_map.values()),
                }
            )
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "timeline": timeline,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    timeline = list(row.get("timeline", []))
    rows_in_packet = len(timeline)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "本 packet は公共記録 event count による activity proxy。"
                "実体的成長や財務指標の代理ではない — 各事象は他 360 packet "
                "で個別確認。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "年次 event 観測無し = 活動ゼロを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "year_count": len(timeline),
        "year_min": min((t.get("year") for t in timeline), default=None),
        "year_max": max((t.get("year") for t in timeline), default=None),
        "total_events": sum(int(t.get("event_total") or 0) for t in timeline),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "timeline": timeline,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": bangou, "houjin_bangou": bangou},
        metrics=metrics,
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
