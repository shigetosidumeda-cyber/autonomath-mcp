#!/usr/bin/env python3
"""Generate ``subsidy_roi_estimate_v1`` packets (Wave 60 #3 of 10).

業種 (JSIC major) ごとに amount_granted_yen + amount_project_total_yen の
公開部分から descriptive ROI proxy (subsidy_rate と median amount) を集計する。
個社 ROI 評価ではなく cohort 内 distribution のみ。

Cohort
------
::

    cohort = jsic_major (A-V)
"""

from __future__ import annotations

import contextlib
import statistics
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

PACKAGE_KIND: Final[str] = "subsidy_roi_estimate_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 subsidy ROI estimate packet は jpi_adoption_records の amount_granted_yen "
    "+ amount_project_total_yen 公開部分から業種別 ROI proxy を集計した descriptive "
    "指標です。事業性評価判断は中小企業診断士 + 税理士 の一次確認が前提 "
    "(中小企業診断士法 / 税理士法 §52)。実際の ROI は事業内容で大きく変動。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        granted: list[int] = []
        total_amounts: list[int] = []
        ratios: list[float] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT amount_granted_yen, amount_project_total_yen "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ? "
                "   AND amount_granted_yen IS NOT NULL "
                "   AND amount_granted_yen > 0 "
                " LIMIT 5000",
                (jsic_code,),
            ):
                g = int(r["amount_granted_yen"] or 0)
                t = int(r["amount_project_total_yen"] or 0)
                if g > 0:
                    granted.append(g)
                if t > 0:
                    total_amounts.append(t)
                if g > 0 and t > 0:
                    ratios.append(g / t)
        n_amounts = len(granted)
        median_granted = int(statistics.median(granted)) if granted else 0
        median_total = int(statistics.median(total_amounts)) if total_amounts else 0
        median_ratio = round(statistics.median(ratios), 4) if ratios else None
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "observed_grants_n": n_amounts,
            "median_granted_yen": median_granted,
            "median_project_total_yen": median_total,
            "median_subsidy_ratio": median_ratio,
        }
        if n_amounts > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    n_amounts = int(row.get("observed_grants_n") or 0)
    rows_in_packet = n_amounts

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "事業性評価判断は中小企業診断士 + 税理士 の一次確認が前提。"
                "実際の ROI は事業内容で大きく変動"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で amount_granted 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.chusho.meti.go.jp/",
            "source_fetched_at": None,
            "publisher": "中小企業庁",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "observed_grants_n": n_amounts,
        "median_granted_yen": int(row.get("median_granted_yen") or 0),
        "median_project_total_yen": int(row.get("median_project_total_yen") or 0),
        "median_subsidy_ratio": row.get("median_subsidy_ratio"),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "observed_grants_n": n_amounts,
            "median_granted_yen": int(row.get("median_granted_yen") or 0),
            "median_project_total_yen": int(row.get("median_project_total_yen") or 0),
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
