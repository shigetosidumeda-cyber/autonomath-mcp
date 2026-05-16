#!/usr/bin/env python3
"""Generate ``bilateral_trade_program_v1`` packets (Wave 64 #7 of 10).

国 (am_tax_treaty) ごとに 二国間貿易協定 (EPA / FTA / RCEP / TPP) 制度
関連 jpi_programs を集約し、descriptive bilateral trade program density
proxy として packet 化する。EPA / FTA / RCEP / TPP 原産地証明 + 適用判断
は所管官庁 + 国際通商弁護士の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "bilateral_trade_program_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

PROGRAM_KEYWORDS: Final[tuple[str, ...]] = (
    "EPA", "FTA", "RCEP", "TPP", "二国間", "経済連携",
    "経連協定", "通商協定", "原産地", "貿易協定", "FTAAP", "ASEAN",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 bilateral trade program packet は am_tax_treaty 条約国 × jpi_programs "
    "name + EPA/FTA/RCEP keyword 検索による descriptive 指標です。EPA / FTA / "
    "RCEP / TPP 原産地証明 + 適用判断は所管官庁 (経産省 / 外務省 / 税関) + "
    "国際通商弁護士の一次確認が前提 (弁護士法 §72)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_tax_treaty"):
        return
    if not table_exists(primary_conn, "jpi_programs"):
        return

    treaties: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT country_iso, country_name_ja, country_name_en, treaty_kind "
            "  FROM am_tax_treaty ORDER BY country_iso"
        ):
            treaties.append(dict(r))

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in PROGRAM_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in PROGRAM_KEYWORDS)
    candidates: list[dict[str, Any]] = []
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
        country_name_ja = str(t.get("country_name_ja") or "")
        matches: list[dict[str, Any]] = []
        for p in candidates[:PER_AXIS_RECORD_CAP]:
            matches.append(
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
            "country_name_ja": country_name_ja,
            "country_name_en": t.get("country_name_en"),
            "treaty_kind": t.get("treaty_kind"),
            "bilateral_trade_programs": matches,
            "candidate_pool_size": len(candidates),
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = str(row.get("country_iso") or "UNKNOWN")
    country_name_ja = str(row.get("country_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"
    matched = list(row.get("bilateral_trade_programs", []))
    rows_in_packet = len(matched) + 1

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "EPA / FTA / RCEP / TPP 原産地証明 + 適用判断は所管官庁 + "
                "国際通商弁護士の一次確認が前提"
            ),
        }
    ]
    if not matched:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "公開 jpi_programs に EPA/FTA/RCEP 関連 keyword 制度 未観測"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.mofa.go.jp/mofaj/gaiko/fta/",
            "source_fetched_at": None,
            "publisher": "外務省 経済連携協定 (EPA/FTA)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/trade_policy/epa/",
            "source_fetched_at": None,
            "publisher": "経済産業省 EPA/FTA",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": country_iso},
        "country_iso": country_iso,
        "country_name_ja": country_name_ja,
        "country_name_en": row.get("country_name_en"),
        "treaty_kind": row.get("treaty_kind"),
        "bilateral_trade_programs": matched,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": country_iso, "country_iso": country_iso},
        metrics={
            "bilateral_trade_program_count": len(matched),
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
