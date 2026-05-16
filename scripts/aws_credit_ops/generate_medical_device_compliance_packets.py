"""Generate ``medical_device_compliance_v1`` packets (Wave 92 #5).

業種 (JSIC major) ごとに 医療機器 compliance 兆候 (採択密度 proxy) を集計し、
descriptive sectoral medical device compliance indicator として packet 化する。医療機器 クラス I-IV / QMS / ISO 13485 / 製造販売届出 判断は PMDA + 厚労省 一次資料 + 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "medical_device_compliance_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 medical device compliance packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、医療機器 compliance / 一般 / 管理 / 高度管理 / 特定保守管理 / クラス I-IV / QMS / ISO 13485 / 製造販売届出 / 認証 / 承認 / プログラム医療機器 (SaMD) 判断は PMDA + 厚労省 + 医療機器登録番号マスタ + QMS 監査 + 一次確認が前提です "
    "(医薬品医療機器等法 (薬機法) §23-2 (製造販売届出) §23-2-3 (承認) §23-2-23 (認証), QMS 省令 (平16 厚労省令169), ISO 13485:2016, IEC 62366 (ユーザビリティ), JIS T 14971 (リスクマネジメント), 医療機器プログラム ガイドライン (SaMD) 等)。"
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
                "医療機器 compliance / クラス分類 / QMS / ISO 13485 / SaMD 判断は PMDA + 厚労省 + 登録番号マスタ + 監査 一次確認が前提"
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
            "source_url": "https://www.pmda.go.jp/review-services/drug-reviews/about-reviews/devices/0001.html",
            "source_fetched_at": None,
            "publisher": "PMDA 医療機器審査",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryoukiki/index.html",
            "source_fetched_at": None,
            "publisher": "厚労省 医療機器",
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
