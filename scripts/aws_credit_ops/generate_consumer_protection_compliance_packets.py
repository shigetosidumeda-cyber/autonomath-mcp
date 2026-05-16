#!/usr/bin/env python3
"""Generate ``consumer_protection_compliance_v1`` packets (Wave 63 #6 of 10).

業種 (JSIC major) ごとに 消費者保護法 compliance + 行政指導 密度を proxy
集計し、descriptive consumer protection compliance signal として packet 化
する。違反認定 / 行政処分内容 / 消費者契約法判断は消費者庁 + 弁護士 + 一次資料
が前提。

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

PACKAGE_KIND: Final[str] = "consumer_protection_compliance_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

CONSUMER_KEYWORDS: Final[tuple[str, ...]] = (
    "消費者保護", "消費者契約", "景表法", "景品表示", "特定商取引",
    "特商法", "消費生活", "PL法", "製造物責任", "クーリングオフ",
    "誤認表示", "優良誤認", "有利誤認",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 consumer protection compliance packet は jpi_programs name + "
    "消費者 keyword 検索 + am_enforcement_detail business_improvement "
    "kind 集計から業種別 消費者保護法 compliance + 行政指導 密度を集計した "
    "descriptive 指標です。違反認定 / 行政処分内容 / 消費者契約法判断は "
    "消費者庁 + 弁護士 + 一次資料が前提 (景表法 §5 / 特商法 §3)。"
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

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in CONSUMER_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in CONSUMER_KEYWORDS)
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

    business_improvement_n = 0
    with contextlib.suppress(Exception):
        row = primary_conn.execute(
            "SELECT COUNT(*) AS c FROM am_enforcement_detail "
            " WHERE enforcement_kind = 'business_improvement'"
        ).fetchone()
        if row:
            business_improvement_n = int(row["c"] or 0)

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
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "consumer_programs": matches,
            "business_improvement_pool_n": business_improvement_n,
            "candidate_pool_size": len(candidates),
        }
        if matches or business_improvement_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    matched = list(row.get("consumer_programs", []))
    bi_n = int(row.get("business_improvement_pool_n") or 0)
    rows_in_packet = len(matched) + (1 if bi_n > 0 else 0)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "違反認定 / 行政処分内容 / 消費者契約法判断は "
                "消費者庁 + 弁護士 + 一次資料が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で 消費者 keyword + business_improvement 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.caa.go.jp/",
            "source_fetched_at": None,
            "publisher": "消費者庁",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.no-trouble.caa.go.jp/",
            "source_fetched_at": None,
            "publisher": "消費者庁 国民生活センター",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "consumer_programs": matched,
        "business_improvement_pool_n": bi_n,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "consumer_program_count": len(matched),
            "business_improvement_pool_n": bi_n,
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
