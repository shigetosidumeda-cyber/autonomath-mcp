#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""am_enforcement_summary batch driver — 行政処分の経緯・原因・結果サマリ.

PURPOSE (migration wave24_141_am_narrative_quarantine の stub):
    am_enforcement_detail 中、am_enforcement_summary に未登録の処分を
    batch_size 件取得し、Claude Code subagent にサマリを生成させる helper。
    本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_enforcement_summary_batch.py
                  --batch_id 1 --batch_size 200 --lang ja --dry-run`
    2. 本 script: am_enforcement_detail で am_enforcement_summary に未登録の
                  enforcement_id を SELECT、subagent 用 prompt + schema を出す。
    3. operator: Claude Code subagent → JSONL →
                 tools/offline/_inbox/enforcement_summary/.
    4. operator: ingest_offline_inbox.py が UNIQUE (enforcement_id, lang) で INSERT。

NO LLM IMPORT.
"""

from __future__ import annotations

import argparse
import sys

from _runner_common import (
    DEFAULT_AUTONOMATH_DB,
    emit,
    query_rows,
)

from jpintel_mcp.ingest.schemas.enforcement_summary import EnforcementSummary

TOOL_SLUG = "enforcement_summary"

SQL_PENDING = """
    SELECT ed.enforcement_id,
           ed.houjin_bangou,
           ed.target_name,
           ed.enforcement_kind,
           ed.issuing_authority,
           ed.issuance_date,
           ed.exclusion_start,
           ed.exclusion_end,
           ed.amount_yen,
           ed.reason_summary,
           ed.related_law_ref,
           ed.source_url
      FROM am_enforcement_detail AS ed
     WHERE ed.source_url IS NOT NULL
       AND ed.source_url != ''
       AND NOT EXISTS (
         SELECT 1 FROM am_enforcement_summary AS s
          WHERE s.enforcement_id = ed.enforcement_id
            AND s.lang = ?
       )
     ORDER BY ed.issuance_date DESC, ed.enforcement_id ASC
     LIMIT ?
"""

RULES = [
    "body_text = 経緯 / 原因 / 結果 / 該当法令 / 教訓を 200-500 字で。",
    "事実は source_url の一次資料に基づくこと。推測は明示し confidence を下げる旨を本文に。",
    "amount_yen が NULL なら本文中に「金額: 公開情報なし」と明記。",
    "source_url_json に少なくとも 1 つ source_url を入れる。",
    "subagent_run_id = '{batch_id}-{seq}'。generated_at は ISO8601 UTC。",
    "lang は --lang 引数に合わせる。",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--batch_id", type=int, required=True)
    p.add_argument("--batch_size", type=int, default=200)
    p.add_argument("--lang", choices=("ja", "en"), default="ja")
    p.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rows = query_rows(args.autonomath_db, SQL_PENDING, (args.lang, args.batch_size))
    schema = EnforcementSummary.model_json_schema()
    emit(
        tool_slug=TOOL_SLUG,
        batch_id=args.batch_id,
        rows=rows,
        schema_title=f"EnforcementSummary ({args.lang})",
        schema_json=schema,
        title=f"am_enforcement_summary batch ({args.lang})",
        purpose=(
            f"am_enforcement_detail の中で am_enforcement_summary に未登録 "
            f"(lang={args.lang}) な処分について経緯サマリを生成する。"
        ),
        rules=RULES,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
