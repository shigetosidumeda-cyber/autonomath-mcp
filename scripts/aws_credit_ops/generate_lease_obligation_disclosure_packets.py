"""Generate ``lease_obligation_disclosure_v1`` packets (Wave 93 #10 of 10).

業種 (JSIC major) ごとに Lease 義務 disclosure (IFRS 16) 兆候 (採択密度
proxy) を集計し、descriptive sectoral lease obligation disclosure indicator
として packet 化する。実際の 使用権資産 / リース負債 / IFRS 16 適用 / 日本
基準 リース取引会計基準 / オペレーティングリース vs ファイナンスリース /
セール&リースバック / 短期リース 免除 / 少額リース 免除 / 残価保証 判断は
EDINET 有価証券報告書 (連結注記 リース) + ASBJ リース会計基準 + IFRS 財団
+ KAM (監査上の主要な検討事項) + 監査法人 一次確認が前提。

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

PACKAGE_KIND: Final[str] = "lease_obligation_disclosure_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 lease obligation disclosure packet は jpi_adoption_records 業種別"
    " 採択密度 を集計した descriptive proxy で、実際の 使用権資産 / "
    "リース負債 / IFRS 16 適用 / 日本基準 リース取引会計基準 / オペレー"
    "ティングリース vs ファイナンスリース / セール&リースバック / 短期"
    "リース 免除 (12ヶ月以下) / 少額リース 免除 / 残価保証 / 借手割引率"
    " (追加借入利子率) / 拡張オプション / 解約オプション 判断は EDINET "
    "有価証券報告書 (連結注記 リース) + ASBJ リース会計基準 + IFRS 財団"
    " + KAM (監査上の主要な検討事項) + 監査法人 一次確認が前提です "
    "(IFRS 16 §22-§51 (Recognition), §38-§47 (Measurement), §51-§60 "
    "(Disclosure); 日本基準 ASBJ「リース取引に関する会計基準」企業会計"
    "基準第13号, 同適用指針第16号; 国際的会計基準コンバージェンス工程"
    " (2026 年予定 ASBJ 新リース基準); 公認会計士法 §2 監査義務, 金商"
    "法 §193-2 (財務情報の正確性), 法人税法 §22 (損金算入))。"
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
                "使用権資産 / リース負債 / IFRS 16 適用 / 日本基準"
                " リース取引会計基準 / オペレーティングリース vs "
                "ファイナンスリース / セール&リースバック / 短期"
                "リース 免除 / 少額リース 免除 / 残価保証 / 借手"
                "割引率 / 拡張・解約オプション 判断は EDINET 有価"
                "証券報告書 (連結注記 リース) + ASBJ リース会計"
                "基準 + IFRS 財団 + KAM + 監査法人 一次確認が前提"
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
            "source_url": "https://disclosure2.edinet-fsa.go.jp/",
            "source_fetched_at": None,
            "publisher": "EDINET 有価証券報告書 (連結注記 リース)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.asb.or.jp/jp/accounting_standards/accounting_standards/y2007/2007-0330.html",
            "source_fetched_at": None,
            "publisher": "ASBJ 企業会計基準第13号 リース取引に関する会計基準",
            "license": "proprietary",
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
