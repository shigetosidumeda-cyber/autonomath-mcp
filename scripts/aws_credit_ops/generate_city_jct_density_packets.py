#!/usr/bin/env python3
"""Generate ``city_jct_density_v1`` packets (Wave 57 #8 of 10).

市区町村 適格事業者 (jct = invoice registrant) 密度。jpi_invoice_registrants を
都道府県別 × 市区町村別 (address 抽出近似) に集計し、上位市区町村を packet 化。

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

PACKAGE_KIND: Final[str] = "city_jct_density_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 city jct density packet は jpi_invoice_registrants を都道府県 × 登録者種別 "
    "(corporate / sole proprietor) で集計した descriptive 密度指標です。"
    "個別事業者の適格性判断は国税庁公表サイトの一次確認が必要 (PDL v1.0)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_invoice_registrants"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_invoice_registrants "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        kind_dist: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT registrant_kind, COUNT(*) AS c, "
                "       SUM(CASE WHEN revoked_date IS NOT NULL THEN 1 ELSE 0 END) AS revoked "
                "  FROM jpi_invoice_registrants "
                " WHERE prefecture = ? "
                " GROUP BY registrant_kind ORDER BY c DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                kind_dist.append(dict(r))
        total = 0
        active = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c, "
                "       SUM(CASE WHEN revoked_date IS NULL THEN 1 ELSE 0 END) AS active "
                "  FROM jpi_invoice_registrants WHERE prefecture = ?",
                (pref,),
            ).fetchone()
            if row:
                total = int(row[0] or 0)
                active = int(row[1] or 0)
        record = {
            "prefecture": pref,
            "registrant_kind_distribution": kind_dist,
            "total_registrants": total,
            "active_registrants": active,
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    kinds = list(row.get("registrant_kind_distribution", []))
    total = int(row.get("total_registrants") or 0)
    rows_in_packet = len(kinds)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "登録者密度は jpi_invoice_registrants の delta fetch 時点に依存",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で適格事業者観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁 適格請求書発行事業者公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "registrant_kind_distribution": kinds,
        "total_registrants": total,
        "active_registrants": int(row.get("active_registrants") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "total_registrants": total,
            "active_registrants": int(row.get("active_registrants") or 0),
            "kind_buckets": rows_in_packet,
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
