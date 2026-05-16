#!/usr/bin/env python3
"""Generate ``insider_trading_disclosure_v1`` packets (Wave 63 #2 of 10).

業種 (JSIC major) ごとに 内部者取引 + 適時開示 制度密度を proxy 集計し、
descriptive insider trading disclosure timeliness signal として packet 化する。
個別事案の判断 / 違反認定は SESC + 取引所 + 一次資料が前提。

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

PACKAGE_KIND: Final[str] = "insider_trading_disclosure_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

INSIDER_KEYWORDS: Final[tuple[str, ...]] = (
    "内部者", "インサイダー", "適時開示", "重要事実", "公開買付",
    "TOB", "金商法", "金融商品取引法", "有価証券報告書", "決算短信",
    "臨時報告", "発行登録", "上場",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 insider trading × disclosure packet は jpi_programs name + insider "
    "keyword 検索 + am_enforcement_detail 違反集計から業種別 内部者取引 × "
    "適時開示 制度密度を集計した descriptive 指標です。個別事案の判断 / "
    "違反認定は SESC + 取引所 + 一次資料が前提 (金商法 §166 / §175)。"
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

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in INSIDER_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in INSIDER_KEYWORDS)
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

    # Pull enforcement_detail volume for disclosure-related authorities.
    enforcement_kinds: dict[str, int] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT enforcement_kind, COUNT(*) AS c "
            "  FROM am_enforcement_detail "
            " WHERE issuing_authority LIKE '%金融%' "
            "    OR issuing_authority LIKE '%証券%' "
            "    OR issuing_authority LIKE '%取引所%' "
            " GROUP BY enforcement_kind ORDER BY c DESC LIMIT 8"
        ):
            enforcement_kinds[str(r["enforcement_kind"]) or "unknown"] = int(
                r["c"] or 0
            )

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
            "disclosure_programs": matches,
            "financial_enforcement_kinds": enforcement_kinds,
            "candidate_pool_size": len(candidates),
        }
        if matches:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    matched = list(row.get("disclosure_programs", []))
    enf_kinds = dict(row.get("financial_enforcement_kinds") or {})
    rows_in_packet = len(matched) + len(enf_kinds)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "個別事案の判断 / 違反認定は SESC + 取引所 + 一次資料が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で insider keyword + 金融行政処分 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.fsa.go.jp/sesc/",
            "source_fetched_at": None,
            "publisher": "証券取引等監視委員会 (SESC)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jpx.co.jp/listing/disclosure/",
            "source_fetched_at": None,
            "publisher": "日本取引所グループ 適時開示",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "disclosure_programs": matched,
        "financial_enforcement_kinds": enf_kinds,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "disclosure_program_count": len(matched),
            "financial_enforcement_kind_count": len(enf_kinds),
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
