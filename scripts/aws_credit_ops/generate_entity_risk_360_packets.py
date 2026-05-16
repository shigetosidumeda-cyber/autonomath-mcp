#!/usr/bin/env python3
"""Generate ``entity_risk_360_v1`` packets (Wave 69 #10 of 10).

法人 × all risk axes. Aggregate counts / proxies along three risk axes —
counterparty concentration (HHI proxy across bid procurers), grant
intensity (total_received_yen vs adoption count), and violation count
(enforcement events). Pure descriptive — NO risk score.

Cohort
------

::

    cohort = houjin_bangou (13-digit, canonical subject.kind = "houjin")
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

PACKAGE_KIND: Final[str] = "entity_risk_360_v1"
TOP_PARTNER_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 entity risk 360 packet は HHI proxy / grant intensity / violation "
    "count の descriptive rollup です。risk score / 与信判断 / leverage "
    "推定ではない — DD は弁護士・会計士・税理士確認が必要 (§52 / §72)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,  # noqa: ARG001
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    cap = int(limit) if limit is not None else 100000
    # total_received_yen / total_adoptions are 0 in current snapshot — seed
    # from observed adoption density which surfaces risk-worthy houjin.
    sql = (
        "SELECT h.houjin_bangou, h.normalized_name, h.prefecture, "
        "       h.jsic_major, h.total_adoptions, h.total_received_yen, "
        "       COUNT(a.id) AS adopt_count "
        "  FROM jpi_adoption_records AS a "
        "  JOIN houjin_master AS h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY h.houjin_bangou "
        " ORDER BY adopt_count DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        bangou = str(base["houjin_bangou"])
        partner_amounts: dict[str, int] = {}
        violation_count = 0
        if table_exists(primary_conn, "jpi_bids"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT procuring_entity, awarded_amount_yen "
                    "  FROM jpi_bids "
                    " WHERE winner_houjin_bangou = ? "
                    "   AND awarded_amount_yen > 0",
                    (bangou,),
                ):
                    name = str(r["procuring_entity"] or "")
                    if not name:
                        continue
                    partner_amounts[name] = partner_amounts.get(name, 0) + int(
                        r["awarded_amount_yen"] or 0
                    )
        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                violation_count = int(
                    primary_conn.execute(
                        "SELECT COUNT(*) FROM am_enforcement_detail "
                        " WHERE houjin_bangou = ?",
                        (bangou,),
                    ).fetchone()[0]
                )

        total_award = sum(partner_amounts.values())
        hhi = 0.0
        if total_award > 0:
            shares = [v / total_award for v in partner_amounts.values()]
            hhi = sum(s * s * 10_000.0 for s in shares)
        top_partners = sorted(
            partner_amounts.items(), key=lambda kv: kv[1], reverse=True
        )[:TOP_PARTNER_CAP]
        # adopt_count > 0 is guaranteed by the seed query — emit a risk packet
        # even when bid_total_award_yen / violation_count are 0 (no_hit
        # semantics preserve the descriptive null observation).
        yield {
            "houjin_bangou": bangou,
            "normalized_name": base["normalized_name"],
            "prefecture": base["prefecture"],
            "jsic_major": base["jsic_major"],
            "total_adoptions": int(base["adopt_count"] or 0),
            "total_received_yen": int(base["total_received_yen"] or 0),
            "bid_partner_count": len(partner_amounts),
            "bid_total_award_yen": total_award,
            "bid_hhi_basis_points": round(hhi, 2),
            "top_partners": [
                {"counterpart_name": k, "amount_yen": v} for k, v in top_partners
            ],
            "enforcement_event_count": violation_count,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    top_partners = list(row.get("top_partners", []))
    # rows_in_packet = number of meaningful per-axis observations.
    # Always emit at least 1 (grant intensity axis is canonically present
    # by virtue of the adoption-density seed query).
    rows_in_packet = max(
        (1 if int(row.get("bid_partner_count") or 0) > 0 else 0)
        + (1 if int(row.get("enforcement_event_count") or 0) > 0 else 0)
        + (1 if int(row.get("total_adoptions") or 0) > 0 else 0),
        1,
    )

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "本 packet は HHI proxy / event count の descriptive "
                "rollup。risk score / 与信判断ではない — DD は弁護士・"
                "会計士確認 (§52 / §72)。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "risk axis 観測無し = リスクゼロを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
        {
            "source_url": "https://www.geps.go.jp/",
            "source_fetched_at": None,
            "publisher": "政府電子調達 (GEPS)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "bid_partner_count": int(row.get("bid_partner_count") or 0),
        "bid_total_award_yen": int(row.get("bid_total_award_yen") or 0),
        "bid_hhi_basis_points": float(row.get("bid_hhi_basis_points") or 0.0),
        "enforcement_event_count": int(row.get("enforcement_event_count") or 0),
        "total_adoptions": int(row.get("total_adoptions") or 0),
        "total_received_yen": int(row.get("total_received_yen") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "risk_axes": {
            "counterparty_concentration": {
                "partner_count": int(row.get("bid_partner_count") or 0),
                "total_award_yen": int(row.get("bid_total_award_yen") or 0),
                "hhi_basis_points": float(
                    row.get("bid_hhi_basis_points") or 0.0
                ),
                "top_partners": top_partners,
            },
            "grant_intensity": {
                "total_adoptions": int(row.get("total_adoptions") or 0),
                "total_received_yen": int(row.get("total_received_yen") or 0),
            },
            "violation": {
                "enforcement_event_count": int(
                    row.get("enforcement_event_count") or 0
                ),
            },
        },
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
