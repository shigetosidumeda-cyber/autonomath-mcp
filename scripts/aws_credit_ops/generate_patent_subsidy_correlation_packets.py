#!/usr/bin/env python3
"""Generate ``patent_subsidy_correlation_v1`` packets (Wave 55 #5).

特許出願 (JPO J14 proxy via 知財 keyword) × 補助金採択 (J05) × 業種
(JSIC) cross-link packet. For each JSIC major, surface adoption records
whose program names include 特許/知財/INPIT/弁理/実用新案/意匠 fence
keywords as a descriptive proxy for "知財投資 ROI" cohort. We do not
join to JPO J-PlatPat directly (out of scope); the packet documents the
adoption side and flags the unjoined gap.

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

PACKAGE_KIND: Final[str] = "patent_subsidy_correlation_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

_PATENT_KEYWORDS: Final[tuple[str, ...]] = (
    "特許",
    "知財",
    "INPIT",
    "弁理",
    "実用新案",
    "意匠",
    "ものづくり",
    "事業再構築",
    "新事業",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 patent subsidy correlation packet は 採択履歴 × 業種 × 知財キーワード "
    "の descriptive cross-link です。特許出願・登録の正本は J-PlatPat "
    "(INPIT) を一次確認、知財投資 ROI 評価は弁理士判断が前提です "
    "(弁理士法 §75 boundaries)。"
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

    like_clauses = " OR ".join("program_name_raw LIKE ?" for _ in _PATENT_KEYWORDS)
    like_params = tuple(f"%{kw}%" for kw in _PATENT_KEYWORDS)

    for emitted, (jsic_code, jsic_name) in enumerate(jsic_majors):
        record: dict[str, Any] = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "industry_patent_adoption_count": 0,
            "industry_total_amount_yen": 0,
            "top_recipients": [],
            "sample_programs": [],
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount_granted_yen), 0) AS s "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ? "
                f"  AND ({like_clauses})",
                (jsic_code, *like_params),
            ):
                record["industry_patent_adoption_count"] = int(r["c"] or 0)
                record["industry_total_amount_yen"] = int(r["s"] or 0)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT houjin_bangou, "
                "       COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ? "
                f"  AND ({like_clauses}) "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13 "
                " GROUP BY houjin_bangou "
                " ORDER BY total_amount_yen DESC "
                " LIMIT ?",
                (jsic_code, *like_params, PER_AXIS_RECORD_CAP),
            ):
                record["top_recipients"].append(
                    {
                        "houjin_bangou": r["houjin_bangou"],
                        "adoptions": int(r["adoptions"] or 0),
                        "total_amount_yen": int(r["total_amount_yen"] or 0),
                    }
                )
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT program_name_raw, "
                "       COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE industry_jsic_medium IS NOT NULL "
                "   AND substr(industry_jsic_medium, 1, 1) = ? "
                f"  AND ({like_clauses}) "
                " GROUP BY program_name_raw "
                " ORDER BY total_amount_yen DESC "
                " LIMIT ?",
                (jsic_code, *like_params, PER_AXIS_RECORD_CAP),
            ):
                record["sample_programs"].append(
                    {
                        "program_name": r["program_name_raw"],
                        "adoptions": int(r["adoptions"] or 0),
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
    progs = list(row.get("sample_programs", []))
    rows_in_packet = len(recipients) + len(progs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "特許出願・登録の正本は J-PlatPat (INPIT)。知財 ROI 評価は "
                "弁理士判断が前提。本 packet は採択側 descriptive proxy で、"
                "JPO 側突合は未実施。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "業種別 知財キーワード採択無 — 知財投資無を意味しない",
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
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
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
        "industry_patent_adoption_count": int(
            row.get("industry_patent_adoption_count") or 0
        ),
        "industry_total_amount_yen": int(row.get("industry_total_amount_yen") or 0),
        "top_recipient_count": len(recipients),
        "sample_program_count": len(progs),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": row.get("jsic_name_ja"),
        "industry_patent_adoption_count": int(
            row.get("industry_patent_adoption_count") or 0
        ),
        "industry_total_amount_yen": int(row.get("industry_total_amount_yen") or 0),
        "top_recipients": recipients,
        "sample_programs": progs,
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
