"""Generate ``press_release_pulse_v1`` packets (Wave 86 #9 of 10).

業種 (JSIC major) ごとに Press release pulse signal (PR TIMES / 共同通信 PR
Wire / @Press / Value Press / 自社 newsroom / 自治体合同 PR / 政策発表連動 /
ニュースリリース件数 / 季節性 / メディア露出) descriptive sectoral proxy を
採択密度 経由で集計し packet 化する。本 packet は 景表法 + 金商法 公平開示 +
適時開示 + 公正取引委員会 + 各 PR wire 公式利用規約 を一次裏取とする 公開 信
号 で、表示適法性 / 過大表現 / インサイダー類似 / プレスリリース転載判定 /
記事内容 PR 表記 (景表法 § 5) 判断は 弁護士 + 各業界自主規制機関 + 取引所 +
PR 配信代行サービスの一次確認が前提。

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

PACKAGE_KIND: Final[str] = "press_release_pulse_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 press release pulse packet は jpi_adoption_records 業種別 採択密度 "
    "を集計した descriptive proxy で、表示適法性 / 過大表現 / インサイダー類似 "
    "/ プレスリリース転載判定 / 記事内容 PR 表記 / 取引所 適時開示連動 判断は "
    "弁護士 + 各業界自主規制機関 + 取引所 + PR 配信代行サービスの一次確認が"
    "前提です (景表法 §5, 金商法 §166, §167, 取引所 適時開示規則, ステマ告示 "
    "令和5年内閣府告示第19号, 不正競争防止法 §2)。"
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
                "表示適法性 / 過大表現 / インサイダー類似 / プレスリリース"
                "転載判定 / 記事内容 PR 表記 / 取引所 適時開示連動 判断は "
                "弁護士 + 各業界自主規制機関 + 取引所 + PR 配信代行サービス"
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
            "source_url": "https://www.jpx.co.jp/regulation/listing/disclosure/index.html",
            "source_fetched_at": None,
            "publisher": "東京証券取引所 適時開示制度",
            "license": "public_domain",
        },
        {
            "source_url": "https://www.caa.go.jp/policies/policy/representation/fair_labeling/",
            "source_fetched_at": None,
            "publisher": "消費者庁 不当表示 (景表法)",
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
