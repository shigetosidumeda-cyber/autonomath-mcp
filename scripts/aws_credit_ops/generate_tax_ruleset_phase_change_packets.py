#!/usr/bin/env python3
"""Generate ``tax_ruleset_phase_change_v1`` packets (Wave 56 #4 of 10).

税制 ruleset の effective_from / effective_until に基づく段階変更タイムラインを
税目 (tax_category) 単位で packet 化する。

Cohort
------
::

    cohort = tax_category (national/local/corporate/income/consumption/property/inheritance)
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

PACKAGE_KIND: Final[str] = "tax_ruleset_phase_change_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 tax ruleset phase change packet は jpi_tax_rulesets の effective_from / "
    "effective_until を時系列に並べた descriptive 指標です。実際の適用判断は "
    "税理士確認 + 所管官庁 (国税庁・財務省・総務省) 公示の一次確認が前提 "
    "(税理士法 §52)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_tax_rulesets"):
        return
    cats: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT tax_category FROM jpi_tax_rulesets "
            " WHERE tax_category IS NOT NULL AND tax_category != ''"
        ):
            cats.append(str(r["tax_category"]))

    for emitted, cat in enumerate(cats):
        timeline: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT unified_id, ruleset_name, ruleset_kind, "
                "       effective_from, effective_until, rate_or_amount, "
                "       authority, source_url "
                "  FROM jpi_tax_rulesets "
                " WHERE tax_category = ? "
                " ORDER BY effective_from DESC LIMIT ?",
                (cat, PER_AXIS_RECORD_CAP),
            ):
                d = dict(r)
                rate = d.get("rate_or_amount")
                if isinstance(rate, str) and len(rate) > 160:
                    d["rate_or_amount"] = rate[:160] + "…"
                timeline.append(d)
        record = {
            "tax_category": cat,
            "phase_changes": timeline,
            "count": len(timeline),
        }
        if timeline:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cat = str(row.get("tax_category") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cat)}"
    phases = list(row.get("phase_changes", []))
    rows_in_packet = len(phases)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "税制適用判断は税理士確認 + 所管官庁公示の一次確認が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 tax_category で段階変更 ruleset 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.mof.go.jp/tax_policy/",
            "source_fetched_at": None,
            "publisher": "財務省 税制",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "tax_category", "id": cat},
        "tax_category": cat,
        "phase_changes": phases,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": cat, "tax_category": cat},
        metrics={"phase_change_count": rows_in_packet},
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
