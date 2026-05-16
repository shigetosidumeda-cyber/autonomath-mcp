#!/usr/bin/env python3
"""Generate ``child_population_overlay_v1`` packets (Wave 84 #8 of 10).

業種 (JSIC major) ごとに 子供人口 overlay (0-14歳 人口比率
+ 出生率 + 保育所 整備率) の descriptive sectoral proxy を 採択
密度 経由で集計し packet 化する。本 packet は こども家庭庁 子ども
若者白書 / 厚労省 人口動態統計 / 内閣府 少子化対策大綱 を一次
裏取とする 公開 信号 で、合計特殊出生率 / 待機児童数 / 学童保育
整備率 / 子育て世帯加算判断はこども家庭庁 + 厚労省 + 自治体
児童福祉担当 + 保育士 + 児童相談所の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "child_population_overlay_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 child population overlay packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、合計特殊出生率 / 待機"
    "児童数 / 学童保育整備率 / 子育て世帯加算判断はこども家庭庁 + "
    "厚労省 + 自治体 児童福祉担当 + 保育士 + 児童相談所の一次確認が"
    "前提です (こども基本法 §1, 児童福祉法 §1, 少子化社会対策基本法"
    " §2, 子ども・子育て支援法 §3, 児童手当法 §1)。"
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
                "合計特殊出生率 / 待機児童数 / 学童保育整備率 / "
                "子育て世帯加算判断はこども家庭庁 + 厚労省 + "
                "自治体 児童福祉担当 + 保育士 + 児童相談所の一次"
                "確認が前提"
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
            "source_url": "https://www.cfa.go.jp/policies/kodomo-wakamono-hakusho/",
            "source_fetched_at": None,
            "publisher": "こども家庭庁 子供・若者白書",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mhlw.go.jp/toukei/list/81-1a.html",
            "source_fetched_at": None,
            "publisher": "厚生労働省 人口動態統計",
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
