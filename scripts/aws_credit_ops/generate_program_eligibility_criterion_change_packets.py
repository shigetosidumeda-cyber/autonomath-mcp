"""Generate ``program_eligibility_criterion_change_v1`` packets (Wave 98 #2 of 10).

制度 (program_id) ごとに am_program_eligibility_history の eligibility
diff (initial / content_drift / eligibility_drift / noop) を時系列で
集計し、descriptive eligibility criterion change indicator として packet
化する。実際の申請要件適合判断 / 認定可否は 各所管省庁 + 認定支援機関 +
顧問税理士の一次確認が前提。

Cohort
------
::

    cohort = program_id (am_program_eligibility_history.program_id)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "program_eligibility_criterion_change_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 program eligibility criterion change packet は "
    "am_program_eligibility_history を時系列集計した descriptive "
    "eligibility drift 観測で、実際の申請要件適合判断 / 認定可否 / "
    "提出書類影響は 各所管省庁 + 認定 経営革新等支援機関 + 顧問税理士の "
    "一次確認が前提です (中小企業等経営強化法、各省告示)。"
)

_MAX_CAPTURES_PER_PACKET: Final[int] = 30


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_program_eligibility_history"):
        return
    program_ids: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT program_id, COUNT(*) AS n "
            "  FROM am_program_eligibility_history "
            " GROUP BY program_id "
            " HAVING n > 0 "
            " ORDER BY program_id"
        ):
            program_ids.append(str(r["program_id"]))

    for emitted, program_id in enumerate(program_ids):
        captures: list[dict[str, Any]] = []
        diff_reason_counts: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for c in primary_conn.execute(
                "SELECT captured_at, eligibility_hash, diff_reason "
                "  FROM am_program_eligibility_history "
                " WHERE program_id = ? "
                " ORDER BY captured_at DESC "
                " LIMIT ?",
                (program_id, _MAX_CAPTURES_PER_PACKET),
            ):
                reason = str(c["diff_reason"] or "unknown")
                diff_reason_counts[reason] = diff_reason_counts.get(reason, 0) + 1
                captures.append(
                    {
                        "captured_at": str(c["captured_at"]),
                        "eligibility_hash": (
                            str(c["eligibility_hash"])
                            if c["eligibility_hash"]
                            else None
                        ),
                        "diff_reason": reason,
                    }
                )
        record = {
            "program_id": program_id,
            "captures": captures,
            "capture_n": len(captures),
            "diff_reason_counts": diff_reason_counts,
        }
        if len(captures) > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    program_id = str(row.get("program_id") or "UNKNOWN")
    captures = list(row.get("captures") or [])
    capture_n = int(row.get("capture_n") or len(captures))
    diff_reason_counts = dict(row.get("diff_reason_counts") or {})
    eligibility_drift_n = int(diff_reason_counts.get("eligibility_drift", 0))
    content_drift_n = int(diff_reason_counts.get("content_drift", 0))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(program_id)}"
    rows_in_packet = capture_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "申請要件適合判断 / 認定可否 / 提出書類影響は "
                "各所管省庁 + 認定 経営革新等支援機関 + 顧問税理士の "
                "一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 program で eligibility history 観測無し",
            }
        )
    if rows_in_packet >= _MAX_CAPTURES_PER_PACKET:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    f"capture >{_MAX_CAPTURES_PER_PACKET} で打切、全履歴は "
                    "am_program_eligibility_history 直接参照が必要"
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
            "source_url": "https://www.jizokuka-r5h.jp/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 持続化補助金",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "program_id", "id": program_id},
        "program_id": program_id,
        "captures": captures,
        "capture_n": capture_n,
        "diff_reason_counts": diff_reason_counts,
        "eligibility_drift_n": eligibility_drift_n,
        "content_drift_n": content_drift_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": program_id, "program_id": program_id},
        metrics={
            "capture_n": capture_n,
            "eligibility_drift_n": eligibility_drift_n,
            "content_drift_n": content_drift_n,
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
