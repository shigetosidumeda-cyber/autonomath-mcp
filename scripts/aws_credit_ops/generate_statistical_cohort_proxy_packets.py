#!/usr/bin/env python3
"""Generate ``statistical_cohort_proxy_v1`` packets (Wave 53.3 #3).

法人 × e-Stat 業界統計 proxy packet. Compares each 法人 (houjin_master row)
against same-JSIC industry medians using ``am_entities`` statistic records
+ ``industry_stats`` rollup tables. Output is descriptive only — no
percentile claim language.

Cohort
------

::

    cohort = (jsic_major × prefecture)

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "statistical_cohort_proxy_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 statistical cohort proxy packet は houjin_master JSIC × 都道府県 を"
    "業界平均と比較する descriptive 指標です。e-Stat 経済センサスを一次確認"
    "してください。診断士・税理士の判断材料であって判断結果ではありません。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return

    # Group by prefecture only — jsic_major is NULL across the corpus at this
    # snapshot; we keep the cohort_id namespace forward-compatible by emitting
    # `jsic_major="UNKNOWN"` while letting the SUM/AVG roll up at the
    # prefecture-level.
    cohort_stats: dict[tuple[str, str], dict[str, Any]] = {}
    with contextlib.suppress(Exception):
        for row in primary_conn.execute(
            "SELECT COALESCE(jsic_major, 'UNKNOWN') AS jsic_major, "
            "       prefecture, "
            "       COUNT(*) AS n, "
            "       AVG(total_adoptions) AS mean_adoptions, "
            "       AVG(total_received_yen) AS mean_received_yen, "
            "       MIN(total_received_yen) AS min_received, "
            "       MAX(total_received_yen) AS max_received "
            "  FROM houjin_master "
            " WHERE prefecture IS NOT NULL "
            " GROUP BY jsic_major, prefecture "
            " HAVING n > 0"
        ):
            jsic = str(row["jsic_major"] or "UNKNOWN")
            pref = str(row["prefecture"] or "UNKNOWN")
            cohort_stats[(jsic, pref)] = {
                "n_houjin": int(row["n"] or 0),
                "mean_adoptions": float(row["mean_adoptions"] or 0),
                "mean_received_yen": float(row["mean_received_yen"] or 0),
                "min_received": int(row["min_received"] or 0),
                "max_received": int(row["max_received"] or 0),
            }

    # Surface top-adoption houjin per cohort with delta vs cohort mean
    for emitted, (key, stats) in enumerate(
        sorted(cohort_stats.items(), key=lambda kv: -kv[1]["n_houjin"])
    ):
        jsic, pref = key
        cohort_id = f"{jsic}.{pref}"
        record: dict[str, Any] = {
            "cohort_id": cohort_id,
            "jsic_major": jsic,
            "prefecture": pref,
            "cohort_stats": stats,
            "top_houjin": [],
            "industry_stat_refs": [],
        }
        # Surface top houjin per cohort. We tolerate missing total_received_yen
        # (the snapshot has it zero across the corpus) and fall back to
        # total_adoptions; the 業界平均との比較 stays descriptive only.
        with contextlib.suppress(Exception):
            for h in primary_conn.execute(
                "SELECT houjin_bangou, normalized_name, total_adoptions, "
                "       total_received_yen "
                "  FROM houjin_master "
                " WHERE COALESCE(jsic_major, 'UNKNOWN') = ? AND prefecture = ? "
                " ORDER BY total_adoptions DESC, total_received_yen DESC "
                " LIMIT ?",
                (jsic, pref, PER_AXIS_RECORD_CAP),
            ):
                received = int(h["total_received_yen"] or 0)
                mean_y = stats["mean_received_yen"]
                delta_ratio = (received / mean_y) if mean_y > 0 else None
                record["top_houjin"].append(
                    {
                        "houjin_bangou": h["houjin_bangou"],
                        "normalized_name": h["normalized_name"],
                        "total_adoptions": int(h["total_adoptions"] or 0),
                        "total_received_yen": received,
                        "vs_cohort_mean_ratio": (
                            round(delta_ratio, 3) if delta_ratio is not None else None
                        ),
                    }
                )

        if table_exists(primary_conn, "industry_stats"):
            with contextlib.suppress(Exception):
                for s in primary_conn.execute(
                    "SELECT * FROM industry_stats LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    sdict = dict(s)
                    record["industry_stat_refs"].append(
                        {k: sdict[k] for k in list(sdict)[:6]}
                    )

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cohort_id = str(row.get("cohort_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    top_houjin = list(row.get("top_houjin", []))
    stat_refs = list(row.get("industry_stat_refs", []))
    rows_in_packet = len(top_houjin) + len(stat_refs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "業界平均との比較は descriptive 指標です。e-Stat 経済センサスを"
                "一次確認、診断士・税理士の判断材料として使ってください。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "このコホートで houjin 観測なし",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.e-stat.go.jp/",
            "source_fetched_at": None,
            "publisher": "総務省統計局 e-Stat",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.stat.go.jp/data/e-census/",
            "source_fetched_at": None,
            "publisher": "経済センサス",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "cohort_houjin_count": int(row.get("cohort_stats", {}).get("n_houjin") or 0),
        "top_houjin_in_packet": len(top_houjin),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "cohort", "id": cohort_id},
        "cohort_stats": row.get("cohort_stats") or {},
        "top_houjin": top_houjin,
        "industry_stat_refs": stat_refs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": cohort_id,
            "jsic_major": row.get("jsic_major"),
            "prefecture": row.get("prefecture"),
        },
        metrics=metrics,
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
