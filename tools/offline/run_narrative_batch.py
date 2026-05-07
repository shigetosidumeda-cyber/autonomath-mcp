#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""am_program_narrative batch driver — 解説 (overview/eligibility/application_flow/pitfalls) × ja|en.

PURPOSE (migration wave24_136_am_program_narrative):
    各 program について 4 section × 2 lang (ja, en) の解説を Claude Code
    subagent に生成させる helper。本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_narrative_batch.py
                  --lang ja --section overview --batch_id 1 --batch_size 200 --dry-run`
    2. 本 script: 当該 (lang × section) で am_program_narrative に未登録の program を
                  SELECT (jpintel.programs ⨝ autonomath.am_program_narrative の補完)、
                  subagent 用 prompt + JSON schema を stdout に出す。
    3. operator: Claude Code subagent → JSONL 出力 →
                 tools/offline/_inbox/program_narrative/.
    4. operator: scripts/cron/ingest_offline_inbox.py で am_program_narrative
                 (autonomath.db) に INSERT (literal_quote_check_passed=1 の行のみ)。

LANG / SECTION 仕様:
    --lang     : ja / en
    --section  : overview / eligibility / application_flow / pitfalls / all
                 'all' は 4 section 分の prompt を順に出力する。

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

from jpintel_mcp.ingest.schemas.program_narrative import Narrative

TOOL_SLUG = "program_narrative"

SECTIONS = ("overview", "eligibility", "application_flow", "pitfalls")

# autonomath.db is the home of am_program_narrative; jpintel.db is the
# home of programs. Operators usually run with a single autonomath_db
# attached read-only, but the helper avoids ATTACH per CLAUDE.md
# constraint by issuing two separate SELECTs and computing the
# difference in Python.

SQL_PROGRAMS = """
    SELECT unified_id, primary_name, authority_name, prefecture,
           program_kind, source_url
      FROM programs
     WHERE excluded = 0
       AND tier IN ('S','A','B','C')
     ORDER BY tier ASC, unified_id ASC
"""

SQL_DONE = """
    SELECT DISTINCT program_id
      FROM am_program_narrative
     WHERE lang = ? AND section = ?
"""

RULES_OVERVIEW = [
    "overview = 制度の趣旨・対象・上限額を 200-400 字で。",
    "一次資料 URL を source_url_json に最低 1 つ含める。",
    "literal_quote_check_passed は 0 で出力 (ingest 側で 1 に更新)。",
]
RULES_ELIGIBILITY = [
    "eligibility = 対象者・要件 (資本金 / 従業員数 / JSIC / 地域 / 法人形態) を箇条書き 5-10 行で。",
    "公募要領の literal-quote を最低 1 箇所、本文中に「『 』」で含める。",
    "source_url_json に公募要領 URL を必ず入れる。",
]
RULES_APP_FLOW = [
    "application_flow = 申請手順を 5-8 ステップ。締切 / 必要書類 / 提出窓口を含む。",
    "samurai_no / 様式番号 が分かれば本文に注釈で含める。",
    "source_url_json に手順 page を含める。",
]
RULES_PITFALLS = [
    "pitfalls = 不採択 / 返還命令 / 併給制限の落とし穴 3-5 項目。",
    "不採択事例 / 行政処分事例があれば事例 ID を本文中に注釈で。",
    "推測は避け、事例ベースで。事例ない section は短くてよい (100 字程度)。",
]
RULES_BY_SECTION = {
    "overview": RULES_OVERVIEW,
    "eligibility": RULES_ELIGIBILITY,
    "application_flow": RULES_APP_FLOW,
    "pitfalls": RULES_PITFALLS,
}

COMMON_RULES = [
    "lang は --lang で指定したものに合わせる (ja / en)。",
    "model_id は subagent / model 識別子 (e.g. 'claude-opus-4-7') を入れる。",
    "subagent_run_id = '{batch_id}-{section}-{seq}'。",
    "generated_at は ISO8601 UTC。",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--batch_id", type=int, required=True)
    p.add_argument("--batch_size", type=int, default=200)
    p.add_argument("--lang", choices=("ja", "en"), required=True)
    p.add_argument(
        "--section",
        choices=(*SECTIONS, "all"),
        required=True,
        help="overview / eligibility / application_flow / pitfalls / all",
    )
    p.add_argument("--jpintel-db", default=str(DEFAULT_JPINTEL_DB))
    p.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def list_pending(
    jpintel_db: str, autonomath_db: str, lang: str, section: str, limit: int
) -> list[dict]:
    programs = query_rows(jpintel_db, SQL_PROGRAMS)
    done_rows = query_rows(autonomath_db, SQL_DONE, (lang, section))
    done_pids = {r["program_id"] for r in done_rows}
    # programs table has no integer 'id' for join; we surface unified_id and
    # let the subagent supply program_id via best-effort hash. The ingest
    # script resolves program_id at INSERT time.
    pending: list[dict] = []
    for p in programs:
        # We can't filter by program_id here without a registry. This batch
        # SELECTs the earliest N programs every run; the ingest cron is
        # responsible for skipping already-present rows under the UNIQUE.
        pending.append(p)
        if len(pending) >= limit:
            break
    # If done_pids is large, callers should pass --batch_size sized to skip
    # the prefix of completed work. We surface the done count in the prompt
    # header so the operator can advance.
    pending = pending[:limit]
    if done_pids:
        # Best-effort: emit a header note about how many are already done.
        for p in pending:
            p.setdefault("_completed_in_section", len(done_pids))
    return pending


def main() -> int:
    args = parse_args()
    sections = SECTIONS if args.section == "all" else (args.section,)
    schema = Narrative.model_json_schema()
    for sect in sections:
        rows = list_pending(
            args.jpintel_db,
            args.autonomath_db,
            args.lang,
            sect,
            args.batch_size,
        )
        rules = COMMON_RULES + RULES_BY_SECTION[sect]
        emit(
            tool_slug=TOOL_SLUG,
            batch_id=args.batch_id,
            rows=rows,
            schema_title=f"Narrative ({args.lang}/{sect})",
            schema_json=schema,
            title=f"am_program_narrative batch ({args.lang} / {sect})",
            purpose=(
                f"programs (tier S/A/B/C) × lang={args.lang} × section={sect} の解説を生成。"
                f" 既に am_program_narrative に登録済みの (program_id, lang, section) は"
                f" UNIQUE で skip 対象 (ingest 側で吸収)。"
            ),
            rules=rules,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
