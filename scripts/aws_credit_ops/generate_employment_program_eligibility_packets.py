#!/usr/bin/env python3
"""Generate ``employment_program_eligibility_v1`` packets (Wave 58 #7 of 10).

雇用 × 制度適格。jpi_programs を keyword で 雇用調整 / 雇用安定 / 助成金 系に
filter し、各都道府県の雇用関連 program inventory を packet 化。

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

PACKAGE_KIND: Final[str] = "employment_program_eligibility_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 employment program eligibility packet は jpi_programs を 雇用 keyword で"
    "filter した descriptive 適格性 hint です。実際の雇用調整助成金等の申請判断は"
    "ハローワーク + 社労士の専門判断が必要 (社労士法 boundaries)。"
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
        progs: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT unified_id, primary_name, authority_level, authority_name, "
                "       amount_max_man_yen, official_url, tier "
                "  FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? "
                "   AND ( primary_name LIKE '%雇用%' OR primary_name LIKE '%人材%' "
                "         OR primary_name LIKE '%助成金%' OR primary_name LIKE '%採用%' "
                "         OR primary_name LIKE '%キャリア%' )"
                " ORDER BY tier LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                progs.append(dict(r))
        record = {
            "prefecture": pref,
            "employment_programs": progs,
            "program_count": len(progs),
        }
        if progs:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    progs = list(row.get("employment_programs", []))
    rows_in_packet = len(progs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "雇用関連助成金の申請判断は社労士確認が必要 (社労士法 boundaries)"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で雇用関連 program 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.mhlw.go.jp/",
            "source_fetched_at": None,
            "publisher": "厚生労働省",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.hellowork.mhlw.go.jp/",
            "source_fetched_at": None,
            "publisher": "ハローワーク",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "employment_programs": progs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"program_count": rows_in_packet},
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
