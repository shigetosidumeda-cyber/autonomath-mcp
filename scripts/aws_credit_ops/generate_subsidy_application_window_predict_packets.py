#!/usr/bin/env python3
"""Generate ``subsidy_application_window_predict_v1`` packets (Wave 56 #7 of 10).

申請期間 (am_application_round) の過去 cycle を集計し、次回想定 window 開始月の
forecast 候補を出すための descriptive timing signal を packet 化する。
NO LLM — forecast は単純な過去 N round の月分布 mode を取るだけ。

Cohort
------
::

    cohort = program_unified_id
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

PACKAGE_KIND: Final[str] = "subsidy_application_window_predict_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 subsidy application window predict packet は am_application_round の"
    "過去 cycle から月分布 mode を出した descriptive forecast 候補です。"
    "次回 round の実際の公示時期は所管官庁が決定するため、Jグランツ / "
    "各自治体公報の一次確認が必須。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_application_round"):
        return

    rounds_by_pgm: dict[str, list[dict[str, Any]]] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT program_entity_id, round_label, application_open_date, "
            "       application_close_date, announced_date, status, source_url "
            "  FROM am_application_round "
            " ORDER BY program_entity_id, announced_date DESC"
        ):
            pid = str(r["program_entity_id"] or "")
            if not pid:
                continue
            rounds_by_pgm.setdefault(pid, []).append(dict(r))

    for emitted, (pid, rounds) in enumerate(rounds_by_pgm.items()):
        recent = rounds[: PER_AXIS_RECORD_CAP * 2]
        # mode of open-month
        month_count: dict[str, int] = {}
        for d in recent:
            v = d.get("application_open_date")
            if isinstance(v, str) and len(v) >= 7:
                mm = v[5:7]
                month_count[mm] = month_count.get(mm, 0) + 1
        predicted_mode = ""
        if month_count:
            predicted_mode = max(month_count.items(), key=lambda kv: kv[1])[0]
        record = {
            "program_entity_id": pid,
            "recent_rounds": recent[:PER_AXIS_RECORD_CAP],
            "open_month_distribution": month_count,
            "predicted_open_month_mode": predicted_mode,
            "round_count": len(rounds),
        }
        if recent:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pid = str(row.get("program_entity_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pid)}"
    rounds = list(row.get("recent_rounds", []))
    rows_in_packet = len(rounds)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "forecast は過去 cycle の月分布 mode のみ。実際の公示は所管官庁次第",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該制度で過去 round 観測無し",
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
        "subject": {"kind": "program_entity", "id": pid},
        "program_entity_id": pid,
        "recent_rounds": rounds,
        "open_month_distribution": row.get("open_month_distribution", {}),
        "predicted_open_month_mode": str(row.get("predicted_open_month_mode") or ""),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pid, "program_entity_id": pid},
        metrics={
            "recent_round_count": rows_in_packet,
            "total_round_count": int(row.get("round_count") or 0),
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
