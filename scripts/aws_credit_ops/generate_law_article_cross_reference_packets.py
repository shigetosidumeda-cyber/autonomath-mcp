"""Generate ``law_article_cross_reference_v1`` packets (Wave 98 #9 of 10).

法令 (am_law_article.law_canonical_id) ごとに、条文数 + 改正活動 (last_amended
分布) + 英訳カバレッジ (body_en non-null 比率) を集計し、descriptive law
article cross-reference indicator として packet 化する。実際の条文有効性
/ 改正発効日適用 / 解釈は 各所管省庁 + 弁護士 + 顧問税理士の一次確認が
前提 (e-Gov 法令検索、各省告示、弁護士法 §72)。

Cohort
------
::

    cohort = law_canonical_id (am_law_article.law_canonical_id)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "law_article_cross_reference_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 law article cross-reference packet は am_law_article を法令別に "
    "集計した descriptive cross-reference indicator で、実際の条文有効性 "
    "/ 改正発効日適用 / 解釈判断は 各所管省庁 + 弁護士 + 顧問税理士の "
    "一次確認が前提です (e-Gov 法令検索 CC-BY 4.0、各省告示、弁護士法 §72)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_law_article"):
        return
    laws: list[tuple[str, int]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT law_canonical_id, COUNT(*) AS n "
            "  FROM am_law_article "
            " GROUP BY law_canonical_id "
            " HAVING n > 0 "
            " ORDER BY law_canonical_id"
        ):
            laws.append((str(r["law_canonical_id"]), int(r["n"] or 0)))

    for emitted, (law_canonical_id, article_n) in enumerate(laws):
        article_kind_counts: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT article_kind, COUNT(*) AS n "
                "  FROM am_law_article "
                " WHERE law_canonical_id = ? "
                " GROUP BY article_kind",
                (law_canonical_id,),
            ):
                article_kind_counts[str(r["article_kind"] or "main")] = int(r["n"] or 0)

        body_en_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM am_law_article "
                " WHERE law_canonical_id = ? AND body_en IS NOT NULL",
                (law_canonical_id,),
            ).fetchone()
            if row:
                body_en_n = int(row["n"] or 0)

        # last_amended max + min as time-band bounds.
        last_amended_min: str | None = None
        last_amended_max: str | None = None
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT MIN(last_amended) AS lo, MAX(last_amended) AS hi "
                "  FROM am_law_article "
                " WHERE law_canonical_id = ? AND last_amended IS NOT NULL",
                (law_canonical_id,),
            ).fetchone()
            if row:
                last_amended_min = str(row["lo"]) if row["lo"] is not None else None
                last_amended_max = str(row["hi"]) if row["hi"] is not None else None

        record = {
            "law_canonical_id": law_canonical_id,
            "article_n": article_n,
            "article_kind_counts": article_kind_counts,
            "body_en_n": body_en_n,
            "body_en_ratio": (body_en_n / article_n) if article_n > 0 else 0.0,
            "last_amended_min": last_amended_min,
            "last_amended_max": last_amended_max,
        }
        if article_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    law_canonical_id = str(row.get("law_canonical_id") or "UNKNOWN")
    article_n = int(row.get("article_n") or 0)
    article_kind_counts = dict(row.get("article_kind_counts") or {})
    body_en_n = int(row.get("body_en_n") or 0)
    body_en_ratio = float(row.get("body_en_ratio") or 0.0)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(law_canonical_id)}"
    rows_in_packet = article_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "条文有効性 / 改正発効日適用 / 解釈判断は "
                "各所管省庁 + 弁護士 + 顧問税理士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 law で article 観測無し",
            }
        )
    if body_en_ratio < 1.0:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"英訳 (body_en) カバレッジ {body_en_n}/{article_n} "
                    "= 100% 未達、英語参照には注意"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://elaws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
        {
            "source_url": "https://www.japaneselawtranslation.go.jp/",
            "source_fetched_at": None,
            "publisher": "日本法令外国語訳データベース",
            "license": "cc_by_4.0",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "law_canonical_id", "id": law_canonical_id},
        "law_canonical_id": law_canonical_id,
        "article_n": article_n,
        "article_kind_counts": article_kind_counts,
        "body_en_n": body_en_n,
        "body_en_ratio": round(body_en_ratio, 4),
        "last_amended_min": row.get("last_amended_min"),
        "last_amended_max": row.get("last_amended_max"),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": law_canonical_id,
            "law_canonical_id": law_canonical_id,
        },
        metrics={
            "article_n": article_n,
            "body_en_n": body_en_n,
            "body_en_ratio": round(body_en_ratio, 4),
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
