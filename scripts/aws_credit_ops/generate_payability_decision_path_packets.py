#!/usr/bin/env python3
"""Generate ``payability_decision_path_v1`` packets (Wave 100 #5 of 10).

Per outcome (am_composed_tool_catalog.tool_id), emit a Payability
decision path comparing the ¥3/req metered cost vs a pure-LLM baseline
(proxy: 1500 token in + 500 token out @ Claude Opus 4.7 rate, NO live
call). Quantifies "cost-saving per use case" along the Wave 51 funnel
`Payability` axis (memory `feedback_cost_saving_v2_quantified.md`
+ `feedback_agent_funnel_6_stages.md`). NO LLM.

Cohort
------
::

    cohort = composed_tool_id (am_composed_tool_catalog.tool_id)
"""

from __future__ import annotations

import contextlib
import json
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

PACKAGE_KIND: Final[str] = "payability_decision_path_v1"

#: jpcite metered price 税込 ¥3.30 — keep as-is for transparency.
_JPCITE_PRICE_JPY_PER_REQ: Final[float] = 3.30

#: Opus 4.7 proxy: ~1500 tok in + 500 tok out @ $15/MTok input + $75/MTok output,
#: 1 USD ≈ ¥155, rounded to whole yen. Defensive estimate, NOT live billing.
_LLM_BASELINE_JPY_PER_OUTCOME: Final[float] = 11.0

DEFAULT_DISCLAIMER: Final[str] = (
    "本 payability decision path packet は ¥3/req metered (税込 ¥3.30) vs pure "
    "LLM baseline (token proxy) の cost-saving descriptive で、顧客 acquisition "
    "助言や 税理士法 §52 範疇の費用判断を代替しない。LLM baseline は token 消費 "
    "概算で実 billing ではなく、Stripe metered + idempotency_cache の真値が出れば "
    "別 packet kind で上書きされる。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_composed_tool_catalog"):
        return

    rows: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT tool_id, version, atomic_tool_chain, domain, description, status "
            "  FROM am_composed_tool_catalog "
            " WHERE status = 'committed' "
            " ORDER BY tool_id, version DESC"
        ):
            rows.append(dict(r))

    seen: set[str] = set()
    emitted = 0
    for r in rows:
        tool_id = str(r.get("tool_id") or "")
        if not tool_id or tool_id in seen:
            continue
        seen.add(tool_id)
        try:
            chain_obj = json.loads(r.get("atomic_tool_chain") or "{}")
        except (TypeError, ValueError):
            continue
        chain = chain_obj.get("atomic_chain") or []
        if not isinstance(chain, list):
            continue
        steps = chain[:7]
        savings_factor = int(chain_obj.get("savings_factor") or 0)
        # Decision path: 1 composed call = 1 ¥3 spend; N atomic calls = N×¥3.
        composed_jpy = _JPCITE_PRICE_JPY_PER_REQ
        atomic_jpy = _JPCITE_PRICE_JPY_PER_REQ * max(len(steps), 1)
        llm_jpy = _LLM_BASELINE_JPY_PER_OUTCOME
        savings_vs_atomic_jpy = round(atomic_jpy - composed_jpy, 2)
        savings_vs_llm_jpy = round(llm_jpy - composed_jpy, 2)
        yield {
            "tool_id": tool_id,
            "version": int(r.get("version") or 1),
            "domain": str(r.get("domain") or ""),
            "description": str(r.get("description") or ""),
            "steps": steps,
            "composed_jpy": composed_jpy,
            "atomic_jpy": atomic_jpy,
            "llm_jpy": llm_jpy,
            "savings_vs_atomic_jpy": savings_vs_atomic_jpy,
            "savings_vs_llm_jpy": savings_vs_llm_jpy,
            "savings_factor": savings_factor,
        }
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    tool_id = str(row.get("tool_id") or "UNKNOWN")
    version = int(row.get("version") or 1)
    steps = list(row.get("steps") or [])
    rows_in_packet = len(steps)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(tool_id)}:v{version}"

    known_gaps = [
        {
            "code": "pricing_or_cap_unconfirmed",
            "description": (
                "LLM baseline は token 消費概算 (¥11/outcome 換算)、実 LLM billing は "
                "プロバイダ / モデル / プロンプト長で大幅変動"
            ),
        },
        {
            "code": "professional_review_required",
            "description": (
                "費用比較は買付判断の補助、税理士法 §52 / 認定 経営革新等支援機関 の 確認が要"
            ),
        },
    ]

    sources = [
        {
            "source_url": "https://docs.jpcite.com/agent-funnel/payability/",
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
        "subject": {"kind": "composed_tool", "id": tool_id},
        "tool_id": tool_id,
        "version": version,
        "domain": str(row.get("domain") or ""),
        "description": str(row.get("description") or ""),
        "decision_path": {
            "composed_call_jpy": float(row.get("composed_jpy") or 0.0),
            "atomic_chain_jpy": float(row.get("atomic_jpy") or 0.0),
            "llm_baseline_jpy": float(row.get("llm_jpy") or 0.0),
            "savings_vs_atomic_jpy": float(row.get("savings_vs_atomic_jpy") or 0.0),
            "savings_vs_llm_jpy": float(row.get("savings_vs_llm_jpy") or 0.0),
            "savings_factor": int(row.get("savings_factor") or 0),
        },
        "atomic_steps": steps,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": tool_id, "tool_id": tool_id, "version": version},
        metrics={
            "atomic_step_n": rows_in_packet,
            "composed_jpy": float(row.get("composed_jpy") or 0.0),
            "atomic_jpy": float(row.get("atomic_jpy") or 0.0),
            "llm_baseline_jpy": float(row.get("llm_jpy") or 0.0),
            "savings_vs_llm_jpy": float(row.get("savings_vs_llm_jpy") or 0.0),
            "savings_factor": int(row.get("savings_factor") or 0),
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
