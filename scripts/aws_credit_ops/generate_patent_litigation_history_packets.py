#!/usr/bin/env python3
"""Generate ``patent_litigation_history_v1`` packets (Wave 82 #5 of 10).

業種 (JSIC major) ごとに 特許 訴訟 history (侵害訴訟 / 無効審判 /
差止 / 損害賠償) の descriptive sectoral proxy を 採択密度 経由で
集計し packet 化する。侵害判断 / 均等論 / クレーム解釈 / 損害額
算定 (特許法 §102) / 差止仮処分判断は弁護士 + 弁理士 + 知財高裁
判例 + 特許庁審判官の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "patent_litigation_history_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 patent litigation history packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、特許 侵害訴訟 / 無効審判 / "
    "差止 / 仮処分 / 損害賠償 / 均等論 / クレーム解釈 / 補正 / 訂正 / "
    "国際特許訴訟 (ITC, EPO) 判断は弁護士 + 弁理士 + 知財高裁判例 + 特許庁"
    "審判官の一次確認が前提です (特許法 §100, §102, §123, §126, 民事訴訟法, "
    "弁護士法 §72, 弁理士法 §4)。"
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
                "特許 侵害訴訟 / 無効審判 / 差止 / 仮処分 / 損害賠償 / "
                "均等論 / クレーム解釈 / 補正 / 訂正 / 国際特許訴訟判断は"
                "弁護士 + 弁理士 + 知財高裁判例 + 特許庁審判官の一次確認が"
                "前提"
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
            "source_url": "https://www.ip.courts.go.jp/",
            "source_fetched_at": None,
            "publisher": "知的財産高等裁判所",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.j-platpat.inpit.go.jp/g0100",
            "source_fetched_at": None,
            "publisher": "特許庁 j-platpat 審判検索",
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
