#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""am_program_eligibility_predicate batch driver — 要件述語の結晶化.

PURPOSE (W1-9 / migration wave24_137_am_program_eligibility_predicate):
    各 program の公募要領から eligibility 述語 (capital_max / employee_max /
    jsic_in / region_in / invoice_required / business_age_min_years 等) を
    Claude Code subagent に構造化抽出させる helper。Wave 21 の
    apply_eligibility_chain_am と Wave 22 の bundle_application_kit が
    この crystallized 表を読む。
    本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_extract_eligibility_predicates_batch.py
                  --batch_id 1 --batch_size 200 --dry-run`
    2. 本 script: programs (tier S/A/B/C) のうち am_program_eligibility_predicate
                  に未登録の program を SELECT、subagent 用 prompt + schema を出す。
    3. operator: Claude Code subagent → JSONL →
                 tools/offline/_inbox/eligibility_predicates/.
    4. operator: ingest_offline_inbox.py が UNIQUE 制約で
                 INSERT OR IGNORE → am_program_eligibility_predicate。

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

from jpintel_mcp.ingest.schemas.eligibility_predicate import (
    EligibilityPredicateBatchRow,
)

TOOL_SLUG = "eligibility_predicates"

SQL_PROGRAMS = """
    SELECT unified_id,
           primary_name,
           authority_name,
           authority_level,
           prefecture,
           program_kind,
           target_types_json,
           crop_categories_json,
           funding_purpose_json,
           amount_max_man_yen,
           source_url,
           official_url
      FROM programs
     WHERE excluded = 0
       AND tier IN ('S','A','B','C')
       AND COALESCE(source_url, official_url) IS NOT NULL
       AND COALESCE(source_url, official_url) != ''
     ORDER BY tier ASC, unified_id ASC
"""

SQL_DONE_UIDS = """
    SELECT DISTINCT program_unified_id FROM am_program_eligibility_predicate
"""

RULES = [
    "公募要領を読んで eligibility predicate を 1 row = 1 (kind × operator × value) として抽出。",
    "predicate_kind は enum 16 種から選ぶ。該当無しは 'other' を使い、"
    "value_text に自由記述で記載。",
    "operator は enum 10 種から (=, !=, <, <=, >, >=, IN, NOT_IN, CONTAINS, EXISTS)。",
    "数値は value_num に (例: 資本金 3000 万円以下 → kind=capital_max, op='<=', value_num=30000000)。",
    "テキストは value_text に。複数値は value_json に JSON 配列で。",
    "is_required は 1=必須要件 / 0=任意・優遇。判別不能なら 1。",
    "source_clause_quote は公募要領からの literal-quote (改変禁止)。",
    "source_url は公募要領 URL を必ず入れる。",
    "1 batch row = 1 program、predicates は配列。要件不明 program は predicates=[]。",
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


def list_pending(jpintel_db: str, autonomath_db: str, limit: int) -> list[dict]:
    programs = query_rows(jpintel_db, SQL_PROGRAMS)
    done = {r["program_unified_id"] for r in query_rows(autonomath_db, SQL_DONE_UIDS)}
    out: list[dict] = []
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
    schema = EligibilityPredicateBatchRow.model_json_schema()
    emit(
        tool_slug=TOOL_SLUG,
        batch_id=args.batch_id,
        rows=rows,
        schema_title="EligibilityPredicateBatchRow",
        schema_json=schema,
        title="am_program_eligibility_predicate batch",
        purpose=(
            "programs (tier S/A/B/C) のうち am_program_eligibility_predicate に "
            "未登録の program に対し、公募要領から要件述語を結晶化抽出する。"
        ),
        rules=RULES,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
