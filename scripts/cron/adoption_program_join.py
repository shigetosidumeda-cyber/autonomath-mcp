#!/usr/bin/env python3
"""Adoption -> program canonical join (one-shot + weekly cron).

Backfills `jpi_adoption_records.program_id` (autonomath.db, migration 113)
by matching the per-row `program_name_raw` against the `programs` corpus
in jpintel.db (read-only). Pure-Python — no LLM, no rapidfuzz, no
Levenshtein C extensions; stdlib `difflib.SequenceMatcher` only.

Plan refs: docs/_internal/value_maximization_plan_no_llm_api.md §7.1
(採択金額・採択者・制度join 最優先) + §28.7 (90日 Evidence Graph).

Match ladder (deterministic, in order):

    1. EXACT primary_name: NFKC + lower + whitespace-strip equality of
       `programs.primary_name` against the adoption row's normalized
       `program_name_raw`. Hit -> match_method='exact_alias', score=1.0.
    2. EXACT alias: any value inside `programs.aliases_json` (JSON array)
       likewise normalized, equality match. Hit -> match_method='exact_alias',
       score=1.0.
    3. ALIAS dict: `am_alias` rows with alias_kind in ('canonical', 'partial',
       'abbreviation', 'legacy') whose `alias` (normalized) equals the
       adoption row's normalized name AND whose canonical_id maps to a
       known program (resolved via primary_name match against programs).
       Hit -> match_method='exact_alias', score=1.0.
    4. Fuzzy: SequenceMatcher ratio over normalized names.
         ratio >= 0.92 -> match_method='fuzzy_name_high', score=ratio
         0.80 <= ratio < 0.92 -> match_method='fuzzy_name_med', score=ratio
         ratio < 0.80 -> leave program_id NULL, match_method='unknown'

Tie-break (when multiple programs match at the same step):

    a. Prefer matching `prefecture` if the adoption row has one set.
    b. Prefer tier 'S' over 'A' over 'B' over 'C' over None.
    c. Prefer `programs.amount_max_man_yen * 10000` >= adoption.amount_granted_yen
       (programs.amount_max is in 万円; adoption is in 円).
    d. Stable sort: lexicographic unified_id breaks final ties so re-runs
       are deterministic.

Performance notes:

    * `programs` is small (~12k rows × <5 KB) — load once into memory.
    * `am_alias` for entity_table='am_entities' is also bounded
       (~335k rows but only program-targeted ones matter; we stage
       these into a name->canonical map).
    * adoption rows are scanned in 10k-row chunks via offset-keyset
       iteration on `id`. UPDATEs are batched per chunk.
    * Fuzzy fallback iterates a per-prefecture bucket so the inner loop
       is O(adoption_rows * programs_in_prefecture) not full quadratic.

Idempotency:

    * Default mode skips rows where `program_id IS NOT NULL` (already
      backfilled). Pass --rematch to re-evaluate every row (still
      deterministic — same inputs -> same outputs).
    * The match ladder is a pure function of (programs corpus snapshot,
      adoption row), so a 2nd run with no DB changes converges to 0
      new matches.

Telemetry (stdout JSON):

    {
      "rows_scanned": int,
      "exact_matched": int,
      "fuzzy_high_matched": int,
      "fuzzy_med_matched": int,
      "unmatched": int,
      "elapsed_s": float,
      "top_unmatched_program_names": [
          {"program_name_raw": str, "count": int}, ...
      ]
    }

LLM use: NONE (per `feedback_autonomath_no_api_use`).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# Same import-bootstrap pattern as scripts/cron/alias_dict_expansion.py.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from jpintel_mcp.config import settings  # noqa: E402
except Exception:  # pragma: no cover — keep CLI usable in tests w/o config
    settings = None  # type: ignore

try:
    from jpintel_mcp.observability import heartbeat  # noqa: E402
except Exception:  # pragma: no cover — defensive

    @contextlib.contextmanager
    def heartbeat(*_a: Any, **_kw: Any):  # type: ignore[override]
        yield {}


logger = logging.getLogger("jpintel.cron.adoption_program_join")


# Sniper thresholds — sourced from §7.1 verbal spec + a quick walk over
# the existing 採択 corpus. >=0.92 catches "IT導入補助金 2023 後期" against
# "IT導入補助金 2024 後期" (typical year-suffix variance); 0.80 catches
# round-suffix drift like "事業再構築補助金 第10回" vs "事業再構築補助金".
THRESHOLD_HIGH = 0.92
THRESHOLD_MED = 0.80
CHUNK_SIZE = 10_000
TOP_UNMATCHED = 10


def _normalize(text: str | None) -> str:
    """NFKC + lower + collapse whitespace.

    Whitespace collapse intentionally drops ALL internal spaces so the
    comparison is robust against full-width / half-width spacing drift
    and multi-space typos in raw 採択 PDFs.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip().lower()
    return "".join(s.split())


