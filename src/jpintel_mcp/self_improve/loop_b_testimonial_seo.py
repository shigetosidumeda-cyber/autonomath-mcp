"""Loop B: customer success -> testimonial -> SEO/GEO copy.

Cadence: monthly (1st of month, 10:00 JST)
Inputs:
    * `query_log_v2` rows (Wave 9 #1) — successful tool invocations carry
      `result_bucket='hit'` (or `result_bucket='success'`) plus a `tool`
      label and a status_code in 2xx. The combination is our "hit_pattern":
      a customer-driven query that was answered without falling into a
      zero-result / low-confidence bucket.
    * Optional customer rating signal — a list of dicts shaped like
      `{api_key_hash, rating, comment, tool}` collected from the post-
      response CSAT widget. Rating is 1-5; comment is free-text and MUST
      be PII-redacted before any persistence (INV-21 + APPI § 31).

Outputs:
    `data/testimonials_proposed.yaml` — operator review queue. Operator
    polishes + manually copies high-quality entries into landing-page
    copy (`site/index.html` testimonial block) and structured-data JSON-LD
    (`Review` schema). NEVER hot-promotes — every quote is human-edited.

Cost ceiling: ~2 CPU minutes / month, ≤ 5k row scans, 0 external API calls,
              0 LLM calls.

Method (T+30d, plain rules-based, NO LLM rewrite):
  1. Pull `query_log_v2` rows from the prior 30 days where status_code in
     2xx and `result_bucket` indicates a hit (i.e., the request returned a
     useful answer rather than empty / error).
  2. Group by `tool` — each tool label becomes one testimonial bucket.
     Rank buckets by hit count. The tool label is the "hit_pattern"
     surface form.
  3. If a customer-rating list is supplied, attach the median rating per
     tool and pick up to N=3 sample comments per tool. Comments go through
     `security.pii_redact.redact_text` before they leave this module —
     法人番号 / email / 電話 never reach the YAML, the landing page, or
     downstream review queues. This is the INV-21 contract.
  4. Confidence ranking (mirrors loop_a / loop_g threshold convention):
        hits >= 5  -> high
        hits 3-4   -> medium
        hits < 3   -> noise floor — dropped.
     A bucket also requires either (a) >= 1 rated comment with rating >= 4
     after redaction, or (b) hits >= 5 with no ratings at all. Rated buckets
     with rating <= 3 are dropped (we will not surface lukewarm reviews).
  5. Emit `data/testimonials_proposed.yaml` with shape:
        - tool: <tool_label>
          confidence: high | medium
          hits: int
          median_rating: float | null
          sample_comments: [str, ...]   # already redacted
          suggestion: free-form note for the operator
     Operator reads, polishes prose, attaches industry/region attribution
     (NEVER from PII — only from operator-known facts), and copies into
     site/index.html + per-tool SEO snippets.

LLM use: NONE. Pure SQL + Counter + redact_text, per CONSTITUTION 13.2.

Launch v1 (this module):
    Provides `extract_hits`, `extract_testimonials`, `write_testimonials_yaml`,
    and a `run()` that accepts optional `query_log_rows` + `ratings` kwargs
    so tests can inject fixtures without spinning up a real DB. When
    callers pass nothing, `run()` returns the zeroed scaffold — same
    posture as loop_a / loop_g. Real DB wiring (read from learning DB)
    lives in the orchestrator that imports this module.

Cron wiring is intentionally out-of-scope for this module (handled by
`scripts/self_improve_orchestrator.py`).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped,unused-ignore]
except Exception:  # pragma: no cover - yaml optional at import time
    yaml = None

from jpintel_mcp.security.pii_redact import redact_text

# Repo layout: src/jpintel_mcp/self_improve/loop_b_testimonial_seo.py
# climb four parents to land on the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
PROPOSALS_PATH = REPO_ROOT / "data" / "testimonials_proposed.yaml"

# Confidence thresholds — kept in sync with loop_a's DBSCAN min_samples=3
# and loop_g's "≥ 5 hits = high" rule.
THRESHOLD_HIGH = 5
THRESHOLD_MEDIUM = 3

# Customer ratings <= this are excluded entirely. We will not surface
# lukewarm or negative reviews on the landing page.
MIN_PROMOTABLE_RATING = 4

# Hit buckets that count as "successful" answers. Anything else (zero,
# error, low_confidence) is *not* a customer success and must not feed
# the testimonial pipeline.
SUCCESS_BUCKETS = frozenset({"hit", "success", "ok"})

# Maximum redacted sample comments per tool to attach to a proposal.
MAX_SAMPLE_COMMENTS = 3


def extract_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter `query_log_v2` rows down to the success-path subset.

    A row qualifies when ALL of:
        * `status_code` is 2xx (200..299), OR `status_code` is missing
          (some test fixtures omit it — we accept those rather than drop).
        * `result_bucket` is in SUCCESS_BUCKETS (case-insensitive).
        * `tool` is a non-empty string.

    Pure function: no I/O, no mutation of inputs.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        tool = r.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        bucket = r.get("result_bucket")
        if not isinstance(bucket, str):
            continue
        if bucket.lower() not in SUCCESS_BUCKETS:
            continue
        status = r.get("status_code")
        if status is not None:
            try:
                if not (200 <= int(status) < 300):
                    continue
            except (TypeError, ValueError):
                continue
        out.append({"tool": tool.strip(), "result_bucket": bucket.lower()})
    return out


def _attach_ratings(tool: str, ratings: list[dict[str, Any]]) -> tuple[float | None, list[str]]:
    """Return (median_rating, redacted_sample_comments) for a single tool.

    Filters ratings to only those tagged for this tool, drops anything below
    MIN_PROMOTABLE_RATING (so lukewarm reviews never reach the landing page),
    redacts comment text via `redact_text` (INV-21), and keeps at most
    MAX_SAMPLE_COMMENTS distinct non-empty redacted strings.

    If no ratings target the tool, returns (None, []).
    """
    relevant_scores: list[float] = []
    sample_comments: list[str] = []
    seen: set[str] = set()
    for entry in ratings:
        if not isinstance(entry, dict):
            continue
        if entry.get("tool") != tool:
            continue
        raw_rating = entry.get("rating")
        if raw_rating is None:
            continue
        try:
            score = float(raw_rating)
        except (TypeError, ValueError):
            continue
        if score < MIN_PROMOTABLE_RATING:
            continue
        relevant_scores.append(score)
        comment = entry.get("comment")
        if not isinstance(comment, str) or not comment.strip():
            continue
        # PII redaction is non-negotiable — every comment string passes
        # through redact_text before it can be persisted or rendered.
        redacted = redact_text(comment.strip())
        if redacted in seen:
            continue
        seen.add(redacted)
        if len(sample_comments) < MAX_SAMPLE_COMMENTS:
            sample_comments.append(redacted)
    if not relevant_scores:
        return (None, [])
    return (statistics.median(relevant_scores), sample_comments)


def extract_testimonials(
    hits: list[dict[str, Any]],
    ratings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Cluster hits + ratings into testimonial proposals ranked by hit count.

    Returns a list of proposal dicts sorted by hit count desc. Each proposal:
        tool             str        -- the tool label / hit_pattern surface form
        confidence       str        -- high | medium  (low/noise dropped)
        hits             int        -- total successful invocations
        median_rating    float|None -- median CSAT rating (>=4 only) or None
        sample_comments  list[str]  -- up to 3 PII-redacted comments
        suggestion       str        -- free-form note for the operator
    """
    ratings = ratings or []
    counts: Counter[str] = Counter()
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hits:
        counts[h["tool"]] += 1
        by_tool[h["tool"]].append(h)

    proposals: list[dict[str, Any]] = []
    for tool, n in counts.most_common():
        if n < THRESHOLD_MEDIUM:
            continue  # noise floor — skip
        median_rating, sample_comments = _attach_ratings(tool, ratings)

        # Promotion gate: either we have at least one >=4-star comment
        # for the tool, or hit count alone is high (>=THRESHOLD_HIGH).
        # If there are tool-tagged ratings but they all fell below the
        # promotable threshold, _attach_ratings returns (None, []) and
        # we treat that as "rated but not promotable" — drop unless hits
        # alone meet the high-confidence floor.
        has_rating_signal = any(isinstance(r, dict) and r.get("tool") == tool for r in ratings)
        if has_rating_signal and median_rating is None and n < THRESHOLD_HIGH:
            continue
        if not has_rating_signal and n < THRESHOLD_HIGH:
            # Unrated bucket — require high confidence on hits alone.
            continue

        confidence = "high" if n >= THRESHOLD_HIGH else "medium"
        if sample_comments:
            suggestion = (
                f"{n} successful invocations of '{tool}' over the window with "
                f"{len(sample_comments)} promotable comment(s). "
                f"Operator: polish prose, attach industry/region from operator-"
                f"known facts only (NEVER from logs), and copy into "
                f"site/index.html + per-tool SEO snippet. PII already redacted."
            )
        else:
            suggestion = (
                f"{n} successful invocations of '{tool}' over the window with no "
                f"comment-side signal yet. Operator: pair with a hand-collected "
                f"quote (DM / email opt-in) before promoting; do not invent "
                f"customer language."
            )
        proposals.append(
            {
                "tool": tool,
                "confidence": confidence,
                "hits": n,
                "median_rating": median_rating,
                "sample_comments": sample_comments,
                "suggestion": suggestion,
            }
        )
    return proposals


