#!/usr/bin/env python3
"""Generate ``bid_opportunity_matching_v1`` packets (Wave 53.2 #5).

入札 matching packet. One packet per ``(prefecture × classification_code)``
cohort over the ``bids`` corpus (362 rows live as of 2026-05-07). Sorts
by upcoming ``bid_deadline``.

Cohort
------

::

    cohort = (prefecture × classification_code)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

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

PACKAGE_KIND: Final[str] = "bid_opportunity_matching_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 bid opportunity matching packet は jpintel.db.bids または "
    "autonomath.db.bids を都道府県 × 分類で集計した descriptive 指標です。"
    "落札可否・参加資格は発注機関公示の確認が必須 (会計法 / 地方自治法 "
    "boundaries)。"
)


def _open_bids_conn(
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
) -> sqlite3.Connection | None:
    """Return the connection that has the ``bids`` table populated."""

    if jpintel_conn is not None and table_exists(jpintel_conn, "bids"):
        try:
            count = jpintel_conn.execute(
                "SELECT COUNT(*) FROM bids"
            ).fetchone()[0]
        except sqlite3.Error:
            count = 0
        if count > 0:
            return jpintel_conn
    if table_exists(primary_conn, "bids"):
        return primary_conn
    return None


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    conn = _open_bids_conn(primary_conn, jpintel_conn)
    if conn is None:
        return

    sql = (
        "SELECT unified_id, bid_title, bid_kind, procuring_entity, "
        "       ministry, prefecture, announcement_date, question_deadline, "
        "       bid_deadline, decision_date, budget_ceiling_yen, "
        "       awarded_amount_yen, participant_count, classification_code, "
        "       source_url "
        "  FROM bids"
    )

    agg: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in conn.execute(sql):
        pref = normalise_token(row["prefecture"])
        cls = normalise_token(row["classification_code"])
        key = (pref, cls)
        bucket = agg.setdefault(key, [])
        bucket.append(
            {
                "bid_unified_id": row["unified_id"],
                "bid_title": row["bid_title"],
                "bid_kind": row["bid_kind"],
                "procuring_entity": row["procuring_entity"],
                "ministry": row["ministry"],
                "announcement_date": row["announcement_date"],
                "question_deadline": row["question_deadline"],
                "bid_deadline": row["bid_deadline"],
                "decision_date": row["decision_date"],
                "budget_ceiling_yen": (
                    int(row["budget_ceiling_yen"])
                    if row["budget_ceiling_yen"] is not None
                    else None
                ),
                "awarded_amount_yen": (
                    int(row["awarded_amount_yen"])
                    if row["awarded_amount_yen"] is not None
                    else None
                ),
                "participant_count": (
                    int(row["participant_count"])
                    if row["participant_count"] is not None
                    else None
                ),
                "source_url": row["source_url"],
            }
        )

    for emitted, ((pref, cls), bids) in enumerate(sorted(agg.items())):
        bids.sort(
            key=lambda d: (d.get("bid_deadline") or "9999-12-31"),
        )
        cohort_id = f"{pref}.{cls}"
        yield {
            "cohort_id": cohort_id,
            "prefecture": pref,
            "classification_code": cls,
            "bids": bids[:PER_AXIS_RECORD_CAP],
            "total_in_cohort": len(bids),
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cohort_id = str(row["cohort_id"])
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    bids = list(row.get("bids", []))
    total = int(row.get("total_in_cohort", 0))

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "落札可否・参加資格は発注機関公示の確認が必須。等級 / "
                "実績 / 所在地要件はコホート集計で表現できません。"
            ),
        }
    ]
    if not bids:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "このコホートで入札観測なし — 発注機関一次確認が必要",
            }
        )
    if any(b.get("bid_deadline") is None for b in bids):
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "bid_deadline 欠損あり — GEPS / 発注機関一次確認が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 (GEPS)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.njss.info/",
            "source_fetched_at": None,
            "publisher": "NJSS 入札情報 (canonical landing)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "total_in_cohort": total,
        "listed_count": len(bids),
    }
    body = {
        "bids": bids,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": cohort_id,
            "prefecture": row["prefecture"],
            "classification_code": row["classification_code"],
        },
        metrics=metrics,
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, len(bids)


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
