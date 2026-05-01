"""Loop C: per-customer query pattern -> personalized cache.

Cadence: weekly (Sunday 03:00 JST — off-peak)
Inputs: `query_log_v2` (last 30 days, INV-21-redacted; we read only
        `api_key_hash` + `tool` + `params_shape` — never raw query text,
        never the API key body, never email / 法人番号),
        existing `personalized_cache` (L4) table.
Outputs:
    * Per-customer cache key prefix `pcc:{api_key_hash[:8]}:{tool}:{params_hash}`
      seeded into L4 with TTL = 2x global cache TTL (per-customer reuse
      expectation is higher than the cross-customer baseline).
    * `data/personalized_cache_report.json` — operator-readable summary of
      per-customer top patterns + cache utilization rate. Written on the
      non-dry-run path; dry runs still compute the report shape but do
      not persist it.

Cost ceiling: ~10 CPU minutes / week, ≤ 200k row scans, 0 external API
calls, 0 LLM calls. ¥3/req metered budget never charges this loop because
no Anthropic API call ever fires here (memory `feedback_autonomath_no_api_use`).

Method (T+30d):
  1. For each `api_key_hash` with ≥ THRESHOLD_PER_CUSTOMER (=3) rows in the
     last 30 days, build a (tool, params_hash) histogram.
  2. Top-K (K=20) patterns per customer become the personalized cache
     candidates. Anything below THRESHOLD_PER_CUSTOMER is discarded (a
     single one-off query is not a "pattern").
  3. For each candidate, derive cache key `pcc:{api_key_hash[:8]}:{tool}:
     {params_hash}` and report it as inserted into L4 with TTL = 2 *
     GLOBAL_CACHE_TTL_S. Real L4 wiring lives in the orchestrator; this
     module returns the proposal set so it can be batched / paced.
  4. Compute per-customer utilization rate = (top-K hit volume) / (total
     volume in window). Higher rate ⇒ caching gives outsized ROI.

PII boundary (INV-21):
    * Only `api_key_hash` enters this loop. Raw API keys, raw email
      addresses, raw 法人番号, raw query text are NEVER read.
    * `params_shape` is the redacted, normalised structure of params
      (already produced upstream by the API surface — see
      `api/programs.py` redaction). This module additionally runs
      `redact_text` over any string params_shape leaf as a defence-in-
      depth, so a misshapen upstream row cannot leak PII into the
      report or the cache key.
    * The cache key trims `api_key_hash` to 8 chars to limit information
      leakage in cache backends that log keys; this is the standard
      industry trim and matches the global cache key convention.

LLM use: NONE. Pure rules + hashing.

Launch v1 (this module):
    Provides `extract_patterns`, `build_cache_proposals`,
    `write_report_json`, and a `run()` that accepts an optional
    `query_log_rows` kwarg so tests can inject fixtures. When callers
    pass nothing, `run()` returns the zeroed scaffold — same posture as
    loop_a / loop_b.

Cron wiring is intentionally out-of-scope for this module (handled by
`scripts/self_improve_orchestrator.py`).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jpintel_mcp.security.pii_redact import redact_text

# Repo layout: src/jpintel_mcp/self_improve/loop_c_personalized_cache.py
# climb four parents to land on the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "data" / "personalized_cache_report.json"

# Per-customer minimum hit count for a (tool, params_hash) pair to count
# as a "pattern" rather than a one-off. Anything below is dropped.
THRESHOLD_PER_CUSTOMER = 3

# Top-K patterns per customer that become personalized-cache candidates.
TOP_K_PER_CUSTOMER = 20

# Global cache TTL baseline (seconds). The personalized cache uses 2x this
# because per-customer reuse expectation is higher than the cross-customer
# baseline. Kept as a module constant so the orchestrator can override.
GLOBAL_CACHE_TTL_S = 24 * 3600  # 24h
PERSONALIZED_CACHE_TTL_S = 2 * GLOBAL_CACHE_TTL_S  # 48h

# api_key_hash trim length for cache key prefix. Matches the global cache
# key convention; full hash never enters cache backend logs.
API_KEY_HASH_TRIM = 8


def _params_hash(params_shape: Any) -> str:
    """Stable short hash of a params_shape leaf.

    `params_shape` is the redacted, normalised structure produced by the
    API surface — typically a dict like {"q": "<redacted>", "tier": "S"}.
    We canonicalise via sorted-key JSON and SHA-256-truncate to 12 hex
    chars; this gives ~10^14 collision space which is overkill for the
    per-customer K=20 working set but matches the global-cache hash
    width (debuggability over compactness).

    Pure function: no I/O.
    """
    try:
        canonical = json.dumps(params_shape, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        canonical = repr(params_shape)
    # Defence-in-depth: if a misshapen upstream row leaked PII into a
    # string leaf, redact it before hashing. The hash itself is not
    # reversible, but the canonical string is what gets reported back in
    # the JSON if a caller asked for raw shapes — so we keep INV-21 here.
    canonical = redact_text(canonical)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _trim_api_key_hash(api_key_hash: str) -> str:
    """Trim api_key_hash to API_KEY_HASH_TRIM chars.

    Returns the lowercase hex-friendly trim. If the input is shorter than
    the trim length we return it as-is rather than padding (test fixtures
    may use short labels like 'ak_abc').
    """
    s = (api_key_hash or "").strip()
    if len(s) <= API_KEY_HASH_TRIM:
        return s
    return s[:API_KEY_HASH_TRIM]


def extract_patterns(
    rows: list[dict[str, Any]],
) -> dict[str, Counter[tuple[str, str]]]:
    """Group `query_log_v2` rows into per-customer (tool, params_hash) histograms.

    A row qualifies when ALL of:
        * `api_key_hash` is a non-empty string (anonymous tier rows are
          dropped — those don't have a per-customer identity to cache for).
        * `tool` is a non-empty string.
        * `params_shape` is JSON-serialisable (dict/list/str/int/float/
          bool/None). Non-serialisable rows fall back to `repr()` and are
          still counted; we never crash on a malformed row.

    Returns:
        Mapping `api_key_hash -> Counter` keyed by `(tool, params_hash)`.

    Pure function: no I/O, no mutation of inputs.
    """
    by_customer: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for r in rows:
        if not isinstance(r, dict):
            continue
        akh = r.get("api_key_hash")
        if not isinstance(akh, str) or not akh.strip():
            continue
        tool = r.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        params_shape = r.get("params_shape")
        ph = _params_hash(params_shape)
        by_customer[akh.strip()][(tool.strip(), ph)] += 1
    return by_customer


def build_cache_proposals(
    by_customer: dict[str, Counter[tuple[str, str]]],
) -> list[dict[str, Any]]:
    """Build per-customer cache proposals from the histograms.

    Returns a list of proposal dicts, one per (customer, pattern) cell:
        api_key_hash_trim   str   -- 8-char trim, isolation key prefix
        tool                str
        params_hash         str   -- 12-hex SHA-256 truncate
        cache_key           str   -- pcc:{trim}:{tool}:{params_hash}
        hits                int
        ttl_s               int   -- PERSONALIZED_CACHE_TTL_S

    Sorted: by api_key_hash_trim asc, then hits desc — stable for
    snapshot-style assertions.
    """
    proposals: list[dict[str, Any]] = []
    for akh in sorted(by_customer.keys()):
        counter = by_customer[akh]
        # Drop sub-threshold patterns (one-off queries are not a pattern).
        kept = [
            (k, n) for k, n in counter.most_common() if n >= THRESHOLD_PER_CUSTOMER
        ]
        # Top-K per customer.
        kept = kept[:TOP_K_PER_CUSTOMER]
        trim = _trim_api_key_hash(akh)
        for (tool, params_hash), hits in kept:
            cache_key = f"pcc:{trim}:{tool}:{params_hash}"
            proposals.append(
                {
                    "api_key_hash_trim": trim,
                    "tool": tool,
                    "params_hash": params_hash,
                    "cache_key": cache_key,
                    "hits": hits,
                    "ttl_s": PERSONALIZED_CACHE_TTL_S,
                }
            )
    return proposals


def utilization_summary(
    by_customer: dict[str, Counter[tuple[str, str]]],
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-customer utilization rate = top-K hit volume / total volume.

    Higher rate ⇒ a small cache covers a large share of that customer's
    traffic ⇒ caching gives outsized ROI.

    Returns one summary row per customer (anonymous customers excluded
    upstream by extract_patterns):
        api_key_hash_trim   str
        total_volume        int   -- all rows for this customer
        cached_volume       int   -- rows covered by the proposed top-K
        utilization_rate    float -- cached / total, rounded to 4 places
        pattern_count       int   -- proposals emitted for this customer
    """
    cached_per_trim: dict[str, int] = defaultdict(int)
    pattern_count_per_trim: dict[str, int] = defaultdict(int)
    for p in proposals:
        cached_per_trim[p["api_key_hash_trim"]] += int(p["hits"])
        pattern_count_per_trim[p["api_key_hash_trim"]] += 1

    summary: list[dict[str, Any]] = []
    for akh in sorted(by_customer.keys()):
        total = sum(by_customer[akh].values())
        trim = _trim_api_key_hash(akh)
        cached = cached_per_trim.get(trim, 0)
        rate = round(cached / total, 4) if total > 0 else 0.0
        summary.append(
            {
                "api_key_hash_trim": trim,
                "total_volume": total,
                "cached_volume": cached,
                "utilization_rate": rate,
                "pattern_count": pattern_count_per_trim.get(trim, 0),
            }
        )
    return summary


def write_report_json(
    proposals: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    path: Path,
) -> int:
    """Write the personalized-cache report as JSON. Returns bytes written.

    Schema (stable for downstream operator dashboards):
        {
          "loop": "loop_c_personalized_cache",
          "ttl_s": int,
          "threshold_per_customer": int,
          "top_k_per_customer": int,
          "proposals": [...],   # one per (customer, pattern)
          "summary":   [...]    # one per customer
        }
    """
    body = json.dumps(
        {
            "loop": "loop_c_personalized_cache",
            "ttl_s": PERSONALIZED_CACHE_TTL_S,
            "threshold_per_customer": THRESHOLD_PER_CUSTOMER,
            "top_k_per_customer": TOP_K_PER_CUSTOMER,
            "proposals": proposals,
            "summary": summary,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return len(body.encode("utf-8"))


def run(
    *,
    dry_run: bool = True,
    query_log_rows: list[dict[str, Any]] | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Refresh per-customer personalized cache.

    Args:
        dry_run: When True, do not persist `personalized_cache_report.json`
            and do not signal L4 cache inserts. Still parses + counts and
            still reports `actions_proposed`. Same posture as loop_a /
            loop_b.
        query_log_rows: Optional injection of `query_log_v2` rows. When
            None, returns the zeroed scaffold — production wiring (read
            from the learning DB) lives in the orchestrator, keeping
            this module dependency-free for tests.
        out_path: Override for the report JSON output. Defaults to
            `data/personalized_cache_report.json`.

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.
    """
    out_p = out_path if out_path is not None else REPORT_PATH

    if query_log_rows is None:
        return {
            "loop": "loop_c_personalized_cache",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    by_customer = extract_patterns(query_log_rows)
    proposals = build_cache_proposals(by_customer)
    summary = utilization_summary(by_customer, proposals)

    actions_executed = 0
    if not dry_run and proposals:
        write_report_json(proposals, summary, out_p)
        actions_executed = 1

    return {
        "loop": "loop_c_personalized_cache",
        "scanned": len(query_log_rows),
        "actions_proposed": len(proposals),
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    print(json.dumps(run(dry_run=True)))
