#!/usr/bin/env python3
"""Generate ``segment_pivot_routing_v1`` packets (Wave 99 #2 of 10).

agent funnel の Discoverability/Justifiability 軸を segment 別に切り出し、
accounting_firm / law_firm / SME / consultant / municipal / foreign_fdi の
6 segment 毎に **entry-point composed tool** + 推奨 outcome chain を pre-built
control packet 化する。Wave 51 L3 cross_outcome_routing と pair で使う。

Cohort
------
::

    cohort = segment_id (accounting_firm | law_firm | sme | consultant
                          | municipal | foreign_fdi)
"""

from __future__ import annotations

import contextlib
import json
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

PACKAGE_KIND: Final[str] = "segment_pivot_routing_v1"

#: Static segment universe (matches cohort revenue model §8 cohorts in CLAUDE.md).
_SEGMENT_HINTS: Final[dict[str, dict[str, Any]]] = {
    "accounting_firm": {
        "ja": "税理士・会計士事務所",
        "primary_domain": "audit_seal_pack",
        "preferred_domains": ["due_diligence", "tax", "audit_seal_pack"],
    },
    "law_firm": {
        "ja": "弁護士事務所",
        "primary_domain": "compliance",
        "preferred_domains": ["compliance", "court_decision", "due_diligence"],
    },
    "sme": {
        "ja": "中小企業 (本人申請)",
        "primary_domain": "subsidy_application",
        "preferred_domains": ["subsidy_application", "tax", "construction"],
    },
    "consultant": {
        "ja": "補助金 / 認定経営革新等支援機関 コンサルタント",
        "primary_domain": "subsidy_consulting",
        "preferred_domains": ["subsidy_application", "due_diligence", "construction"],
    },
    "municipal": {
        "ja": "自治体・公的機関",
        "primary_domain": "policy_lookup",
        "preferred_domains": ["compliance", "subsidy_application", "policy_lookup"],
    },
    "foreign_fdi": {
        "ja": "外資系 (FDI) 法人",
        "primary_domain": "international_tax",
        "preferred_domains": ["due_diligence", "international_tax", "compliance"],
    },
}

DEFAULT_DISCLAIMER: Final[str] = (
    "本 segment pivot routing packet は am_composed_tool_catalog から segment "
    "別 entry-point + outcome chain hint を rollup した control-plane packet "
    "で、税理士法 §52 / 弁護士法 §72 / 行政書士法 §1の2 / 社労士法 §27 の "
    "専門家業務を代替しない。実 outcome は対応専門家の一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_composed_tool_catalog"):
        return

    tools_by_domain: dict[str, list[dict[str, Any]]] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT tool_id, version, domain, description, atomic_tool_chain "
            "  FROM am_composed_tool_catalog "
            " WHERE status = 'committed' "
            " ORDER BY tool_id"
        ):
            domain = str(r["domain"] or "")
            try:
                chain_obj = json.loads(r["atomic_tool_chain"] or "{}")
            except (TypeError, ValueError):
                chain_obj = {}
            tools_by_domain.setdefault(domain, []).append(
                {
                    "tool_id": str(r["tool_id"] or ""),
                    "version": int(r["version"] or 1),
                    "description": str(r["description"] or ""),
                    "savings_factor": int(chain_obj.get("savings_factor") or 0),
                    "chain_step_n": len(chain_obj.get("atomic_chain") or []),
                }
            )

    for emitted, (segment_id, hint) in enumerate(_SEGMENT_HINTS.items()):
        entry_points: list[dict[str, Any]] = []
        primary_domain = str(hint.get("primary_domain") or "")
        preferred_domains = list(hint.get("preferred_domains") or [])
        for dom in preferred_domains:
            for tool in tools_by_domain.get(dom, []):
                entry_points.append({"recommended_domain": dom, **tool})
        record = {
            "segment_id": segment_id,
            "segment_label_ja": str(hint.get("ja") or segment_id),
            "primary_domain": primary_domain,
            "preferred_domains": preferred_domains,
            "entry_points": entry_points,
            "entry_point_n": len(entry_points),
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    segment_id = str(row.get("segment_id") or "UNKNOWN")
    label = str(row.get("segment_label_ja") or "")
    primary_domain = str(row.get("primary_domain") or "")
    preferred_domains = list(row.get("preferred_domains") or [])
    entry_points = list(row.get("entry_points") or [])
    entry_point_n = int(row.get("entry_point_n") or len(entry_points))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(segment_id)}"
    rows_in_packet = entry_point_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "segment entry-point は am_composed_tool_catalog の hint で、"
                "実際の outcome 判断は対応専門家の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 segment で entry-point composed tool 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://docs.jpcite.com/agent-runtime/segments/",
            "source_fetched_at": None,
            "publisher": "jpcite agent runtime segment docs",
            "license": "gov_standard",
        },
        {
            "source_url": "https://docs.jpcite.com/wave51/cross-outcome-routing/",
            "source_fetched_at": None,
            "publisher": "jpcite Wave 51 L3 cross_outcome_routing",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "segment", "id": segment_id},
        "segment_id": segment_id,
        "segment_label_ja": label,
        "primary_domain": primary_domain,
        "preferred_domains": preferred_domains,
        "entry_points": entry_points,
        "entry_point_n": entry_point_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": segment_id, "segment_id": segment_id},
        metrics={"entry_point_n": entry_point_n},
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
