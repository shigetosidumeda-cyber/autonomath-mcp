#!/usr/bin/env python3
"""Generate ``industry_association_link_v1`` packets (Wave 58 #9 of 10).

業界団体 × 法人 link。jpi_support_org (商工会・商工会議所等) と
jpi_adoption_records を都道府県で join し、地域業界団体の支援対象法人を
descriptive にリンク。

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

PACKAGE_KIND: Final[str] = "industry_association_link_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

DEFAULT_DISCLAIMER: Final[str] = (
    "本 industry association link packet は jpi_support_org (商工会・商工会議所等)"
    "と jpi_adoption_records を都道府県で連結した descriptive link 指標です。"
    "実際の会員 mapping は各団体の名簿の一次確認が必要。"
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

    have_support = table_exists(primary_conn, "jpi_support_org")
    for emitted, pref in enumerate(prefs):
        support_orgs: list[dict[str, Any]] = []
        if have_support:
            with contextlib.suppress(Exception):
                # Try common column names
                cols_to_try = [
                    ("name", "prefecture"),
                    ("org_name", "prefecture"),
                    ("normalized_name", "prefecture"),
                ]
                for name_col, pref_col in cols_to_try:
                    try:
                        for r in primary_conn.execute(
                            f"SELECT {name_col} AS name, {pref_col} AS pref "
                            f"  FROM jpi_support_org WHERE {pref_col} = ? LIMIT ?",
                            (pref, PER_AXIS_RECORD_CAP),
                        ):
                            support_orgs.append(dict(r))
                        if support_orgs:
                            break
                    except Exception:
                        continue
        top_industry_by_amount: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT substr(industry_jsic_medium, 1, 1) AS jsic, "
                "       COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? AND industry_jsic_medium IS NOT NULL "
                " GROUP BY substr(industry_jsic_medium, 1, 1) "
                " ORDER BY total_amount_yen DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                top_industry_by_amount.append(dict(r))
        record = {
            "prefecture": pref,
            "support_organizations": support_orgs,
            "top_industry_link": top_industry_by_amount,
        }
        if support_orgs or top_industry_by_amount:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    orgs = list(row.get("support_organizations", []))
    inds = list(row.get("top_industry_link", []))
    rows_in_packet = len(orgs) + len(inds)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": "支援団体 × 法人会員 mapping は各団体名簿の一次確認が必要",
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で支援団体 link データ無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.shokokai.or.jp/",
            "source_fetched_at": None,
            "publisher": "全国商工会連合会",
            "license": "proprietary",
        },
        {
            "source_url": "https://www.jcci.or.jp/",
            "source_fetched_at": None,
            "publisher": "日本商工会議所",
            "license": "proprietary",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "support_organizations": orgs,
        "top_industry_link": inds,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "support_org_count": len(orgs),
            "industry_link_count": len(inds),
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
