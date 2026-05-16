"""Generate ``government_payment_velocity_v1`` packets (Wave 87 #10 of 10).

業種 (JSIC major) ごとに 公金支払 (government payment) velocity / 支払
遅延 signal (採択密度 proxy) を集計し、descriptive sectoral government
payment velocity indicator として packet 化する。請求から入金までの日数 /
公金支払遅延発生件数 / 公金支払遅延防止法 §8 利息発生 / 前金払・部分払
活用率 / 中間前払 制度 / 標準処理期間 (会計法 §22) / 概算払 / 即日払 /
公共工事 出来高部分払 / 工程進捗 連動部分払 / 月内払 / 翌月末払 / 30 日
以内 政府支払 ルール 判断は 財務省 主計局 + 国交省 (公共工事関連) + 各
府省 会計課 + 会計検査院 + 公認会計士 + 弁護士の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "government_payment_velocity_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 government payment velocity packet は jpi_adoption_records 業種"
    "別 採択密度 を集計した descriptive proxy で、実際の 請求から入金"
    "までの日数 / 公金支払遅延発生件数 / 公金支払遅延防止法 §8 利息発"
    "生 / 前金払・部分払 活用率 / 中間前払 制度 / 標準処理期間 (会計"
    "法 §22) / 概算払 / 即日払 / 公共工事 出来高部分払 / 工程進捗 連動"
    "部分払 / 月内払 / 翌月末払 / 30 日以内 政府支払 ルール 判断は 財"
    "務省 主計局 + 国交省 + 各府省 会計課 + 会計検査院 + 公認会計士 + "
    "弁護士の一次確認が前提です (政府契約の支払遅延防止等に関する法律 "
    "§8, 会計法 §22, 公共工事の前払金保証事業に関する法律, 中小企業"
    "庁 下請代金支払遅延等防止法)。"
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
                "請求から入金までの日数 / 公金支払遅延発生件数 / 公金支"
                "払遅延防止法 §8 利息発生 / 前金払・部分払 活用率 / 中"
                "間前払 制度 / 標準処理期間 (会計法 §22) / 概算払 / 即"
                "日払 / 公共工事 出来高部分払 / 工程進捗 連動部分払 / "
                "月内払 / 翌月末払 / 30 日以内 政府支払 ルール 判断は 財"
                "務省 主計局 + 国交省 + 各府省 会計課 + 会計検査院 + 公"
                "認会計士 + 弁護士の一次確認が前提"
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
            "source_url": "https://elaws.e-gov.go.jp/document?lawid=324AC0000000256",
            "source_fetched_at": None,
            "publisher": "政府契約の支払遅延防止等に関する法律",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mof.go.jp/policy/budget/topics/",
            "source_fetched_at": None,
            "publisher": "財務省 予算・会計",
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
