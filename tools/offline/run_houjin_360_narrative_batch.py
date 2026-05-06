#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""am_houjin_360_narrative batch driver — 法人 360° 解説 (lang=ja/en).

PURPOSE (migration wave24_141_am_narrative_quarantine の stub):
    houjin_master 中、am_houjin_360_narrative に未登録の法人を batch_size
    件取得し、Claude Code subagent に総合 360° 解説を生成させる helper。
    本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_houjin_360_narrative_batch.py
                  --batch_id 1 --batch_size 200 --lang ja --dry-run`
    2. 本 script: houjin_master の中で am_houjin_360_narrative に未登録の
                  houjin_bangou を SELECT、subagent 用 prompt + schema を出す。
    3. operator: Claude Code subagent → JSONL →
                 tools/offline/_inbox/houjin_360_narrative/.
    4. operator: ingest_offline_inbox.py が UNIQUE (houjin_bangou, lang) で
                 INSERT OR IGNORE。

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

from jpintel_mcp.ingest.schemas.houjin_360_narrative import Houjin360Narrative


TOOL_SLUG = "houjin_360_narrative"

# autonomath.db is unified primary (houjin_master mirrored) — single DB.
SQL_PENDING = """
    SELECT hm.houjin_bangou,
           hm.normalized_name,
           hm.address_normalized,
           hm.prefecture,
           hm.municipality,
           hm.corporation_type,
           hm.total_adoptions,
           hm.total_received_yen,
           hm.jsic_major
      FROM houjin_master AS hm
     WHERE hm.houjin_bangou IS NOT NULL
       AND hm.houjin_bangou != ''
       AND NOT EXISTS (
         SELECT 1 FROM am_houjin_360_narrative AS n
          WHERE n.houjin_bangou = hm.houjin_bangou
            AND n.lang = ?
       )
     ORDER BY COALESCE(hm.total_adoptions, 0) DESC, hm.houjin_bangou ASC
     LIMIT ?
"""

RULES = [
    "body_text = 法人 360° 解説 (300-600 字)。事業内容 / 採択履歴 / 行政処分有無 / "
    "適格事業者登録状況 / JSIC 業種をまとめる。",
    "事実は SELECT 結果 + 公開一次資料に基づくこと。推測は避け、"
    "不確実な点は「公開情報なし」と明記。",
    "source_url_json に houjin_master 由来 URL (NTA 法人番号 / EDINET / 自社サイト) を入れる。",
    "subagent_run_id = '{batch_id}-{seq}'。generated_at は ISO8601 UTC。",
    "houjin_bangou は 13 桁文字列のままで返す (整数化禁止)。",
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
    schema = Houjin360Narrative.model_json_schema()
    emit(
        tool_slug=TOOL_SLUG,
        batch_id=args.batch_id,
        rows=rows,
        schema_title=f"Houjin360Narrative ({args.lang})",
        schema_json=schema,
        title=f"am_houjin_360_narrative batch ({args.lang})",
        purpose=(
            f"houjin_master の中で am_houjin_360_narrative に未登録 "
            f"(lang={args.lang}) な法人について 360° 解説を生成する。"
        ),
        rules=RULES,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
