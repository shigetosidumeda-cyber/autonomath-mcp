#!/usr/bin/env python3
"""Generate ``diet_question_program_link_v1`` packets (Wave 53.3 #4).

国会質問 (kokkai) × 制度 (programs) policy-lineage packet. Maps each
program to recent diet-question signals via ``am_entity_facts`` (when the
fact name carries ``law.amendment_in_diet`` / ``program.policy_origin``) +
``am_amendment_diff`` field changes that align with kokkai cycles.

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

PACKAGE_KIND: Final[str] = "diet_question_program_link_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 diet question program link packet は am_entity_facts (政策起源系) と "
    "am_amendment_diff の descriptive 紐付けです。国会会議録の正本は衆参両院"
    "国会会議録検索システムを一次確認してください。政策意図の解釈は"
    "政策担当者・専門家確認が前提です。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_entities"):
        return

    # Drive packet set from programs that actually have observable change
    # signals (am_amendment_diff). Without diffs the policy-origin claim
    # collapses to no_hit_not_absence anyway.
    cap = int(limit) if limit is not None else 50000
    diff_program_ids: list[str] = []
    if table_exists(primary_conn, "am_amendment_diff"):
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT DISTINCT entity_id "
                "  FROM am_amendment_diff "
                " WHERE entity_id IS NOT NULL "
                " LIMIT ?",
                (cap,),
            ):
                diff_program_ids.append(str(r["entity_id"]))

    if not diff_program_ids:
        return

    sql = (
        "SELECT canonical_id, primary_name, source_url "
        "  FROM am_entities "
        " WHERE record_kind = 'program' "
        "   AND canonical_id IN ({placeholders}) "
        " ORDER BY canonical_id"
    ).format(placeholders=",".join("?" * len(diff_program_ids)))

    rows: list[dict[str, Any]] = [
        {
            "canonical_id": r["canonical_id"],
            "primary_name": r["primary_name"],
            "source_url": r["source_url"],
        }
        for r in primary_conn.execute(sql, diff_program_ids)
    ]
    # Backfill: programs that appear in diff but are not yet in am_entities
    # surface as descriptive shell rows so we don't lose them.
    seen_in_entities = {str(r["canonical_id"]) for r in rows}
    for entity_id in diff_program_ids:
        if entity_id not in seen_in_entities:
            rows.append(
                {
                    "canonical_id": entity_id,
                    "primary_name": None,
                    "source_url": None,
                }
            )

    for emitted, base in enumerate(rows):
        entity_id = str(base["canonical_id"])
        record: dict[str, Any] = {
            "program_entity_id": entity_id,
            "program_name": base["primary_name"],
            "program_source_url": base["source_url"],
            "policy_origin_facts": [],
            "amendment_diffs": [],
        }
        if table_exists(primary_conn, "am_entity_facts"):
            with contextlib.suppress(Exception):
                for fact in primary_conn.execute(
                    "SELECT field_name, field_value_text, source_url, created_at "
                    "  FROM am_entity_facts "
                    " WHERE entity_id = ? "
                    "   AND (field_name LIKE '%policy_origin%' "
                    "        OR field_name LIKE '%amendment_in_diet%' "
                    "        OR field_name LIKE '%diet%' "
                    "        OR field_name LIKE '%shitsumon%') "
                    " LIMIT ?",
                    (entity_id, PER_AXIS_RECORD_CAP),
                ):
                    record["policy_origin_facts"].append(
                        {
                            "field_name": fact["field_name"],
                            "value_text": (
                                str(fact["field_value_text"])[:300]
                                if fact["field_value_text"] is not None
                                else None
                            ),
                            "source_url": fact["source_url"],
                            "created_at": fact["created_at"],
                        }
                    )
        if table_exists(primary_conn, "am_amendment_diff"):
            with contextlib.suppress(Exception):
                for d in primary_conn.execute(
                    "SELECT field_name, detected_at, prev_value, new_value, "
                    "       source_url "
                    "  FROM am_amendment_diff "
                    " WHERE entity_id = ? "
                    " ORDER BY detected_at DESC "
                    " LIMIT ?",
                    (entity_id, PER_AXIS_RECORD_CAP),
                ):
                    record["amendment_diffs"].append(
                        {
                            "field_name": d["field_name"],
                            "detected_at": d["detected_at"],
                            "prev_value": (
                                str(d["prev_value"])[:150]
                                if d["prev_value"] is not None
                                else None
                            ),
                            "new_value": (
                                str(d["new_value"])[:150]
                                if d["new_value"] is not None
                                else None
                            ),
                            "source_url": d["source_url"],
                        }
                    )
        # Always yield when we have at least one amendment diff — the
        # policy-origin facts axis is honestly thin in the snapshot, but
        # the diff axis is the load-bearing one and we emit it even when
        # facts are empty so the agent still gets the lineage proxy.
        if record["amendment_diffs"] or record["policy_origin_facts"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity_id = str(row.get("program_entity_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity_id)}"
    facts = list(row.get("policy_origin_facts", []))
    diffs = list(row.get("amendment_diffs", []))
    rows_in_packet = len(facts) + len(diffs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "政策意図の解釈は政策担当者・専門家確認が前提です。"
                "国会会議録検索を一次確認してください。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "この制度に対する diet-question 連結シグナル無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://kokkai.ndl.go.jp/",
            "source_fetched_at": None,
            "publisher": "国会会議録検索システム",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.shugiin.go.jp/",
            "source_fetched_at": None,
            "publisher": "衆議院",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "policy_origin_fact_count": len(facts),
        "amendment_diff_count": len(diffs),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "program", "id": entity_id},
        "program_name": row.get("program_name"),
        "program_source_url": row.get("program_source_url"),
        "policy_origin_facts": facts,
        "amendment_diffs": diffs,
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
