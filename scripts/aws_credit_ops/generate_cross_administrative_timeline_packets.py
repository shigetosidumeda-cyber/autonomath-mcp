#!/usr/bin/env python3
"""Generate ``cross_administrative_timeline_v1`` packets (Wave 53.3 #8).

法人 × 行政処分 × 採択履歴 (時系列) packet. Builds a single chronologically
sorted event-log per houjin that interleaves ``am_enforcement_detail``,
``jpi_adoption_records``, and ``jpi_bids`` events. Useful for due-diligence
agents that need a single coherent timeline.

Cohort
------

::

    cohort = houjin_bangou (13-digit)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "cross_administrative_timeline_v1"
PER_AXIS_RECORD_CAP: Final[int] = 15

DEFAULT_DISCLAIMER: Final[str] = (
    "本 cross administrative timeline packet は行政処分 + 補助金採択 + 入札落札"
    "を時系列で並べた descriptive event log です。事象間の因果関係は推論"
    "していません。DD 用途では各事象の一次出典を必ず確認。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return

    cap = int(limit) if limit is not None else 100000
    sql = (
        "SELECT houjin_bangou, normalized_name, prefecture, jsic_major "
        "  FROM houjin_master "
        " WHERE houjin_bangou IS NOT NULL "
        "   AND length(houjin_bangou) = 13 "
        " ORDER BY total_received_yen DESC NULLS LAST "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        events: list[dict[str, Any]] = []
        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT issuance_date AS dt, 'enforcement' AS axis, "
                    "       enforcement_kind AS kind, "
                    "       issuing_authority AS authority, "
                    "       reason_summary AS summary, amount_yen, source_url "
                    "  FROM am_enforcement_detail "
                    " WHERE houjin_bangou = ? "
                    "   AND issuance_date IS NOT NULL "
                    " ORDER BY issuance_date DESC ",
                    (bangou,),
                ):
                    events.append(
                        {
                            "date": r["dt"],
                            "axis": "enforcement",
                            "kind": r["kind"],
                            "authority": r["authority"],
                            "summary": (
                                str(r["summary"])[:160]
                                if r["summary"] is not None
                                else None
                            ),
                            "amount_yen": int(r["amount_yen"] or 0),
                            "source_url": r["source_url"],
                        }
                    )
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT announced_at AS dt, program_name_raw, "
                    "       amount_granted_yen, program_id, source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    "   AND announced_at IS NOT NULL "
                    " ORDER BY announced_at DESC ",
                    (bangou,),
                ):
                    events.append(
                        {
                            "date": r["dt"],
                            "axis": "adoption",
                            "kind": "subsidy_granted",
                            "program_name": r["program_name_raw"],
                            "amount_yen": int(r["amount_granted_yen"] or 0),
                            "program_id": r["program_id"],
                            "source_url": r["source_url"],
                        }
                    )
        if table_exists(primary_conn, "jpi_bids"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT decision_date AS dt, bid_title, awarded_amount_yen, "
                    "       procuring_entity, ministry "
                    "  FROM jpi_bids "
                    " WHERE winner_houjin_bangou = ? "
                    "   AND decision_date IS NOT NULL "
                    " ORDER BY decision_date DESC ",
                    (bangou,),
                ):
                    events.append(
                        {
                            "date": r["dt"],
                            "axis": "bid_award",
                            "kind": "procurement_won",
                            "bid_title": (
                                str(r["bid_title"])[:120]
                                if r["bid_title"] is not None
                                else None
                            ),
                            "amount_yen": int(r["awarded_amount_yen"] or 0),
                            "procuring_entity": r["procuring_entity"],
                            "ministry": r["ministry"],
                        }
                    )
        events.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
        events = events[:PER_AXIS_RECORD_CAP]
        if not events:
            continue
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "events": events,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    events = list(row.get("events", []))
    rows_in_packet = len(events)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "事象間の因果は推論していません。DD では各 axis の一次出典を"
                "個別確認してください。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "観測 event 無し = 活動ゼロを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={bangou}",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "event_count": len(events),
        "axis_count": len({e.get("axis") for e in events}),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "events": events,
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
