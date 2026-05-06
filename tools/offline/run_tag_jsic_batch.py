#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""JSIC tagging batch driver — assigns jsic_major/middle/minor to programs.

PURPOSE (W2-13 連動 / migration wave24_113a / wave24_113b):
    `programs.jsic_major IS NULL` な未タグ program を batch_size 件取得し、
    Claude Code subagent に program 名 + enriched 内容から JSIC 業種コードを
    分類させる helper。本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_tag_jsic_batch.py --batch_id 1
                  --batch_size 200 --dry-run`
    2. 本 script: SQL から jsic_major IS NULL の program list を SELECT し、
                  subagent 用 prompt + JSON schema + 投入 path を stdout に。
    3. operator: Claude Code subagent を起動して prompt を渡す。
    4. subagent: 結果を JSON Lines として
                 tools/offline/_inbox/jsic_classification/{date}-batch_{id}.jsonl に書く。
    5. operator: scripts/cron/ingest_offline_inbox.py で programs テーブル
                 (jsic_major / middle / minor / assigned_at / assigned_method)
                 へ UPDATE。

NO LLM IMPORT.
"""
from __future__ import annotations

import argparse
import sys

from _runner_common import (
    DEFAULT_JPINTEL_DB,
    emit,
    query_rows,
)

# Pydantic schema (Pydantic v2). Imported via path injection in _runner_common.
from jpintel_mcp.ingest.schemas.jsic_tag import JsicTag

TOOL_SLUG = "jsic_classification"

SQL_UNTAGGED = """
    SELECT unified_id,
           primary_name,
           authority_name,
           program_kind,
           prefecture,
           crop_categories_json,
           target_types_json,
           funding_purpose_json,
           equipment_category,
           source_url
      FROM programs
     WHERE excluded = 0
       AND tier IN ('S','A','B','C')
       AND jsic_major IS NULL
     ORDER BY tier ASC, unified_id ASC
     LIMIT ?
"""

RULES = [
    "JSIC 大分類 (A-T) を必ず 1 つ assign。判定不能なら 'S' (サービス業) を低 confidence で。",
    "JSIC 中分類 (2 桁) は確信できる場合のみ。曖昧なら null。",
    "JSIC 小分類 (3 桁) は中分類が確信できる場合のみ。",
    "rationale に program 名のキーワード、authority 名、crop / 設備カテゴリを根拠として明記。",
    "subagent_run_id = '{batch_id}-{seq}' を使う。",
    "assigned_at は ISO8601 UTC。",
    "jsic_assigned_method は 'classifier' (subagent 自動分類) を使う。",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--batch_id", type=int, required=True)
    p.add_argument("--batch_size", type=int, default=200)
    p.add_argument("--jpintel-db", default=str(DEFAULT_JPINTEL_DB))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rows = query_rows(args.jpintel_db, SQL_UNTAGGED, (args.batch_size,))
    schema = JsicTag.model_json_schema()
    emit(
        tool_slug=TOOL_SLUG,
        batch_id=args.batch_id,
        rows=rows,
        schema_title="JsicTag",
        schema_json=schema,
        title="JSIC tagging batch",
        purpose=(
            "programs.jsic_major IS NULL の program list を JSIC 大分類 / 中分類 / "
            "小分類で分類し、programs テーブルに UPDATE する素材を出力する。"
        ),
        rules=RULES,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
