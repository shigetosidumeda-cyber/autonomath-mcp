#!/usr/bin/env python3
"""Generate ``patent_corp_360_v1`` packets (Wave 53.3 #1).

法人 × 特許 (JPO J14) cross-link packet. Combines ``houjin_master`` with
fact-level patent signals (``program.cap_patent_jpy`` / patent-bearing
support orgs) plus authority-side patent statistics to surface the patent
density per 法人 at descriptive granularity.

Cohort
------

::

    cohort = houjin_bangou (13-digit)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "patent_corp_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 patent corp 360 packet は houjin_master + 採択履歴 + 特許関連の制度上限額"
    "ファクトの descriptive 名寄せです。実際の特許権所有・出願は特許情報"
    "プラットフォーム (J-PlatPat / JPO) を一次確認してください "
    "(弁理士法 §75 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return

    # Step 1: rank houjin by adoption activity (proxy for patent-eligible scale)
    sql = (
        "SELECT houjin_bangou, normalized_name, prefecture, jsic_major, "
        "       total_adoptions, total_received_yen "
        "  FROM houjin_master "
        " WHERE houjin_bangou IS NOT NULL "
        "   AND length(houjin_bangou) = 13 "
        " ORDER BY total_received_yen DESC NULLS LAST, total_adoptions DESC "
        " LIMIT ?"
    )
    cap = int(limit) if limit is not None else 200000
    rows = list(primary_conn.execute(sql, (cap,)))

    for emitted, row in enumerate(rows):
        bangou = str(row["houjin_bangou"])
        record: dict[str, Any] = {
            "houjin_bangou": bangou,
            "normalized_name": row["normalized_name"],
            "prefecture": row["prefecture"],
            "jsic_major": row["jsic_major"],
            "total_adoptions": int(row["total_adoptions"] or 0),
            "total_received_yen": int(row["total_received_yen"] or 0),
            "patent_signals": [],
            "patent_cap_programs": [],
        }

        # Step 2: pull patent-related program adoption history (program.cap_patent_jpy)
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for adoption in primary_conn.execute(
                    "SELECT program_id, program_name_raw, amount_granted_yen, "
                    "       announced_at, source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    "   AND program_name_raw LIKE '%特許%' "
                    " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                    " LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    record["patent_signals"].append(
                        {
                            "program_id": adoption["program_id"],
                            "program_name": adoption["program_name_raw"],
                            "amount_yen": int(adoption["amount_granted_yen"] or 0),
                            "announced_at": adoption["announced_at"],
                            "source_url": adoption["source_url"],
                        }
                    )

        # Step 3: program-level patent cap facts
        if table_exists(primary_conn, "am_entity_facts"):
            with contextlib.suppress(Exception):
                for fact in primary_conn.execute(
                    "SELECT entity_id, field_value_numeric, unit, source_url "
                    "  FROM am_entity_facts "
                    " WHERE field_name = 'program.cap_patent_jpy' "
                    "   AND field_value_numeric IS NOT NULL "
                    " ORDER BY field_value_numeric DESC "
                    " LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    record["patent_cap_programs"].append(
                        {
                            "program_entity_id": fact["entity_id"],
                            "cap_yen": int(fact["field_value_numeric"] or 0),
                            "unit": fact["unit"],
                            "source_url": fact["source_url"],
                        }
                    )

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    patent_signals = list(row.get("patent_signals", []))
    patent_caps = list(row.get("patent_cap_programs", []))
    rows_in_packet = len(patent_signals) + len(patent_caps)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "特許権所有・出願の正本は J-PlatPat (JPO) — 本 packet は補助金"
                "採択に基づく descriptive proxy です。弁理士確認推奨。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "特許関連シグナルが観測されない = 特許なしを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.j-platpat.inpit.go.jp/",
            "source_fetched_at": None,
            "publisher": "J-PlatPat (INPIT)",
            "license": "gov_standard",
        },
        {
            "source_url": f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={bangou}",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "patent_signal_count": len(patent_signals),
        "patent_cap_program_count": len(patent_caps),
        "total_received_yen": int(row.get("total_received_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
            "total_adoptions": int(row.get("total_adoptions") or 0),
        },
        "patent_signals": patent_signals,
        "patent_cap_programs": patent_caps,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": bangou, "houjin_bangou": bangou},
        metrics=metrics,
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
