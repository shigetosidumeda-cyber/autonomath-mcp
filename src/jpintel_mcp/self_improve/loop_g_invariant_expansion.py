"""Loop G: failure mode -> property-based invariant expansion (INV-21 / INV-22).

Cadence: monthly (5th of month, 11:00 JST)
Inputs:
    * Sanitizer-hit log lines emitted by `api.response_sanitizer` and
      `mcp.server` whenever the affirmative-grant regex bank in
      `_AFFIRMATIVE_RULES` matches a generated response. Each hit carries
      a comma-separated `hits=<pid1>,<pid2>` string + the request path /
      tool label. We do not need the original query text — INV-22 is a
      *response*-side invariant, so the surface form lives in the body
      that already triggered the sanitizer.
    * The current `_AFFIRMATIVE_RULES` set in
      `src/jpintel_mcp/api/response_sanitizer.py` so we know which
      patterns are already covered (no duplicates).

Outputs:
    `data/invariants_proposed.yaml` — operator review queue. Operator
    polishes + moves rules into `_AFFIRMATIVE_RULES` (INV-22) or into
    `security/pii_redact.py::PII_PATTERNS` (INV-21). NEVER hot-promotes
    automatically; everything goes through review.

Cost ceiling: ~3 CPU minutes / month, ≤ 5k log lines scanned,
              0 external API calls, 0 LLM calls.

Method (T+30d, plain rules-based):
  1. Collect log lines matching `response_sanitized ... hits=<pids>`
     (and the MCP equivalent `mcp_response_sanitized`) over the last
     N days (default 30). The lines come from stderr capture or a file
     handler; the orchestrator passes a path explicitly.
  2. For each pattern-id, count occurrences and bucket by request path
     / MCP tool. High-frequency hit clusters tell us which rules need
     *narrower* phrasing or a *new* sibling pattern.
  3. Confidence ranking: hits ≥ 5 = high, 3–4 = medium, < 3 = noise
     (skipped). Same threshold the loop_a docstring uses for clusters.
  4. Emit `data/invariants_proposed.yaml` with shape:
        - id: <pattern_id>
          kind: INV-22-affirmative-grant   # or INV-21-pii
          existing: bool                   # already in _AFFIRMATIVE_RULES?
          hits: int
          confidence: high | medium
          paths: [/v1/...]                 # sample request paths
          suggestion: free-form note for the operator
     Operator reads, edits, and either copies into the live regex bank
     or discards.

LLM use: NONE. Pure regex parsing + Counter, per CONSTITUTION 13.2.

Launch v1 (this module):
    Provides the building blocks (`parse_sanitizer_log_lines`,
    `propose_invariants`, `write_proposals_yaml`) and a `run()` that
    accepts an optional `log_path` kwarg (defaults to
    `data/logs/sanitizer_hits.log`). When the log file is absent we
    return the zeroed scaffold dict so the orchestrator dashboard
    stays green pre-launch — same posture as loop_a.

Cron wiring is intentionally out-of-scope for this module (handled by
`scripts/self_improve_orchestrator.py` + a separate cron entry —
P3.1.5).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - yaml optional at import time
    yaml = None  # type: ignore

from jpintel_mcp.api import response_sanitizer as _sanitizer

# Repo layout: src/jpintel_mcp/self_improve/loop_g_invariant_expansion.py
# climb four parents to land on the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_PATH = REPO_ROOT / "data" / "logs" / "sanitizer_hits.log"
PROPOSALS_PATH = REPO_ROOT / "data" / "invariants_proposed.yaml"

# Confidence thresholds — kept in sync with loop_a's DBSCAN min_samples=3
# and the deep_dive_v8 "≥ 5 hits = high signal" rule.
THRESHOLD_HIGH = 5
THRESHOLD_MEDIUM = 3

# Log lines emitted by:
#   api/response_sanitizer.py    -> "response_sanitized path=%s status=%d hits=%s"
#   mcp/server.py                -> "mcp_response_sanitized tool=%s hits=%s"
# Both end in `hits=<comma-separated pattern ids>`. We parse either shape.
_LOG_LINE_RE = re.compile(
    r"(?P<kind>response_sanitized|mcp_response_sanitized)\s+"
    r"(?:path=(?P<path>\S+)|tool=(?P<tool>\S+))"
    r"(?:\s+status=\d+)?"
    r"\s+hits=(?P<hits>[\w\-,]+)"
)


def _existing_pattern_ids() -> set[str]:
    """Pattern ids already wired into the runtime sanitizer bank.

    Pulled directly from the `_AFFIRMATIVE_RULES` tuple so we never drift
    from what's actually live. If a proposal re-discovers an existing id,
    we still surface it (operator may want to *narrow* the regex), but we
    flag `existing: True` so the polish step is honest about scope.
    """
    return {pid for _pat, _repl, pid in _sanitizer._AFFIRMATIVE_RULES}


def parse_sanitizer_log_lines(lines: list[str]) -> list[dict[str, str]]:
    """Parse raw log lines, returning one dict per individual hit.

    A single line like::

        WARNING response_sanitized path=/v1/programs/search status=200 hits=must-grant,absolute-grant

    yields TWO dicts (one per pattern id). Pure function: no I/O.
    """
    out: list[dict[str, str]] = []
    for ln in lines:
        m = _LOG_LINE_RE.search(ln)
        if not m:
            continue
        kind = m.group("kind")
        target = m.group("path") or m.group("tool") or "<unknown>"
        for pid in m.group("hits").split(","):
            pid = pid.strip()
            if not pid:
                continue
            out.append({"kind": kind, "target": target, "pattern_id": pid})
    return out


def propose_invariants(hits: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Cluster hits into invariant-rule proposals ranked by confidence.

    Returns a list of proposal dicts sorted by hit count desc. Each
    proposal carries:
        id          str   -- the sanitizer pattern id (e.g. "must-grant")
        kind        str   -- INV-22-affirmative-grant | INV-21-pii
        existing    bool  -- already in the live regex bank?
        hits        int   -- total occurrences across all paths/tools
        confidence  str   -- high | medium  (low/noise dropped)
        paths       list  -- up to 5 sample paths/tools
        suggestion  str   -- free-form note for the human reviewer
    """
    counts: Counter[str] = Counter()
    targets: dict[str, list[str]] = defaultdict(list)
    for h in hits:
        counts[h["pattern_id"]] += 1
        # Record up to 5 distinct sample paths per pattern id.
        seen = targets[h["pattern_id"]]
        if h["target"] not in seen and len(seen) < 5:
            seen.append(h["target"])

    existing = _existing_pattern_ids()
    proposals: list[dict[str, Any]] = []
    for pid, n in counts.most_common():
        if n < THRESHOLD_MEDIUM:
            continue  # noise floor — skip
        confidence = "high" if n >= THRESHOLD_HIGH else "medium"
        is_existing = pid in existing
        if is_existing:
            suggestion = (
                f"Pattern '{pid}' already live in _AFFIRMATIVE_RULES but still "
                f"firing {n}x. Review whether the regex needs narrower "
                f"phrasing or a sibling rule covering an adjacent verb."
            )
        else:
            suggestion = (
                f"Unknown pattern id '{pid}' fired {n}x. Likely a typo in the "
                f"log emitter, or a new rule was deployed without a matching "
                f"entry here. Verify before promoting."
            )
        proposals.append(
            {
                "id": pid,
                "kind": "INV-22-affirmative-grant",
                "existing": is_existing,
                "hits": n,
                "confidence": confidence,
                "paths": list(targets[pid]),
                "suggestion": suggestion,
            }
        )
    return proposals


