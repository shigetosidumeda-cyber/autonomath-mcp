#!/usr/bin/env python3
"""Generate ``succession_event_pulse_v1`` packets (Wave 56 #9 of 10).

事業承継・廃業の代理 signal として jpi_adoption_records の announced_at と
am_application_round の close_date を都道府県別 × 月別 pulse 化する。
法人マスタの established_date/close_date は現状 gBizINFO snapshot で空のため
採用しない。代わりに採択イベント = 事業継続性の良い proxy、申請締切 =
事業承継 timing 検討 signal として扱う。

Cohort
------
::

    cohort = prefecture
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

PACKAGE_KIND: Final[str] = "succession_event_pulse_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 succession event pulse packet は jpi_houjin_master の established_date / "
    "close_date を都道府県 × 月で集計した descriptive 法人ライフサイクル指標です。"
    "事業承継支援判断は中小機構 + 各自治体支援センターの一次確認が前提。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "jpi_adoption_records"):
        return
    prefs: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT prefecture FROM jpi_adoption_records "
            " WHERE prefecture IS NOT NULL AND prefecture != ''"
        ):
            prefs.append(str(r["prefecture"]))

    for emitted, pref in enumerate(prefs):
        adoption_monthly: dict[str, int] = {}
        close_monthly: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT substr(announced_at, 1, 7) AS ym, COUNT(*) AS c "
                "  FROM jpi_adoption_records "
                " WHERE prefecture = ? AND announced_at IS NOT NULL "
                "   AND length(announced_at) >= 7 "
                " GROUP BY ym ORDER BY ym DESC LIMIT ?",
                (pref, PER_AXIS_RECORD_CAP),
            ):
                adoption_monthly[str(r["ym"])] = int(r["c"] or 0)
        if table_exists(primary_conn, "am_application_round"):
            with contextlib.suppress(Exception):
                for r in primary_conn.execute(
                    "SELECT substr(application_close_date, 1, 7) AS ym, "
                    "       COUNT(*) AS c "
                    "  FROM am_application_round "
                    " WHERE application_close_date IS NOT NULL "
                    "   AND length(application_close_date) >= 7 "
                    " GROUP BY ym ORDER BY ym DESC LIMIT ?",
                    (PER_AXIS_RECORD_CAP,),
                ):
                    close_monthly[str(r["ym"])] = int(r["c"] or 0)
        record = {
            "prefecture": pref,
            "adoption_event_monthly": adoption_monthly,
            "application_close_monthly": close_monthly,
            "adoption_total": sum(adoption_monthly.values()),
            "application_close_total": sum(close_monthly.values()),
        }
        if adoption_monthly or close_monthly:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    pref = str(row.get("prefecture") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(pref)}"
    adopt = dict(row.get("adoption_event_monthly", {}))
    cl = dict(row.get("application_close_monthly", {}))
    rows_in_packet = len(adopt) + len(cl)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "freshness_stale_or_unknown",
            "description": (
                "事業活動 pulse は jpi_adoption_records 採択時点 + "
                "am_application_round 締切時点 の proxy"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該都道府県で月次パルス観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jgrants-portal.go.jp/",
            "source_fetched_at": None,
            "publisher": "Jグランツ",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.chusho.meti.go.jp/zaimu/shoukei/",
            "source_fetched_at": None,
            "publisher": "中小企業庁 事業承継",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "prefecture", "id": pref},
        "prefecture": pref,
        "adoption_event_monthly": adopt,
        "application_close_monthly": cl,
        "adoption_total": int(row.get("adoption_total") or 0),
        "application_close_total": int(row.get("application_close_total") or 0),
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": pref, "prefecture": pref},
        metrics={
            "adoption_event_month_count": len(adopt),
            "application_close_month_count": len(cl),
            "adoption_total": int(row.get("adoption_total") or 0),
            "application_close_total": int(row.get("application_close_total") or 0),
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
