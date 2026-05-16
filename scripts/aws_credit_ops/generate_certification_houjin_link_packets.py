#!/usr/bin/env python3
"""Generate ``certification_houjin_link_v1`` packets (Wave 58 #5 of 10).

認証 × 法人 link。am_entities で record_kind='certification' な認証 entity の
raw_json から ISO/JIS/GMP/HACCP 等の認証名を抽出し、認証保有 (またはマッチ) する
法人候補を集計する。

Cohort
------
::

    cohort = certification entity (canonical_id)
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

PACKAGE_KIND: Final[str] = "certification_houjin_link_v1"
PER_AXIS_RECORD_CAP: Final[int] = 12

DEFAULT_DISCLAIMER: Final[str] = (
    "本 certification houjin link packet は am_entities (record_kind='certification')"
    "と jpi_adoption_records の keyword マッチによる descriptive リンク指標です。"
    "実際の認証保有判断は各認証機関の公開リストの一次確認が必要。"
)


def _aggregate(
    *,
    primary_conn: sqlite3.Connection,
    jpintel_conn: sqlite3.Connection | None,
    limit: int | None,
) -> Iterator[dict[str, Any]]:
    if not table_exists(primary_conn, "am_entities"):
        return
    certs: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for r in primary_conn.execute(
            "SELECT canonical_id, "
            "       COALESCE("
            "         json_extract(raw_json, '$.item_name'), "
            "         json_extract(raw_json, '$.primary_name'), "
            "         json_extract(raw_json, '$.name') "
            "       ) AS name "
            "  FROM am_entities WHERE record_kind = 'certification' "
            " LIMIT 200"
        ):
            certs.append(dict(r))

    for emitted, c in enumerate(certs):
        cid = str(c.get("canonical_id") or "")
        name = str(c.get("name") or "")
        if not name or len(name) < 3:
            continue
        # Use first 4 chars as search keyword to broaden matches
        keyword = name[:4] if len(name) >= 4 else name
        matches: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for r in primary_conn.execute(
                "SELECT houjin_bangou, company_name_raw, prefecture, "
                "       program_name_raw, COUNT(*) AS adoptions "
                "  FROM jpi_adoption_records "
                " WHERE program_name_raw LIKE ? OR project_title LIKE ? "
                " GROUP BY houjin_bangou LIMIT ?",
                (f"%{keyword}%", f"%{keyword}%", PER_AXIS_RECORD_CAP),
            ):
                matches.append(dict(r))
        record = {
            "certification_id": cid,
            "certification_name": name,
            "search_keyword": keyword,
            "linked_houjin": matches,
            "match_count": len(matches),
        }
        if matches:
            yield record
        if limit is not None and (emitted + 1) >= limit:
            return


def _render(row: dict[str, Any], generated_at: str) -> tuple[str, dict[str, Any], int]:
    cid = str(row.get("certification_id") or "UNKNOWN")
    package_id = f"{PACKAGE_KIND}:{safe_packet_id_segment(cid)}"
    matches = list(row.get("linked_houjin", []))
    rows_in_packet = len(matches)

    known_gaps: list[dict[str, str]] = [
        {
            "code": "identity_ambiguity_unresolved",
            "description": (
                "認証保有は keyword マッチ proxy、実際の保有判断は各認証機関の"
                "公開リストの一次確認が必要"
            ),
        }
    ]
    if rows_in_packet == 0:
        known_gaps.append(
            {
                "code": "no_hit_not_absence",
                "description": "該認証で linked houjin 観測無し",
            }
        )

    sources: list[dict[str, Any]] = [
        {
            "source_url": "https://www.jab.or.jp/",
            "source_fetched_at": None,
            "publisher": "公益財団法人 日本適合性認定協会 (JAB)",
            "license": "proprietary",
        },
        {
            "source_url": "https://www.jisc.go.jp/",
            "source_fetched_at": None,
            "publisher": "日本工業標準調査会 (JISC)",
            "license": "gov_standard",
        },
    ]
    body: dict[str, Any] = {
        "subject": {"kind": "certification", "id": cid},
        "certification_id": cid,
        "certification_name": str(row.get("certification_name") or ""),
        "linked_houjin": matches,
    }
    envelope = jpcir_envelope(
        package_kind=PACKAGE_KIND,
        package_id=package_id,
        cohort_definition={"cohort_id": cid, "certification_id": cid},
        metrics={"match_count": rows_in_packet},
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
