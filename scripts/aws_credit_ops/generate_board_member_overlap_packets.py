#!/usr/bin/env python3
"""Generate ``board_member_overlap_v1`` packets (Wave 58 #3 of 10).

役員兼任 network。jpi_houjin_master の alternative_names_json + 採択 record の
project_title から法人間の関係性を proxy する descriptive network signal。
役員情報そのものは公開 source として gBizINFO 連結だが、本 packet 内に役員 PII
を含めない (anonymized cohort)。

Cohort
------
::

    cohort = prefecture (法人グループの所在地)
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

PACKAGE_KIND: Final[str] = "board_member_overlap_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 board member overlap packet は anonymized cohort 統計のみで、役員 PII を"
    "含めない。実際の役員兼任証拠は gBizINFO + 商業登記簿の一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_houjin_master"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_houjin_master "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        # alternative_names_json is unpopulated → use corporation_type clustering
        # to surface co-located corp groups of same corp_type as overlap proxy
        ct_buckets: dict[str, list[dict[str, Any]]] = {}
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT houjin_bangou, normalized_name, corporation_type "
                "  FROM jpi_houjin_master "
                " WHERE prefecture = ? AND normalized_name IS NOT NULL "
                "   AND length(normalized_name) >= 4 "
                " LIMIT 5000",
                (pref,),
            ):
                d = dict(r)
                name = str(d.get("normalized_name") or "")
                if len(name) < 4:
                    continue
                # cluster by name 3-char prefix within prefecture
                sig = name[:3]
                ct_buckets.setdefault(sig, []).append(
                    {
                        "houjin_bangou": d["houjin_bangou"],
                        "normalized_name": name,
                        "corporation_type": d.get("corporation_type"),
                    }
                )
        # only keep clusters with ≥ 2 entities (overlap signal proxy)
        groups = [
            {"signature": k, "count": len(v), "samples": v[:3]}
            for k, v in ct_buckets.items() if len(v) >= 2
        ][:PER_AXIS_RECORD_CAP]
        record = {
            "prefecture": pref,
            "overlap_groups": groups,
            "group_count": len(groups),
        }
        if groups:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    groups = list(row.get("overlap_groups", []))
    rows_in_packet = len(groups)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "本 packet は anonymized cohort のみ、役員 PII を含めない。"
                "実際の兼任証拠は商業登記簿の一次確認が必要"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で overlap signal 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経産省)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "overlap_groups": groups,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={"group_count": rows_in_packet},
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
