#!/usr/bin/env python3
"""Generate ``corporate_360_snapshot_v1`` packets (Wave 99 #6 of 10).

houjin_master + jpi_adoption_records + am_enforcement_detail を 3 axis
snapshot として rollup し、houjin_360 MCP tool の事前 baseline を packet 化
する。本格的 houjin_360 (`scripts/aws_credit_ops/generate_houjin_360_packets.py`)
の full corpus 166K cohort とは別に、**業種 (jsic_major) × 規模 cohort** に
切り出した snapshot をペイロードとして提供する軽量 packet。

Cohort
------
::

    cohort = jsic_major (A-V) — am_industry_jsic.jsic_level='major'
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

PACKAGE_KIND: Final[str] = "corporate_360_snapshot_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 corporate 360 snapshot packet は houjin_master + jpi_adoption_records + "
    "am_enforcement_detail を業種 (jsic_major) 単位で rollup した descriptive "
    "snapshot で、与信判断 / 個社評価には用いず、税理士法 §52・弁護士法 §72・"
    "行政書士法 §1の2 のいずれにも該当しない。**個社の与信・税務・法令適用判断は "
    "顧問専門家の一次確認が前提**。"
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
        # axis 1: corporate identity — count via am_entity_facts on the
        # canonical ``corp.jsic_major`` field_name (indexed by entity_id +
        # field_name). Avoids json_extract scan over 166K am_entities rows
        # which on 9.4 GB DB takes minutes; the facts path is 2-8 ms.
        houjin_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(DISTINCT entity_id) AS n FROM am_entity_facts "
                " WHERE field_name = 'corp.jsic_major' "
                "   AND field_value_text = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                houjin_n = int(row["n"] or 0)

        # axis 2: adoption (jpi_adoption_records industry_jsic_medium).
        adoption_n = 0
        adoption_total_yen = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(amount_granted_yen), 0) AS amt "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
                adoption_total_yen = int(row["amt"] or 0)

        # axis 3: enforcement — join via am_enforcement_detail.entity_id which
        # is the corporate canonical_id, looked up via the same fact-based
        # cohort. Sub-query is bounded by jsic match set, no full table scan.
        enforcement_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n FROM am_enforcement_detail e "
                " WHERE e.entity_id IN ("
                "   SELECT entity_id FROM am_entity_facts "
                "    WHERE field_name = 'corp.jsic_major' "
                "      AND field_value_text = ?)",
                (jsic_code,),
            ).fetchone()
            if row:
                enforcement_n = int(row["n"] or 0)

        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "houjin_n": houjin_n,
            "adoption_n": adoption_n,
            "adoption_total_yen": adoption_total_yen,
            "enforcement_n": enforcement_n,
        }
        if houjin_n > 0 or adoption_n > 0 or enforcement_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    houjin_n = int(row.get("houjin_n") or 0)
    adoption_n = int(row.get("adoption_n") or 0)
    adoption_total_yen = int(row.get("adoption_total_yen") or 0)
    enforcement_n = int(row.get("enforcement_n") or 0)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    rows_in_packet = houjin_n + adoption_n + enforcement_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "個社の与信 / 税務 / 法令適用判断は 顧問税理士・弁護士・行政書士 の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で 3 axis 全て観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "経済産業省 gBizINFO",
            "license": "cc_by_4.0",
        },
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]

    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "axis_corporate_identity": {"houjin_n": houjin_n},
        "axis_adoption": {
            "adoption_n": adoption_n,
            "adoption_total_yen": adoption_total_yen,
        },
        "axis_enforcement": {"enforcement_n": enforcement_n},
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "houjin_n": houjin_n,
            "adoption_n": adoption_n,
            "enforcement_n": enforcement_n,
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
