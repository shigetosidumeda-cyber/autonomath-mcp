"""Generate ``manufacturing_facility_inventory_v1`` packets (Wave 93 #5 of 10).

業種 (JSIC major) ごとに 製造拠点 inventory 兆候 (採択密度 proxy) を集計し、
descriptive sectoral manufacturing facility inventory indicator として packet
化する。実際の 工場拠点 / 生産能力 / 立地条件 / 工業団地 / 工場立地法 届出
/ 工場立地動向調査 / 製造品出荷額 / 設備投資 判断は 経産省 工業統計調査
/ 工場立地動向調査 + 有価証券報告書 (EDINET) 「設備の状況」 + 工場立地法
届出 + 建築基準法 用途地域 + 環境影響評価 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "manufacturing_facility_inventory_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 manufacturing facility inventory packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、実際の 工場拠点 / "
    "生産能力 / 立地条件 / 工業団地 / 工場立地法 届出 / 工場立地動向"
    "調査 / 製造品出荷額 / 設備投資 / 操業度 / 稼働率 / 環境影響評価 "
    "判断は 経産省 工業統計調査 / 工場立地動向調査 + 有価証券報告書 "
    "(EDINET) 「設備の状況」 + 工場立地法 届出 + 建築基準法 用途地域"
    " + 環境影響評価 一次確認が前提です (工場立地法 §6-§9, 工業立地法,"
    " 環境影響評価法 §2-§4 §14-§38, 建築基準法 §48 用途地域, 都市計画"
    "法 §8 §29, 大気汚染防止法 §6, 水質汚濁防止法 §5, 化学物質審査規制"
    "法 §3, PRTR 法 §4, 産業立地税制 (中小企業地域経済牽引事業計画)"
    " 等)。"
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
                "工場拠点 / 生産能力 / 立地条件 / 工業団地 / 工場"
                "立地法 届出 / 工場立地動向調査 / 製造品出荷額 / "
                "設備投資 / 操業度 / 稼働率 / 環境影響評価 判断は "
                "経産省 工業統計調査 / 工場立地動向調査 + 有価証券"
                "報告書 (EDINET) 「設備の状況」 + 工場立地法 届出 +"
                " 建築基準法 用途地域 + 環境影響評価 一次確認が前提"
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
            "source_url": "https://www.meti.go.jp/statistics/tyo/kougyo/index.html",
            "source_fetched_at": None,
            "publisher": "経済産業省 工業統計調査",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/local_economy/nipponsaikoh/koujyouricchi.html",
            "source_fetched_at": None,
            "publisher": "経済産業省 工場立地法・工場立地動向調査",
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
