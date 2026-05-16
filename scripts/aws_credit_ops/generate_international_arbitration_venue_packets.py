#!/usr/bin/env python3
"""Generate ``international_arbitration_venue_v1`` packets (Wave 64 #10 of 10).

国 (am_tax_treaty) ごとに 国際仲裁 venue 偏好 関連制度を集約し、
descriptive cross-border arbitration venue preference proxy として packet 化
する。仲裁地選択 / NY 条約 加盟国 + 仲裁条項判断は所管官庁 (法務省 / JIDRC)
+ 国際商事仲裁弁護士の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "international_arbitration_venue_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

PROGRAM_KEYWORDS: Final[tuple[str, ...]] = (
    "仲裁", "国際仲裁", "ADR", "紛争解決", "商事仲裁",
    "JIDRC", "JCAA", "ICC", "SIAC", "HKIAC", "ICSID", "NY条約",
)

# Curated list of major arbitration venues used by Japan-related international
# commercial contracts. This is a descriptive registry, not legal advice.
_VENUE_REGISTRY: Final[dict[str, dict[str, str]]] = {
    "JP": {"venue": "JCAA / JIDRC", "city": "Tokyo / Osaka"},
    "SG": {"venue": "SIAC", "city": "Singapore"},
    "HK": {"venue": "HKIAC", "city": "Hong Kong SAR"},
    "GB": {"venue": "LCIA", "city": "London"},
    "US": {"venue": "ICC New York / AAA-ICDR", "city": "New York"},
    "FR": {"venue": "ICC Paris", "city": "Paris"},
    "CH": {"venue": "Swiss Arbitration Centre", "city": "Geneva / Zurich"},
    "KR": {"venue": "KCAB", "city": "Seoul"},
    "CN": {"venue": "CIETAC", "city": "Beijing"},
    "DE": {"venue": "DIS", "city": "Frankfurt"},
    "NL": {"venue": "NAI", "city": "Amsterdam"},
    "SE": {"venue": "SCC", "city": "Stockholm"},
    "AE": {"venue": "DIAC / ADGM", "city": "Dubai / Abu Dhabi"},
    "MY": {"venue": "AIAC", "city": "Kuala Lumpur"},
    "AU": {"venue": "ACICA", "city": "Sydney"},
    "BR": {"venue": "CAM-CCBC", "city": "São Paulo"},
    "IN": {"venue": "MCIA / IIAC", "city": "Mumbai / New Delhi"},
}

DEFAULT_DISCLAIMER: Final[str] = (
    "本 international arbitration venue packet は am_tax_treaty 条約国 × "
    "_VENUE_REGISTRY による descriptive curated 指標です。仲裁地選択 / NY 条約"
    "加盟国確認 / 仲裁条項起案 / 仲裁判断執行可能性判断は所管官庁 (法務省 / "
    "JIDRC) + 国際商事仲裁弁護士の一次確認が前提 (弁護士法 §72)。"
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
            "SELECT country_iso, country_name_ja, country_name_en, treaty_kind "
            "  FROM am_tax_treaty ORDER BY country_iso"
        ):
            treaties.append(dict(r))

    candidates: list[dict[str, Any]] = []
    if table_exists(primary_conn, "jpi_programs"):
        where_clauses = " OR ".join(["primary_name LIKE ?" for _ in PROGRAM_KEYWORDS])
        params = tuple(f"%{kw}%" for kw in PROGRAM_KEYWORDS)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT unified_id, primary_name, authority_level, prefecture, "
                "       program_kind, tier "
                "  FROM jpi_programs "
                f" WHERE excluded = 0 AND ({where_clauses}) "
                " ORDER BY tier ASC LIMIT 200",
                params,
            ):
                candidates.append(dict(r))

    for emitted, t in enumerate(treaties):
        country_iso = str(t.get("country_iso") or "")
        venue = _VENUE_REGISTRY.get(country_iso)
        programs: list[dict[str, Any]] = []
        for p in candidates[:PER_AXIS_RECORD_CAP]:
            programs.append(
                {
                    "unified_id": p.get("unified_id"),
                    "primary_name": p.get("primary_name"),
                    "authority_level": p.get("authority_level"),
                    "prefecture": p.get("prefecture"),
                    "program_kind": p.get("program_kind"),
                }
            )
        record = {
            "country_iso": country_iso,
            "country_name_ja": t.get("country_name_ja"),
            "country_name_en": t.get("country_name_en"),
            "treaty_kind": t.get("treaty_kind"),
            "arbitration_venue": venue,
            "arbitration_programs": programs,
            "candidate_pool_size": len(candidates),
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = str(row.get("country_iso") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"
    venue = row.get("arbitration_venue")
    programs = list(row.get("arbitration_programs", []))
    venue_count = 1 if venue else 0
    rows_in_packet = venue_count + len(programs) + 1  # treaty row counts

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "仲裁地選択 / NY 条約加盟国確認 / 仲裁条項起案 / 執行可能性判断"
                "は法務省 + 国際商事仲裁弁護士の一次確認が前提"
            ),
        }
    ]
    if venue is None and not programs:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "_VENUE_REGISTRY 未掲載 + jpi_programs 関連 keyword 制度 未観測"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.moj.go.jp/shihouhousei/shihouhousei04_00080.html",
            "source_fetched_at": None,
            "publisher": "法務省 仲裁法",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jcaa.or.jp/",
            "source_fetched_at": None,
            "publisher": "日本商事仲裁協会 (JCAA)",
            "license": "proprietary",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": country_iso},
        "country_iso": country_iso,
        "country_name_ja": row.get("country_name_ja"),
        "country_name_en": row.get("country_name_en"),
        "treaty_kind": row.get("treaty_kind"),
        "arbitration_venue": venue,
        "arbitration_programs": programs,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": country_iso, "country_iso": country_iso},
        metrics={
            "venue_registry_hit": venue_count,
            "arbitration_program_count": len(programs),
            "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
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
