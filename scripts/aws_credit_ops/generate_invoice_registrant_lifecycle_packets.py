"""Generate ``invoice_registrant_lifecycle_v1`` packets (Wave 98 #6 of 10).

都道府県 (prefecture) ごとに jpi_invoice_registrants の registration /
activity / revoked / expired lifecycle event を集計し、descriptive
invoice registrant lifecycle indicator として packet 化する。実際の
適格事業者番号有効性 / 取消理由 / 再登録可否は 国税庁 + 顧問税理士の
一次確認が前提 (消費税法 §57の2 (適格請求書発行事業者の登録))。

Cohort
------
::

    cohort = prefecture (jpi_invoice_registrants.prefecture)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "invoice_registrant_lifecycle_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 invoice registrant lifecycle packet は jpi_invoice_registrants の "
    "registration / revoked / expired lifecycle event を都道府県別に集計した "
    "descriptive proxy で、実際の適格事業者番号有効性 / 取消理由 / 再登録可否 "
    "判断は 国税庁 + 顧問税理士の一次確認が前提です (消費税法 §57の2、PDL "
    "v1.0 with attribution to NTA)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_invoice_registrants"):
        return
    prefectures: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture "
            "  FROM jpi_invoice_registrants "
            " WHERE prefecture IS NOT NULL AND prefecture <> '' "
            " ORDER BY prefecture"
        ):
            prefectures.append(str(r["prefecture"]))

    for emitted, prefecture in enumerate(prefectures):
        # 4-axis lifecycle counts per prefecture:
        # registered_n (all rows with prefecture)
        # revoked_n   (revoked_date IS NOT NULL)
        # expired_n   (expired_date IS NOT NULL)
        # active_n    (neither revoked nor expired)
        registered_n = 0
        revoked_n = 0
        expired_n = 0
        active_n = 0
        kind_counts: dict[str, int] = {}
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n   FROM jpi_invoice_registrants  WHERE prefecture = ?",
                (prefecture,),
            ).fetchone()
            if row:
                registered_n = int(row["n"] or 0)
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM jpi_invoice_registrants "
                " WHERE prefecture = ? AND revoked_date IS NOT NULL",
                (prefecture,),
            ).fetchone()
            if row:
                revoked_n = int(row["n"] or 0)
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM jpi_invoice_registrants "
                " WHERE prefecture = ? AND expired_date IS NOT NULL",
                (prefecture,),
            ).fetchone()
            if row:
                expired_n = int(row["n"] or 0)
        active_n = max(0, registered_n - revoked_n - expired_n)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT registrant_kind, COUNT(*) AS n "
                "  FROM jpi_invoice_registrants "
                " WHERE prefecture = ? "
                " GROUP BY registrant_kind",
                (prefecture,),
            ):
                kind_counts[str(r["registrant_kind"] or "unknown")] = int(r["n"] or 0)

        record = {
            "prefecture": prefecture,
            "registered_n": registered_n,
            "revoked_n": revoked_n,
            "expired_n": expired_n,
            "active_n": active_n,
            "kind_counts": kind_counts,
        }
        if registered_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    prefecture = str(row.get("prefecture") or "UNKNOWN")
    registered_n = int(row.get("registered_n") or 0)
    revoked_n = int(row.get("revoked_n") or 0)
    expired_n = int(row.get("expired_n") or 0)
    active_n = int(row.get("active_n") or 0)
    kind_counts = dict(row.get("kind_counts") or {})
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(prefecture)}"
    rows_in_packet = registered_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "適格事業者番号有効性 / 取消理由 / 再登録可否判断は "
                "国税庁 + 顧問税理士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 prefecture で invoice registrant 観測無し",
            }
        )
    known_gaps.append(
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "jpi_invoice_registrants は delta-only snapshot (13,801 rows)、"
                "monthly bulk (4M rows) 反映前は完全網羅でない可能性"
            ),
        }
    )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁 適格請求書発行事業者公表サイト",
            "license": "pdl_v1.0",
        },
        {
            "source_url": "https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice.htm",
            "source_fetched_at": None,
            "publisher": "国税庁 インボイス制度",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": prefecture},
        "prefecture": prefecture,
        "registered_n": registered_n,
        "revoked_n": revoked_n,
        "expired_n": expired_n,
        "active_n": active_n,
        "kind_counts": kind_counts,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": prefecture, "prefecture": prefecture},
        metrics={
            "registered_n": registered_n,
            "revoked_n": revoked_n,
            "expired_n": expired_n,
            "active_n": active_n,
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
