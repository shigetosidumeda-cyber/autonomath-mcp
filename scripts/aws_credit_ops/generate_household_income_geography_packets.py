#!/usr/bin/env python3
"""Generate ``household_income_geography_v1`` packets (Wave 84 #9 of 10).

業種 (JSIC major) ごとに 世帯所得地理 (中央値 + ジニ係数 + 相対
貧困率 + 生活保護率) の descriptive sectoral proxy を 採択密度
経由で集計し packet 化する。本 packet は 厚労省 国民生活基礎
調査 / 総務省 家計調査 / 内閣府 経済財政白書 を一次裏取と
する 公開 信号 で、世帯所得中央値 / ジニ係数 / 相対貧困率 /
生活保護率判断は厚労省 + 総務省 + 内閣府 + 社会保障審議会 +
社会福祉士 + 自治体 生活保護担当の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "household_income_geography_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 household income geography packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、世帯所得中央値 / ジニ"
    "係数 / 相対貧困率 / 生活保護率判断は厚労省 + 総務省 + 内閣府 + "
    "社会保障審議会 + 社会福祉士 + 自治体 生活保護担当の一次確認が"
    "前提です (生活保護法 §1, 社会福祉法 §3, 子どもの貧困対策の推進"
    "に関する法律 §2, 国民生活基礎調査令 §4, 家計調査令 §3)。"
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
        adoption_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n FROM jpi_adoption_records  WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
        }
        if adoption_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    adoption_n = int(row.get("adoption_n") or 0)
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "世帯所得中央値 / ジニ係数 / 相対貧困率 / 生活保護"
                "率判断は厚労省 + 総務省 + 内閣府 + 社会保障審議会"
                " + 社会福祉士 + 自治体 生活保護担当の一次確認が"
                "前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で adoption record 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.mhlw.go.jp/toukei/list/20-21.html",
            "source_fetched_at": None,
            "publisher": "厚生労働省 国民生活基礎調査",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.stat.go.jp/data/kakei/",
            "source_fetched_at": None,
            "publisher": "総務省 統計局 家計調査",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
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
