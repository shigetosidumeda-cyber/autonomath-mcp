"""Tier B - DB-derived synthetic 220 questions.

10 SQL templates x ~22 sampled rows. Ground truth IS the SQL result by
construction; any tool/gold divergence is a wire-up bug.

Run: ``python -m tests.eval.tier_b_template > tier_b_generated.jsonl``
Re-run nightly to catch DB drift. Seeded RNG so output is stable.

4 of 10 templates wired (T1-T4). T5-T10 stubbed - implementer fills in
during P2.3.x. Each stub = 1 SQL + 1 question template + tool name (~30 min).
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
SEED_DB = REPO_ROOT / "tests" / "eval" / "fixtures" / "seed.db"


def _resolve(prod: Path) -> Path:
    if SEED_DB.exists() and os.environ.get("EVAL_USE_SEED", "0") == "1":
        return SEED_DB
    return prod


# (template_id, db_path, sql, n_max, tool, arg_field, gold_field, question_template)
TEMPLATES: list[tuple[str, Path, str, int, str, str, str, str]] = [
    (
        "T1_round_close",
        AUTONOMATH_DB,
        """SELECT round_label, application_close_date FROM am_application_round
           WHERE application_close_date IS NOT NULL
             AND application_close_date >= '2024-01-01'
           ORDER BY round_id LIMIT 50""",
        50,
        "search_acceptance_stats_am",
        "round_label",
        "application_close_date",
        "{round_label} の公募締切日は?",
    ),
    (
        "T2_program_max_amount",
        JPINTEL_DB,
        """SELECT primary_name, amount_max_man_yen FROM programs
           WHERE tier IN ('S','A') AND amount_max_man_yen IS NOT NULL
             AND excluded = 0
           ORDER BY unified_id LIMIT 40""",
        40,
        "search_gx_programs_am",
        "primary_name",
        "amount_max_man_yen",
        "{primary_name} の上限額(万円)は?",
    ),
    (
        "T3_tax_ruleset_until",
        AUTONOMATH_DB,
        """SELECT ruleset_name, effective_until FROM jpi_tax_rulesets
           WHERE effective_until IS NOT NULL""",
        20,
        "get_am_tax_rule",
        "ruleset_name",
        "effective_until",
        "{ruleset_name} の終了日は?",
    ),
    (
        "T4_law_article_exists",
        AUTONOMATH_DB,
        """SELECT law_canonical_id, article_number FROM am_law_article
           WHERE text_summary IS NOT NULL
           ORDER BY article_id LIMIT 30""",
        30,
        "get_law_article_am",
        "law_canonical_id",
        "article_number",
        "{law_canonical_id} 第{article_number}条の条文は存在するか?",
    ),
    # ── Stubs (TODO: P2.3.x implementer wires SQL + tool args) ──
    # T5_supreme_court_date (jpi_court_decisions, 20)
    # T6_prefecture_top_subsidy (programs WHERE prefecture IS NOT NULL, 20)
    # T7_invoice_registrant_lookup (jpi_invoice_registrants by houjin_bangou, 20)
    # T8_tier_s_program_authority (programs WHERE tier='S', 20)
    # T9_adoption_avg_amount (jpi_adoption_records GROUP BY round, 10)
    # T10_law_article_count_by_law (am_law_article GROUP BY law_canonical_id, 10)
]


def generate(seed: int = 42) -> list[dict[str, Any]]:
    random.seed(seed)
    out: list[dict[str, Any]] = []
    for tpl_id, db_path, sql, n, tool, arg_field, gold_field, q_tpl in TEMPLATES:
        resolved = _resolve(db_path)
        if not resolved.exists():
            continue
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = list(conn.execute(sql))
        except sqlite3.OperationalError:
            conn.close()
            continue
        conn.close()
        if len(rows) > n:
            rows = random.sample(rows, n)
        for i, r in enumerate(rows):
            d = dict(r)
            try:
                question = q_tpl.format(**d)
            except KeyError:
                continue
            out.append(
                {
                    "id": f"TB{tpl_id}_{i:03d}",
                    "template": tpl_id,
                    "question": question,
                    "tool": tool,
                    "arguments": {arg_field: d[arg_field]},
                    "gold_field": gold_field,
                    "gold_value": d[gold_field],
                }
            )
    return out


if __name__ == "__main__":
    for q in generate():
        print(json.dumps(q, ensure_ascii=False))
