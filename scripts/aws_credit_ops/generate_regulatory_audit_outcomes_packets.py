#!/usr/bin/env python3
"""Generate ``regulatory_audit_outcomes_v1`` packets (Wave 63 #10 of 10).

業種 (JSIC major) ごとに 規制監査結果 + 改善命令 + 業務改善命令 累積 outcome
を proxy 集計し、descriptive regulatory audit outcomes signal として packet
化する。監査内容 / 改善命令詳細 / 是正措置内容は所管官庁 + 監査法人 + 一次
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

PACKAGE_KIND: Final[str] = "regulatory_audit_outcomes_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

AUDIT_KEYWORDS: Final[tuple[str, ...]] = (
    "監査", "規制監査", "立入検査", "業務改善", "改善命令",
    "業務停止", "是正", "勧告", "指導", "監督",
    "コンプライアンス", "内部統制", "業務監査",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulatory audit outcomes packet は jpi_programs name + 監査 "
    "keyword 検索 + am_enforcement_detail 業務改善+ライセンス取消+業務停止 "
    "kind 集計から業種別 規制監査結果 + 改善命令 + 業務停止 累積 outcome を "
    "集計した descriptive 指標です。監査内容 / 改善命令詳細 / 是正措置内容は "
    "所管官庁 + 監査法人 + 一次資料が前提。"
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

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in AUDIT_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in AUDIT_KEYWORDS)
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

    # Outcome distribution: improvement/revoke/suspend across audit-related kinds.
    audit_outcomes: dict[str, int] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT enforcement_kind, COUNT(*) AS c "
            "  FROM am_enforcement_detail "
            " WHERE enforcement_kind IN ("
            "  'business_improvement','license_revoke','contract_suspend',"
            "  'investigation','other'"
            " ) "
            " GROUP BY enforcement_kind ORDER BY c DESC LIMIT 6"
        ):
            audit_outcomes[str(r["enforcement_kind"]) or "unknown"] = int(
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
            "audit_programs": matches,
            "audit_outcome_distribution": audit_outcomes,
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
    matched = list(row.get("audit_programs", []))
    outcomes = dict(row.get("audit_outcome_distribution") or {})
    rows_in_packet = len(matched) + len(outcomes)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "監査内容 / 改善命令詳細 / 是正措置内容は "
                "所管官庁 + 監査法人 + 一次資料が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で 監査 keyword + audit outcome 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.bao-jftc.go.jp/",
            "source_fetched_at": None,
            "publisher": "公的監査制度・改善命令 (各省庁横断)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.fsa.go.jp/policy/auditfirms/",
            "source_fetched_at": None,
            "publisher": "金融庁 監査監督",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "audit_programs": matched,
        "audit_outcome_distribution": outcomes,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "audit_program_count": len(matched),
            "audit_outcome_kind_count": len(outcomes),
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
