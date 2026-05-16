"""Generate ``corporate_website_signal_v1`` packets (Wave 86 #1 of 10).

業種 (JSIC major) ごとに 企業 web presence signal (公式 corporate site 有無 /
ドメイン年齢 / SSL/TLS 適合 / お問い合わせ form / プライバシーポリシー / 特商法
表記 / cookie consent) descriptive sectoral proxy を 採択密度 経由で集計し
packet 化する。本 packet は 特定商取引法 + 個情委 cookie 規律 + ICP 届出 / JADMA
通販基準 / 電気通信事業法 ガイドラインを一次裏取とする 公開 信号 で、site
完全性判定 / 法令 compliance 判断は 弁護士 + 個人情報保護委員会 + JADMA + 弁理士
+ 公式広告審査機関の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "corporate_website_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 corporate website signal packet は jpi_adoption_records 業種別 採択密度 "
    "を集計した descriptive proxy で、公式 site 完全性 / 特商法表記 / プライバシー"
    "ポリシー / cookie consent / SSL 適合 / お問い合わせ form / 電気通信事業法 "
    "ガイドライン compliance 判断は 弁護士 + 個人情報保護委員会 + JADMA + 電気"
    "通信事業者協会 + 公式広告審査機関の一次確認が前提です (特定商取引法 §11, "
    "個人情報保護法 §27, 電気通信事業法 §27の12, JADMA 通信販売基準, JIS Q 15001)。"
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
                "公式 site 完全性 / 特商法表記 / プライバシーポリシー / "
                "cookie consent / SSL 適合 / お問い合わせ form / 電気通信"
                "事業法 ガイドライン compliance 判断は 弁護士 + 個人情報"
                "保護委員会 + JADMA + 電気通信事業者協会 + 公式広告審査"
                "機関の一次確認が前提"
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
            "source_url": "https://www.no-trouble.caa.go.jp/what/mailorder/",
            "source_fetched_at": None,
            "publisher": "消費者庁 特定商取引法 通信販売",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.ppc.go.jp/personalinfo/legal/guidelines_tsusoku/",
            "source_fetched_at": None,
            "publisher": "個人情報保護委員会 ガイドライン (cookie)",
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
