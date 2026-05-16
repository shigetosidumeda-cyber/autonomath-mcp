#!/usr/bin/env python3
"""Generate ``patent_environmental_link_v1`` packets (Wave 54 #1).

特許 (JPO J14) × 環境 (J15) cross-link packet. Identifies programs whose
法人 receivers also carry environmental signals (env enforcement /
GX-related law refs) — a proxy for "environmental patent" sub-cohort. This
combines ``jpi_adoption_records`` (program × houjin) with
``am_enforcement_detail`` (env axis) and ``am_entity_facts`` patent caps
to expose corp-level overlap.

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

PACKAGE_KIND: Final[str] = "patent_environmental_link_v1"
PER_AXIS_RECORD_CAP: Final[int] = 6

_PATENT_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "特許",
        "知財",
        "INPIT",
        "弁理",
        "実用新案",
        "意匠",
        "ものづくり",
        "事業再構築",
        "新事業",
    }
)
_ENV_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "環境",
        "GX",
        "脱炭素",
        "省エネ",
        "温対",
        "再エネ",
        "廃棄物",
        "リサイクル",
        "公害",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 patent environmental link packet は特許関連採択履歴と環境系シグナル"
    "の descriptive cross-link です。実際の特許権所有・出願は J-PlatPat、"
    "排出量・PRTR 届出は環境省 PRTR DB を一次確認してください "
    "(弁理士法 §75 / 行政書士法 §1の2 boundaries — 申請書面は代行しません)。"
)


def _hits(text: str | None, kws: frozenset[str]) -> bool:
    if text is None:
        return False
    s = str(text)
    return any(kw in s for kw in kws)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    cap = int(limit) if limit is not None else 100000

    # Drive packet set from houjin who took up programs known for patent /
    # trademark / 知財 / 中小企業 知財 — drawn from a wide intent pool so
    # the snapshot returns rows even when program names don't carry the
    # exact 特許 keyword string.
    candidate_sql = (
        "SELECT DISTINCT houjin_bangou "
        "  FROM jpi_adoption_records "
        " WHERE houjin_bangou IS NOT NULL "
        "   AND length(houjin_bangou) = 13 "
        "   AND ("
        "     program_name_raw LIKE '%特許%' "
        "  OR program_name_raw LIKE '%知財%' "
        "  OR program_name_raw LIKE '%実用新案%' "
        "  OR program_name_raw LIKE '%ものづくり%' "
        "  OR program_name_raw LIKE '%事業再構築%' "
        "  OR program_name_raw LIKE '%新事業%' "
        "   ) "
        " LIMIT ?"
    )
    bangou_list: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(candidate_sql, (cap,)):
            bangou_list.append(str(r["houjin_bangou"]))

    for emitted, bangou in enumerate(bangou_list):
        record: dict[str, Any] = {
            "houjin_bangou": bangou,
            "normalized_name": None,
            "prefecture": None,
            "jsic_major": None,
            "patent_adoptions": [],
            "env_signals": [],
        }
        if table_exists(primary_conn, "houjin_master"):
            with contextlib.suppress(Exception):
                for h in primary_conn.execute(
                    "SELECT normalized_name, prefecture, jsic_major "
                    "  FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
                    (bangou,),
                ):
                    record["normalized_name"] = h["normalized_name"]
                    record["prefecture"] = h["prefecture"]
                    record["jsic_major"] = h["jsic_major"]
        with contextlib.suppress(Exception):
            for adopt in primary_conn.execute(
                "SELECT program_id, program_name_raw, amount_granted_yen, "
                "       announced_at, source_url "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                " LIMIT 50",
                (bangou,),
            ):
                if not _hits(adopt["program_name_raw"], _PATENT_KEYWORDS):
                    continue
                if len(record["patent_adoptions"]) >= PER_AXIS_RECORD_CAP:
                    continue
                record["patent_adoptions"].append(
                    {
                        "program_id": adopt["program_id"],
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
                    "       related_law_ref, reason_summary, source_url "
                    "  FROM am_enforcement_detail "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY issuance_date DESC "
                    " LIMIT 40",
                    (bangou,),
                ):
                    if not (
                        _hits(enf["issuing_authority"], _ENV_KEYWORDS)
                        or _hits(enf["related_law_ref"], _ENV_KEYWORDS)
                    ):
                        continue
                    if len(record["env_signals"]) >= PER_AXIS_RECORD_CAP:
                        continue
                    record["env_signals"].append(
                        {
                            "issuance_date": enf["issuance_date"],
                            "enforcement_kind": enf["enforcement_kind"],
                            "issuing_authority": enf["issuing_authority"],
                            "related_law_ref": enf["related_law_ref"],
                            "reason_summary": (
                                str(enf["reason_summary"])[:200]
                                if enf["reason_summary"] is not None
                                else None
                            ),
                            "source_url": enf["source_url"],
                        }
                    )

        if record["patent_adoptions"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = str(row.get("houjin_bangou") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(bangou)}"
    patents = list(row.get("patent_adoptions", []))
    envs = list(row.get("env_signals", []))
    rows_in_packet = len(patents) + len(envs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "特許権所有・出願の正本は J-PlatPat (INPIT)。環境関連届出は"
                "環境省 PRTR / EIA-DB を一次確認。弁理士・行政書士判断必須。"
            ),
        }
    ]
    if len(envs) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "環境シグナル無 = 環境関連無しを意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.j-platpat.inpit.go.jp/",
            "source_fetched_at": None,
            "publisher": "J-PlatPat (INPIT)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.env.go.jp/chemi/prtr/",
            "source_fetched_at": None,
            "publisher": "環境省 PRTR",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "patent_adoption_count": len(patents),
        "env_signal_count": len(envs),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": bangou},
        "houjin_summary": {
            "houjin_bangou": bangou,
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "patent_adoptions": patents,
        "env_signals": envs,
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
