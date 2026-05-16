#!/usr/bin/env python3
"""Generate ``local_government_subsidy_aggregator_v1`` packets (Wave 53.2 #7).

自治体 subsidy aggregate packet. Filters ``programs`` where
``authority_level`` is prefectural / municipal and produces one packet per
``(prefecture × authority_level)`` cohort listing the top programs by
``coverage_score``.

Cohort
------

::

    cohort = (prefecture × authority_level)

``authority_level`` domain ``national | prefecture | municipality |
special_zone | other``.

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

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
    import sqlite3
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "local_government_subsidy_aggregator_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 local government subsidy aggregator packet は jpintel.db.programs "
    "の prefectural / municipal 制度を集計した descriptive 指標です。"
    "実際の申請可否は自治体公示の確認が必須 (行政書士法 §1の2 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if jpintel_conn is None or not table_exists(jpintel_conn, "programs"):
        return
    sql = (
        "SELECT unified_id, primary_name, prefecture, municipality, "
        "       authority_level, authority_name, program_kind, tier, "
        "       coverage_score, amount_max_man_yen, subsidy_rate, "
        "       official_url, source_url "
        "  FROM programs "
        " WHERE excluded = 0 "
        "   AND audit_quarantined = 0 "
        "   AND tier IN ('S','A','B','C') "
        "   AND authority_level IN ('prefecture','municipality','special_zone')"
    )

    agg: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in jpintel_conn.execute(sql):
        pref = normalise_token(row["prefecture"])
        level = normalise_token(row["authority_level"])
        key = (pref, level)
        bucket = agg.setdefault(key, [])
        bucket.append(
            {
                "program_unified_id": row["unified_id"],
                "primary_name": row["primary_name"],
                "municipality": row["municipality"],
                "authority_name": row["authority_name"],
                "program_kind": row["program_kind"],
                "tier": row["tier"],
                "coverage_score": (
                    float(row["coverage_score"])
                    if row["coverage_score"] is not None
                    else None
                ),
                "amount_max_man_yen": (
                    float(row["amount_max_man_yen"])
                    if row["amount_max_man_yen"] is not None
                    else None
                ),
                "subsidy_rate": (
                    float(row["subsidy_rate"])
                    if row["subsidy_rate"] is not None
                    else None
                ),
                "official_url": row["official_url"],
                "source_url": row["source_url"],
            }
        )

    for emitted, ((pref, level), programs) in enumerate(sorted(agg.items())):
        programs.sort(
            key=lambda d: (d.get("coverage_score") or 0.0),
            reverse=True,
        )
        cohort_id = f"{pref}.{level}"
        yield {
            "cohort_id": cohort_id,
            "prefecture": pref,
            "authority_level": level,
            "programs": programs[:PER_AXIS_RECORD_CAP],
            "total_in_cohort": len(programs),
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cohort_id = str(row["cohort_id"])
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    programs = list(row.get("programs", []))
    total = int(row.get("total_in_cohort", 0))

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "自治体制度は要綱・要領が頻繁に改定。最新の申請可否は"
                "自治体公示の確認が必須。"
            ),
        }
    ]
    if not programs:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "このコホートで自治体制度の観測なし — 自治体一次サイトの確認が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/index.html",
            "source_fetched_at": None,
            "publisher": "総務省 地方財政",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "total_in_cohort": total,
        "ranked_count": len(programs),
    }
    body = {
        "ranked_programs": programs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": cohort_id,
            "prefecture": row["prefecture"],
            "authority_level": row["authority_level"],
        },
        metrics=metrics,
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, len(programs)


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
