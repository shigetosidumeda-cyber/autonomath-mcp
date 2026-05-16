#!/usr/bin/env python3
"""Generate ``municipal_tax_subsidy_cohort_v1`` packets (Wave 55 #6).

地方税 ruleset (jpi_tax_rulesets local-tax slice) × 自治体補助金 ×
産業 (e-Stat / JSIC) 3-axis cohort packet. For each prefecture, surface
the local-tax slice of national/prefectural tax rulesets paired with
the adoption density per JSIC major within that prefecture.

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

PACKAGE_KIND: Final[str] = "municipal_tax_subsidy_cohort_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 municipal tax subsidy cohort packet は地方税 ruleset スライス + "
    "自治体補助金採択 × 産業 cross-link です。地方税条例の正本は各自治体"
    "公報、補助金は Jグランツ + 各自治体公報を一次確認。地方税適用判断は"
    "税理士確認が前提です (税理士法 §52 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    # Local-tax slice of rulesets (local tax category) — full-table cache (small)
    local_tax_rules: list[dict[str, Any]] = []
    if table_exists(primary_conn, "jpi_tax_rulesets"):
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT unified_id, ruleset_name, tax_category, ruleset_kind, "
                "       effective_from, effective_until "
                "  FROM jpi_tax_rulesets "
                " WHERE tax_category IN ('local','property','inheritance')"
                " ORDER BY effective_from DESC "
                " LIMIT 30"
            ):
                local_tax_rules.append(dict(r))

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
            "local_tax_rules": [dict(t) for t in local_tax_rules][:PER_AXIS_RECORD_CAP],
            "industry_density": [],
            "total_adoptions": 0,
            "total_amount_yen": 0,
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount_granted_yen), 0) AS s "
                "  FROM jpi_adoption_records WHERE prefecture = ?",
                (pref,),
            ):
                record["total_adoptions"] = int(r["c"] or 0)
                record["total_amount_yen"] = int(r["s"] or 0)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT substr(industry_jsic_medium, 1, 1) AS jsic_major, "
                "       COUNT(*) AS adoptions, "
                "       COUNT(DISTINCT houjin_bangou) AS unique_houjin, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                "   AND industry_jsic_medium IS NOT NULL "
                " GROUP BY substr(industry_jsic_medium, 1, 1) "
                " ORDER BY total_amount_yen DESC "
                " LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                record["industry_density"].append(
                    {
                        "jsic_major": r["jsic_major"],
                        "adoptions": int(r["adoptions"] or 0),
                        "unique_houjin": int(r["unique_houjin"] or 0),
                        "total_amount_yen": int(r["total_amount_yen"] or 0),
                    }
                )

        if record["total_adoptions"] > 0 or record["local_tax_rules"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    rules = list(row.get("local_tax_rules", []))
    density = list(row.get("industry_density", []))
    rows_in_packet = len(rules) + len(density)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "地方税条例の正本は各自治体公報、補助金は Jグランツ + 各自治体"
                "公報を一次確認。地方税適用判断は税理士確認が前提。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で地方税 × 産業密度の cross-link 該当無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_zeisei/",
            "source_fetched_at": None,
            "publisher": "総務省 地方税制度",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "local_tax_rule_count": len(rules),
        "industry_density_bucket_count": len(density),
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "local_tax_rules": rules,
        "industry_density": density,
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
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
