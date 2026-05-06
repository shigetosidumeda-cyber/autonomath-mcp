#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""am_program_documents batch driver — 申請書類 list 抽出 (extract_application_documents).

PURPOSE (migration wave24_138_am_program_documents):
    `am_program_documents` に未登録の program について公募要領 / 様式 page から
    必要書類 (申請書 / 計画書 / 見積書 / 登記簿 / 納税証明 / 財務諸表 / 同意書 / その他)
    を Claude Code subagent に構造化抽出させる helper。
    本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_app_documents_batch.py
                  --batch_id 1 --batch_size 200 --dry-run`
    2. 本 script: programs (tier S/A/B/C) ⨝ am_program_documents の補集合を
                  SELECT、subagent 用 prompt + schema を出す。
    3. operator: Claude Code subagent → JSONL →
                 tools/offline/_inbox/program_application_documents/.
    4. operator: ingest_offline_inbox.py が UNIQUE (program, doc_name, yoshiki_no)
                 で INSERT OR IGNORE。

NO LLM IMPORT.
"""
from __future__ import annotations

import argparse
import sys

from _runner_common import (
    DEFAULT_AUTONOMATH_DB,
    DEFAULT_JPINTEL_DB,
    emit,
    query_rows,
)

from jpintel_mcp.ingest.schemas.program_documents import ProgramDocumentsRow


TOOL_SLUG = "program_application_documents"

SQL_PROGRAMS = """
    SELECT unified_id,
           primary_name,
           authority_name,
           prefecture,
           program_kind,
           source_url,
           official_url,
           amount_max_man_yen
      FROM programs
     WHERE excluded = 0
       AND tier IN ('S','A','B','C')
       AND COALESCE(source_url, official_url) IS NOT NULL
       AND COALESCE(source_url, official_url) != ''
     ORDER BY tier ASC, unified_id ASC
"""

SQL_DONE_PROGRAM_UIDS = """
    SELECT DISTINCT program_unified_id FROM am_program_documents
"""

RULES = [
    "公募要領 / 様式 page を読み、必要な書類を 1 row = 1 文書として返す。",
    "doc_kind は enum (申請書/計画書/見積書/登記簿/納税証明/財務諸表/同意書/その他) のいずれか。"
    "判断つかない場合は null。",
    "yoshiki_no は様式番号 (e.g. '様式第1号') があれば必ず入れる。同名 doc が様式番号違いで複数ある場合は別 row。",
    "is_required は 1=必須 / 0=任意。判別不能なら 1 を default。",
    "url は様式の直接 download URL がある場合のみ入れる。",
    "source_clause_quote は公募要領からの literal-quote (改変禁止)。",
    "1 batch row = 1 program、documents は配列。program に書類記載がない場合 documents=[]。",
    "subagent_run_id = '{batch_id}-{seq}'。extracted_at / evaluated_at は ISO8601 UTC。",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--batch_id", type=int, required=True)
    p.add_argument("--batch_size", type=int, default=200)
    p.add_argument("--jpintel-db", default=str(DEFAULT_JPINTEL_DB))
    p.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def list_pending(
    jpintel_db: str, autonomath_db: str, limit: int
) -> list[dict]:
    programs = query_rows(jpintel_db, SQL_PROGRAMS)
    done = {r["program_unified_id"] for r in query_rows(autonomath_db, SQL_DONE_PROGRAM_UIDS)}
    out = []
    for p in programs:
        if p["unified_id"] in done:
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    args = parse_args()
    rows = list_pending(args.jpintel_db, args.autonomath_db, args.batch_size)
    schema = ProgramDocumentsRow.model_json_schema()
    emit(
        tool_slug=TOOL_SLUG,
        batch_id=args.batch_id,
        rows=rows,
        schema_title="ProgramDocumentsRow",
        schema_json=schema,
        title="am_program_documents batch (extract_application_documents)",
        purpose=(
            "programs (tier S/A/B/C) の中で am_program_documents に未登録の program に対し、"
            "公募要領から必要書類リストを抽出する。"
        ),
        rules=RULES,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
