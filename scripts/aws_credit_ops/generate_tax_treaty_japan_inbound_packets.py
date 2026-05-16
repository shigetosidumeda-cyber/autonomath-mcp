#!/usr/bin/env python3
"""Generate ``tax_treaty_japan_inbound_v1`` packets (Wave 53.2 #4).

国際課税 treaty packet. One packet per (Japan → country) treaty row in
``am_tax_treaty`` (33 hand-curated countries as of 2026-05-07). The
packet pre-renders treaty kind / signed / in_force dates / WHT rates /
PE day threshold / information-exchange status / treaty URL.

Cohort
------

::

    cohort = country_iso

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

PACKAGE_KIND: Final[str] = "tax_treaty_japan_inbound_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 tax treaty packet は am_tax_treaty (33 国手 curated) を country_iso "
    "別に packet 化した descriptive 指標です。条文解釈・適用判定は税理士・"
    "弁護士・財務省主税局公開資料の確認が必須 (税理士法 §52)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_tax_treaty"):
        return
    sql = (
        "SELECT country_iso, country_name_ja, country_name_en, treaty_kind, "
        "       dta_signed_date, dta_in_force_date, "
        "       wht_dividend_pct, wht_dividend_parent_pct, "
        "       wht_interest_pct, wht_royalty_pct, "
        "       pe_days_threshold, info_exchange "
        "  FROM am_tax_treaty "
        " ORDER BY country_iso"
    )
    emitted = 0
    for row in primary_conn.execute(sql):
        country_iso = normalise_token(row["country_iso"])
        if country_iso == "UNKNOWN":
            continue
        yield {
            "country_iso": country_iso,
            "country_name_ja": row["country_name_ja"],
            "country_name_en": row["country_name_en"],
            "treaty_kind": row["treaty_kind"],
            "dta_signed_date": row["dta_signed_date"],
            "dta_in_force_date": row["dta_in_force_date"],
            "wht_dividend_pct": row["wht_dividend_pct"],
            "wht_dividend_parent_pct": row["wht_dividend_parent_pct"],
            "wht_interest_pct": row["wht_interest_pct"],
            "wht_royalty_pct": row["wht_royalty_pct"],
            "pe_days_threshold": row["pe_days_threshold"],
            "info_exchange": row["info_exchange"],
        }
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = normalise_token(row.get("country_iso"))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "treaty rate は base case のみ。LOB / PPT / 適格者条項の"
                "適用判定は税理士・国際税務 専門家の確認が必須 (税理士法 §52)。"
            ),
        }
    ]
    missing = [
        k
        for k in (
            "dta_signed_date",
            "dta_in_force_date",
            "wht_dividend_pct",
            "wht_royalty_pct",
            "pe_days_threshold",
        )
        if row.get(k) is None
    ]
    if missing:
        known_gaps.append(
            {
                "code": "pricing_or_cap_unconfirmed",
                "description": (
                    "treaty 数値が NULL の項目あり (" + ",".join(missing) + ") "
                    "— OECD model / 財務省条文を一次確認"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.mof.go.jp/tax_policy/summary/international/tax_convention/index.htm",
            "source_fetched_at": None,
            "publisher": "財務省 国際課税・租税条約",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nta.go.jp/taxes/shiraberu/kokusai/index.htm",
            "source_fetched_at": None,
            "publisher": "国税庁 国際税務",
            "license": "gov_standard",
        },
    ]

    metrics = {
        "wht_dividend_pct": row.get("wht_dividend_pct"),
        "wht_dividend_parent_pct": row.get("wht_dividend_parent_pct"),
        "wht_interest_pct": row.get("wht_interest_pct"),
        "wht_royalty_pct": row.get("wht_royalty_pct"),
        "pe_days_threshold": row.get("pe_days_threshold"),
    }
    body = {
        "treaty": {
            "country_iso": country_iso,
            "country_name_ja": row.get("country_name_ja"),
            "country_name_en": row.get("country_name_en"),
            "treaty_kind": row.get("treaty_kind"),
            "dta_signed_date": row.get("dta_signed_date"),
            "dta_in_force_date": row.get("dta_in_force_date"),
            "info_exchange": row.get("info_exchange"),
        },
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": country_iso,
            "country_iso": country_iso,
        },
        metrics=metrics,
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, 1


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
