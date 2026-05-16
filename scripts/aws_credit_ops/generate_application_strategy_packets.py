#!/usr/bin/env python3
"""Generate ``application_strategy_v1`` packets (Wave 53.2 #11).

申請戦略 template packet. Per program (jpintel.db programs), assemble the
canonical strategy scaffold:

* the program row metadata,
* ``am_application_steps`` ordered ``step_no``,
* ``am_application_round`` upcoming rounds (sorted by close_date).

Output is a scaffold only — NO legal advice, NO LLM. Aimed at
行政書士 / SME owners as preparation-checklist.

Cohort
------

::

    cohort = program_unified_id

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
import sqlite3
import sys
from typing import TYPE_CHECKING, Any, Final

from scripts.aws_credit_ops._packet_base import (
    jpcir_envelope,
    normalise_token,
    safe_packet_id_segment,
    table_exists,
)
from scripts.aws_credit_ops._packet_runner import run_generator

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "application_strategy_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 application strategy packet は scaffold (公開資料からの定型化) のみ。"
    "申請書面作成・代理は行政書士の独占業務 (行政書士法 §1の2)。本 packet "
    "は LLM 推論を含みません。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if jpintel_conn is None or not table_exists(jpintel_conn, "programs"):
        return

    # Build per-program step + round lookups from autonomath.
    steps_lookup: dict[str, list[dict[str, Any]]] = {}
    if table_exists(primary_conn, "am_application_steps"):
        with contextlib.suppress(sqlite3.Error):
            for row in primary_conn.execute(
                "SELECT program_entity_id, step_no, step_title, "
                "       step_description, expected_days, online_or_offline, "
                "       responsible_party "
                "  FROM am_application_steps "
                " ORDER BY program_entity_id, step_no"
            ):
                eid = str(row["program_entity_id"] or "")
                if not eid:
                    continue
                steps_lookup.setdefault(eid, []).append(
                    {
                        "step_no": row["step_no"],
                        "step_title": row["step_title"],
                        "step_description": row["step_description"],
                        "expected_days": row["expected_days"],
                        "online_or_offline": row["online_or_offline"],
                        "responsible_party": row["responsible_party"],
                    }
                )

    rounds_lookup: dict[str, list[dict[str, Any]]] = {}
    if table_exists(primary_conn, "am_application_round"):
        with contextlib.suppress(sqlite3.Error):
            for row in primary_conn.execute(
                "SELECT program_entity_id, round_label, round_seq, "
                "       application_open_date, application_close_date, "
                "       announced_date, status "
                "  FROM am_application_round "
                " ORDER BY program_entity_id, application_close_date"
            ):
                eid = str(row["program_entity_id"] or "")
                if not eid:
                    continue
                rounds_lookup.setdefault(eid, []).append(
                    {
                        "round_label": row["round_label"],
                        "round_seq": row["round_seq"],
                        "application_open_date": row["application_open_date"],
                        "application_close_date": row["application_close_date"],
                        "announced_date": row["announced_date"],
                        "status": row["status"],
                    }
                )

    sql = (
        "SELECT unified_id, primary_name, authority_level, authority_name, "
        "       prefecture, program_kind, tier, coverage_score, "
        "       amount_max_man_yen, subsidy_rate, official_url, source_url "
        "  FROM programs "
        " WHERE excluded = 0 "
        "   AND audit_quarantined = 0 "
        "   AND tier IN ('S','A','B','C') "
        " ORDER BY tier, unified_id"
    )
    emitted = 0
    for row in jpintel_conn.execute(sql):
        uid = normalise_token(row["unified_id"])
        if uid == "UNKNOWN":
            continue
        # Soft-link via uid substring against entity_id keys (best-effort).
        steps: list[dict[str, Any]] = []
        rounds: list[dict[str, Any]] = []
        for eid, step_list in steps_lookup.items():
            if uid in eid:
                steps = step_list[:PER_AXIS_RECORD_CAP]
                break
        for eid, round_list in rounds_lookup.items():
            if uid in eid:
                rounds = round_list[:PER_AXIS_RECORD_CAP]
                break
        yield {
            "program_unified_id": uid,
            "primary_name": row["primary_name"],
            "authority_level": row["authority_level"],
            "authority_name": row["authority_name"],
            "prefecture": row["prefecture"],
            "program_kind": row["program_kind"],
            "tier": row["tier"],
            "coverage_score": row["coverage_score"],
            "amount_max_man_yen": row["amount_max_man_yen"],
            "subsidy_rate": row["subsidy_rate"],
            "official_url": row["official_url"],
            "source_url": row["source_url"],
            "steps": steps,
            "rounds": rounds,
        }
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    uid = normalise_token(row.get("program_unified_id"))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(uid)}"
    steps = list(row.get("steps", []))
    rounds = list(row.get("rounds", []))

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "申請書面作成・代理は行政書士の独占業務 (行政書士法 §1の2)。"
                "本 packet は scaffold のみで、提出書類の最終確認は行政書士・"
                "所管官庁公示で実施。"
            ),
        }
    ]
    if not steps:
        known_gaps.append(
            {
                "code": "source_receipt_incomplete",
                "description": (
                    "application_steps が観測されていません — 要綱 PDF /"
                    "募集要項を一次確認"
                ),
            }
        )
    if not rounds:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "application_round が観測されていません — 一次官公庁公示で確認"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": str(row.get("official_url") or row.get("source_url") or "https://www.e-gov.go.jp/"),
            "source_fetched_at": None,
            "publisher": str(row.get("authority_name") or "制度所管官庁"),
            "license": "gov_standard",
        }
    ]
    metrics = {
        "steps_count": len(steps),
        "rounds_count": len(rounds),
        "tier": row.get("tier"),
    }
    body = {
        "program": {
            "program_unified_id": uid,
            "primary_name": row.get("primary_name"),
            "authority_level": row.get("authority_level"),
            "authority_name": row.get("authority_name"),
            "prefecture": row.get("prefecture"),
            "program_kind": row.get("program_kind"),
            "tier": row.get("tier"),
            "coverage_score": row.get("coverage_score"),
            "amount_max_man_yen": row.get("amount_max_man_yen"),
            "subsidy_rate": row.get("subsidy_rate"),
            "official_url": row.get("official_url"),
            "source_url": row.get("source_url"),
        },
        "strategy_steps": steps,
        "upcoming_rounds": rounds,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": uid,
            "program_unified_id": uid,
        },
        metrics=metrics,
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, max(len(steps), 1)


def main(argv: Sequence[str] | None = None) -> int:
    return run_generator(
        argv=argv,
        package_kind=PACKAGE_KIND,
        default_db="autonomath.db",
        aggregate=_aggregate,
        render=_render,
        needs_jpintel=True,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
