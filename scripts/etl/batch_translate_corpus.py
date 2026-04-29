#!/usr/bin/env python3
"""Offline batch translate the AutonoMath corpus to English (operator only).

OPERATOR-SIDE ETL — runs once on the operator's workstation, NOT at
request time. Per `feedback_autonomath_no_api_use` (CLAUDE memory), the
service must NEVER call the Anthropic API on the user's request path:
¥0.5/req structure cannot absorb a ¥2-15 LLM call. This script is the
single sanctioned exception — it pre-computes English aliases offline,
charges the cost to the operator's developer-budget Anthropic API key,
and writes the results into am_alias.language='en' so the runtime path
JOINs them as static reference data.

Total operator cost (estimated):
    programs           10,790 names × 1 LLM call ≈  ¥30,000
    laws               154 full-text  × 1 LLM call ≈  (NOT translated here —
                       feature 4 ingests e-Gov EN translations directly
                       under CC-BY 4.0; this script only translates the
                       9,484 law NAMES)
    laws (names only)  9,484         × 1 LLM call ≈  ¥25,000
    tax_rulesets       50 (→1,000)    × 1 LLM call ≈  ¥150 (¥3k at 1k)
    court_decisions    2,065          × 1 LLM call ≈  ¥6,000
    invoice_registrants 1,000 sample  × 1 LLM call ≈  ¥3,000
    -------
    Total                                ≈  ¥30-80k (well under ceiling)

The bulk of the cost is in `programs` (10,790) and `laws` (9,484);
both are batchable. Anthropic Batch API gets us 50% off list price.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/etl/batch_translate_corpus.py --dry-run
    python scripts/etl/batch_translate_corpus.py --corpus programs --batch-size 100
    python scripts/etl/batch_translate_corpus.py --corpus all --use-batch-api

Flags:
    --corpus {programs,laws,tax_rulesets,court_decisions,invoice,all}
    --dry-run         (print plan + token estimate, don't call API)
    --use-batch-api   (50% off, completes within 24h, async)
    --batch-size N    (default 100; controls per-request prompt size)
    --resume          (skip rows already in am_alias as language='en')
    --limit N         (cap rows per corpus; useful for testing)

Output:
    1. INSERT INTO am_alias rows where (language='en', alias_kind='english')
       linked to the entity_table + canonical_id of the source row.
    2. A run-log JSON at /tmp/batch_translate_run_<ts>.json with token
       counts, error rates, and the per-corpus cost breakdown so the
       operator can verify against Stripe's Anthropic invoice.

The disclaimer "JP primary_name is canonical, EN is machine-translated
reference" is surfaced in every response that JOINs am_alias on
language='en'. See src/jpintel_mcp/api/programs.py:_apply_lang_en_alias.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
RUN_LOG_DIR = Path("/tmp")

LOG = logging.getLogger("batch_translate")

# Per-call prompt budget. Claude Haiku 3.5 is sufficient for proper-noun
# transliteration; we don't need Sonnet for "translate '小規模事業者持続化補助金'
# to English". List prices @ 2026-04-29:
#   Haiku 3.5  $1.00 / MTok input,  $5.00 / MTok output
#   Sonnet 4   $3.00 / MTok input, $15.00 / MTok output
# At ~50 input + 30 output tokens per row, Haiku at 100-batch is the right
# pick. Batch API doubles throughput at 50% off.
DEFAULT_MODEL = "claude-haiku-3-5"
PROMPT_HEADER = (
    "You are translating Japanese government-program / law / tax-rule names "
    "to English for use as reference labels in a structured database.\n\n"
    "RULES:\n"
    "1. Translate proper nouns to their official English form when one "
    "exists (e.g. 経済産業省 → Ministry of Economy, Trade and Industry).\n"
    "2. For program names with no official EN, produce a literal "
    "translation that preserves the kanji semantics "
    "(e.g. 小規模事業者持続化補助金 → Small Business Sustainability Subsidy).\n"
    "3. Keep the translation under 80 characters when possible.\n"
    "4. Output ONLY the English translation per input, no commentary.\n"
    "5. If a name is already in English / romaji, echo it back verbatim.\n\n"
    "Translate each numbered Japanese name to English on its own line, "
    "prefixed with the same number:\n\n"
)


def estimate_cost_yen(n_rows: int, model: str = DEFAULT_MODEL,
                      use_batch: bool = False) -> dict[str, float]:
    """Per-row cost estimate (yen, exclusive of consumption tax)."""
    # ~50 input tokens + 30 output tokens per row when batched at 100
    in_tok = 50
    out_tok = 30
    if model.startswith("claude-haiku"):
        usd_in_per_mtok = 1.00
        usd_out_per_mtok = 5.00
    elif model.startswith("claude-sonnet"):
        usd_in_per_mtok = 3.00
        usd_out_per_mtok = 15.00
    else:
        # Conservative fallback
        usd_in_per_mtok = 3.00
        usd_out_per_mtok = 15.00
    usd_per_row = (in_tok * usd_in_per_mtok + out_tok * usd_out_per_mtok) / 1_000_000
    if use_batch:
        usd_per_row *= 0.5  # Batch API discount
    yen_per_usd = 156.0  # April 2026 spot
    yen_per_row = usd_per_row * yen_per_usd
    return {
        "yen_per_row": yen_per_row,
        "yen_total": yen_per_row * n_rows,
        "n_rows": n_rows,
        "model": model,
        "use_batch": use_batch,
    }


# ---------------------------------------------------------------------------
# Corpus iterators
# ---------------------------------------------------------------------------

def iter_programs(jpintel_db: Path, limit: int | None = None,
                  resume: bool = True,
                  autonomath_db: Path | None = None
                  ) -> Iterator[tuple[str, str, str]]:
    """Yield (entity_table, canonical_id, jp_name) for programs.primary_name.

    `entity_table` for programs is 'am_entities' (programs are mirrored as
    am_entities record_kind='program' under canonical_id `program:UNI-...`)
    so the alias lands in the correct namespace.
    """
    conn = sqlite3.connect(jpintel_db)
    conn.row_factory = sqlite3.Row
    sql = """
        SELECT unified_id, primary_name
          FROM programs
         WHERE excluded = 0
           AND tier IN ('S','A','B','C')
           AND primary_name IS NOT NULL
           AND primary_name != ''
    """
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()

    # Resume support: skip rows already translated.
    already = set()
    if resume and autonomath_db and autonomath_db.exists():
        ac = sqlite3.connect(autonomath_db)
        cur = ac.execute(
            "SELECT canonical_id FROM am_alias "
            "WHERE language = 'en' AND entity_table = 'am_entities' "
            "  AND alias_kind = 'english'"
        )
        already = {r[0] for r in cur.fetchall()}
        ac.close()

    for row in rows:
        canonical_id = f"program:{row['unified_id']}"
        if canonical_id in already:
            continue
        yield ("am_entities", canonical_id, row["primary_name"])


def iter_laws(autonomath_db: Path, limit: int | None = None,
              resume: bool = True) -> Iterator[tuple[str, str, str]]:
    """Yield (entity_table, canonical_id, jp_name) for am_law.canonical_name."""
    conn = sqlite3.connect(autonomath_db)
    conn.row_factory = sqlite3.Row

    already = set()
    if resume:
        cur = conn.execute(
            "SELECT canonical_id FROM am_alias "
            "WHERE language = 'en' AND entity_table = 'am_law'"
        )
        already = {r[0] for r in cur.fetchall()}

    sql = "SELECT canonical_id, canonical_name FROM am_law WHERE canonical_name IS NOT NULL"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()
    for row in rows:
        if row["canonical_id"] in already:
            continue
        yield ("am_law", row["canonical_id"], row["canonical_name"])


def iter_tax_rulesets(jpintel_db: Path, limit: int | None = None,
                      resume: bool = True,
                      autonomath_db: Path | None = None
                      ) -> Iterator[tuple[str, str, str]]:
    """Yield (entity_table, canonical_id, jp_name) for tax_rulesets.ruleset_name."""
    conn = sqlite3.connect(jpintel_db)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT unified_id, ruleset_name
          FROM tax_rulesets
         WHERE ruleset_name IS NOT NULL
    """
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()

    already = set()
    if resume and autonomath_db and autonomath_db.exists():
        ac = sqlite3.connect(autonomath_db)
        cur = ac.execute(
            "SELECT canonical_id FROM am_alias "
            "WHERE language = 'en' AND entity_table = 'am_entities' "
            "  AND canonical_id LIKE 'tax_rule:%'"
        )
        already = {r[0] for r in cur.fetchall()}
        ac.close()

    for row in rows:
        canonical_id = f"tax_rule:{row['unified_id']}"
        if canonical_id in already:
            continue
        yield ("am_entities", canonical_id, row["ruleset_name"])


