"""Generate ``subsidy_program_amendment_lineage_v1`` packets (Wave 98 #1 of 10).

制度 (program entity) ごとに am_amendment_diff の field-by-field 改正
chain (amendment lineage) を replay し、descriptive program amendment
lineage indicator として packet 化する。実際の制度適用判断 / 申請可否 /
締切影響は 各所管省庁 + 認定 経営革新等支援機関 + 顧問税理士の一次確認が
前提 (中小企業等経営強化法 / 補助金交付規程)。

Cohort
------
::

    cohort = program_entity_id (am_entities.canonical_id, record_kind='program')

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

PACKAGE_KIND: Final[str] = "subsidy_program_amendment_lineage_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 subsidy program amendment lineage packet は am_amendment_diff "
    "field-by-field 改正履歴を replay した descriptive lineage で、実際の "
    "制度適用判断 / 申請可否 / 締切影響は 各所管省庁 + 認定 経営革新等支援機関 + "
    "顧問税理士の一次確認が前提 (中小企業等経営強化法、補助金交付規程)。"
)

# Cap per-packet diff event count so envelope stays under MAX_PACKET_BYTES
# (25 KB). am_amendment_diff has 16K rows across 11K entities, mean ≈ 1.5
# events/entity, but a few entities have 50+ events; truncate.
_MAX_EVENTS_PER_PACKET: Final[int] = 40


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return
    if not table_exists(primary_conn, "am_entities"):
        return
    # Pull all program entities that have ≥1 amendment diff event.
    # JOIN here keeps the cohort universe well-defined and skips orphaned
    # diffs whose entity row was archived.
    entity_rows: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT e.canonical_id, e.primary_name "
            "  FROM am_entities e "
            "  JOIN am_amendment_diff d ON d.entity_id = e.canonical_id "
            " WHERE e.record_kind = 'program' "
            " ORDER BY e.canonical_id"
        ):
            entity_rows.append(
                (str(r["canonical_id"]), str(r["primary_name"] or ""))
            )

    for emitted, (entity_id, primary_name) in enumerate(entity_rows):
        events: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for d in primary_conn.execute(
                "SELECT field_name, prev_hash, new_hash, detected_at "
                "  FROM am_amendment_diff "
                " WHERE entity_id = ? "
                " ORDER BY detected_at DESC "
                " LIMIT ?",
                (entity_id, _MAX_EVENTS_PER_PACKET),
            ):
                events.append(
                    {
                        "field_name": str(d["field_name"]),
                        "prev_hash": (
                            str(d["prev_hash"]) if d["prev_hash"] else None
                        ),
                        "new_hash": (
                            str(d["new_hash"]) if d["new_hash"] else None
                        ),
                        "detected_at": str(d["detected_at"]),
                    }
                )
        record = {
            "entity_id": entity_id,
            "primary_name": primary_name,
            "events": events,
            "event_n": len(events),
        }
        if len(events) > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity_id = str(row.get("entity_id") or "UNKNOWN")
    primary_name = str(row.get("primary_name") or "")
    events = list(row.get("events") or [])
    event_n = int(row.get("event_n") or len(events))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity_id)}"
    rows_in_packet = event_n

    field_set = sorted({str(e.get("field_name") or "") for e in events})

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "制度適用判断 / 申請可否 / 締切影響は 各所管省庁 + "
                "認定 経営革新等支援機関 + 顧問税理士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 program entity で amendment diff 観測無し",
            }
        )
    if rows_in_packet >= _MAX_EVENTS_PER_PACKET:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"amendment event >{_MAX_EVENTS_PER_PACKET} で打切、全履歴は "
                    "am_amendment_diff 直接参照が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.chusho.meti.go.jp/keiei/kakushin/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 経営革新等支援機関",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/economy/keiei_innovation/",
            "source_fetched_at": None,
            "publisher": "経済産業省 経営革新",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "program_entity", "id": entity_id},
        "entity_id": entity_id,
        "primary_name": primary_name,
        "events": events,
        "event_n": event_n,
        "fields_touched": field_set,
        "fields_touched_n": len(field_set),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": entity_id,
            "program_entity_id": entity_id,
        },
        metrics={
            "event_n": event_n,
            "fields_touched_n": len(field_set),
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
