#!/usr/bin/env python3
"""Generate ``prefecture_environmental_compliance_v1`` packets (Wave 57 #10 of 10).

都道府県別 環境 compliance score。jpi_programs (subject_areas ⊇ '環境') +
jpi_court_decisions (subject_area LIKE '%環境%') + jpi_enforcement_cases (
legal_basis LIKE '%環境%') を都道府県別に集計し、active compliance signal を出す。

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

PACKAGE_KIND: Final[str] = "prefecture_environmental_compliance_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 prefecture environmental compliance packet は jpi_programs + "
    "jpi_court_decisions + jpi_enforcement_cases を都道府県 × 環境 keyword で"
    "集計した descriptive compliance signal です。実際の compliance 判断は"
    "環境省 + 各自治体公報の一次確認が必須。"
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
        env_programs = 0
        env_decisions = 0
        env_enforcement = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? "
                "   AND (primary_name LIKE '%環境%' OR primary_name LIKE '%GX%' "
                "        OR primary_name LIKE '%省エネ%' OR primary_name LIKE '%脱炭素%' "
                "        OR primary_name LIKE '%再生可能%')",
                (pref,),
            ).fetchone()
            if row:
                env_programs = int(row[0] or 0)
        if table_exists(primary_conn, "jpi_court_decisions"):
            with contextlib.suppress(Exception):
                row = primary_conn.execute(
                    "SELECT COUNT(*) AS c FROM jpi_court_decisions "
                    " WHERE court LIKE ? AND ( subject_area LIKE '%環境%' "
                    "    OR parties_involved LIKE '%環境%' )",
                    (f"%{pref}%",),
                ).fetchone()
                if row:
                    env_decisions = int(row[0] or 0)
        if table_exists(primary_conn, "jpi_enforcement_cases"):
            with contextlib.suppress(Exception):
                row = primary_conn.execute(
                    "SELECT COUNT(*) AS c FROM jpi_enforcement_cases "
                    " WHERE prefecture = ? "
                    "   AND ( legal_basis LIKE '%環境%' OR reason_excerpt LIKE '%環境%' )",
                    (pref,),
                ).fetchone()
                if row:
                    env_enforcement = int(row[0] or 0)
        # Higher programs + court rulings + enforcement actions = compliance footprint
        score = env_programs * 1 + env_decisions * 2 + env_enforcement * 2
        record = {
            "prefecture": pref,
            "env_programs": env_programs,
            "env_decisions": env_decisions,
            "env_enforcement": env_enforcement,
            "compliance_score": score,
        }
        if score > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    score = int(row.get("compliance_score") or 0)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "compliance signal は env keyword 集計のみ。実際の compliance 判断は"
                "環境省 + 各自治体公報の一次確認が必須"
            ),
        }
    ]
    if score == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で環境 compliance signal 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.env.go.jp/",
            "source_fetched_at": None,
            "publisher": "環境省",
            "license": "gov_standard",
        },
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
        "env_programs": int(row.get("env_programs") or 0),
        "env_decisions": int(row.get("env_decisions") or 0),
        "env_enforcement": int(row.get("env_enforcement") or 0),
        "compliance_score": score,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"compliance_score": score},
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, max(score, 1)


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
