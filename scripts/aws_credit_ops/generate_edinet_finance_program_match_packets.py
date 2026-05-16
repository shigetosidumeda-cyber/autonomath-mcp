#!/usr/bin/env python3
"""Generate ``edinet_finance_program_match_v1`` packets (Wave 53.3 #5).

EDINET 財務 × 制度 (補助金 / 投資減税) financial-impact packet. Cross-joins
``houjin_master`` (上場 + 関係会社) with ``jpi_adoption_records`` (補助金実績)
and ``jpi_tax_rulesets`` (税制特例) — surfaces program-level cap × actual
adoption amount × treated as deductible/credit, all as descriptive table
rows for accountant review.

Cohort
------

::

    cohort = houjin_bangou (13-digit)

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

PACKAGE_KIND: Final[str] = "edinet_finance_program_match_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 edinet finance program match packet は houjin_master + 補助金採択 + "
    "税制特例 の descriptive 紐付けです。財務インパクトの正本は EDINET "
    "有価証券報告書 を一次確認、税務処理の判断は会計士・税理士に委ねて"
    "ください (税理士法 §52)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    # Drive packet set from adoption-side (any houjin with at least one
    # adoption row). The corpus has 201,845 adoption rows; we cap the
    # candidate list at the requested limit.
    cap = int(limit) if limit is not None else 100000
    sql = (
        "SELECT a.houjin_bangou, "
        "       COALESCE(h.normalized_name, '') AS normalized_name, "
        "       h.prefecture, h.jsic_major, "
        "       COALESCE(h.total_adoptions, 0) AS total_adoptions, "
        "       COALESCE(h.total_received_yen, 0) AS total_received_yen, "
        "       COUNT(*) AS adoption_count "
        "  FROM jpi_adoption_records a "
        "  LEFT JOIN houjin_master h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY a.houjin_bangou "
        " ORDER BY adoption_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        record: dict[str, Any] = {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "total_received_yen": int(base["total_received_yen"] or 0),
            "adoption_rows": [],
            "tax_rulesets": [],
        }
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for ad in primary_conn.execute(
                    "SELECT program_id, program_name_raw, amount_granted_yen, "
                    "       announced_at, round_label, source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                    " LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    record["adoption_rows"].append(
                        {
                            "program_id": ad["program_id"],
                            "program_name": ad["program_name_raw"],
                            "amount_yen": int(ad["amount_granted_yen"] or 0),
                            "announced_at": ad["announced_at"],
                            "round_label": ad["round_label"],
                            "source_url": ad["source_url"],
                            "accounting_axis": "income_other_or_capital_grant",
                        }
                    )
        if table_exists(primary_conn, "jpi_tax_rulesets"):
            with contextlib.suppress(Exception):
                for tr in primary_conn.execute(
                    "SELECT rule_id, rule_name, source_url "
                    "  FROM jpi_tax_rulesets "
                    " LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    record["tax_rulesets"].append(
                        {
                            "rule_id": tr["rule_id"],
                            "rule_name": tr["rule_name"],
                            "source_url": tr["source_url"],
                        }
                    )
        if record["adoption_rows"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    adoptions = list(row.get("adoption_rows", []))
    rulesets = list(row.get("tax_rulesets", []))
    rows_in_packet = len(adoptions) + len(rulesets)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "補助金の会計処理 (圧縮記帳 / 直接控除 / 益金処理) + 税制特例の"
                "適用判断は会計士・税理士の確認が必須。EDINET 正本確認も併読。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "この法人で補助金 + 税制特例の組み合わせ観測なし",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": f"https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx?bj1k={bangou}",
            "source_fetched_at": None,
            "publisher": "金融庁 EDINET",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nta.go.jp/taxes/shiraberu/zeimu-sankou/",
            "source_fetched_at": None,
            "publisher": "国税庁 税務参考",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "adoption_row_count": len(adoptions),
        "tax_ruleset_count": len(rulesets),
        "total_received_yen": int(row.get("total_received_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "adoption_rows": adoptions,
        "tax_rulesets": rulesets,
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
