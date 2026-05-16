#!/usr/bin/env python3
"""Generate ``application_round_timeline_v1`` packets (Wave 99 #7 of 10).

am_application_round を program (program_entity_id) 単位に集計し、
申請開始 / 締切 / 採択発表 / 交付開始の round cadence (rolling timeline) を
packet 化する。Wave 22 の `forecast_program_renewal` の入力として、program の
過去 round 間隔 + 開閉 status をペイロードとして提供する。

Cohort
------
::

    cohort = program_entity_id (am_application_round.program_entity_id)
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

PACKAGE_KIND: Final[str] = "application_round_timeline_v1"

#: Per-packet round cap to stay under MAX_PACKET_BYTES (25 KB).
_MAX_ROUNDS_PER_PACKET: Final[int] = 40

DEFAULT_DISCLAIMER: Final[str] = (
    "本 application round timeline packet は am_application_round を program "
    "単位で rollup した descriptive cadence で、次期 round 開催可否や締切は "
    "**所管省庁の公示が一次情報**。申請可否 / 締切影響の最終判断は 認定 経営"
    "革新等支援機関 + 顧問税理士 (§52) + 行政書士 (§1の2) の一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_application_round"):
        return

    program_ids: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT program_entity_id "
            "  FROM am_application_round "
            " ORDER BY program_entity_id"
        ):
            program_ids.append(str(r["program_entity_id"]))

    for emitted, program_id in enumerate(program_ids):
        rounds: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT round_label, round_seq, application_open_date, "
                "       application_close_date, announced_date, "
                "       disbursement_start_date, budget_yen, status, source_url "
                "  FROM am_application_round "
                " WHERE program_entity_id = ? "
                " ORDER BY COALESCE(application_open_date, '') DESC, "
                "          COALESCE(round_seq, 0) DESC "
                " LIMIT ?",
                (program_id, _MAX_ROUNDS_PER_PACKET),
            ):
                rounds.append(
                    {
                        "round_label": str(r["round_label"] or ""),
                        "round_seq": int(r["round_seq"]) if r["round_seq"] is not None else None,
                        "application_open_date": str(r["application_open_date"] or "") or None,
                        "application_close_date": str(r["application_close_date"] or "") or None,
                        "announced_date": str(r["announced_date"] or "") or None,
                        "disbursement_start_date": str(r["disbursement_start_date"] or "") or None,
                        "budget_yen": (
                            int(r["budget_yen"]) if r["budget_yen"] is not None else None
                        ),
                        "status": str(r["status"] or "") or None,
                        "source_url": str(r["source_url"] or "") or None,
                    }
                )
        if not rounds:
            continue
        status_counts: dict[str, int] = {}
        for rd in rounds:
            st = str(rd.get("status") or "unknown")
            status_counts[st] = status_counts.get(st, 0) + 1
        record = {
            "program_entity_id": program_id,
            "rounds": rounds,
            "round_n": len(rounds),
            "status_counts": status_counts,
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    program_id = str(row.get("program_entity_id") or "UNKNOWN")
    rounds = list(row.get("rounds") or [])
    round_n = int(row.get("round_n") or len(rounds))
    status_counts = dict(row.get("status_counts") or {})
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(program_id)}"
    rows_in_packet = round_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "次期 round 開催可否 / 締切 / 申請可否の最終判断は 所管省庁公示 + "
                "認定 経営革新等支援機関 + 顧問税理士 + 行政書士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 program で application round 観測無し",
            }
        )
    if rows_in_packet >= _MAX_ROUNDS_PER_PACKET:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"round >{_MAX_ROUNDS_PER_PACKET} で打切、全 round は "
                    "am_application_round 直接参照が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.chusho.meti.go.jp/keiei/kakushin/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 経営革新等支援機関",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/",
            "source_fetched_at": None,
            "publisher": "経済産業省",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "program_entity", "id": program_id},
        "program_entity_id": program_id,
        "rounds": rounds,
        "round_n": round_n,
        "status_counts": status_counts,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": program_id, "program_entity_id": program_id},
        metrics={
            "round_n": round_n,
            "open_n": int(status_counts.get("open", 0)),
            "upcoming_n": int(status_counts.get("upcoming", 0)),
            "closed_n": int(status_counts.get("closed", 0)),
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
