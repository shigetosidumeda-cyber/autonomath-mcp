"""Generate ``divestiture_event_signal_v1`` packets (Wave 89 #2 of 10).

業種 (JSIC major) ごとに 譲渡 event signal (事業譲渡 / 子会社売却 /
非中核資産処分 / カーブアウト / 撤退) の signal 兆候 (採択密度 proxy) を
集計し, descriptive sectoral divestiture event signal indicator として
packet 化する。実際の譲渡対価 / SPA 条件 / 表明保証 / クロージング
条件 / 競業避止 / 残存債務承継は EDINET 臨時報告書 + JPX 適時開示 +
M&A advisor + 弁護士 (M&A) の一次確認が前提。

Cohort
------
::

    cohort = jsic_major (A-V)
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

PACKAGE_KIND: Final[str] = "divestiture_event_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 divestiture event signal packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、実際の譲渡対価 / SPA "
    "条件 / 表明保証 / クロージング条件 / 競業避止 / 残存債務承継 / "
    "適格分社型分割 判断は EDINET 臨時報告書 + JPX 適時開示 + M&A "
    "advisor + 弁護士 (M&A) + 税理士 (組織再編) の一次確認が前提です "
    "(会社法 §467 事業譲渡 §763 会社分割, 金商法 §24-5 §27-9-2, 法人税"
    "法 §62-3 適格分割 §62-9 適格分社型, 独禁法 §16)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_industry_jsic"):
        return
    industries: list[tuple[str, str]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic "
            " WHERE jsic_level = 'major' ORDER BY jsic_code"
        ):
            industries.append((str(r["jsic_code"]), str(r["jsic_name_ja"])))

    for emitted, (jsic_code, jsic_name) in enumerate(industries):
        adoption_n = 0
        with contextlib.suppress(Exception):
            row = primary_conn.execute(
                "SELECT COUNT(*) AS n FROM jpi_adoption_records  WHERE industry_jsic_medium = ?",
                (jsic_code,),
            ).fetchone()
            if row:
                adoption_n = int(row["n"] or 0)
        record = {
            "jsic_major": jsic_code,
            "jsic_name_ja": jsic_name,
            "adoption_n": adoption_n,
        }
        if adoption_n > 0:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    jsic_code = str(row.get("jsic_major") or "UNKNOWN")
    jsic_name = str(row.get("jsic_name_ja") or "")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(jsic_code)}"
    adoption_n = int(row.get("adoption_n") or 0)
    rows_in_packet = adoption_n

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "譲渡対価 / SPA 条件 / 表明保証 / クロージング条件 / "
                "競業避止 / 残存債務承継 / 適格分社型分割 判断は EDINET"
                " 臨時報告書 + JPX 適時開示 + M&A advisor + 弁護士 + 税"
                "理士 (組織再編) の一次確認が前提"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該 jsic_major で adoption record 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://disclosure.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET 金融庁 (臨時報告書 / 有価証券報告書)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.release.tdnet.info/",
            "source_fetched_at": None,
            "publisher": "JPX 東証 適時開示情報 (事業譲渡 / 子会社売却)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "jsic_major", "id": jsic_code},
        "jsic_major": jsic_code,
        "jsic_name_ja": jsic_name,
        "adoption_n": adoption_n,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": jsic_code, "jsic_major": jsic_code},
        metrics={
            "adoption_n": adoption_n,
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
