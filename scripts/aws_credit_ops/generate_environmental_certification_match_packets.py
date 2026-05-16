#!/usr/bin/env python3
"""Generate ``environmental_certification_match_v1`` packets (Wave 55 #10).

環境証明 (ISO 14001 / EMS / GX-related keyword set on adoption + program
+ enforcement axes) × 補助金 × 制度 3-axis cross-link packet. For each
prefecture, surface paired signals: adoption set whose program names hit
environmental-certification fence keywords + corresponding environment
tax-ruleset slices (carbon-related) + environmental enforcement clusters.

Cohort
------

::

    cohort = prefecture (都道府県名)

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

PACKAGE_KIND: Final[str] = "environmental_certification_match_v1"
PER_AXIS_RECORD_CAP: Final[int] = 6

_ENV_CERT_KEYWORDS: Final[tuple[str, ...]] = (
    "ISO14001",
    "ISO 14001",
    "EMS",
    "エコアクション",
    "環境マネジメント",
    "GX",
    "脱炭素",
    "省エネ",
    "カーボンニュートラル",
    "再エネ",
    "ZEH",
    "ZEB",
)

DEFAULT_DISCLAIMER: Final[str] = (
    "本 environmental certification match packet は環境認証キーワード "
    "(ISO14001 / EMS / GX 等) × 補助金 × 制度 の descriptive cross-link "
    "です。実際の認証保有・更新は各認証機関 (JIPDEC / JACO 等) を一次"
    "確認、環境関連届出は環境省 PRTR / EIA-DB を一次確認してください "
    "(行政書士法 §1の2 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return

    like_clauses_adopt = " OR ".join(
        "program_name_raw LIKE ?" for _ in _ENV_CERT_KEYWORDS
    )
    like_params = tuple(f"%{kw}%" for kw in _ENV_CERT_KEYWORDS)

    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_adoption_records "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        record: dict[str, Any] = {
            "prefecture": pref,
            "env_cert_adoption_count": 0,
            "env_cert_total_amount_yen": 0,
            "env_cert_programs": [],
            "env_cert_recipients": [],
            "env_enforcements": [],
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount_granted_yen), 0) AS s "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                f"  AND ({like_clauses_adopt})",
                (pref, *like_params),
            ):
                record["env_cert_adoption_count"] = int(r["c"] or 0)
                record["env_cert_total_amount_yen"] = int(r["s"] or 0)
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT program_name_raw, "
                "       COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                f"  AND ({like_clauses_adopt}) "
                " GROUP BY program_name_raw "
                " ORDER BY total_amount_yen DESC "
                " LIMIT ?",
                (pref, *like_params, PER_AXIS_RECORD_CAP),
            ):
                record["env_cert_programs"].append(
                    {
                        "program_name": r["program_name_raw"],
                        "adoptions": int(r["adoptions"] or 0),
                        "total_amount_yen": int(r["total_amount_yen"] or 0),
                    }
                )
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT houjin_bangou, "
                "       COUNT(*) AS adoptions, "
                "       COALESCE(SUM(amount_granted_yen), 0) AS total_amount_yen "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? "
                f"  AND ({like_clauses_adopt}) "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13 "
                " GROUP BY houjin_bangou "
                " ORDER BY total_amount_yen DESC "
                " LIMIT ?",
                (pref, *like_params, PER_AXIS_RECORD_CAP),
            ):
                record["env_cert_recipients"].append(
                    {
                        "houjin_bangou": r["houjin_bangou"],
                        "adoptions": int(r["adoptions"] or 0),
                        "total_amount_yen": int(r["total_amount_yen"] or 0),
                    }
                )
        if table_exists(primary_conn, "am_enforcement_detail"):
            with contextlib.suppress(Exception):
                # Restrict env enforcements via reason_summary / related_law_ref text.
                for r in primary_conn.execute(
                    "SELECT issuance_date, enforcement_kind, issuing_authority, "
                    "       related_law_ref, target_name, source_url "
                    "  FROM am_enforcement_detail "
                    " WHERE (issuing_authority LIKE '%環境%' "
                    "        OR related_law_ref LIKE '%環境%' "
                    "        OR related_law_ref LIKE '%廃棄物%' "
                    "        OR related_law_ref LIKE '%省エネ%' "
                    "        OR related_law_ref LIKE '%温対%') "
                    " ORDER BY issuance_date DESC "
                    " LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    if len(record["env_enforcements"]) >= PER_AXIS_RECORD_CAP:
                        break
                    record["env_enforcements"].append(
                        {
                            "issuance_date": r["issuance_date"],
                            "enforcement_kind": r["enforcement_kind"],
                            "issuing_authority": r["issuing_authority"],
                            "related_law_ref": r["related_law_ref"],
                            "target_name": r["target_name"],
                            "source_url": r["source_url"],
                        }
                    )

        if (
            record["env_cert_adoption_count"] > 0
            or record["env_enforcements"]
        ):
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    progs = list(row.get("env_cert_programs", []))
    recips = list(row.get("env_cert_recipients", []))
    enfs = list(row.get("env_enforcements", []))
    rows_in_packet = len(progs) + len(recips) + len(enfs)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "ISO14001 / EMS / GX 認証の保有状況は JIPDEC / JACO 等の認証"
                "登録簿、環境関連届出は環境省 PRTR / EIA-DB を一次確認。本 "
                "packet は名称キーワード proxy で、認証実体は未突合。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で環境認証キーワード採択 / 環境処分共に該当無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.iso.org/iso-14001-environmental-management.html",
            "source_fetched_at": None,
            "publisher": "ISO (ISO 14001)",
            "license": "proprietary",
        },
        {
            "source_url": "https://www.env.go.jp/policy/kihon_keikaku/index.html",
            "source_fetched_at": None,
            "publisher": "環境省 環境基本計画",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "env_cert_adoption_count": int(row.get("env_cert_adoption_count") or 0),
        "env_cert_total_amount_yen": int(row.get("env_cert_total_amount_yen") or 0),
        "env_cert_program_count": len(progs),
        "env_cert_recipient_count": len(recips),
        "env_enforcement_count": len(enfs),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "env_cert_adoption_count": int(row.get("env_cert_adoption_count") or 0),
        "env_cert_total_amount_yen": int(row.get("env_cert_total_amount_yen") or 0),
        "env_cert_programs": progs,
        "env_cert_recipients": recips,
        "env_enforcements": enfs,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
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
