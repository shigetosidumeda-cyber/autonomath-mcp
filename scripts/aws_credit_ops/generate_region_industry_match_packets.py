#!/usr/bin/env python3
"""Generate ``region_industry_match_v1`` packets (Wave 57 #3 of 10).

地域 × 業種 (JSIC) のマッチング matrix。jpi_adoption_records から各都道府県の
JSIC 大分類別 unique houjin 数と合計交付額を集計する。

Cohort
------
::

    cohort = prefecture
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

PACKAGE_KIND: Final[str] = "region_industry_match_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 region industry match packet は jpi_adoption_records を都道府県 × JSIC で"
    "集計した descriptive マッチ指標です。実際の業種適合判断は中小機構 + 各自治体"
    "支援センターの一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_adoption_records "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        rows: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT substr(industry_jsic_medium, 1, 1) AS jsic_major, "
                "       COUNT(*) AS adoptions, "
                "       COUNT(DISTINCT houjin_bangou) AS unique_houjin, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                "   AND industry_jsic_medium IS NOT NULL "
                " GROUP BY substr(industry_jsic_medium, 1, 1) "
                " ORDER BY total_amount_yen DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                rows.append(dict(r))
        record = {
            "prefecture": pref,
            "industry_match": rows,
            "industry_count": len(rows),
        }
        if rows:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    rows = list(row.get("industry_match", []))
    rows_in_packet = len(rows)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": "業種マッチは jpi_adoption_records 時点 + JSIC 大分類抽出に依存",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で業種マッチデータ無し",
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
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "industry_match": rows,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"industry_count": rows_in_packet},
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
