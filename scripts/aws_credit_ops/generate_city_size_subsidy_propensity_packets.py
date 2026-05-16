#!/usr/bin/env python3
"""Generate ``city_size_subsidy_propensity_v1`` packets (Wave 57 #5 of 10).

自治体規模 (am_region population_band) × 補助金率の傾向を packet 化。
人口バンドごとの平均交付額・採択件数 propensity を都道府県別に出す。

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

PACKAGE_KIND: Final[str] = "city_size_subsidy_propensity_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 city size subsidy propensity packet は am_region の population_band と "
    "jpi_adoption_records を join した descriptive 傾向指標です。municipality "
    "正規化精度に依存。"
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

    have_region = table_exists(primary_conn, "am_region")
    for emitted, pref in enumerate(prefs):
        muni_rows: list[dict[str, Any]] = []
        if have_region:
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT a.municipality, "
                    "       COUNT(*) AS adoptions, "
                    "       COALESCE(AVG(a.amount_granted_yen), 0) AS avg_amount_yen, "
                    "       COALESCE(SUM(a.amount_granted_yen), 0) AS total_amount_yen, "
                    "       r.population_band "
                    "  FROM jpi_adoption_records a "
                    "  LEFT JOIN am_region r ON r.name_ja = a.municipality "
                    " WHERE a.prefecture = ? "
                    "   AND a.municipality IS NOT NULL AND a.municipality != '' "
                    " GROUP BY a.municipality, r.population_band "
                    " ORDER BY adoptions DESC LIMIT ?",
                    (pref, PER_AXIS_RECORD_CAP),
                ):
                    muni_rows.append(dict(r))
        else:
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT municipality, "
                    "       COUNT(*) AS adoptions, "
                    "       COALESCE(AVG(amount_granted_yen), 0) AS avg_amount_yen, "
                    "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                    "  FROM jpi_adoption_records "
                    " WHERE prefecture = ? "
                    "   AND municipality IS NOT NULL AND municipality != '' "
                    " GROUP BY municipality "
                    " ORDER BY adoptions DESC LIMIT ?",
                    (pref, PER_AXIS_RECORD_CAP),
                ):
                    muni_rows.append({**dict(r), "population_band": None})
        record = {"prefecture": pref, "municipality_propensity": muni_rows}
        if muni_rows:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    munis = list(row.get("municipality_propensity", []))
    rows_in_packet = len(munis)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": "municipality 名 normalization 精度 = am_region join 結果に依存",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で municipality propensity 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/",
            "source_fetched_at": None,
            "publisher": "総務省 地方行政",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "municipality_propensity": munis,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"municipality_count": rows_in_packet},
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
