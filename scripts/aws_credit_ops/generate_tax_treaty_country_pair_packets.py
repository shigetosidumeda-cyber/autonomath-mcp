"""Generate ``tax_treaty_country_pair_v1`` packets (Wave 98 #4 of 10).

国別 (am_tax_treaty.country_iso) ごとに 日本 ↔ 相手国 bilateral DTA
(double taxation agreement) surface (WHT rates / PE threshold / info
exchange status) を集計し、descriptive bilateral country-pair indicator
として packet 化する。実際の源泉徴収 / 適用条文 / 軽減税率届出 (155-1)
判断は 国税庁 + 顧問税理士 + 国際税務 SP の一次確認が前提 (租税条約等の
実施に伴う所得税法等の特例等に関する法律)。

Cohort
------
::

    cohort = country_iso (am_tax_treaty.country_iso, ISO 3166-1 alpha-2)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "tax_treaty_country_pair_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 tax treaty country pair packet は am_tax_treaty を国別に展開した "
    "descriptive bilateral treaty surface で、実際の源泉徴収 / 適用条文 / "
    "軽減税率届出 (155-1) 判断は 国税庁 + 顧問税理士 + 国際税務 SP の "
    "一次確認が前提です (実施特例法、所得税法 §161-165、法人税法 §138-141)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_tax_treaty"):
        return
    rows: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT country_iso, country_name_ja, country_name_en, "
            "       treaty_kind, dta_signed_date, dta_in_force_date, "
            "       wht_dividend_pct, wht_dividend_parent_pct, "
            "       wht_interest_pct, wht_royalty_pct, "
            "       pe_days_threshold, info_exchange "
            "  FROM am_tax_treaty "
            " ORDER BY country_iso"
        ):
            rows.append(
                {
                    "country_iso": str(r["country_iso"]),
                    "country_name_ja": str(r["country_name_ja"] or ""),
                    "country_name_en": str(r["country_name_en"] or ""),
                    "treaty_kind": str(r["treaty_kind"] or ""),
                    "dta_signed_date": (
                        str(r["dta_signed_date"]) if r["dta_signed_date"] else None
                    ),
                    "dta_in_force_date": (
                        str(r["dta_in_force_date"])
                        if r["dta_in_force_date"]
                        else None
                    ),
                    "wht_dividend_pct": (
                        float(r["wht_dividend_pct"])
                        if r["wht_dividend_pct"] is not None
                        else None
                    ),
                    "wht_dividend_parent_pct": (
                        float(r["wht_dividend_parent_pct"])
                        if r["wht_dividend_parent_pct"] is not None
                        else None
                    ),
                    "wht_interest_pct": (
                        float(r["wht_interest_pct"])
                        if r["wht_interest_pct"] is not None
                        else None
                    ),
                    "wht_royalty_pct": (
                        float(r["wht_royalty_pct"])
                        if r["wht_royalty_pct"] is not None
                        else None
                    ),
                    "pe_days_threshold": (
                        int(r["pe_days_threshold"])
                        if r["pe_days_threshold"] is not None
                        else None
                    ),
                    "info_exchange": str(r["info_exchange"] or ""),
                }
            )

    for emitted, record in enumerate(rows):
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = str(row.get("country_iso") or "UNKNOWN")
    country_name_ja = str(row.get("country_name_ja") or "")
    country_name_en = str(row.get("country_name_en") or "")
    treaty_kind = str(row.get("treaty_kind") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"

    # 1 country = 1 packet, rows_in_packet=1 (treaty surface itself).
    rows_in_packet = 1

    # WHT presence count: how many of the 4 WHT axes have a non-NULL
    # treaty rate. Useful for downstream "completeness" cohort.
    wht_fields = [
        "wht_dividend_pct",
        "wht_dividend_parent_pct",
        "wht_interest_pct",
        "wht_royalty_pct",
    ]
    wht_present_n = sum(1 for f in wht_fields if row.get(f) is not None)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "源泉徴収 / 適用条文 / 軽減税率届出 (155-1) 判断は "
                "国税庁 + 顧問税理士 + 国際税務 SP の一次確認が前提"
            ),
        }
    ]
    if wht_present_n < 4:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": (
                    f"4 軸 WHT のうち {wht_present_n} 軸のみ rate 設定済、"
                    "残は条文直接参照が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/index.htm",
            "source_fetched_at": None,
            "publisher": "財務省 租税条約",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nta.go.jp/publication/pamph/koho/kurashi/html/06_3.htm",
            "source_fetched_at": None,
            "publisher": "国税庁 国際課税",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "country_iso", "id": country_iso},
        "country_iso": country_iso,
        "country_name_ja": country_name_ja,
        "country_name_en": country_name_en,
        "treaty_kind": treaty_kind,
        "dta_signed_date": row.get("dta_signed_date"),
        "dta_in_force_date": row.get("dta_in_force_date"),
        "wht_dividend_pct": row.get("wht_dividend_pct"),
        "wht_dividend_parent_pct": row.get("wht_dividend_parent_pct"),
        "wht_interest_pct": row.get("wht_interest_pct"),
        "wht_royalty_pct": row.get("wht_royalty_pct"),
        "pe_days_threshold": row.get("pe_days_threshold"),
        "info_exchange": row.get("info_exchange"),
        "wht_present_n": wht_present_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": country_iso, "country_iso": country_iso},
        metrics={"wht_present_n": wht_present_n},
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
