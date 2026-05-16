#!/usr/bin/env python3
"""Generate ``kanpou_event_burst_v1`` packets (Wave 56 #10 of 10).

官報 event (jpi_enforcement_cases + jpi_court_decisions + am_amendment_diff)
を年-月で総和し、平均比 ≥2× で「burst」と判定した月を packet 化。

Cohort
------
::

    cohort = ministry (官報の source_url から逆引きする近似値、空は OTHER)
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

PACKAGE_KIND: Final[str] = "kanpou_event_burst_v1"
PER_AXIS_RECORD_CAP: Final[int] = 24
BURST_THRESHOLD: Final[float] = 2.0

DEFAULT_DISCLAIMER: Final[str] = (
    "本 kanpou event burst packet は jpi_enforcement_cases + jpi_court_decisions "
    "+ am_amendment_diff を月別に総和し、平均比≥2x の月を burst 候補とした "
    "descriptive signal です。実際の event 内容は官報原文の一次確認が必須。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    monthly: dict[str, dict[str, int]] = {}

    def _add(ym: str, key: str) -> None:
        if len(ym) < 7:
            return
        m = ym[:7]
        bucket = monthly.setdefault(m, {"enforcement": 0, "court": 0, "amendment": 0})
        bucket[key] += 1

    if table_exists(primary_conn, "jpi_enforcement_cases"):
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT disclosed_date FROM jpi_enforcement_cases "
                " WHERE disclosed_date IS NOT NULL"
            ):
                _add(str(r["disclosed_date"]), "enforcement")
    if table_exists(primary_conn, "jpi_court_decisions"):
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT decision_date FROM jpi_court_decisions "
                " WHERE decision_date IS NOT NULL"
            ):
                _add(str(r["decision_date"]), "court")
    if table_exists(primary_conn, "am_amendment_diff"):
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT detected_at FROM am_amendment_diff "
                " WHERE detected_at IS NOT NULL"
            ):
                _add(str(r["detected_at"]), "amendment")

    if not monthly:
        return

    # compute averages and burst detection
    totals = [b["enforcement"] + b["court"] + b["amendment"] for b in monthly.values()]
    mean = sum(totals) / max(len(totals), 1)
    bursts: list[dict[str, Any]] = []
    for ym, b in monthly.items():
        total = b["enforcement"] + b["court"] + b["amendment"]
        if mean > 0 and total >= mean * BURST_THRESHOLD:
            bursts.append(
                {
                    "year_month": ym,
                    "total": total,
                    "enforcement": b["enforcement"],
                    "court": b["court"],
                    "amendment": b["amendment"],
                    "ratio_to_mean": round(total / mean, 2) if mean else 0.0,
                }
            )
    bursts.sort(key=lambda d: d["total"], reverse=True)

    # 1 single global packet
    record = {
        "scope": "global",
        "monthly_mean": round(mean, 2),
        "bursts": bursts[:PER_AXIS_RECORD_CAP],
        "month_observed": len(monthly),
    }
    yield record
    if limit is not None and limit <= 1:
        return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    scope = str(row.get("scope") or "global")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(scope)}"
    bursts = list(row.get("bursts", []))
    rows_in_packet = len(bursts)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "burst signal は descriptive のみ。各 event 内容は官報原文確認必須",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "burst 候補無し (平均比≥2x の月が無い)",
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
        "subject": {"kind": "scope", "id": scope},
        "scope": scope,
        "bursts": bursts,
        "monthly_mean": float(row.get("monthly_mean") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": scope, "scope": scope},
        metrics={
            "burst_count": rows_in_packet,
            "month_observed": int(row.get("month_observed") or 0),
            "monthly_mean": float(row.get("monthly_mean") or 0.0),
        },
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, max(rows_in_packet, 1)


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
