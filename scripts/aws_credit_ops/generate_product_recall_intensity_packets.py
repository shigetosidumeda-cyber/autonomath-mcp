#!/usr/bin/env python3
"""Generate ``product_recall_intensity_v1`` packets (Wave 63 #9 of 10).

業種 (JSIC major) ごとに 製品リコール + PL関連 行政処分 累積 intensity を
proxy 集計し、descriptive product recall intensity signal として packet 化
する。リコール対象品判定 / PL責任認定は消費者庁 + 経産省 + 製造業者 + 一次
資料が前提。

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

PACKAGE_KIND: Final[str] = "product_recall_intensity_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

RECALL_KEYWORDS: Final[tuple[str, ...]] = (
    "リコール", "製品回収", "回収", "PL", "製造物責任",
    "欠陥", "安全規格", "PSマーク", "技適", "薬機法",
    "医薬品", "食品衛生", "食品安全", "事故報告",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 product recall intensity packet は jpi_programs name + リコール "
    "keyword 検索 + am_enforcement_anomaly enforcement_count 集計から業種別 "
    "リコール + PL関連 累積 intensity を集計した descriptive 指標です。"
    "リコール対象品判定 / PL責任認定は消費者庁 + 経産省 + 製造業者 + 一次資料"
    "が前提 (PL法 §3 / 消費生活用製品安全法)。"
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

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in RECALL_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in RECALL_KEYWORDS)
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

    # Pull anomaly counts indexed by jsic_major as a sectoral intensity proxy.
    anomaly_by_jsic: dict[str, int] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_major, SUM(enforcement_count) AS s "
            "  FROM am_enforcement_anomaly "
            " WHERE jsic_major IS NOT NULL "
            " GROUP BY jsic_major"
        ):
            anomaly_by_jsic[str(r["jsic_major"]) or "?"] = int(r["s"] or 0)

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
        intensity_n = int(anomaly_by_jsic.get(jsic_code, 0))
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "recall_programs": matches,
            "anomaly_intensity_n": intensity_n,
            "candidate_pool_size": len(candidates),
        }
        if matches or intensity_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    matched = list(row.get("recall_programs", []))
    intensity_n = int(row.get("anomaly_intensity_n") or 0)
    rows_in_packet = len(matched) + (1 if intensity_n > 0 else 0)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "リコール対象品判定 / PL責任認定は "
                "消費者庁 + 経産省 + 製造業者 + 一次資料が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で recall keyword + anomaly intensity 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.recall.caa.go.jp/",
            "source_fetched_at": None,
            "publisher": "消費者庁 リコール情報",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/product_safety/recall/",
            "source_fetched_at": None,
            "publisher": "経済産業省 製品安全 リコール",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "recall_programs": matched,
        "anomaly_intensity_n": intensity_n,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "recall_program_count": len(matched),
            "anomaly_intensity_n": intensity_n,
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
