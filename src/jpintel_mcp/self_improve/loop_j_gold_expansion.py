"""Loop J: query_log -> gold.yaml expansion candidates.

Cadence: monthly (20th of month, 09:00 JST)
Inputs:
    * `query_log_v2` (last 30 days, paid + anon) — successful tool
      invocations carry a `tool` label, the literal `tool_args` JSON
      blob, a `top_result_id` (unified_id / case_id / loan_id / ...),
      a `confidence` score in [0,1], and an optional `sentiment` /
      CSAT signal. We mine high-confidence + high-stability rows.
    * `jpi_adoption_records` — when the user query resolves to an
      adoption row whose canonical id is already in the live DB, the
      adoption itself is a SQL-derivable answer. We use it to anchor
      the gold-row's `expected_ids` list (post-launch the orchestrator
      passes a callable that runs the SQL; tests inject a fixture).
    * `evals/gold.yaml` — the existing frozen gold standard. Any
      proposed query that already appears (by `query_text` exact
      match) is silently skipped — gold rows are append-only and we
      never re-propose existing entries.

Outputs:
    `data/tier_a_proposed.yaml` — operator review queue. Each entry:
        - id              short slug derived from the query
          query_text      the natural-language question (PII-redacted)
          tool_name       which MCP tool was used
          tool_args       literal kwargs from the query_log row
          expected_ids    SQL-derived top-K (from adoption_records)
          gold_source_url canonical primary-source URL backing the answer
          confidence      [0,1] mined confidence (>= 0.95 only)
          stability       count of distinct sessions over the window
          recommended     accept | reject_low_confidence | review
          note            why this candidate is interesting
    Operator hand-curates and copies accepted rows into evals/gold.yaml.
    NEVER hot-promotes — gold rows become regression tests forever, so
    every promotion is a deliberate human edit.

Cost ceiling: ~5 CPU minutes / month, ≤ 100k row scans, 0 external API
calls, 0 LLM calls (per `feedback_autonomath_no_api_use`).

Method (launch v1, plain rules-based, NO LLM rewrite):
  1. Filter `query_log_v2` rows to:
        * `confidence >= MIN_CONFIDENCE` (0.95 — the brief mandates a
          high bar because gold rows are forever)
        * `top_result_id` non-empty
        * `sentiment in POSITIVE_SENTIMENTS` (positive | neutral)
          OR `sentiment` missing AND confidence >= 0.97 (uncategorized
          but very high confidence still qualifies)
        * a non-empty `tool` label and a JSON-shaped `tool_args`
  2. Group by (normalized_query_text, tool_name, top_result_id).
     Stability = count of *distinct* session ids in the group.
     Drop any group with stability < MIN_STABILITY (5).
  3. For each surviving group:
        * Look up the SQL-derived expected_ids via the supplied
          `derive_expected_ids` callable (signature:
          `(tool_name, tool_args, top_result_id) -> list[str]`).
          If the callable returns [] we drop the candidate — gold
          requires a verifiable answer.
        * Look up gold_source_url via `derive_source_url`. If empty,
          the candidate is downgraded to `recommended='review'`.
  4. Skip any candidate whose `query_text` already appears in the
     loaded `evals/gold.yaml` (by normalized exact-match).
  5. Redact every emitted query_text through `redact_text` (INV-21).
     Even though `query_log_v2` is supposed to be already redacted by
     the ingest path, we re-run the redactor at proposal time as a
     defence in depth — the cost is sub-millisecond per row and
     gold rows leave the trust boundary the moment they hit
     `data/tier_a_proposed.yaml`.
  6. Emit YAML. Operator reads + manually merges accepted rows into
     evals/gold.yaml.

LLM use: NONE. Pure SQL + Counter + redact_text.

Launch v1 (this module):
    Provides `extract_candidates`, `write_proposals_yaml`, and a
    `run()` that accepts optional `query_log_rows`, `derive_expected_ids`,
    `derive_source_url`, `existing_gold` kwargs so tests can inject
    fixtures without spinning up a real DB. When callers pass nothing,
    `run()` returns the zeroed scaffold — same posture as loop_a /
    loop_b / loop_g.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import yaml  # type: ignore[import-untyped,unused-ignore]
except Exception:  # pragma: no cover - yaml optional at import time
    yaml = None

from jpintel_mcp.security.pii_redact import redact_text

if TYPE_CHECKING:
    from collections.abc import Callable

# Repo layout: src/jpintel_mcp/self_improve/loop_j_gold_expansion.py
# climb four parents to reach repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
PROPOSALS_PATH = REPO_ROOT / "data" / "tier_a_proposed.yaml"
GOLD_PATH = REPO_ROOT / "evals" / "gold.yaml"

# Confidence floor — gold rows are regression tests forever, so we
# only mine high-confidence pairs. The brief mandates >= 0.95.
MIN_CONFIDENCE = 0.95

# Stability — a query must recur in at least N distinct sessions over
# the 30-day window before it is proposal-worthy. Mirrors loop_a's
# DBSCAN min_samples=3 floor but stricter (gold > telemetry).
MIN_STABILITY = 5

# Sentiment buckets that mean "the user did not push back".
POSITIVE_SENTIMENTS = frozenset({"positive", "neutral"})

# Pattern returning a slug — keep ASCII-safe for the YAML id field.
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _normalize_query(text: str) -> str:
    """Trim + collapse whitespace so duplicate queries cluster correctly."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _slug_from(query: str, top_id: str) -> str:
    """Generate a short, stable id slug for the proposal.

    Combines a hash-free prefix from the query (first 6 ASCII tokens)
    with the unified id tail. Pure function — gold rows must have
    deterministic ids so re-runs do not multiply candidates.
    """
    base = _SLUG_RE.sub("-", query.lower())[:32].strip("-")
    if not base:
        base = "q"
    tail = _SLUG_RE.sub("-", str(top_id).lower())[-12:].strip("-")
    return f"j_{base}_{tail}" if tail else f"j_{base}"


