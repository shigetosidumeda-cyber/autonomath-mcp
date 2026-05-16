#!/usr/bin/env python3
"""Generate ``program_amendment_velocity_v1`` packets (Wave 99 #8 of 10).

am_amendment_diff の per-program event 数 + observed window から amendment
velocity (改正頻度 / 月) を packet 化する。Wave 22 の `forecast_program_renewal`
+ Wave 98 ``subsidy_program_amendment_lineage_v1`` の **velocity**
(field-by-field 改正の rolling 月次密度) を、agent runtime 側の "次の改正窓 / 監視
優先度" 推定 input として事前 trace。

Cohort
------
::

    cohort = program_entity_id (am_amendment_diff.entity_id ∩ record_kind='program')
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

PACKAGE_KIND: Final[str] = "program_amendment_velocity_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 program amendment velocity packet は am_amendment_diff の rolling 月次 "
    "密度を packet 化した descriptive proxy で、次回改正窓の予測ではない。"
    "改正観測 / 適用 / 申請影響は 所管省庁公示 + 認定 経営革新等支援機関 + "
    "顧問税理士 (§52) + 行政書士 (§1の2) の一次確認が前提。eligibility_hash は "
    "v1/v2 で変化しない場合があるため、time-series は 144 dated rows のみ firm。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return
    if not table_exists(primary_conn, "am_entities"):
        return

    rows: list[tuple[str, str, int, str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT e.canonical_id, e.primary_name, "
            "       COUNT(d.diff_id) AS event_n, "
            "       MIN(d.detected_at) AS first_at, "
            "       MAX(d.detected_at) AS last_at "
            "  FROM am_entities e "
            "  JOIN am_amendment_diff d ON d.entity_id = e.canonical_id "
            " WHERE e.record_kind = 'program' "
            " GROUP BY e.canonical_id "
            " ORDER BY event_n DESC, e.canonical_id"
        ):
            rows.append(
                (
                    str(r["canonical_id"]),
                    str(r["primary_name"] or ""),
                    int(r["event_n"] or 0),
                    str(r["first_at"] or ""),
                    str(r["last_at"] or ""),
                )
            )

    for emitted, (entity_id, primary_name, event_n, first_at, last_at) in enumerate(rows):
        # Per-month velocity: rough month delta from first→last detected_at.
        velocity_per_month: float | None = None
        if first_at and last_at and event_n > 0:
            try:
                from datetime import datetime as _dt

                f = _dt.fromisoformat(first_at.replace("Z", "+00:00"))
                latest = _dt.fromisoformat(last_at.replace("Z", "+00:00"))
                delta_days = max(1.0, (latest - f).total_seconds() / 86400.0)
                months = max(1.0, delta_days / 30.0)
                velocity_per_month = round(event_n / months, 4)
            except (TypeError, ValueError):
                velocity_per_month = None

        record = {
            "entity_id": entity_id,
            "primary_name": primary_name,
            "event_n": event_n,
            "first_detected_at": first_at or None,
            "last_detected_at": last_at or None,
            "velocity_per_month": velocity_per_month,
        }
        if event_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity_id = str(row.get("entity_id") or "UNKNOWN")
    primary_name = str(row.get("primary_name") or "")
    event_n = int(row.get("event_n") or 0)
    first_at = row.get("first_detected_at")
    last_at = row.get("last_detected_at")
    velocity = row.get("velocity_per_month")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity_id)}"
    rows_in_packet = event_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "改正観測 / 適用 / 申請影響は 所管省庁公示 + 認定 経営革新等"
                "支援機関 + 顧問税理士 + 行政書士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 program で amendment diff 観測無し",
            }
        )
    known_gaps.append(
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "am_amendment_snapshot の eligibility_hash は v1/v2 で変化しない "
                "場合があり、time-series は 144 dated rows のみ firm (CLAUDE.md 注記)"
            ),
        }
    )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.chusho.meti.go.jp/keiei/kakushin/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 経営革新等支援機関",
            "license": "gov_standard",
        },
        {
            "source_url": "https://elaws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "program_entity", "id": entity_id},
        "entity_id": entity_id,
        "primary_name": primary_name,
        "event_n": event_n,
        "first_detected_at": first_at,
        "last_detected_at": last_at,
        "velocity_per_month": velocity,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": entity_id, "program_entity_id": entity_id},
        metrics={"event_n": event_n, "velocity_per_month": velocity or 0.0},
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
