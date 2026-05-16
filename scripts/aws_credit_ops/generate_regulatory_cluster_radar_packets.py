#!/usr/bin/env python3
"""Generate ``regulatory_cluster_radar_v1`` packets (Wave 55 #2).

行政処分 (am_enforcement_detail) × 法令改正 (am_amendment_diff) × 業種
(JSIC) cross-link packet. For each JSIC major, surface paired signals of
recent enforcement actions (target_name × authority × enforcement_kind)
alongside recent program amendments — descriptive proxy for "業種 X
における規制強化トレンド" radar.

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

PACKAGE_KIND: Final[str] = "regulatory_cluster_radar_v1"
PER_AXIS_RECORD_CAP: Final[int] = 6

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulatory cluster radar packet は行政処分 × 法令改正 × 業種 の "
    "descriptive cross-link です。処分・改正の正本は各処分庁公表 + e-Gov "
    "法令検索を一次確認。法規制強化判断は専門家確認が前提 (税理士法 §52 / "
    "行政書士法 §1 boundaries)。"
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
            "enforcements": [],
            "amendments": [],
        }
        # houjin_bangou set for this JSIC major
        bangou_set: set[str] = set()
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT DISTINCT houjin_bangou FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ? "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13 "
                " LIMIT 500",
                (jsic_code,),
            ):
                bangou_set.add(str(r["houjin_bangou"]))
        record["industry_houjin_count"] = len(bangou_set)
        # Match enforcement on subset of bangou (cap query parameters)
        if bangou_set and table_exists(primary_conn, "am_enforcement_detail"):
            bangou_list = list(bangou_set)[:60]
            placeholders = ",".join("?" * len(bangou_list))
            with contextlib.suppress(Exception):
                for enf in primary_conn.execute(
                    "SELECT houjin_bangou, target_name, issuance_date, "
                    "       enforcement_kind, issuing_authority, "
                    "       related_law_ref, source_url "
                    "  FROM am_enforcement_detail "
                    f" WHERE houjin_bangou IN ({placeholders}) "
                    " ORDER BY issuance_date DESC "
                    " LIMIT ?",
                    (*bangou_list, PER_AXIS_RECORD_CAP * 2),
                ):
                    if len(record["enforcements"]) >= PER_AXIS_RECORD_CAP:
                        break
                    record["enforcements"].append(
                        {
                            "houjin_bangou": enf["houjin_bangou"],
                            "target_name": enf["target_name"],
                            "issuance_date": enf["issuance_date"],
                            "enforcement_kind": enf["enforcement_kind"],
                            "issuing_authority": enf["issuing_authority"],
                            "related_law_ref": enf["related_law_ref"],
                            "source_url": enf["source_url"],
                        }
                    )
        # Sample recent program-amendment diffs from program entities that
        # adopted in this JSIC. This is the same descriptive proxy used in
        # regulatory_change_industry_impact_v1.
        if table_exists(primary_conn, "am_amendment_diff"):
            program_names: list[str] = []
            with contextlib.suppress(Exception):
                for n in primary_conn.execute(
                    "SELECT DISTINCT program_name_raw FROM jpi_adoption_records "
                    " WHERE industry_jsic_medium IS NOT NULL "
                    "   AND substr(industry_jsic_medium, 1, 1) = ? "
                    "   AND program_name_raw IS NOT NULL "
                    " LIMIT 12",
                    (jsic_code,),
                ):
                    program_names.append(str(n["program_name_raw"]))
            ent_ids: set[str] = set()
            for pname in program_names[:8]:
                with contextlib.suppress(Exception):
                    for ent in primary_conn.execute(
                        "SELECT canonical_id FROM am_entities "
                        " WHERE record_kind = 'program' "
                        "   AND primary_name LIKE ? "
                        " LIMIT 4",
                        (f"%{pname[:8]}%",),
                    ):
                        ent_ids.add(str(ent["canonical_id"]))
            if ent_ids:
                ent_list = list(ent_ids)[:30]
                placeholders2 = ",".join("?" * len(ent_list))
                with contextlib.suppress(Exception):
                    for d in primary_conn.execute(
                        "SELECT entity_id, field_name, detected_at, "
                        "       new_value, source_url "
                        "  FROM am_amendment_diff "
                        f" WHERE entity_id IN ({placeholders2}) "
                        " ORDER BY detected_at DESC "
                        " LIMIT ?",
                        (*ent_list, PER_AXIS_RECORD_CAP * 2),
                    ):
                        if len(record["amendments"]) >= PER_AXIS_RECORD_CAP:
                            break
                        record["amendments"].append(
                            {
                                "program_entity_id": d["entity_id"],
                                "field_name": d["field_name"],
                                "detected_at": d["detected_at"],
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
    enfs = list(row.get("enforcements", []))
    amds = list(row.get("amendments", []))
    rows_in_packet = len(enfs) + len(amds)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "規制強化トレンドの判定は専門家確認が前提。法令改正は "
                "e-Gov、処分は各処分庁公表を一次確認。本 packet は "
                "descriptive radar 用 cross-link です。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該業種で行政処分・改正の双方記録無 — 規制無しを意味しない",
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
        {
            "source_url": "https://www.meti.go.jp/",
            "source_fetched_at": None,
            "publisher": "経済産業省 (処分公表)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "enforcement_count": len(enfs),
        "amendment_count": len(amds),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": row.get("jsic_name_ja"),
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "enforcements": enfs,
        "amendments": amds,
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
