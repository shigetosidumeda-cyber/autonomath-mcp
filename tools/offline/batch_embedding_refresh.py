#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, scripts/etl/, tests/.
"""Wave 16 F2 — batch embedding refresh driver for jpcite semantic search.

Operator-only offline script. Production runtime (src/) NEVER imports
LLM SDKs (`anthropic` / `openai` / `google.generativeai` /
`claude_agent_sdk`) and NEVER reads `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY`. This driver lives
in `tools/offline/` precisely because it is the one place where local
sentence-transformers inference IS permitted — and even here we use a
local sentence-transformers model (NOT an LLM SDK), because

  * jpcite bills ¥3/req fully metered (税込 ¥3.30). One LLM provider
    call (Anthropic / OpenAI / Gemini) costs ¥0.5–¥5 per embedding.
    Calling them at corpus-refresh time is bearable (operator OPEX);
    calling them from `src/` per request would bankrupt the unit
    economics.
  * `feedback_no_operator_llm_api` (memory entry) further restricts
    even operator scripts: LLM API calls from `tools/offline/` must
    go through `claude_agent_sdk` (which is OUR Claude Code Max
    subscription pre-paid model time, not a per-request meter). For
    DENSE EMBEDDING the better answer is local
    `sentence-transformers` — same model produces deterministic
    vectors with zero per-request cost and zero network dependency.

Scope (the 3 corpora called out in the Wave 16 F2 launch plan):

    +-----------------+--------------------------+----------+
    | corpus          | row count (CLAUDE.md SOT) | vec tier |
    +-----------------+--------------------------+----------+
    | program         |               11,601     | S        |
    | law             |                6,493     | L        |
    | case_study      |                2,286     | C        |
    +-----------------+--------------------------+----------+

Output:
    `am_canonical_vec_<program|law|case_study>` (sqlite-vec virtual
    table) populated via the existing `embed_canonical_entities.py`
    upsert path. Wave 16 F2 reuses the canonical vec families landed
    in migration 166 so the populator is idempotent — re-running this
    driver only embeds canonical_ids that do NOT already have a
    map+vec pair (resume-safe).

Usage:
    # Operator-only. Run from the repo root with the local 312 venv.
    .venv312/bin/python tools/offline/batch_embedding_refresh.py --dry-run
    .venv312/bin/python tools/offline/batch_embedding_refresh.py \\
        --corpora program,law,case_study --max-rows 1000
    .venv312/bin/python tools/offline/batch_embedding_refresh.py
    # Background full refresh (longest path = program at 11.6k rows):
    nohup .venv312/bin/python tools/offline/batch_embedding_refresh.py \\
        > /tmp/batch_embedding_refresh.log 2>&1 &

NO LLM API:
    - This file imports `sentence_transformers` (local model) only.
    - The companion `embed_canonical_entities.py` it delegates to also
      uses `sentence_transformers`; NEITHER imports `anthropic` /
      `openai` / `google.generativeai` / `claude_agent_sdk`.
    - Neither file reads any of `ANTHROPIC_API_KEY` /
      `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY`.
    - CI guard: `tests/test_no_llm_in_production.py` excludes
      `tools/offline/` by path. The guard re-asserts that
      `src/jpintel_mcp/api/semantic_search.py` (the production
      handler) does NOT import any LLM SDK.

Production read-side:
    `src/jpintel_mcp/api/semantic_search.py` exposes
    `POST /v1/semantic_search`. The CLIENT supplies the query
    embedding pre-computed on its side (or, in agent-orchestrated
    flows, the LLM call lives client-side). jpcite simply returns
    cosine-similarity top-k from the vec tables this driver
    populates. The production handler imports `sqlite3` only.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

LOG = logging.getLogger("batch_embedding_refresh")

# Wave 16 F2 corpora — mirror the launch plan exactly.
F2_CORPORA: tuple[str, ...] = ("program", "law", "case_study")

# Default model: matches `embed_canonical_entities.py` so future kNN
# paths can swap between vec families without re-embedding queries.
# multilingual-e5-large is 1024-dim, normalize_embeddings=True.
DEFAULT_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_BATCH = 64


@dataclass
class CorpusReport:
    """One-corpus outcome row for the summary table."""

    corpus: str
    candidate_rows: int = 0
    existing_rows: int = -1
    embedded: int = 0
    skipped_existing: int = 0
    skipped_empty: int = 0
    elapsed_sec: float = 0.0
    dry_run: bool = False
    error: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def _import_embed_module():
    """Import the existing operator-side embedder.

    We delegate the actual `sentence-transformers` work + sqlite-vec
    write-side to `embed_canonical_entities.py` (already operator-only,
    already idempotent). This driver only orchestrates the 3 F2 corpora
    and produces the summary report that the launch plan asks for.

    Local import (NOT at module load) keeps `--dry-run` cheap.
    """
    tools_offline_dir = Path(__file__).resolve().parent
    if str(tools_offline_dir) not in sys.path:
        sys.path.insert(0, str(tools_offline_dir))
    import embed_canonical_entities as embedder

    return embedder


def _run_one_corpus(
    corpus: str,
    autonomath_db: Path,
    batch_size: int,
    max_rows: int | None,
    model_name: str,
    dry_run: bool,
    replace_existing: bool,
) -> CorpusReport:
    """Embed one corpus. Delegates to embed_canonical_entities.run_kind()."""
    rep = CorpusReport(corpus=corpus, dry_run=dry_run)
    t0 = time.time()
    try:
        embedder = _import_embed_module()
    except ImportError as exc:
        rep.error = f"cannot import embed_canonical_entities: {exc}"
        return rep

    spec = embedder.KIND_SPECS.get(corpus)
    if spec is None:
        rep.error = (
            f"unknown corpus {corpus!r}; expected one of "
            f"{sorted(embedder.KIND_SPECS.keys())}"
        )
        return rep

    try:
        sub_report = embedder.run_kind(
            spec=spec,
            autonomath_db=autonomath_db,
            batch_size=batch_size,
            max_rows=max_rows,
            model_name=model_name,
            dry_run=dry_run,
            replace_existing=replace_existing,
        )
    except SystemExit as exc:
        rep.error = f"run_kind aborted: {exc}"
        return rep
    except Exception as exc:  # noqa: BLE001
        rep.error = f"run_kind raised: {exc.__class__.__name__}: {exc}"
        return rep

    rep.candidate_rows = int(sub_report.get("candidate_rows", 0))
    rep.existing_rows = int(sub_report.get("existing_rows", -1))
    rep.embedded = int(sub_report.get("embedded", 0))
    rep.skipped_existing = int(sub_report.get("skipped_existing", 0))
    rep.skipped_empty = int(sub_report.get("skipped_empty", 0))
    rep.elapsed_sec = round(time.time() - t0, 2)
    rep.extra["vec_table"] = sub_report.get("vec_table")
    rep.extra["remaining_rows"] = sub_report.get("remaining_rows")
    return rep


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    p.add_argument(
        "--corpora",
        default=",".join(F2_CORPORA),
        help=(
            "Comma-separated subset of F2_CORPORA to refresh "
            f"(default: {','.join(F2_CORPORA)})."
        ),
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Per-corpus newly-embedded row cap (0 = unlimited).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH,
        help=f"sentence-transformers encode batch (default {DEFAULT_BATCH}).",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Local sentence-transformers model id (default {DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report candidate counts only — NO model load, NO DB write.",
    )
    p.add_argument(
        "--replace-existing",
        action="store_true",
        help=(
            "Re-embed canonical_ids that already have a map+vec pair. "
            "Defaults to resume-safe (skip existing)."
        ),
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    requested = [c.strip() for c in args.corpora.split(",") if c.strip()]
    bad = [c for c in requested if c not in F2_CORPORA]
    if bad:
        LOG.error("unknown corpora %s; allowed=%s", bad, F2_CORPORA)
        return 2
    if not requested:
        LOG.error("no corpora selected")
        return 2

    if not args.autonomath_db.exists():
        LOG.error("autonomath db not found: %s", args.autonomath_db)
        return 2

    max_rows = None if args.max_rows == 0 else args.max_rows
    LOG.info(
        "Wave 16 F2 batch embedding refresh; corpora=%s dry_run=%s replace_existing=%s",
        requested,
        args.dry_run,
        args.replace_existing,
    )

    reports: list[CorpusReport] = []
    for corpus in requested:
        rep = _run_one_corpus(
            corpus=corpus,
            autonomath_db=args.autonomath_db,
            batch_size=args.batch_size,
            max_rows=max_rows,
            model_name=args.model,
            dry_run=args.dry_run,
            replace_existing=args.replace_existing,
        )
        reports.append(rep)
        if rep.error:
            LOG.warning("[%s] error: %s", corpus, rep.error)

    LOG.info("==== Wave 16 F2 refresh summary ====")
    total_embedded = 0
    total_candidate = 0
    fail = 0
    for r in reports:
        if r.error:
            LOG.info("  %-12s ERROR: %s", r.corpus, r.error)
            fail += 1
            continue
        LOG.info(
            "  %-12s candidate=%6d existing=%6d embedded=%6d "
            "skipped_existing=%6d skipped_empty=%5d elapsed=%6.2fs",
            r.corpus,
            r.candidate_rows,
            r.existing_rows,
            r.embedded,
            r.skipped_existing,
            r.skipped_empty,
            r.elapsed_sec,
        )
        total_embedded += r.embedded
        total_candidate += r.candidate_rows
    LOG.info("  TOTAL candidate=%d embedded=%d errors=%d", total_candidate, total_embedded, fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