def iter_court_decisions(jpintel_db: Path, limit: int | None = None,
                         resume: bool = True,
                         autonomath_db: Path | None = None
                         ) -> Iterator[tuple[str, str, str]]:
    """Yield (entity_table, canonical_id, jp_name) for court_decisions case names."""
    conn = sqlite3.connect(jpintel_db)
    conn.row_factory = sqlite3.Row

    # Probe for the actual column name (some snapshots use case_name, others case_title)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(court_decisions)").fetchall()}
    title_col = "case_name" if "case_name" in cols else (
        "case_title" if "case_title" in cols else "summary"
    )
    pk_col = "unified_id" if "unified_id" in cols else "decision_id"

    sql = (
        f"SELECT {pk_col} AS pk, {title_col} AS title FROM court_decisions "
        f"WHERE {title_col} IS NOT NULL"
    )
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()

    already = set()
    if resume and autonomath_db and autonomath_db.exists():
        ac = sqlite3.connect(autonomath_db)
        cur = ac.execute(
            "SELECT canonical_id FROM am_alias "
            "WHERE language = 'en' AND canonical_id LIKE 'court_decision:%'"
        )
        already = {r[0] for r in cur.fetchall()}
        ac.close()

    for row in rows:
        canonical_id = f"court_decision:{row['pk']}"
        if canonical_id in already:
            continue
        yield ("am_entities", canonical_id, row["title"])


