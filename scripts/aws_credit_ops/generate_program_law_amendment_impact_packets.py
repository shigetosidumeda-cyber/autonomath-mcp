#!/usr/bin/env python3
"""Generate ``program_law_amendment_impact_v1`` packets (Wave 53.2 #1).

For each amended law observed in ``am_amendment_diff``, roll up the set of
programs that cite the law via ``program_law_refs`` so an agent can quickly
ask "law L just got amended — which programs are affected?".

Cohort
------

::

    cohort = law_unified_id

Up to ``PER_AXIS_RECORD_CAP`` recent diffs + impacted programs per packet.

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB (top-N truncation).
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import contextlib
import sqlite3
import sys
from typing import TYPE_CHECKING, Any, Final

from scripts.aws_credit_ops._packet_base import (
    jpcir_envelope,
    normalise_token,
    safe_packet_id_segment,
    table_exists,
)
from scripts.aws_credit_ops._packet_runner import run_generator

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "program_law_amendment_impact_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 program_law_amendment_impact packet は am_amendment_diff × "
    "program_law_refs の cross-source roll-up です。法令改正 → 制度影響の"
    "実体判断は税理士・行政書士・所管官庁の一次確認が必須 (税理士法 §52 / "
    "行政書士法 §1の2 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return
    if jpintel_conn is None or not table_exists(jpintel_conn, "program_law_refs"):
        return

    # Build law -> programs lookup from jpintel.db.
    law_to_programs: dict[str, list[dict[str, Any]]] = {}
    with contextlib.suppress(sqlite3.Error):
        for row in jpintel_conn.execute(
            "SELECT law_unified_id, program_unified_id, ref_kind, "
            "       article_citation, source_url "
            "  FROM program_law_refs"
        ):
            lid = row["law_unified_id"]
            if not isinstance(lid, str) or not lid:
                continue
            law_to_programs.setdefault(lid, []).append(
                {
                    "program_unified_id": row["program_unified_id"],
                    "ref_kind": row["ref_kind"],
                    "article_citation": row["article_citation"],
                    "source_url": row["source_url"],
                }
            )

    # Bring program name lookup too — useful for the agent.
    program_name_lookup: dict[str, str] = {}
    with contextlib.suppress(sqlite3.Error):
        for row in jpintel_conn.execute(
            "SELECT unified_id, primary_name FROM programs WHERE excluded=0"
        ):
            uid = row["unified_id"]
            if isinstance(uid, str):
                program_name_lookup[uid] = str(row["primary_name"] or "")

    # Bring law name lookup.
    law_lookup: dict[str, dict[str, str]] = {}
    with contextlib.suppress(sqlite3.Error):
        for row in jpintel_conn.execute(
            "SELECT unified_id, law_title, law_number, last_amended_date "
            "  FROM laws"
        ):
            lid = row["unified_id"]
            if isinstance(lid, str):
                law_lookup[lid] = {
                    "law_title": str(row["law_title"] or ""),
                    "law_number": str(row["law_number"] or ""),
                    "last_amended_date": str(row["last_amended_date"] or ""),
                }

    # Build program_entity_id -> list[diff] map from am_amendment_diff. The
    # entity_id is program-keyed (e.g. ``program:03_exclusion_rules:...``);
    # we extract the trailing token segment as a soft program identifier and
    # roll up by the unified_id when it matches.
    program_diffs: dict[str, list[dict[str, Any]]] = {}
    for row in primary_conn.execute(
        "SELECT entity_id, field_name, prev_value, new_value, "
        "       detected_at, source_url "
        "  FROM am_amendment_diff "
        " ORDER BY detected_at DESC"
    ):
        eid = row["entity_id"]
        if not isinstance(eid, str) or not eid:
            continue
        bucket = program_diffs.setdefault(eid, [])
        if len(bucket) >= PER_AXIS_RECORD_CAP:
            continue
        bucket.append(
            {
                "field_name": row["field_name"],
                "prev_value": (
                    str(row["prev_value"])[:240]
                    if row["prev_value"] is not None
                    else None
                ),
                "new_value": (
                    str(row["new_value"])[:240]
                    if row["new_value"] is not None
                    else None
                ),
                "detected_at": row["detected_at"],
                "source_url": row["source_url"],
                "entity_id": eid,
            }
        )

    # Now invert program_law_refs to law -> set[program]; for each law we
    # produce a packet whose diffs are unioned across cited programs.
    agg: dict[str, dict[str, Any]] = {}
    for lid, program_links in law_to_programs.items():
        # Best-effort: try to match the program_unified_id in entity_id via
        # substring lookup (am_amendment_diff entity_id uses program names,
        # not unified_id, so this is a coverage gap declared as a known_gap
        # rather than a fail).
        diffs: list[dict[str, Any]] = []
        seen_entity: set[str] = set()
        for p in program_links:
            puid = str(p.get("program_unified_id") or "")
            if not puid:
                continue
            # heuristic: match on puid substring in entity_id.
            for eid, eid_diffs in program_diffs.items():
                if eid in seen_entity:
                    continue
                if puid in eid or eid.endswith(puid):
                    seen_entity.add(eid)
                    diffs.extend(eid_diffs)
                    if len(diffs) >= PER_AXIS_RECORD_CAP:
                        break
            if len(diffs) >= PER_AXIS_RECORD_CAP:
                break
        agg[lid] = {
            "law_unified_id": lid,
            "diffs": diffs[:PER_AXIS_RECORD_CAP],
            "impacted_programs": [
                {
                    **p,
                    "program_name": program_name_lookup.get(
                        str(p.get("program_unified_id") or ""), ""
                    ),
                }
                for p in program_links[:PER_AXIS_RECORD_CAP]
            ],
            "law_meta": law_lookup.get(lid, {}),
        }

    for emitted, _lid in enumerate(sorted(agg.keys())):
        yield agg[_lid]
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    law_unified_id = normalise_token(row.get("law_unified_id"))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(law_unified_id)}"
    diffs = list(row.get("diffs", []))
    impacted = list(row.get("impacted_programs", []))
    law_meta = dict(row.get("law_meta", {}))
    # rows_in_packet is impacted_program_count OR diff_count, whichever is
    # non-zero. We never reject a packet purely for missing diffs because
    # the law -> program map alone is already useful for the agent.
    rows_in_packet = max(len(impacted), len(diffs))

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "改正影響範囲は法解釈を含む。税理士・行政書士・所管官庁の"
                "一次確認が必須。"
            ),
        }
    ]
    if not impacted:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "本改正に紐づく制度が観測されない場合があります — "
                    "program_law_refs の網羅未完を許容。"
                ),
            }
        )
    if not diffs or not any(d.get("detected_at") for d in diffs):
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "detected_at 鮮度不明 — 改正実体は e-Gov / 官報で確認。",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://laws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索 (canonical)",
            "license": "cc_by_4.0",
        },
        {
            "source_url": "https://kanpou.npb.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報 (国立印刷局)",
            "license": "gov_standard",
        },
    ]

    metrics = {
        "diff_count": len(diffs),
        "impacted_program_count": len(impacted),
    }
    body = {
        "amendment_diffs": diffs,
        "impacted_programs": impacted,
        "law_meta": law_meta,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": law_unified_id,
            "law_unified_id": law_unified_id,
        },
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
        needs_jpintel=True,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
