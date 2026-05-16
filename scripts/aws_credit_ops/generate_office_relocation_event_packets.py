"""Generate ``office_relocation_event_v1`` packets (Wave 93 #4 of 10).

業種 (JSIC major) ごとに 事務所移転 event 兆候 (採択密度 proxy) を集計し、
descriptive sectoral office relocation event indicator として packet 化する。
実際の 本店移転 / 支店移転 / 商業登記変更 / 移転日 / 移転理由 / 移転規模 /
移転費用 / 移転補助金 (都市移転 / 地方移転) / 印紙税 / 登録免許税 判断は
法務局 商業登記 (本店所在地変更登記) + 有価証券報告書 「沿革」 + 国土交通省
本社機能移転促進税制 + 内閣府 地方創生推進交付金 + 公証人役場 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "office_relocation_event_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 office relocation event packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、実際の 本店移転 / 支店"
    "移転 / 商業登記変更 / 移転日 / 移転理由 / 移転規模 / 移転費用 / "
    "移転補助金 (本社機能 移転 / 地方移転) / 印紙税 / 登録免許税 判断"
    "は 法務局 商業登記 (本店所在地変更登記) + 有価証券報告書 「沿革」"
    " + 国土交通省 本社機能移転促進税制 + 内閣府 地方創生推進交付金 + "
    "公証人役場 一次確認が前提です (会社法 §911 §915 (本店所在地登記),"
    " 商業登記法 §17, 登録免許税法 別表第一第1号 (商業登記), 地方拠点"
    "強化税制 (措置法 §10-4 §42-11-3 §62-3-2), 地方創生推進交付金 ガイド"
    "ライン)。"
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
                "本店移転 / 支店移転 / 商業登記変更 / 移転日 / 移転"
                "理由 / 移転規模 / 移転費用 / 移転補助金 (本社機能"
                "移転 / 地方移転) / 印紙税 / 登録免許税 判断は 法務"
                "局 商業登記 (本店所在地変更登記) + 有価証券報告書"
                " 「沿革」 + 国土交通省 本社機能移転促進税制 + 内閣"
                "府 地方創生推進交付金 + 公証人役場 一次確認が前提"
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
            "source_url": "https://www.moj.go.jp/MINJI/minji06_00027.html",
            "source_fetched_at": None,
            "publisher": "法務省 商業登記 本店所在地変更登記",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.chisou.go.jp/sousei/about/honsyakinou/",
            "source_fetched_at": None,
            "publisher": "内閣府 本社機能移転促進・地方拠点強化税制",
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
