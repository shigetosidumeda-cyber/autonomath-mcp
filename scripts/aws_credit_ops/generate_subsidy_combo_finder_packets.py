#!/usr/bin/env python3
"""Generate ``subsidy_combo_finder_v1`` packets (Wave 99 #5 of 10).

am_compat_matrix から program A × program B の compatible / case_by_case /
incompatible pair を集計し、subsidy_combo_finder MCP tool の事前 rollup を
packet 化する。program A 起点で top-N compatible / case_by_case pair を
greedy 列挙、incompatible 列挙は除外フィルタとして同梱。

Cohort
------
::

    cohort = program_a_id (am_compat_matrix.program_a_id)
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

PACKAGE_KIND: Final[str] = "subsidy_combo_finder_v1"

#: Top-N compatible pair cap; keeps envelope under 25 KB ceiling.
_MAX_PAIRS_PER_PACKET: Final[int] = 25

DEFAULT_DISCLAIMER: Final[str] = (
    "本 subsidy combo finder packet は am_compat_matrix の program A × program B "
    "(compatible / case_by_case / incompatible) を rollup した descriptive "
    "compatibility hint で、実際の制度併用判断は 適正化法 §17 + 各補助金交付規程 + "
    "顧問税理士 (§52) + 認定 経営革新等支援機関の一次確認が前提。inferred_only=1 "
    "の pair は heuristic で confidence ≤0.7 が多く、補助金審査での援用は不可。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_compat_matrix"):
        return

    program_a_ids: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT program_a_id "
            "  FROM am_compat_matrix "
            " WHERE visibility = 'public' "
            " ORDER BY program_a_id"
        ):
            program_a_ids.append(str(r["program_a_id"]))

    for emitted, program_a_id in enumerate(program_a_ids):
        pairs: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT program_b_id, compat_status, combined_max_yen, "
                "       rationale_short, source_url, confidence, inferred_only "
                "  FROM am_compat_matrix "
                " WHERE program_a_id = ? "
                "   AND visibility = 'public' "
                " ORDER BY (compat_status = 'compatible') DESC, "
                "          confidence DESC, "
                "          program_b_id "
                " LIMIT ?",
                (program_a_id, _MAX_PAIRS_PER_PACKET),
            ):
                pairs.append(
                    {
                        "program_b_id": str(r["program_b_id"] or ""),
                        "compat_status": str(r["compat_status"] or ""),
                        "combined_max_yen": (
                            int(r["combined_max_yen"])
                            if r["combined_max_yen"] is not None
                            else None
                        ),
                        "rationale_short": str(r["rationale_short"] or "") or None,
                        "source_url": str(r["source_url"] or "") or None,
                        "confidence": (
                            float(r["confidence"]) if r["confidence"] is not None else None
                        ),
                        "inferred_only": int(r["inferred_only"] or 0),
                    }
                )
        record = {
            "program_a_id": program_a_id,
            "pairs": pairs,
            "pair_n": len(pairs),
        }
        if len(pairs) > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    program_a_id = str(row.get("program_a_id") or "UNKNOWN")
    pairs = list(row.get("pairs") or [])
    pair_n = int(row.get("pair_n") or len(pairs))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(program_a_id)}"
    rows_in_packet = pair_n

    status_counts: dict[str, int] = {}
    for p in pairs:
        status = str(p.get("compat_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "制度併用判断は 適正化法 §17 + 各補助金交付規程 + 顧問税理士 + "
                "認定 経営革新等支援機関の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 program で compat pair 観測無し",
            }
        )
    if any(int(p.get("inferred_only") or 0) == 1 for p in pairs):
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    "inferred_only=1 の pair が含まれる、heuristic で confidence "
                    "≤0.7 が多く補助金審査の援用は不可"
                ),
            }
        )
    if rows_in_packet >= _MAX_PAIRS_PER_PACKET:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"pair >{_MAX_PAIRS_PER_PACKET} で打切、全 pair は "
                    "am_compat_matrix 直接参照が必要"
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
        "subject": {"kind": "program", "id": program_a_id},
        "program_a_id": program_a_id,
        "pairs": pairs,
        "pair_n": pair_n,
        "status_counts": status_counts,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": program_a_id, "program_a_id": program_a_id},
        metrics={"pair_n": pair_n, "compatible_n": status_counts.get("compatible", 0)},
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
