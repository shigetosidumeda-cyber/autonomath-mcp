#!/usr/bin/env python3
"""Generate ``vendor_payment_history_match_v1`` packets (Wave 58 #8 of 10).

取引先 支払履歴 match (公開部分のみ)。jpi_bids の落札履歴を vendor (winner) ×
procurer (procuring) のペアで集計し、支払履歴 proxy として packet 化する。

Cohort
------
::

    cohort = vendor houjin_bangou (winner_houjin_bangou)
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

PACKAGE_KIND: Final[str] = "vendor_payment_history_match_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 vendor payment history match packet は jpi_bids の落札履歴を公開部分のみで"
    "集計した descriptive 支払履歴 proxy です。私人間取引の支払履歴は対象外。"
    "実際の支払履歴判断は取引書類の一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_bids"):
        return
    # houjin_bangou is unpopulated in jpi_bids; iterate by winner_name fallback
    # (or procuring_entity if winner_name is also empty).
    vendors: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT COALESCE(NULLIF(winner_name, ''), procuring_entity) AS v, "
            "       COUNT(*) AS c "
            "  FROM jpi_bids "
            " WHERE (winner_name IS NOT NULL AND winner_name != '') "
            "    OR (procuring_entity IS NOT NULL AND procuring_entity != '') "
            " GROUP BY v HAVING c >= 1 ORDER BY c DESC"
        ):
            v = str(r["v"] or "")
            if v:
                vendors.append(v)

    for emitted, vendor in enumerate(vendors):
        payments: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT procuring_entity, awarded_amount_yen, decision_date, "
                "       bid_title, bid_kind "
                "  FROM jpi_bids "
                " WHERE winner_name = ? OR procuring_entity = ? "
                " ORDER BY decision_date DESC LIMIT ?",
                (vendor, vendor, PER_AXIS_RECORD_CAP),
            ):
                payments.append(dict(r))
        total_amount = 0
        unique_procurers = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COALESCE(SUM(awarded_amount_yen), 0) AS s, "
                "       COUNT(DISTINCT procuring_entity) AS d "
                "  FROM jpi_bids WHERE winner_name = ? OR procuring_entity = ?",
                (vendor, vendor),
            ).fetchone()
            if row:
                total_amount = int(row["s"] or 0)
                unique_procurers = int(row["d"] or 0)
        record = {
            "vendor_name": vendor,
            "payment_history": payments,
            "total_amount_yen": total_amount,
            "unique_procurer_count": unique_procurers,
        }
        if payments:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    vendor = str(row.get("vendor_name") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(vendor)}"
    payments = list(row.get("payment_history", []))
    rows_in_packet = len(payments)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "私人間取引は対象外、実際の支払履歴判断は取引書類の一次確認が必要",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 vendor で payment history 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 (GEPS)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "vendor_name", "id": vendor},
        "vendor_name": vendor,
        "payment_history": payments,
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
        "unique_procurer_count": int(row.get("unique_procurer_count") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": vendor, "vendor_name": vendor},
        metrics={
            "payment_count": rows_in_packet,
            "total_amount_yen": int(row.get("total_amount_yen") or 0),
            "unique_procurer_count": int(row.get("unique_procurer_count") or 0),
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
