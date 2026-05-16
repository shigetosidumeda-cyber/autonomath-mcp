#!/usr/bin/env python3
"""Generate ``trademark_industry_density_v1`` packets (Wave 54 #7).

商標 (JPO J14) × 業種 (JSIC) packet. Surfaces trademark-tagged programs
+ adoptions bucketed by JSIC major from houjin_master.jsic_major. The
packet answers "which industries lean trademark-heavy in their support
programs?".

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

PACKAGE_KIND: Final[str] = "trademark_industry_density_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

_TRADEMARK_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "商標",
        "ブランド",
        "ロゴ",
        "意匠",
        "知財",
        "持続化",
        "小規模事業者",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 trademark industry density packet は商標関連 program × 業種別の "
    "descriptive density です。実際の商標登録・出願は J-PlatPat を一次"
    "確認してください (弁理士法 §75 boundaries)。"
)


def _hits(text: str | None) -> bool:
    if text is None:
        return False
    s = str(text)
    return any(kw in s for kw in _TRADEMARK_KEYWORDS)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return

    jsic_majors: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' "
            " ORDER BY jsic_code"
        ):
            jsic_majors.append((str(r["jsic_code"]), str(r["jsic_name_ja"] or "")))

    for emitted, (jsic_code, jsic_name) in enumerate(jsic_majors):
        record: dict[str, Any] = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "houjin_count_in_major": 0,
            "trademark_adoption_count": 0,
            "trademark_adoptions": [],
        }
        # houjin_master.jsic_major is honestly thin; fall back to
        # adoption-side industry tag (industry_jsic_medium starts with the
        # JSIC major code letter when populated).
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(DISTINCT a.houjin_bangou) AS c "
                "  FROM jpi_adoption_records a "
                " WHERE a.industry_jsic_medium IS NOT NULL "
                "   AND substr(a.industry_jsic_medium, 1, 1) = ?",
                (jsic_code,),
            ):
                record["houjin_count_in_major"] = int(r["c"] or 0)
        # Trademark-tagged adoption sample for this jsic_major.
        with contextlib.suppress(Exception):
            for adopt in primary_conn.execute(
                "SELECT a.houjin_bangou, a.program_name_raw, "
                "       a.amount_granted_yen, a.announced_at, a.source_url "
                "  FROM jpi_adoption_records a "
                " WHERE a.industry_jsic_medium IS NOT NULL "
                "   AND substr(a.industry_jsic_medium, 1, 1) = ? "
                " ORDER BY COALESCE(a.amount_granted_yen, 0) DESC "
                " LIMIT 400",
                (jsic_code,),
            ):
                if not _hits(adopt["program_name_raw"]):
                    continue
                if (
                    len(record["trademark_adoptions"]) >= PER_AXIS_RECORD_CAP
                ):
                    record["trademark_adoption_count"] += 1
                    continue
                record["trademark_adoptions"].append(
                    {
                        "houjin_bangou": adopt["houjin_bangou"],
                        "program_name": adopt["program_name_raw"],
                        "amount_yen": int(adopt["amount_granted_yen"] or 0),
                        "announced_at": adopt["announced_at"],
                        "source_url": adopt["source_url"],
                    }
                )
                record["trademark_adoption_count"] += 1

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    adoptions = list(row.get("trademark_adoptions", []))
    rows_in_packet = len(adoptions)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "商標登録・出願の正本は J-PlatPat (JPO)。本 packet は"
                "補助金 program 名のキーワード一致による proxy です。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "この JSIC 業種では商標関連 program 採択なし",
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
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC 分類)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "houjin_count_in_major": int(row.get("houjin_count_in_major") or 0),
        "trademark_adoption_count_total": int(
            row.get("trademark_adoption_count") or 0
        ),
        "trademark_adoption_sample_count": len(adoptions),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": row.get("jsic_name_ja"),
        "trademark_adoptions": adoptions,
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
