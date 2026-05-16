#!/usr/bin/env python3
"""Generate ``kfs_saiketsu_industry_radar_v1`` packets (Wave 54 #5).

国税不服審判所 裁決 (nta_saiketsu / KFS) × JSIC 業種 packet. For each
tax_type bucket, surfaces the saiketsu rows + count by 業種-mappable
keyword. Industry-side keyword bucketing is heuristic (the saiketsu corpus
itself is not industry-tagged) so the packet honestly emits
``identity_ambiguity_unresolved`` for cross-walk results.

Cohort
------

::

    cohort = tax_type (税目)

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

PACKAGE_KIND: Final[str] = "kfs_saiketsu_industry_radar_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

# JSIC-major aware keyword shapes (heuristic, descriptive only).
_INDUSTRY_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "D_建設": ("建設", "建築", "土木", "工事"),
    "E_製造": ("製造", "工場", "生産"),
    "F_電気": ("電気", "ガス", "熱供給"),
    "G_情報": ("ソフト", "情報", "通信"),
    "H_運輸": ("運輸", "運送", "倉庫", "物流"),
    "I_卸小売": ("卸", "小売", "商社"),
    "J_金融": ("銀行", "金融", "保険"),
    "K_不動産": ("不動産", "賃貸", "売買"),
    "L_学術": ("研究", "技術サービス", "学術"),
    "M_飲食": ("飲食", "宿泊", "ホテル"),
    "N_生活": ("理美容", "クリーニング", "生活関連"),
    "O_教育": ("教育", "学習"),
    "P_医療": ("医療", "病院", "介護", "福祉"),
    "Q_複合": ("複合",),
    "R_他サービス": ("廃棄物", "リース", "労務"),
}

DEFAULT_DISCLAIMER: Final[str] = (
    "本 kfs saiketsu industry radar packet は国税不服審判所 裁決事例の"
    "業種別 keyword bucket です。JSIC との厳密対応は付与されていません。"
    "裁決の正本は kfs.go.jp、業種判定は実態に応じて再確認してください "
    "(税理士法 §52 / §72 boundaries — 個別事案は税理士確認必須)。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "nta_saiketsu"):
        return

    tax_types: list[str] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT DISTINCT tax_type FROM nta_saiketsu "
            " WHERE tax_type IS NOT NULL AND tax_type != ''"
        ):
            tax_types.append(str(r["tax_type"]))

    for emitted, tax_type in enumerate(tax_types):
        record: dict[str, Any] = {
            "tax_type": tax_type,
            "industry_buckets": [],
            "saiketsu_sample": [],
        }
        # Build industry buckets via keyword sampling of the saiketsu corpus.
        buckets: dict[str, list[dict[str, Any]]] = {
            label: [] for label in _INDUSTRY_KEYWORDS
        }
        with contextlib.suppress(Exception):
            for sk in primary_conn.execute(
                "SELECT decision_date, title, decision_summary, source_url "
                "  FROM nta_saiketsu "
                " WHERE tax_type = ? "
                " ORDER BY decision_date DESC "
                " LIMIT 200",
                (tax_type,),
            ):
                text = (
                    f"{sk['title'] or ''} {sk['decision_summary'] or ''}"
                ).strip()
                tagged = False
                for label, kws in _INDUSTRY_KEYWORDS.items():
                    if any(kw in text for kw in kws) and len(buckets[label]) < 3:
                        buckets[label].append(
                            {
                                "decision_date": sk["decision_date"],
                                "title": (
                                    str(sk["title"])[:100]
                                    if sk["title"] is not None
                                    else None
                                ),
                                "source_url": sk["source_url"],
                            }
                        )
                        tagged = True
                if not tagged and len(record["saiketsu_sample"]) < PER_AXIS_RECORD_CAP:
                    record["saiketsu_sample"].append(
                        {
                            "decision_date": sk["decision_date"],
                            "title": (
                                str(sk["title"])[:100]
                                if sk["title"] is not None
                                else None
                            ),
                            "source_url": sk["source_url"],
                        }
                    )

        for label, rows in buckets.items():
            if rows:
                record["industry_buckets"].append(
                    {
                        "industry_label": label,
                        "match_count": len(rows),
                        "samples": rows,
                    }
                )

        if record["industry_buckets"] or record["saiketsu_sample"]:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    tax_type = str(row.get("tax_type") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(tax_type)}"
    buckets = list(row.get("industry_buckets", []))
    samples = list(row.get("saiketsu_sample", []))
    rows_in_packet = sum(int(b.get("match_count") or 0) for b in buckets) + len(samples)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "業種ラベルは keyword bucket — JSIC 厳密対応ではない。"
                "個別事案の業種判定は税理士確認が前提。"
            ),
        }
    ]
    if len(buckets) == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "この税目では業種 keyword 一致なし — 全件 sample 参照",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.kfs.go.jp/",
            "source_fetched_at": None,
            "publisher": "国税不服審判所",
            "license": "gov_standard",
        },
        {
            "source_url": "https://www.e-stat.go.jp/classifications/terms/10",
            "source_fetched_at": None,
            "publisher": "e-Stat (JSIC)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "industry_bucket_count": len(buckets),
        "untagged_sample_count": len(samples),
        "total_matches": sum(int(b.get("match_count") or 0) for b in buckets),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "tax_type", "id": tax_type},
        "tax_type": tax_type,
        "industry_buckets": buckets,
        "saiketsu_sample": samples,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": tax_type, "tax_type": tax_type},
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
