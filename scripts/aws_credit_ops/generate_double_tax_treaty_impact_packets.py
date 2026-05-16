#!/usr/bin/env python3
"""Generate ``double_tax_treaty_impact_v1`` packets (Wave 64 #2 of 10).

国 (am_tax_treaty) ごとに 二重課税排除 条約 impact を WHT pct 差分 + 国内
制度のクロスリンクで descriptive impact proxy として packet 化する。
条約適用判断 / 源泉徴収判断は国税庁 + 税理士の一次確認が前提。

Cohort
------
::

    cohort = country_iso (ISO 3166-1 alpha-2)
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

PACKAGE_KIND: Final[str] = "double_tax_treaty_impact_v1"

# Statutory Japan withholding-tax pct baseline (national, non-treaty).
# Source: 国税庁「源泉徴収のあらまし」基本税率。
STATUTORY_WHT_DIVIDEND_PCT: Final[float] = 20.42
STATUTORY_WHT_INTEREST_PCT: Final[float] = 20.42
STATUTORY_WHT_ROYALTY_PCT: Final[float] = 20.42

DEFAULT_DISCLAIMER: Final[str] = (
    "本 double tax treaty impact packet は am_tax_treaty の WHT rate と日本国内"
    " 源泉徴収基本税率 (20.42%) の差分を一律比較した descriptive 指標です。"
    "条約適用要件・源泉徴収判定・限度税率の正本は国税庁・財務省条約集 "
    "を一次確認、税理士の判断が前提です (税理士法 §52)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_tax_treaty"):
        return

    treaties: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT country_iso, country_name_ja, country_name_en, treaty_kind, "
            "       dta_signed_date, dta_in_force_date, "
            "       wht_dividend_pct, wht_dividend_parent_pct, "
            "       wht_interest_pct, wht_royalty_pct "
            "  FROM am_tax_treaty ORDER BY country_iso"
        ):
            treaties.append(dict(r))

    for emitted, t in enumerate(treaties):
        country_iso = str(t.get("country_iso") or "")

        def _impact(treaty_pct: float | None, statutory: float) -> dict[str, Any]:
            if treaty_pct is None:
                return {
                    "treaty_pct": None,
                    "statutory_pct": statutory,
                    "savings_pct_points": None,
                }
            try:
                tp = float(treaty_pct)
            except (TypeError, ValueError):
                return {
                    "treaty_pct": None,
                    "statutory_pct": statutory,
                    "savings_pct_points": None,
                }
            return {
                "treaty_pct": tp,
                "statutory_pct": statutory,
                "savings_pct_points": round(statutory - tp, 4),
            }

        impact = {
            "dividend": _impact(t.get("wht_dividend_pct"), STATUTORY_WHT_DIVIDEND_PCT),
            "dividend_parent": _impact(
                t.get("wht_dividend_parent_pct"), STATUTORY_WHT_DIVIDEND_PCT
            ),
            "interest": _impact(t.get("wht_interest_pct"), STATUTORY_WHT_INTEREST_PCT),
            "royalty": _impact(t.get("wht_royalty_pct"), STATUTORY_WHT_ROYALTY_PCT),
        }
        record = {
            "country_iso": country_iso,
            "country_name_ja": t.get("country_name_ja"),
            "country_name_en": t.get("country_name_en"),
            "treaty_kind": t.get("treaty_kind"),
            "dta_signed_date": t.get("dta_signed_date"),
            "dta_in_force_date": t.get("dta_in_force_date"),
            "impact": impact,
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = str(row.get("country_iso") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"
    impact = dict(row.get("impact") or {})
    rows_in_packet = 1 + sum(
        1 for axis in impact.values() if isinstance(axis, dict) and axis.get("treaty_pct") is not None
    )

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "条約適用要件 / 限度税率 / PE 判定は国税庁 + 税理士の一次確認が"
                "前提。本 packet は条約 WHT pct と statutory pct の差分 proxy。"
            ),
        }
    ]
    has_any_treaty = any(
        isinstance(axis, dict) and axis.get("treaty_pct") is not None
        for axis in impact.values()
    )
    if not has_any_treaty:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "条約 WHT pct 4 軸全 None — 条約条文の個別読込が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": (
                "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/"
            ),
            "source_fetched_at": None,
            "publisher": "財務省 租税条約一覧",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/",
            "source_fetched_at": None,
            "publisher": "国税庁 源泉徴収",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": country_iso},
        "country_iso": country_iso,
        "country_name_ja": row.get("country_name_ja"),
        "country_name_en": row.get("country_name_en"),
        "treaty_kind": row.get("treaty_kind"),
        "dta_signed_date": row.get("dta_signed_date"),
        "dta_in_force_date": row.get("dta_in_force_date"),
        "impact": impact,
        "statutory_baseline_pct": {
            "dividend": STATUTORY_WHT_DIVIDEND_PCT,
            "interest": STATUTORY_WHT_INTEREST_PCT,
            "royalty": STATUTORY_WHT_ROYALTY_PCT,
        },
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": country_iso, "country_iso": country_iso},
        metrics={
            "treaty_axis_filled_count": sum(
                1
                for axis in impact.values()
                if isinstance(axis, dict) and axis.get("treaty_pct") is not None
            ),
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
