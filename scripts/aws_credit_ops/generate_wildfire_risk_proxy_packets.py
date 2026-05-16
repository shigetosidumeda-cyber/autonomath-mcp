#!/usr/bin/env python3
"""Generate ``wildfire_risk_proxy_v1`` packets (Wave 83 #10 of 10).

業種 (JSIC major) ごとに 山火事 (forest fire / wildfire) risk × 事業所 proxy
(採択密度 proxy) を集計し、descriptive sectoral wildfire risk proxy indicator
として packet 化する。林野火災 発生件数 / 焼失面積 / 山林近接事業所 / 季節
気象条件 (低湿 + 強風) / 気候変動 干ばつ拡大 / 火災予防 林野庁 / 消防防火
体制 / 損害保険評価 判断は林野庁 + 総務省消防庁 + 気象庁 + 都道府県 林務部 +
内閣府防災 + 気候変動適応センター + 損害保険専門家 + 森林学者の一次確認が
前提。

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

PACKAGE_KIND: Final[str] = "wildfire_risk_proxy_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 wildfire risk proxy packet は jpi_adoption_records 業種別 採択密度 "
    "を集計した descriptive proxy で、林野火災 発生件数 / 焼失面積 / 山林"
    "近接事業所 / 季節気象条件 (低湿 + 強風) / 気候変動 干ばつ拡大 / 火災"
    "予防 林野庁 / 消防防火体制 / 損害保険評価 判断は林野庁 + 総務省消防庁 + "
    "気象庁 + 都道府県 林務部 + 内閣府防災 + 気候変動適応センター + 損害"
    "保険専門家 + 森林学者の一次確認が前提です (消防法 §3, 森林法 §10の2, "
    "林野庁 林野火災統計, 消防庁 消防白書 林野火災)。"
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
                "林野火災 発生件数 / 焼失面積 / 山林近接事業所 / 季節気象"
                "条件 / 気候変動 干ばつ拡大 / 火災予防 / 消防防火体制 / "
                "損害保険評価 判断は林野庁 + 総務省消防庁 + 気象庁 + 都"
                "道府県 林務部 + 内閣府防災 + 気候変動適応センター + 損害"
                "保険専門家 + 森林学者の一次確認が前提"
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
            "source_url": "https://www.rinya.maff.go.jp/j/hogo/sanbou/index.html",
            "source_fetched_at": None,
            "publisher": "林野庁 森林保全 林野火災対策",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.fdma.go.jp/publication/hakusho/",
            "source_fetched_at": None,
            "publisher": "総務省消防庁 消防白書",
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
