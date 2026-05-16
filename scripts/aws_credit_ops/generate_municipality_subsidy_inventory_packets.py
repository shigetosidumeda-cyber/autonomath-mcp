#!/usr/bin/env python3
"""Generate ``municipality_subsidy_inventory_v1`` packets (Wave 57 #2 of 10).

政令市・自治体レベル (jpi_programs の authority_level = 'municipality') の
補助金 inventory を都道府県別に集計し、主要 municipality top-N を packet 化。

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

PACKAGE_KIND: Final[str] = "municipality_subsidy_inventory_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 municipality subsidy inventory packet は jpi_programs を都道府県 × 自治体"
    "単位で集計した descriptive 在庫指標です。実際の申請可否は各自治体公報の一次"
    "確認が必須。"
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
        muni_top: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT municipality, COUNT(*) AS c, "
                "       COUNT(CASE WHEN tier = 'S' THEN 1 END) AS tier_s, "
                "       COUNT(CASE WHEN tier = 'A' THEN 1 END) AS tier_a "
                "  FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? "
                "   AND municipality IS NOT NULL AND municipality != '' "
                " GROUP BY municipality ORDER BY c DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                muni_top.append(dict(r))
        muni_total = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? "
                "   AND authority_level = 'municipality'",
                (pref,),
            ).fetchone()
            if row:
                muni_total = int(row[0] or 0)
        record = {
            "prefecture": pref,
            "municipality_top": muni_top,
            "municipality_program_total": muni_total,
            "municipality_count": len(muni_top),
        }
        if muni_top or muni_total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    munis = list(row.get("municipality_top", []))
    rows_in_packet = len(munis)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "自治体補助金 inventory は jpi_programs snapshot 時点に依存",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で municipality 補助金観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/",
            "source_fetched_at": None,
            "publisher": "総務省 地方税制度",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "municipality_top": munis,
        "municipality_program_total": int(row.get("municipality_program_total") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "municipality_count": rows_in_packet,
            "municipality_program_total": int(
                row.get("municipality_program_total") or 0
            ),
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
