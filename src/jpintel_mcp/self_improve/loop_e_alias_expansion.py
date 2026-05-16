"""Loop E: language query -> multi-language alias expansion (V4+).

Cadence: weekly (Wednesday 04:00 JST)
Inputs:
    * `query_log_v2` (last 14 days) — production tool calls. The schema
      itself does NOT carry the raw query text (PII boundary, INV-21).
      The miss-query corpus is therefore supplied separately by the
      orchestrator (a redacted log file or an in-memory list); the DB
      surface is used to *count* zero-bucket events and to fetch the
      existing alias / primary_name corpus to dedupe against.
    * `am_alias` (335,605 rows at launch) — already-known surface forms.
    * `jpi_programs.primary_name` (13,578 rows) — canonical anchor strings.

Outputs:
    `data/alias_proposed.yaml` — operator review queue. Operator polishes
    + INSERTs into `am_alias`. NEVER hot-promotes automatically.

Cost ceiling: ~5 CPU minutes / week, ≤ 100k row scans, 0 LLM calls.

Method (T+30d, plain rules-based):
  1. Pull the redacted miss-query corpus (queries that returned 0 results
     last week). The orchestrator is responsible for emitting these to a
     log file with PII redaction already applied (`security.pii_redact`).
     We re-run `redact_text` defensively before any string comparison.
  2. For each miss query, generate two normalized forms via pykakasi
     (hiragana + katakana) so kana/kanji-mixed queries can match
     kana-only aliases.
  3. Walk `jpi_programs.primary_name` + the existing `am_alias.alias`
     corpus. Compute SequenceMatcher ratio (≈Levenshtein) per pair.
     Threshold ≥ 0.85 → candidate alias. Pure stdlib; no external deps.
  4. Skip queries whose closest match is already an exact alias for the
     same canonical_id (no-op proposals add review cost without value).
  5. Write `data/alias_proposed.yaml` shape:
        - alias: <miss_query (redacted)>
          canonical_id: <unified_id>
          primary_name: <jpi_programs.primary_name>
          score: 0.87
          form: original | hira | kana
          confidence: high | medium
     Operator reads, edits, INSERTs into `am_alias` with
     alias_kind='partial' (or 'kana' / 'misc' depending on review).

LLM use: NONE. Pure pykakasi + difflib.SequenceMatcher.

Launch v1 (this module):
    Provides the building blocks (`tokenize_query`, `score_pair`,
    `propose_aliases`, `write_proposals_yaml`) and a `run()` that
    accepts an optional `miss_queries` kwarg for unit tests + a
    `db_path` for the alias / primary_name corpus. When the DB is
    absent (fresh dev) we return the zeroed scaffold dict so the
    orchestrator dashboard stays green pre-launch — same posture as
    loop_a / loop_g.

Cron wiring is intentionally out-of-scope here (handled by
`scripts/self_improve_orchestrator.py`).
"""

from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import yaml  # type: ignore[import-untyped,unused-ignore]
except Exception:  # pragma: no cover - yaml optional at import time
    yaml = None

try:
    import pykakasi
except Exception:  # pragma: no cover - pykakasi optional at import time
    pykakasi = None  # type: ignore[assignment]

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.security.pii_redact import redact_text

if TYPE_CHECKING:
    from collections.abc import Iterable

# Repo layout: src/jpintel_mcp/self_improve/loop_e_alias_expansion.py
# climb four parents to reach the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = Path(
    get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", str(REPO_ROOT / "autonomath.db"))
    or str(REPO_ROOT / "autonomath.db")
)
PROPOSALS_PATH = REPO_ROOT / "data" / "alias_proposed.yaml"

# Similarity thresholds — sniper-claim posture: high precision, low recall.
# 0.85 catches near-misses (typos, kana variants, particle drops) without
# pulling in unrelated kanji-overlap noise the FTS5 trigram tokenizer is
# already known to produce (see CLAUDE.md gotchas).
THRESHOLD_HIGH = 0.92
THRESHOLD_MEDIUM = 0.85

