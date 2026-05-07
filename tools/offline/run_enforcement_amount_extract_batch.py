#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""Offline enforcement-amount ETL batch driver (operator-only, no LLM SDK import).

Operator-only offline script. Not callable from production runtime.

PURPOSE (MASTER_PLAN_v1 章 3 §M7 — am_enforcement_detail 22,258 のうち
amount 入り 9.8% → 90%+ への拡張):
    `am_enforcement_detail.amount_yen IS NULL` な行政処分行を 50 件ずつ
    バッチで取得し、各処分の発表 PDF / HTML から「課徴金 X 万円」
    「返還命令 X 円」「過料 X 円」等の金額表現を Claude Code subagent に
    構造化抽出させる helper。

    本スクリプト自体は **LLM API を呼ばない**。Anthropic / OpenAI /
    Google の SDK import を一切持たないことが launch invariant
    (`feedback_no_operator_llm_api`, CLAUDE.md "What NOT to do" §) の
    遵守条件。

    実際の抽出は Claude Code subagent (operator が手動で起動する別
    プロセス) が JSON Lines を `tools/offline/_inbox/enforcement_amount/`
    に書き込む形で完結する。subagent への投入指示と出力スキーマは
    本ファイルの docstring と /tmp/ プロンプト雛形に出力される。

WORKFLOW:
    1. operator: `python tools/offline/run_enforcement_amount_extract_batch.py
                  --batch-size 50 --batch-id 2026-05-04-batch-001`
    2. 本 script: SQL から amount_yen IS NULL の行政処分行を SELECT し、
                  source_url 付きで subagent 用プロンプトを
                  /tmp/enforcement_amount_<batch_id>.md に書き出す。
                  API key は触らない。
    3. operator: Claude Code subagent (Task tool) を起動して上記プロンプト
                 + 行 list を渡す。subagent が source_url の PDF / HTML
                 を読んで amount を抽出する。
    4. subagent: 結果を JSON Lines として
                 `tools/offline/_inbox/enforcement_amount/{date}-{batch_id}.jsonl`
                 に書き込む (1 行 = 1 enforcement)。
    5. operator: `python scripts/cron/ingest_offline_inbox.py` で取り込み。

OUTPUT JSON LINES SCHEMA (subagent が遵守):
    {
      "enforcement_id": int,             // am_enforcement_detail.enforcement_id
      "amount_yen": int | null,          // 抽出できた金額 (整数円)
      "amount_kind": "fine" | "grant_refund" | "subsidy_exclude" |
                     "contract_suspend" | "business_improvement" |
                     "license_revoke" | "investigation" | "other" | null,
      "currency": "JPY",                 // 常に JPY (将来 USD 等が出たら修正)
      "clause_quote": str,               // 一次資料からの literal quote
                                          // (照合用、改変禁止)
      "source_url": str,                 // 元の source_url
      "source_fetched_at": str | null,   // ISO8601 UTC
      "confidence": "high" | "med" | "low",
      "subagent_run_id": str,
      "evaluated_at": str                // ISO8601 UTC
    }

INBOX → DB 取り込みの検証要件:
    `scripts/cron/ingest_offline_inbox.py` 側で:
    - clause_quote が source_url の取得済 cache に literal 一致するか
    - amount_yen >= 0
    - currency == "JPY"
    - amount_kind が enum 範囲内
    のチェックを通った行のみを am_enforcement_detail の amount_yen 列に
    UPDATE する。fail は `_quarantine/enforcement_amount/` へ。

Usage:
    python tools/offline/run_enforcement_amount_extract_batch.py \\
        --batch-size 50 --batch-id 2026-05-04-001
    python tools/offline/run_enforcement_amount_extract_batch.py \\
        --batch-size 50 --batch-id 2026-05-04-001 --dry-run

Flags:
    --batch-size N            1 batch あたりの enforcement 件数 (default 50)
    --batch-id STR            trace 用 batch ID
    --autonomath-db PATH      autonomath.db (default: autonomath.db at repo root)
    --max-rows N              本 invocation の上限 (default 500)
    --dry-run                 プロンプト雛形 + list を stdout に
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
INBOX_DIR = Path(__file__).resolve().parent / "_inbox" / "enforcement_amount"
PROMPT_DIR = Path("/tmp")

LOG = logging.getLogger("enforcement_amount_extract_batch")

