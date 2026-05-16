#!/usr/bin/env python3
"""Generate ``business_lifecycle_stage_v1`` packets (Wave 60 #4 of 10).

業種 (JSIC major) ごとに採択 round_label を新規 / 継続 / 後継 / 撤退 の lifecycle
proxy に分類し、cohort 内 frequency を集計する。個社 lifecycle 判定ではなく、
業種全体の lifecycle distribution shape のみ。

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

PACKAGE_KIND: Final[str] = "business_lifecycle_stage_v1"

LIFECYCLE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "founding": ("創業", "起業", "新設", "新規", "設立", "スタートアップ"),
    "growth": ("成長", "拡大", "事業拡張", "成長戦略"),
    "transformation": ("再構築", "事業転換", "DX", "GX", "イノベ"),
    "succession": ("承継", "後継", "M&A", "事業承継"),
    "exit": ("廃業", "撤退", "事業終了", "解散"),
}

DEFAULT_DISCLAIMER: Final[str] = (
    "本 business lifecycle stage packet は jpi_adoption_records の round_label + "
    "project_title から keyword ベースで lifecycle stage proxy 分類した "
    "descriptive 指標です。事業ライフサイクル評価判断は中小企業診断士 + "
    "事業承継支援センターの一次確認が前提。"
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
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        stage_counts: dict[str, int] = dict.fromkeys(LIFECYCLE_KEYWORDS, 0)
        total = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT round_label, project_title FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ? LIMIT 10000",
                (jsic_code,),
            ):
                total += 1
                text = " ".join(
                    str(r[c] or "") for c in ("round_label", "project_title")
                )
                for stage, kws in LIFECYCLE_KEYWORDS.items():
                    if any(kw in text for kw in kws):
                        stage_counts[stage] += 1
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "total_observed": total,
            "stage_counts": stage_counts,
        }
        if total > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    stage_counts = dict(row.get("stage_counts") or {})
    total = int(row.get("total_observed") or 0)
    rows_in_packet = sum(int(v or 0) for v in stage_counts.values())

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "lifecycle 評価判断は中小企業診断士 + 事業承継支援センターの一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で lifecycle keyword 観測無し",
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
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "total_observed": total,
        "stage_counts": stage_counts,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "total_observed": total,
            "matched_lifecycle_signals": rows_in_packet,
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
