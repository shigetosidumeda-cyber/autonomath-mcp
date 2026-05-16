#!/usr/bin/env python3
"""Generate ``gov_spending_efficiency_v1`` packets (Wave 55 #1).

補助金交付額 (J05) × 採択企業 EDINET 業績 (J13 proxy) × 業種 (JSIC) packet.
For each JSIC major, surface top 補助金 recipients by total amount and the
descriptive cross-link between adoption density × industry — a proxy for
"補助金の費用対効果". We do not compute ROI directly (EDINET 連結業績
matching requires per-houjin 有報 join which is out of scope for the
descriptive packet); instead we expose per-JSIC top-N recipient list
with adoption count, total received yen and per-recipient adoption
program diversity.

Cohort
------

::

    cohort = jsic_major (A..T)

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

PACKAGE_KIND: Final[str] = "gov_spending_efficiency_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 gov spending efficiency packet は採択履歴の JSIC 別 top-N 受給 houjin "
    "descriptive aggregate です。EDINET 連結業績 (J13) と突合した費用対効果"
    "数値の正本は EDINET XBRL を一次確認、業績影響評価は税理士・会計士の"
    "判断が前提です (税理士法 §52 / 公認会計士法 §47条の2 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    jsic_majors: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            jsic_majors.append((str(r["jsic_code"]), str(r["jsic_name_ja"] or "")))

    for emitted, (jsic_code, jsic_name) in enumerate(jsic_majors):
        record: dict[str, Any] = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "industry_houjin_count": 0,
            "industry_total_amount_yen": 0,
            "industry_total_adoptions": 0,
            "top_recipients": [],
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(DISTINCT houjin_bangou) AS hc, "
                "       COUNT(*) AS ac, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS sa "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ?",
                (jsic_code,),
            ):
                record["industry_houjin_count"] = int(r["hc"] or 0)
                record["industry_total_adoptions"] = int(r["ac"] or 0)
                record["industry_total_amount_yen"] = int(r["sa"] or 0)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT houjin_bangou, "
                "       COUNT(*) AS adoptions, "
                "       COUNT(DISTINCT program_name_raw) AS program_diversity, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ? "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13 "
                " GROUP BY houjin_bangou "
                " ORDER BY total_amount_yen DESC "
                " LIMIT ?",
                (jsic_code, PER_AXIS_RECORD_CAP),
            ):
                record["top_recipients"].append(
                    {
                        "houjin_bangou": r["houjin_bangou"],
                        "adoptions": int(r["adoptions"] or 0),
                        "program_diversity": int(r["program_diversity"] or 0),
                        "total_amount_yen": int(r["total_amount_yen"] or 0),
                    }
                )

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    recipients = list(row.get("top_recipients", []))
    rows_in_packet = len(recipients)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "EDINET 業績との費用対効果評価は会計士・税理士確認が前提。"
                "本 packet は採択側 descriptive aggregate で、業績側突合は"
                "未実施。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "業種別 top-N 該当無 = 採択無しを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://disclosure2.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "industry_total_adoptions": int(row.get("industry_total_adoptions") or 0),
        "industry_total_amount_yen": int(row.get("industry_total_amount_yen") or 0),
        "top_recipient_count": len(recipients),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": row.get("jsic_name_ja"),
        "industry_houjin_count": int(row.get("industry_houjin_count") or 0),
        "industry_total_adoptions": int(row.get("industry_total_adoptions") or 0),
        "industry_total_amount_yen": int(row.get("industry_total_amount_yen") or 0),
        "top_recipients": recipients,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
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
