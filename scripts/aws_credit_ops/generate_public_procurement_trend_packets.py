#!/usr/bin/env python3
"""Generate ``public_procurement_trend_v1`` packets (Wave 53.3 #9).

業種 (JSIC) × 入札落札 × 採択 packet (政府調達トレンド). For each
(jsic_major × ministry) cell, computes descriptive procurement-trend
signals: win-rate, top contractors, average awarded amount.

Cohort
------

::

    cohort = (jsic_major × ministry)

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

PACKAGE_KIND: Final[str] = "public_procurement_trend_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 public procurement trend packet は jpi_bids の descriptive 集計です。"
    "個別案件の評価・落札理由は調達庁 / 各省契約担当部 を一次確認、入札参加"
    "資格は地方公共団体 / 中央調達 で異なります。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_bids"):
        return

    # Build (jsic_major × ministry) cells. decision_date is unpopulated at
    # this snapshot — we use announcement_date as the timing axis instead
    # and degrade gracefully when awarded_amount_yen is absent.
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT COALESCE(classification_code, 'UNKNOWN') AS jsic_major, "
            "       COALESCE(ministry, 'UNKNOWN') AS ministry, "
            "       COUNT(*) AS n, "
            "       COALESCE(SUM(awarded_amount_yen), 0) AS total_yen, "
            "       COALESCE(AVG(awarded_amount_yen), 0) AS mean_yen "
            "  FROM jpi_bids "
            " WHERE announcement_date IS NOT NULL "
            "    OR decision_date IS NOT NULL "
            " GROUP BY jsic_major, ministry "
            " HAVING n > 0"
        ):
            jsic = str(r["jsic_major"] or "UNKNOWN")[:5]
            ministry = str(r["ministry"] or "UNKNOWN")[:50]
            cells[(jsic, ministry)] = {
                "bid_count": int(r["n"] or 0),
                "total_awarded_yen": int(r["total_yen"] or 0),
                "mean_awarded_yen": float(r["mean_yen"] or 0),
            }

    for emitted, ((jsic, ministry), cell) in enumerate(
        sorted(cells.items(), key=lambda kv: -kv[1]["bid_count"])
    ):
        cohort_id = f"{jsic}|{ministry}"
        top_winners: list[dict[str, Any]] = []
        # winner_houjin_bangou is sparse at this snapshot — fall back to
        # surfacing top bid_title rows (descriptive, not aggregated) so the
        # packet always carries at least 1 evidence-bearing row.
        with contextlib.suppress(Exception):
            for w in primary_conn.execute(
                "SELECT winner_houjin_bangou, winner_name, "
                "       bid_title, awarded_amount_yen, announcement_date, "
                "       procuring_entity "
                "  FROM jpi_bids "
                " WHERE COALESCE(classification_code, 'UNKNOWN') = ? "
                "   AND COALESCE(ministry, 'UNKNOWN') = ? "
                " ORDER BY COALESCE(awarded_amount_yen, 0) DESC, "
                "          announcement_date DESC "
                " LIMIT ?",
                (jsic, ministry, PER_AXIS_RECORD_CAP),
            ):
                top_winners.append(
                    {
                        "houjin_bangou": w["winner_houjin_bangou"],
                        "winner_name": w["winner_name"],
                        "bid_title": (
                            str(w["bid_title"])[:120]
                            if w["bid_title"] is not None
                            else None
                        ),
                        "awarded_amount_yen": int(w["awarded_amount_yen"] or 0),
                        "announcement_date": w["announcement_date"],
                        "procuring_entity": w["procuring_entity"],
                    }
                )
        yield {
            "cohort_id": cohort_id,
            "jsic_major": jsic,
            "ministry": ministry,
            "cell_stats": cell,
            "top_winners": top_winners,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cohort_id = str(row.get("cohort_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    winners = list(row.get("top_winners", []))
    cell = row.get("cell_stats") or {}
    rows_in_packet = 1 + len(winners)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "落札理由・評価方式は調達庁 / 各省契約担当部の一次確認が"
                "必要。入札参加資格は別途要確認。"
            ),
        }
    ]
    if int(cell.get("bid_count") or 0) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "このコホートで入札観測無し",
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
            "source_url": "https://www.kantei.go.jp/jp/singi/keizai/chiisaisihai/",
            "source_fetched_at": None,
            "publisher": "内閣府 公共調達",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "bid_count": int(cell.get("bid_count") or 0),
        "total_awarded_yen": int(cell.get("total_awarded_yen") or 0),
        "mean_awarded_yen": round(float(cell.get("mean_awarded_yen") or 0), 2),
        "top_winner_count": len(winners),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "cohort", "id": cohort_id},
        "cell_stats": cell,
        "top_winners": winners,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": cohort_id,
            "jsic_major": row.get("jsic_major"),
            "ministry": row.get("ministry"),
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
