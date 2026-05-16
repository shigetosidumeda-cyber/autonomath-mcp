"""Generate ``employer_practices_liability_v1`` packets (Wave 94 #5 of 10).

業種 (JSIC major) ごとに 雇用慣行賠償責任保険 (Employment Practices
Liability Insurance, EPLI) coverage (ハラスメント / 差別 / 不当解雇 /
パワハラ / 賃金未払 訴訟費用 / 第三者ハラスメント) の coverage 兆候
(採択密度 proxy) を集計し, descriptive sectoral EPLI indicator として
packet 化する。実際の限度額 / リテンション / 第三者ハラスメント特約 /
和解 settlement coverage / 個人事業主 cover 判断は損保会社 + 労働法専門
ブローカー + 社労士 + 弁護士 (労働) の一次確認が前提。

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

PACKAGE_KIND: Final[str] = "employer_practices_liability_v1"

DEFAULT_DISCLAIMER: Final[str] = (
    "本 employer practices liability (EPLI) packet は jpi_adoption_records "
    "業種別 採択密度 を集計した descriptive proxy で、実際の限度額 / リテ"
    "ンション / ハラスメント / 差別 / 不当解雇 / パワハラ / 賃金未払 訴訟"
    "費用 / 第三者ハラスメント特約 / settlement coverage / 個人事業主 cover"
    " 判断は損保会社 + 労働法専門ブローカー + 社労士 + 弁護士 (労働) の"
    "一次確認が前提です (労基法 §15-§24, 男女雇用機会均等法 §6 §11 §11-2 "
    "ハラスメント, パワハラ防止法 改正労働施策総合推進法 §30-2)。"
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
                "限度額 / リテンション / ハラスメント / 差別 / 不当解雇 / "
                "パワハラ / 賃金未払 訴訟費用 / 第三者ハラスメント特約 / "
                "settlement coverage / 個人事業主 cover 判断は損保会社 + "
                "労働法ブローカー + 社労士 + 弁護士 (労働) の一次確認が前提"
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
            "source_url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyoukintou/seisaku06/index.html",
            "source_fetched_at": None,
            "publisher": "厚労省 雇用環境均等 (ハラスメント防止指針)",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.no-harassment.mhlw.go.jp/",
            "source_fetched_at": None,
            "publisher": "厚労省 あかるい職場応援団 (パワハラ防止法)",
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
