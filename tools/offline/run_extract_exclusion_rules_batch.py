#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Offline exclusion-rules ETL batch driver (operator-only, no LLM SDK import).

Operator-only offline script. Not callable from production runtime.

PURPOSE (MASTER_PLAN_v1 章 3 §D4 — exclusion_rules 181 → 5,000-10,000 ルール拡張):
    tier S/A の公募要領 PDF (cache 済) を 50 件ずつバッチで取得し、
    各 program の併給可否 / 排他 / 前提条件 / 絶対禁止 を Claude Code
    subagent に構造化抽出させる helper。

    本スクリプト自体は **LLM API を呼ばない**。Anthropic / OpenAI /
    Google の SDK import を一切持たないことが launch invariant
    (`feedback_no_operator_llm_api`, CLAUDE.md "What NOT to do" §) の
    遵守条件。

    実際の抽出は Claude Code subagent (operator が手動で起動する別
    プロセス) が JSON Lines を `tools/offline/_inbox/exclusion_rules/`
    に書き込む形で完結する。subagent への投入指示と出力スキーマは
    本ファイルの docstring と stdout に出力される。

WORKFLOW:
    1. operator: `python tools/offline/run_extract_exclusion_rules_batch.py
                  --tier S,A --batch-size 50 --batch-id 2026-05-04-batch-001`
    2. 本 script: SQL から tier S/A の対象 program list + cached PDF path
                  + source_url を SELECT し、subagent 用プロンプト雛形を
                  /tmp/exclusion_rules_batch_<batch_id>.md に書き出す。
                  __ANTHROPIC_KEY__ などの API key は触らない。
    3. operator: Claude Code subagent (Task tool) を起動し、上記プロンプト
                 + program list を渡す。subagent が PDF を読んで構造化
                 出力する。
    4. subagent: 結果を JSON Lines として
                 `tools/offline/_inbox/exclusion_rules/{date}-{batch_id}.jsonl`
                 に書き込む (1 行 = 1 program、`rules` は配列)。
    5. operator: `python scripts/cron/ingest_offline_inbox.py` を実行し、
                 inbox の jsonl を Pydantic 検証 → exclusion_rules テーブル
                 に INSERT する (こちらも LLM API を呼ばない)。

OUTPUT JSON LINES SCHEMA (subagent が遵守すべき形式):
    {
      "program_id": int,             // jpintel.programs.unified_id を str→int 変換不能なら 0
      "program_uid": str,            // unified_id (元の文字列のまま)
      "rules": [
        {
          "kind": "exclude" | "prerequisite" | "absolute" | "combine_ok",
          "target_program_id": int | null,   // 相手側 program (combine_ok / exclude)
          "target_program_uid": str | null,  // 相手側 unified_id
          "clause_quote": str,               // 公募要領からの literal-quote
                                              // (照合に使うので改変禁止)
          "source_url": str,                 // 一次資料 URL (公募要領 PDF)
          "confidence": "high" | "med" | "low"
        }
      ],
      "subagent_run_id": str,        // subagent 側で割り振る trace id
      "evaluated_at": str            // ISO8601 UTC
    }

INBOX → DB 取り込みの検証要件:
    `scripts/cron/ingest_offline_inbox.py` 側で:
    - clause_quote が公募要領原本にリテラル一致するか確認
      (literal-quote check pass)
    - source_url が programs.source_url と整合するか
    - target_program_id / target_program_uid のいずれかが non-null
    - kind が enum 範囲内
    のチェックを通った行のみを exclusion_rules に INSERT する。
    fail した行は `_quarantine/exclusion_rules/` へ moved。

Usage:
    python tools/offline/run_extract_exclusion_rules_batch.py \\
        --tier S,A --batch-size 50 --batch-id 2026-05-04-001
    python tools/offline/run_extract_exclusion_rules_batch.py \\
        --tier S,A --batch-size 50 --batch-id 2026-05-04-001 --dry-run

Flags:
    --tier S,A           対象 tier (CSV)
    --batch-size N       1 batch あたりの program 件数 (default 50)
    --batch-id STR       trace 用 batch ID (subagent run と紐付け)
    --jpintel-db PATH    jpintel.db (default: data/jpintel.db)
    --dry-run            プロンプト雛形を出すだけで program list は stdout
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
INBOX_DIR = Path(__file__).resolve().parent / "_inbox" / "exclusion_rules"
PROMPT_DIR = Path("/tmp")

LOG = logging.getLogger("extract_exclusion_rules_batch")