# Cap how many pairs we evaluate per miss query — even with 13.5k programs
# + 335k aliases, the cost ceiling (~5 CPU min / week) keeps this tractable
# at weekly cadence. The cap protects unit tests from doing a 100k pass.
MAX_CANDIDATES_PER_QUERY = 5


@lru_cache(maxsize=1)
def _kakasi() -> Any:
    """Lazy pykakasi handle (single-instance per process, like the slug
    generator in scripts/generate_program_pages.py)."""
    if pykakasi is None:
        return None
    return pykakasi.kakasi()  # type: ignore[no-untyped-call]


def tokenize_query(text: str) -> dict[str, str]:
    """Return the original + hiragana + katakana forms of `text`.

    Pure function. Falls back to {"orig": text, "hira": text, "kana": text}
    if pykakasi is unavailable so the caller can still match on the raw
    surface form in tests / pre-launch environments.

    Always re-runs `redact_text` defensively — a defense-in-depth posture
    against an upstream emitter forgetting to redact.
    """
    safe = redact_text(text or "")
    kks = _kakasi()
    if kks is None or not safe:
        return {"orig": safe, "hira": safe, "kana": safe}
    parts = kks.convert(safe)
    hira = "".join(p.get("hira", "") for p in parts)
    kana = "".join(p.get("kana", "") for p in parts)
    return {"orig": safe, "hira": hira, "kana": kana}


