#!/usr/bin/env python3
"""Generate ``gbiz_invoice_dispatch_match_v1`` packets (Wave 54 #10).

gBizINFO (J07) × インボイス (J03) × 取引パターン (B2B) packet. For each
invoice-registrant 法人 with a 13-digit houjin_bangou + matched
houjin_master row, surface invoice attributes + adoption history as a
B2B "取引先 due diligence" feed.

Cohort
------

::

    cohort = invoice_registration_number (T + 13 digits)

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

PACKAGE_KIND: Final[str] = "gbiz_invoice_dispatch_match_v1"
PER_AXIS_RECORD_CAP: Final[int] = 6

DEFAULT_DISCLAIMER: Final[str] = (
    "本 gbiz invoice dispatch match packet は NTA インボイス公表 + 法人 "
    "master + 採択履歴の descriptive 突合せです。取引可否判断は商号確定 + "
    "事業継続性確認が前提です (税理士法 §52 / §72 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_invoice_registrants"):
        return
    cap = int(limit) if limit is not None else 100000

    registrants: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT invoice_registration_number, houjin_bangou, "
            "       normalized_name, prefecture, registered_date, "
            "       revoked_date, expired_date, registrant_kind, "
            "       trade_name, source_url "
            "  FROM jpi_invoice_registrants "
            " WHERE houjin_bangou IS NOT NULL "
            "   AND length(houjin_bangou) = 13 "
            " LIMIT ?",
            (cap,),
        ):
            registrants.append(
                {
                    "invoice_id": r["invoice_registration_number"],
                    "houjin_bangou": r["houjin_bangou"],
                    "normalized_name": r["normalized_name"],
                    "prefecture": r["prefecture"],
                    "registered_date": r["registered_date"],
                    "revoked_date": r["revoked_date"],
                    "expired_date": r["expired_date"],
                    "registrant_kind": r["registrant_kind"],
                    "trade_name": r["trade_name"],
                    "source_url": r["source_url"],
                }
            )

    for emitted, base in enumerate(registrants):
        record: dict[str, Any] = dict(base)
        record["houjin_master_match"] = None
        record["adoption_history"] = []
        record["enforcement_history"] = []
        bangou = str(base["houjin_bangou"])
        if table_exists(primary_conn, "houjin_master"):
            with contextlib.suppress(Exception):
                for h in primary_conn.execute(
                    "SELECT normalized_name, address_normalized, "
                    "       corporation_type, established_date, "
                    "       total_adoptions, total_received_yen, jsic_major "
                    "  FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
                    (bangou,),
                ):
                    record["houjin_master_match"] = {
                        "normalized_name": h["normalized_name"],
                        "address_normalized": h["address_normalized"],
                        "corporation_type": h["corporation_type"],
                        "established_date": h["established_date"],
                        "total_adoptions": int(h["total_adoptions"] or 0),
                        "total_received_yen": int(h["total_received_yen"] or 0),
                        "jsic_major": h["jsic_major"],
                    }
        if table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for adopt in primary_conn.execute(
                    "SELECT program_name_raw, amount_granted_yen, announced_at, "
                    "       source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                    " LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    record["adoption_history"].append(
                        {
                            "program_name": adopt["program_name_raw"],
                            "amount_yen": int(adopt["amount_granted_yen"] or 0),
                            "announced_at": adopt["announced_at"],
                            "source_url": adopt["source_url"],
                        }
                    )
        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                for enf in primary_conn.execute(
                    "SELECT issuance_date, enforcement_kind, issuing_authority, "
                    "       reason_summary, source_url "
                    "  FROM am_enforcement_detail "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY issuance_date DESC "
                    " LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    record["enforcement_history"].append(
                        {
                            "issuance_date": enf["issuance_date"],
                            "enforcement_kind": enf["enforcement_kind"],
                            "issuing_authority": enf["issuing_authority"],
                            "reason_summary": (
                                str(enf["reason_summary"])[:200]
                                if enf["reason_summary"] is not None
                                else None
                            ),
                            "source_url": enf["source_url"],
                        }
                    )

        # Always emit — the invoice registrant data is itself the load-
        # bearing payload; cross-link enrichment is optional surface.
        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    invoice_id = str(row.get("invoice_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(invoice_id)}"
    adopts = list(row.get("adoption_history", []))
    enfs = list(row.get("enforcement_history", []))
    rows_in_packet = (
        1  # The invoice registrant row itself is the load-bearing payload.
        + len(adopts)
        + len(enfs)
        + (1 if row.get("houjin_master_match") is not None else 0)
    )

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "取引先 due diligence は税理士確認 + 事業継続性確認が前提。"
                "本 packet は公開情報の descriptive 突合せで、商取引判断は"
                "別途確認が必要です。"
            ),
        }
    ]
    if row.get("revoked_date") is not None or row.get("expired_date") is not None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "インボイス登録が取消/失効 — 最新状態は NTA 公表サイトで再確認",
            }
        )
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "採択 / 行政処分 / 法人 master いずれも一致なし",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.invoice-kohyo.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "NTA インボイス公表サイト",
            "license": "pdl_v1.0",
        },
        {
            "source_url": (
                "https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id="
                f"{row.get('houjin_bangou') or ''}"
            ),
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
        {
            "source_url": "https://info.gbiz.go.jp/",
            "source_fetched_at": None,
            "publisher": "gBizINFO (経済産業省)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "adoption_history_count": len(adopts),
        "enforcement_history_count": len(enfs),
        "houjin_master_matched": 1 if row.get("houjin_master_match") is not None else 0,
    }
    body: dict[str, Any] = {
        "subject": {"kind": "invoice_registrant", "id": invoice_id},
        "invoice_registrant": {
            "invoice_id": invoice_id,
            "houjin_bangou": row.get("houjin_bangou"),
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "registered_date": row.get("registered_date"),
            "revoked_date": row.get("revoked_date"),
            "expired_date": row.get("expired_date"),
            "registrant_kind": row.get("registrant_kind"),
            "trade_name": row.get("trade_name"),
        },
        "houjin_master_match": row.get("houjin_master_match"),
        "adoption_history": adopts,
        "enforcement_history": enfs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": invoice_id, "invoice_id": invoice_id},
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
