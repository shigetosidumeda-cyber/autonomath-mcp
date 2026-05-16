"""Generate ``public_bid_win_share_v1`` packets (Wave 87 #1 of 10).

業種 (JSIC major) ごとに 公共入札 winning share / 落札 (採択密度 proxy) を
集計し、descriptive sectoral public bid win share indicator として packet
化する。落札率 / 平均落札価格 / 入札参加業者数 / 競争入札・指名競争・随契
区分 / 国・自治体・独法・公社・公庫 発注主体 / WTO 政府調達協定 対象 /
発注金額帯 判断は 各府省 契約情報公開 + 政府電子調達 GEPS + NJSS + 各
自治体 入札公告 + 会計検査院 + 公正取引委員会 + 入札監視委員会 + 法務
担当者 + 入札専門家の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "public_bid_win_share_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 public bid win share packet は jpi_adoption_records 業種別 採択"
    "密度 を集計した descriptive proxy で、実際の 落札率 / 平均落札価格 / "
    "入札参加業者数 / 競争入札・指名競争・随意契約 区分 / 国・自治体・"
    "独立行政法人・公社・公庫 発注主体 / WTO 政府調達協定 対象案件 / "
    "発注金額帯 判断は 各府省 契約情報公開 + 政府電子調達 GEPS + NJSS + "
    "各自治体 入札公告 + 会計検査院 + 公正取引委員会 + 入札監視委員会 + "
    "法務担当者 + 入札専門家の一次確認が前提です (会計法 §29条の3, 予決"
    "令 §62-100, 地方自治法 §234, 地方自治法施行令 §167)。"
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
                "落札率 / 平均落札価格 / 入札参加業者数 / 競争入札・指名"
                "競争・随意契約 区分 / 国・自治体・独立行政法人・公社・"
                "公庫 発注主体 / WTO 政府調達協定 対象案件 / 発注金額帯 "
                "判断は 各府省 契約情報公開 + 政府電子調達 GEPS + NJSS + "
                "各自治体 入札公告 + 会計検査院 + 公正取引委員会 + 入札"
                "監視委員会 + 法務担当者 + 入札専門家の一次確認が前提"
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
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 GEPS",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jbaudit.go.jp/",
            "source_fetched_at": None,
            "publisher": "会計検査院",
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