SUBAGENT_PROMPT_TEMPLATE = """\
# enforcement_amount 抽出ジョブ (subagent 用プロンプト雛形)

## 目的
以下行政処分 list の source_url (PDF / HTML) を取得し、
処分金額 (課徴金 / 返還命令 / 過料 / 等) を構造化抽出する。

## 出力先
`{inbox_path}` に JSON Lines (1 行 = 1 enforcement) で書き込むこと。

## 出力スキーマ (1 行ぶん)
```
{{
  "enforcement_id": int,
  "amount_yen": int | null,
  "amount_kind": "fine" | "grant_refund" | "subsidy_exclude" |
                 "contract_suspend" | "business_improvement" |
                 "license_revoke" | "investigation" | "other" | null,
  "currency": "JPY",
  "clause_quote": "<一次資料からの literal quote、改変禁止>",
  "source_url": "<source_url>",
  "source_fetched_at": "<ISO8601 UTC>" | null,
  "confidence": "high" | "med" | "low",
  "subagent_run_id": "<batch_id>-<seq>",
  "evaluated_at": "<ISO8601 UTC>"
}}
```

## ルール
1. amount_yen は整数円。「100 万円」は 1000000、「1.5 億円」は 150000000。
   範囲表記 ("100-300 万円") は最大値を採用し confidence='med'。
2. clause_quote は原文を literal でコピー。要約・意訳禁止。
3. amount が記載されていない処分は amount_yen=null, confidence='low'
   で 1 行出力 (空行ではなく明示的 null)。
4. 「1 法人あたり最大 X 円」のように上限のみ示す処分は、その上限を
   amount_yen に入れ confidence='med'。
5. 同一 enforcement_id に複数 amount が現れる (例: 過料 + 返還命令) 場合、
   主要処分 1 つを採用し、副次は clause_quote に括弧書きで併記する。

## enforcement list (この batch で処理)
{enforcement_list_json}
"""


def list_target_enforcements(autonomath_db: Path, limit: int) -> list[dict[str, Any]]:
    """amount_yen IS NULL の処分行を SQL から取得 (LLM 呼出なし)."""
    sql = """
        SELECT enforcement_id,
               entity_id,
               houjin_bangou,
               target_name,
               enforcement_kind,
               issuing_authority,
               issuance_date,
               reason_summary,
               source_url,
               source_fetched_at
          FROM am_enforcement_detail
         WHERE amount_yen IS NULL
           AND source_url IS NOT NULL
           AND source_url != ''
         ORDER BY issuance_date DESC, enforcement_id ASC
         LIMIT ?
    """
    conn = sqlite3.connect(autonomath_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def chunk(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def render_subagent_prompt(enforcements: list[dict[str, Any]], inbox_path: Path) -> str:
    enforcement_list_json = json.dumps(enforcements, ensure_ascii=False, indent=2)
    return SUBAGENT_PROMPT_TEMPLATE.format(
        inbox_path=str(inbox_path),
        enforcement_list_json=enforcement_list_json,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--batch-size", type=int, default=50, help="1 batch あたりの enforcement 件数 (default 50)"
    )
    p.add_argument("--batch-id", required=True, help="trace 用 batch ID (e.g. 2026-05-04-001)")
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument(
        "--max-rows", type=int, default=500, help="本 invocation で取り出す row 上限 (default 500)"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="プロンプト雛形と list を stdout に出すのみ"
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    LOG.info("listing am_enforcement_detail rows with amount_yen IS NULL (limit=%d)", args.max_rows)
    enforcements = list_target_enforcements(args.autonomath_db, args.max_rows)
    LOG.info("got %d enforcement rows", len(enforcements))

    today = datetime.now(UTC).strftime("%Y%m%d")
    batch_id = args.batch_id

    n_batches = 0
    for batch_idx, batch_rows in enumerate(chunk(enforcements, args.batch_size)):
        n_batches += 1
        inbox_filename = f"{today}-{batch_id}-batch{batch_idx:03d}.jsonl"
        inbox_path = INBOX_DIR / inbox_filename
        prompt_path = PROMPT_DIR / (f"enforcement_amount_{batch_id}_batch{batch_idx:03d}.md")
        prompt_text = render_subagent_prompt(batch_rows, inbox_path)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        LOG.info(
            "batch %03d: %d enforcements → prompt=%s inbox=%s",
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
        "next step: run a Claude Code subagent on each "
        "/tmp/enforcement_amount_*.md prompt; subagent must write "
        "JSONL to %s, then run scripts/cron/ingest_offline_inbox.py",
        INBOX_DIR,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
