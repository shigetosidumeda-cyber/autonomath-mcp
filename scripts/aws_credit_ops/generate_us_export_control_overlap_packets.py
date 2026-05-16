#!/usr/bin/env python3
"""Generate ``us_export_control_overlap_v1`` packets (Wave 64 #6 of 10).

業種 (JSIC major) ごとに 米輸出規制 (EAR / ITAR) × 経産省 安保輸出管理
overlap 関連制度を集約し、descriptive sectoral US export control × METI
overlap density proxy として packet 化する。EAR / ITAR / 外為法判断は
所管官庁 + 国際通商弁護士の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "us_export_control_overlap_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

SECTOR_KEYWORDS: Final[tuple[str, ...]] = (
    "EAR", "ITAR", "安全保障", "安保輸出", "経済安全保障", "デュアルユース",
    "輸出管理", "リスト規制", "キャッチオール", "BIS", "米国", "規制対象",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 US export control × METI overlap packet は jpi_programs name + EAR/"
    "ITAR/安保輸出 keyword 検索による descriptive 指標です。EAR (Export "
    "Administration Regulations) / ITAR (International Traffic in Arms "
    "Regulations) / 外為法 (外国為替及び外国貿易法) 適用判断は所管官庁 "
    "(経産省 / 米国商務省 BIS / 米国国務省) + 国際通商弁護士の一次確認が"
    "前提 (弁護士法 §72)。"
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
            "us_export_control_programs": matches,
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
    matched = list(row.get("us_export_control_programs", []))
    enforcement_n = int(row.get("enforcement_distribution_n") or 0)
    rows_in_packet = len(matched) + enforcement_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "EAR / ITAR / 外為法適用判断は所管官庁 + 国際通商弁護士の"
                "一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で 米輸出規制 keyword + 行政処分密度 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.meti.go.jp/policy/anpo/",
            "source_fetched_at": None,
            "publisher": "経済産業省 安全保障貿易管理",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.bis.doc.gov/",
            "source_fetched_at": None,
            "publisher": "U.S. Bureau of Industry and Security (BIS)",
            "license": "public_domain",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "us_export_control_programs": matched,
        "enforcement_distribution_n": enforcement_n,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "us_export_control_program_count": len(matched),
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
