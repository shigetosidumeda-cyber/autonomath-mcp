#!/usr/bin/env python3
"""Generate ``manufacturing_dx_grants_v1`` packets (Wave 62 #6 of 10).

業種 (JSIC major) ごとに 製造業 × DX補助 + ものづくり補助 制度を集約し、
descriptive sectoral manufacturing DX grant intensity proxy として packet 化する。
DX 認定 / ものづくり補助金判断は所管官庁 + 中小企業診断士確認が前提。

Cohort
------
::

    cohort = jsic_major (A-V)
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

PACKAGE_KIND: Final[str] = "manufacturing_dx_grants_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

SECTOR_KEYWORDS: Final[tuple[str, ...]] = (
    "製造", "ものづくり", "DX", "IT導入", "設備投資", "中小企業", "工場",
    "生産性", "スマート工場", "デジタル", "工程", "自動化",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 manufacturing × DX grant packet は jpi_programs name + 製造 / DX keyword "
    "検索 + jpi_pc_enforcement_industry_distribution から業種別 製造業 × DX補助 "
    "+ ものづくり補助 制度密度を集計した descriptive 指標です。DX 認定 / "
    "ものづくり補助金判断は所管官庁 + 中小企業診断士 等の一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    if not table_exists(primary_conn, "jpi_programs"):
        return
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in SECTOR_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in SECTOR_KEYWORDS)
    candidates: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT unified_id, primary_name, authority_level, prefecture, "
            "       program_kind, target_types_json, tier "
            "  FROM jpi_programs "
            f" WHERE excluded = 0 AND ({where_clauses}) "
            " ORDER BY tier ASC LIMIT 1000",
            params,
        ):
            candidates.append(dict(r))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        matches: list[dict[str, Any]] = []
        for p in candidates:
            tt = str(p.get("target_types_json") or "")
            name = str(p.get("primary_name") or "")
            if jsic_code in tt or (jsic_name and jsic_name in name):
                matches.append(
                    {
                        "unified_id": p.get("unified_id"),
                        "primary_name": p.get("primary_name"),
                        "authority_level": p.get("authority_level"),
                        "prefecture": p.get("prefecture"),
                        "program_kind": p.get("program_kind"),
                    }
                )
            if len(matches) >= PER_AXIS_RECORD_CAP:
                break
        enforcement_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c "
                "  FROM jpi_pc_enforcement_industry_distribution "
                " WHERE industry_jsic = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                enforcement_n = int(row["c"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "manufacturing_programs": matches,
            "enforcement_distribution_n": enforcement_n,
            "candidate_pool_size": len(candidates),
        }
        if matches or enforcement_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    matched = list(row.get("manufacturing_programs", []))
    enforcement_n = int(row.get("enforcement_distribution_n") or 0)
    rows_in_packet = len(matched) + enforcement_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "DX 認定 / ものづくり補助金判断は所管官庁 + 中小企業診断士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で manufacturing keyword + 行政処分密度 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.meti.go.jp/policy/mono_info_service/",
            "source_fetched_at": None,
            "publisher": "経済産業省 製造・サービス",
            "license": "gov_standard",
        },
        {
            "source_url": "https://portal.monodukuri-hojo.jp/",
            "source_fetched_at": None,
            "publisher": "全国中小企業団体中央会 ものづくり補助金事務局",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "manufacturing_programs": matched,
        "enforcement_distribution_n": enforcement_n,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "manufacturing_program_count": len(matched),
            "enforcement_distribution_n": enforcement_n,
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
