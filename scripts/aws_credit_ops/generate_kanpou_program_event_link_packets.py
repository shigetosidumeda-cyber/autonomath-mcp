#!/usr/bin/env python3
"""Generate ``kanpou_program_event_link_v1`` packets (Wave 54 #4).

官報 (J08) × 制度 (programs) packet. Per program-entity, surface the
amendment-diff events that overlap with kanpou-publishable categories
(name / amount / target). The cohort answers "did this program receive
a kanpou-style 公示 in the last 12 months?".

Cohort
------

::

    cohort = program_entity_id

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

PACKAGE_KIND: Final[str] = "kanpou_program_event_link_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

# 官報公示 likely-publishable diff fields.
_KANPOU_RELEVANT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "amount_max_yen",
        "subsidy_rate_max",
        "program.subsidy_rate",
        "program.target_entity",
        "eligibility_text",
        "program.prerequisite",
        "target_set_json",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 kanpou program event link packet は am_amendment_diff の "
    "公示-relevant 軸を制度別に紐付けた descriptive feed です。"
    "実際の公示日時は官報 (国立印刷局) を一次確認してください。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return
    cap = int(limit) if limit is not None else 50000

    # Pull entities that have at least one kanpou-relevant field, sorted
    # by recency of that field. This makes the packet set practically
    # useful — agents looking for "published-style" events get them.
    entities: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT entity_id, MAX(detected_at) AS recent_at "
            "  FROM am_amendment_diff "
            " WHERE entity_id IS NOT NULL "
            "   AND field_name IN ("
            "     'amount_max_yen','subsidy_rate_max','program.subsidy_rate',"
            "     'program.target_entity','eligibility_text',"
            "     'program.prerequisite','target_set_json'"
            "   ) "
            " GROUP BY entity_id "
            " ORDER BY recent_at DESC "
            " LIMIT ?",
            (cap,),
        ):
            entities.append(str(r["entity_id"]))

    for emitted, entity_id in enumerate(entities):
        record: dict[str, Any] = {
            "program_entity_id": entity_id,
            "program_name": None,
            "kanpou_relevant_events": [],
            "all_other_events": [],
        }
        if table_exists(primary_conn, "am_entities"):
            with contextlib.suppress(Exception):
                for ent in primary_conn.execute(
                    "SELECT primary_name FROM am_entities "
                    " WHERE canonical_id = ? LIMIT 1",
                    (entity_id,),
                ):
                    record["program_name"] = ent["primary_name"]
        with contextlib.suppress(Exception):
            for d in primary_conn.execute(
                "SELECT field_name, detected_at, prev_value, new_value, "
                "       source_url "
                "  FROM am_amendment_diff "
                " WHERE entity_id = ? "
                " ORDER BY detected_at DESC "
                " LIMIT 30",
                (entity_id,),
            ):
                row = {
                    "field_name": d["field_name"],
                    "detected_at": d["detected_at"],
                    "prev_value": (
                        str(d["prev_value"])[:120]
                        if d["prev_value"] is not None
                        else None
                    ),
                    "new_value": (
                        str(d["new_value"])[:120]
                        if d["new_value"] is not None
                        else None
                    ),
                    "source_url": d["source_url"],
                }
                if d["field_name"] in _KANPOU_RELEVANT_FIELDS:
                    if len(record["kanpou_relevant_events"]) < PER_AXIS_RECORD_CAP:
                        record["kanpou_relevant_events"].append(row)
                elif len(record["all_other_events"]) < PER_AXIS_RECORD_CAP:
                    record["all_other_events"].append(row)

        if record["kanpou_relevant_events"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity_id = str(row.get("program_entity_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity_id)}"
    kanpou_events = list(row.get("kanpou_relevant_events", []))
    other_events = list(row.get("all_other_events", []))
    rows_in_packet = len(kanpou_events) + len(other_events)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "公示日時の正本は官報 (国立印刷局)。本 packet は am_amendment_diff "
                "から公示-likely 軸を抽出した descriptive proxy です。"
            ),
        }
    ]
    if len(kanpou_events) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "公示-likely 改正シグナル無し — 官報直接確認が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://kanpou.npb.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報 (国立印刷局)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://laws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
    ]
    metrics = {
        "kanpou_relevant_count": len(kanpou_events),
        "other_event_count": len(other_events),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "program", "id": entity_id},
        "program_name": row.get("program_name"),
        "kanpou_relevant_events": kanpou_events,
        "all_other_events": other_events,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": entity_id, "program_entity_id": entity_id},
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
