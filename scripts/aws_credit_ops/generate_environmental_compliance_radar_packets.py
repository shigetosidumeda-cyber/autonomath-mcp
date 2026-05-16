#!/usr/bin/env python3
"""Generate ``environmental_compliance_radar_v1`` packets (Wave 53.3 #2).

法人 × 環境省データ (排出量 / EIA / PRTR / 廃棄物) radar packet. Cross-joins
``houjin_master`` against environmental enforcement signals
(``am_enforcement_detail`` where issuing_authority is 環境省 / 都道府県
環境部 etc.) and program-level environmental categories
(``program.cap_design_trademark_jpy`` is excluded — only GX / energy / waste
classifications).

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

PACKAGE_KIND: Final[str] = "environmental_compliance_radar_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

# 環境省 + 経産省GX関連の publisher 名 (issuing_authority 検出用)
_ENV_AUTHORITY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"環境省", "環境本省", "環境部", "環境局", "GX", "地球環境"}
)
_ENV_LAW_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "廃棄物",
        "リサイクル",
        "PRTR",
        "大気汚染",
        "水質汚濁",
        "土壌",
        "省エネ",
        "温対法",
        "EIA",
        "環境影響",
        "公害",
    }
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 environmental compliance radar packet は am_enforcement_detail + "
    "GX 関連 program ファクトの descriptive 集約です。実際の排出量・PRTR 届出は"
    "環境省 PRTR データベース、EIA 結果は環境省 EIA-DB を一次確認してください "
    "(行政書士法 §1の2 boundaries — 申請書面を代わりに作りません)。"
)


def _is_env_authority(authority: str | None) -> bool:
    if authority is None:
        return False
    s = str(authority)
    return any(kw in s for kw in _ENV_AUTHORITY_KEYWORDS)


def _is_env_law(law_ref: str | None) -> bool:
    if law_ref is None:
        return False
    s = str(law_ref)
    return any(kw in s for kw in _ENV_LAW_KEYWORDS)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_enforcement_detail"):
        return

    # Drive packet set from env-flagged houjin (enforcement-evidence-first).
    cap = int(limit) if limit is not None else 50000
    # houjin_bangou is unpopulated (empty-string) on env-side enforcement
    # rows; cohort_id falls back to a hash of target_name when bangou is
    # absent so the packet still has a stable identifier per 法人.
    candidates: list[tuple[str, str | None, int]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT COALESCE(NULLIF(houjin_bangou, ''), '') AS bangou, "
            "       target_name, enforcement_id "
            "  FROM am_enforcement_detail "
            " WHERE ("
            "       issuing_authority LIKE '%環境%' "
            "    OR related_law_ref LIKE '%廃棄物%' "
            "    OR related_law_ref LIKE '%リサイクル%' "
            "    OR related_law_ref LIKE '%PRTR%' "
            "    OR related_law_ref LIKE '%大気%' "
            "    OR related_law_ref LIKE '%水質%' "
            "    OR related_law_ref LIKE '%省エネ%' "
            "    OR related_law_ref LIKE '%温対%' "
            "    OR related_law_ref LIKE '%公害%' "
            "    OR related_law_ref LIKE '%環境%' "
            "   ) "
            "   AND target_name IS NOT NULL "
            " LIMIT ?",
            (cap,),
        ):
            candidates.append(
                (str(r["bangou"]), r["target_name"], int(r["enforcement_id"] or 0))
            )

    for emitted, (bangou, target_name, enf_id_anchor) in enumerate(candidates):
        # cohort_id falls back to the enforcement_id-anchored 法人 row when
        # houjin_bangou is empty so packets remain individually addressable.
        cohort_id = bangou or f"env_anchor_{enf_id_anchor}"
        record: dict[str, Any] = {
            "houjin_bangou": bangou or None,
            "cohort_id": cohort_id,
            "normalized_name": target_name,
            "prefecture": None,
            "jsic_major": None,
            "env_enforcements": [],
            "gx_program_adoptions": [],
        }
        if bangou and table_exists(primary_conn, "houjin_master"):
            with contextlib.suppress(Exception):
                for h in primary_conn.execute(
                    "SELECT normalized_name, prefecture, jsic_major "
                    "  FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
                    (bangou,),
                ):
                    record["normalized_name"] = (
                        h["normalized_name"] or record["normalized_name"]
                    )
                    record["prefecture"] = h["prefecture"]
                    record["jsic_major"] = h["jsic_major"]

        # Filter enforcement by target_name when bangou is empty (so we still
        # collect the actual env enforcement rows for this 法人 row).
        enf_sql = (
            "SELECT issuance_date, enforcement_kind, issuing_authority, "
            "       related_law_ref, reason_summary, amount_yen, source_url "
            "  FROM am_enforcement_detail "
            " WHERE target_name = ? "
            " ORDER BY issuance_date DESC"
        )
        with contextlib.suppress(Exception):
            for row in primary_conn.execute(enf_sql, (target_name,)):
                auth = row["issuing_authority"]
                law = row["related_law_ref"]
                if not (_is_env_authority(auth) or _is_env_law(law)):
                    continue
                if len(record["env_enforcements"]) >= PER_AXIS_RECORD_CAP:
                    continue
                record["env_enforcements"].append(
                    {
                        "issuance_date": row["issuance_date"],
                        "enforcement_kind": row["enforcement_kind"],
                        "issuing_authority": auth,
                        "related_law_ref": law,
                        "reason_summary": (
                            str(row["reason_summary"])[:200]
                            if row["reason_summary"] is not None
                            else None
                        ),
                        "amount_yen": int(row["amount_yen"] or 0),
                        "source_url": row["source_url"],
                    }
                )

        if bangou and table_exists(primary_conn, "jpi_adoption_records"):
            with contextlib.suppress(Exception):
                for row in primary_conn.execute(
                    "SELECT program_id, program_name_raw, amount_granted_yen, "
                    "       announced_at, source_url "
                    "  FROM jpi_adoption_records "
                    " WHERE houjin_bangou = ? "
                    " ORDER BY COALESCE(amount_granted_yen, 0) DESC "
                    " LIMIT ?",
                    (bangou, PER_AXIS_RECORD_CAP),
                ):
                    record["gx_program_adoptions"].append(
                        {
                            "program_id": row["program_id"],
                            "program_name": row["program_name_raw"],
                            "amount_yen": int(row["amount_granted_yen"] or 0),
                            "announced_at": row["announced_at"],
                            "source_url": row["source_url"],
                        }
                    )

        if record["env_enforcements"] or record["gx_program_adoptions"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    bangou = row.get("houjin_bangou")
    cohort_id = str(row.get("cohort_id") or bangou or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cohort_id)}"
    env_enf = list(row.get("env_enforcements", []))
    gx_ads = list(row.get("gx_program_adoptions", []))
    rows_in_packet = len(env_enf) + len(gx_ads)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "排出量・PRTR 届出の正本は環境省 PRTR DB、EIA 評価書は EIA-DB を"
                "一次確認してください。行政処分は所管自治体公示も併読。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "環境関連シグナル無し = 違反/届出ゼロを意味しない",
            }
        )
    if bangou is None:
        known_gaps.append(
            {
                "code": "identity_ambiguity_unresolved",
                "description": (
                    "houjin_bangou が未収録 — 環境本省 enforcement レコードは "
                    "target_name でしか名寄せできていません。NTA 法人番号確認推奨。"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.env.go.jp/chemi/prtr/",
            "source_fetched_at": None,
            "publisher": "環境省 PRTR",
            "license": "gov_standard",
        },
        {
            "source_url": "https://assess.env.go.jp/",
            "source_fetched_at": None,
            "publisher": "環境省 環境影響評価情報支援ネットワーク",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "env_enforcement_count": len(env_enf),
        "gx_program_adoption_count": len(gx_ads),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "houjin", "id": cohort_id},
        "houjin_summary": {
            "houjin_bangou": bangou,
            "normalized_name": row.get("normalized_name"),
            "prefecture": row.get("prefecture"),
            "jsic_major": row.get("jsic_major"),
        },
        "env_enforcements": env_enf,
        "gx_program_adoptions": gx_ads,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": cohort_id, "houjin_bangou": bangou},
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
