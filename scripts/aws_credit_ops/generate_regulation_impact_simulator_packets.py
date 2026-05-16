#!/usr/bin/env python3
"""Generate ``regulation_impact_simulator_v1`` packets (Wave 53.3 #10).

法令改正 × 影響業種 × 影響法人 (forward impact predictor) packet. For each
recent amendment (am_amendment_diff), surfaces the impacted JSIC majors and
top-affected houjin candidates (joined via houjin_master jsic_major and
program entity_id mapping). Predictor is descriptive — no judgment.

Cohort
------

::

    cohort = amendment_diff_id

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

PACKAGE_KIND: Final[str] = "regulation_impact_simulator_v1"
PER_AXIS_RECORD_CAP: Final[int] = 6

DEFAULT_DISCLAIMER: Final[str] = (
    "本 regulation impact simulator packet は am_amendment_diff + houjin_master "
    "JSIC の descriptive 紐付けで forward-looking ではありません。実際の改正"
    "影響評価は所管官庁 / 弁護士 / 税理士の確認が前提です。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_amendment_diff"):
        return

    cap = int(limit) if limit is not None else 20000
    # Build entity_id → jsic_major lookup (program entities only)
    entity_jsic: dict[str, str] = {}
    if table_exists(primary_conn, "am_entities"):
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT canonical_id, "
                "       UPPER(COALESCE("
                "         json_extract(raw_json, '$.industry_jsic_major'), "
                "         SUBSTR(json_extract(raw_json, '$.industry_jsic_medium'),1,1), "
                "         'UNKNOWN'"
                "       )) AS jsic_major "
                "  FROM am_entities "
                " WHERE record_kind = 'program'"
            ):
                cid = r["canonical_id"]
                jm = r["jsic_major"]
                if isinstance(cid, str) and isinstance(jm, str):
                    entity_jsic[cid] = jm or "UNKNOWN"

    sql = (
        "SELECT diff_id, entity_id, field_name, prev_value, new_value, "
        "       detected_at, source_url "
        "  FROM am_amendment_diff "
        " WHERE detected_at IS NOT NULL "
        " ORDER BY detected_at DESC "
        " LIMIT ?"
    )
    for emitted, base in enumerate(primary_conn.execute(sql, (cap,))):
        diff_id = str(base["diff_id"])
        entity_id = str(base["entity_id"] or "")
        jsic = entity_jsic.get(entity_id, "UNKNOWN")
        impacted_houjin: list[dict[str, Any]] = []
        if jsic != "UNKNOWN" and table_exists(primary_conn, "houjin_master"):
            with contextlib.suppress(Exception):
                for h in primary_conn.execute(
                    "SELECT houjin_bangou, normalized_name, prefecture, "
                    "       total_received_yen "
                    "  FROM houjin_master "
                    " WHERE jsic_major = ? "
                    "   AND total_received_yen > 0 "
                    " ORDER BY total_received_yen DESC "
                    " LIMIT ?",
                    (jsic, PER_AXIS_RECORD_CAP),
                ):
                    impacted_houjin.append(
                        {
                            "houjin_bangou": h["houjin_bangou"],
                            "normalized_name": h["normalized_name"],
                            "prefecture": h["prefecture"],
                            "total_received_yen": int(h["total_received_yen"] or 0),
                        }
                    )
        yield {
            "diff_id": diff_id,
            "entity_id": entity_id,
            "field_name": base["field_name"],
            "prev_value": (
                str(base["prev_value"])[:160]
                if base["prev_value"] is not None
                else None
            ),
            "new_value": (
                str(base["new_value"])[:160]
                if base["new_value"] is not None
                else None
            ),
            "detected_at": base["detected_at"],
            "source_url": base["source_url"],
            "impacted_jsic_major": jsic,
            "impacted_houjin": impacted_houjin,
        }
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    diff_id = str(row.get("diff_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(diff_id)}"
    impacted = list(row.get("impacted_houjin", []))
    rows_in_packet = 1 + len(impacted)  # amendment row counts as 1

    known_gaps: list[dict[str, str]] = [
        {
            "code": "professional_review_required",
            "description": (
                "実際の改正影響評価は所管官庁 / 弁護士 / 税理士の確認が前提。"
                "本 packet は entity → JSIC → houjin の descriptive 紐付けです。"
            ),
        }
    ]
    if not impacted:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "JSIC マッピング未確定 — 影響法人列挙不可",
            }
        )
    if row.get("detected_at") is None:
        known_gaps.append(
            {
                "code": "freshness_stale_or_unknown",
                "description": "detected_at 不明 — 改正検知時点が不明",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": (
                str(row.get("source_url"))
                if row.get("source_url") is not None
                else "https://laws.e-gov.go.jp/"
            ),
            "source_fetched_at": None,
            "publisher": "e-Gov 法令検索 (改正検知元)",
            "license": "cc_by_4.0",
        },
        {
            "source_url": "https://kanpou.npb.go.jp/",
            "source_fetched_at": None,
            "publisher": "官報 (国立印刷局)",
            "license": "gov_standard",
        },
    ]
    metrics = {
        "impacted_jsic_major": str(row.get("impacted_jsic_major") or "UNKNOWN"),
        "impacted_houjin_count": len(impacted),
    }
    body: dict[str, Any] = {
        "subject": {"kind": "rule_change", "id": diff_id},
        "amendment": {
            "entity_id": row.get("entity_id"),
            "field_name": row.get("field_name"),
            "prev_value": row.get("prev_value"),
            "new_value": row.get("new_value"),
            "detected_at": row.get("detected_at"),
        },
        "impacted_houjin": impacted,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": diff_id, "diff_id": diff_id},
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
