#!/usr/bin/env python3
"""Generate ``trustability_audit_log_v1`` packets (Wave 100 #3 of 10).

Per record_kind cohort, check whether an audit log presence signal
exists across am_validation_result + am_entity_annotation surfaces.
Emits a `trust_score` proxy combining 3 axes (validation_pass_rate,
annotation_density, baseline) along the Wave 51 funnel `Trustability`
axis (memory `feedback_agent_funnel_6_stages.md`). NO LLM.

Cohort
------
::

    cohort = record_kind (program / case_study / law / authority / ...)
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

PACKAGE_KIND: Final[str] = "trustability_audit_log_v1"

_MAX_RECORDS_PER_COHORT: Final[int] = 80

DEFAULT_DISCLAIMER: Final[str] = (
    "本 trustability audit log packet は am_validation_result + "
    "am_entity_annotation の rollup で、信頼性の descriptive proxy。"
    "Stripe metered billing の double-entry / Ed25519 attestation は "
    "別 packet kind で重畳。本 packet 単体で 公認会計士法 / 監査基準委員会 "
    "の監査基準を代替しない、Wave 51 dim O 重畳後に上書きされる。"
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

    has_validation = table_exists(primary_conn, "am_validation_result")
    has_annotation = table_exists(primary_conn, "am_entity_annotation")

    for emitted, kind in enumerate(kinds):
        records: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT entity_id, canonical_id FROM am_entities "
                " WHERE record_kind = ? "
                " ORDER BY entity_id "
                " LIMIT ?",
                (kind, _MAX_RECORDS_PER_COHORT),
            ):
                ent_id = int(r["entity_id"] or 0)
                rec = {
                    "entity_id": ent_id,
                    "canonical_id": str(r["canonical_id"] or ""),
                    "validation_pass": 0,
                    "annotation_n": 0,
                }
                if has_validation:
                    with contextlib.suppress(Exception):
                        vr = primary_conn.execute(
                            "SELECT COUNT(*) AS n FROM am_validation_result "
                            " WHERE entity_id = ? AND status = 'pass'",
                            (ent_id,),
                        ).fetchone()
                        if vr:
                            rec["validation_pass"] = int(vr["n"] or 0)
                if has_annotation:
                    with contextlib.suppress(Exception):
                        ar = primary_conn.execute(
                            "SELECT COUNT(*) AS n FROM am_entity_annotation  WHERE entity_id = ?",
                            (ent_id,),
                        ).fetchone()
                        if ar:
                            rec["annotation_n"] = int(ar["n"] or 0)
                records.append(rec)
        if not records:
            continue
        pass_rate = round(
            sum(1 for r in records if r["validation_pass"] > 0) / max(len(records), 1),
            3,
        )
        ann_density = round(sum(r["annotation_n"] for r in records) / max(len(records), 1), 2)
        # 3-axis (pass_rate 0.5, ann_density min 0.3, baseline 0.2).
        trust_score = round(pass_rate * 0.5 + min(ann_density / 5.0, 1.0) * 0.3 + 0.2, 3)
        yield {
            "record_kind": kind,
            "records": records,
            "validation_pass_rate": pass_rate,
            "annotation_density": ann_density,
            "trust_score": trust_score,
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
            "code": "professional_review_required",
            "description": (
                "trust_score は descriptive proxy、監査基準委員会の監査基準下では "
                "公認会計士 / 監査法人 の review が要"
            ),
        },
        {
            "code": "source_receipt_incomplete",
            "description": "validation_result / annotation 未登録 entity は 0 計上",
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/agent-funnel/trustability/",
            "source_fetched_at": None,
            "publisher": "jpcite docs",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "record_kind", "id": kind},
        "record_kind": kind,
        "records": records[:_MAX_RECORDS_PER_COHORT],
        "validation_pass_rate": float(row.get("validation_pass_rate") or 0.0),
        "annotation_density": float(row.get("annotation_density") or 0.0),
        "trust_score": float(row.get("trust_score") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": f"kind_{kind}", "record_kind": kind},
        metrics={
            "record_n": rows_in_packet,
            "validation_pass_rate": float(row.get("validation_pass_rate") or 0.0),
            "annotation_density": float(row.get("annotation_density") or 0.0),
            "trust_score": float(row.get("trust_score") or 0.0),
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
