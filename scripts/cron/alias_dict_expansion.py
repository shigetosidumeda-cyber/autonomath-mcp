#!/usr/bin/env python3
"""Weekly cron: mine `empty_search_log` for alias candidates.

Reads queries that returned 0 results in the past 7 days, normalizes via
pykakasi (kakasi -> hiragana / romaji), then compares against the existing
alias dictionary (`am_alias` 335,605 rows + `_AUTHORITY_LEVEL_ALIASES` /
`_PREFECTURE_ALIASES` / `_JSIC_ALIASES` in `api/vocab.py`). Levenshtein
within +/- 2 chars OR phonetic match -> candidate alias inserted into
`alias_candidates_queue` (mig 112) for moderation.

Production write 必ず review 後 (Plan §8.7): this cron NEVER writes to
`am_alias`. The only write surface is `python -m jpintel_mcp.loops.alias_review
--approve <id>`, which inspects the queue row and INSERTs into am_alias.

Cadence:
    * Sunday 03:00 JST (Saturday 18:00 UTC) — `.github/workflows/alias-expansion-weekly.yml`
    * Internal lookback window: 7 days

Sources walked:
    * `empty_search_log` (jpintel.db, mig 062) — 0-result queries +
      group-by query for empty_query_count.
    * `am_alias` (autonomath.db) — already-known surface forms; the cron
      skips candidates whose surface form is already an existing alias for
      the same canonical term.
    * `programs.name` (jpintel.db, FTS5-backed) + canonical anchors from
      `_PREFECTURE_ALIASES` / `_AUTHORITY_LEVEL_ALIASES` / `_JSIC_ALIASES`
      — anchor strings to score normalized query against.

LLM use: NONE (per `feedback_autonomath_no_api_use`). Pure pykakasi +
difflib.SequenceMatcher (≈Levenshtein, in stdlib) + plain SQL.

Output:
    * stdout JSON: `{candidates_proposed, scanned, top_5_examples, ...}`
    * `alias_candidates_queue` rows (status='pending') for operator review
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

# Same import-bootstrap pattern as scripts/cron/expire_trials.py so this
# file is runnable as `python scripts/cron/alias_dict_expansion.py` without
# editable-install.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    import pykakasi  # type: ignore
except Exception:  # pragma: no cover — pykakasi optional in test envs
    pykakasi = None  # type: ignore

from jpintel_mcp.api.vocab import (  # noqa: E402
    _AUTHORITY_LEVEL_ALIASES,
    _JSIC_ALIASES,
    _PREFECTURE_ALIASES,
)
from jpintel_mcp.config import settings  # noqa: E402

try:
    from jpintel_mcp.observability import heartbeat  # noqa: E402
except Exception:  # pragma: no cover — defensive
    @contextlib.contextmanager
    def heartbeat(*_a: Any, **_kw: Any):  # type: ignore[override]
        yield {}

logger = logging.getLogger("jpintel.cron.alias_dict_expansion")

# Sniper-claim posture: high precision, low recall. SequenceMatcher ratio
# >= 0.82 is the floor for "near-miss" pairs after kakasi normalization;
# pure char-overlap noise from FTS5 trigram is filtered out by the
# `abs(len(a)-len(b)) <= 2` length gate before scoring.
THRESHOLD = 0.82
LENGTH_DELTA = 2  # ±2 chars Levenshtein-ish bound (per spec)
MIN_EMPTY_COUNT = 2  # query must have >1 empty hits in the window
LOOKBACK_DAYS = 7
MAX_ANCHORS = 12_000  # ceiling on anchor list (program names + alias surfaces)
MAX_CANDIDATES_PER_QUERY = 3
TOP_EXAMPLES = 5


@lru_cache(maxsize=1)
def _kakasi():
    """Lazy single-instance pykakasi handle."""
    if pykakasi is None:
        return None
    return pykakasi.kakasi()


def normalize_query(text: str) -> dict[str, str]:
    """Return {orig, hira, romaji, lower} forms of `text`.

    pykakasi maps kanji+kana -> hiragana ('hira') and Hepburn romaji
    ('hepburn'). The lower-case orig form is used for ASCII alias matches
    (e.g. 'Tokyo' -> 'tokyo' vocab hit).
    """
    safe = (text or "").strip()
    out = {"orig": safe, "hira": safe, "romaji": "", "lower": safe.lower()}
    kks = _kakasi()
    if kks is None or not safe:
        return out
    try:
        parts = kks.convert(safe)
        out["hira"] = "".join(p.get("hira", "") for p in parts)
        out["romaji"] = "".join(p.get("hepburn", "") for p in parts).lower()
    except Exception:  # pragma: no cover — pykakasi shouldn't raise on str
        pass
    return out


def _vocab_anchors() -> list[tuple[str, str]]:
    """(canonical_term, surface_form) anchors from vocab.py constants.

    Each canonical maps to its own surface forms. Includes prefecture
    canonical kanji + romaji + short kanji, JSIC names, authority labels.
    """
    anchors: list[tuple[str, str]] = []
    # Prefecture aliases — value is canonical (e.g. '東京都'), key is alias surface.
    for surface, canonical in _PREFECTURE_ALIASES.items():
        anchors.append((canonical, surface))
    # JSIC aliases — value is canonical letter (A..T), key is alias surface.
    for surface, canonical in _JSIC_ALIASES.items():
        anchors.append((canonical, surface))
    # Authority level aliases — value is canonical (national/prefecture/etc).
    for surface, canonical in _AUTHORITY_LEVEL_ALIASES.items():
        anchors.append((canonical, surface))
    return anchors


def _load_program_anchors(jpintel_db: Path) -> list[tuple[str, str]]:
    """Load program names from jpintel.db as canonical anchors."""
    if not jpintel_db.exists():
        return []
    anchors: list[tuple[str, str]] = []
    conn = sqlite3.connect(f"file:{jpintel_db}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT unified_id, primary_name FROM programs "
            "WHERE excluded=0 AND tier IN ('S','A','B','C') "
            "AND primary_name IS NOT NULL "
            "ORDER BY unified_id "
            "LIMIT ?",
            (MAX_ANCHORS,),
        )
        for pid, name in cur:
            anchors.append((str(pid), name))
    except sqlite3.OperationalError as exc:
        logger.warning("program anchors: %s", exc)
    finally:
        conn.close()
    return anchors


def _load_existing_aliases(autonomath_db: Path) -> set[tuple[str, str]]:
    """Return set of (canonical_term_lower, alias_lower) already in am_alias.

    The lower-case form lets us de-dupe against case-only variants without
    inflating the queue. An empty set on missing DB is fine — the cron then
    proposes everything that crosses the threshold (operator filters).
    """
    out: set[tuple[str, str]] = set()
    if not autonomath_db.exists():
        return out
    try:
        conn = sqlite3.connect(f"file:{autonomath_db}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return out
    try:
        cur = conn.execute("SELECT canonical_id, alias FROM am_alias")
        for cid, alias in cur:
            if cid is None or alias is None:
                continue
            out.add((str(cid).lower(), str(alias).lower()))
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return out


def _load_empty_queries(
    jpintel_db: Path,
    *,
    days: int = LOOKBACK_DAYS,
    min_count: int = MIN_EMPTY_COUNT,
    now: datetime | None = None,
) -> list[tuple[str, int, str, str]]:
    """Return [(query, count, first_seen, last_seen), ...] for the window.

    Only queries with `count >= min_count` are surfaced — single-shot empty
    queries are too noisy to spend operator review time on.
    """
    if not jpintel_db.exists():
        return []
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    rows: list[tuple[str, int, str, str]] = []
    conn = sqlite3.connect(f"file:{jpintel_db}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            """SELECT query,
                      COUNT(*) AS c,
                      MIN(created_at) AS first_seen,
                      MAX(created_at) AS last_seen
                 FROM empty_search_log
                WHERE created_at >= ?
                  AND length(trim(query)) >= 2
                GROUP BY query
               HAVING c >= ?
                ORDER BY c DESC""",
            (cutoff_iso, int(min_count)),
        )
        rows = [(q, int(c), fs, ls) for (q, c, fs, ls) in cur]
    except sqlite3.OperationalError as exc:
        logger.warning("empty_search_log read failed: %s", exc)
    finally:
        conn.close()
    return rows


def _score_pair(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _length_bounded(a: str, b: str, *, delta: int = LENGTH_DELTA) -> bool:
    """Cheap pre-filter: skip pairs whose length differs by more than ±delta.

    Approximates Levenshtein bound — an edit distance of N requires the
    string lengths to differ by at most N. Combined with SequenceMatcher
    above the THRESHOLD, this captures "near-miss" typos / kana variants
    without pulling in unrelated single-kanji overlap noise.
    """
    return abs(len(a) - len(b)) <= delta


def _phonetic_match(forms_a: dict[str, str], surface_b: str) -> bool:
    """True if normalized hira / romaji of A matches surface B.

    Match types (in order):
      1. Exact equality (after lowercase) on any form of A vs surface B.
      2. Surface B is contained as a substring in any form of A — but
         only when the surface is ASCII-free (kanji / kana) and >=2 chars,
         OR ASCII >=3 chars. This avoids 'dejitaruka' romaji noise picking
         up 'IT' from `_JSIC_ALIASES`.
      3. Any form of A is contained in surface B — same length / charset
         guards, in reverse direction.

    The asymmetric ASCII guard is deliberate. Kanji / kana surfaces
    embed cleanly ('農業' inside '農業 のうぎょう'); ASCII <=2 alias
    keys ('IT', 'DX') are too short to substring-match against romaji
    output without noise.
    """
    if not surface_b:
        return False
    sb = surface_b.lower().strip()
    if not sb:
        return False
    sb_is_ascii = sb.isascii()
    # Length floor: kanji/kana >=2, ASCII >=3.
    sb_min = 3 if sb_is_ascii else 2
    if len(sb) < sb_min:
        return False
    for form_text in (forms_a.get("orig"), forms_a.get("hira"),
                      forms_a.get("romaji"), forms_a.get("lower")):
        if not form_text:
            continue
        ft = form_text.lower()
        if ft == sb:
            return True
        # Substring containment — both directions.
        if sb in ft or ft in sb:
            return True
    return False


def _propose_for_query(
    query: str,
    forms: dict[str, str],
    anchors: list[tuple[str, str]],
    existing: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Return top-N candidates for a single query."""
    candidates: list[dict[str, Any]] = []
    seen_canonicals: set[str] = set()
    for canonical, surface in anchors:
        if canonical in seen_canonicals:
            # Already proposed for this canonical (multiple alias surfaces
            # may map to the same canonical) — keep first hit.
            continue
        # Phonetic shortcut — exact hira / romaji match scores 1.0.
        if _phonetic_match(forms, surface):
            score = 1.0
        else:
            # Check all four normalized forms; take the best.
            best = 0.0
            for form_text in (forms.get("orig"), forms.get("hira"),
                              forms.get("romaji"), forms.get("lower")):
                if not form_text:
                    continue
                if not _length_bounded(form_text, surface):
                    continue
                s = _score_pair(form_text, surface)
                if s > best:
                    best = s
            score = best
        if score < THRESHOLD:
            continue
        # Skip if the proposal is already a known alias (case-insensitive).
        if (str(canonical).lower(), query.lower()) in existing:
            continue
        seen_canonicals.add(canonical)
        candidates.append(
            {
                "canonical_term": canonical,
                "match_score": round(score, 4),
                "matched_surface": surface,
            }
        )
    candidates.sort(key=lambda c: c["match_score"], reverse=True)
    return candidates[:MAX_CANDIDATES_PER_QUERY]


