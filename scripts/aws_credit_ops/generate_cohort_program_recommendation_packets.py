#!/usr/bin/env python3
"""Generate ``cohort_program_recommendation_v1`` packets (Wave 53.2 #2).

For each ``(jsic_major × prefecture × tier)`` cohort, rank programs whose
``programs`` row maps to that cohort and produce a top-N recommendation
list (descending by ``coverage_score``).

Cohort
------

::

    cohort = (jsic_major × prefecture × tier)

Tier domain ``S | A | B | C``. ``UNKNOWN`` is acceptable for the jsic_major
or prefecture leg.

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

PACKAGE_KIND: Final[str] = "cohort_program_recommendation_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 cohort program recommendation packet は jpintel.db.programs "
    "table を業種 × 地域 × tier で集計したランキングです。個別案件の"
    "適格性は所管官庁公示を一次情報として確認してください (税理士法 §52 "
    "/ 行政書士法 §1の2 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if jpintel_conn is None or not table_exists(jpintel_conn, "programs"):
        return

    agg: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in jpintel_conn.execute(
        "SELECT unified_id, primary_name, jsic_major, prefecture, tier, "
        "       coverage_score, amount_max_man_yen, subsidy_rate, "
        "       authority_level, authority_name, official_url, source_url "
        "  FROM programs "
        " WHERE excluded = 0 "
        "   AND tier IN ('S','A','B','C') "
        "   AND audit_quarantined = 0"
    ):
        jsic = normalise_token(row["jsic_major"])
        pref = normalise_token(row["prefecture"])
        tier = normalise_token(row["tier"])
        key = (jsic, pref, tier)
        bucket = agg.setdefault(key, [])
        bucket.append(
            {
                "program_unified_id": row["unified_id"],
                "primary_name": row["primary_name"],
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
                "authority_level": row["authority_level"],
                "authority_name": row["authority_name"],
                "official_url": row["official_url"],
                "source_url": row["source_url"],
            }
        )

    for emitted, ((jsic, pref, tier), programs) in enumerate(sorted(agg.items())):
        programs.sort(
            key=lambda d: (d.get("coverage_score") or 0.0),
            reverse=True,
        )
        cohort_id = f"{jsic}.{pref}.{tier}"
        yield {
            "cohort_id": cohort_id,
            "jsic_major": jsic,
            "prefecture": pref,
            "tier": tier,
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
                "ランキングは coverage_score 主軸の descriptive 指標です。"
                "実際の申請可否は所管官庁公示の確認が必須。"
            ),
        }
    ]
    if not programs:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "このコホートで観測なし — 「制度ゼロ」を意味しません。"
                ),
            }
        )
    if any((p.get("coverage_score") is None) for p in programs):
        known_gaps.append(
            {
                "code": "pricing_or_cap_unconfirmed",
                "description": "coverage_score 欠損あり — 一次情報で再確認",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.meti.go.jp/policy/mono_info_service/mono/index.html",
            "source_fetched_at": None,
            "publisher": "METI 補助金検索",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.maff.go.jp/j/supply/hozyo/index.html",
            "source_fetched_at": None,
            "publisher": "MAFF 補助金等情報",
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
            "jsic_major": row["jsic_major"],
            "prefecture": row["prefecture"],
            "tier": row["tier"],
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
