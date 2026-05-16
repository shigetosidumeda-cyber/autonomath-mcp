#!/usr/bin/env python3
"""Generate ``entity_360_summary_v1`` packets (Wave 69 #1 of 10).

法人 × all-registries 1-call cross-source baseline. Each packet bundles
houjin_master core + adoption rollup + invoice registrant + enforcement
rollup + 採択 program list + bid count — so an AI agent only needs one
fetch instead of 6+ separate registry calls.

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

PACKAGE_KIND: Final[str] = "entity_360_summary_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity 360 summary packet は houjin × 全公開レジストリの 1-call "
    "descriptive baseline です。実体把握用途では各 axis の一次出典を必ず"
    "個別確認してください。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    cap = int(limit) if limit is not None else 100000
    # Seed from adoption density (richest cross-axis signal) — houjin_master
    # total_received_yen / total_adoptions are 0 in current snapshot.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.municipality, h.corporation_type, h.jsic_major, "
        "       h.established_date, h.total_adoptions, h.total_received_yen, "
        "       COUNT(a.id) AS adopt_count "
        "  FROM jpi_adoption_records AS a "
        "  JOIN houjin_master AS h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " ORDER BY adopt_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        axes: dict[str, Any] = {}

        if table_exists(primary_conn, "jpi_invoice_registrants"):
            with contextlib.suppress(Exception):
                row = primary_conn.execute(
                    "SELECT invoice_registration_number, registered_date, "
                    "       revoked_date, registrant_kind "
                    "  FROM jpi_invoice_registrants "
                    " WHERE houjin_bangou = ? LIMIT 1",
                    (bangou,),
                ).fetchone()
                if row is not None:
                    axes["invoice_registrant"] = {
                        "invoice_registration_number": row[
                            "invoice_registration_number"
                        ],
                        "registered_date": row["registered_date"],
                        "revoked_date": row["revoked_date"],
                        "registrant_kind": row["registrant_kind"],
                    }

        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                axes["adoption_rollup"] = {
                    "row_count": primary_conn.execute(
                        "SELECT COUNT(*) FROM jpi_adoption_records "
                        " WHERE houjin_bangou = ?",
                        (bangou,),
                    ).fetchone()[0]
                }

        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                axes["enforcement_rollup"] = {
                    "row_count": primary_conn.execute(
                        "SELECT COUNT(*) FROM am_enforcement_detail "
                        " WHERE houjin_bangou = ?",
                        (bangou,),
                    ).fetchone()[0]
                }

        if table_exists(primary_conn, "jpi_bids"):
            with contextlib.suppress(Exception):
                axes["bid_rollup"] = {
                    "row_count": primary_conn.execute(
                        "SELECT COUNT(*) FROM jpi_bids "
                        " WHERE winner_houjin_bangou = ?",
                        (bangou,),
                    ).fetchone()[0]
                }

        if not axes:
            continue
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "municipality": base["municipality"],
            "corporation_type": base["corporation_type"],
            "jsic_major": base["jsic_major"],
            "established_date": base["established_date"],
            "total_adoptions": int(base["total_adoptions"] or 0),
            "total_received_yen": int(base["total_received_yen"] or 0),
            "axes": axes,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    axes = dict(row.get("axes") or {})
    rows_in_packet = len(axes) + 1  # 1 base + per-axis rollups

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "本 packet は descriptive rollup。実取引・与信・採用判断は "
                "各 registry の一次資料を別途確認してください。"
            ),
        }
    ]
    if rows_in_packet <= 1:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "観測 axis 無し = 不在を意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={bangou}",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経産省)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "axis_count": len(axes),
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_received_yen": int(row.get("total_received_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "municipality": row.get("municipality"),
            "corporation_type": row.get("corporation_type"),
            "jsic_major": row.get("jsic_major"),
            "established_date": row.get("established_date"),
        },
        "axes": axes,
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