def _passes_confidence_gate(row: dict[str, Any]) -> bool:
    """Apply the confidence + sentiment policy from step 1 of the brief."""
    raw_conf = row.get("confidence")
    if raw_conf is None:
        return False
    try:
        conf = float(raw_conf)
    except (TypeError, ValueError):
        return False
    if conf < MIN_CONFIDENCE:
        return False
    sentiment = row.get("sentiment")
    if isinstance(sentiment, str) and sentiment.lower() in POSITIVE_SENTIMENTS:
        return True
    # Uncategorized but very high confidence — still allowed.
    return sentiment is None and conf >= 0.97


def _coerce_args(args: Any) -> dict[str, Any] | None:
    """Return a dict for `tool_args` — accepts JSON string or dict."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def extract_candidates(
    rows: list[dict[str, Any]],
    *,
    derive_expected_ids: Callable[[str, dict[str, Any], str], list[str]] | None = None,
    derive_source_url: Callable[[str, dict[str, Any], str], str | None] | None = None,
    existing_gold_queries: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Cluster query_log rows into gold-expansion candidates.

    Returns a list of candidate dicts sorted by stability desc. Each
    candidate dict carries the keys documented in the module docstring.

    Pure function: no I/O beyond the optional caller-supplied
    `derive_*` callables. Tests inject those to keep the loop hermetic.
    """
    derive_ids = derive_expected_ids or (lambda *_args: [])
    derive_url = derive_source_url or (lambda *_args: None)
    existing = existing_gold_queries or set()

    # Group by (normalized_query, tool, top_result_id).
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "sessions": set(),
            "max_confidence": 0.0,
            "tool_args": None,
            "raw_query": "",
        }
    )

    for r in rows:
        if not isinstance(r, dict):
            continue
        if not _passes_confidence_gate(r):
            continue
        tool = r.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        top_id = r.get("top_result_id")
        if not isinstance(top_id, str) or not top_id.strip():
            continue
        query = _normalize_query(r.get("query_text") or "")
        if not query:
            continue
        args = _coerce_args(r.get("tool_args"))
        if args is None:
            continue
        session = r.get("session_id") or r.get("api_key_hash") or r.get("ip_hash")
        if not isinstance(session, str) or not session.strip():
            continue

        key = (query, tool.strip(), top_id.strip())
        g = groups[key]
        g["sessions"].add(session.strip())
        try:
            raw_conf2 = r.get("confidence")
            if raw_conf2 is not None:
                g["max_confidence"] = max(g["max_confidence"], float(raw_conf2))
        except (TypeError, ValueError):
            pass
        # Keep the *first* observed args dict — query_log already
        # normalises args, so ties in the same group should be
        # functionally equivalent.
        if g["tool_args"] is None:
            g["tool_args"] = args
        if not g["raw_query"]:
            g["raw_query"] = query

    candidates: list[dict[str, Any]] = []
    for (query, tool, top_id), g in groups.items():
        stability = len(g["sessions"])
        if stability < MIN_STABILITY:
            continue
        if query in existing:
            # Already in gold — never re-propose.
            continue

        # Defence-in-depth: redact again at proposal time.
        redacted_query = redact_text(query)

        args = g["tool_args"] or {}
        expected_ids = derive_ids(tool, args, top_id) or []
        if not expected_ids:
            # No SQL-derivable answer — drop the candidate; gold
            # requires a verifiable expected list.
            continue
        source_url = derive_url(tool, args, top_id)

        recommended = "accept" if source_url else "review"

        candidates.append(
            {
                "id": _slug_from(redacted_query, top_id),
                "query_text": redacted_query,
                "tool_name": tool,
                "tool_args": args,
                "expected_ids": list(expected_ids),
                "gold_source_url": source_url,
                "confidence": round(float(g["max_confidence"]), 4),
                "stability": stability,
                "recommended": recommended,
                "note": (
                    f"Mined {stability} distinct sessions at "
                    f"confidence>={MIN_CONFIDENCE}. Operator: verify the "
                    f"top_result_id ({top_id}) is still tier S/A/B and the "
                    f"source URL is a primary government source (no "
                    f"aggregator like noukaweb/hojyokin-portal). Drop into "
                    f"evals/gold.yaml under the appropriate category prefix."
                ),
            }
        )

    candidates.sort(key=lambda c: (-c["stability"], -c["confidence"], c["id"]))
    return candidates


