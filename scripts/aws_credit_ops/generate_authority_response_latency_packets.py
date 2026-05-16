#!/usr/bin/env python3
"""Generate ``authority_response_latency_v1`` packets (Wave 99 #9 of 10).

pc_authority_action_frequency を authority 単位に集計し、
月次 action_count cadence (rolling 12 month) を packet 化する。「authority ×
公的 response latency」proxy として、所管別の改正 / 公示 / パブコメ 反応速度の
descriptive snapshot。Wave 51 dim K (predictive_service) の入力で、agent が
"この所管はいつ動くか" を ¥-band cheapest_sufficient_route に組み込むための
事前 trace。

Cohort
------
::

    cohort = authority_id (am_authority.canonical_id ∩ pc_authority_action_frequency)
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

PACKAGE_KIND: Final[str] = "authority_response_latency_v1"

#: Per-packet month cap.
_MAX_MONTHS_PER_PACKET: Final[int] = 24

DEFAULT_DISCLAIMER: Final[str] = (
    "本 authority response latency packet は pc_authority_action_frequency の "
    "月次 action_count を rolling 12 month で rollup した descriptive proxy で、"
    "個別案件の reply 期日や公示時期の予測ではない。公的所管の reply / 公示 / "
    "パブコメ反応は 所管公示が一次情報、最終判断は 顧問専門家 (税理士 §52 / "
    "弁護士 §72 / 行政書士 §1の2) の一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_authority"):
        return
    if not table_exists(primary_conn, "pc_authority_action_frequency"):
        return

    authorities: list[tuple[str, str, str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT canonical_id, canonical_name, level, COALESCE(website, '') AS website "
            "  FROM am_authority "
            " ORDER BY canonical_id"
        ):
            authorities.append(
                (
                    str(r["canonical_id"]),
                    str(r["canonical_name"]),
                    str(r["level"]),
                    str(r["website"]),
                )
            )

    for emitted, (authority_id, name_ja, level, website) in enumerate(authorities):
        monthly: list[dict[str, Any]] = []
        total_action = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT month_yyyymm, action_count, refreshed_at "
                "  FROM pc_authority_action_frequency "
                " WHERE authority_id = ? "
                " ORDER BY month_yyyymm DESC "
                " LIMIT ?",
                (authority_id, _MAX_MONTHS_PER_PACKET),
            ):
                count = int(r["action_count"] or 0)
                total_action += count
                monthly.append(
                    {
                        "month_yyyymm": str(r["month_yyyymm"] or ""),
                        "action_count": count,
                        "refreshed_at": str(r["refreshed_at"] or ""),
                    }
                )
        # rolling mean (last min(12, len) months)
        rolling_mean: float | None = None
        if monthly:
            window = monthly[: min(12, len(monthly))]
            if window:
                rolling_mean = round(
                    sum(int(m.get("action_count") or 0) for m in window) / len(window), 4
                )
        record = {
            "authority_id": authority_id,
            "authority_name_ja": name_ja,
            "level": level,
            "website": website or None,
            "monthly_action": monthly,
            "month_n": len(monthly),
            "total_action_count": total_action,
            "rolling_mean_12mo": rolling_mean,
        }
        if monthly:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    authority_id = str(row.get("authority_id") or "UNKNOWN")
    name_ja = str(row.get("authority_name_ja") or "")
    level = str(row.get("level") or "")
    website = row.get("website")
    monthly = list(row.get("monthly_action") or [])
    month_n = int(row.get("month_n") or len(monthly))
    total_action = int(row.get("total_action_count") or 0)
    rolling_mean = row.get("rolling_mean_12mo")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(authority_id)}"
    rows_in_packet = month_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "公的所管の reply 期日 / 公示時期 / パブコメ反応は 所管公示 + "
                "顧問専門家の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 authority で月次 action_count 観測無し",
            }
        )
    if rows_in_packet >= _MAX_MONTHS_PER_PACKET:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"月次 row >{_MAX_MONTHS_PER_PACKET} で打切、全期間は "
                    "pc_authority_action_frequency 直接参照が必要"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": website or "https://www.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": name_ja or "e-Gov",
            "license": "gov_standard",
        },
        {
            "source_url": "https://public-comment.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov パブリックコメント",
            "license": "gov_standard",
        },
    ]

    body: dict[str, Any] = {
        "subject": {"kind": "authority", "id": authority_id},
        "authority_id": authority_id,
        "authority_name_ja": name_ja,
        "level": level,
        "website": website,
        "monthly_action": monthly,
        "month_n": month_n,
        "total_action_count": total_action,
        "rolling_mean_12mo": rolling_mean,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": authority_id, "authority_id": authority_id},
        metrics={
            "month_n": month_n,
            "total_action_count": total_action,
            "rolling_mean_12mo": rolling_mean or 0.0,
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
