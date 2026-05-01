"""Loop F: customer attribution -> channel ROI ranking (organic-only).

Cadence: weekly (Friday 16:00 JST, before the weekly publish)
Inputs:
    * `query_log_v2` (Wave 9 #1) — per-request rows carrying `api_key_hash`
      (NEVER raw key) plus a Referer-derived or User-Agent-derived
      `channel` label. Raw query text is NOT available here (INV-21
      boundary); the channel label arrives pre-bucketed.
    * `subscribers` rows — `email` (PII, never echoed to the report) +
      `source` / `utm_source` indicating the signup channel.
    * `billing_events` per-customer revenue. Used to attribute ¥ (¥3/req
      metered) back to the channel that brought the customer in.

Outputs:
    `data/channel_roi_report.json` — per-channel × conversion × LTV table.
    Operator reads this purely as guidance for *where to publish next*
    (more Zenn posts? GitHub README polish?). Never feeds an ad budget.

Cost ceiling: ~1 CPU minute / week, ≤ 50k row scans, 0 external API calls,
              0 LLM calls.

Method (T+30d, plain rules-based, NO LLM):
  1. Bucket signup attribution by channel:
        organic_search   -- google / bing / duckduckgo / yahoo
        mcp_registry     -- mcp.so / smithery / dxt
        github           -- github.com referrer or "github" utm
        blog             -- zenn / qiita / note / hatena
        partnerships     -- explicit utm_source allow-list
        direct           -- no referrer, no utm
        other            -- anything else (guard against label drift)
  2. Compute per channel: signups_28d, paid_28d (any billing_event with
     amount_jpy > 0), paid_conversion_rate, revenue_28d_jpy, LTV (sum
     of all per-customer revenue across the 28d window — NOT projected,
     we will not invent future revenue per `feedback_no_fake_data`).
  3. Confidence ranking:
        signups >= 30 -> high
        signups 10-29 -> medium
        signups < 10  -> low (kept in report for visibility)
  4. Emit `data/channel_roi_report.json` with shape:
        {
          "computed_at": "...",
          "window_days": 28,
          "channels": [
            {
              "channel": "...",
              "signups_28d": int,
              "paid_28d": int,
              "paid_conversion_rate": float,
              "revenue_28d_jpy": int,
              "ltv_jpy": float,
              "confidence": "high"|"medium"|"low"
            }, ...
          ]
        }

LLM use: NONE. Pure SQL-style aggregation in Python (Counter + dict math).

Memory note: AutonoMath is `feedback_organic_only_no_ads` — this loop is
informational, never paid-channel optimization, never ad-spend allocation.
We measure organic flow because zero-touch ops still wants to know which
public surface is bringing customers in. Per
`feedback_autonomath_no_api_use` we never call any external API from
inside this loop. Per INV-21 we never persist raw `email` or any other
PII — only the per-channel aggregates ever land in the JSON.

Launch v1 (this module):
    Provides `bucket_channel`, `aggregate_channels`,
    `write_report_json`, and a `run()` that accepts optional fixture
    kwargs. When none are passed, returns the zeroed scaffold — same
    posture as loop_a / loop_b / loop_d / loop_e / loop_g.

Cron wiring is intentionally out-of-scope for this module (handled by
`scripts/self_improve_orchestrator.py`).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Repo layout: src/jpintel_mcp/self_improve/loop_f_channel_roi.py
# climb four parents to reach the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "data" / "channel_roi_report.json"

# Confidence thresholds (mirror loop_b / loop_g hit-count posture).
N_HIGH = 30
N_MEDIUM = 10

# Channel mapping. We bucket coarsely on purpose — narrower labels add
# review cost without changing the operator's next move ("publish more
# Zenn posts" vs "publish more Qiita posts" is the same action under the
# `blog` bucket). Operator can split later if a channel grows enough to
# warrant its own row.
SEARCH_HOSTS = frozenset(
    {"google", "bing", "duckduckgo", "yahoo", "baidu", "ecosia", "brave"}
)
REGISTRY_HOSTS = frozenset({"mcp.so", "smithery", "dxt", "mcp-registry"})
BLOG_HOSTS = frozenset({"zenn", "qiita", "note", "hatena", "medium"})
PARTNERSHIP_SOURCES = frozenset({"partnership", "speakerdeck", "podcast"})


def bucket_channel(*, referer: str | None = None, utm_source: str | None = None) -> str:
    """Map a (referer, utm_source) pair to one of seven canonical channels.

    Pure function: no I/O. Rules apply in order; first match wins.

    Order rationale:
        1. utm_source is explicit operator-tagged attribution — trust it
           first when present.
        2. Referer string is heuristic; lower-cased substring check.
        3. Empty / None on both -> `direct`.
        4. Anything else -> `other` so label drift is visible in reports.
    """
    src = (utm_source or "").strip().lower()
    ref = (referer or "").strip().lower()

    if src:
        if src in PARTNERSHIP_SOURCES:
            return "partnerships"
        if src in REGISTRY_HOSTS or src.startswith("mcp"):
            return "mcp_registry"
        if src in BLOG_HOSTS:
            return "blog"
        if src in SEARCH_HOSTS:
            return "organic_search"
        if "github" in src:
            return "github"
        if src == "direct":
            return "direct"
        # Falls through to referer inspection so utm typos don't destroy
        # data — but we mark it `other` if the referer also fails.

    if ref:
        # Strip protocol + path so "https://google.com/search?q=..." -> "google.com"
        host = ref
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        host = host.split("/", 1)[0]
        # Keep tokens like "github.com" intact; substring scan against the
        # known hosts. We do NOT regex on TLDs — that overfits to .com.
        if any(s in host for s in SEARCH_HOSTS):
            return "organic_search"
        if any(s in host for s in REGISTRY_HOSTS):
            return "mcp_registry"
        if "github" in host:
            return "github"
        if any(s in host for s in BLOG_HOSTS):
            return "blog"

    if not src and not ref:
        return "direct"
    return "other"


def _confidence_label(n: int) -> str:
    if n >= N_HIGH:
        return "high"
    if n >= N_MEDIUM:
        return "medium"
    return "low"


def aggregate_channels(
    *,
    subscribers: list[dict[str, Any]],
    billing_events: list[dict[str, Any]],
    window_days: int = 28,
) -> dict[str, Any]:
    """Compute the per-channel aggregate report.

    Args:
        subscribers: list of dicts shaped like
            {api_key_hash, channel, signed_up_at} OR
            {api_key_hash, referer, utm_source, signed_up_at}.
            If `channel` is present we trust it; otherwise we run
            `bucket_channel(referer=, utm_source=)` to derive one.
            `email` MAY be present but is NEVER read here — INV-21 says
            PII never leaves redaction layer. We key everything on
            `api_key_hash` (already hashed upstream).
        billing_events: list of dicts shaped like
            {api_key_hash, amount_jpy, occurred_at}. Per
            `feedback_autonomath_no_api_use` and the ¥3/req model these
            are the metered usage events from `usage_events` joined with
            the per-call ¥3 fact, NOT a Stripe round-trip. We do NOT
            call Stripe inside this loop.
        window_days: trailing window length. Default 28 (matches the
            loop's weekly cadence + the launch billing window).

    Returns:
        Report dict with shape documented in module docstring. Pure
        function: no I/O.
    """
    # Bucket subscribers by channel; key by api_key_hash so we can join
    # with billing_events. Drop rows missing api_key_hash entirely
    # (without it we cannot tie revenue back; we will NOT join on email
    # per INV-21).
    by_hash: dict[str, str] = {}
    for s in subscribers:
        if not isinstance(s, dict):
            continue
        api_hash = s.get("api_key_hash")
        if not isinstance(api_hash, str) or not api_hash.strip():
            continue
        channel = s.get("channel")
        if not isinstance(channel, str) or not channel.strip():
            channel = bucket_channel(
                referer=s.get("referer"),
                utm_source=s.get("utm_source"),
            )
        by_hash[api_hash.strip()] = channel.strip()

    # Per-channel signup count.
    signups: dict[str, int] = defaultdict(int)
    for ch in by_hash.values():
        signups[ch] += 1

    # Per-channel revenue + paid-customer count. A customer is "paid"
    # when their summed amount_jpy > 0 across the window.
    revenue_per_hash: dict[str, int] = defaultdict(int)
    for ev in billing_events:
        if not isinstance(ev, dict):
            continue
        api_hash = ev.get("api_key_hash")
        if not isinstance(api_hash, str) or api_hash.strip() not in by_hash:
            continue
        try:
            amt = int(ev.get("amount_jpy") or 0)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        revenue_per_hash[api_hash.strip()] += amt

    revenue_per_channel: dict[str, int] = defaultdict(int)
    paid_per_channel: dict[str, int] = defaultdict(int)
    for api_hash, ch in by_hash.items():
        rev = revenue_per_hash.get(api_hash, 0)
        if rev > 0:
            paid_per_channel[ch] += 1
        revenue_per_channel[ch] += rev

    channels = []
    for ch in sorted(signups.keys()):
        n = signups[ch]
        paid = paid_per_channel.get(ch, 0)
        rev = revenue_per_channel.get(ch, 0)
        rate = (paid / n) if n > 0 else 0.0
        # LTV = realized revenue / signups (per-customer mean over the
        # window). We will NOT project forward-looking revenue.
        ltv = (rev / n) if n > 0 else 0.0
        channels.append(
            {
                "channel": ch,
                "signups_28d": n,
                "paid_28d": paid,
                "paid_conversion_rate": round(rate, 6),
                "revenue_28d_jpy": rev,
                "ltv_jpy": round(ltv, 2),
                "confidence": _confidence_label(n),
            }
        )

    return {
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "window_days": window_days,
        "channels": channels,
    }


def write_report_json(report: dict[str, Any], path: Path) -> int:
    """Write report JSON. Returns bytes written."""
    body = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n", encoding="utf-8")
    return len((body + "\n").encode("utf-8"))


def run(
    *,
    dry_run: bool = True,
    subscribers: list[dict[str, Any]] | None = None,
    billing_events: list[dict[str, Any]] | None = None,
    out_path: Path | None = None,
    window_days: int = 28,
) -> dict[str, Any]:
    """Aggregate channel ROI for the trailing window.

    Args:
        dry_run: When True, do not write `channel_roi_report.json` —
            still aggregate, still report `actions_proposed`. Same
            contract as loop_a / loop_b / loop_d / loop_g.
        subscribers: Optional list of attribution rows. When None we
            return the zeroed scaffold (orchestrator hasn't wired it yet).
        billing_events: Optional list of {api_key_hash, amount_jpy}
            revenue rows.
        out_path: Override for the JSON output path. Defaults to
            `data/channel_roi_report.json`.
        window_days: Override the trailing window (default 28).

    Returns:
        Standard self-improve loop dict:
            {loop, scanned, actions_proposed, actions_executed}.

        - `scanned` counts subscribers (signup attribution rows we processed).
        - `actions_proposed` counts channels with paid_conversion_rate > 0
          AND confidence != "low" — those are the operator-actionable
          rows ("publish more here").
        - `actions_executed` counts the JSON write (0 / 1).

    Memory invariants:
        - PII (email, raw queries, raw IPs) NEVER reaches the JSON. We
          key by api_key_hash only.
        - The output never recommends ad spend. It is purely an organic
          ranking signal. Per `feedback_organic_only_no_ads`.
    """
    out_p = out_path if out_path is not None else REPORT_PATH

    if not subscribers:
        # Pre-launch / orchestrator hasn't wired subscribers yet — keep
        # the dashboard green. Same posture as loop_a / loop_b / loop_e.
        return {
            "loop": "loop_f_channel_roi",
            "scanned": 0,
            "actions_proposed": 0,
            "actions_executed": 0,
        }

    report = aggregate_channels(
        subscribers=subscribers,
        billing_events=billing_events or [],
        window_days=window_days,
    )

    # Actionable: any channel with paying customers and meaningful sample.
    proposed = sum(
        1
        for c in report["channels"]
        if c["paid_28d"] > 0 and c["confidence"] != "low"
    )

    actions_executed = 0
    if not dry_run and report["channels"]:
        write_report_json(report, out_p)
        actions_executed = 1

    return {
        "loop": "loop_f_channel_roi",
        "scanned": len(subscribers),
        "actions_proposed": proposed,
        "actions_executed": actions_executed,
    }


if __name__ == "__main__":
    print(json.dumps(run(dry_run=True)))
