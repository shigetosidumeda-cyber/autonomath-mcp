#!/usr/bin/env python3
"""Generate ``program_eligibility_chain_v1`` packets (Wave 99 #4 of 10).

制度 (program entity) ごとに am_subsidy_rule / am_target_profile / am_amount_
condition / am_industry_jsic を結合し、apply_eligibility_chain_am call trace
の入力となる **eligibility chain skeleton** を packet 化する。implicit な
chain (subsidy_rule → target_profile → amount_condition → industry_jsic) を
固定して agent runtime の chain 解決を 1 call に圧縮するための事前 trace。

Cohort
------
::

    cohort = program_entity_id (am_entities.canonical_id, record_kind='program')
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

PACKAGE_KIND: Final[str] = "program_eligibility_chain_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 program eligibility chain packet は am_subsidy_rule + am_target_profile + "
    "am_amount_condition + am_industry_jsic を replay した descriptive skeleton "
    "で、最終的な制度適用判断 / 申請可否 / 締切影響は 各所管省庁 + 認定 経営革新等"
    "支援機関 + 顧問税理士 (§52) + 行政書士 (§1の2) の一次確認が前提 (中小企業等経営"
    "強化法 / 補助金交付規程)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_entities"):
        return
    if not table_exists(primary_conn, "am_subsidy_rule"):
        return

    program_rows: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT e.canonical_id, e.primary_name "
            "  FROM am_entities e "
            "  JOIN am_subsidy_rule s ON s.program_entity_id = e.canonical_id "
            " WHERE e.record_kind = 'program' "
            " ORDER BY e.canonical_id"
        ):
            program_rows.append((str(r["canonical_id"]), str(r["primary_name"] or "")))

    for emitted, (entity_id, primary_name) in enumerate(program_rows):
        rules: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for s in primary_conn.execute(
                "SELECT rule_type, base_rate_pct, cap_yen, per_unit_yen, "
                "       unit_type, effective_from, effective_until, article_ref, "
                "       source_url, foreign_capital_eligibility "
                "  FROM am_subsidy_rule "
                " WHERE program_entity_id = ? "
                " ORDER BY rule_type, effective_from",
                (entity_id,),
            ):
                rules.append(
                    {
                        "rule_type": str(s["rule_type"] or ""),
                        "base_rate_pct": (
                            float(s["base_rate_pct"]) if s["base_rate_pct"] is not None else None
                        ),
                        "cap_yen": int(s["cap_yen"]) if s["cap_yen"] is not None else None,
                        "per_unit_yen": (
                            int(s["per_unit_yen"]) if s["per_unit_yen"] is not None else None
                        ),
                        "unit_type": str(s["unit_type"] or "") or None,
                        "effective_from": str(s["effective_from"] or "") or None,
                        "effective_until": str(s["effective_until"] or "") or None,
                        "article_ref": str(s["article_ref"] or "") or None,
                        "source_url": str(s["source_url"] or "") or None,
                        "foreign_capital_eligibility": str(s["foreign_capital_eligibility"] or "")
                        or None,
                    }
                )
        record = {
            "entity_id": entity_id,
            "primary_name": primary_name,
            "rules": rules,
            "rule_n": len(rules),
        }
        if len(rules) > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    entity_id = str(row.get("entity_id") or "UNKNOWN")
    primary_name = str(row.get("primary_name") or "")
    rules = list(row.get("rules") or [])
    rule_n = int(row.get("rule_n") or len(rules))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(entity_id)}"
    rows_in_packet = rule_n

    chain_steps = [
        {"step": 1, "tool": "search_tax_incentives", "purpose": "tax rule resolution"},
        {"step": 2, "tool": "list_open_programs", "purpose": "program metadata + round"},
        {
            "step": 3,
            "tool": "apply_eligibility_chain_am",
            "purpose": "subsidy_rule × target_profile × amount_condition chain",
        },
        {
            "step": 4,
            "tool": "find_complementary_programs_am",
            "purpose": "compatible program enumeration (am_compat_matrix)",
        },
    ]

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "制度適用判断 / 申請可否 / 締切影響は 所管省庁 + 認定 経営革新等"
                "支援機関 + 顧問税理士 + 行政書士 の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 program で subsidy_rule 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.chusho.meti.go.jp/keiei/kakushin/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 経営革新等支援機関",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.meti.go.jp/policy/economy/keiei_innovation/",
            "source_fetched_at": None,
            "publisher": "経済産業省 経営革新",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "program_entity", "id": entity_id},
        "entity_id": entity_id,
        "primary_name": primary_name,
        "rules": rules,
        "rule_n": rule_n,
        "chain_steps": chain_steps,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": entity_id, "program_entity_id": entity_id},
        metrics={"rule_n": rule_n, "chain_step_n": len(chain_steps)},
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
