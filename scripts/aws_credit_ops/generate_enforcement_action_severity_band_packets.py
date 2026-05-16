"""Generate ``enforcement_action_severity_band_v1`` packets (Wave 98 #8 of 10).

行政処分 enforcement_kind (am_enforcement_detail.enforcement_kind ∈
{business_improvement / license_revoke / grant_refund / subsidy_exclude /
fine / contract_suspend / investigation / other}) ごとに severity bucket
分布を集計し、descriptive enforcement action severity band indicator
として packet 化する。実際の処分有効性 / 不服申立可否 / 営業継続可否は
各所管省庁 + 行政書士 (不服申立支援) + 弁護士の一次確認が前提 (行政不服
審査法、行政書士法 §1の2、弁護士法 §72)。

Cohort
------
::

    cohort = enforcement_kind (business_improvement / license_revoke /
             grant_refund / subsidy_exclude / fine / contract_suspend /
             investigation / other)

``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
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

PACKAGE_KIND: Final[str] = "enforcement_action_severity_band_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 enforcement action severity band packet は am_enforcement_detail を "
    "enforcement_kind 別に severity bucket 集計した descriptive severity "
    "distribution proxy で、実際の処分有効性 / 不服申立可否 / 営業継続可否 "
    "判断は 各所管省庁 + 行政書士 (不服申立支援) + 弁護士の一次確認が前提"
    "です (行政不服審査法、行政書士法 §1の2、弁護士法 §72)。"
)

_ENFORCEMENT_KINDS: Final[tuple[str, ...]] = (
    "business_improvement",
    "license_revoke",
    "grant_refund",
    "subsidy_exclude",
    "fine",
    "contract_suspend",
    "investigation",
    "other",
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_enforcement_detail"):
        return

    for emitted, enforcement_kind in enumerate(_ENFORCEMENT_KINDS):
        case_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n   FROM am_enforcement_detail  WHERE enforcement_kind = ?",
                (enforcement_kind,),
            ).fetchone()
            if row:
                case_n = int(row["n"] or 0)

        # Amount severity buckets (¥, NULL = bucket 'unspecified'):
        # bucket_lt_1m / bucket_1m_10m / bucket_10m_100m / bucket_gte_100m
        # / bucket_unspecified
        bucket_unspecified = 0
        bucket_lt_1m = 0
        bucket_1m_10m = 0
        bucket_10m_100m = 0
        bucket_gte_100m = 0
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT amount_yen   FROM am_enforcement_detail  WHERE enforcement_kind = ?",
                (enforcement_kind,),
            ):
                a = r["amount_yen"]
                if a is None:
                    bucket_unspecified += 1
                else:
                    av = int(a)
                    if av < 1_000_000:
                        bucket_lt_1m += 1
                    elif av < 10_000_000:
                        bucket_1m_10m += 1
                    elif av < 100_000_000:
                        bucket_10m_100m += 1
                    else:
                        bucket_gte_100m += 1

        # exclusion_start / exclusion_end presence (排除期間 specified
        # / unspecified).
        exclusion_period_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM am_enforcement_detail "
                " WHERE enforcement_kind = ? "
                "   AND exclusion_start IS NOT NULL "
                "   AND exclusion_end IS NOT NULL",
                (enforcement_kind,),
            ).fetchone()
            if row:
                exclusion_period_n = int(row["n"] or 0)

        record = {
            "enforcement_kind": enforcement_kind,
            "case_n": case_n,
            "bucket_unspecified": bucket_unspecified,
            "bucket_lt_1m": bucket_lt_1m,
            "bucket_1m_10m": bucket_1m_10m,
            "bucket_10m_100m": bucket_10m_100m,
            "bucket_gte_100m": bucket_gte_100m,
            "exclusion_period_n": exclusion_period_n,
        }
        if case_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    enforcement_kind = str(row.get("enforcement_kind") or "UNKNOWN")
    case_n = int(row.get("case_n") or 0)
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(enforcement_kind)}"
    rows_in_packet = case_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "処分有効性 / 不服申立可否 / 営業継続可否判断は "
                "各所管省庁 + 行政書士 (不服申立支援) + 弁護士の一次確認が"
                "前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 enforcement_kind で 行政処分 観測無し",
            }
        )
    bucket_unspecified = int(row.get("bucket_unspecified") or 0)
    if bucket_unspecified > 0 and case_n > 0 and (bucket_unspecified / case_n) > 0.5:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": (
                    f"amount_yen が unspecified の比率 "
                    f"{bucket_unspecified}/{case_n} (>50%)、severity 分布 "
                    "解釈には注意"
                ),
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.e-gov.go.jp/laws/2050000061",
            "source_fetched_at": None,
            "publisher": "e-Gov 行政不服審査法",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.soumu.go.jp/main_sosiki/jichi_gyousei/bunken/",
            "source_fetched_at": None,
            "publisher": "総務省 行政不服審査制度",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "enforcement_kind", "id": enforcement_kind},
        "enforcement_kind": enforcement_kind,
        "case_n": case_n,
        "amount_severity_buckets": {
            "unspecified": bucket_unspecified,
            "lt_1m": int(row.get("bucket_lt_1m") or 0),
            "1m_10m": int(row.get("bucket_1m_10m") or 0),
            "10m_100m": int(row.get("bucket_10m_100m") or 0),
            "gte_100m": int(row.get("bucket_gte_100m") or 0),
        },
        "exclusion_period_n": int(row.get("exclusion_period_n") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={
            "cohort_id": enforcement_kind,
            "enforcement_kind": enforcement_kind,
        },
        metrics={
            "case_n": case_n,
            "exclusion_period_n": int(row.get("exclusion_period_n") or 0),
        },
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
