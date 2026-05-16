#!/usr/bin/env python3
"""Generate ``entity_court_360_v1`` packets (Wave 69 #4 of 10).

法人 × all-judgements axes. Search ``jpi_court_decisions`` for cases
where the houjin's normalized_name appears in ``case_name`` /
``parties_involved`` / ``key_ruling`` and bundle into a per-entity
judgement rollup.

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

PACKAGE_KIND: Final[str] = "entity_court_360_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity court 360 packet は normalized_name による名寄せ 1-call "
    "rollup です。同姓・同名衝突や法人格違いで誤マッチが発生し得る — 各 "
    "事件は事件番号を一次確認してください (司法書士法 §3 領域)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    if not table_exists(primary_conn, "jpi_court_decisions"):
        return
    cap = int(limit) if limit is not None else 100000
    # Seed from jpi_adoption_records — top-ranked houjin are most likely to
    # also appear as parties in court_decisions name match.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, COUNT(a.id) AS adopt_count "
        "  FROM jpi_adoption_records AS a "
        "  JOIN houjin_master AS h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        "   AND h.normalized_name IS NOT NULL "
        " GROUP BY h.houjin_bangou "
        " ORDER BY adopt_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        normalized_name = str(base["normalized_name"] or "")
        if not normalized_name:
            continue
        # Use substring match — case_name / parties_involved are free text.
        like_pat = f"%{normalized_name}%"
        cases: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT unified_id, case_name, case_number, court, "
                "       court_level, decision_date, decision_type, "
                "       subject_area, key_ruling, full_text_url "
                "  FROM jpi_court_decisions "
                " WHERE case_name LIKE ? OR parties_involved LIKE ? "
                " ORDER BY decision_date DESC LIMIT ?",
                (like_pat, like_pat, PER_AXIS_RECORD_CAP),
            ):
                cases.append(
                    {
                        "unified_id": r["unified_id"],
                        "case_name": r["case_name"],
                        "case_number": r["case_number"],
                        "court": r["court"],
                        "court_level": r["court_level"],
                        "decision_date": r["decision_date"],
                        "decision_type": r["decision_type"],
                        "subject_area": r["subject_area"],
                        "key_ruling": (
                            str(r["key_ruling"])[:200]
                            if r["key_ruling"] is not None
                            else None
                        ),
                        "full_text_url": r["full_text_url"],
                    }
                )
        yield {
            "houjin_bangou": bangou,
            "normalized_name": normalized_name,
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "cases": cases,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    cases = list(row.get("cases", []))
    # Always emit ≥1 row marker (court name match is sparse — no_hit semantics).
    rows_in_packet = max(len(cases), 1)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "case_name / parties_involved 名寄せ — 同名・類似名による"
                "誤マッチが残存。事件番号での個別確認必須。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "判例観測無し = 訴訟経験ゼロを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.courts.go.jp/app/hanrei_jp/search1",
            "source_fetched_at": None,
            "publisher": "裁判所 (最高裁判所)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "case_count": len(cases),
        "court_levels": sorted({str(c.get("court_level") or "") for c in cases}),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "cases": cases,
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
