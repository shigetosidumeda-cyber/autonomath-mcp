#!/usr/bin/env python3
"""Generate ``justifiability_evidence_v1`` packets (Wave 100 #2 of 10).

Per record_kind cohort, Justifiability score combining (a) citation
density from ``am_entity_facts.source_id`` rollup and (b) descriptive
proxy of evidence weight per ¥3/req call along the Wave 51 funnel
`Justifiability` axis (memory `feedback_agent_funnel_6_stages.md`).
NO LLM call.

Cohort
------
::

    cohort = record_kind (program / case_study / tax_measure / law / ...)
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

PACKAGE_KIND: Final[str] = "justifiability_evidence_v1"

_MAX_RECORDS_PER_KIND: Final[int] = 80

DEFAULT_DISCLAIMER: Final[str] = (
    "本 justifiability evidence packet は am_entity_facts.source_id × "
    "am_source.fetched_at の rollup で、citation density + freshness の "
    "descriptive proxy。Wave 51 dim O explainable_fact (Ed25519 sign) は "
    "後段で本層に重なる予定。本 packet 単体で 税理士法 §52 / 弁護士法 §72 / "
    "行政書士法 §1の2 の専門家判断を代替しない。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_entities"):
        return

    kinds: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT record_kind, COUNT(*) AS n FROM am_entities "
            " GROUP BY record_kind HAVING n > 0 ORDER BY n DESC LIMIT 12"
        ):
            kinds.append(str(r["record_kind"]))

    for emitted, kind in enumerate(kinds):
        records: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT canonical_id, COUNT(DISTINCT f.source_id) AS source_n "
                "  FROM am_entities e "
                "  LEFT JOIN am_entity_facts f ON f.entity_id = e.entity_id "
                " WHERE e.record_kind = ? "
                " GROUP BY canonical_id "
                " ORDER BY source_n DESC "
                " LIMIT ?",
                (kind, _MAX_RECORDS_PER_KIND),
            ):
                records.append(
                    {
                        "canonical_id": str(r["canonical_id"] or ""),
                        "source_n": int(r["source_n"] or 0),
                    }
                )
        if not records:
            continue
        avg_source_n = round(sum(rec["source_n"] for rec in records) / max(len(records), 1), 2)
        # Citation density proxy: avg distinct sources per record.
        justifiability_score = round(min(1.0, avg_source_n / 5.0), 3)
        yield {
            "record_kind": kind,
            "records": records,
            "avg_source_n": avg_source_n,
            "justifiability_score": justifiability_score,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    kind = str(row.get("record_kind") or "unknown")
    records = list(row.get("records") or [])
    rows_in_packet = len(records)
    package_id = f"{PACKAGE_KIND}:kind_{safe_packet_id_segment(kind)}"

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "source freshness は am_source.fetched_at に依存、未 fetch 行は "
                "freshness=NULL 扱いで score 押し下げの対象外"
            ),
        },
        {
            "code": "source_receipt_incomplete",
            "description": "source_id=NULL fact は density 計算から除外",
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/agent-funnel/justifiability/",
            "source_fetched_at": None,
            "publisher": "jpcite docs",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "record_kind", "id": kind},
        "record_kind": kind,
        "records": records[:_MAX_RECORDS_PER_KIND],
        "avg_source_n": float(row.get("avg_source_n") or 0.0),
        "justifiability_score": float(row.get("justifiability_score") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": f"kind_{kind}", "record_kind": kind},
        metrics={
            "record_n": rows_in_packet,
            "avg_source_n": float(row.get("avg_source_n") or 0.0),
            "justifiability_score": float(row.get("justifiability_score") or 0.0),
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
