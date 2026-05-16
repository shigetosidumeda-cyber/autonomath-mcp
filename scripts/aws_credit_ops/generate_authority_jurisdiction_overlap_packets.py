"""Generate ``authority_jurisdiction_overlap_v1`` packets (Wave 98 #3 of 10).

ministry-level authority (am_authority.level = 'ministry' / 'agency') 毎に、
prefecture-level program 発出量を am_entities.authority_canonical で集計し、
descriptive ministry × prefecture jurisdiction overlap matrix indicator
として packet 化する。実際の所管 / 申請窓口 / 補助金交付主体判断は 各所管
省庁 + 都道府県担当課の一次確認が前提。

Cohort
------
::

    cohort = ministry_authority_id (am_authority.canonical_id, level ∈
             {ministry, agency, cabinet})

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "authority_jurisdiction_overlap_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 authority jurisdiction overlap packet は am_entities × am_authority "
    "× am_region を JOIN した descriptive overlap matrix で、実際の所管 / "
    "申請窓口 / 補助金交付主体判断は 各所管省庁 + 都道府県担当課の一次確認が "
    "前提です (補助金交付規程、自治法 §2)。"
)

_MAX_PREFS_PER_PACKET: Final[int] = 47  # all 47 都道府県


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_authority"):
        return
    if not table_exists(primary_conn, "am_entities"):
        return
    ministries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT canonical_id, canonical_name "
            "  FROM am_authority "
            " WHERE level IN ('cabinet', 'ministry', 'agency') "
            " ORDER BY canonical_id"
        ):
            ministries.append(
                (str(r["canonical_id"]), str(r["canonical_name"] or ""))
            )

    for emitted, (ministry_id, ministry_name) in enumerate(ministries):
        # Programs issued under this ministry, prefecture-bucketed via
        # source_url_domain prefix heuristic (lacking strict prefecture
        # FK on am_entities). Use raw_json prefecture marker if present.
        program_n = 0
        prefecture_buckets: dict[str, int] = {}
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM am_entities "
                " WHERE record_kind = 'program' "
                "   AND authority_canonical = ?",
                (ministry_id,),
            ).fetchone()
            if row:
                program_n = int(row["n"] or 0)
        # Aggregate prefecture overlap by source_url_domain heuristic
        # (TLD slug correlates with prefecture for *.pref.*.lg.jp).
        with contextlib.suppress(Exception):
            for d in primary_conn.execute(
                "SELECT source_url_domain, COUNT(*) AS n "
                "  FROM am_entities "
                " WHERE record_kind = 'program' "
                "   AND authority_canonical = ? "
                "   AND source_url_domain IS NOT NULL "
                " GROUP BY source_url_domain "
                " ORDER BY n DESC "
                " LIMIT 60",
                (ministry_id,),
            ):
                dom = str(d["source_url_domain"] or "")
                # Match prefecture from `*.pref.{slug}.lg.jp` style.
                slug = ""
                if ".pref." in dom:
                    parts = dom.split(".pref.")
                    if len(parts) == 2:
                        slug_parts = parts[1].split(".")
                        if slug_parts:
                            slug = slug_parts[0]
                bucket = slug or f"_domain:{dom}"
                prefecture_buckets[bucket] = (
                    prefecture_buckets.get(bucket, 0) + int(d["n"] or 0)
                )

        record = {
            "ministry_id": ministry_id,
            "ministry_name": ministry_name,
            "program_n": program_n,
            "prefecture_buckets": prefecture_buckets,
        }
        if program_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    ministry_id = str(row.get("ministry_id") or "UNKNOWN")
    ministry_name = str(row.get("ministry_name") or "")
    program_n = int(row.get("program_n") or 0)
    prefecture_buckets = dict(row.get("prefecture_buckets") or {})
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(ministry_id)}"
    rows_in_packet = program_n

    # Truncate to top 30 buckets so envelope stays under 25 KB.
    top_buckets = dict(
        sorted(prefecture_buckets.items(), key=lambda kv: kv[1], reverse=True)[:30]
    )

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "所管 / 申請窓口 / 補助金交付主体判断は 各所管省庁 + "
                "都道府県担当課の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 ministry で program 発出無し",
            }
        )
    if len(prefecture_buckets) > 30:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": "domain bucket >30 で打切、top 30 のみ収載",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.e-stat.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Stat 政府統計の総合窓口",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/",
            "source_fetched_at": None,
            "publisher": "総務省 自治行政局",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "ministry_authority", "id": ministry_id},
        "ministry_id": ministry_id,
        "ministry_name": ministry_name,
        "program_n": program_n,
        "prefecture_buckets": top_buckets,
        "prefecture_bucket_n": len(prefecture_buckets),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": ministry_id,
            "ministry_authority_id": ministry_id,
        },
        metrics={
            "program_n": program_n,
            "prefecture_bucket_n": len(prefecture_buckets),
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
