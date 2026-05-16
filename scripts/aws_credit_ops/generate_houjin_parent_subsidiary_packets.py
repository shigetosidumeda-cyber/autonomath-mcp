#!/usr/bin/env python3
"""Generate ``houjin_parent_subsidiary_v1`` packets (Wave 58 #1 of 10).

法人 親子関係 cross-ref。jpi_houjin_master の normalized_name を keyword 共通
prefix で類似法人グルーピングし、各企業群の cross-ref を packet 化する。
公開情報ベースの descriptive grouping のみで、登記情報による親子証明ではない。

Cohort
------
::

    cohort = name_prefix (normalized_name の先頭 4 字)
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

PACKAGE_KIND: Final[str] = "houjin_parent_subsidiary_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 houjin parent subsidiary packet は jpi_houjin_master の normalized_name "
    "prefix grouping による descriptive 類似法人 cross-ref です。実際の親子関係は"
    "法人登記簿 + EDINET 連結対象開示の一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_houjin_master"):
        return

    prefix_groups: dict[str, list[dict[str, Any]]] = {}
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT houjin_bangou, normalized_name, prefecture, corporation_type, "
            "       total_adoptions, total_received_yen "
            "  FROM jpi_houjin_master "
            " WHERE normalized_name IS NOT NULL "
            "   AND length(normalized_name) >= 4 "
            " LIMIT 200000"
        ):
            name = str(r["normalized_name"] or "")
            if len(name) < 4:
                continue
            prefix = name[:4]
            prefix_groups.setdefault(prefix, []).append(dict(r))

    # only emit prefixes with multiple linked entities
    candidates = [
        (k, v) for k, v in prefix_groups.items() if len(v) >= 2
    ]
    candidates.sort(key=lambda kv: len(kv[1]), reverse=True)

    for emitted, (prefix, group) in enumerate(candidates):
        group_top = group[:PER_AXIS_RECORD_CAP]
        record = {
            "name_prefix": prefix,
            "linked_entities": group_top,
            "group_size_total": len(group),
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("name_prefix") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    ents = list(row.get("linked_entities", []))
    rows_in_packet = len(ents)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "name_prefix grouping は登記情報による親子証明ではない、"
                "実際の親子関係は法人登記簿 + EDINET 連結対象開示の一次確認が必要"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 prefix で linked entity 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経産省)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://disclosure.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET (金融庁)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "name_prefix", "id": pref},
        "name_prefix": pref,
        "linked_entities": ents,
        "group_size_total": int(row.get("group_size_total") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "name_prefix": pref},
        metrics={
            "linked_entities_count": rows_in_packet,
            "group_size_total": int(row.get("group_size_total") or 0),
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
