#!/usr/bin/env python3
"""Generate ``permit_renewal_calendar_v1`` packets (Wave 53.2 #6).

許認可 renewal calendar packet. Pulls ``am_application_round`` rows whose
``round_label`` looks like a renewal cycle (更新 / 再認定 / 再申請) and
groups by ``program_entity_id``. Acts as a renewal-due calendar source.

Cohort
------

::

    cohort = program_entity_id

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

PACKAGE_KIND: Final[str] = "permit_renewal_calendar_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

RENEWAL_KEYWORDS: Final[tuple[str, ...]] = (
    "更新",
    "再認定",
    "再申請",
    "再交付",
    "継続",
    "renewal",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 permit renewal calendar packet は am_application_round を許認可"
    "更新キーワードで抽出した descriptive 指標です。許認可保持の実際の"
    "更新可否・期限は所管官庁の確認が必須 (行政書士法 §1の2 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_application_round"):
        return

    like_clauses = " OR ".join(
        ["round_label LIKE ?"] * len(RENEWAL_KEYWORDS)
    )
    like_params = [f"%{kw}%" for kw in RENEWAL_KEYWORDS]
    sql = (
        "SELECT program_entity_id, round_label, round_seq, "
        "       application_open_date, application_close_date, "
        "       announced_date, disbursement_start_date, "
        "       budget_yen, status, source_url, source_fetched_at "
        "  FROM am_application_round "
        f" WHERE {like_clauses}"
    )

    agg: dict[str, list[dict[str, Any]]] = {}
    for row in primary_conn.execute(sql, like_params):
        eid = normalise_token(row["program_entity_id"])
        bucket = agg.setdefault(eid, [])
        bucket.append(
            {
                "round_label": row["round_label"],
                "round_seq": row["round_seq"],
                "application_open_date": row["application_open_date"],
                "application_close_date": row["application_close_date"],
                "announced_date": row["announced_date"],
                "disbursement_start_date": row["disbursement_start_date"],
                "budget_yen": (
                    int(row["budget_yen"])
                    if row["budget_yen"] is not None
                    else None
                ),
                "status": row["status"],
                "source_url": row["source_url"],
                "source_fetched_at": row["source_fetched_at"],
            }
        )

    for emitted, (eid, rounds) in enumerate(sorted(agg.items())):
        rounds.sort(
            key=lambda d: (d.get("application_close_date") or "9999-12-31")
        )
        yield {
            "program_entity_id": eid,
            "rounds": rounds[:PER_AXIS_RECORD_CAP],
            "total_in_cohort": len(rounds),
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    eid = normalise_token(row.get("program_entity_id"))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(eid)}"
    rounds = list(row.get("rounds", []))
    total = int(row.get("total_in_cohort", 0))

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "許認可更新の可否・期限は所管官庁の確認が必須 (行政書士法 "
                "§1の2 — 申請代理は行政書士業務)。"
            ),
        }
    ]
    if not rounds:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "更新ラウンド観測なし — 一次官公庁公示の確認が必要",
            }
        )
    if any(r.get("application_close_date") is None for r in rounds):
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "close_date 欠損 — 一次公示の確認が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov ポータル",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "total_in_cohort": total,
        "rounds_count": len(rounds),
    }
    body = {
        "renewal_rounds": rounds,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": eid,
            "program_entity_id": eid,
        },
        metrics=metrics,
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, len(rounds)


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