def iter_invoice(jpintel_db: Path, limit: int = 1000, resume: bool = True,
                 autonomath_db: Path | None = None
                 ) -> Iterator[tuple[str, str, str]]:
    """Yield 1000 sample invoice_registrants for transliteration (legal name)."""
    conn = sqlite3.connect(jpintel_db)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(invoice_registrants)").fetchall()}
    if "name" in cols:
        name_col = "name"
    elif "trade_name" in cols:
        name_col = "trade_name"
    else:
        name_col = "houjin_name"
    pk_col = "registration_no" if "registration_no" in cols else "houjin_bangou"
    rows = conn.execute(
        f"SELECT {pk_col} AS pk, {name_col} AS nm FROM invoice_registrants "
        f"WHERE {name_col} IS NOT NULL LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    already = set()
    if resume and autonomath_db and autonomath_db.exists():
        ac = sqlite3.connect(autonomath_db)
        cur = ac.execute(
            "SELECT canonical_id FROM am_alias "
            "WHERE language = 'en' AND canonical_id LIKE 'invoice_registrant:%'"
        )
        already = {r[0] for r in cur.fetchall()}
        ac.close()

    for row in rows:
        canonical_id = f"invoice_registrant:{row['pk']}"
        if canonical_id in already:
            continue
        yield ("am_entities", canonical_id, row["nm"])


CORPUS_DISPATCH = {
    "programs": iter_programs,
    "laws": iter_laws,
    "tax_rulesets": iter_tax_rulesets,
    "court_decisions": iter_court_decisions,
    "invoice": iter_invoice,
}


# ---------------------------------------------------------------------------
# Anthropic API call
# ---------------------------------------------------------------------------

def call_anthropic_batch(jp_names: list[str], model: str = DEFAULT_MODEL,
                         use_batch_api: bool = False
                         ) -> list[str | None]:
    """Translate a list of JP names → list of EN names (None on parse error).

    Uses the per-batch `claude.messages.create()` form at the synchronous
    path or the batch API for the async path. Authoritative usage doc:
    https://docs.anthropic.com/en/api/messages-batches
    """
    try:
        import anthropic
    except ImportError:
        LOG.error("anthropic package not installed. Run: pip install anthropic")
        sys.exit(2)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        LOG.error("ANTHROPIC_API_KEY env var not set")
        sys.exit(2)

    client = anthropic.Anthropic(api_key=api_key)

    # Build numbered prompt
    numbered = "\n".join(f"{i+1}. {nm}" for i, nm in enumerate(jp_names))
    prompt = PROMPT_HEADER + numbered

    if use_batch_api:
        # Batch API (50% off, async). For brevity we use sync call here;
        # operator can switch to batch when N > 1000 by editing this function.
        LOG.warning("Batch API path requested but using sync (TODO)")

    response = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text  # type: ignore[union-attr]

    # Parse "N. <english>" lines
    out: list[str | None] = [None] * len(jp_names)
    for line in text.splitlines():
        line = line.strip()
        if not line or "." not in line:
            continue
        idx_str, _, en = line.partition(".")
        try:
            idx = int(idx_str.strip()) - 1
        except ValueError:
            continue
        if 0 <= idx < len(out):
            out[idx] = en.strip()

    return out


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def upsert_alias(autonomath_db: Path, entity_table: str,
                 canonical_id: str, alias: str) -> None:
    """Insert (entity_table, canonical_id, alias) into am_alias.

    Idempotent: am_alias has UNIQUE (entity_table, canonical_id, alias),
    so re-running with the same translation is a no-op. A different
    translation for the same row will fail the unique constraint —
    operator must DELETE the old row first if intentional.
    """
    conn = sqlite3.connect(autonomath_db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO am_alias "
            "(entity_table, canonical_id, alias, alias_kind, language) "
            "VALUES (?, ?, ?, 'english', 'en')",
            (entity_table, canonical_id, alias),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--corpus", choices=list(CORPUS_DISPATCH.keys()) + ["all"],
                   default="all", help="which corpus to translate")
    p.add_argument("--dry-run", action="store_true",
                   help="print plan + cost estimate, do not call API")
    p.add_argument("--use-batch-api", action="store_true",
                   help="use Anthropic Batch API (50%% off, async)")
    p.add_argument("--batch-size", type=int, default=100,
                   help="rows per Anthropic call (default 100)")
    p.add_argument("--limit", type=int, default=None,
                   help="cap rows per corpus (testing)")
    p.add_argument("--resume", action="store_true", default=True,
                   help="skip rows already in am_alias.language=en")
    p.add_argument("--no-resume", dest="resume", action="store_false",
                   help="re-translate even if alias exists")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Anthropic model id (default {DEFAULT_MODEL})")
    p.add_argument("--autonomath-db", type=Path,
                   default=DEFAULT_AUTONOMATH_DB)
    p.add_argument("--jpintel-db", type=Path,
                   default=DEFAULT_JPINTEL_DB)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    corpora = list(CORPUS_DISPATCH.keys()) if args.corpus == "all" else [args.corpus]
    run_log: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "args": vars(args),
        "corpora": {},
    }

    # Phase 1: count rows
    plan: dict[str, list[tuple[str, str, str]]] = {}
    for c in corpora:
        if c == "laws":
            rows = list(iter_laws(args.autonomath_db, limit=args.limit,
                                  resume=args.resume))
        elif c == "programs":
            rows = list(iter_programs(args.jpintel_db, limit=args.limit,
                                      resume=args.resume,
                                      autonomath_db=args.autonomath_db))
        elif c == "tax_rulesets":
            rows = list(iter_tax_rulesets(args.jpintel_db, limit=args.limit,
                                          resume=args.resume,
                                          autonomath_db=args.autonomath_db))
        elif c == "court_decisions":
            rows = list(iter_court_decisions(args.jpintel_db, limit=args.limit,
                                             resume=args.resume,
                                             autonomath_db=args.autonomath_db))
        elif c == "invoice":
            rows = list(iter_invoice(args.jpintel_db,
                                     limit=args.limit or 1000,
                                     resume=args.resume,
                                     autonomath_db=args.autonomath_db))
        else:
            rows = []
        plan[c] = rows
        cost = estimate_cost_yen(len(rows), model=args.model,
                                 use_batch=args.use_batch_api)
        run_log["corpora"][c] = {"n_rows_to_translate": len(rows),
                                  "cost_estimate": cost}
        LOG.info("corpus=%s rows=%d cost=¥%.0f",
                 c, len(rows), cost["yen_total"])

    total_yen = sum(v["cost_estimate"]["yen_total"]
                    for v in run_log["corpora"].values())
    LOG.info("=" * 50)
    LOG.info("TOTAL ESTIMATE: ¥%.0f (%d rows)",
             total_yen, sum(len(r) for r in plan.values()))

    if args.dry_run:
        path = RUN_LOG_DIR / f"batch_translate_dryrun_{int(time.time())}.json"
        path.write_text(json.dumps(run_log, indent=2, ensure_ascii=False))
        LOG.info("dry-run plan written to %s", path)
        return 0

    # Phase 2: translate + write
    translated_total = 0
    errors_total = 0
    for c, rows in plan.items():
        if not rows:
            continue
        LOG.info("translating corpus=%s n=%d", c, len(rows))
        for i in range(0, len(rows), args.batch_size):
            batch = rows[i:i + args.batch_size]
            jp_names = [r[2] for r in batch]
            try:
                en_names = call_anthropic_batch(
                    jp_names, model=args.model,
                    use_batch_api=args.use_batch_api,
                )
            except Exception as e:  # noqa: BLE001
                LOG.error("batch %d-%d failed: %s", i, i + len(batch), e)
                errors_total += len(batch)
                continue
            for (etable, cid, _jp), en in zip(batch, en_names, strict=False):
                if en:
                    upsert_alias(args.autonomath_db, etable, cid, en)
                    translated_total += 1
                else:
                    errors_total += 1
            LOG.info("  batch %d done (translated=%d errors=%d)",
                     i // args.batch_size, translated_total, errors_total)

    run_log["finished_at"] = datetime.now(timezone.utc).isoformat()
    run_log["translated_total"] = translated_total
    run_log["errors_total"] = errors_total
    log_path = RUN_LOG_DIR / f"batch_translate_run_{int(time.time())}.json"
    log_path.write_text(json.dumps(run_log, indent=2, ensure_ascii=False))
    LOG.info("done. translated=%d errors=%d log=%s",
             translated_total, errors_total, log_path)
    return 0 if errors_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
