"""Generate ``program_post_award_calendar_v1`` packets (Wave 98 #10 of 10).

制度 (program_unified_id) ごとに am_program_calendar_12mo の 12 ヶ月先
month-by-month is_open / deadline event timeline を集計し、descriptive
post-award monitoring calendar indicator として packet 化する。実際の
申請可否 / 締切影響 / 補助金交付決定後の monitoring obligation は 各所管
省庁 + 認定 経営革新等支援機関 + 顧問税理士の一次確認が前提 (補助金交付
規程、中小企業等経営強化法)。

Cohort
------
::

    cohort = program_unified_id (am_program_calendar_12mo.program_unified_id)

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

PACKAGE_KIND: Final[str] = "program_post_award_calendar_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 program post-award calendar packet は am_program_calendar_12mo の "
    "12 ヶ月先 month-by-month is_open / deadline event timeline を集計した "
    "descriptive monitoring calendar で、実際の申請可否 / 締切影響 / 補助金 "
    "交付決定後の monitoring obligation 判断は 各所管省庁 + 認定 経営革新等 "
    "支援機関 + 顧問税理士の一次確認が前提です (補助金交付規程、中小企業等 "
    "経営強化法)。"
)

# am_program_calendar_12mo carries 12 month rows per program, so a max
# of 12 events per packet is the natural envelope budget.
_MAX_MONTHS_PER_PACKET: Final[int] = 12


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_program_calendar_12mo"):
        return
    program_ids: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT program_unified_id, COUNT(*) AS n "
            "  FROM am_program_calendar_12mo "
            " GROUP BY program_unified_id "
            " HAVING n > 0 "
            " ORDER BY program_unified_id"
        ):
            program_ids.append(str(r["program_unified_id"]))

    for emitted, program_id in enumerate(program_ids):
        months: list[dict[str, Any]] = []
        open_n = 0
        closed_n = 0
        with contextlib.suppress(Exception):
            for c in primary_conn.execute(
                "SELECT month_start, is_open, deadline, round_id_json "
                "  FROM am_program_calendar_12mo "
                " WHERE program_unified_id = ? "
                " ORDER BY month_start "
                " LIMIT ?",
                (program_id, _MAX_MONTHS_PER_PACKET),
            ):
                is_open = int(c["is_open"] or 0)
                if is_open == 1:
                    open_n += 1
                else:
                    closed_n += 1
                months.append(
                    {
                        "month_start": str(c["month_start"]),
                        "is_open": is_open,
                        "deadline": (str(c["deadline"]) if c["deadline"] else None),
                        "round_id_json": (str(c["round_id_json"]) if c["round_id_json"] else None),
                    }
                )

        record = {
            "program_id": program_id,
            "months": months,
            "month_n": len(months),
            "open_n": open_n,
            "closed_n": closed_n,
        }
        if len(months) > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    program_id = str(row.get("program_id") or "UNKNOWN")
    months = list(row.get("months") or [])
    month_n = int(row.get("month_n") or len(months))
    open_n = int(row.get("open_n") or 0)
    closed_n = int(row.get("closed_n") or 0)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(program_id)}"
    rows_in_packet = month_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "申請可否 / 締切影響 / 補助金交付決定後の monitoring "
                "obligation 判断は 各所管省庁 + 認定 経営革新等支援機関 + "
                "顧問税理士の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": ("該 program で 12 ヶ月 calendar event 観測無し"),
            }
        )
    if open_n == 0 and rows_in_packet > 0:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": ("12 ヶ月全期間で is_open=0、最新 round 公告反映待ちの可能性"),
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
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "経済産業省 jGrants",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "program_unified_id", "id": program_id},
        "program_unified_id": program_id,
        "months": months,
        "month_n": month_n,
        "open_n": open_n,
        "closed_n": closed_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": program_id,
            "program_unified_id": program_id,
        },
        metrics={
            "month_n": month_n,
            "open_n": open_n,
            "closed_n": closed_n,
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
