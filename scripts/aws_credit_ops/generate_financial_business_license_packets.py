#!/usr/bin/env python3
"""Generate ``financial_business_license_v1`` packets (Wave 78 #7 of 10).

業種 (JSIC major) ごとに 金商業 license 兆候 (採択密度 proxy) を集計し、
descriptive sectoral financial business license indicator として packet 化する。
個社の金融商品取引業登録可否 / 業種区分判定ではなく業種全体の overlay shape のみ。

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

PACKAGE_KIND: Final[str] = "financial_business_license_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 financial business license packet は jpi_adoption_records 業種別 "
    "採択密度を 金融商品取引法 §29 金融商品取引業 (第一種金商業 / 第二種 / "
    "投資助言 / 投資運用) / 銀行業 / 貸金業 / 資金移動業 兆候 proxy として "
    "集計した descriptive 指標で、個社の登録可否 / 業種区分 / 認定 / 健全 "
    "性は 金融庁 / 財務局 / 弁護士 / コンプライアンス担当の一次確認が前提 "
    "です (金商法 §29, 銀行法 §4, 貸金業法 §3, 資金決済法 §37)。"
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
                "SELECT COUNT(*) AS n FROM jpi_adoption_records "
                " WHERE industry_jsic_medium = ?",
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
                "個社の金商業登録可否 / 業種区分 / 認定 / 健全性は 金融庁 / "
                "財務局 / 弁護士 / コンプライアンス担当の一次確認が前提"
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
            "source_url": "https://www.fsa.go.jp/menkyo/menkyoj/kinyushohin.html",
            "source_fetched_at": None,
            "publisher": "金融庁 金融商品取引業者登録一覧",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.fsa.go.jp/menkyo/menkyoj/kashikin.html",
            "source_fetched_at": None,
            "publisher": "金融庁 貸金業者登録一覧",
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
