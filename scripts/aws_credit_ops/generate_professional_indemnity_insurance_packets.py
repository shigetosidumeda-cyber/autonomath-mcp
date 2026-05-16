"""Generate ``professional_indemnity_insurance_v1`` packets (Wave 94 #7 of 10).

業種 (JSIC major) ごとに 専門職業賠償責任保険 (Professional Indemnity /
Errors & Omissions, E&O) coverage (士業 / コンサル / IT / 医療 / 設計
業務上の過誤 / 説明義務違反 / 法令違反) の coverage 兆候 (採択密度 proxy)
を集計し, descriptive sectoral professional indemnity indicator として
packet 化する。実際の限度額 / 退職後 ROR / 自由業 cover / claims-made
ベース / 弁護士費用 / regulatory action 判断は損保会社 + 士業専門ブロー
カー + 各士業会 + 弁護士 (専門職責任) の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "professional_indemnity_insurance_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 professional indemnity (E&O) insurance packet は jpi_adoption_records"
    " 業種別 採択密度 を集計した descriptive proxy で、実際の限度額 / 退職後"
    " ROR / 自由業 cover / claims-made ベース / 弁護士費用 / regulatory "
    "action / 説明義務違反 / 法令違反 / 各士業会 strict liability 判断は"
    "損保会社 + 士業専門ブローカー + 各士業会 + 弁護士 (専門職責任) の"
    "一次確認が前提です (税理士法 §39 §39-2 §40 損害賠償, 公認会計士法 "
    "§30 §31 監査責任, 弁護士法 §27 §28 弁護士の任務, 建築士法 §22 §23 "
    "設計監理 損害賠償, 民法 §709 §415 債務不履行)。"
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
                "限度額 / 退職後 ROR / 自由業 cover / claims-made ベース / "
                "弁護士費用 / regulatory action / 説明義務違反 / 法令違反 / "
                "各士業会 strict liability 判断は損保会社 + 士業ブローカー +"
                " 各士業会 + 弁護士 (専門職責任) の一次確認が前提"
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
            "source_url": "https://www.nichizeiren.or.jp/",
            "source_fetched_at": None,
            "publisher": "日本税理士会連合会 (税理士業務賠償責任)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nichibenren.or.jp/",
            "source_fetched_at": None,
            "publisher": "日本弁護士連合会 (弁護士賠償責任)",
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
