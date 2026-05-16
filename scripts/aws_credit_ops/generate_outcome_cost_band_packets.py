#!/usr/bin/env python3
"""Generate ``outcome_cost_band_v1`` packets (Wave 99 #3 of 10).

site/.well-known/jpcite-outcome-catalog.json を元に、outcome × ¥-band
(¥300 / ¥600 / ¥900) cost matrix を pre-built packet 化する。Wave 50 RC1 で
14 outcome contracts に estimated_price_jpy が fill された結果を、agent 側
の cheapest_sufficient_route に直接 bind するための matrix 形式 control packet。

Cohort
------
::

    cohort = cost_band (light=¥300 / standard=¥600 / composed=¥900 / free=¥0)
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from scripts.aws_credit_ops._packet_base import (
    jpcir_envelope,
    safe_packet_id_segment,
)
from scripts.aws_credit_ops._packet_runner import run_generator

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "outcome_cost_band_v1"

#: Canonical outcome catalog (Wave 50 RC1 site/.well-known artifact).
_OUTCOME_CATALOG_PATH: Final[Path] = Path("site/.well-known/jpcite-outcome-catalog.json")

#: Static price-band labels matching the outcome catalog `cost_band` enum.
_BAND_LABEL: Final[dict[str, dict[str, Any]]] = {
    "free": {"label_ja": "無料 (control / preview)", "max_yen": 0},
    "light": {"label_ja": "Light (~¥300)", "max_yen": 300},
    "standard": {"label_ja": "Standard (~¥600)", "max_yen": 600},
    "composed": {"label_ja": "Composed (~¥900)", "max_yen": 900},
}

DEFAULT_DISCLAIMER: Final[str] = (
    "本 outcome cost band packet は site/.well-known/jpcite-outcome-catalog.json "
    "(canonical Wave 50 RC1 artifact) を ¥-band で rollup した cheapest_sufficient_"
    "route 補助 packet で、税理士法 §52 / 弁護士法 §72 / 行政書士法 §1の2 の専門家"
    "業務を代替しない。価格は税抜 (税込 ¥3.30 metered) の estimate で、Stripe "
    "metered billing の実請求が正本。"
)


def _load_outcomes() -> list[dict[str, Any]]:
    if not _OUTCOME_CATALOG_PATH.exists():
        return []
    try:
        data = json.loads(_OUTCOME_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    outs = data.get("outcomes")
    return list(outs) if isinstance(outs, list) else []


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    outcomes = _load_outcomes()
    if not outcomes:
        return

    by_band: dict[str, list[dict[str, Any]]] = {b: [] for b in _BAND_LABEL}
    for o in outcomes:
        band = str(o.get("cost_band") or "free")
        if band not in by_band:
            by_band[band] = []
        by_band[band].append(
            {
                "outcome_contract_id": str(o.get("outcome_contract_id") or ""),
                "display_name": str(o.get("display_name") or ""),
                "estimated_price_jpy": int(o.get("estimated_price_jpy") or 0),
                "package_kind": str(o.get("package_kind") or ""),
                "billable": bool(o.get("billable") or False),
                "preview_endpoint": str(o.get("preview_endpoint") or ""),
                "source_count": int(o.get("source_count") or 0),
                "estimated_tokens_saved": int(o.get("estimated_tokens_saved") or 0),
            }
        )

    emitted = 0
    for band, hints in _BAND_LABEL.items():
        items = by_band.get(band, [])
        record = {
            "cost_band": band,
            "label_ja": str(hints.get("label_ja") or band),
            "max_yen": int(hints.get("max_yen") or 0),
            "outcomes": items,
            "outcome_n": len(items),
        }
        yield record
        emitted += 1
        if limit is not None and emitted >= limit:
            return
    _ = contextlib  # keep import linked


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    band = str(row.get("cost_band") or "free")
    label = str(row.get("label_ja") or "")
    max_yen = int(row.get("max_yen") or 0)
    outcomes = list(row.get("outcomes") or [])
    outcome_n = int(row.get("outcome_n") or len(outcomes))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(band)}"
    rows_in_packet = outcome_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "pricing_or_cap_unconfirmed",
            "description": (
                "estimated_price_jpy は Wave 50 RC1 contract で fill された "
                "estimate、実請求は Stripe metered billing が正本"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 cost_band で outcome 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://jpcite.com/.well-known/jpcite-outcome-catalog.json",
            "source_fetched_at": None,
            "publisher": "jpcite outcome catalog (Wave 50 RC1)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://docs.jpcite.com/pricing/",
            "source_fetched_at": None,
            "publisher": "jpcite ¥3/req pricing docs",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "cost_band", "id": band},
        "cost_band": band,
        "label_ja": label,
        "max_yen": max_yen,
        "outcomes": outcomes,
        "outcome_n": outcome_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": band, "cost_band": band},
        metrics={"outcome_n": outcome_n, "max_yen": max_yen},
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
