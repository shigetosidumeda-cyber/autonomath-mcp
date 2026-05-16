#!/usr/bin/env python3
"""Generate ``environmental_disposal_radar_v1`` packets (Wave 54 #8).

廃棄物処理 (J15) × 行政処分 (am_enforcement_municipality + am_enforcement_detail)
packet. For each issuing_authority that ever issued a 廃棄物-related action,
collect the most recent disposal-permit-revoke / improvement-order entries
so an agent gets a watch feed per authority.

Cohort
------

::

    cohort = issuing_authority

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

PACKAGE_KIND: Final[str] = "environmental_disposal_radar_v1"
PER_AXIS_RECORD_CAP: Final[int] = 10

_DISPOSAL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "廃棄物",
        "産業廃棄物",
        "一般廃棄物",
        "リサイクル",
        "処分",
        "排出",
        "汚泥",
        "焼却",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 environmental disposal radar packet は廃棄物関連行政処分の"
    "issuing_authority 別 feed です。各処分の正本は所管自治体公示 + "
    "環境省発表を一次確認してください (行政書士法 §1 boundaries)。"
)


def _hits(text: str | None) -> bool:
    if text is None:
        return False
    s = str(text)
    return any(kw in s for kw in _DISPOSAL_KEYWORDS)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_enforcement_detail"):
        return
    cap = int(limit) if limit is not None else 5000

    authorities: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT issuing_authority, COUNT(*) AS c "
            "  FROM am_enforcement_detail "
            " WHERE issuing_authority IS NOT NULL "
            "   AND ("
            "     related_law_ref LIKE '%廃棄物%' "
            "  OR related_law_ref LIKE '%リサイクル%' "
            "  OR related_law_ref LIKE '%処分%' "
            "   ) "
            " GROUP BY issuing_authority "
            " ORDER BY c DESC "
            " LIMIT ?",
            (cap,),
        ):
            authorities.append(str(r["issuing_authority"]))

    for emitted, auth in enumerate(authorities):
        record: dict[str, Any] = {
            "issuing_authority": auth,
            "disposal_enforcements": [],
            "municipality_actions": [],
        }
        with contextlib.suppress(Exception):
            for enf in primary_conn.execute(
                "SELECT issuance_date, enforcement_kind, target_name, "
                "       related_law_ref, reason_summary, amount_yen, source_url "
                "  FROM am_enforcement_detail "
                " WHERE issuing_authority = ? "
                " ORDER BY issuance_date DESC "
                " LIMIT 100",
                (auth,),
            ):
                if not (
                    _hits(enf["related_law_ref"])
                    or _hits(enf["reason_summary"])
                ):
                    continue
                if len(record["disposal_enforcements"]) >= PER_AXIS_RECORD_CAP:
                    break
                record["disposal_enforcements"].append(
                    {
                        "issuance_date": enf["issuance_date"],
                        "enforcement_kind": enf["enforcement_kind"],
                        "target_name": enf["target_name"],
                        "related_law_ref": enf["related_law_ref"],
                        "reason_summary": (
                            str(enf["reason_summary"])[:200]
                            if enf["reason_summary"] is not None
                            else None
                        ),
                        "amount_yen": int(enf["amount_yen"] or 0),
                        "source_url": enf["source_url"],
                    }
                )
        # Cross-link with am_enforcement_municipality where agency_name matches.
        if table_exists(primary_conn, "am_enforcement_municipality"):
            with contextlib.suppress(Exception):
                for mu in primary_conn.execute(
                    "SELECT action_date, action_type, agency_name, "
                    "       prefecture_name, body_text_excerpt, source_url "
                    "  FROM am_enforcement_municipality "
                    " WHERE agency_name LIKE ? "
                    " ORDER BY action_date DESC "
                    " LIMIT ?",
                    (f"%{auth}%", PER_AXIS_RECORD_CAP),
                ):
                    record["municipality_actions"].append(
                        {
                            "action_date": mu["action_date"],
                            "action_type": mu["action_type"],
                            "agency_name": mu["agency_name"],
                            "prefecture_name": mu["prefecture_name"],
                            "body_excerpt": (
                                str(mu["body_text_excerpt"])[:200]
                                if mu["body_text_excerpt"] is not None
                                else None
                            ),
                            "source_url": mu["source_url"],
                        }
                    )

        if record["disposal_enforcements"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    auth = str(row.get("issuing_authority") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(auth)}"
    enfs = list(row.get("disposal_enforcements", []))
    mus = list(row.get("municipality_actions", []))
    rows_in_packet = len(enfs) + len(mus)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "廃棄物処理業の許可・処分の正本は所管自治体公示 + 環境省。"
                "本 packet は am_enforcement_detail 抽出の watch proxy です。"
            ),
        }
    ]
    if len(mus) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": (
                    "am_enforcement_municipality と直接 join 一致なし — "
                    "別自治体表記 / 名寄せ不一致の可能性"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.env.go.jp/recycle/",
            "source_fetched_at": None,
            "publisher": "環境省 リサイクル対策部",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.env.go.jp/hourei/",
            "source_fetched_at": None,
            "publisher": "環境省 法令データベース",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "disposal_enforcement_count": len(enfs),
        "municipality_action_count": len(mus),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "issuing_authority", "id": auth},
        "issuing_authority": auth,
        "disposal_enforcements": enfs,
        "municipality_actions": mus,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": auth, "issuing_authority": auth},
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
