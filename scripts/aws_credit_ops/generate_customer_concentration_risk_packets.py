"""Generate ``customer_concentration_risk_v1`` packets (Wave 91 #7).

業種 (JSIC major) ごとに 顧客集中 risk 兆候 (採択密度 proxy) を集計し、
descriptive sectoral customer concentration risk indicator として packet 化する。顧客集中 / 主要販売先依存度 / 10% ルール 注記 / 信用リスク 判断は 企業 開示資料 + 統合報告書 + 有...

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

PACKAGE_KIND: Final[str] = "customer_concentration_risk_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 customer concentration risk packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、顧客集中 / 主要販売先依存度 / 10% ルール 注記 / 信用リスク 判断は 企業 開示資料 + 統合報告書 + 有報 主要販売先注記 + 営業 / 経理 部門の一次確認が前提です "
    "(金商法 §24 有価証券報告書, 企業会計基準 17号 セグメント情報, 財務諸表等規則 §8-31 主要販売先, 会社法 §362 内部統制決議, 下請法 §2-1, 独占禁止法 §19 優越的地位濫用 等)。"
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
                "顧客集中 / 主要販売先依存度 / 10% ルール 注記 / 信用リスク 判断は 企業 開示資料 + 統合報告書 + 有報 主要販売先注記 + 営業 / 経理 部門の一次確認が前提"
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
            "publisher": "EDINET 金融庁 (有報 主要販売先)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jftc.go.jp/houdou/torihikijirei/",
            "source_fetched_at": None,
            "publisher": "公正取引委員会 優越的地位濫用",
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
