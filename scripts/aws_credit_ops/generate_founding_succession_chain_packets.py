#!/usr/bin/env python3
"""Generate ``founding_succession_chain_v1`` packets (Wave 58 #4 of 10).

設立 → 後継 chain (採択履歴ベース proxy)。jpi_adoption_records で houjin_bangou
ごとに採択 round の累積 chain を時系列で並べ、各 chain の最初 + 最新 + 平均
amount を packet 化 (事業承継後の後継法人を採択で proxy する)。

Cohort
------
::

    cohort = houjin_bangou (4+ adoptions のもの)
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

PACKAGE_KIND: Final[str] = "founding_succession_chain_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10
MIN_ADOPTIONS_FOR_CHAIN: Final[int] = 4

DEFAULT_DISCLAIMER: Final[str] = (
    "本 founding succession chain packet は jpi_adoption_records による descriptive"
    "事業継続性 proxy です。実際の事業承継判断は中小機構 + 法人登記 + 商業登記の"
    "一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    eligible: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT houjin_bangou, COUNT(*) AS c "
            "  FROM jpi_adoption_records "
            " WHERE houjin_bangou IS NOT NULL "
            " GROUP BY houjin_bangou HAVING c >= ? "
            " ORDER BY c DESC",
            (MIN_ADOPTIONS_FOR_CHAIN,),
        ):
            hb = str(r["houjin_bangou"] or "")
            if hb:
                eligible.append(hb)

    for emitted, hb in enumerate(eligible):
        chain: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT announced_at, program_name_raw, program_id, "
                "       amount_granted_yen, prefecture "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                " ORDER BY announced_at LIMIT ?",
                (hb, PER_AXIS_RECORD_CAP),
            ):
                chain.append(dict(r))
        if not chain:
            continue
        total_count = 0
        total_amount = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount_granted_yen), 0) AS s "
                "  FROM jpi_adoption_records WHERE houjin_bangou = ?",
                (hb,),
            ).fetchone()
            if row:
                total_count = int(row["c"] or 0)
                total_amount = int(row["s"] or 0)
        record = {
            "houjin_bangou": hb,
            "chain": chain,
            "total_adoptions": total_count,
            "total_amount_yen": total_amount,
            "first_event_date": chain[0].get("announced_at"),
            "latest_event_date": chain[-1].get("announced_at"),
        }
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    hb = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(hb)}"
    chain = list(row.get("chain", []))
    rows_in_packet = len(chain)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "事業承継判断は法人登記 + 商業登記 + 中小機構支援センターの一次確認が必要"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該法人で chain 観測無し (採択 ≥ 4 件の条件未満)",
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
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経産省)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "houjin_bangou", "id": hb},
        "houjin_bangou": hb,
        "chain": chain,
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_amount_yen": int(row.get("total_amount_yen") or 0),
        "first_event_date": row.get("first_event_date"),
        "latest_event_date": row.get("latest_event_date"),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": hb, "houjin_bangou": hb},
        metrics={
            "chain_length": rows_in_packet,
            "total_adoptions": int(row.get("total_adoptions") or 0),
            "total_amount_yen": int(row.get("total_amount_yen") or 0),
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
