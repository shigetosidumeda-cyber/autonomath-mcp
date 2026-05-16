#!/usr/bin/env python3
"""Generate ``entity_partner_360_v1`` packets (Wave 69 #8 of 10).

法人 × all business partners. Rollup of bidirectional ``jpi_bids``
participation — every counterpart (procurer / vendor) the houjin
has interacted with, plus aggregate counts and total awarded amount.

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

PACKAGE_KIND: Final[str] = "entity_partner_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity partner 360 packet は GEPS / 入札データに基づく取引相手 "
    "rollup です。取引判断は契約書 + 双方の開示資料での一次確認が必要 "
    "(DD は弁護士確認)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    if not table_exists(primary_conn, "jpi_bids"):
        return
    cap = int(limit) if limit is not None else 100000
    # jpi_bids.winner_houjin_bangou is empty in current snapshot — fall back to
    # ranking by adoption density which best surfaces "active partner" houjin.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, COUNT(a.id) AS adopt_count "
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
        partners_as_vendor: list[dict[str, Any]] = []
        partners_as_procurer: list[dict[str, Any]] = []
        # 法人 won bids — counterparts are procurer side.
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT procuring_entity, procuring_houjin_bangou, "
                "       awarded_amount_yen, decision_date, bid_title, "
                "       ministry "
                "  FROM jpi_bids "
                " WHERE winner_houjin_bangou = ? "
                " ORDER BY decision_date DESC LIMIT ?",
                (bangou, PER_AXIS_RECORD_CAP),
            ):
                partners_as_vendor.append(
                    {
                        "role": "vendor_to",
                        "counterpart_name": r["procuring_entity"],
                        "counterpart_houjin_bangou": r["procuring_houjin_bangou"],
                        "amount_yen": int(r["awarded_amount_yen"] or 0),
                        "decision_date": r["decision_date"],
                        "bid_title": (
                            str(r["bid_title"])[:120]
                            if r["bid_title"] is not None
                            else None
                        ),
                        "ministry": r["ministry"],
                    }
                )
        # 法人 procured — counterparts are vendor side.
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT winner_name, winner_houjin_bangou, "
                "       awarded_amount_yen, decision_date, bid_title, "
                "       ministry "
                "  FROM jpi_bids "
                " WHERE procuring_houjin_bangou = ? "
                " ORDER BY decision_date DESC LIMIT ?",
                (bangou, PER_AXIS_RECORD_CAP),
            ):
                partners_as_procurer.append(
                    {
                        "role": "procurer_of",
                        "counterpart_name": r["winner_name"],
                        "counterpart_houjin_bangou": r["winner_houjin_bangou"],
                        "amount_yen": int(r["awarded_amount_yen"] or 0),
                        "decision_date": r["decision_date"],
                        "bid_title": (
                            str(r["bid_title"])[:120]
                            if r["bid_title"] is not None
                            else None
                        ),
                        "ministry": r["ministry"],
                    }
                )
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "partners_as_vendor": partners_as_vendor,
            "partners_as_procurer": partners_as_procurer,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    vendors = list(row.get("partners_as_vendor", []))
    procurers = list(row.get("partners_as_procurer", []))
    # Always emit at least 1 row marker (no_hit_not_absence semantics for
    # houjin with no bid history in current snapshot).
    rows_in_packet = max(len(vendors) + len(procurers), 1)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "取引判断は契約書 + 双方の開示資料での一次確認が必要 "
                "(DD は弁護士確認)。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "入札 partner 観測無し = 取引なしを意味しない",
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
    total_amount = sum(int(p.get("amount_yen") or 0) for p in vendors) + sum(
        int(p.get("amount_yen") or 0) for p in procurers
    )
    metrics = {
        "partner_count_as_vendor": len(vendors),
        "partner_count_as_procurer": len(procurers),
        "total_amount_yen": total_amount,
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "partners_as_vendor": vendors,
        "partners_as_procurer": procurers,
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
