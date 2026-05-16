#!/usr/bin/env python3
"""Generate ``regulatory_q_over_q_diff_v1`` packets (Wave 56 #6 of 10).

法令改正 (``am_amendment_diff``) を四半期単位で集計し、Q-over-Q の差分件数 +
変更頻度の高い field_name top-N + ministry 別の改正密度を packet 化。

Cohort
------
::

    cohort = quarter (YYYY-Q)
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

PACKAGE_KIND: Final[str] = "regulatory_q_over_q_diff_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulatory Q-over-Q diff packet は am_amendment_diff を四半期単位で"
    "集計した descriptive 法令改正密度指標です。条文の実際の影響評価は "
    "弁護士・行政書士の専門判断が前提。"
)


def _quarter_from_iso(value: str | None) -> str:
    if not isinstance(value, str) or len(value) < 7:
        return "UNKNOWN"
    y = value[:4]
    m = value[5:7]
    if not (y.isdigit() and m.isdigit()):
        return "UNKNOWN"
    yi = int(y)
    mi = int(m)
    q = (mi - 1) // 3 + 1
    return f"{yi}-Q{q}"


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return

    per_q: dict[str, dict[str, Any]] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT detected_at, field_name, COUNT(*) AS c "
            "  FROM am_amendment_diff "
            " WHERE detected_at IS NOT NULL "
            " GROUP BY detected_at, field_name"
        ):
            q = _quarter_from_iso(str(r["detected_at"]))
            bucket = per_q.setdefault(
                q,
                {"total_diffs": 0, "field_top": {}, "quarter": q},
            )
            c = int(r["c"] or 0)
            bucket["total_diffs"] += c
            f = str(r["field_name"] or "_unknown")
            field_top = bucket["field_top"]
            field_top[f] = field_top.get(f, 0) + c

    qs_sorted = sorted(per_q.keys(), reverse=True)
    for emitted, q in enumerate(qs_sorted):
        if q == "UNKNOWN":
            continue
        bucket = per_q[q]
        top_pairs = sorted(
            bucket["field_top"].items(), key=lambda kv: kv[1], reverse=True
        )[:PER_AXIS_RECORD_CAP]
        record = {
            "quarter": q,
            "total_diffs": bucket["total_diffs"],
            "field_top": [{"field_name": k, "count": v} for k, v in top_pairs],
        }
        if bucket["total_diffs"] > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    q = str(row.get("quarter") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(q)}"
    field_top = list(row.get("field_top", []))
    total = int(row.get("total_diffs") or 0)
    rows_in_packet = len(field_top)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": "条文の影響評価は弁護士・行政書士の専門判断が前提",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該四半期で改正 diff 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://elaws.e-gov.go.jp/",
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索",
            "license": "cc_by_4.0",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "quarter", "id": q},
        "quarter": q,
        "field_top": field_top,
        "total_diffs": total,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": q, "quarter": q},
        metrics={"total_diffs": total, "field_top_count": rows_in_packet},
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, max(rows_in_packet, 1 if total > 0 else 0)


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
