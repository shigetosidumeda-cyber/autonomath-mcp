#!/usr/bin/env python3
"""Generate ``invoice_registrant_public_check_v1`` packets (Wave 53.2 #10).

T番号 light check packet. Distinct from ``invoice_houjin_check`` — this is
a thin public-record lookup that surfaces ONLY the NTA-published columns of
the registration (no houjin_360 / enforcement cross-join). Per
``invoice_registration_number`` packet.

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

import sqlite3
import sys
from typing import TYPE_CHECKING, Any, Final

from scripts.aws_credit_ops._packet_base import (
    jpcir_envelope,
    normalise_token,
    safe_packet_id_segment,
    table_exists,
)
from scripts.aws_credit_ops._packet_runner import run_generator

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "invoice_registrant_public_check_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 invoice registrant public check packet は国税庁 適格請求書発行事業者"
    "公表サイト (PDL v1.0) 由来の公開項目のみ。仕入税額控除可否は実際の"
    "請求書/帳簿要件 (消法 §30) で確認し、税理士の確認が必要です (税理士法 §52)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    # Prefer jpintel.db.invoice_registrants when populated; fall back to
    # autonomath.db (8.29 GB unified primary).
    conn: sqlite3.Connection | None = None
    if jpintel_conn is not None and table_exists(jpintel_conn, "invoice_registrants"):
        try:
            n = jpintel_conn.execute(
                "SELECT COUNT(*) FROM invoice_registrants"
            ).fetchone()[0]
        except sqlite3.Error:
            n = 0
        if n > 0:
            conn = jpintel_conn
    if conn is None and table_exists(primary_conn, "invoice_registrants"):
        conn = primary_conn
    if conn is None:
        return

    sql = (
        "SELECT invoice_registration_number, houjin_bangou, normalized_name, "
        "       address_normalized, prefecture, registered_date, "
        "       revoked_date, expired_date, registrant_kind, trade_name, "
        "       last_updated_nta, source_url "
        "  FROM invoice_registrants "
        " ORDER BY invoice_registration_number"
    )
    emitted = 0
    for row in conn.execute(sql):
        trn = normalise_token(row["invoice_registration_number"])
        if len(trn) != 14 or not trn.startswith("T"):
            continue
        yield {
            "invoice_registration_number": trn,
            "houjin_bangou": row["houjin_bangou"],
            "normalized_name": row["normalized_name"],
            "address_normalized": row["address_normalized"],
            "prefecture": row["prefecture"],
            "registered_date": row["registered_date"],
            "revoked_date": row["revoked_date"],
            "expired_date": row["expired_date"],
            "registrant_kind": row["registrant_kind"],
            "trade_name": row["trade_name"],
            "last_updated_nta": row["last_updated_nta"],
            "source_url": row["source_url"],
        }
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    trn = normalise_token(row.get("invoice_registration_number"))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(trn)}"

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "登録状態のみ公開。仕入税額控除可否は税理士確認が必須 (税理士法 "
                "§52 / 消費税法 §30)。"
            ),
        }
    ]
    revoked = row.get("revoked_date")
    expired = row.get("expired_date")
    if revoked is not None or expired is not None:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": (
                    "revoked_date / expired_date があります — 取消・失効済の"
                    "可能性。最新は NTA 公表サイトで再確認"
                ),
            }
        )
    if row.get("last_updated_nta") is None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "last_updated_nta 不明 — NTA 公表サイトで一次確認",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": f"https://www.invoice-kohyo.nta.go.jp/regno-search/detail?selRegNo={trn[1:]}",
            "source_fetched_at": None,
            "publisher": "NTA 適格請求書発行事業者公表サイト",
            "license": "pdl_v1.0",
        }
    ]
    metrics = {
        "has_revoked_date": revoked is not None,
        "has_expired_date": expired is not None,
        "registrant_kind": row.get("registrant_kind"),
    }
    body = {
        "registrant": {
            "invoice_registration_number": trn,
            "houjin_bangou": row.get("houjin_bangou"),
            "normalized_name": row.get("normalized_name"),
            "address_normalized": row.get("address_normalized"),
            "prefecture": row.get("prefecture"),
            "registered_date": row.get("registered_date"),
            "revoked_date": revoked,
            "expired_date": expired,
            "registrant_kind": row.get("registrant_kind"),
            "trade_name": row.get("trade_name"),
            "last_updated_nta": row.get("last_updated_nta"),
        },
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": trn,
            "invoice_registration_number": trn,
        },
        metrics=metrics,
        body=body,
        sources=sources,
        known_gaps=known_gaps,
        disclaimer=DEFAULT_DISCLAIMER,
        generated_at=generated_at,
    )
    return package_id, envelope, 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_generator(
        argv=argv,
        package_kind=PACKAGE_KIND,
        default_db="autonomath.db",
        aggregate=_aggregate,
        render=_render,
        needs_jpintel=True,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
