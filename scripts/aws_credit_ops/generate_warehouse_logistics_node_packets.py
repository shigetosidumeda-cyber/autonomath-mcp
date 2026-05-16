"""Generate ``warehouse_logistics_node_v1`` packets (Wave 93 #6 of 10).

業種 (JSIC major) ごとに 倉庫 logistics node 兆候 (採択密度 proxy) を集計し、
descriptive sectoral warehouse logistics node indicator として packet 化する。
実際の 倉庫所在地 / 倉庫業 登録 / 普通倉庫 / 冷蔵倉庫 / 危険物倉庫 / 物流
施設 / 床面積 / コールドチェーン / DC / TC / 自動化倉庫 (AS/RS) / ロボット
活用 判断は 国交省 倉庫業登録簿 + 有価証券報告書 (EDINET) 「設備の状況」
+ 物流総合効率化法 認定 + 経産省 物流効率化推進事業 + 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "warehouse_logistics_node_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 warehouse logistics node packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、実際の 倉庫所在地 / 倉庫"
    "業 登録 / 普通倉庫 / 冷蔵倉庫 / 危険物倉庫 / 物流施設 / 床面積 / "
    "コールドチェーン / DC / TC / 自動化倉庫 (AS/RS) / ロボット活用 / "
    "WMS / TMS 判断は 国交省 倉庫業登録簿 + 有価証券報告書 (EDINET) "
    "「設備の状況」 + 物流総合効率化法 認定 + 経産省 物流効率化推進"
    "事業 + 一次確認が前提です (倉庫業法 §3-§7 §11 §16, 物流総合効率"
    "化法 §4-§9 (流通業務総合効率化), 標準倉庫寄託約款, 消防法 §10 "
    "(危険物倉庫), 食品衛生法 (冷蔵倉庫), 道路法 §47 (大型倉庫前面"
    "道路), 都市計画法 §29 開発許可, 建築基準法 §6, JIS Z 0001 物流"
    "用語)。"
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
                "倉庫所在地 / 倉庫業 登録 / 普通倉庫 / 冷蔵倉庫 / "
                "危険物倉庫 / 物流施設 / 床面積 / コールドチェーン"
                " / DC / TC / 自動化倉庫 / WMS / TMS 判断は 国交省"
                " 倉庫業登録簿 + 有価証券報告書 (EDINET) 「設備の"
                "状況」 + 物流総合効率化法 認定 + 経産省 物流効率化"
                "推進事業 + 一次確認が前提"
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
            "source_url": "https://www.mlit.go.jp/seisakutokatsu/freight/butsuryu05000.html",
            "source_fetched_at": None,
            "publisher": "国土交通省 倉庫業・物流総合効率化法",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/distribution/index.html",
            "source_fetched_at": None,
            "publisher": "経済産業省 物流政策・物流効率化推進事業",
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
