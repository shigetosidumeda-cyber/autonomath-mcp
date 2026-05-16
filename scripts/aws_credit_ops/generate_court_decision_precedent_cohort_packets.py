"""Generate ``court_decision_precedent_cohort_v1`` packets (Wave 98 #7 of 10).

case_type (am_court_decisions_v2.case_type ∈ {tax / admin / corporate / ip /
labor / civil / criminal / other}) ごとに、precedent_weight / court_level /
related_law_ids_json で cohort 集計し、descriptive court decision precedent
cohort indicator として packet 化する。実際の判例適用可否 / 拘束力判断 /
事案当てはめは 弁護士 + 司法書士 (簡裁代理) + 顧問税理士 (税務) の一次
確認が前提 (弁護士法 §72、司法書士法 §3、税理士法 §52)。

Cohort
------
::

    cohort = case_type (tax / admin / corporate / ip / labor / civil /
             criminal / other)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "court_decision_precedent_cohort_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 court decision precedent cohort packet は am_court_decisions_v2 を "
    "case_type 別に集計した descriptive precedent cohort で、実際の判例適用 "
    "可否 / 拘束力判断 / 事案当てはめは 弁護士 + 司法書士 (簡裁代理) + "
    "顧問税理士 (税務) の一次確認が前提です (弁護士法 §72、司法書士法 §3、"
    "税理士法 §52)。"
)

_CASE_TYPES: Final[tuple[str, ...]] = (
    "tax",
    "admin",
    "corporate",
    "ip",
    "labor",
    "civil",
    "criminal",
    "other",
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_court_decisions_v2"):
        return

    for emitted, case_type in enumerate(_CASE_TYPES):
        case_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n   FROM am_court_decisions_v2  WHERE case_type = ?",
                (case_type,),
            ).fetchone()
            if row:
                case_n = int(row["n"] or 0)

        # Court-level breakdown (canonical: supreme / high / district /
        # summary / family).
        court_level_counts: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT court_level_canonical, COUNT(*) AS n "
                "  FROM am_court_decisions_v2 "
                " WHERE case_type = ? "
                " GROUP BY court_level_canonical",
                (case_type,),
            ):
                court_level_counts[str(r["court_level_canonical"] or "unknown")] = int(r["n"] or 0)

        # Precedent weight breakdown (binding / persuasive /
        # informational).
        precedent_weight_counts: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT precedent_weight, COUNT(*) AS n "
                "  FROM am_court_decisions_v2 "
                " WHERE case_type = ? "
                " GROUP BY precedent_weight",
                (case_type,),
            ):
                precedent_weight_counts[str(r["precedent_weight"] or "unknown")] = int(r["n"] or 0)

        # Sample of related_law_ids_json (most-referenced 法令 distinct
        # canonical ids, top 20).
        record = {
            "case_type": case_type,
            "case_n": case_n,
            "court_level_counts": court_level_counts,
            "precedent_weight_counts": precedent_weight_counts,
        }
        if case_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    case_type = str(row.get("case_type") or "UNKNOWN")
    case_n = int(row.get("case_n") or 0)
    court_level_counts = dict(row.get("court_level_counts") or {})
    precedent_weight_counts = dict(row.get("precedent_weight_counts") or {})
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(case_type)}"
    rows_in_packet = case_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "判例適用可否 / 拘束力判断 / 事案当てはめは 弁護士 + "
                "司法書士 (簡裁代理) + 顧問税理士 (税務) の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 case_type で court decision 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.courts.go.jp/app/hanrei_jp/search1",
            "source_fetched_at": None,
            "publisher": "裁判所 裁判例検索",
            "license": "gov_standard",
        },
        {
            "source_url": "https://kuzira.ndl.go.jp/",
            "source_fetched_at": None,
            "publisher": "国立国会図書館 NDL Search",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "case_type", "id": case_type},
        "case_type": case_type,
        "case_n": case_n,
        "court_level_counts": court_level_counts,
        "precedent_weight_counts": precedent_weight_counts,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": case_type, "case_type": case_type},
        metrics={
            "case_n": case_n,
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
