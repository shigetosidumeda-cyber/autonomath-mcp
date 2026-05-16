"""Generate ``influencer_partnership_signal_v1`` packets (Wave 86 #4 of 10).

業種 (JSIC major) ごとに Influencer 提携 signal (タイアップ広告 / アンバサダー
契約 / ステマ告示遵守 / #PR・#広告 表記 / アフィリエイト link 開示 / ライブ
コマース / YouTuber 起用 / イベント登壇) descriptive sectoral proxy を 採択
密度 経由で集計し packet 化する。本 packet は 消費者庁 ステマ告示 (令和5年9月
内閣府告示第19号) + 景表法 + JIAA インターネット広告倫理綱領 + JARO + WOMマー
ケティング協議会 ガイドラインを一次裏取とする 公開 信号 で、起用契約適法性 /
表示判定 / 利益相反 / 二重決済 / 反社チェック compliance 判断は 弁護士 + 消費
者庁 + JIAA + WOMJ + 反社情報機関の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "influencer_partnership_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 influencer partnership signal packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、起用契約適法性 / 表示判定 "
    "(#PR・#広告) / 利益相反 / 二重決済 / 反社チェック / ステマ告示 compliance "
    "判断は 弁護士 + 消費者庁 + JIAA + WOMマーケティング協議会 + 反社情報機関の"
    "一次確認が前提です (景表法 §5, ステマ告示 令和5年内閣府告示第19号, "
    "暴力団排除条例, JIAA インターネット広告倫理綱領, WOMJ ガイドライン)。"
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
                "起用契約適法性 / 表示判定 (#PR・#広告) / 利益相反 / "
                "二重決済 / 反社チェック / ステマ告示 compliance 判断は "
                "弁護士 + 消費者庁 + JIAA + WOMマーケティング協議会 + "
                "反社情報機関の一次確認が前提"
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
            "source_url": "https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing/",
            "source_fetched_at": None,
            "publisher": "消費者庁 ステマ告示",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.womj.jp/guideline.html",
            "source_fetched_at": None,
            "publisher": "WOMマーケティング協議会 (WOMJ) ガイドライン",
            "license": "public_domain",
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
