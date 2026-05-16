#!/usr/bin/env python3
"""Generate ``regulatory_change_industry_impact_v1`` packets (Wave 54 #9).

法令改正 (am_amendment_diff) × 業種影響 (JSIC) packet. For each JSIC
major, sample the most-recent program amendments whose recipients
historically cluster in that industry. Surfaces "業種 X で直近影響を
受けた法令改正 N 件" descriptive feed.

Cohort
------

::

    cohort = jsic_major (A..T)

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

PACKAGE_KIND: Final[str] = "regulatory_change_industry_impact_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulatory change industry impact packet は am_amendment_diff の"
    "業種別 descriptive impact feed です。法令改正の正本は e-Gov 法令検索、"
    "業種影響評価は専門家確認が前提です (税理士法 §52 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return

    jsic_majors: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            jsic_majors.append((str(r["jsic_code"]), str(r["jsic_name_ja"] or "")))

    for emitted, (jsic_code, jsic_name) in enumerate(jsic_majors):
        record: dict[str, Any] = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "industry_houjin_count": 0,
            "industry_program_amendments": [],
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(DISTINCT houjin_bangou) AS c "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ?",
                (jsic_code,),
            ):
                record["industry_houjin_count"] = int(r["c"] or 0)
        # adoption.program_id namespace does not align with
        # am_amendment_diff.entity_id namespace in the snapshot, so we
        # cross via am_entities.primary_name fuzzy keyword overlap. The
        # packet is descriptive — exact joins are explicitly out of scope.
        program_names_for_jsic: list[str] = []
        with contextlib.suppress(Exception):
            for n in primary_conn.execute(
                "SELECT DISTINCT program_name_raw "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ? "
                "   AND program_name_raw IS NOT NULL "
                " LIMIT 25",
                (jsic_code,),
            ):
                program_names_for_jsic.append(str(n["program_name_raw"]))
        if not program_names_for_jsic:
            yield record
            if limit is not None and (emitted + 1) >= limit:
                return
            continue
        # Build matching set of entity_ids via am_entities.primary_name.
        ent_id_set: set[str] = set()
        for pname in program_names_for_jsic[:20]:
            with contextlib.suppress(Exception):
                for ent in primary_conn.execute(
                    "SELECT canonical_id FROM am_entities "
                    " WHERE record_kind = 'program' "
                    "   AND primary_name LIKE ? "
                    " LIMIT 5",
                    (f"%{pname[:8]}%",),
                ):
                    ent_id_set.add(str(ent["canonical_id"]))
        if not ent_id_set:
            yield record
            if limit is not None and (emitted + 1) >= limit:
                return
            continue
        ent_list = list(ent_id_set)[:30]
        placeholders = ",".join("?" * len(ent_list))
        amend_sql = (
            "SELECT entity_id, field_name, detected_at, prev_value, "
            "       new_value, source_url "
            "  FROM am_amendment_diff "
            f" WHERE entity_id IN ({placeholders}) "
            " ORDER BY detected_at DESC "
            " LIMIT ?"
        )
        with contextlib.suppress(Exception):
            for d in primary_conn.execute(
                amend_sql, (*ent_list, PER_AXIS_RECORD_CAP * 4)
            ):
                if (
                    len(record["industry_program_amendments"])
                    >= PER_AXIS_RECORD_CAP
                ):
                    break
                record["industry_program_amendments"].append(
                    {
                        "program_entity_id": d["entity_id"],
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

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    amends = list(row.get("industry_program_amendments", []))
    rows_in_packet = len(amends)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "業種影響評価は専門家確認が前提。法令改正の正本は e-Gov 法令"
                "検索 + 各省庁発表 — 本 packet は descriptive proxy です。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "業種クラスタ × 改正 重複なし — 影響無しを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://laws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
        {
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "industry_program_amendment_count": len(amends),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": row.get("jsic_name_ja"),
        "industry_program_amendments": amends,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
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