def _upsert_candidate(
    conn: sqlite3.Connection,
    *,
    candidate_alias: str,
    canonical_term: str,
    match_score: float,
    empty_query_count: int,
    first_seen: str,
    last_seen: str,
) -> str:
    """INSERT-or-bump a candidate. Returns 'inserted' / 'bumped' / 'skipped'.

    `bumped` updates last_seen + empty_query_count + match_score on a row
    that's still pending. Approved/rejected rows are left alone — operator
    decisions are sticky across cron runs.
    """
    cur = conn.execute(
        "SELECT id, status, empty_query_count, match_score "
        "FROM alias_candidates_queue "
        "WHERE candidate_alias=? AND canonical_term=?",
        (candidate_alias, canonical_term),
    )
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO alias_candidates_queue("
            "  candidate_alias, canonical_term, match_score, "
            "  empty_query_count, first_seen, last_seen, status"
            ") VALUES (?,?,?,?,?,?, 'pending')",
            (
                candidate_alias,
                canonical_term,
                match_score,
                empty_query_count,
                first_seen,
                last_seen,
            ),
        )
        return "inserted"
    rid, status, prior_count, prior_score = row
    if status != "pending":
        return "skipped"
    new_score = max(float(prior_score or 0.0), float(match_score))
    new_count = max(int(prior_count or 0), int(empty_query_count))
    conn.execute(
        "UPDATE alias_candidates_queue "
        "SET last_seen=?, empty_query_count=?, match_score=? "
        "WHERE id=?",
        (last_seen, new_count, new_score, rid),
    )
    return "bumped"


