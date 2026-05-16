"""Generate ``electrical_safety_audit_v1`` packets (Wave 92 #9).

業種 (JSIC major) ごとに 電気安全 audit 兆候 (採択密度 proxy) を集計し、
descriptive sectoral electrical safety audit indicator として packet 化する。電安法 (電気用品安全法) / PSE / 特定電気用品 / 自主検査 / 技術基準適合 判断は 経産省 + NITE + 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "electrical_safety_audit_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 electrical safety audit packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、電気安全 audit / 電安法 (電気用品安全法) / PSE マーク (菱形 = 特定電気用品 / 丸形 = 特定以外電気用品) / 自主検査 / 技術基準適合 / 工場検査 / 適合性検査 / 電池 (リチウムイオン) PSE / 電気事業法 §39 §43 (技術基準) 判断は 経産省 + NITE + 登録検査機関 + 一次確認が前提です "
    "(電気用品安全法 §10 (届出事業者) §27 (表示) §28 (販売制限), 電気用品の技術上の基準を定める省令 (令1, 令2), 電気事業法 §39 §40 §43, 工業標準化法 §19, JIS C 9335-1 (家電安全) 等)。"
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
                "電気安全 audit / 電安法 / PSE / 特定電気用品 / 技術基準適合 / 工場検査 判断は 経産省 + NITE + 登録検査機関 + 一次確認が前提"
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
            "source_url": "https://www.meti.go.jp/policy/consumer/seian/denan/",
            "source_fetched_at": None,
            "publisher": "経済産業省 電気用品安全法 (PSE)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nite.go.jp/safety/index.html",
            "source_fetched_at": None,
            "publisher": "NITE 製品安全",
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
