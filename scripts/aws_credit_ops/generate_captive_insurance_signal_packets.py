"""Generate ``captive_insurance_signal_v1`` packets (Wave 94 #9 of 10).

業種 (JSIC major) ごとに キャプティブ保険 (Captive Insurance) signal
(pure captive / group captive / rent-a-captive / cell captive / 再保険
fronting / 自家保険 prefunding) の signal 兆候 (採択密度 proxy) を集計し,
descriptive sectoral captive insurance indicator として packet 化する。
実際の domicile 選択 (バミューダ / シンガポール / ハワイ / 沖縄等) /
資本金 / solvency margin / 移転価格 / CFC 課税 (タックスヘイブン対策税制)
判断は損保会社 + captive 専門 actuary + 国際税理士 + 弁護士 (国際課税) +
domicile 規制当局の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "captive_insurance_signal_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 captive insurance signal packet は jpi_adoption_records 業種別 "
    "採択密度 を集計した descriptive proxy で、実際の domicile 選択 "
    "(バミューダ / シンガポール / ハワイ / 沖縄等) / 資本金 / solvency "
    "margin / pure captive vs group captive vs cell captive 構造 / 再保険"
    " fronting / 自家保険 prefunding / 移転価格 / CFC 課税 (タックスヘイ"
    "ブン対策税制) 判断は損保会社 + captive actuary + 国際税理士 + 弁護士"
    " (国際課税) + domicile 規制当局の一次確認が前提です (措置法 §66-6 "
    "外国子会社合算税制 / CFC 税制, 保険業法 §185 外国保険業者, OECD "
    "BEPS Action 3, 法人税法 §69 外税控除)。"
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
                "domicile 選択 / 資本金 / solvency margin / pure vs group "
                "vs cell captive 構造 / 再保険 fronting / 自家保険 "
                "prefunding / 移転価格 / CFC 課税 (タックスヘイブン対策"
                "税制) 判断は損保会社 + captive actuary + 国際税理士 + "
                "弁護士 (国際課税) + domicile 規制当局の一次確認が前提"
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
            "source_url": "https://www.fsa.go.jp/policy/hoken/",
            "source_fetched_at": None,
            "publisher": "金融庁 保険行政 (外国保険業者 §185)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.nta.go.jp/law/joho-zeikaishaku/hojin/",
            "source_fetched_at": None,
            "publisher": "国税庁 法人税 (CFC 税制 タックスヘイブン対策)",
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