def write_proposals_yaml(proposals: list[dict[str, Any]], path: Path) -> int:
    """Write the proposals list to YAML. Returns bytes written.

    Uses safe_dump so the file is plain YAML 1.1 (no Python-specific tags),
    sorted-keys=False to keep the proposal dict order readable.
    """
    if yaml is None:
        # YAML missing — emit a minimal hand-rolled file so the operator
        # still gets a review queue. Format mirrors the safe_dump output.
        body_lines = ["proposals:"]
        for p in proposals:
            body_lines.append(f"  - id: {p['id']}")
            body_lines.append(f"    kind: {p['kind']}")
            body_lines.append(f"    existing: {str(p['existing']).lower()}")
            body_lines.append(f"    hits: {p['hits']}")
            body_lines.append(f"    confidence: {p['confidence']}")
            body_lines.append(f"    paths: {p['paths']}")
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
    log_path: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, int]:
    """Scan sanitizer-hit logs and propose invariant rule candidates.

    Args:
        dry_run: When True, do not write `invariants_proposed.yaml` —
            still parse + count, still report `actions_proposed`. Same
            contract as loop_a (NEVER touches live regex bank).
        log_path: Override for the sanitizer hit log file. Defaults to
            `data/logs/sanitizer_hits.log` under the repo root.
        out_path: Override for the proposals YAML output. Defaults to
            `data/invariants_proposed.yaml`.

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.
    """
    log_p = log_path if log_path is not None else DEFAULT_LOG_PATH
    out_p = out_path if out_path is not None else PROPOSALS_PATH

    if not log_p.exists():
        # Pre-launch / fresh deploy: no log file yet. Same posture as
        # loop_a's "no DB rows yet" — keep the orchestrator green.
        return {
            "loop": "loop_g_invariant_expansion",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    raw = log_p.read_text(encoding="utf-8", errors="replace").splitlines()
    hits = parse_sanitizer_log_lines(raw)
    proposals = propose_invariants(hits)

    actions_executed = 0
    if not dry_run and proposals:
        # Real run: drop the YAML for human review. We still consider this
        # a *proposal* (not promoted), so actions_executed counts the YAML
        # writes, not regex-bank mutations. Live bank stays untouched.
        write_proposals_yaml(proposals, out_p)
        actions_executed = 1

    return {
        "loop": "loop_g_invariant_expansion",
        "scanned": len(raw),
        "actions_proposed": len(proposals),
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(dry_run=True)))