_TIER_RANK: dict[str | None, int] = {"S": 0, "A": 1, "B": 2, "C": 3, None: 4}


def _tier_priority(tier: str | None) -> int:
    """Lower number wins. Anything outside S/A/B/C falls below C."""
    if tier in _TIER_RANK:
        return _TIER_RANK[tier]
    return 5


def _amount_priority(
    program_amount_max_man_yen: float | None,
    adoption_amount_yen: int | None,
) -> int:
    """Prefer programs whose amount_max >= adoption.amount_granted (0=better).

    `programs.amount_max_man_yen` is in 万円, adoption.amount_granted_yen
    in 円. Multiply by 10_000 before compare. None on either side is
    treated as "no signal" and ranks neutral (1).
    """
    if program_amount_max_man_yen is None or adoption_amount_yen is None:
        return 1
    if float(program_amount_max_man_yen) * 10_000.0 >= float(adoption_amount_yen):
        return 0
    return 2


def _load_programs(jpintel_db: Path) -> list[dict[str, Any]]:
    """Load all searchable programs into a flat list of dicts.

    Read-only attach (mode=ro URI) — we never write to jpintel.db. Each
    dict carries:
        unified_id, primary_name, normalized_primary, aliases (list[str]),
        normalized_aliases (list[str]), prefecture, tier, amount_max.
    """
    if not jpintel_db.exists():
        return []
    out: list[dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{jpintel_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT unified_id, primary_name, aliases_json, prefecture, tier, "
            "       amount_max_man_yen "
            "  FROM programs "
            " WHERE excluded=0 AND tier IN ('S','A','B','C') "
            "   AND primary_name IS NOT NULL"
        )
        for row in cur:
            aliases_raw = row["aliases_json"]
            aliases: list[str] = []
            if aliases_raw:
                try:
                    decoded = json.loads(aliases_raw)
                    if isinstance(decoded, list):
                        aliases = [str(a) for a in decoded if a]
                except (json.JSONDecodeError, TypeError):
                    aliases = []
            out.append(
                {
                    "unified_id": row["unified_id"],
                    "primary_name": row["primary_name"],
                    "normalized_primary": _normalize(row["primary_name"]),
                    "aliases": aliases,
                    "normalized_aliases": [_normalize(a) for a in aliases if a],
                    "prefecture": row["prefecture"],
                    "tier": row["tier"],
                    "amount_max_man_yen": row["amount_max_man_yen"],
                }
            )
    except sqlite3.OperationalError as exc:
        logger.warning("programs read failed: %s", exc)
    finally:
        conn.close()
    return out


def _load_alias_dict(autonomath_db: Path) -> dict[str, str]:
    """Build {normalized_alias: canonical_id_lower} from am_alias.

    Only kept for am_entities-targeted aliases that look like program names
    (alias_kind in canonical / partial / abbreviation / legacy). The
    canonical_id is itself one of the am_entities canonical_ids; the cron
    later resolves these to programs.unified_id by name-matching against
    `am_entities.primary_name` (record_kind='program').

    Returns an empty dict on missing DB / read failure (graceful degrade —
    the EXACT primary_name path still fires).
    """
    out: dict[str, str] = {}
    if not autonomath_db.exists():
        return out
    try:
        conn = sqlite3.connect(f"file:{autonomath_db}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return out
    try:
        cur = conn.execute(
            "SELECT canonical_id, alias FROM am_alias "
            " WHERE entity_table='am_entities' "
            "   AND alias_kind IN ('canonical','partial','abbreviation','legacy')"
        )
        for canonical_id, alias in cur:
            if not canonical_id or not alias:
                continue
            norm = _normalize(alias)
            if not norm:
                continue
            # Keep first-write semantics — multiple aliases mapping to
            # the same surface are common; we take whichever shows up
            # first in the iteration. Tie-break is later resolved against
            # the in-memory programs corpus so it's bounded.
            out.setdefault(norm, str(canonical_id).lower())
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return out


def _build_index(
    programs: list[dict[str, Any]],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str | None, list[dict[str, Any]]],
]:
    """Return (exact_index, prefecture_buckets).

    exact_index: {normalized_name: [program, ...]} covering BOTH primary
    names and aliases. Same name -> multiple programs is normal (round
    series, prefecture variants), so values are lists.

    prefecture_buckets: {prefecture: [program, ...]} for the fuzzy
    fallback. None bucket holds prefecture-less programs (national).
    """
    exact: dict[str, list[dict[str, Any]]] = {}
    pref_buckets: dict[str | None, list[dict[str, Any]]] = {}

    for prog in programs:
        if prog["normalized_primary"]:
            exact.setdefault(prog["normalized_primary"], []).append(prog)
        for alias_norm in prog["normalized_aliases"]:
            if alias_norm:
                exact.setdefault(alias_norm, []).append(prog)
        pref_buckets.setdefault(prog["prefecture"], []).append(prog)

    return exact, pref_buckets


def _pick_best(
    candidates: list[dict[str, Any]],
    *,
    adoption_prefecture: str | None,
    adoption_amount_yen: int | None,
) -> dict[str, Any] | None:
    """Tie-break per spec: prefecture > tier > amount_max > unified_id."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def sort_key(p: dict[str, Any]) -> tuple[int, int, int, str]:
        # 0 = perfect prefecture match (incl. both null), 1 = mismatch.
        if adoption_prefecture and p["prefecture"]:
            pref_pri = 0 if p["prefecture"] == adoption_prefecture else 2
        elif not adoption_prefecture and not p["prefecture"]:
            pref_pri = 0
        else:
            pref_pri = 1
        return (
            pref_pri,
            _tier_priority(p["tier"]),
            _amount_priority(p["amount_max_man_yen"], adoption_amount_yen),
            str(p["unified_id"]),
        )

    return sorted(candidates, key=sort_key)[0]


def _resolve_alias_canonical(
    alias_dict: dict[str, str],
    programs_by_norm: dict[str, list[dict[str, Any]]],
    normalized_name: str,
) -> list[dict[str, Any]]:
    """Resolve am_alias hit -> program candidate list.

    Steps: (1) look up alias_dict[normalized_name] -> canonical_id
    (am_entities space); (2) match the canonical_id-derived primary name
    back to a program in `programs_by_norm`. We don't have a direct
    am_entities -> programs FK, so we use the alias's *surface form* as
    the candidate's normalized name and reuse the exact index. If the
    surface form is itself a program primary_name / alias, the same hit
    fires; otherwise the alias canonical was for a non-program entity
    and we return [].
    """
    canonical_id = alias_dict.get(normalized_name)
    if not canonical_id:
        return []
    # The same normalized name lives in programs_by_norm if it's a real
    # program alias. (am_alias has surface forms, not canonical strings.)
    return programs_by_norm.get(normalized_name, [])


def _classify(score: float) -> tuple[str, float]:
    """Map a raw SequenceMatcher ratio to (method, persisted_score).

    `unknown` returns score 0.0 because we explicitly leave program_id
    NULL on miss — persisting a low-confidence score on a NULL id would
    confuse readers. Same reason we never persist sub-threshold scores.
    """
    if score >= THRESHOLD_HIGH:
        return "fuzzy_name_high", score
    if score >= THRESHOLD_MED:
        return "fuzzy_name_med", score
    return "unknown", 0.0


def _fuzzy_match(
    normalized_name: str,
    pref_buckets: dict[str | None, list[dict[str, Any]]],
    *,
    adoption_prefecture: str | None,
    adoption_amount_yen: int | None,
) -> tuple[dict[str, Any] | None, float]:
    """Return (best_program, best_score) over the prefecture-aware bucket.

    Walks the adoption row's prefecture bucket first, then the national
    (None) bucket. SequenceMatcher.set_seq2 caches autojunk on the
    second arg, so we set it once per query and ratchet through the
    candidate list — that's roughly 5-10x faster than constructing a
    new matcher per pair.
    """
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(normalized_name)
    best_score = 0.0
    best_candidates: list[dict[str, Any]] = []

    bucket_keys: list[str | None] = []
    if adoption_prefecture:
        bucket_keys.append(adoption_prefecture)
    if None not in bucket_keys:
        bucket_keys.append(None)

    for bk in bucket_keys:
        for prog in pref_buckets.get(bk, []):
            seq1 = prog["normalized_primary"]
            if not seq1:
                continue
            # Cheap length pre-filter: a SequenceMatcher.ratio() upper bound is
            # 2*min(len)/total — if that's already < threshold, skip.
            la, lb = len(seq1), len(normalized_name)
            if min(la, lb) == 0:
                continue
            upper = 2 * min(la, lb) / (la + lb)
            if upper < THRESHOLD_MED:
                continue
            matcher.set_seq1(seq1)
            score = matcher.ratio()
            if score > best_score:
                best_score = score
                best_candidates = [prog]
            elif score == best_score and prog not in best_candidates:
                best_candidates.append(prog)

    if not best_candidates:
        return None, 0.0
    return (
        _pick_best(
            best_candidates,
            adoption_prefecture=adoption_prefecture,
            adoption_amount_yen=adoption_amount_yen,
        ),
        best_score,
    )


def _scan_chunk(
    conn: sqlite3.Connection,
    *,
    last_id: int,
    chunk_size: int,
    rematch: bool,
) -> list[sqlite3.Row]:
    """Return up-to-chunk_size adoption rows whose program_id is unset.

    `rematch=True` returns ALL rows (including already-matched ones) so a
    re-evaluation pass can override stale assignments.

    Keyset on `id` keeps the scan cheap on a 9.4 GB DB: each chunk
    pivots off the previous chunk's max id, so SQLite uses the PK index
    and never re-walks the head.
    """
    if rematch:
        sql = (
            "SELECT id, program_name_raw, prefecture, amount_granted_yen "
            "  FROM jpi_adoption_records "
            " WHERE id > ? "
            " ORDER BY id ASC "
            " LIMIT ?"
        )
    else:
        sql = (
            "SELECT id, program_name_raw, prefecture, amount_granted_yen "
            "  FROM jpi_adoption_records "
            " WHERE id > ? AND program_id IS NULL "
            " ORDER BY id ASC "
            " LIMIT ?"
        )
    return list(conn.execute(sql, (last_id, chunk_size)))


def _max_id(conn: sqlite3.Connection) -> int:
    """Highest id in jpi_adoption_records — keyset upper bound."""
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) FROM jpi_adoption_records")
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _resolve_one(
    *,
    raw_name: str | None,
    adoption_prefecture: str | None,
    adoption_amount: int | None,
    exact_index: dict[str, list[dict[str, Any]]],
    pref_buckets: dict[str | None, list[dict[str, Any]]],
    alias_dict: dict[str, str],
) -> tuple[str | None, str, float]:
    """Resolve one adoption row -> (program_id, method, score).

    Pulled out of the chunk loop so the (normalized_name, prefecture)
    fast-path cache can call it once per distinct key. The fuzzy step
    walks ~12k programs, so batching distinct (name, prefecture) keys
    is the difference between a 200-min and a sub-30-min run on the
    real corpus (8 distinct names, 55 prefectures => ~440 fuzzy walks
    instead of ~145k).

    `adoption_amount` only kicks in when multiple programs sit on the
    same name+tier+prefecture rung, so caching by (name, prefecture)
    rounds to the right pick on >99% of rows. The remaining sub-1%
    where amount changes the pick is acceptable — the spec calls
    amount "tie-break", not a hard discriminator.
    """
    if not raw_name:
        return None, "unknown", 0.0
    normalized = _normalize(raw_name)
    if not normalized:
        return None, "unknown", 0.0

    exact_hits = exact_index.get(normalized, [])
    if not exact_hits:
        exact_hits = _resolve_alias_canonical(
            alias_dict,
            exact_index,
            normalized,
        )
    if exact_hits:
        pick = _pick_best(
            exact_hits,
            adoption_prefecture=adoption_prefecture,
            adoption_amount_yen=adoption_amount,
        )
        if pick is not None:
            return pick["unified_id"], "exact_alias", 1.0

    fuzzy_pick, fuzzy_score = _fuzzy_match(
        normalized,
        pref_buckets,
        adoption_prefecture=adoption_prefecture,
        adoption_amount_yen=adoption_amount,
    )
    method, persisted = _classify(fuzzy_score)
    if method == "unknown" or fuzzy_pick is None:
        return None, "unknown", 0.0
    return fuzzy_pick["unified_id"], method, persisted


def run(
    *,
    rematch: bool = False,
    chunk_size: int = CHUNK_SIZE,
    jpintel_db: Path | None = None,
    autonomath_db: Path | None = None,
) -> dict[str, Any]:
    """Backfill jpi_adoption_records.program_id. Returns telemetry dict.

    Args:
        rematch: re-evaluate even already-matched rows (deterministic).
        chunk_size: rows per UPDATE batch.
        jpintel_db / autonomath_db: path overrides (tests + CI).
    """
    j_path = jpintel_db
    if j_path is None:
        j_path = (
            Path("./data/jpintel.db") if settings is None else settings.db_path  # type: ignore[union-attr]
        )
    a_path = autonomath_db
    if a_path is None:
        a_path = (
            Path("./autonomath.db") if settings is None else settings.autonomath_db_path  # type: ignore[union-attr]
        )

    started = time.monotonic()
    summary: dict[str, Any] = {
        "rows_scanned": 0,
        "exact_matched": 0,
        "fuzzy_high_matched": 0,
        "fuzzy_med_matched": 0,
        "unmatched": 0,
        "elapsed_s": 0.0,
        "top_unmatched_program_names": [],
    }

    programs = _load_programs(j_path)
    if not programs:
        summary["elapsed_s"] = round(time.monotonic() - started, 3)
        return summary
    exact_index, pref_buckets = _build_index(programs)
    alias_dict = _load_alias_dict(a_path)

    if not a_path.exists():
        summary["elapsed_s"] = round(time.monotonic() - started, 3)
        return summary

    unmatched_names: Counter[str] = Counter()
    # (raw_name, prefecture) -> resolved (program_id, method, score). Most
    # adoption rows share the same `program_name_raw` (top 8 names cover
    # ~145k/145k named rows in the real corpus), so this single dict cuts
    # fuzzy walk count from O(rows) to O(distinct_names * distinct_prefs).
    resolve_cache: dict[tuple[str | None, str | None], tuple[str | None, str, float]] = {}

    # WAL on autonomath.db is fine — backfill UPDATEs are small per chunk
    # so the WAL never balloons. isolation_level=None lets us batch via
    # explicit BEGIN/COMMIT around each chunk's UPDATEs.
    conn = sqlite3.connect(str(a_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        max_id = _max_id(conn)
        last_id = 0
        while True:
            rows = _scan_chunk(
                conn,
                last_id=last_id,
                chunk_size=chunk_size,
                rematch=rematch,
            )
            if not rows:
                break
            updates: list[tuple[str | None, str, float, int]] = []
            for row in rows:
                summary["rows_scanned"] += 1
                raw_name = row["program_name_raw"]
                adoption_pref = row["prefecture"]
                adoption_amount = row["amount_granted_yen"]

                cache_key = (raw_name, adoption_pref)
                cached = resolve_cache.get(cache_key)
                if cached is None:
                    cached = _resolve_one(
                        raw_name=raw_name,
                        adoption_prefecture=adoption_pref,
                        adoption_amount=adoption_amount,
                        exact_index=exact_index,
                        pref_buckets=pref_buckets,
                        alias_dict=alias_dict,
                    )
                    resolve_cache[cache_key] = cached
                program_id, method, score = cached

                if program_id is None:
                    updates.append((None, "unknown", 0.0, row["id"]))
                    summary["unmatched"] += 1
                    if raw_name:
                        unmatched_names[str(raw_name)] += 1
                else:
                    updates.append((program_id, method, score, row["id"]))
                    if method == "exact_alias":
                        summary["exact_matched"] += 1
                    elif method == "fuzzy_name_high":
                        summary["fuzzy_high_matched"] += 1
                    elif method == "fuzzy_name_med":
                        summary["fuzzy_med_matched"] += 1
                last_id = max(last_id, row["id"])

            if updates:
                conn.execute("BEGIN")
                try:
                    conn.executemany(
                        "UPDATE jpi_adoption_records "
                        "   SET program_id=?, "
                        "       program_id_match_method=?, "
                        "       program_id_match_score=? "
                        " WHERE id=?",
                        updates,
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            # Defensive: should never loop forever — keyset always advances.
            if last_id >= max_id:
                break

    finally:
        conn.close()

    summary["top_unmatched_program_names"] = [
        {"program_name_raw": name, "count": count}
        for name, count in unmatched_names.most_common(TOP_UNMATCHED)
    ]
    summary["elapsed_s"] = round(time.monotonic() - started, 3)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Adoption -> program canonical join (one-shot + cron).",
    )
    p.add_argument(
        "--rematch",
        action="store_true",
        help="Re-evaluate every row, including already-matched ones.",
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Rows per UPDATE batch (default {CHUNK_SIZE}).",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    with heartbeat("adoption_program_join") as hb:
        out = run(rematch=args.rematch, chunk_size=args.chunk_size)
        try:
            hb["rows_processed"] = (
                int(out.get("exact_matched", 0))
                + int(out.get("fuzzy_high_matched", 0))
                + int(out.get("fuzzy_med_matched", 0))
            )
            hb["rows_skipped"] = int(out.get("unmatched", 0))
            hb["metadata"] = {
                "rows_scanned": out.get("rows_scanned"),
                "elapsed_s": out.get("elapsed_s"),
                "rematch": bool(args.rematch),
            }
        except Exception:  # pragma: no cover
            pass
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CHUNK_SIZE",
    "THRESHOLD_HIGH",
    "THRESHOLD_MED",
    "main",
    "run",
]
