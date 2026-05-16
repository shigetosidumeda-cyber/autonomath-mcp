#!/usr/bin/env python3
"""Generate ``kanpou_gazette_watch_v1`` packets (Wave 53.2 #8).

官報 watch packet. Aggregates recently-amended laws (``laws`` table) and
``am_amendment_diff`` rows by month-of-detection, producing a kanpou-style
publication feed by month so an agent can ask "what was published in
``YYYY-MM``?".

Cohort
------

::

    cohort = year_month (YYYY-MM)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

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

PACKAGE_KIND: Final[str] = "kanpou_gazette_watch_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 kanpou gazette watch packet は am_amendment_diff + laws を月次"
    "集計した観測 feed です。法令公布の正本は官報 (国立印刷局) を一次"
    "確認してください (景表法 / 消費者契約法 boundaries — 数値は参照値)。"
)


def _to_year_month(iso_value: Any) -> str | None:
    if not isinstance(iso_value, str) or len(iso_value) < 7:
        return None
    head = iso_value[:7]
    if not (head[:4].isdigit() and head[5:7].isdigit() and head[4] == "-"):
        return None
    return head


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}

    if table_exists(primary_conn, "am_amendment_diff"):
        for row in primary_conn.execute(
            "SELECT entity_id, field_name, detected_at, source_url "
            "  FROM am_amendment_diff "
            " ORDER BY detected_at DESC"
        ):
            ym = _to_year_month(row["detected_at"])
            if ym is None:
                continue
            bucket = agg.setdefault(
                ym,
                {
                    "year_month": ym,
                    "amendment_diffs": [],
                    "law_amendments": [],
                },
            )
            if len(bucket["amendment_diffs"]) < PER_AXIS_RECORD_CAP:
                bucket["amendment_diffs"].append(
                    {
                        "entity_id": row["entity_id"],
                        "field_name": row["field_name"],
                        "detected_at": row["detected_at"],
                        "source_url": row["source_url"],
                    }
                )

    if jpintel_conn is not None and table_exists(jpintel_conn, "laws"):
        for row in jpintel_conn.execute(
            "SELECT unified_id, law_title, law_number, ministry, "
            "       last_amended_date, full_text_url "
            "  FROM laws "
            " WHERE last_amended_date IS NOT NULL "
            " ORDER BY last_amended_date DESC"
        ):
            ym = _to_year_month(row["last_amended_date"])
            if ym is None:
                continue
            bucket = agg.setdefault(
                ym,
                {
                    "year_month": ym,
                    "amendment_diffs": [],
                    "law_amendments": [],
                },
            )
            if len(bucket["law_amendments"]) < PER_AXIS_RECORD_CAP:
                bucket["law_amendments"].append(
                    {
                        "law_unified_id": row["unified_id"],
                        "law_title": row["law_title"],
                        "law_number": row["law_number"],
                        "ministry": row["ministry"],
                        "last_amended_date": row["last_amended_date"],
                        "full_text_url": row["full_text_url"],
                    }
                )

    for emitted, ym in enumerate(sorted(agg.keys(), reverse=True)):
        yield agg[ym]
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    ym = str(row.get("year_month") or "UNKNOWN-MONTH")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(ym)}"
    diffs = list(row.get("amendment_diffs", []))
    laws = list(row.get("law_amendments", []))
    rows_in_packet = max(len(diffs), len(laws))

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "公布日時の正本は官報 (国立印刷局) — 本 packet は観測スナップ"
                "ショットです。施行日・改正内容は e-Gov を一次確認。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "この月で公布観測なし — 官報直接確認が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://kanpou.npb.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報 (国立印刷局)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://laws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
    ]
    metrics = {
        "amendment_diff_count": len(diffs),
        "law_amendment_count": len(laws),
    }
    body = {
        "amendment_diffs": diffs,
        "law_amendments": laws,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": ym,
            "year_month": ym,
        },
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
        needs_jpintel=True,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