def _load_existing_gold_queries(gold_path: Path) -> set[str]:
    """Return the set of normalized `query_text` values already in gold.yaml.

    Best-effort: missing file or unparseable YAML -> empty set. We must
    not crash the loop if the gold file is moved.
    """
    if yaml is None or not gold_path.exists():
        return set()
    try:
        raw = yaml.safe_load(gold_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    queries = raw.get("queries") or []
    out: set[str] = set()
    for q in queries:
        if not isinstance(q, dict):
            continue
        text = q.get("query_text")
        if isinstance(text, str) and text.strip():
            out.add(_normalize_query(text))
    return out


def write_proposals_yaml(candidates: list[dict[str, Any]], path: Path) -> int:
    """Write candidates as YAML. Returns bytes written.

    Falls back to a hand-rolled emitter if `yaml` is unavailable, same
    posture as loop_b.write_testimonials_yaml / loop_g.write_proposals_yaml.
    """
    if yaml is None:
        body_lines = ["proposals:"]
        for c in candidates:
            body_lines.append(f"  - id: {c['id']}")
            body_lines.append(f"    query_text: {c['query_text']!r}")
            body_lines.append(f"    tool_name: {c['tool_name']}")
            body_lines.append(f"    tool_args: {json.dumps(c['tool_args'], ensure_ascii=False)}")
            body_lines.append("    expected_ids:")
            for eid in c["expected_ids"]:
                body_lines.append(f"      - {eid}")
            body_lines.append(
                f"    gold_source_url: "
                f"{('null' if c['gold_source_url'] is None else c['gold_source_url'])}"
            )
            body_lines.append(f"    confidence: {c['confidence']}")
            body_lines.append(f"    stability: {c['stability']}")
            body_lines.append(f"    recommended: {c['recommended']}")
            body_lines.append(f"    note: {c['note']!r}")
        body = "\n".join(body_lines) + "\n"
    else:
        body = yaml.safe_dump(
            {"proposals": candidates},
            allow_unicode=True,
            sort_keys=False,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return len(body.encode("utf-8"))


def run(
    *,
    dry_run: bool = True,
    query_log_rows: list[dict[str, Any]] | None = None,
    derive_expected_ids: Callable[[str, dict[str, Any], str], list[str]] | None = None,
    derive_source_url: Callable[[str, dict[str, Any], str], str | None] | None = None,
    existing_gold: set[str] | None = None,
    out_path: Path | None = None,
    gold_path: Path | None = None,
) -> dict[str, Any]:
    """Mine high-confidence stable queries as gold expansion candidates.

    Args:
        dry_run: When True, do not write `tier_a_proposed.yaml` — still
            parse + count, still report `actions_proposed`.
        query_log_rows: Optional injection of `query_log_v2` rows. When
            None the function returns the zeroed scaffold (orchestrator
            has not wired the learning DB yet, same posture as loop_b).
        derive_expected_ids: Callable that returns the SQL-derived top-K
            expected unified_ids for a (tool_name, tool_args, top_result_id)
            triple. Required for any actual proposal — without it no
            candidate can carry a verifiable expected list.
        derive_source_url: Callable that returns the canonical
            primary-source URL backing the SQL-derived answer. Optional;
            candidates without a source URL drop to `recommended='review'`.
        existing_gold: Optional set of query_text strings already in
            gold.yaml. When None we read `evals/gold.yaml` from disk.
        out_path: Override for the proposals YAML output. Defaults to
            `data/tier_a_proposed.yaml`.
        gold_path: Override for the existing-gold YAML path. Defaults
            to `evals/gold.yaml`.

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.
    """
    out_p = out_path if out_path is not None else PROPOSALS_PATH
    gold_p = gold_path if gold_path is not None else GOLD_PATH

    if query_log_rows is None:
        # Pre-launch / orchestrator hasn't wired up the learning DB yet —
        # keep the dashboard green. Same posture as loop_b's empty path.
        return {
            "loop": "loop_j_gold_expansion",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    existing = existing_gold if existing_gold is not None else _load_existing_gold_queries(gold_p)

    candidates = extract_candidates(
        query_log_rows,
        derive_expected_ids=derive_expected_ids,
        derive_source_url=derive_source_url,
        existing_gold_queries=existing,
    )

    actions_executed = 0
    if not dry_run and candidates:
        write_proposals_yaml(candidates, out_p)
        actions_executed = 1

    return {
        "loop": "loop_j_gold_expansion",
        "scanned": len(query_log_rows),
        "actions_proposed": len(candidates),
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    print(json.dumps(run(dry_run=True)))