def write_testimonials_yaml(proposals: list[dict[str, Any]], path: Path) -> int:
    """Write the testimonials proposals to YAML. Returns bytes written.

    Uses safe_dump so the file is plain YAML 1.1 (no Python-specific tags).
    Falls back to a hand-rolled emitter if the optional `yaml` module is
    missing — same posture as loop_g.write_proposals_yaml.
    """
    if yaml is None:
        body_lines = ["proposals:"]
        for p in proposals:
            body_lines.append(f"  - tool: {p['tool']}")
            body_lines.append(f"    confidence: {p['confidence']}")
            body_lines.append(f"    hits: {p['hits']}")
            mr = p["median_rating"]
            body_lines.append(f"    median_rating: {('null' if mr is None else mr)}")
            body_lines.append("    sample_comments:")
            for c in p["sample_comments"]:
                body_lines.append(f"      - {c!r}")
            body_lines.append(f"    suggestion: {p['suggestion']!r}")
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
    query_log_rows: list[dict[str, Any]] | None = None,
    ratings: list[dict[str, Any]] | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Scan query_log_v2 hits and propose testimonial candidates.

    Args:
        dry_run: When True, do not write `testimonials_proposed.yaml` —
            still parse + count, still report `actions_proposed`. Matches
            loop_a / loop_g (NEVER touches landing-page copy directly).
        query_log_rows: Optional injection of `query_log_v2` rows. When
            None, the function returns the zeroed scaffold — production
            wiring (read from the learning DB) lives in the orchestrator,
            keeping this module dependency-free for tests.
        ratings: Optional list of `{tool, rating, comment, api_key_hash}`
            dicts. Comments are redacted via INV-21 before persistence.
        out_path: Override for the proposals YAML output. Defaults to
            `data/testimonials_proposed.yaml`.

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.
    """
    out_p = out_path if out_path is not None else PROPOSALS_PATH

    if query_log_rows is None:
        # Pre-launch / orchestrator hasn't wired up the learning DB yet —
        # keep the dashboard green. Same posture as loop_a's empty-YAML.
        return {
            "loop": "loop_b_testimonial_seo",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    hits = extract_hits(query_log_rows)
    proposals = extract_testimonials(hits, ratings or [])

    actions_executed = 0
    if not dry_run and proposals:
        write_testimonials_yaml(proposals, out_p)
        actions_executed = 1

    return {
        "loop": "loop_b_testimonial_seo",
        "scanned": len(query_log_rows),
        "actions_proposed": len(proposals),
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(dry_run=True)))
