#!/usr/bin/env python3
"""Generate ``succession_match_3axis_v1`` packets (Wave 55 #3).

事業承継候補 × 事業内容類似度 (法人360 proxy) × 地域 cross-link packet.
Without M&A intent labels we lean on a proxy: each prefecture's set of
adopting houjin grouped by JSIC medium serves as the candidate pool, and
within-JSIC overlapping program adoption is used as a coarse similarity
ranking. Surfaces "都道府県 X で同業種 × 共通制度採択 を持つ houjin pair
候補" cohort summary — descriptive matching scaffold only.

Cohort
------

::

    cohort = prefecture (都道府県名)

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

PACKAGE_KIND: Final[str] = "succession_match_3axis_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 succession match 3-axis packet は事業内容類似度 + 地域 + 業種 の "
    "descriptive matching scaffold です。実際の M&A / 事業承継判断には "
    "DD 必須、税理士・弁護士・M&A advisor の確認が前提です (税理士法 §52 / "
    "弁護士法 §72 / 司法書士法 §3 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_adoption_records "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        record: dict[str, Any] = {
            "prefecture": pref,
            "candidate_count": 0,
            "industry_buckets": [],
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(DISTINCT houjin_bangou) AS c "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13",
                (pref,),
            ):
                record["candidate_count"] = int(r["c"] or 0)
        # Aggregate by JSIC medium first letter (major), top buckets by candidate count
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT substr(industry_jsic_medium, 1, 1) AS jsic_major, "
                "       COUNT(DISTINCT houjin_bangou) AS candidate_count, "
                "       COUNT(DISTINCT program_name_raw) AS program_diversity "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                "   AND industry_jsic_medium IS NOT NULL "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13 "
                " GROUP BY substr(industry_jsic_medium, 1, 1) "
                " ORDER BY candidate_count DESC "
                " LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                if (r["candidate_count"] or 0) < 2:
                    continue
                bucket: dict[str, Any] = {
                    "jsic_major": r["jsic_major"],
                    "candidate_count": int(r["candidate_count"] or 0),
                    "program_diversity": int(r["program_diversity"] or 0),
                    "common_program_top3": [],
                }
                with contextlib.suppress(Exception):
                    for p in primary_conn.execute(
                        "SELECT program_name_raw, "
                        "       COUNT(DISTINCT houjin_bangou) AS shared_houjin "
                        "  FROM jpi_adoption_records "
                        " WHERE prefecture = ? "
                        "   AND substr(industry_jsic_medium, 1, 1) = ? "
                        "   AND program_name_raw IS NOT NULL "
                        " GROUP BY program_name_raw "
                        " HAVING shared_houjin >= 2 "
                        " ORDER BY shared_houjin DESC "
                        " LIMIT 3",
                        (pref, r["jsic_major"]),
                    ):
                        bucket["common_program_top3"].append(
                            {
                                "program_name": p["program_name_raw"],
                                "shared_houjin": int(p["shared_houjin"] or 0),
                            }
                        )
                record["industry_buckets"].append(bucket)

        if record["industry_buckets"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    buckets = list(row.get("industry_buckets", []))
    rows_in_packet = len(buckets)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "M&A / 事業承継判断は DD 必須、税理士・弁護士・M&A advisor "
                "確認が前提。本 packet は事業内容類似度 + 地域 + 業種の "
                "descriptive scaffold で、相手先選定の予備情報のみ。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で同業種 × 共通制度候補無 — 承継候補無を意味しない",
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
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 事業承継",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "candidate_count": int(row.get("candidate_count") or 0),
        "industry_bucket_count": rows_in_packet,
    }
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "candidate_count": int(row.get("candidate_count") or 0),
        "industry_buckets": buckets,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
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
