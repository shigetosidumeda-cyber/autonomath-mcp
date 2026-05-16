"""Generate ``employer_brand_signal_v1`` packets (Wave 86 #7 of 10).

業種 (JSIC major) ごとに Employer brand signal (採用 site / 社員口コミ
(OpenWork / Lighthouse / Job Total / Indeed) / Glassdoor 類似 / 求人 platform
出稿 強度 / リファラル制度 / 新卒 popularity / 中途満足度 / 退職 review)
descriptive sectoral proxy を 採択密度 経由で集計し packet 化する。本 packet は
厚労省 就職活動指針 + 経団連 採用選考活動 + 職業安定法 + 個情委 履歴書取扱い +
プロバイダ責任制限法 を一次裏取とする 公開 信号 で、口コミ削除 / 名誉毀損対応
/ 個人情報含有 review 対応 / 職業安定法上の求人広告 適法性判断は 弁護士 + プロ
バイダ + 厚労省 + ハローワーク + 各プラットフォームの一次確認が前提。

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

PACKAGE_KIND: Final[str] = "employer_brand_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 employer brand signal packet は jpi_adoption_records 業種別 採択密度 "
    "を集計した descriptive proxy で、口コミ削除 / 名誉毀損対応 / 個人情報含有 "
    "review 対応 / 職業安定法上の求人広告 適法性 / 経団連 採用選考活動 / 中途・"
    "新卒 popularity 判定は 弁護士 + プロバイダ + 厚労省 + ハローワーク + 各"
    "プラットフォームの一次確認が前提です (職業安定法 §5の3, 個人情報保護法 "
    "§27, プロバイダ責任制限法 §4, 男女雇用機会均等法 §5)。"
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
                "口コミ削除 / 名誉毀損対応 / 個人情報含有 review 対応 / "
                "職業安定法上の求人広告 適法性 / 経団連 採用選考活動 / "
                "中途・新卒 popularity 判定は 弁護士 + プロバイダ + 厚労省 "
                "+ ハローワーク + 各プラットフォームの一次確認が前提"
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
            "source_url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/jakunensha/index.html",
            "source_fetched_at": None,
            "publisher": "厚生労働省 若年者雇用対策",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyouseisaku/saiyou/index.html",
            "source_fetched_at": None,
            "publisher": "厚生労働省 採用選考 (職業安定法)",
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
