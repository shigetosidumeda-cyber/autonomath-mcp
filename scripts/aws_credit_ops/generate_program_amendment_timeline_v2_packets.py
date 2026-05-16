#!/usr/bin/env python3
"""Generate ``program_amendment_timeline_v2`` packets (Wave 56 #1 of 10).

制度 (program) ごとに ``am_amendment_diff`` の改正履歴を時系列で並べ、
``am_amendment_snapshot`` で観測された影響期間を packet 化する。

Cohort
------
::

    cohort = program_unified_id (jpi_programs)

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

PACKAGE_KIND: Final[str] = "program_amendment_timeline_v2"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 program amendment timeline packet は am_amendment_diff + "
    "am_amendment_snapshot を制度単位で時系列化した descriptive 指標です。"
    "改正の効力発生・適用範囲は所管官庁公示・税理士確認が前提 "
    "(税理士法 §52 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return

    # Iterate from am_amendment_diff entity_id (canonical autonomath identifier)
    entity_ids: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT entity_id, COUNT(*) AS c "
            "  FROM am_amendment_diff "
            " GROUP BY entity_id ORDER BY c DESC LIMIT 5000"
        ):
            eid = str(r["entity_id"] or "")
            if eid:
                entity_ids.append(eid)

    for emitted, eid in enumerate(entity_ids):
        record: dict[str, Any] = {
            "entity_id": eid,
            "amendment_history": [],
            "snapshot_periods": [],
            "diff_count": 0,
            "snapshot_count": 0,
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT field_name, prev_value, new_value, detected_at, "
                "       source_url "
                "  FROM am_amendment_diff "
                " WHERE entity_id = ? "
                " ORDER BY detected_at DESC LIMIT ?",
                (eid, PER_AXIS_RECORD_CAP),
            ):
                rd = dict(r)
                for k in ("prev_value", "new_value"):
                    v = rd.get(k)
                    if isinstance(v, str) and len(v) > 200:
                        rd[k] = v[:200] + "…"
                record["amendment_history"].append(rd)
                record["diff_count"] += 1
        if table_exists(primary_conn, "am_amendment_snapshot"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT version_seq, observed_at, effective_from, "
                    "       effective_until, amount_max_yen, subsidy_rate_max "
                    "  FROM am_amendment_snapshot "
                    " WHERE entity_id = ? "
                    " ORDER BY observed_at DESC LIMIT ?",
                    (eid, PER_AXIS_RECORD_CAP),
                ):
                    record["snapshot_periods"].append(dict(r))
                    record["snapshot_count"] += 1
        if record["diff_count"] > 0 or record["snapshot_count"] > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    eid = str(row.get("entity_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(eid)}"
    history = list(row.get("amendment_history", []))
    snapshots = list(row.get("snapshot_periods", []))
    rows_in_packet = len(history) + len(snapshots)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "改正の効力発生・適用範囲は所管官庁公示が一次情報、"
                "税理士確認が前提 (税理士法 §52)。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "改正履歴・snapshot 観測無し — 一次官公庁公示確認が必要",
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
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "diff_count": int(row.get("diff_count") or 0),
        "snapshot_count": int(row.get("snapshot_count") or 0),
        "total_records": rows_in_packet,
    }
    body: dict[str, Any] = {
        "subject": {"kind": "entity", "id": eid},
        "entity_id": eid,
        "amendment_history": history,
        "snapshot_periods": snapshots,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": eid, "entity_id": eid},
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
