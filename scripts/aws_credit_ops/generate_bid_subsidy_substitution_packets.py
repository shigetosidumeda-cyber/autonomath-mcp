#!/usr/bin/env python3
"""Generate ``bid_subsidy_substitution_v1`` packets (Wave 55 #8).

入札落札 (jpi_bids) × 補助金採択 (J05) × 企業 360 (jpi_houjin_master)
3-axis substitution overview packet. For each procuring_entity in
jpi_bids, surface bid composition (kobo_subsidy / open / selective /
negotiated mix), total bid amount, and the adoption count + total amount
attributable to that ministry's program family — descriptive proxy for
"政府調達 vs 補助金 重複度" cross-link. winner_name + winner_houjin_bangou
are honest no-hit fields in the current snapshot.

Cohort
------

::

    cohort = procuring_entity (発注機関名)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "bid_subsidy_substitution_v1"
PER_AXIS_RECORD_CAP: Final[int] = 6

DEFAULT_DISCLAIMER: Final[str] = (
    "本 bid subsidy substitution packet は入札落札 × 補助金採択 × 法人 "
    "の descriptive cross-link です。入札・契約の正本は各発注機関公表 "
    "(GEPS / 自治体公報)、補助金は Jグランツを一次確認。重複度・代替"
    "性の評価は外部 advisor 判断が前提です。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_bids"):
        return

    procuring: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT procuring_entity FROM jpi_bids "
            " WHERE procuring_entity IS NOT NULL AND procuring_entity != ''"
        ):
            procuring.append(str(r["procuring_entity"]))

    for emitted, entity in enumerate(procuring):
        record: dict[str, Any] = {
            "procuring_entity": entity,
            "bid_kind_mix": [],
            "bid_count": 0,
            "bid_total_amount_yen": 0,
            "bid_samples": [],
            "subsidy_program_overlap": [],
            "subsidy_total_amount_yen": 0,
            "subsidy_total_adoptions": 0,
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(*) AS c, "
                "       COALESCE(SUM(awarded_amount_yen), 0) AS s "
                "  FROM jpi_bids WHERE procuring_entity = ?",
                (entity,),
            ):
                record["bid_count"] = int(r["c"] or 0)
                record["bid_total_amount_yen"] = int(r["s"] or 0)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT bid_kind, COUNT(*) AS c "
                "  FROM jpi_bids "
                " WHERE procuring_entity = ? "
                " GROUP BY bid_kind "
                " ORDER BY c DESC",
                (entity,),
            ):
                record["bid_kind_mix"].append(
                    {"bid_kind": r["bid_kind"], "count": int(r["c"] or 0)}
                )
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT bid_title, bid_kind, ministry, prefecture, "
                "       decision_date, awarded_amount_yen, "
                "       budget_ceiling_yen, source_url "
                "  FROM jpi_bids "
                " WHERE procuring_entity = ? "
                " ORDER BY COALESCE(decision_date, '') DESC "
                " LIMIT ?",
                (entity, PER_AXIS_RECORD_CAP),
            ):
                record["bid_samples"].append(
                    {
                        "bid_title": r["bid_title"],
                        "bid_kind": r["bid_kind"],
                        "ministry": r["ministry"],
                        "prefecture": r["prefecture"],
                        "decision_date": r["decision_date"],
                        "awarded_amount_yen": int(r["awarded_amount_yen"] or 0),
                        "budget_ceiling_yen": (
                            int(r["budget_ceiling_yen"])
                            if r["budget_ceiling_yen"] is not None
                            else None
                        ),
                        "source_url": r["source_url"],
                    }
                )
        # Coarse subsidy overlap: programs whose name contains the entity
        # ministry name as a fence (descriptive proxy).
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT COUNT(*) AS c, "
                    "       COALESCE(SUM(amount_granted_yen), 0) AS s "
                    "  FROM jpi_adoption_records "
                    " WHERE program_name_raw LIKE ?",
                    (f"%{entity[:6]}%",),
                ):
                    record["subsidy_total_adoptions"] = int(r["c"] or 0)
                    record["subsidy_total_amount_yen"] = int(r["s"] or 0)
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT program_name_raw, "
                    "       COUNT(*) AS adoptions, "
                    "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                    "  FROM jpi_adoption_records "
                    " WHERE program_name_raw LIKE ? "
                    " GROUP BY program_name_raw "
                    " ORDER BY total_amount_yen DESC "
                    " LIMIT ?",
                    (f"%{entity[:6]}%", PER_AXIS_RECORD_CAP),
                ):
                    record["subsidy_program_overlap"].append(
                        {
                            "program_name": r["program_name_raw"],
                            "adoptions": int(r["adoptions"] or 0),
                            "total_amount_yen": int(r["total_amount_yen"] or 0),
                        }
                    )

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity = str(row.get("procuring_entity") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity)}"
    kinds = list(row.get("bid_kind_mix", []))
    bid_samples = list(row.get("bid_samples", []))
    subsidy_overlap = list(row.get("subsidy_program_overlap", []))
    rows_in_packet = len(kinds) + len(bid_samples) + len(subsidy_overlap)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "入札・契約の正本は各発注機関公表 (GEPS / 自治体公報)、補助金は "
                "Jグランツを一次確認。重複度評価は外部 advisor 判断が前提。"
            ),
        },
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "winner_name + winner_houjin_bangou は jpi_bids 現スナップショット"
                "では未集計 — 落札者 × 採択法人の identity 突合は今後の精緻化対象。"
            ),
        },
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該発注機関で入札 / 補助金 cross-link 該当無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 GEPS",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁 法人番号公表",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "bid_count": int(row.get("bid_count") or 0),
        "bid_kind_mix_count": len(kinds),
        "bid_sample_count": len(bid_samples),
        "subsidy_total_adoptions": int(row.get("subsidy_total_adoptions") or 0),
        "subsidy_total_amount_yen": int(row.get("subsidy_total_amount_yen") or 0),
        "subsidy_program_overlap_count": len(subsidy_overlap),
        "bid_total_amount_yen": int(row.get("bid_total_amount_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": entity},
        "procuring_entity": entity,
        "bid_count": int(row.get("bid_count") or 0),
        "bid_total_amount_yen": int(row.get("bid_total_amount_yen") or 0),
        "bid_kind_mix": kinds,
        "bid_samples": bid_samples,
        "subsidy_total_adoptions": int(row.get("subsidy_total_adoptions") or 0),
        "subsidy_total_amount_yen": int(row.get("subsidy_total_amount_yen") or 0),
        "subsidy_program_overlap": subsidy_overlap,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": entity,
            "procuring_entity": entity,
        },
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
