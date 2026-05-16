#!/usr/bin/env python3
"""Generate ``entity_invoice_360_v1`` packets (Wave 69 #5 of 10).

法人 × invoice registrant + cross-source confirmation. Bundle NTA 適格
請求書発行事業者 公表サイト row (T number, registered_date, revoked_date,
registrant_kind) + houjin_master normalized_name + jpi_adoption_records
delta into a per-entity invoice readiness brief.

Cohort
------

::

    cohort = houjin_bangou (13-digit, canonical subject.kind = "houjin")
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

PACKAGE_KIND: Final[str] = "entity_invoice_360_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity invoice 360 packet は NTA 適格請求書発行事業者 公表サイト + "
    "houjin_master の cross-source 照合 rollup です。仕入税額控除可否の"
    "最終判定は会計士・税理士確認 (§52 / §47条の2)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    if not table_exists(primary_conn, "jpi_invoice_registrants"):
        return
    cap = int(limit) if limit is not None else 100000
    # Seed directly from jpi_invoice_registrants for guaranteed hits.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major "
        "  FROM jpi_invoice_registrants AS i "
        "  JOIN houjin_master AS h ON h.houjin_bangou = i.houjin_bangou "
        " WHERE i.houjin_bangou IS NOT NULL "
        "   AND length(i.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        invoice_row: dict[str, Any] | None = None
        if table_exists(primary_conn, "jpi_invoice_registrants"):
            with contextlib.suppress(Exception):
                row = primary_conn.execute(
                    "SELECT invoice_registration_number, normalized_name, "
                    "       registered_date, revoked_date, expired_date, "
                    "       registrant_kind, source_url, last_updated_nta "
                    "  FROM jpi_invoice_registrants "
                    " WHERE houjin_bangou = ? LIMIT 1",
                    (bangou,),
                ).fetchone()
                if row is not None:
                    invoice_row = {
                        "invoice_registration_number": row[
                            "invoice_registration_number"
                        ],
                        "registrant_kind": row["registrant_kind"],
                        "registered_date": row["registered_date"],
                        "revoked_date": row["revoked_date"],
                        "expired_date": row["expired_date"],
                        "name_normalized_in_nta": row["normalized_name"],
                        "source_url": row["source_url"],
                        "last_updated_nta": row["last_updated_nta"],
                    }
        if invoice_row is None:
            continue
        # Name agreement check between NTA invoice public file and our
        # houjin_master normalized_name.
        name_houjin = str(base["normalized_name"] or "")
        name_nta = str(invoice_row.get("name_normalized_in_nta") or "")
        cross_source = {
            "name_agreement": name_houjin == name_nta,
            "name_houjin_master": name_houjin,
            "name_nta_invoice_registrants": name_nta,
        }
        yield {
            "houjin_bangou": bangou,
            "normalized_name": name_houjin,
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "invoice_row": invoice_row,
            "cross_source": cross_source,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    invoice_row = dict(row.get("invoice_row") or {})
    cross_source = dict(row.get("cross_source") or {})
    rows_in_packet = 1 if invoice_row else 0

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "仕入税額控除可否の最終判定は会計士・税理士確認 (§52 / "
                "§47条の2)。本 packet は公表 NTA 情報の rollup のみ。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "適格請求書発行事業者 未登録 = 廃業を意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "NTA 適格請求書発行事業者 公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "has_invoice_registration": rows_in_packet == 1,
        "name_agreement": bool(cross_source.get("name_agreement")),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "invoice_row": invoice_row,
        "cross_source_check": cross_source,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": bangou, "houjin_bangou": bangou},
        metrics=metrics,
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
