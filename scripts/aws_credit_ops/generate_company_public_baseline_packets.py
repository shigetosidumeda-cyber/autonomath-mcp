#!/usr/bin/env python3
"""Generate ``company_public_baseline_v1`` packets (Wave 53.2 #9).

Light-weight houjin baseline. Distinct from ``houjin_360_v1`` — this
packet emits ONLY public-record attributes from ``houjin_master`` (no
adoption / enforcement / invoice scoring). Aimed at high-volume cohort
priming or quick public-record lookup.

Cohort
------

::

    cohort = houjin_bangou

Constraints
-----------

* NO LLM API calls.
* Each packet < 25 KB.
* DRY_RUN default — ``--commit`` flips to live S3 PUT.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

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
    import sqlite3
    from collections.abc import Iterator, Sequence

PACKAGE_KIND: Final[str] = "company_public_baseline_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 company public baseline packet は国税庁 法人番号公表サイト由来 "
    "(houjin_master / pdl_v1.0) の公開項目のみ。与信・取引判断には houjin_360 "
    "packet または 弁護士・税理士の確認が必要です。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    sql = (
        "SELECT houjin_bangou, normalized_name, address_normalized, "
        "       prefecture, municipality, corporation_type, "
        "       established_date, close_date, last_updated_nta, "
        "       jsic_major "
        "  FROM houjin_master "
        " WHERE houjin_bangou IS NOT NULL "
        "   AND length(houjin_bangou) = 13 "
        " ORDER BY houjin_bangou"
    )
    emitted = 0
    for row in primary_conn.execute(sql):
        bangou = normalise_token(row["houjin_bangou"])
        if bangou == "UNKNOWN" or len(bangou) != 13:
            continue
        yield {
            "houjin_bangou": bangou,
            "normalized_name": row["normalized_name"],
            "address_normalized": row["address_normalized"],
            "prefecture": row["prefecture"],
            "municipality": row["municipality"],
            "corporation_type": row["corporation_type"],
            "established_date": row["established_date"],
            "close_date": row["close_date"],
            "last_updated_nta": row["last_updated_nta"],
            "jsic_major": row["jsic_major"],
        }
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = normalise_token(row.get("houjin_bangou"))
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "公開ベースライン (NTA 法人番号公表サイト) のみ。与信・取引"
                "判断は houjin_360 packet または 専門家確認が必要。"
            ),
        }
    ]
    if row.get("close_date") is not None:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": (
                    "close_date があります — 法人が解散・清算済の可能性。"
                    "現在状況は NTA 法人番号公表サイトで再確認。"
                ),
            }
        )
    if row.get("last_updated_nta") is None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "last_updated_nta 不明 — 一次確認が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHouzinNo={bangou}",
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        }
    ]
    metrics = {
        "has_close_date": row.get("close_date") is not None,
    }
    body = {
        "baseline": {
            "houjin_bangou": bangou,
            "normalized_name": row.get("normalized_name"),
            "address_normalized": row.get("address_normalized"),
            "prefecture": row.get("prefecture"),
            "municipality": row.get("municipality"),
            "corporation_type": row.get("corporation_type"),
            "established_date": row.get("established_date"),
            "close_date": row.get("close_date"),
            "last_updated_nta": row.get("last_updated_nta"),
            "jsic_major": row.get("jsic_major"),
        },
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": bangou,
            "houjin_bangou": bangou,
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
        needs_jpintel=False,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