def run(
    *,
    dry_run: bool = False,
    days: int = LOOKBACK_DAYS,
    min_count: int = MIN_EMPTY_COUNT,
    jpintel_db: Path | None = None,
    autonomath_db: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mine empty_search_log + emit candidates to alias_candidates_queue.

    Args:
        dry_run: when True, score and report but never INSERT into the queue.
        days / min_count: lookback window + frequency floor.
        jpintel_db / autonomath_db: path overrides (tests).
        now: clock override (tests).

    Returns dict: {candidates_proposed, candidates_inserted,
    candidates_bumped, candidates_skipped, scanned_queries, top_5_examples,
    dry_run, lookback_days}.
    """
    j_path = jpintel_db if jpintel_db is not None else settings.db_path
    a_path = autonomath_db if autonomath_db is not None else settings.autonomath_db_path

    queries = _load_empty_queries(
        j_path, days=days, min_count=min_count, now=now,
    )
    summary: dict[str, Any] = {
        "scanned_queries": len(queries),
        "candidates_proposed": 0,
        "candidates_inserted": 0,
        "candidates_bumped": 0,
        "candidates_skipped": 0,
        "top_5_examples": [],
        "dry_run": bool(dry_run),
        "lookback_days": days,
    }
    if not queries:
        return summary

    anchors = _vocab_anchors() + _load_program_anchors(j_path)
    existing = _load_existing_aliases(a_path)

    # Open the queue DB (jpintel.db) once, reuse across queries.
    conn = sqlite3.connect(j_path, isolation_level=None)
    try:
        # Belt-and-suspenders: tests may pass a fresh DB without the table.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS alias_candidates_queue (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  candidate_alias TEXT NOT NULL,
                  canonical_term TEXT NOT NULL,
                  match_score REAL NOT NULL,
                  empty_query_count INTEGER NOT NULL,
                  first_seen TIMESTAMP NOT NULL,
                  last_seen TIMESTAMP NOT NULL,
                  status TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                  reviewed_at TIMESTAMP,
                  reviewer TEXT,
                  UNIQUE(candidate_alias, canonical_term)
              )"""
        )
        examples: list[dict[str, Any]] = []
        for query, qcount, first_seen, last_seen in queries:
            forms = normalize_query(query)
            cands = _propose_for_query(query, forms, anchors, existing)
            if not cands:
                continue
            summary["candidates_proposed"] += len(cands)
            for c in cands:
                if not dry_run:
                    op = _upsert_candidate(
                        conn,
                        candidate_alias=query,
                        canonical_term=str(c["canonical_term"]),
                        match_score=float(c["match_score"]),
                        empty_query_count=int(qcount),
                        first_seen=str(first_seen or ""),
                        last_seen=str(last_seen or ""),
                    )
                    if op == "inserted":
                        summary["candidates_inserted"] += 1
                    elif op == "bumped":
                        summary["candidates_bumped"] += 1
                    else:
                        summary["candidates_skipped"] += 1
                if len(examples) < TOP_EXAMPLES:
                    examples.append({
                        "query": query,
                        "canonical_term": c["canonical_term"],
                        "match_score": c["match_score"],
                        "matched_surface": c["matched_surface"],
                        "empty_query_count": qcount,
                    })
        summary["top_5_examples"] = examples
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Weekly alias dictionary auto-extension cron.",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Score + report but never INSERT into the queue.")
    p.add_argument("--days", type=int, default=LOOKBACK_DAYS,
                   help=f"Lookback window (default {LOOKBACK_DAYS}).")
    p.add_argument("--min-count", type=int, default=MIN_EMPTY_COUNT,
                   help="Min empty-hit count to surface a query (default 2).")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    with heartbeat("alias_dict_expansion") as hb:
        out = run(dry_run=args.dry_run, days=args.days,
                  min_count=args.min_count)
        try:
            hb["rows_processed"] = int(out.get("candidates_inserted", 0)) + \
                int(out.get("candidates_bumped", 0))
            hb["rows_skipped"] = int(out.get("candidates_skipped", 0))
            hb["metadata"] = {
                "scanned_queries": out.get("scanned_queries"),
                "candidates_proposed": out.get("candidates_proposed"),
                "lookback_days": args.days,
                "dry_run": bool(args.dry_run),
            }
        except Exception:  # pragma: no cover
            pass
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "LOOKBACK_DAYS",
    "MIN_EMPTY_COUNT",
    "THRESHOLD",
    "main",
    "normalize_query",
    "run",
]
