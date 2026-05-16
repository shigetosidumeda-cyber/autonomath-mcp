"""Generate ``hostile_takeover_proxy_v1`` packets (Wave 89 #10 of 10).

業種 (JSIC major) ごとに Hostile takeover proxy signal (敵対的買収 / 同意
なき公開買付 / 大量保有報告書 急増 / 委任状争奪 / 防衛策発動 / 防衛策
更新議案) の signal 兆候 (採択密度 proxy) を集計し, descriptive sectoral
hostile takeover proxy indicator として packet 化する。実際の防衛策発動
要件 / 株主総会決議 / 独立委員会 答申 / 委任状勧誘規則 整合 / 経産省
公正な買収の在り方 指針 整合 判断は EDINET 大量保有報告書 + JPX 適時
開示 + 弁護士 (M&A) の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "hostile_takeover_proxy_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 hostile takeover proxy packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、実際の防衛策発動要件 / "
    "株主総会決議 / 独立委員会 答申 / 委任状勧誘規則 整合 / 経産省 "
    "公正な買収の在り方 指針 整合 / 大量保有報告 違反 / 公開買付規制 "
    "整合 判断は EDINET 大量保有報告書 + JPX 適時開示 + 弁護士 (M&A) "
    "の一次確認が前提です (金商法 §27-23 大量保有 §27-2 公開買付 §194-3"
    " 委任状勧誘規則, 会社法 §155 自己株式取得 §247 新株予約権無償割当"
    ", 経産省 公正な買収の在り方 指針 2023)。"
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
                "防衛策発動要件 / 株主総会決議 / 独立委員会 答申 / 委任"
                "状勧誘規則 整合 / 経産省 公正な買収の在り方 指針 整合 "
                "/ 大量保有報告 違反 / 公開買付規制 整合 判断は EDINET"
                " + JPX 適時開示 + 弁護士 (M&A) の一次確認が前提"
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
            "publisher": "EDINET 金融庁 (大量保有報告書 / 変更報告書)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/economy/keiei_innovation/keieiryoku/m_a_guidelines.html",
            "source_fetched_at": None,
            "publisher": "経産省 企業買収における行動指針 (2023 公正な買収の在り方)",
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
