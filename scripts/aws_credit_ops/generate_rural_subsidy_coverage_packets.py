#!/usr/bin/env python3
"""Generate ``rural_subsidy_coverage_v1`` packets (Wave 57 #9 of 10).

過疎地域 (am_region population_band IN ('xs','s')) 補助金 coverage。
人口 < 10万人の市区町村を「rural」と定義し、各都道府県の rural municipality 数と
補助金採択密度を packet 化。

Cohort
------
::

    cohort = prefecture
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

PACKAGE_KIND: Final[str] = "rural_subsidy_coverage_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 rural subsidy coverage packet は am_region の人口バンド + "
    "jpi_adoption_records を join した descriptive coverage 指標です。"
    "過疎地域指定の正確な定義は総務省 過疎地域自立促進特別措置法に基づく"
    "一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_region"):
        return
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT parent_code AS pc FROM am_region "
            " WHERE region_level = 'municipality' AND parent_code IS NOT NULL"
        ):
            pc = str(r["pc"] or "")
            if pc:
                prefs.append(pc)

    for emitted, pref_code in enumerate(prefs):
        pref_name = ""
        rural_munis: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT name_ja FROM am_region WHERE region_code = ?",
                (pref_code,),
            ).fetchone()
            if row:
                pref_name = str(row[0] or "")
        if not pref_name:
            continue
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT r.name_ja AS municipality, r.population_band, r.population, "
                "       COALESCE(("
                "         SELECT COUNT(*) FROM jpi_adoption_records a "
                "          WHERE a.prefecture = ? AND a.municipality = r.name_ja"
                "       ), 0) AS adoptions "
                "  FROM am_region r "
                " WHERE r.region_level = 'municipality' "
                "   AND r.parent_code = ? "
                "   AND (r.population_band IN ('xs','s') OR r.population < 100000) "
                " ORDER BY adoptions DESC LIMIT ?",
                (pref_name, pref_code, PER_AXIS_RECORD_CAP),
            ):
                rural_munis.append(dict(r))
        if not rural_munis:
            continue
        total_munis = len(rural_munis)
        munis_with_coverage = sum(1 for d in rural_munis if int(d.get("adoptions") or 0) > 0)
        record = {
            "prefecture": pref_name,
            "prefecture_code": pref_code,
            "rural_municipalities": rural_munis,
            "rural_municipality_total": total_munis,
            "municipalities_with_coverage": munis_with_coverage,
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    munis = list(row.get("rural_municipalities", []))
    rows_in_packet = len(munis)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "「過疎地域」の正確な指定は過疎地域自立促進特別措置法ベースで"
                "総務省一次確認が必要 — 人口バンド近似のみ。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で rural municipality 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/",
            "source_fetched_at": None,
            "publisher": "総務省 過疎対策",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "rural_municipalities": munis,
        "rural_municipality_total": int(row.get("rural_municipality_total") or 0),
        "municipalities_with_coverage": int(
            row.get("municipalities_with_coverage") or 0
        ),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "rural_municipality_total": int(row.get("rural_municipality_total") or 0),
            "municipalities_with_coverage": int(
                row.get("municipalities_with_coverage") or 0
            ),
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
