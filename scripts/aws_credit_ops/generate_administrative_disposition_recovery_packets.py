#!/usr/bin/env python3
"""Generate ``administrative_disposition_recovery_v1`` packets (Wave 55 #9).

行政処分後 × 採択履歴 × 業種復活率 cross-link packet. For each
issuing_authority in am_enforcement_detail, surface paired signals: total
disposition count, disposition_kind mix, and the post-disposition
subsequent adoption count of disposed houjin (descriptive proxy for
"処分後の業種復活率"). We do not compute a true recovery rate (requires
date-bracketed cohort design); the packet exposes both sides for an
analyst to compute.

Cohort
------

::

    cohort = issuing_authority (処分庁)

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

PACKAGE_KIND: Final[str] = "administrative_disposition_recovery_v1"
PER_AXIS_RECORD_CAP: Final[int] = 8

DEFAULT_DISCLAIMER: Final[str] = (
    "本 administrative disposition recovery packet は行政処分 × 採択履歴 × "
    "業種 の descriptive cross-link です。処分の正本は各処分庁公表、採択は "
    "Jグランツを一次確認。処分前後の事業継続・復活判定は外部 advisor の "
    "判断が前提です (税理士法 §52 / 弁護士法 §72 boundaries)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_enforcement_detail"):
        return

    auths: list[tuple[str, int]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT issuing_authority, COUNT(*) AS c "
            "  FROM am_enforcement_detail "
            " WHERE issuing_authority IS NOT NULL AND issuing_authority != '' "
            " GROUP BY issuing_authority "
            " ORDER BY c DESC"
        ):
            auths.append((str(r["issuing_authority"]), int(r["c"] or 0)))

    for emitted, (auth, count) in enumerate(auths):
        record: dict[str, Any] = {
            "issuing_authority": auth,
            "disposition_count": count,
            "kind_mix": [],
            "disposed_houjin_sample": [],
            "post_disposition_adoption_summary": {
                "disposed_houjin_with_adoption_count": 0,
                "post_disposition_adoption_count": 0,
                "post_disposition_total_amount_yen": 0,
            },
        }
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT enforcement_kind, COUNT(*) AS c "
                "  FROM am_enforcement_detail "
                " WHERE issuing_authority = ? "
                " GROUP BY enforcement_kind "
                " ORDER BY c DESC",
                (auth,),
            ):
                record["kind_mix"].append(
                    {"enforcement_kind": r["enforcement_kind"], "count": int(r["c"] or 0)}
                )
        disposed_bangous: list[tuple[str, str]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT houjin_bangou, MAX(issuance_date) AS last_issuance "
                "  FROM am_enforcement_detail "
                " WHERE issuing_authority = ? "
                "   AND houjin_bangou IS NOT NULL "
                "   AND length(houjin_bangou) = 13 "
                " GROUP BY houjin_bangou "
                " LIMIT 200",
                (auth,),
            ):
                disposed_bangous.append(
                    (str(r["houjin_bangou"]), str(r["last_issuance"] or ""))
                )
        if disposed_bangous and table_exists(primary_conn, "jpi_adoption_records"):
            count_with_adopt = 0
            adoption_total_count = 0
            adoption_total_amount = 0
            for bangou, last_issuance in disposed_bangous:
                hit_count = 0
                hit_amount = 0
                with contextlib.suppress(Exception):
                    for r in primary_conn.execute(
                        "SELECT COUNT(*) AS c, "
                        "       COALESCE(SUM(amount_granted_yen), 0) AS s "
                        "  FROM jpi_adoption_records "
                        " WHERE houjin_bangou = ? "
                        "   AND (announced_at IS NULL OR announced_at >= ?)",
                        (bangou, last_issuance),
                    ):
                        hit_count = int(r["c"] or 0)
                        hit_amount = int(r["s"] or 0)
                if hit_count > 0:
                    count_with_adopt += 1
                    adoption_total_count += hit_count
                    adoption_total_amount += hit_amount
                if (
                    len(record["disposed_houjin_sample"]) < PER_AXIS_RECORD_CAP
                    and hit_count > 0
                ):
                    with contextlib.suppress(Exception):
                        for h in primary_conn.execute(
                            "SELECT normalized_name, prefecture FROM jpi_houjin_master "
                            " WHERE houjin_bangou = ? LIMIT 1",
                            (bangou,),
                        ):
                            record["disposed_houjin_sample"].append(
                                {
                                    "houjin_bangou": bangou,
                                    "normalized_name": h["normalized_name"],
                                    "prefecture": h["prefecture"],
                                    "last_disposition_date": last_issuance,
                                    "post_disposition_adoption_count": hit_count,
                                    "post_disposition_total_amount_yen": hit_amount,
                                }
                            )
                            break
            record["post_disposition_adoption_summary"] = {
                "disposed_houjin_with_adoption_count": count_with_adopt,
                "post_disposition_adoption_count": adoption_total_count,
                "post_disposition_total_amount_yen": adoption_total_amount,
            }

        yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    auth = str(row.get("issuing_authority") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(auth)}"
    kinds = list(row.get("kind_mix", []))
    samples = list(row.get("disposed_houjin_sample", []))
    rows_in_packet = len(kinds) + len(samples)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "処分前後の事業継続・復活判定は外部 advisor の判断が前提。"
                "本 packet は処分 × 採択 の descriptive cross-link で、recovery "
                "rate 計算は analyst 側で行う設計。"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該処分庁で処分後採択該当無し — 復活無を意味しない",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.meti.go.jp/",
            "source_fetched_at": None,
            "publisher": "経済産業省 (処分公表)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.houjin-bangou.nta.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税庁 法人番号公表",
            "license": "pdl_v1.0",
        },
    ]
    summary = row.get("post_disposition_adoption_summary") or {}
    metrics = {
        "disposition_count": int(row.get("disposition_count") or 0),
        "kind_mix_count": len(kinds),
        "disposed_houjin_with_adoption_count": int(
            summary.get("disposed_houjin_with_adoption_count") or 0
        ),
        "post_disposition_adoption_count": int(
            summary.get("post_disposition_adoption_count") or 0
        ),
        "post_disposition_total_amount_yen": int(
            summary.get("post_disposition_total_amount_yen") or 0
        ),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "jurisdiction", "id": auth},
        "issuing_authority": auth,
        "disposition_count": int(row.get("disposition_count") or 0),
        "kind_mix": kinds,
        "disposed_houjin_sample": samples,
        "post_disposition_adoption_summary": summary,
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
