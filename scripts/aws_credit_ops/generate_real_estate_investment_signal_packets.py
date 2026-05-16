"""Generate ``real_estate_investment_signal_v1`` packets (Wave 93 #8 of 10).

業種 (JSIC major) ごとに 不動産投資 signal 兆候 (採択密度 proxy) を集計し、
descriptive sectoral real estate investment signal indicator として packet
化する。実際の 投資不動産 保有 / 取得 / 売却 / NOI / cap rate / IRR / LTV /
DSCR / GP-LP 構造 / 不動産特定共同事業 / 不動産信託受益権 / 私募ファンド /
不動産流動化 SPC 判断は 有価証券報告書 (EDINET) + 不動産特定共同事業法 +
信託業法 + 金融商品取引法 + 不動産鑑定士 + 税理士 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "real_estate_investment_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 real estate investment signal packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、実際の 投資不動産"
    " 保有 / 取得 / 売却 / NOI / cap rate / IRR / LTV / DSCR / GP-LP "
    "構造 / 不動産特定共同事業 / 不動産信託受益権 / 私募ファンド / 不動"
    "産流動化 SPC / TMK (特定目的会社) / GK-TK スキーム 判断は 有価証券"
    "報告書 (EDINET) + 不動産特定共同事業法 + 信託業法 + 金融商品取引法"
    " + 不動産鑑定士 + 税理士 一次確認が前提です (不動産特定共同事業法 "
    "§3-§4 §28-§30, 信託業法 §3 §50-2, 金融商品取引法 §2-2 §28 §29 §63,"
    " 資産流動化法 §3 §223, 投資信託法 §187, 宅建業法 §3, 金商法 §66 "
    "(投資助言業), 不動産鑑定評価基準, IFRS 16 / IAS 40, 企業会計基準"
    "第28号 「公正価値測定」, 法人税法 §22 §62-§64-2 (組織再編))。"
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
                "投資不動産 保有 / 取得 / 売却 / NOI / cap rate / "
                "IRR / LTV / DSCR / GP-LP / 不動産特定共同事業 / "
                "不動産信託受益権 / 私募ファンド / 不動産流動化 "
                "SPC / TMK / GK-TK 判断は 有価証券報告書 (EDINET)"
                " + 不動産特定共同事業法 + 信託業法 + 金融商品取引"
                "法 + 不動産鑑定士 + 税理士 一次確認が前提"
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
            "source_url": "https://www.mlit.go.jp/totikensangyo/totikensangyo_fr3_000010.html",
            "source_fetched_at": None,
            "publisher": "国土交通省 不動産特定共同事業法",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.fsa.go.jp/policy/kinyusyohintorihiki/index.html",
            "source_fetched_at": None,
            "publisher": "金融庁 金融商品取引法 (不動産関連投資信託)",
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
