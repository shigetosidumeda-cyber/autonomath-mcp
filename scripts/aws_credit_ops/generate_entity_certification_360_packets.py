#!/usr/bin/env python3
"""Generate ``entity_certification_360_v1`` packets (Wave 69 #6 of 10).

法人 × all certifications. Mirror ``am_relation`` (relation_type =
'has_authority' / 'compatible' / 'prerequisite') anchored to the
houjin's canonical_id in ``am_entities`` (record_kind = corporate_entity)
plus aggregate signals from ``jpi_adoption_records`` to extract the
program-level certification footprint.

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

PACKAGE_KIND: Final[str] = "entity_certification_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity certification 360 packet は法人と認定制度・許認可・前提条件"
    "に関する descriptive rollup です。認定取得の可否や現有性は所管官庁の"
    "一次確認が必要 (有効期限 / 取消履歴は未収録)。"
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
    # Seed from jpi_adoption_records ranked — guarantees ≥1 program_id row
    # for the certification footprint axis.
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
    has_am_entities = table_exists(primary_conn, "am_entities")
    has_am_relation = table_exists(primary_conn, "am_relation")
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        cert_rows: list[dict[str, Any]] = []

        # Resolve canonical_id from am_entities first (corporate_entity).
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
                    "SELECT relation_type, target_entity_id, target_raw, "
                    "       confidence "
                    "  FROM am_relation "
                    " WHERE source_entity_id = ? "
                    "   AND relation_type IN "
                    "       ('has_authority','compatible','prerequisite', "
                    "        'applies_to') "
                    " LIMIT ?",
                    (canonical_id, PER_AXIS_RECORD_CAP),
                ):
                    cert_rows.append(
                        {
                            "axis": str(r["relation_type"]),
                            "target_entity_id": r["target_entity_id"],
                            "target_raw": r["target_raw"],
                            "confidence": float(r["confidence"] or 0.0),
                        }
                    )

        # Adoption-derived certification footprint (program_id distinct).
        program_ids: set[str] = set()
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT DISTINCT program_id "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    "   AND program_id IS NOT NULL LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    pid = r["program_id"]
                    if pid:
                        program_ids.add(str(pid))

        if not cert_rows and not program_ids:
            continue
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "canonical_id": canonical_id,
            "certification_relations": cert_rows,
            "program_id_footprint": sorted(program_ids),
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    cert_rows = list(row.get("certification_relations") or [])
    program_ids = list(row.get("program_id_footprint") or [])
    rows_in_packet = len(cert_rows) + len(program_ids)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "認定取得の現有性 / 有効期限 / 取消履歴は所管官庁の一次"
                "確認が必要 (本 packet は relation の rollup のみ)。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "認定 relation 観測無し = 認定なしを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.chusho.meti.go.jp/",
            "source_fetched_at": None,
            "publisher": "中小企業庁ほか所管官庁",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "certification_relation_count": len(cert_rows),
        "program_id_footprint_count": len(program_ids),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "canonical_id": row.get("canonical_id"),
        "certification_relations": cert_rows,
        "program_id_footprint": program_ids,
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
