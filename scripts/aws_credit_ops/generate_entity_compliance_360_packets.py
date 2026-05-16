#!/usr/bin/env python3
"""Generate ``entity_compliance_360_v1`` packets (Wave 69 #2 of 10).

法人 × all-enforcement axes. Bundle ``am_enforcement_detail`` rows
(exclusion / grant_refund / fine 等) + ``jpi_enforcement_cases`` 補助金等
不正使用 events into a single per-houjin compliance brief.

Cohort
------

::

    cohort = houjin_bangou (13-digit, canonical subject.kind = "houjin")
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

PACKAGE_KIND: Final[str] = "entity_compliance_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity compliance 360 packet は行政処分 + 補助金等不正使用事案を"
    "1-call で並べた descriptive rollup です。法的評価は弁護士確認、"
    "与信判断は契約書 + 一次出典の個別確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    if not table_exists(primary_conn, "am_enforcement_detail"):
        return
    cap = int(limit) if limit is not None else 100000
    # Seed from am_enforcement_detail ranked by event count.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, COUNT(e.enforcement_id) AS event_count "
        "  FROM am_enforcement_detail AS e "
        "  JOIN houjin_master AS h ON h.houjin_bangou = e.houjin_bangou "
        " WHERE e.houjin_bangou IS NOT NULL "
        "   AND length(e.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " ORDER BY event_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        events: list[dict[str, Any]] = []
        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT enforcement_kind, issuing_authority, issuance_date, "
                    "       reason_summary, amount_yen, source_url "
                    "  FROM am_enforcement_detail "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY issuance_date DESC LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    events.append(
                        {
                            "axis": "administrative_enforcement",
                            "kind": r["enforcement_kind"],
                            "authority": r["issuing_authority"],
                            "date": r["issuance_date"],
                            "summary": (
                                str(r["reason_summary"])[:160]
                                if r["reason_summary"] is not None
                                else None
                            ),
                            "amount_yen": int(r["amount_yen"] or 0),
                            "source_url": r["source_url"],
                        }
                    )
        if table_exists(primary_conn, "jpi_enforcement_cases"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT event_type, ministry, prefecture, "
                    "       reason_excerpt, amount_yen, source_url, "
                    "       disclosed_date "
                    "  FROM jpi_enforcement_cases "
                    " WHERE recipient_houjin_bangou = ? "
                    " ORDER BY disclosed_date DESC LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    events.append(
                        {
                            "axis": "subsidy_misuse",
                            "kind": r["event_type"],
                            "authority": r["ministry"],
                            "date": r["disclosed_date"],
                            "summary": (
                                str(r["reason_excerpt"])[:160]
                                if r["reason_excerpt"] is not None
                                else None
                            ),
                            "amount_yen": int(r["amount_yen"] or 0),
                            "source_url": r["source_url"],
                        }
                    )
        if not events:
            continue
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "events": events,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    events = list(row.get("events", []))
    rows_in_packet = len(events)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "法的評価は弁護士確認。与信判断は契約書 + 一次出典の"
                "個別確認が必要。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "観測 event 無し = clean を意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "event_count": len(events),
        "axis_count": len({e.get("axis") for e in events}),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "events": events,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": bangou, "houjin_bangou": bangou},
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
