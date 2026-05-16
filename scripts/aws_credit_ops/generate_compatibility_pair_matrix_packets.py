#!/usr/bin/env python3
"""Generate ``compatibility_pair_matrix_v1`` packets (Wave 99 #10 of 10).

am_compat_matrix から program A × program B pair を **公開承認軸 (sourced)
+ inferred 軸 (heuristic)** に切り分け、portfolio_optimize cohort 単位の
matrix 形 packet を生成する。Wave 22 portfolio composition と Wave 99
``subsidy_combo_finder_v1`` の 集合視点 (cohort-level pair density / status
mix) の two-dimensional rollup。

Cohort
------
::

    cohort = compat_status_x_origin (e.g. compatible_sourced / case_by_case_inferred)
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

PACKAGE_KIND: Final[str] = "compatibility_pair_matrix_v1"

#: Top-N example pair cap (sample, not full enumeration).
_MAX_PAIRS_PER_PACKET: Final[int] = 30

DEFAULT_DISCLAIMER: Final[str] = (
    "本 compatibility pair matrix packet は am_compat_matrix を compat_status × "
    "origin (sourced / inferred) で rollup した descriptive cohort で、補助金"
    "併用判断は 適正化法 §17 + 各補助金交付規程 + 顧問税理士 (§52) + 認定 経営"
    "革新等支援機関の一次確認が前提。inferred_only=1 pair は heuristic で "
    "confidence ≤0.7 が多く、補助金審査での援用は不可。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_compat_matrix"):
        return

    # cohort = (compat_status, origin) where origin = sourced (inferred_only=0)
    # / inferred (inferred_only=1).
    cohorts: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT compat_status, "
            "       CASE WHEN inferred_only = 0 THEN 'sourced' ELSE 'inferred' END AS origin "
            "  FROM am_compat_matrix "
            " WHERE visibility = 'public' "
            " GROUP BY compat_status, origin "
            " ORDER BY compat_status, origin"
        ):
            cohorts.append((str(r["compat_status"] or ""), str(r["origin"])))

    for emitted, (compat_status, origin) in enumerate(cohorts):
        inferred_flag = 1 if origin == "inferred" else 0
        pair_n = 0
        sum_yen = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(combined_max_yen), 0) AS amt "
                "  FROM am_compat_matrix "
                " WHERE compat_status = ? "
                "   AND inferred_only = ? "
                "   AND visibility = 'public'",
                (compat_status, inferred_flag),
            ).fetchone()
            if row:
                pair_n = int(row["n"] or 0)
                sum_yen = int(row["amt"] or 0)
        sample_pairs: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT program_a_id, program_b_id, combined_max_yen, "
                "       rationale_short, confidence, source_url "
                "  FROM am_compat_matrix "
                " WHERE compat_status = ? "
                "   AND inferred_only = ? "
                "   AND visibility = 'public' "
                " ORDER BY confidence DESC, program_a_id "
                " LIMIT ?",
                (compat_status, inferred_flag, _MAX_PAIRS_PER_PACKET),
            ):
                sample_pairs.append(
                    {
                        "program_a_id": str(r["program_a_id"] or ""),
                        "program_b_id": str(r["program_b_id"] or ""),
                        "combined_max_yen": (
                            int(r["combined_max_yen"])
                            if r["combined_max_yen"] is not None
                            else None
                        ),
                        "rationale_short": str(r["rationale_short"] or "") or None,
                        "confidence": (
                            float(r["confidence"]) if r["confidence"] is not None else None
                        ),
                        "source_url": str(r["source_url"] or "") or None,
                    }
                )
        record = {
            "compat_status": compat_status,
            "origin": origin,
            "pair_n": pair_n,
            "combined_max_yen_sum": sum_yen,
            "sample_pairs": sample_pairs,
            "sample_n": len(sample_pairs),
        }
        if pair_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    compat_status = str(row.get("compat_status") or "UNKNOWN")
    origin = str(row.get("origin") or "UNKNOWN")
    pair_n = int(row.get("pair_n") or 0)
    sum_yen = int(row.get("combined_max_yen_sum") or 0)
    sample_pairs = list(row.get("sample_pairs") or [])
    sample_n = int(row.get("sample_n") or len(sample_pairs))
    cohort_id = f"{compat_status}_{origin}"
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    rows_in_packet = pair_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "補助金併用判断は 適正化法 §17 + 各補助金交付規程 + 顧問税理士 + "
                "認定 経営革新等支援機関の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 (compat_status × origin) で pair 観測無し",
            }
        )
    if origin == "inferred":
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    "inferred_only=1 cohort は heuristic 由来、confidence ≤0.7 が多く "
                    "補助金審査での援用は不可"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://portal.monodukuri-hojo.jp/about.html",
            "source_fetched_at": None,
            "publisher": "ものづくり補助金事務局 併用ルール解説",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.chusho.meti.go.jp/keiei/kakushin/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 経営革新等支援機関",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "compat_cohort", "id": cohort_id},
        "compat_status": compat_status,
        "origin": origin,
        "pair_n": pair_n,
        "combined_max_yen_sum": sum_yen,
        "sample_pairs": sample_pairs,
        "sample_n": sample_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": cohort_id,
            "compat_status": compat_status,
            "origin": origin,
        },
        metrics={
            "pair_n": pair_n,
            "combined_max_yen_sum": sum_yen,
            "sample_n": sample_n,
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