def score_pair(a: str, b: str) -> float:
    """SequenceMatcher ratio in [0, 1]. 1.0 = identical. Pure function."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _load_corpus_from_db(
    db_path: Path,
) -> tuple[list[tuple[str, str]], dict[str, set[str]]]:
    """Load (canonical_id, surface) pairs + the per-canonical alias set.

    Returns:
        anchors: list of (canonical_id, surface) covering both
            jpi_programs.primary_name and am_alias.alias for entity_table
            in ('am_entities',) — the alias table the prod code reads.
        existing: canonical_id -> set of already-known alias surface forms.
            Used to skip no-op proposals (miss query identical to live alias).
    """
    if not db_path.exists():
        return [], {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        anchors: list[tuple[str, str]] = []
        existing: dict[str, set[str]] = {}
        # primary_name anchors (rich canonical strings)
        try:
            cur = conn.execute(
                "SELECT unified_id, primary_name FROM jpi_programs "
                "WHERE excluded=0 AND primary_name IS NOT NULL"
            )
            anchors.extend((cid, name) for cid, name in cur)
        except sqlite3.OperationalError:
            # jpi_programs not present in this DB — caller handles emptiness.
            pass
        # am_alias surface forms keyed by canonical_id (am_entities scope)
        try:
            cur = conn.execute(
                "SELECT canonical_id, alias FROM am_alias WHERE entity_table='am_entities'"
            )
            for cid, alias in cur:
                anchors.append((cid, alias))
                existing.setdefault(cid, set()).add(alias)
        except sqlite3.OperationalError:
            pass
        return anchors, existing
    finally:
        conn.close()


def propose_aliases(
    miss_queries: Iterable[str],
    anchors: list[tuple[str, str]],
    existing: dict[str, set[str]] | None = None,
    *,
    threshold: float = THRESHOLD_MEDIUM,
) -> list[dict[str, Any]]:
    """For each miss query, return up to `MAX_CANDIDATES_PER_QUERY` alias
    candidates whose SequenceMatcher score crosses `threshold`.

    Each proposal dict carries:
        alias         str   -- redacted miss-query surface form
        canonical_id  str   -- best-matching anchor's canonical_id
        primary_name  str   -- the matched anchor surface
        form          str   -- which token form scored highest
        score         float -- SequenceMatcher ratio in [0,1]
        confidence    str   -- high (>=0.92) | medium (>=0.85)

    Pure function: no DB / I/O.
    """
    existing = existing or {}
    proposals: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for raw in miss_queries:
        forms = tokenize_query(raw)
        # Score every (form, anchor) pair, keep best per canonical_id.
        per_canonical: dict[str, dict[str, Any]] = {}
        for cid, surface in anchors:
            best_score = 0.0
            best_form = "orig"
            for form_name, form_text in forms.items():
                s = score_pair(form_text, surface)
                if s > best_score:
                    best_score = s
                    best_form = form_name
            if best_score < threshold:
                continue
            cur = per_canonical.get(cid)
            if cur is None or best_score > cur["score"]:
                per_canonical[cid] = {
                    "score": best_score,
                    "primary_name": surface,
                    "form": best_form,
                }
        # Rank canonical matches by score, take top N.
        ranked = sorted(per_canonical.items(), key=lambda kv: kv[1]["score"], reverse=True)[
            :MAX_CANDIDATES_PER_QUERY
        ]
        for cid, info in ranked:
            alias_text = forms["orig"]
            # Skip if alias already known for this canonical_id.
            if alias_text in existing.get(cid, set()):
                continue
            # Dedupe identical (alias, canonical_id) pairs across miss queries.
            key = (alias_text, cid)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            score = info["score"]
            confidence = "high" if score >= THRESHOLD_HIGH else "medium"
            proposals.append(
                {
                    "alias": alias_text,
                    "canonical_id": cid,
                    "primary_name": info["primary_name"],
                    "form": info["form"],
                    "score": round(score, 4),
                    "confidence": confidence,
                }
            )
    proposals.sort(key=lambda p: p["score"], reverse=True)
    return proposals


def write_proposals_yaml(proposals: list[dict[str, Any]], path: Path) -> int:
    """Write proposals to YAML. Returns bytes written.

    Mirrors loop_g's safe_dump posture so the operator-review pipeline
    treats both files the same way.
    """
    if yaml is None:
        body_lines = ["proposals:"]
        for p in proposals:
            body_lines.append(f"  - alias: {p['alias']!r}")
            body_lines.append(f"    canonical_id: {p['canonical_id']}")
            body_lines.append(f"    primary_name: {p['primary_name']!r}")
            body_lines.append(f"    form: {p['form']}")
            body_lines.append(f"    score: {p['score']}")
            body_lines.append(f"    confidence: {p['confidence']}")
        body = "\n".join(body_lines) + "\n"
    else:
        body = yaml.safe_dump(
            {"proposals": proposals},
            allow_unicode=True,
            sort_keys=False,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return len(body.encode("utf-8"))


def run(
    *,
    dry_run: bool = True,
    miss_queries: list[str] | None = None,
    db_path: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Mine alias candidates from miss queries.

    Args:
        dry_run: When True, do not write `alias_proposed.yaml` — still
            tokenize + score, still report `actions_proposed`. Same
            contract as loop_a / loop_g (NEVER touches `am_alias`).
        miss_queries: Override for the redacted miss-query list. When
            None we return the zeroed scaffold dict — production wiring
            (T+30d) will pull these from a redacted log file the
            orchestrator points at.
        db_path: Override for the DB carrying `am_alias` + `jpi_programs`.
            Defaults to `autonomath.db` at repo root.
        out_path: Override for the proposals YAML output. Defaults to
            `data/alias_proposed.yaml`.

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.
    """
    dbp = db_path if db_path is not None else DEFAULT_DB_PATH
    out_p = out_path if out_path is not None else PROPOSALS_PATH

    if not miss_queries:
        # Pre-launch / empty corpus: keep the orchestrator dashboard green.
        return {
            "loop": "loop_e_alias_expansion",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    anchors, existing = _load_corpus_from_db(dbp)
    if not anchors:
        # DB missing or pre-seed: nothing to compare against. Return
        # a zeroed scaffold (don't flag this as a failure — the loop
        # itself ran cleanly, the corpus just isn't there yet).
        return {
            "loop": "loop_e_alias_expansion",
            "scanned": len(miss_queries),
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    proposals = propose_aliases(miss_queries, anchors, existing)
    actions_executed = 0
    if not dry_run and proposals:
        write_proposals_yaml(proposals, out_p)
        actions_executed = 1

    return {
        "loop": "loop_e_alias_expansion",
        "scanned": len(miss_queries),
        "actions_proposed": len(proposals),
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(dry_run=True)))
