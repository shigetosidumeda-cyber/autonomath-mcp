#!/usr/bin/env python3
"""Generate ``inbound_tax_treaty_compliance_v1`` packets (Wave 55 #4).

国際企業 (法人) × 税務条約 (am_tax_treaty, 33 か国) × インボイス (J03)
3-axis compliance overview packet. For each country with a treaty in
am_tax_treaty, surface treaty WHT rates + descriptive set of registered
invoice issuers whose normalized_name contains country-specific
hint tokens (e.g. "アメリカ" / "USA"). NOTE: name-based inference is a
proxy only — true foreign-affiliate identification requires UBO
disclosure outside our corpus.

Cohort
------

::

    cohort = country_iso (ISO 3166-1 alpha-2)

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

PACKAGE_KIND: Final[str] = "inbound_tax_treaty_compliance_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 inbound tax treaty compliance packet は租税条約 (am_tax_treaty) と "
    "インボイス公表名称突合の descriptive cross-link です。源泉徴収・PE "
    "判定・インボイス対応コンプライアンスの正本は国税庁・財務省条約集 + "
    "受領者居住国適用要件を一次確認、税理士の判断が前提です (税理士法 §52)。"
)

# Country-specific name-hint tokens for proxy registrant filtering.
_COUNTRY_HINTS: Final[dict[str, tuple[str, ...]]] = {
    "US": ("アメリカ", "米国", "USA", "US Inc"),
    "GB": ("英国", "イギリス", "UK ", "United Kingdom"),
    "DE": ("ドイツ", "Germany"),
    "FR": ("フランス", "France"),
    "CN": ("中国", "China", "中華"),
    "KR": ("韓国", "Korea"),
    "SG": ("シンガポール", "Singapore"),
    "AU": ("オーストラリア", "Australia"),
    "CA": ("カナダ", "Canada"),
    "CH": ("スイス", "Switzerland"),
    "NL": ("オランダ", "Netherlands"),
    "IT": ("イタリア", "Italy"),
    "ES": ("スペイン", "Spain"),
    "BE": ("ベルギー", "Belgium"),
    "BR": ("ブラジル", "Brazil"),
    "IN": ("インド", "India"),
    "ID": ("インドネシア", "Indonesia"),
    "TH": ("タイ", "Thailand"),
    "MY": ("マレーシア", "Malaysia"),
    "PH": ("フィリピン", "Philippines"),
    "VN": ("ベトナム", "Vietnam"),
    "MX": ("メキシコ", "Mexico"),
    "AE": ("UAE", "アラブ首長国連邦"),
    "ZA": ("南アフリカ", "South Africa"),
    "RU": ("ロシア", "Russia"),
}


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
            "SELECT country_iso, country_name_ja, country_name_en, "
            "       treaty_kind, dta_signed_date, dta_in_force_date, "
            "       wht_dividend_pct, wht_dividend_parent_pct, "
            "       wht_interest_pct, wht_royalty_pct "
            "  FROM am_tax_treaty ORDER BY country_iso"
        ):
            treaties.append(dict(r))

    for emitted, t in enumerate(treaties):
        country_iso = str(t.get("country_iso") or "")
        record: dict[str, Any] = {
            "country_iso": country_iso,
            "country_name_ja": t.get("country_name_ja"),
            "country_name_en": t.get("country_name_en"),
            "treaty_kind": t.get("treaty_kind"),
            "dta_signed_date": t.get("dta_signed_date"),
            "dta_in_force_date": t.get("dta_in_force_date"),
            "wht": {
                "dividend_pct": t.get("wht_dividend_pct"),
                "dividend_parent_pct": t.get("wht_dividend_parent_pct"),
                "interest_pct": t.get("wht_interest_pct"),
                "royalty_pct": t.get("wht_royalty_pct"),
            },
            "invoice_registrant_candidates": [],
            "invoice_candidate_count_estimate": 0,
        }
        hints = _COUNTRY_HINTS.get(country_iso, ())
        if hints and table_exists(primary_conn, "jpi_invoice_registrants"):
            # Count + sample names that hit any of the country hint tokens.
            total_count = 0
            for hint in hints:
                with contextlib.suppress(Exception):
                    for c in primary_conn.execute(
                        "SELECT COUNT(*) AS c "
                        "  FROM jpi_invoice_registrants "
                        " WHERE normalized_name LIKE ?",
                        (f"%{hint}%",),
                    ):
                        total_count += int(c["c"] or 0)
                with contextlib.suppress(Exception):
                    for r2 in primary_conn.execute(
                        "SELECT invoice_registration_number, normalized_name, "
                        "       prefecture, registered_date, registrant_kind "
                        "  FROM jpi_invoice_registrants "
                        " WHERE normalized_name LIKE ? "
                        " ORDER BY registered_date DESC "
                        " LIMIT ?",
                        (f"%{hint}%", PER_AXIS_RECORD_CAP),
                    ):
                        if (
                            len(record["invoice_registrant_candidates"])
                            >= PER_AXIS_RECORD_CAP
                        ):
                            break
                        record["invoice_registrant_candidates"].append(
                            {
                                "invoice_registration_number": r2[
                                    "invoice_registration_number"
                                ],
                                "normalized_name": r2["normalized_name"],
                                "prefecture": r2["prefecture"],
                                "registered_date": r2["registered_date"],
                                "registrant_kind": r2["registrant_kind"],
                                "hint_matched": hint,
                            }
                        )
            record["invoice_candidate_count_estimate"] = total_count

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = str(row.get("country_iso") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"
    invs = list(row.get("invoice_registrant_candidates", []))
    rows_in_packet = len(invs) + 1  # treaty row itself counts as one record

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "源泉徴収・PE 判定・インボイス対応の正本は国税庁・財務省条約集 "
                "を一次確認、税理士判断が前提。本 packet は条約 + 公表名称の "
                "descriptive cross-link で UBO 突合は未実施。"
            ),
        },
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "名称ヒントによる外国系企業推定は proxy。実際の外国法人 / 外国"
                "支店 / 日本子会社の識別は UBO 公開情報 + EDINET 親会社情報 + "
                "登記簿で個別確認が必要。"
            ),
        },
    ]
    if not invs:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "公表名称ヒント該当無 — 国内取引無を意味しない",
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
            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁 適格請求書発行事業者公表",
            "license": "pdl_v1.0",
        },
        {
            "source_url": "https://www.nta.go.jp/taxes/shiraberu/shinkoku/tebiki/",
            "source_fetched_at": None,
            "publisher": "国税庁 源泉徴収",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "invoice_candidate_count_estimate": int(
            row.get("invoice_candidate_count_estimate") or 0
        ),
        "invoice_sample_count": len(invs),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": country_iso},
        "country_iso": country_iso,
        "country_name_ja": row.get("country_name_ja"),
        "country_name_en": row.get("country_name_en"),
        "treaty": {
            "treaty_kind": row.get("treaty_kind"),
            "dta_signed_date": row.get("dta_signed_date"),
            "dta_in_force_date": row.get("dta_in_force_date"),
            "wht": row.get("wht"),
        },
        "invoice_registrant_candidates": invs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": country_iso, "country_iso": country_iso},
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
