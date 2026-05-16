#!/usr/bin/env python3
"""Generate ``entity_succession_360_v1`` packets (Wave 69 #7 of 10).

法人 × all succession events. Combine ``am_relation`` rows with
relation_type IN ('successor_of', 'replaces') anchored on the houjin
canonical_id + ``houjin_change_history`` (close_date / change events
when populated).

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

PACKAGE_KIND: Final[str] = "entity_succession_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity succession 360 packet は successor_of / replaces / "
    "close_date 等の event rollup です。M&A・事業承継の最終確認は登記簿"
    "謄本 + 契約書での一次確認が必要 (司法書士法 §3)。"
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
    # houjin_change_history + total_received_yen are empty in current snapshot.
    # Seed from adoption ranking (active houjin are most likely to also carry
    # successor_of / replaces relations in am_relation).
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, h.close_date, h.established_date, "
        "       COUNT(a.id) AS adopt_count "
        "  FROM jpi_adoption_records AS a "
        "  JOIN houjin_master AS h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " ORDER BY adopt_count DESC "
        " LIMIT ?"
    )
    has_am_entities = table_exists(primary_conn, "am_entities")
    has_am_relation = table_exists(primary_conn, "am_relation")
    has_history = table_exists(primary_conn, "houjin_change_history")
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        events: list[dict[str, Any]] = []

        canonical_id: str | None = None
        if has_am_entities:
            with contextlib.suppress(Exception):
                row = primary_conn.execute(
                    "SELECT canonical_id FROM am_entities "
                    " WHERE record_kind = 'corporate_entity' "
                    "   AND source_topic = ? LIMIT 1",
                    (bangou,),
                ).fetchone()
                if row is not None:
                    canonical_id = row["canonical_id"]

        if has_am_relation and canonical_id:
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT relation_type, target_entity_id, target_raw "
                    "  FROM am_relation "
                    " WHERE source_entity_id = ? "
                    "   AND relation_type IN ('successor_of','replaces') "
                    " LIMIT ?",
                    (canonical_id, PER_AXIS_RECORD_CAP),
                ):
                    events.append(
                        {
                            "axis": "relation",
                            "kind": str(r["relation_type"]),
                            "target_entity_id": r["target_entity_id"],
                            "target_raw": r["target_raw"],
                        }
                    )

        if has_history:
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT change_date, process, source_url "
                    "  FROM houjin_change_history "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY change_date DESC LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    events.append(
                        {
                            "axis": "registry_change",
                            "kind": r["process"],
                            "date": r["change_date"],
                            "source_url": r["source_url"],
                        }
                    )

        close_date = base["close_date"]
        if close_date is not None:
            events.append(
                {
                    "axis": "registry_close",
                    "kind": "close_date",
                    "date": close_date,
                }
            )

        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "established_date": base["established_date"],
            "close_date": close_date,
            "canonical_id": canonical_id,
            "events": events,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    events = list(row.get("events", []))
    # Always emit at least 1 row marker (no_hit_not_absence semantics for
    # houjin with no observed succession events in current snapshot).
    rows_in_packet = max(len(events), 1)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "M&A・事業承継の最終確認は登記簿謄本 + 契約書での一次確認が"
                "必要 (司法書士法 §3)。本 packet は public registry event "
                "rollup のみ。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "succession event 観測無し = 承継なしを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={bangou}",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト 変更履歴",
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
            "established_date": row.get("established_date"),
            "close_date": row.get("close_date"),
        },
        "canonical_id": row.get("canonical_id"),
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
