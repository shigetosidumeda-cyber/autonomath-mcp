"""Literal-quote substring verification against operator-side kobo text cache.

W2-13 production caveat #2: the legacy form-only check (length >= 4 +
non-whitespace) accepts strings the subagent invented out of thin air.
Real protection requires a substring match against the original 公募要領
text the subagent quoted from.

CACHE LAYOUT:
    data/kobo_text_cache/{program_unified_id}.txt   UTF-8 plain text

    The operator pre-fetches the 公募要領 / authority page text for each
    target program before running the offline batch (download → strip
    boilerplate → write to file). The runtime cron only READS this
    cache; it never refetches.

CONTRACT:
    literal_quote_pass(quote, program_unified_id) -> bool

    True iff:
      * quote passes form check (non-empty, non-whitespace, len >= 4), AND
      * cache file exists AND `quote in cache_text` is true.

    If the cache file is missing, we LOG a warning and return True (do
    not block ingest). This matches the original spec wording:
    "cache 不在時: warning log + skip (現 fallback)". When the operator
    backfills the cache later, a `--force-retag` re-run can tighten
    the gate.

NO LLM IMPORTS. Pure stdlib + logging.
"""

from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger("jpintel_mcp.ingest.quote_check")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "kobo_text_cache"

# Per-process warning de-dup so a 200-row batch with all-missing cache
# files emits ONE warning, not 200.
_WARNED_MISSING: set[str] = set()


def kobo_text_cache(
    program_unified_id: str,
    cache_dir: Path | None = None,
) -> str | None:
    """Return cached kobo text for `program_unified_id`, or None if absent.

    `cache_dir` override exists for tests; production callers pass None
    and accept the repo-default `data/kobo_text_cache/`.
    """
    if not program_unified_id:
        return None
    base = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
    path = base / f"{program_unified_id}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:  # permission, encoding mismatch, etc.
        LOG.warning("kobo_text_cache read failed for %s: %s", program_unified_id, exc)
        return None


def _form_check(quote: str) -> bool:
    return bool(quote and quote.strip() and len(quote) >= 4)


def literal_quote_pass(
    quote: str,
    program_unified_id: str | None,
    cache_dir: Path | None = None,
) -> bool:
    """Strict literal-quote gate.

    1. Form check: non-empty, non-whitespace, length >= 4.
    2. If cache file exists for `program_unified_id`: require `quote` be
       a literal substring of the cache text.
    3. If cache file missing: warn-once-per-id and accept (form-only
       fallback). Operator can backfill cache + re-ingest with
       `--force-retag` to upgrade the assertion.
    """
    if not _form_check(quote):
        return False
    if not program_unified_id:
        # No id to look up — fall back to form-only.
        return True
    text = kobo_text_cache(program_unified_id, cache_dir=cache_dir)
    if text is None:
        if program_unified_id not in _WARNED_MISSING:
            LOG.warning(
                "kobo_text_cache MISS for %s — accepting form-only "
                "(backfill data/kobo_text_cache/%s.txt + re-run with "
                "--force-retag for strict check)",
                program_unified_id,
                program_unified_id,
            )
            _WARNED_MISSING.add(program_unified_id)
        return True
    return quote in text


__all__ = [
    "DEFAULT_CACHE_DIR",
    "kobo_text_cache",
    "literal_quote_pass",
]
