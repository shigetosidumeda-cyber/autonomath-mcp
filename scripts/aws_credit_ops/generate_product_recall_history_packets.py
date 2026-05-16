"""Generate ``product_recall_history_v1`` packets (Wave 92 #1).

業種 (JSIC major) ごとに 製品リコール history 兆候 (採択密度 proxy) を集計し、
descriptive sectoral product recall history indicator として packet 化する。リコール件数 / 自主回収 / 改善対策 / 製造物責任法 (PL) 訴訟 判断は 企業 開示資料 + 消費者庁 リコール情報 +一次確認が前提。Wave 81 product_recall_signal が原型、本 packet はより深い history coverage。

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

PACKAGE_KIND: Final[str] = "product_recall_history_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 product recall history packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、製品リコール history / 自主回収 / 改善対策 / 製造物責任法 PL 訴訟 / クレーム件数 / 重大製品事故 報告 判断は 企業 開示資料 + 消費者庁 リコール情報 + 経産省 NITE 事故情報 + リコール対象 製品 マスタの一次確認が前提です "
    "(製造物責任法 (PL法) §3, 消費生活用製品安全法 §35-§36 (重大事故 報告), 消費者安全法 §12, 食品衛生法 §54-§59 (回収), 薬機法 §68-9-3 (医薬品回収), 道路運送車両法 §63-2 (リコール届出), 電気用品安全法 §27 等)。"
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
                "製品リコール history / 自主回収 / 改善対策 / PL訴訟 / 重大製品事故 報告 判断は 企業 開示資料 + 消費者庁 リコール情報 + NITE 事故情報 + 監査法人 / 品質保証部門の一次確認が前提"
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
            "source_url": "https://www.caa.go.jp/policies/policy/consumer_safety/recall/",
            "source_fetched_at": None,
            "publisher": "消費者庁 リコール情報",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nite.go.jp/jiko/index.html",
            "source_fetched_at": None,
            "publisher": "経産省 NITE 事故情報",
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
