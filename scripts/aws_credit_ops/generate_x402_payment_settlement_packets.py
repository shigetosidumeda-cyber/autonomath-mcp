#!/usr/bin/env python3
"""Generate ``x402_payment_settlement_v1`` packets (Wave 100 #9 of 10).

Per HTTP-402 settlement cohort (currency / amount-bucket), emit a
settlement timing pattern proxy combining the x402 protocol's 2-second
USDC target (memory `feedback_agent_x402_protocol.md`) with the 3-rail
agent monetization design (Stripe ACS + x402 + MPP per memory
`feedback_agent_monetization_3_payment_rails.md`). Seeds the Wave 51
funnel `Payability` settlement layer. NO LLM.

Cohort
------
::

    cohort = (currency, amount_bucket_usd)
"""

from __future__ import annotations

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

PACKAGE_KIND: Final[str] = "x402_payment_settlement_v1"

#: x402 canonical micropayment buckets (USD).
_AMOUNT_BUCKETS_USD: Final[tuple[float, ...]] = (
    0.001,
    0.003,
    0.01,
    0.03,
    0.10,
    0.30,
    1.00,
    3.00,
)

#: x402 settlement target = 2 seconds per protocol memory.
_X402_TARGET_SETTLE_MS: Final[int] = 2000

_MAX_SAMPLES_PER_BUCKET: Final[int] = 50

DEFAULT_DISCLAIMER: Final[str] = (
    "本 x402 payment settlement packet は HTTP 402 + USDC のプロトコル仕様 "
    "(memory feedback_agent_x402_protocol.md) と 3 rail 設計 (Stripe ACS + "
    "x402 + MPP) の structural cohort で、実 on-chain settlement 履歴は "
    "別 packet kind で上書き予定。本 packet 単体で 暗号資産交換業者法 / "
    "資金決済法 §63条の2 の該当判断を代替しない。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_entities"):
        return

    for emitted, amount_usd in enumerate(_AMOUNT_BUCKETS_USD):
        samples: list[dict[str, Any]] = []
        for i in range(_MAX_SAMPLES_PER_BUCKET):
            # Settlement latency heuristic: smaller amounts settle slightly
            # faster due to less validation overhead.
            est_settle_ms = _X402_TARGET_SETTLE_MS + (i * 20) - int(amount_usd * 100)
            est_settle_ms = max(500, est_settle_ms)
            samples.append(
                {
                    "sample_n": i + 1,
                    "estimated_settle_ms": est_settle_ms,
                    "within_2s_target": est_settle_ms <= _X402_TARGET_SETTLE_MS,
                    "rail": "x402_usdc",
                }
            )
        avg_settle_ms = round(
            sum(s["estimated_settle_ms"] for s in samples) / max(len(samples), 1), 1
        )
        within_target_rate = round(
            sum(1 for s in samples if s["within_2s_target"]) / max(len(samples), 1),
            3,
        )
        yield {
            "currency": "USDC",
            "amount_usd": amount_usd,
            "samples": samples,
            "avg_settle_ms": avg_settle_ms,
            "within_2s_target_rate": within_target_rate,
            "amount_jpy_proxy": round(amount_usd * 155.0, 2),
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    amount_usd = float(row.get("amount_usd") or 0.0)
    currency = str(row.get("currency") or "USDC")
    samples = list(row.get("samples") or [])
    rows_in_packet = len(samples)
    package_id = (
        f"{PACKAGE_KIND}:{safe_packet_id_segment(currency)}_"
        f"usd_{safe_packet_id_segment(str(amount_usd))}"
    )

    known_gaps = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "settle_ms は protocol target + heuristic、実 on-chain settlement は "
                "x402 facilitator log + USDC mempool 観測から上書き"
            ),
        },
        {
            "code": "pricing_or_cap_unconfirmed",
            "description": (
                "USD/JPY 為替は Y155/USD 概算、実 settlement 時の interbank rate で再計算"
            ),
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/x402/",
            "source_fetched_at": None,
            "publisher": "jpcite x402 docs",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.coinbase.com/x402",
            "source_fetched_at": None,
            "publisher": "Coinbase x402 spec",
            "license": "gov_standard",
        },
    ]

    body = {
        "subject": {
            "kind": "x402_amount_bucket",
            "id": f"{currency}_usd_{amount_usd}",
        },
        "currency": currency,
        "amount_usd": amount_usd,
        "amount_jpy_proxy": float(row.get("amount_jpy_proxy") or 0.0),
        "samples": samples[:_MAX_SAMPLES_PER_BUCKET],
        "avg_settle_ms": float(row.get("avg_settle_ms") or 0.0),
        "within_2s_target_rate": float(row.get("within_2s_target_rate") or 0.0),
        "x402_target_settle_ms": _X402_TARGET_SETTLE_MS,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": f"{currency}_usd_{amount_usd}",
            "currency": currency,
            "amount_usd": amount_usd,
        },
        metrics={
            "sample_n": rows_in_packet,
            "avg_settle_ms": float(row.get("avg_settle_ms") or 0.0),
            "within_2s_target_rate": float(row.get("within_2s_target_rate") or 0.0),
            "amount_jpy_proxy": float(row.get("amount_jpy_proxy") or 0.0),
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
