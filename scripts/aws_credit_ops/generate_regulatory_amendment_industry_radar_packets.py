#!/usr/bin/env python3
"""Generate ``regulatory_amendment_industry_radar_v1`` packets (Wave 55 #7).

法令改正 (am_amendment_diff) × 業種影響 (JSIC) × 制度変更 (cross-walk
via am_amendment_snapshot effective_from) packet. For each JSIC major,
surface the most-recent amendment-snapshot transitions (effective_from)
in programs whose adopting houjin cluster in that industry. Differs from
``regulatory_change_industry_impact_v1`` (Wave 54 #9): that packet uses
am_amendment_diff (field-level diffs), this one uses am_amendment_snapshot
(versioned snapshots with effective_from cliffs).

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

PACKAGE_KIND: Final[str] = "regulatory_amendment_industry_radar_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulatory amendment industry radar packet は am_amendment_snapshot の "
    "業種別 effective_from cliffs descriptive feed です。法令改正・制度変更"
    "の正本は e-Gov 法令検索 + 各省庁発表を一次確認、業種影響評価は専門家"
    "確認が前提です (税理士法 §52 boundaries)。"
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
            "amendment_snapshots": [],
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
        program_names: list[str] = []
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
                program_names.append(str(n["program_name_raw"]))
        if not program_names:
            yield record
            if limit is not None and (emitted + 1) >= limit:
                return
            continue
        ent_ids: set[str] = set()
        for pname in program_names[:20]:
            with contextlib.suppress(Exception):
                for ent in primary_conn.execute(
                    "SELECT canonical_id FROM am_entities "
                    " WHERE record_kind = 'program' "
                    "   AND primary_name LIKE ? "
                    " LIMIT 5",
                    (f"%{pname[:8]}%",),
                ):
                    ent_ids.add(str(ent["canonical_id"]))
        if not ent_ids or not table_exists(primary_conn, "am_amendment_snapshot"):
            yield record
            if limit is not None and (emitted + 1) >= limit:
                return
            continue
        ent_list = list(ent_ids)[:30]
        placeholders = ",".join("?" * len(ent_list))
        with contextlib.suppress(Exception):
            for s in primary_conn.execute(
                "SELECT entity_id, version_seq, observed_at, effective_from, "
                "       effective_until, amount_max_yen, subsidy_rate_max, "
                "       source_url "
                "  FROM am_amendment_snapshot "
                f" WHERE entity_id IN ({placeholders}) "
                "   AND effective_from IS NOT NULL "
                " ORDER BY effective_from DESC "
                " LIMIT ?",
                (*ent_list, PER_AXIS_RECORD_CAP * 2),
            ):
                if len(record["amendment_snapshots"]) >= PER_AXIS_RECORD_CAP:
                    break
                record["amendment_snapshots"].append(
                    {
                        "program_entity_id": s["entity_id"],
                        "version_seq": int(s["version_seq"] or 0),
                        "observed_at": s["observed_at"],
                        "effective_from": s["effective_from"],
                        "effective_until": s["effective_until"],
                        "amount_max_yen": (
                            int(s["amount_max_yen"])
                            if s["amount_max_yen"] is not None
                            else None
                        ),
                        "subsidy_rate_max": s["subsidy_rate_max"],
                        "source_url": s["source_url"],
                    }
                )

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    snaps = list(row.get("amendment_snapshots", []))
    rows_in_packet = len(snaps)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "法令改正・制度変更の正本は e-Gov 法令検索 + 各省庁発表 — "
                "本 packet は am_amendment_snapshot の effective_from cliffs を "
                "descriptive radar として束ねたものです。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "業種クラスタ × 制度変更 該当無 — 影響無を意味しない",
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
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "amendment_snapshot_count": len(snaps),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": row.get("jsic_name_ja"),
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "amendment_snapshots": snaps,
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
