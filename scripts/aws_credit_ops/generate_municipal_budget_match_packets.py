#!/usr/bin/env python3
"""Generate ``municipal_budget_match_v1`` packets (Wave 54 #6).

47都道府県 + 政令市 (J11) × 補助金 (J05) packet. For each prefecture-code,
aggregate adoption totals + program count by 自治体 prefix. The packet
exposes per-pref aggregation surface so an agent can ask "what is the
adoption density × scale in prefecture X?".

Cohort
------

::

    cohort = prefecture (都道府県名)

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

PACKAGE_KIND: Final[str] = "municipal_budget_match_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 municipal budget match packet は採択履歴の都道府県別 aggregate です。"
    "自治体予算規模 (歳入・歳出) は総務省 地方財政状況調査、自治体公示は"
    "各自治体公報を一次確認してください。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_adoption_records "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        record: dict[str, Any] = {
            "prefecture": pref,
            "total_adoptions": 0,
            "total_amount_yen": 0,
            "top_programs": [],
            "top_municipalities": [],
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount_granted_yen), 0) AS s "
                "  FROM jpi_adoption_records WHERE prefecture = ?",
                (pref,),
            ):
                record["total_adoptions"] = int(r["c"] or 0)
                record["total_amount_yen"] = int(r["s"] or 0)
        # Top programs by total amount.
        with contextlib.suppress(Exception):
            for prog in primary_conn.execute(
                "SELECT program_name_raw, COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                "   AND program_name_raw IS NOT NULL "
                " GROUP BY program_name_raw "
                " ORDER BY amount_yen DESC "
                " LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                record["top_programs"].append(
                    {
                        "program_name": prog["program_name_raw"],
                        "adoptions": int(prog["adoptions"] or 0),
                        "amount_yen": int(prog["amount_yen"] or 0),
                    }
                )
        # Top municipalities by total amount.
        with contextlib.suppress(Exception):
            for mun in primary_conn.execute(
                "SELECT municipality, COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                "   AND municipality IS NOT NULL "
                " GROUP BY municipality "
                " ORDER BY amount_yen DESC "
                " LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                record["top_municipalities"].append(
                    {
                        "municipality": mun["municipality"],
                        "adoptions": int(mun["adoptions"] or 0),
                        "amount_yen": int(mun["amount_yen"] or 0),
                    }
                )

        if record["total_adoptions"] > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    progs = list(row.get("top_programs", []))
    muns = list(row.get("top_municipalities", []))
    rows_in_packet = len(progs) + len(muns)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "自治体予算規模は総務省 地方財政状況調査を一次確認。"
                "本 packet は採択側の集計で、予算側突合は未実施。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "この都道府県では採択集計 0 件 — 採択記録未収録の可能性",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.soumu.go.jp/iken/zaisei/jokyo_chousa.html",
            "source_fetched_at": None,
            "publisher": "総務省 地方財政状況調査",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
        "top_program_count": len(progs),
        "top_municipality_count": len(muns),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
        "top_programs": progs,
        "top_municipalities": muns,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
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
