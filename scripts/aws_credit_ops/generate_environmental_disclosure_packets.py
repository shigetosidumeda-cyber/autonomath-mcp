#!/usr/bin/env python3
"""Generate ``environmental_disclosure_v1`` packets (Wave 63 #7 of 10).

業種 (JSIC major) ごとに 環境情報開示 (温対法 / GHG / TCFD) 制度密度を proxy
集計し、descriptive environmental disclosure signal として packet 化する。
温対法報告義務 / GHG 算定境界 / TCFD 開示判断は環境省 + 経産省 + 一次資料
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

PACKAGE_KIND: Final[str] = "environmental_disclosure_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

ENV_DISCLOSURE_KEYWORDS: Final[tuple[str, ...]] = (
    "温対法", "地球温暖化対策", "GHG", "温室効果ガス", "CO2",
    "脱炭素", "カーボンニュートラル", "TCFD", "SBT", "Scope1",
    "気候変動", "サステナビリティ", "環境報告", "CDP",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 environmental disclosure packet は jpi_programs name + 環境開示 "
    "keyword 検索 + jpi_pc_program_geographic_density proxy から業種別 "
    "環境情報開示 制度密度を集計した descriptive 指標です。温対法報告義務 / "
    "GHG 算定境界 / TCFD 開示判断は環境省 + 経産省 + 一次資料が前提 (温対法 §26)。"
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

    where_clauses = " OR ".join(
        ["primary_name LIKE ?" for _ in ENV_DISCLOSURE_KEYWORDS]
    )
    params = tuple(f"%{kw}%" for kw in ENV_DISCLOSURE_KEYWORDS)
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

    # Pull a small program-geographic density signal as cohort-level context.
    density_n = 0
    with contextlib.suppress(Exception):
        row = primary_conn.execute(
            "SELECT COUNT(*) AS c FROM jpi_pc_program_geographic_density"
        ).fetchone()
        if row:
            density_n = int(row["c"] or 0)

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
            "env_disclosure_programs": matches,
            "program_density_pool_n": density_n,
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
    matched = list(row.get("env_disclosure_programs", []))
    density_n = int(row.get("program_density_pool_n") or 0)
    rows_in_packet = len(matched) + (1 if density_n > 0 else 0)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "温対法報告義務 / GHG 算定境界 / TCFD 開示判断は "
                "環境省 + 経産省 + 一次資料が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "該 jsic_major で 環境開示 keyword + 地理密度 観測無し"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.env.go.jp/earth/ondanka/ghg/",
            "source_fetched_at": None,
            "publisher": "環境省 温対法 算定・報告・公表制度",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/energy_environment/global_warming/",
            "source_fetched_at": None,
            "publisher": "経済産業省 地球温暖化対策",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "env_disclosure_programs": matched,
        "program_density_pool_n": density_n,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "env_disclosure_program_count": len(matched),
            "program_density_pool_n": density_n,
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