SUBAGENT_PROMPT_TEMPLATE = """\
# exclusion_rules 抽出ジョブ (subagent 用プロンプト雛形)

## 目的
以下 program list の公募要領 (一次資料 PDF / HTML) を読み、
各 program の併給可否 / 排他 / 前提条件 / 絶対禁止 を構造化抽出する。

## 出力先
`{inbox_path}` に JSON Lines (1 行 = 1 program) で書き込むこと。

## 出力スキーマ (1 行ぶん)
```
{{
  "program_id": int,
  "program_uid": "<unified_id>",
  "rules": [
    {{
      "kind": "exclude" | "prerequisite" | "absolute" | "combine_ok",
      "target_program_id": int | null,
      "target_program_uid": "<unified_id>" | null,
      "clause_quote": "<公募要領からの literal quote、改変禁止>",
      "source_url": "<一次資料 URL>",
      "confidence": "high" | "med" | "low"
    }}
  ],
  "subagent_run_id": "<batch_id>-<seq>",
  "evaluated_at": "<ISO8601 UTC>"
}}
```

## ルール
1. clause_quote は公募要領の原文をそのままコピーすること
   (誤字も含めてリテラル)。意訳・要約は禁止。
2. source_url は programs.source_url と一致すること。
3. confidence:
   - "high" = 公募要領に明記
   - "med" = 関連 page 参照で推測可能
   - "low" = 慣行・他制度との類推
4. rules が空配列の program もそのまま出力 (空 array で OK)。
5. LLM 推論で曖昧な場合は confidence='low' を選び、推測内容を
   clause_quote に括弧付きで記載 (e.g. "[類推] ..." )。

## program list (この batch で処理)
{program_list_json}
"""


def list_target_programs(jpintel_db: Path, tiers: list[str], limit: int) -> list[dict[str, Any]]:
    """tier S/A の対象 program を SQL から取得 (LLM 呼出なし)."""
    placeholders = ",".join(["?"] * len(tiers))
    sql = f"""
        SELECT unified_id, primary_name, source_url, official_url,
               authority_level, authority_name, prefecture, program_kind
          FROM programs
         WHERE tier IN ({placeholders})
           AND excluded = 0
           AND COALESCE(source_url, official_url) IS NOT NULL
           AND COALESCE(source_url, official_url) != ''
         ORDER BY tier ASC, unified_id ASC
         LIMIT ?
    """
    conn = sqlite3.connect(jpintel_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, [*tiers, limit]).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def chunk(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def render_subagent_prompt(programs: list[dict[str, Any]], inbox_path: Path) -> str:
    program_list_json = json.dumps(programs, ensure_ascii=False, indent=2)
    return SUBAGENT_PROMPT_TEMPLATE.format(
        inbox_path=str(inbox_path),
        program_list_json=program_list_json,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tier", default="S,A", help="対象 tier の CSV (default 'S,A')")
    p.add_argument(
        "--batch-size", type=int, default=50, help="1 batch あたりの program 数 (default 50)"
    )
    p.add_argument("--batch-id", required=True, help="trace 用 batch ID (e.g. 2026-05-04-001)")
    p.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    p.add_argument(
        "--dry-run", action="store_true", help="プロンプト雛形と program list を stdout に出すのみ"
    )
    p.add_argument(
        "--max-programs",
        type=int,
        default=500,
        help="本 invocation で取り出す program 上限 (default 500)",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    tiers = [t.strip().upper() for t in args.tier.split(",") if t.strip()]
    if not tiers:
        LOG.error("--tier が空です")
        return 2

    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    LOG.info("listing tier=%s programs (limit=%d)", tiers, args.max_programs)
    programs = list_target_programs(args.jpintel_db, tiers, args.max_programs)
    LOG.info("got %d programs", len(programs))

    today = datetime.now(UTC).strftime("%Y%m%d")
    batch_id = args.batch_id

    n_batches = 0
    for batch_idx, batch_rows in enumerate(chunk(programs, args.batch_size)):
        n_batches += 1
        inbox_filename = f"{today}-{batch_id}-batch{batch_idx:03d}.jsonl"
        inbox_path = INBOX_DIR / inbox_filename
        prompt_path = PROMPT_DIR / f"exclusion_rules_{batch_id}_batch{batch_idx:03d}.md"
        prompt_text = render_subagent_prompt(batch_rows, inbox_path)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        LOG.info(
            "batch %03d: %d programs → prompt=%s inbox=%s",
            batch_idx,
            len(batch_rows),
            prompt_path,
            inbox_path,
        )
        if args.dry_run:
            print(f"--- batch {batch_idx} ---")
            print(prompt_text)

    LOG.info("done. batches=%d inbox_dir=%s", n_batches, INBOX_DIR)
    LOG.info(
        "next step: run a Claude Code subagent on each /tmp/"
        "exclusion_rules_*.md prompt; subagent must write JSONL "
        "to %s, then run scripts/cron/ingest_offline_inbox.py",
        INBOX_DIR,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
