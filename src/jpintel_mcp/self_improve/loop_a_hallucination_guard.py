"""Loop A: customer feedback -> hallucination_guard expansion.

Cadence: weekly (Monday 09:30 JST, after the digest)
Inputs: `customer_feedback`, `query_log_v2` (zero-result + low-confidence),
        existing `hallucination_guard` table (60 rows at launch v1)
Outputs: candidate negative-pattern rows appended to
        `hallucination_guard_candidates` for operator review; promoted on next
        run with `dry_run=False` -> `hallucination_guard` (target 1,500+ rows
        within 6 months post-launch).
Cost ceiling: ~5 CPU minutes / week, ≤ 50k DB row scans, 0 external API calls.

Method (T+30d):
  1. Pull last 7 days of customer_feedback rows where flag='wrong_answer' or
     'made_up_program'.
  2. Embed feedback text with local e5-small (already baked into image at
     /models/e5-small/) — do NOT call any LLM.
  3. DBSCAN cluster (eps=0.18, min_samples=3); each cluster -> 1 candidate
     pattern. Cluster medoid string is the surface form.
  4. Append (pattern_text, cluster_size, sample_query_ids) to
     `hallucination_guard_candidates` with `status='pending_review'`.

LLM use: NONE. Local e5-small only.

Launch v1 (this module): YAML-backed in-memory matcher seeded from
`data/hallucination_guard.yaml` (60 entries, 5 audience × 6 vertical × 2
phrase). The response sanitizer in `src/jpintel_mcp/api/safety.py` calls
`match()` to flag high-severity surface-form mentions in generated answers.
`run()` itself is the weekly proposal job; for launch v1 it loads + counts
the YAML so the orchestrator dashboard reports a non-zero `scanned`.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped,unused-ignore]
except Exception:  # pragma: no cover - yaml is optional at import-time
    yaml = None  # type: ignore[assignment,unused-ignore]

# data/hallucination_guard.yaml lives at repo root; this file lives at
# src/jpintel_mcp/self_improve/loop_a_hallucination_guard.py — climb four
# parents to reach repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_PATH = REPO_ROOT / "data" / "hallucination_guard.yaml"

ALLOWED_SEVERITY = {"high", "medium", "low"}
ALLOWED_AUDIENCE = {"税理士", "行政書士", "SMB", "VC", "Dev"}
ALLOWED_VERTICAL = {"補助金", "税制", "融資", "認定", "行政処分", "法令"}


@lru_cache(maxsize=1)
def _load() -> list[dict[str, Any]]:
    """Load and validate the launch-v1 YAML. Cached for the process lifetime.

    Returns an empty list (no exception) if the file or yaml module is
    missing — the orchestrator should not fail on launch even if the data
    asset is not yet shipped to the runtime image.
    """
    if yaml is None or not DATA_PATH.exists():
        return []
    raw = yaml.safe_load(DATA_PATH.read_text(encoding="utf-8")) or {}
    entries = raw.get("entries") or []
    out: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        # Required: phrase, severity, correction, audience, vertical
        if not all(k in e for k in ("phrase", "severity", "correction", "audience", "vertical")):
            continue
        if e["severity"] not in ALLOWED_SEVERITY:
            continue
        if e["audience"] not in ALLOWED_AUDIENCE:
            continue
        if e["vertical"] not in ALLOWED_VERTICAL:
            continue
        out.append(e)
    return out


def match(text: str) -> list[dict[str, Any]]:
    """Return all hallucination_guard entries whose `phrase` appears in `text`.

    Substring match (case-sensitive, full-width preserved). Used by the
    response sanitizer to flag high-severity mentions for either correction
    insertion or refuse-to-answer behaviour.

    Pure function: no DB write, no network. Safe to call per-request.
    """
    if not text:
        return []
    hits: list[dict[str, Any]] = []
    for e in _load():
        if e["phrase"] in text:
            hits.append(e)
    return hits


def summarize() -> dict[str, Any]:
    """Return launch-v1 dataset summary (counts by severity / audience / vertical)."""
    entries = _load()
    sev = Counter(e["severity"] for e in entries)
    aud = Counter(e["audience"] for e in entries)
    vert = Counter(e["vertical"] for e in entries)
    return {
        "total": len(entries),
        "by_severity": dict(sev),
        "by_audience": dict(aud),
        "by_vertical": dict(vert),
        "data_path": str(DATA_PATH),
    }


def run(*, dry_run: bool = True) -> dict[str, Any]:
    """Scan feedback and propose hallucination_guard rows.

    Launch v1: report the seeded YAML row count as `scanned`. Real
    DBSCAN-on-feedback wiring lands at T+30d once query_log_v2 has enough
    volume.

    NEVER writes to the DB. The `dry_run=False` branch will only be
    activated post-T+30d, and even then writes go to
    `hallucination_guard_candidates` (operator review queue), never
    directly to `hallucination_guard`.
    """
    entries = _load()
    return {
        "loop": "loop_a_hallucination_guard",
        "scanned": len(entries),
        "actions_proposed": 0,
        "actions_executed": 0,
    }


def _cli() -> int:
    """Operator CLI: `python -m jpintel_mcp.self_improve.loop_a_hallucination_guard ...`.

    Modes:
      --check "<text>"  -> print matched entries (phrase / severity / correction
                          / law_basis / audience / vertical) for the given text.
                          Returns 1 if any high-severity match, else 0.
      (no args)         -> print the launch-v1 dataset summary (same as before).
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="loop_a_hallucination_guard",
        description="Loop A hallucination_guard CLI (operator pattern probe).",
    )
    parser.add_argument(
        "--check",
        metavar="TEXT",
        help="Substring-match TEXT against the YAML cache; print matched entries.",
    )
    args = parser.parse_args()

    if args.check is not None:
        hits = match(args.check)
        print(
            json.dumps(
                {
                    "input": args.check,
                    "match_count": len(hits),
                    "hits": hits,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if any(h.get("severity") == "high" for h in hits) else 0

    print(
        json.dumps(
            {"run": run(dry_run=True), "summary": summarize()},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_cli())
