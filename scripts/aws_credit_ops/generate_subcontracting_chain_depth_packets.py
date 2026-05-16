"""Generate ``subcontracting_chain_depth_v1`` packets (Wave 87 #7 of 10).

業種 (JSIC major) ごとに 下請 (subcontracting) chain depth signal (採択
密度 proxy) を集計し、descriptive sectoral subcontracting chain depth
indicator として packet 化する。元請 → 1 次下請 → 2 次下請 → 3 次下請 (4
次以下原則禁止 — 建設業法 §22 一括下請負禁止) chain depth / 下請代金支払
遅延 / 下請代金 不当減額 / 下請取引適正化 (下請法 §4 各号) / 下請単価 法
定最低賃金割れ / 中間搾取 / 元請責任 / 履行能力ある下請選定 / 一括下請負
丸投げ 判断は 公正取引委員会 + 中小企業庁 取引調査室 + 国交省 建設業課
+ 弁護士・社労士 + 監査法人 + 元請業者責任者 + 工事業協会の一次確認が
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

PACKAGE_KIND: Final[str] = "subcontracting_chain_depth_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 subcontracting chain depth packet は jpi_adoption_records 業種別"
    " 採択密度 を集計した descriptive proxy で、実際の 元請 → 1 次下請 "
    "→ 2 次下請 → 3 次下請 chain depth / 下請代金支払遅延 / 下請代金 不"
    "当減額 / 下請取引適正化 (下請法 §4 各号) / 下請単価 法定最低賃金割"
    "れ / 中間搾取 / 元請責任 / 履行能力ある下請選定 / 一括下請負 丸投"
    "げ 判断は 公正取引委員会 + 中小企業庁 取引調査室 + 国交省 建設業課"
    " + 弁護士・社労士 + 監査法人 + 元請業者責任者 + 工事業協会の一次"
    "確認が前提です (下請代金支払遅延等防止法 §4, 建設業法 §22 一括下"
    "請負禁止, 建設業法 §26 主任技術者・監理技術者)。"
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
                "元請 → 1 次下請 → 2 次下請 → 3 次下請 chain depth / 下"
                "請代金支払遅延 / 下請代金 不当減額 / 下請取引適正化 "
                "(下請法 §4 各号) / 下請単価 法定最低賃金割れ / 中間搾取"
                " / 元請責任 / 履行能力ある下請選定 / 一括下請負 丸投げ "
                "判断は 公正取引委員会 + 中小企業庁 取引調査室 + 国交省 "
                "建設業課 + 弁護士・社労士 + 監査法人 + 元請業者責任者"
                "の一次確認が前提"
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
            "source_url": "https://www.jftc.go.jp/shitauke/index.html",
            "source_fetched_at": None,
            "publisher": "公正取引委員会 下請法",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.chusho.meti.go.jp/keiei/torihiki/index.html",
            "source_fetched_at": None,
            "publisher": "中小企業庁 下請取引適正化",
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
