#!/usr/bin/env python3
"""Generate ``succession_program_matching_v1`` packets (Wave 53.2 #3).

事業承継 program matcher. Filters jpintel ``programs`` for the 事業承継 /
M&A subdomain (keyword + program_kind heuristics) and produces one packet
per ``(prefecture × authority_level)`` cohort.

Cohort
------

::

    cohort = (prefecture × authority_level)

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

PACKAGE_KIND: Final[str] = "succession_program_matching_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

SUCCESSION_KEYWORDS: Final[tuple[str, ...]] = (
    "事業承継",
    "事業継承",
    "後継者",
    "M&A",
    "経営承継",
    "事業引継ぎ",
    "事業引き継ぎ",
    "親族承継",
    "第三者承継",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 succession program matching packet は jpintel.db.programs を"
    "事業承継 keyword 集合で抽出した descriptive 指標です。承継スキーム"
    "選定・税務処理・株式評価は税理士・公認会計士・弁護士の確認が必須 "
    "(税理士法 §52 / 司法書士法 §3 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if jpintel_conn is None or not table_exists(jpintel_conn, "programs"):
        return
    like_clauses = " OR ".join(
        ["primary_name LIKE ?"] * len(SUCCESSION_KEYWORDS)
    )
    like_params = [f"%{kw}%" for kw in SUCCESSION_KEYWORDS]
    sql = (
        "SELECT unified_id, primary_name, prefecture, authority_level, "
        "       authority_name, program_kind, tier, coverage_score, "
        "       amount_max_man_yen, subsidy_rate, official_url, source_url "
        "  FROM programs "
        " WHERE excluded = 0 "
        "   AND audit_quarantined = 0 "
        "   AND tier IN ('S','A','B','C') "
        f"  AND ({like_clauses})"
    )

    agg: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in jpintel_conn.execute(sql, like_params):
        pref = normalise_token(row["prefecture"])
        level = normalise_token(row["authority_level"])
        key = (pref, level)
        bucket = agg.setdefault(key, [])
        bucket.append(
            {
                "program_unified_id": row["unified_id"],
                "primary_name": row["primary_name"],
                "program_kind": row["program_kind"],
                "tier": row["tier"],
                "authority_name": row["authority_name"],
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
                "承継スキーム・株式評価・税務処理は税理士・会計士・弁護士"
                "の確認が必須 (税理士法 §52 / 司法書士法 §3)。"
            ),
        }
    ]
    if not programs:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "このコホートで承継系制度の観測なし — 一次官公庁公示の確認が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 事業承継",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.smrj.go.jp/sme/regional/successor/",
            "source_fetched_at": None,
            "publisher": "中小企業基盤整備機構 後継者人材バンク",
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
