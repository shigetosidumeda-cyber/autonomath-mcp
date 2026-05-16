#!/usr/bin/env python3
"""Generate ``m_a_event_signals_v1`` packets (Wave 61 #4 of 10).

業種 (JSIC major) ごとに M&A 兆候 proxy (商号変更 / 役員交代 / 資本金変動 等)
の signal density を descriptive に集計する。個社 M&A 判定ではなく、業種全体
の signal density shape のみ。

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

PACKAGE_KIND: Final[str] = "m_a_event_signals_v1"

MA_KEYWORDS: Final[tuple[str, ...]] = (
    "M&A",
    "事業承継",
    "承継",
    "後継",
    "合併",
    "買収",
    "事業譲渡",
    "再構築",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 M&A event signals packet は jpi_adoption_records project_title + "
    "round_label から keyword ベースの descriptive M&A signal density proxy。"
    "個社 M&A 判定は M&A アドバイザー・税理士の一次確認が前提 (税理士法 §52)。"
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
        ma_signal_n = 0
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
                if any(kw in text for kw in MA_KEYWORDS):
                    ma_signal_n += 1
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "total_observed": total_n,
            "ma_signal_n": ma_signal_n,
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
    ma_n = int(row.get("ma_signal_n") or 0)
    rows_in_packet = total_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "M&A 判定は M&A アドバイザー・税理士の一次確認が前提",
        }
    ]
    if ma_n == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で M&A keyword 観測無し",
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
            "source_url": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 事業承継",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "industry", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "total_observed": total_n,
        "ma_signal_n": ma_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "total_observed": total_n,
            "ma_signal_n": ma_n,
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
