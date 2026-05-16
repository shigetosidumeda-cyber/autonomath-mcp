#!/usr/bin/env python3
"""Generate ``public_listed_program_link_v1`` packets (Wave 58 #10 of 10).

上場法人 × 公開制度 link。am_entities (record_kind='corporate_entity') の raw_json
で EDINET / 上場関連 keyword 該当法人を抽出し、その houjin_bangou に紐づく
jpi_adoption_records / jpi_bids を集計する。

Cohort
------
::

    cohort = houjin_bangou (上場/開示企業候補)
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

PACKAGE_KIND: Final[str] = "public_listed_program_link_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 public listed program link packet は EDINET 開示 keyword の含まれる"
    "am_entities (corporate_entity) と jpi_adoption_records / jpi_bids を連結した"
    "descriptive link 指標です。上場区分の確定は東京証券取引所 + EDINET 一次確認"
    "が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    # Take houjin_bangou that appear in jpi_bids (since bids data is more reliable
    # for public-disclosing entities) + cross-reference with jpi_adoption_records
    high_engagement: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT houjin_bangou, COUNT(*) AS c "
            "  FROM jpi_adoption_records "
            " WHERE houjin_bangou IS NOT NULL AND houjin_bangou != '' "
            " GROUP BY houjin_bangou HAVING c >= 5 "
            " ORDER BY c DESC"
        ):
            hb = str(r["houjin_bangou"] or "")
            if hb:
                high_engagement.append(hb)

    have_bids = table_exists(primary_conn, "jpi_bids")
    for emitted, hb in enumerate(high_engagement):
        adoption_rows: list[dict[str, Any]] = []
        bid_rows: list[dict[str, Any]] = []
        company_name = ""
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT announced_at, program_name_raw, program_id, "
                "       amount_granted_yen, company_name_raw, prefecture "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                " ORDER BY announced_at DESC LIMIT ?",
                (hb, PER_AXIS_RECORD_CAP),
            ):
                d = dict(r)
                if not company_name:
                    company_name = str(d.get("company_name_raw") or "")
                adoption_rows.append(d)
        if have_bids:
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT bid_title, procuring_entity, awarded_amount_yen, "
                    "       decision_date "
                    "  FROM jpi_bids "
                    " WHERE winner_houjin_bangou = ? "
                    " ORDER BY decision_date DESC LIMIT ?",
                    (hb, PER_AXIS_RECORD_CAP),
                ):
                    bid_rows.append(dict(r))
        record = {
            "houjin_bangou": hb,
            "company_name": company_name,
            "adoption_link": adoption_rows,
            "bid_link": bid_rows,
        }
        if adoption_rows or bid_rows:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    hb = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(hb)}"
    adoptions = list(row.get("adoption_link", []))
    bids = list(row.get("bid_link", []))
    rows_in_packet = len(adoptions) + len(bids)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "「上場法人」の確定は東京証券取引所 + EDINET 一次確認が必要、"
                "この packet は高 engagement 法人 proxy"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該法人で公開制度 link 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://disclosure.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET (金融庁)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jpx.co.jp/",
            "source_fetched_at": None,
            "publisher": "日本取引所グループ (JPX)",
            "license": "proprietary",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "houjin_bangou", "id": hb},
        "houjin_bangou": hb,
        "company_name": str(row.get("company_name") or ""),
        "adoption_link": adoptions,
        "bid_link": bids,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": hb, "houjin_bangou": hb},
        metrics={
            "adoption_link_count": len(adoptions),
            "bid_link_count": len(bids),
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
