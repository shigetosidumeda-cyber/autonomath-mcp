#!/usr/bin/env python3
"""Generate ``license_houjin_jurisdiction_v1`` packets (Wave 58 #6 of 10).

許認可 × 法人 × 管轄。jpi_programs (program_kind LIKE '%許認可%' OR
'%license%') + jpi_houjin_master の prefecture 軸で permit 系制度の管轄 mapping。

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

PACKAGE_KIND: Final[str] = "license_houjin_jurisdiction_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 license houjin jurisdiction packet は jpi_programs から許認可系制度を"
    "都道府県 × authority で集計した descriptive 管轄指標です。実際の許認可申請は"
    "所管官庁・行政書士確認が必要 (行政書士法 §1の2 boundaries)。"
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
        permits: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT unified_id, primary_name, authority_level, authority_name, "
                "       program_kind, official_url "
                "  FROM jpi_programs "
                " WHERE excluded = 0 AND prefecture = ? "
                "   AND (program_kind LIKE '%許認可%' OR program_kind LIKE '%license%' "
                "        OR primary_name LIKE '%許可%' OR primary_name LIKE '%認可%' "
                "        OR primary_name LIKE '%許認可%' OR primary_name LIKE '%登録%' )"
                " LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                permits.append(dict(r))
        record = {
            "prefecture": pref,
            "permits": permits,
            "permit_count": len(permits),
        }
        if permits:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    permits = list(row.get("permits", []))
    rows_in_packet = len(permits)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "許認可申請は所管官庁・行政書士確認が必要 "
                "(行政書士法 §1の2 boundaries)"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で許認可系 program 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov",
            "license": "cc_by_4.0",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "permits": permits,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"permit_count": rows_in_packet},
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
