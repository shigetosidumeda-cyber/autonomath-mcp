"""Generate ``going_private_signal_v1`` packets (Wave 89 #6 of 10).

業種 (JSIC major) ごとに 非公開化 signal (上場廃止 TOB / 完全子会社化 /
全部取得条項付種類株式 / 株式併合 squeeze-out / 二段階買収) の signal
兆候 (採択密度 proxy) を集計し, descriptive sectoral going-private signal
indicator として packet 化する。実際の TOB 価格 / 二段階買収価格 /
少数株主排除手続 / 反対株主 株式買取請求 / 上場廃止基準 判断は EDINET
公開買付届出書 + JPX 上場廃止情報 + 弁護士 (M&A) の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "going_private_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 going private signal packet は jpi_adoption_records 業種別 採択"
    "密度 を集計した descriptive proxy で、実際の TOB 価格 / 二段階買収"
    " 価格 / 少数株主排除手続 / 反対株主 株式買取請求 / 上場廃止基準 "
    "/ 全部取得条項付種類株式 判断は EDINET 公開買付届出書 + JPX 上場"
    "廃止情報 + 弁護士 (M&A) の一次確認が前提です (金商法 §27-2 公開"
    "買付, 会社法 §171 全部取得条項付種類株式 §785 株式買取請求 §172 "
    "価格決定, JPX 有価証券上場規程)。"
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
                "TOB 価格 / 二段階買収価格 / 少数株主排除手続 / 反対"
                "株主 株式買取請求 / 上場廃止基準 / 全部取得条項付種類"
                "株式 判断は EDINET + JPX 上場廃止情報 + 弁護士 (M&A) "
                "の一次確認が前提"
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
            "source_url": "https://disclosure.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET 金融庁 (公開買付届出書 上場廃止 案件)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jpx.co.jp/listing/stocks/delisting/",
            "source_fetched_at": None,
            "publisher": "JPX 東証 上場廃止 一覧 (有価証券上場規程)",
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
