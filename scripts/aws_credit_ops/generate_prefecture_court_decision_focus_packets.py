#!/usr/bin/env python3
"""Generate ``prefecture_court_decision_focus_v1`` packets (Wave 57 #7 of 10).

都道府県別 判例 focus。jpi_court_decisions を court × decision_type × subject_area
別に集計し、各都道府県の課題焦点を packet 化。
全国データなので court 文字列から都道府県を逆引きする近似値を採用。

Cohort
------
::

    cohort = subject_area (税・労働・許認可・知財・環境・建築 等)
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

PACKAGE_KIND: Final[str] = "prefecture_court_decision_focus_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 prefecture court decision focus packet は jpi_court_decisions を subject_area "
    "× court で集計した descriptive focus 指標です。判例の適用判断は弁護士の専門"
    "判断が前提 (弁護士法 §72 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_court_decisions"):
        return
    subjects: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT subject_area FROM jpi_court_decisions "
            " WHERE subject_area IS NOT NULL AND subject_area != ''"
        ):
            subjects.append(str(r["subject_area"]))

    for emitted, subj in enumerate(subjects):
        court_dist: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT court, court_level, decision_type, COUNT(*) AS c "
                "  FROM jpi_court_decisions "
                " WHERE subject_area = ? "
                " GROUP BY court, court_level, decision_type "
                " ORDER BY c DESC LIMIT ?",
                (subj, PER_AXIS_RECORD_CAP),
            ):
                court_dist.append(dict(r))
        total = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_court_decisions "
                " WHERE subject_area = ?",
                (subj,),
            ).fetchone()
            if row:
                total = int(row[0] or 0)
        record = {
            "subject_area": subj,
            "court_distribution": court_dist,
            "total_decisions": total,
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    subj = str(row.get("subject_area") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(subj)}"
    courts = list(row.get("court_distribution", []))
    total = int(row.get("total_decisions") or 0)
    rows_in_packet = len(courts)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "判例の適用判断は弁護士の専門判断 (弁護士法 §72 boundaries)",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 subject_area で判例 focus 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.courts.go.jp/",
            "source_fetched_at": None,
            "publisher": "裁判所 (最高裁判所)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "subject_area", "id": subj},
        "subject_area": subj,
        "court_distribution": courts,
        "total_decisions": total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": subj, "subject_area": subj},
        metrics={"court_buckets": rows_in_packet, "total_decisions": total},
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
