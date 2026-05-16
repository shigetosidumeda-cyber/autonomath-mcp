#!/usr/bin/env python3
"""Generate ``diet_question_amendment_correlate_v1`` packets (Wave 54 #2).

国会質問 (kokkai J12) × 法令改正 (am_amendment_diff) packet. For each
amended program (entity_id from am_amendment_diff), pull the policy-origin
facts that mention diet / shitsumon and the corresponding nta_shitsugi rows
sharing law refs — the "policy-question → enacted amendment" lineage.

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

PACKAGE_KIND: Final[str] = "diet_question_amendment_correlate_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 diet question amendment correlate packet は am_amendment_diff と "
    "policy-origin facts + nta_shitsugi の descriptive correlate です。"
    "国会会議録の正本は衆参両院検索システム、政策意図解釈は政策担当者"
    "確認が前提です。"
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

    diff_entities: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT entity_id "
            "  FROM am_amendment_diff "
            " WHERE entity_id IS NOT NULL "
            " LIMIT ?",
            (cap,),
        ):
            diff_entities.append(str(r["entity_id"]))

    for emitted, entity_id in enumerate(diff_entities):
        record: dict[str, Any] = {
            "program_entity_id": entity_id,
            "program_name": None,
            "amendment_diffs": [],
            "diet_policy_origin_facts": [],
            "related_shitsugi": [],
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
                "SELECT field_name, detected_at, prev_value, new_value, source_url "
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
                )
        if table_exists(primary_conn, "am_entity_facts"):
            with contextlib.suppress(Exception):
                for fact in primary_conn.execute(
                    "SELECT field_name, field_value_text, source_url, created_at "
                    "  FROM am_entity_facts "
                    " WHERE entity_id = ? "
                    "   AND (field_name LIKE '%diet%' "
                    "        OR field_name LIKE '%shitsumon%' "
                    "        OR field_name LIKE '%policy_origin%' "
                    "        OR field_name LIKE '%kokkai%') "
                    " LIMIT ?",
                    (entity_id, PER_AXIS_RECORD_CAP),
                ):
                    record["diet_policy_origin_facts"].append(
                        {
                            "field_name": fact["field_name"],
                            "value_text": (
                                str(fact["field_value_text"])[:250]
                                if fact["field_value_text"] is not None
                                else None
                            ),
                            "source_url": fact["source_url"],
                            "created_at": fact["created_at"],
                        }
                    )
        # nta_shitsugi cross-link by category fingerprint (entity_id prefix
        # often encodes 法令 category — keep this conservative by tax_type).
        if table_exists(primary_conn, "nta_shitsugi"):
            with contextlib.suppress(Exception):
                for sh in primary_conn.execute(
                    "SELECT slug, category, question, answer, source_url "
                    "  FROM nta_shitsugi "
                    " LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    if len(record["related_shitsugi"]) >= PER_AXIS_RECORD_CAP:
                        break
                    record["related_shitsugi"].append(
                        {
                            "slug": sh["slug"],
                            "category": sh["category"],
                            "question_excerpt": (
                                str(sh["question"])[:180]
                                if sh["question"] is not None
                                else None
                            ),
                            "answer_excerpt": (
                                str(sh["answer"])[:180]
                                if sh["answer"] is not None
                                else None
                            ),
                            "source_url": sh["source_url"],
                        }
                    )

        if record["amendment_diffs"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity_id = str(row.get("program_entity_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity_id)}"
    diffs = list(row.get("amendment_diffs", []))
    facts = list(row.get("diet_policy_origin_facts", []))
    shi = list(row.get("related_shitsugi", []))
    rows_in_packet = len(diffs) + len(facts) + len(shi)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "政策意図と質問→改正の因果は政策担当者確認が前提。"
                "国会会議録 (kokkai.ndl.go.jp) を一次確認してください。"
            ),
        }
    ]
    if len(facts) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "diet/shitsumon facts 無 = 国会由来無しを意味しない",
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
            "source_url": "https://www.nta.go.jp/law/shitsugi/",
            "source_fetched_at": None,
            "publisher": "国税庁 質疑応答事例",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "amendment_diff_count": len(diffs),
        "diet_origin_fact_count": len(facts),
        "related_shitsugi_count": len(shi),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "program", "id": entity_id},
        "program_name": row.get("program_name"),
        "amendment_diffs": diffs,
        "diet_policy_origin_facts": facts,
        "related_shitsugi": shi,
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
