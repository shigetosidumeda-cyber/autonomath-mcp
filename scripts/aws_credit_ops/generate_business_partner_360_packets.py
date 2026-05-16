#!/usr/bin/env python3
"""Generate ``business_partner_360_v1`` packets (Wave 58 #2 of 10).

取引先 360 双方向 due diligence。jpi_bids の procuring_houjin_bangou と
winner_houjin_bangou のペアを集計し、各組合せの落札歴 + 双方向公開情報を packet
化する (両側 due diligence の bootstrap データ)。

Cohort
------
::

    cohort = houjin_bangou (procuring + winner どちらかでも)
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

PACKAGE_KIND: Final[str] = "business_partner_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 business partner 360 packet は jpi_bids の procuring × winner ペアを"
    "双方向集計した descriptive 取引履歴指標です。実際の取引判断は契約書 + "
    "両社開示資料の一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_bids"):
        return
    counterparts: dict[str, list[dict[str, Any]]] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT procuring_entity, winner_name, "
            "       awarded_amount_yen, decision_date, bid_kind, bid_title "
            "  FROM jpi_bids "
            " WHERE procuring_entity IS NOT NULL "
            "   AND procuring_entity != ''"
        ):
            d = dict(r)
            pe = str(d.get("procuring_entity") or "")
            wn = str(d.get("winner_name") or "")
            if pe:
                counterparts.setdefault(f"procurer:{pe}", []).append(d)
            if wn:
                counterparts.setdefault(f"vendor:{wn}", []).append(d)

    candidates = sorted(counterparts.items(), key=lambda kv: len(kv[1]), reverse=True)
    for emitted, (hb, bids) in enumerate(candidates):
        bids_sorted = sorted(bids, key=lambda b: b.get("decision_date") or "", reverse=True)
        top = bids_sorted[:PER_AXIS_RECORD_CAP]
        total_amount = sum(int(b.get("awarded_amount_yen") or 0) for b in bids)
        kind, _, entity_name = hb.partition(":")
        record = {
            "entity_name": entity_name,
            "entity_role": kind,
            "partner_key": hb,
            "bid_history": top,
            "total_bids": len(bids),
            "total_amount_yen": total_amount,
        }
        if bids:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    hb = str(row.get("partner_key") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(hb)}"
    bids = list(row.get("bid_history", []))
    rows_in_packet = len(bids)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "取引判断は契約書 + 両社開示資料の一次確認が必要 (DD は弁護士確認)",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該法人で双方向 bid pair 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 (GEPS)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経産省)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": str(row.get("entity_role") or "entity"), "id": hb},
        "entity_name": str(row.get("entity_name") or ""),
        "entity_role": str(row.get("entity_role") or ""),
        "bid_history": bids,
        "total_bids": int(row.get("total_bids") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": hb, "partner_key": hb},
        metrics={
            "bid_count": rows_in_packet,
            "total_bids": int(row.get("total_bids") or 0),
            "total_amount_yen": int(row.get("total_amount_yen") or 0),
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
