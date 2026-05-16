#!/usr/bin/env python3
"""Generate ``invoice_registration_velocity_v1`` packets (Wave 56 #5 of 10).

インボイス制度の登録 (jpi_invoice_registrants) を都道府県別 × 月別の登録速度
で集計し、累積カーブと月次ピーク・直近12ヶ月推移を packet 化。

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

PACKAGE_KIND: Final[str] = "invoice_registration_velocity_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 invoice registration velocity packet は jpi_invoice_registrants の "
    "registered_date を都道府県 × 月で集計した descriptive 速度指標です。"
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
        monthly: dict[str, int] = {}
        revoked = 0
        total = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT substr(registered_date, 1, 7) AS ym, COUNT(*) AS c "
                "  FROM jpi_invoice_registrants "
                " WHERE prefecture = ? AND registered_date IS NOT NULL "
                "   AND length(registered_date) >= 7 "
                " GROUP BY ym ORDER BY ym DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                ym = str(r["ym"])
                monthly[ym] = int(r["c"] or 0)
                total += monthly[ym]
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c FROM jpi_invoice_registrants "
                " WHERE prefecture = ? AND revoked_date IS NOT NULL",
                (pref,),
            ).fetchone()
            if row:
                revoked = int(row[0] or 0)
        record = {
            "prefecture": pref,
            "monthly_registrations": monthly,
            "active_total": total,
            "revoked_total": revoked,
        }
        if total > 0 or revoked > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    monthly = dict(row.get("monthly_registrations", {}))
    total = int(row.get("active_total") or 0)
    revoked = int(row.get("revoked_total") or 0)
    rows_in_packet = len(monthly)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "登録速度は NTA bulk fetch 時点に依存。最新月は更新遅延あり",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県でインボイス登録月次データ無し",
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
        "monthly_registrations": monthly,
        "active_total": total,
        "revoked_total": revoked,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "month_count": rows_in_packet,
            "active_total": total,
            "revoked_total": revoked,
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
