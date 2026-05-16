#!/usr/bin/env python3
"""Generate ``conflict_mineral_disclosure_v1`` packets (Wave 81 #10 of 10).

業種 (JSIC major) ごとに 紛争鉱物 (conflict mineral) disclosure 兆候
(採択密度 proxy) を集計し、descriptive sectoral conflict mineral
disclosure indicator として packet 化する。3TG (Tin / Tantalum /
Tungsten / Gold) + コバルト サプライチェーン due diligence / US Dodd-
Frank Act §1502 / EU Conflict Minerals Regulation / OECD DRC 紛争鉱物
DD ガイダンス / RMI (Responsible Minerals Initiative) CMRT 対応判断は
経産省 + 外務省 + JOGMEC + 紛争鉱物 DD 実務者の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "conflict_mineral_disclosure_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 conflict mineral disclosure packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、3TG (Tin / Tantalum / "
    "Tungsten / Gold) + Cobalt サプライチェーン due diligence / US Dodd-Frank "
    "Act §1502 / EU Conflict Minerals Regulation / OECD DRC 紛争鉱物 DD ガイ"
    "ダンス / RMI CMRT (Conflict Minerals Reporting Template) 対応判断は経産省 "
    "+ 外務省 + JOGMEC + 紛争鉱物 DD 実務者の一次確認が前提です "
    "(経産省 責任ある鉱物調達 ガイダンス, US Dodd-Frank §1502, EU Regulation "
    "2017/821, OECD Due Diligence Guidance for Responsible Supply Chains)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        adoption_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n FROM jpi_adoption_records  WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
        }
        if adoption_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    adoption_n = int(row.get("adoption_n") or 0)
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "3TG + Cobalt サプライチェーン DD / US Dodd-Frank §1502 / "
                "EU Conflict Minerals Regulation / OECD DRC DD / RMI CMRT "
                "対応判断は経産省 + 外務省 + JOGMEC + 紛争鉱物 DD 実務者の"
                "一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で adoption record 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.meti.go.jp/policy/external_economy/trade_control/05_cooperation/responsible_mineral_sourcing.html",
            "source_fetched_at": None,
            "publisher": "経済産業省 責任ある鉱物調達",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jogmec.go.jp/metal/metal_10_000019.html",
            "source_fetched_at": None,
            "publisher": "JOGMEC エネルギー・金属鉱物資源機構 責任ある鉱物調達",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
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
