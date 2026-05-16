#!/usr/bin/env python3
"""Generate ``trademark_brand_protection_v1`` packets (Wave 53.3 #6).

法人 × 商標 (JPO J14) 360 packet. Surfaces ``program.cap_bad_faith_trademark_jpy``
+ ``program.cap_design_trademark_jpy`` facts as program-level brand
protection signals against houjin_master rows, plus 採択履歴 of trademark
名 hits (商標 / brand / ブランド) in program_name_raw.

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

PACKAGE_KIND: Final[str] = "trademark_brand_protection_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 trademark brand protection packet は houjin_master + 商標関連の補助金"
    "上限額ファクト + 採択履歴の descriptive 紐付けです。商標登録の正本は "
    "J-PlatPat (商標) を一次確認、商標出願業務は弁理士が行います "
    "(弁理士法 §75)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return

    cap = int(limit) if limit is not None else 100000
    sql = (
        "SELECT houjin_bangou, normalized_name, prefecture, jsic_major "
        "  FROM houjin_master "
        " WHERE houjin_bangou IS NOT NULL "
        "   AND length(houjin_bangou) = 13 "
        " ORDER BY total_received_yen DESC NULLS LAST "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        record: dict[str, Any] = {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "trademark_adoption_rows": [],
            "trademark_program_caps": [],
        }
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for ad in primary_conn.execute(
                    "SELECT program_id, program_name_raw, amount_granted_yen, "
                    "       announced_at, source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    "   AND (program_name_raw LIKE '%商標%' "
                    "        OR program_name_raw LIKE '%ブランド%' "
                    "        OR program_name_raw LIKE '%意匠%') "
                    " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                    " LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    record["trademark_adoption_rows"].append(
                        {
                            "program_id": ad["program_id"],
                            "program_name": ad["program_name_raw"],
                            "amount_yen": int(ad["amount_granted_yen"] or 0),
                            "announced_at": ad["announced_at"],
                            "source_url": ad["source_url"],
                        }
                    )
        if table_exists(primary_conn, "am_entity_facts"):
            with contextlib.suppress(Exception):
                for fact in primary_conn.execute(
                    "SELECT entity_id, field_name, field_value_numeric, unit, "
                    "       source_url "
                    "  FROM am_entity_facts "
                    " WHERE field_name IN "
                    "       ('program.cap_bad_faith_trademark_jpy', "
                    "        'program.cap_design_trademark_jpy') "
                    "   AND field_value_numeric IS NOT NULL "
                    " ORDER BY field_value_numeric DESC "
                    " LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    record["trademark_program_caps"].append(
                        {
                            "program_entity_id": fact["entity_id"],
                            "field_name": fact["field_name"],
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
    adoptions = list(row.get("trademark_adoption_rows", []))
    caps = list(row.get("trademark_program_caps", []))
    rows_in_packet = len(adoptions) + len(caps)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "商標登録状況は J-PlatPat (商標) を一次確認。商標出願は"
                "弁理士業務 (弁理士法 §75)。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "商標関連シグナル無し = 商標未保有を意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.j-platpat.inpit.go.jp/t0/",
            "source_fetched_at": None,
            "publisher": "J-PlatPat 商標検索",
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
        "trademark_adoption_count": len(adoptions),
        "trademark_program_cap_count": len(caps),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "trademark_adoption_rows": adoptions,
        "trademark_program_caps": caps,
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
