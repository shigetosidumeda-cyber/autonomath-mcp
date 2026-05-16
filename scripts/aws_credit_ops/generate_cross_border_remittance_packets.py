#!/usr/bin/env python3
"""Generate ``cross_border_remittance_v1`` packets (Wave 61 #5 of 10).

業種 (JSIC major) ごとに 海外送金 + 輸出促進補助金 proxy の cohort indicator
を descriptive に集計する。個社 remittance 判定ではない。

Cohort
------
::

    cohort = jsic_major (A-V)
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

PACKAGE_KIND: Final[str] = "cross_border_remittance_v1"

EXPORT_KEYWORDS: Final[tuple[str, ...]] = (
    "輸出",
    "海外展開",
    "JETRO",
    "JBIC",
    "貿易",
    "国際",
    "海外進出",
    "クロスボーダー",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 cross-border remittance packet は jpi_adoption_records project_title + "
    "round_label から keyword で 海外/輸出 制度 signal を descriptive に proxy。"
    "実際の送金/外為 判断は国際税務 advisor の一次確認が前提 (外為法・税理士法 §52)。"
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
        total_n = 0
        export_signal_n = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT round_label, project_title FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ? LIMIT 10000",
                (jsic_code,),
            ):
                total_n += 1
                text = " ".join(
                    str(r[c] or "") for c in ("round_label", "project_title")
                )
                if any(kw in text for kw in EXPORT_KEYWORDS):
                    export_signal_n += 1
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "total_observed": total_n,
            "export_signal_n": export_signal_n,
        }
        if total_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    total_n = int(row.get("total_observed") or 0)
    export_n = int(row.get("export_signal_n") or 0)
    rows_in_packet = total_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "海外送金/外為判断は国際税務 advisor の一次確認が前提",
        }
    ]
    if export_n == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で 輸出/海外展開 keyword 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jetro.go.jp/",
            "source_fetched_at": None,
            "publisher": "JETRO 日本貿易振興機構",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jbic.go.jp/",
            "source_fetched_at": None,
            "publisher": "国際協力銀行 JBIC",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "total_observed": total_n,
        "export_signal_n": export_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "total_observed": total_n,
            "export_signal_n": export_n,
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
