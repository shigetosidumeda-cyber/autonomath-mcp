"""Generate ``procurement_diversity_index_v1`` packets (Wave 87 #9 of 10).

業種 (JSIC major) ごとに procurement diversity index (採択密度 proxy) を
集計し、descriptive sectoral procurement diversity indicator として packet
化する。発注先 多様性 / 中小企業優先発注比率 (法 §3) / 女性活躍推進法
認定事業者優遇 / 障害者雇用 推進事業者 / 若者活躍推進法 認定 / 地元中小
企業優先 / 社会的責任調達 / 環境配慮型調達 (グリーン購入法 §3) / 男女
共同参画 / LGBT・SOGI フレンドリー / ダイバーシティ経営 / NPO / 社会
的企業 発注 判断は 中小企業庁 + 内閣府 男女共同参画局 + 厚労省 雇用機
会均等課 + 環境省 + 各自治体 公契約担当 + 弁護士・社労士 + 監査法人の
一次確認が前提。

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

PACKAGE_KIND: Final[str] = "procurement_diversity_index_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 procurement diversity index packet は jpi_adoption_records 業種"
    "別 採択密度 を集計した descriptive proxy で、実際の 発注先 多様性 "
    "/ 中小企業優先発注比率 / 女性活躍推進法 認定事業者優遇 / 障害者雇"
    "用 推進事業者 / 若者活躍推進法 認定 / 地元中小企業優先 / 社会的責"
    "任調達 / 環境配慮型調達 (グリーン購入法) / 男女共同参画 / LGBT・"
    "SOGI フレンドリー / ダイバーシティ経営 / NPO / 社会的企業 発注 判"
    "断は 中小企業庁 + 内閣府 男女共同参画局 + 厚労省 雇用機会均等課 +"
    " 環境省 + 各自治体 公契約担当 + 弁護士・社労士 + 監査法人の一次"
    "確認が前提です (中小企業者に関する国等の契約の方針, 女性活躍推進"
    "法 §15, 障害者雇用促進法 §43, グリーン購入法 §3)。"
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
                "発注先 多様性 / 中小企業優先発注比率 / 女性活躍推進法 "
                "認定事業者優遇 / 障害者雇用 推進事業者 / 若者活躍推進法"
                " 認定 / 地元中小企業優先 / 社会的責任調達 / 環境配慮型"
                "調達 (グリーン購入法) / 男女共同参画 / LGBT・SOGI フレ"
                "ンドリー / ダイバーシティ経営 / NPO / 社会的企業 発注 "
                "判断は 中小企業庁 + 内閣府 + 厚労省 + 環境省 + 各自治体"
                " 公契約担当 + 弁護士・社労士 + 監査法人の一次確認が前提"
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
            "source_url": "https://www.chusho.meti.go.jp/keiei/torihiki/2024/240628keiyaku.html",
            "source_fetched_at": None,
            "publisher": "中小企業庁 国等の契約の方針",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.env.go.jp/policy/hozen/green/g-law/index.html",
            "source_fetched_at": None,
            "publisher": "環境省 グリーン購入法",
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
