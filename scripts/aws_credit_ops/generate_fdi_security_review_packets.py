#!/usr/bin/env python3
"""Generate ``fdi_security_review_v1`` packets (Wave 64 #8 of 10).

国 (am_tax_treaty) ごとに 外為法 事前審査 (FDI security review) 関連制度を
集約し、descriptive cross-border FDI security review intensity proxy として
packet 化する。外為法第27条 / 指定業種 + 事前届出判断は所管官庁 (財務省 + 経産省)
+ 弁護士の一次確認が前提。

Cohort
------
::

    cohort = country_iso (ISO 3166-1 alpha-2)
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

PACKAGE_KIND: Final[str] = "fdi_security_review_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

PROGRAM_KEYWORDS: Final[tuple[str, ...]] = (
    "外為法", "対内直接投資", "事前届出", "事前審査", "指定業種",
    "FIRRMA", "コア業種", "経済安全保障", "重要技術", "重要鉱物",
    "外資審査", "対日M&A",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 FDI security review packet は am_tax_treaty 条約国 × jpi_programs "
    "name + 外為法 事前審査 keyword 検索による descriptive 指標です。外為法"
    "第27条 / コア業種指定 / 事前届出義務判断は財務省 + 経産省 + 弁護士の"
    "一次確認が前提 (弁護士法 §72)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_tax_treaty"):
        return
    if not table_exists(primary_conn, "jpi_programs"):
        return

    treaties: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT country_iso, country_name_ja, country_name_en, treaty_kind "
            "  FROM am_tax_treaty ORDER BY country_iso"
        ):
            treaties.append(dict(r))

    where_clauses = " OR ".join(["primary_name LIKE ?" for _ in PROGRAM_KEYWORDS])
    params = tuple(f"%{kw}%" for kw in PROGRAM_KEYWORDS)
    candidates: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT unified_id, primary_name, authority_level, prefecture, "
            "       program_kind, tier "
            "  FROM jpi_programs "
            f" WHERE excluded = 0 AND ({where_clauses}) "
            " ORDER BY tier ASC LIMIT 200",
            params,
        ):
            candidates.append(dict(r))

    for emitted, t in enumerate(treaties):
        country_iso = str(t.get("country_iso") or "")
        country_name_ja = str(t.get("country_name_ja") or "")
        matches: list[dict[str, Any]] = []
        for p in candidates[:PER_AXIS_RECORD_CAP]:
            matches.append(
                {
                    "unified_id": p.get("unified_id"),
                    "primary_name": p.get("primary_name"),
                    "authority_level": p.get("authority_level"),
                    "prefecture": p.get("prefecture"),
                    "program_kind": p.get("program_kind"),
                }
            )
        record = {
            "country_iso": country_iso,
            "country_name_ja": country_name_ja,
            "country_name_en": t.get("country_name_en"),
            "treaty_kind": t.get("treaty_kind"),
            "fdi_security_review_programs": matches,
            "candidate_pool_size": len(candidates),
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    country_iso = str(row.get("country_iso") or "UNKNOWN")
    country_name_ja = str(row.get("country_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(country_iso)}"
    matched = list(row.get("fdi_security_review_programs", []))
    rows_in_packet = len(matched) + 1

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "外為法第27条 / コア業種指定 / 事前届出義務判断は財務省 + "
                "経産省 + 弁護士の一次確認が前提"
            ),
        }
    ]
    if not matched:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "公開 jpi_programs に 外為法 事前審査 keyword 制度 未観測"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": (
                "https://www.mof.go.jp/policy/international_policy/gaitame_kawase/"
                "gaitame/fdi/"
            ),
            "source_fetched_at": None,
            "publisher": "財務省 外為法 対内直接投資 (事前届出)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/anpo/foreign_capital.html",
            "source_fetched_at": None,
            "publisher": "経済産業省 外資 事前届出",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": country_iso},
        "country_iso": country_iso,
        "country_name_ja": country_name_ja,
        "country_name_en": row.get("country_name_en"),
        "treaty_kind": row.get("treaty_kind"),
        "fdi_security_review_programs": matched,
        "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": country_iso, "country_iso": country_iso},
        metrics={
            "fdi_security_review_program_count": len(matched),
            "candidate_pool_size": int(row.get("candidate_pool_size") or 0),
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
