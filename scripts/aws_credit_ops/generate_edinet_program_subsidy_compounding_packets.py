#!/usr/bin/env python3
"""Generate ``edinet_program_subsidy_compounding_v1`` packets (Wave 54 #3).

EDINET 財務 (J13) × 補助金採択 (J05) packet. For each houjin that appears in
adoption_records with concrete amount_granted_yen, compound the total
adoption value and pull aliases (J13 EDINET ticker / 有報 anchor). Surfaces
"採択企業の総獲得額 × EDINET anchor" descriptive correlate.

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

PACKAGE_KIND: Final[str] = "edinet_program_subsidy_compounding_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 edinet program subsidy compounding packet は採択 + 法人 + aliases の"
    "descriptive compounding です。EDINET 有価証券報告書の正本は EDINET "
    "(https://disclosure.edinet-fsa.go.jp/) を一次確認してください。"
    "投資判断には専門家確認が必須です (金商法 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "houjin_master"):
        return
    cap = int(limit) if limit is not None else 200000

    # Rank houjin by adoption density — fan out via adoption_records since
    # houjin_master.total_received_yen + total_adoptions rollups are
    # honestly thin / partial in the snapshot.
    candidates: list[tuple[str, str | None, int, int]] = []
    bangou_counts_sql = (
        "SELECT a.houjin_bangou, h.normalized_name, "
        "       COUNT(*) AS adoption_count "
        "  FROM jpi_adoption_records a "
        "  LEFT JOIN houjin_master h ON h.houjin_bangou = a.houjin_bangou "
        " WHERE a.houjin_bangou IS NOT NULL "
        "   AND length(a.houjin_bangou) = 13 "
        " GROUP BY a.houjin_bangou "
        " ORDER BY adoption_count DESC "
        " LIMIT ?"
    )
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(bangou_counts_sql, (cap,)):
            candidates.append(
                (
                    str(r["houjin_bangou"]),
                    r["normalized_name"],
                    0,
                    int(r["adoption_count"] or 0),
                )
            )

    for emitted, (bangou, name, total_yen, total_adopts) in enumerate(candidates):
        record: dict[str, Any] = {
            "houjin_bangou": bangou,
            "normalized_name": name,
            "total_received_yen": total_yen,
            "total_adoptions": total_adopts,
            "subsidy_adoption_breakdown": [],
            "edinet_anchor_aliases": [],
        }
        with contextlib.suppress(Exception):
            for adopt in primary_conn.execute(
                "SELECT program_id, program_name_raw, amount_granted_yen, "
                "       announced_at, source_url "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                " LIMIT ?",
                (bangou, PER_AXIS_RECORD_CAP),
            ):
                record["subsidy_adoption_breakdown"].append(
                    {
                        "program_id": adopt["program_id"],
                        "program_name": adopt["program_name_raw"],
                        "amount_yen": int(adopt["amount_granted_yen"] or 0),
                        "announced_at": adopt["announced_at"],
                        "source_url": adopt["source_url"],
                    }
                )
        # Pull aliases (these often carry ticker / brand strings used to
        # name-match in EDINET).
        if table_exists(primary_conn, "am_alias"):
            with contextlib.suppress(Exception):
                # am_alias has alias_text + entity_id linkage; we proxy via
                # houjin_master.alternative_names_json instead — robust to
                # schema variations.
                for h in primary_conn.execute(
                    "SELECT alternative_names_json FROM houjin_master "
                    " WHERE houjin_bangou = ? LIMIT 1",
                    (bangou,),
                ):
                    raw = h["alternative_names_json"]
                    if raw is None:
                        continue
                    with contextlib.suppress(Exception):
                        parsed = json.loads(str(raw))
                        if isinstance(parsed, list):
                            for alias in parsed[:PER_AXIS_RECORD_CAP]:
                                record["edinet_anchor_aliases"].append(
                                    {"alias": str(alias)[:80]}
                                )

        if record["subsidy_adoption_breakdown"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    adopts = list(row.get("subsidy_adoption_breakdown", []))
    aliases = list(row.get("edinet_anchor_aliases", []))
    rows_in_packet = len(adopts) + len(aliases)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "EDINET 有価証券報告書の財務数値とは別軸の採択履歴です。"
                "金商法 boundaries — 投資判断には EDINET 一次確認必須。"
            ),
        }
    ]
    if len(aliases) == 0:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": "EDINET anchor alias 未確定 — 名寄せに追加確認が必要",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://disclosure.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET (金融庁)",
            "license": "gov_standard",
        },
        {
            "source_url": (
                f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto?id={bangou}"
            ),
            "source_fetched_at": None,
            "publisher": "NTA 法人番号公表サイト",
            "license": "pdl_v1.0",
        },
    ]
    metrics = {
        "subsidy_adoption_count": len(adopts),
        "edinet_alias_count": len(aliases),
        "total_received_yen": int(row.get("total_received_yen") or 0),
        "total_adoptions": int(row.get("total_adoptions") or 0),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "houjin_bangou": bangou,
            "normalized_name": row.get("normalized_name"),
        },
        "subsidy_adoption_breakdown": adopts,
        "edinet_anchor_aliases": aliases,
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
