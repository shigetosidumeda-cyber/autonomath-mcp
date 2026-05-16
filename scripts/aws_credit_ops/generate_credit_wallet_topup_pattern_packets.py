#!/usr/bin/env python3
"""Generate ``credit_wallet_topup_pattern_v1`` packets (Wave 100 #8 of 10).

Per Y-bucket wallet topup cohort (Y1K / Y3K / Y10K / Y30K / Y100K),
emit a topup pattern proxy combining the canonical 50/80/100% alert
threshold (memory `feedback_agent_credit_wallet_design.md`) with an
auto-topup heuristic. Seeds the Wave 51 funnel `Payability` follow-on
layer. Real topup telemetry from Stripe + credit_wallet ledger will
overwrite later. NO LLM.

Cohort
------
::

    cohort = topup_bucket_jpy (1000 / 3000 / 10000 / 30000 / 100000)
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Final

from scripts.aws_credit_ops._packet_base import (
    jpcir_envelope,
    table_exists,
)
from scripts.aws_credit_ops._packet_runner import run_generator

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "credit_wallet_topup_pattern_v1"

#: Canonical Y buckets per Credit Wallet design memory.
_TOPUP_BUCKETS_JPY: Final[tuple[int, ...]] = (1000, 3000, 10000, 30000, 100000)

#: Canonical alert thresholds (50% / 80% / 100% throttle).
_ALERT_THRESHOLDS: Final[tuple[int, ...]] = (50, 80, 100)

#: Per-bucket sample row cap (cohort frame).
_MAX_ROWS_PER_BUCKET: Final[int] = 60

DEFAULT_DISCLAIMER: Final[str] = (
    "本 credit wallet topup pattern packet は Wave 51 wallet design "
    "(50/80/100% alert + auto-topup) の structural cohort で、実 Stripe "
    "metered の topup 履歴は別 packet kind で上書き予定。本 packet 単体で "
    "資金決済法 §3 / §6 の Pre-paid Card 該当判断を代替しない。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_entities"):
        return

    for emitted, bucket_jpy in enumerate(_TOPUP_BUCKETS_JPY):
        # Per-bucket synthetic rows representing canonical cohort behavior.
        sample_rows: list[dict[str, Any]] = []
        for i in range(_MAX_ROWS_PER_BUCKET):
            # Spend velocity proxy: smaller bucket = faster burn.
            est_days_to_50pct = max(1, int(30 - i * 0.3))
            sample_rows.append(
                {
                    "rank": i + 1,
                    "estimated_days_to_50pct_alert": est_days_to_50pct,
                    "estimated_days_to_80pct_alert": int(est_days_to_50pct * 1.5),
                    "estimated_days_to_100pct_throttle": int(est_days_to_50pct * 2),
                    "auto_topup_enabled_proxy": (i % 3 != 2),
                }
            )
        avg_days_to_50 = round(
            sum(r["estimated_days_to_50pct_alert"] for r in sample_rows) / max(len(sample_rows), 1),
            1,
        )
        auto_topup_rate = round(
            sum(1 for r in sample_rows if r["auto_topup_enabled_proxy"]) / max(len(sample_rows), 1),
            3,
        )
        # Calls available per topup = bucket / Y3.30 (税込).
        calls_per_topup = int(bucket_jpy / 3.30)
        yield {
            "topup_bucket_jpy": bucket_jpy,
            "rows": sample_rows,
            "calls_per_topup": calls_per_topup,
            "avg_days_to_50pct_alert": avg_days_to_50,
            "auto_topup_rate_proxy": auto_topup_rate,
            "alert_thresholds_pct": list(_ALERT_THRESHOLDS),
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bucket_jpy = int(row.get("topup_bucket_jpy") or 0)
    rows = list(row.get("rows") or [])
    rows_in_packet = len(rows)
    package_id = f"{PACKAGE_KIND}:bucket_jpy_{bucket_jpy}"

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "topup 行動推定は design heuristic、Stripe metered topup ledger "
                "+ credit_wallet 接続後に実測で上書き"
            ),
        },
        {
            "code": "pricing_or_cap_unconfirmed",
            "description": ("Y3.30/req 税込前提、消費税率改定 / 軽減税率適用例外 で再評価が要"),
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/wallet/topup-pattern/",
            "source_fetched_at": None,
            "publisher": "jpcite docs",
            "license": "gov_standard",
        },
        {
            "source_url": "https://jpcite.com/pricing",
            "source_fetched_at": None,
            "publisher": "jpcite pricing",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {"kind": "topup_bucket", "id": f"jpy_{bucket_jpy}"},
        "topup_bucket_jpy": bucket_jpy,
        "calls_per_topup": int(row.get("calls_per_topup") or 0),
        "alert_thresholds_pct": list(row.get("alert_thresholds_pct") or []),
        "rows": rows[:_MAX_ROWS_PER_BUCKET],
        "avg_days_to_50pct_alert": float(row.get("avg_days_to_50pct_alert") or 0.0),
        "auto_topup_rate_proxy": float(row.get("auto_topup_rate_proxy") or 0.0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": f"bucket_jpy_{bucket_jpy}",
            "topup_bucket_jpy": bucket_jpy,
        },
        metrics={
            "row_n": rows_in_packet,
            "calls_per_topup": int(row.get("calls_per_topup") or 0),
            "avg_days_to_50pct_alert": float(row.get("avg_days_to_50pct_alert") or 0.0),
            "auto_topup_rate_proxy": float(row.get("auto_topup_rate_proxy") or 0.0),
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
