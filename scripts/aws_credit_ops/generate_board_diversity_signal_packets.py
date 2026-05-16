#!/usr/bin/env python3
"""Generate ``board_diversity_signal_v1`` packets (Wave 63 #1 of 10).

業種 (JSIC major) ごとに 役員構成 + 多様性 signal を proxy 集計し、
descriptive board diversity / governance signal として packet 化する。
役員多様性は外形的な name-prefix + corporation_type 推定であり、
gender / 国籍 / 経歴 等の definitive 判断は登記 + 一次資料が前提。

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

PACKAGE_KIND: Final[str] = "board_diversity_signal_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

GOVERNANCE_KEYWORDS: Final[tuple[str, ...]] = (
    "役員", "取締役", "監査役", "ガバナンス", "コーポレートガバナンス",
    "多様性", "ダイバーシティ", "女性活躍", "女性役員", "社外取締役",
    "報酬", "兼任",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 board diversity signal packet は jpi_programs name + governance "
    "keyword 検索 + jpi_houjin_master corporation_type 分布から業種別 役員 "
    "× 多様性 制度 proxy を集計した descriptive 指標です。gender / 国籍 / "
    "経歴 等の definitive 判断は登記 + 一次資料が前提 (§52 / 司法書士法 §3)。"
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

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in GOVERNANCE_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in GOVERNANCE_KEYWORDS)
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

    # Pull corporation_type distribution as a governance-structure proxy.
    corp_dist: dict[str, int] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT corporation_type, COUNT(*) AS c "
            "  FROM jpi_houjin_master "
            " WHERE corporation_type IS NOT NULL "
            " GROUP BY corporation_type ORDER BY c DESC LIMIT 8"
        ):
            corp_dist[str(r["corporation_type"]) or "unknown"] = int(r["c"] or 0)

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
            "governance_programs": matches,
            "corporation_type_distribution": corp_dist,
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
    matched = list(row.get("governance_programs", []))
    corp_dist = dict(row.get("corporation_type_distribution") or {})
    rows_in_packet = len(matched) + len(corp_dist)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "gender / 国籍 / 経歴 等の definitive 判断は登記 + 一次資料が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で governance keyword + corp_type 分布 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.fsa.go.jp/policy/follow-up/governance/",
            "source_fetched_at": None,
            "publisher": "金融庁 コーポレートガバナンス",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.gender.go.jp/",
            "source_fetched_at": None,
            "publisher": "内閣府 男女共同参画局",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "governance_programs": matched,
        "corporation_type_distribution": corp_dist,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "governance_program_count": len(matched),
            "corp_type_kind_count": len(corp_dist),
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
