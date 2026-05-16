#!/usr/bin/env python3
"""Generate ``entity_subsidy_360_v1`` packets (Wave 69 #3 of 10).

法人 × all-adoption axes. Bundle every ``jpi_adoption_records`` event for
the houjin into a single per-entity grant-history brief — across all
ministries / 補助金 programs / fiscal years.

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

PACKAGE_KIND: Final[str] = "entity_subsidy_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 15

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity subsidy 360 packet は法人 × 補助金採択履歴の descriptive "
    "rollup です。受給可否予測 / 採択戦略提案ではありません — 各 round の"
    "一次出典を必ず個別確認してください。"
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
    # Seed from jpi_adoption_records ranked — guarantees ≥1 adoption row.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, h.total_adoptions, h.total_received_yen, "
        "       COUNT(a.id) AS adopt_count "
        "  FROM jpi_adoption_records AS a "
        "  JOIN houjin_master AS h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " ORDER BY adopt_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        adoptions: list[dict[str, Any]] = []
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT program_id, program_name_raw, announced_at, "
                    "       round_label, amount_granted_yen, "
                    "       amount_project_total_yen, prefecture, "
                    "       municipality, source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY announced_at DESC LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    adoptions.append(
                        {
                            "program_id": r["program_id"],
                            "program_name": r["program_name_raw"],
                            "announced_at": r["announced_at"],
                            "round_label": r["round_label"],
                            "amount_granted_yen": int(r["amount_granted_yen"] or 0),
                            "amount_project_total_yen": int(
                                r["amount_project_total_yen"] or 0
                            ),
                            "prefecture": r["prefecture"],
                            "municipality": r["municipality"],
                            "source_url": r["source_url"],
                        }
                    )
        if not adoptions:
            continue
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "total_adoptions": int(base["total_adoptions"] or 0),
            "total_received_yen": int(base["total_received_yen"] or 0),
            "adoptions": adoptions,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    adoptions = list(row.get("adoptions", []))
    rows_in_packet = len(adoptions)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "本 packet は受給履歴の descriptive rollup。採択予測ではない。"
                "出願検討時は各 round の一次出典を個別確認。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "観測 adoption 無し = 不申請を意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "J-Grants (経産省ほか)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経産省)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "adoption_count": len(adoptions),
        "total_received_yen_in_packet": sum(
            int(a.get("amount_granted_yen") or 0) for a in adoptions
        ),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
            "total_adoptions": int(row.get("total_adoptions") or 0),
            "total_received_yen": int(row.get("total_received_yen") or 0),
        },
        "adoptions": adoptions,
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
