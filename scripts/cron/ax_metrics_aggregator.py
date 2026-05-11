#!/usr/bin/env python3
"""ax_metrics_aggregator.py — daily AX (Agent Experience) rollup.

Wave 17 AX Layer 3 — feeds ``site/status/ax_dashboard.html`` with the 6
quantitative metrics from ax_smart_guide §7:

  1. agent_ratio_pct       — エージェント経由 traffic 比率 (User-Agent)
  2. mcp_tool_calls        — MCP tool 呼出数 (daily / weekly / monthly)
  3. task_success_pct      — エージェント task 成功率 (isError=false 率)
  4. auth_success_pct      — エージェント認証成功率 (OAuth + magic-link)
  5. llms_txt_requests     — llms.txt / .md ファイル配信数 + html 比
  6. agent_conversion_pct  — エージェント発 conversion (UTM + token)

Sources:
  - ``analytics/cf_daily.jsonl``        Cloudflare per-day rollup (paths
                                        + UA class + status)
  - ``analytics/cf_ai_audit_{YYYY-MM-DD}.jsonl``
                                        Per-bot family request counts
                                        (GPTBot / ClaudeBot / etc.)
  - ``analytics/mcp_tool_calls.jsonl``  Optional — written by the MCP
                                        server middleware when present.
                                        Absent in dev; absence is OK.
  - ``analytics/auth_events.jsonl``     Optional — OAuth + magic-link
                                        success/failure events.
  - ``analytics/token_grants.jsonl``    Optional — Stripe / token issue
                                        events with UTM source breakout.

Output:
  ``site/status/ax_metrics.json`` — 7-day rolling per-metric series +
  ``summary`` with p50 / p95 / p99 rollups.

Idempotent: re-running on the same UTC day overwrites the JSON.

No LLM call. Pure stdlib + ``httpx`` (for an optional CF fallback that
only fires when local JSONL is empty).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANALYTICS = _REPO_ROOT / "analytics"
_OUT_PATH = _REPO_ROOT / "site" / "status" / "ax_metrics.json"
_WINDOW_DAYS = 7

# Bot family fingerprints — kept in lockstep with
# ``scripts/cron/cf_ai_audit_dump.py``. Lower-case substring match.
_BOT_NEEDLES: tuple[str, ...] = (
    "gptbot",
    "claudebot",
    "claude-web",
    "anthropic-ai",
    "perplexitybot",
    "perplexity-ai",
    "bytespider",
    "diffbot",
    "cohere-ai",
    "coherebot",
    "youbot",
    "mistralai",
    "mistral-ai",
    "applebot-extended",
    "amazonbot",
    "googlebot",  # not strictly an "agent", but consumed by AI ranking; tracked.
)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sv = sorted(values)
    k = max(0, min(len(sv) - 1, int(round((pct / 100.0) * (len(sv) - 1)))))
    return float(sv[k])


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _read_ai_audit_files(window_days: int) -> dict[str, dict[str, int]]:
    """Return ``{date: {bot: requests}}`` from per-day ai_audit JSONLs."""
    out: dict[str, dict[str, int]] = defaultdict(dict)
    today = datetime.now(UTC).date()
    for offset in range(window_days + 1):
        d = today - timedelta(days=offset)
        path = _ANALYTICS / f"cf_ai_audit_{d.isoformat()}.jsonl"
        for row in _read_jsonl(path):
            bot = str(row.get("bot") or "").lower()
            if not bot:
                continue
            reqs = int(row.get("requests") or 0)
            out[d.isoformat()][bot] = reqs
    return out


def _is_agent_ua(ua: str) -> bool:
    ua_low = (ua or "").lower()
    return any(n in ua_low for n in _BOT_NEEDLES)


def _cf_daily_per_day(window_days: int) -> dict[str, dict[str, Any]]:
    """Project ``cf_daily.jsonl`` rows into ``{date: rollup}``."""
    rows = _read_jsonl(_ANALYTICS / "cf_daily.jsonl")
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    per_day: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total_requests": 0,
            "agent_requests": 0,
            "llms_requests": 0,
            "html_requests": 0,
            "by_path": {},
        }
    )
    for row in rows:
        date = str(row.get("date") or "")
        if not date or date < cutoff:
            continue
        bucket = per_day[date]
        metric = row.get("metric")
        if metric == "summary":
            bucket["total_requests"] += int(row.get("requests") or 0)
        elif metric == "top_ua_class":
            for item in row.get("items") or []:
                ua = str(item.get("user_agent_class") or "")
                reqs = int(item.get("requests") or 0)
                if _is_agent_ua(ua):
                    bucket["agent_requests"] += reqs
        elif metric == "top_paths":
            for item in row.get("items") or []:
                path = str(item.get("path") or "")
                reqs = int(item.get("requests") or 0)
                low = path.lower()
                if low.endswith("/llms.txt") or low.endswith(
                    "/llms-full.txt"
                ) or low.endswith(".md") or "/llms" in low:
                    bucket["llms_requests"] += reqs
                if low.endswith(".html") or low == "/" or low.endswith("/"):
                    bucket["html_requests"] += reqs
                bucket["by_path"][path] = reqs
    return dict(per_day)


def _mcp_calls_per_day(window_days: int) -> dict[str, int]:
    rows = _read_jsonl(_ANALYTICS / "mcp_tool_calls.jsonl")
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    per_day: dict[str, int] = defaultdict(int)
    for row in rows:
        date = str(row.get("date") or "")
        if not date or date < cutoff:
            continue
        per_day[date] += int(row.get("count") or 1)
    return dict(per_day)


def _task_success_per_day(window_days: int) -> dict[str, dict[str, int]]:
    rows = _read_jsonl(_ANALYTICS / "mcp_tool_calls.jsonl")
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "err": 0})
    for row in rows:
        date = str(row.get("date") or "")
        if not date or date < cutoff:
            continue
        if row.get("isError") is True or row.get("is_error") is True:
            per_day[date]["err"] += 1
        else:
            per_day[date]["ok"] += 1
    return dict(per_day)


def _auth_success_per_day(window_days: int) -> dict[str, dict[str, int]]:
    rows = _read_jsonl(_ANALYTICS / "auth_events.jsonl")
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})
    for row in rows:
        date = str(row.get("date") or "")
        if not date or date < cutoff:
            continue
        if row.get("ok") is True or row.get("success") is True:
            per_day[date]["ok"] += 1
        else:
            per_day[date]["fail"] += 1
    return dict(per_day)


def _agent_conversion_per_day(window_days: int) -> dict[str, dict[str, int]]:
    rows = _read_jsonl(_ANALYTICS / "token_grants.jsonl")
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    per_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {"agent_grants": 0, "total_grants": 0, "tokens": 0}
    )
    for row in rows:
        date = str(row.get("date") or "")
        if not date or date < cutoff:
            continue
        utm = str(row.get("utm_source") or row.get("source") or "").lower()
        is_agent = utm in {
            "chatgpt",
            "claude",
            "perplexity",
            "cursor",
            "windsurf",
            "agent",
            "mcp",
            "anthropic",
            "openai",
        }
        per_day[date]["total_grants"] += 1
        per_day[date]["tokens"] += int(row.get("tokens") or 1)
        if is_agent:
            per_day[date]["agent_grants"] += 1
    return dict(per_day)


def _build_series(window_days: int) -> list[dict[str, Any]]:
    today = datetime.now(UTC).date()
    cf_per_day = _cf_daily_per_day(window_days)
    ai_audit = _read_ai_audit_files(window_days)
    mcp_per_day = _mcp_calls_per_day(window_days)
    task_per_day = _task_success_per_day(window_days)
    auth_per_day = _auth_success_per_day(window_days)
    conv_per_day = _agent_conversion_per_day(window_days)

    out: list[dict[str, Any]] = []
    for offset in range(window_days - 1, -1, -1):
        d = (today - timedelta(days=offset)).isoformat()
        cf = cf_per_day.get(d, {})
        # Prefer the ai_audit per-bot sum when present (more accurate than
        # cf_daily's UA class bucket).
        ai_total = sum(ai_audit.get(d, {}).values())
        agent_reqs = ai_total or int(cf.get("agent_requests", 0))
        total_reqs = int(cf.get("total_requests", 0))
        agent_ratio = (
            round((agent_reqs / total_reqs) * 100.0, 2)
            if total_reqs > 0
            else None
        )

        mcp_calls = mcp_per_day.get(d, 0)
        task_b = task_per_day.get(d, {"ok": 0, "err": 0})
        task_total = task_b["ok"] + task_b["err"]
        task_success = (
            round((task_b["ok"] / task_total) * 100.0, 2)
            if task_total > 0
            else None
        )

        auth_b = auth_per_day.get(d, {"ok": 0, "fail": 0})
        auth_total = auth_b["ok"] + auth_b["fail"]
        auth_success = (
            round((auth_b["ok"] / auth_total) * 100.0, 2)
            if auth_total > 0
            else None
        )

        llms_reqs = int(cf.get("llms_requests", 0))
        html_reqs = int(cf.get("html_requests", 0)) or 1
        llms_rel = round(llms_reqs / html_reqs, 3)

        conv_b = conv_per_day.get(d, {"agent_grants": 0, "total_grants": 0, "tokens": 0})
        conv_total = conv_b["total_grants"]
        agent_conv = (
            round((conv_b["agent_grants"] / conv_total) * 100.0, 2)
            if conv_total > 0
            else None
        )

        out.append(
            {
                "date": d,
                "agent_ratio_pct": agent_ratio,
                "mcp_tool_calls": mcp_calls,
                "task_success_pct": task_success,
                "auth_success_pct": auth_success,
                "llms_txt_requests": llms_reqs,
                "llms_relative_to_html": llms_rel,
                "agent_conversion_pct": agent_conv,
                "agent_tokens": conv_b["tokens"],
                "raw_agent_requests": agent_reqs,
                "raw_total_requests": total_reqs,
            }
        )
    return out


def _summary(days: list[dict[str, Any]]) -> dict[str, Any]:
    ratios = [d["agent_ratio_pct"] for d in days if d.get("agent_ratio_pct") is not None]
    iserrors = []
    for d in days:
        ok = d.get("task_success_pct")
        if ok is not None:
            iserrors.append(round(100.0 - ok, 2))
    return {
        "agent_ratio_p50": _percentile(ratios, 50),
        "agent_ratio_p95": _percentile(ratios, 95),
        "agent_ratio_p99": _percentile(ratios, 99),
        "mcp_calls_weekly": sum(d.get("mcp_tool_calls") or 0 for d in days),
        "mcp_calls_monthly": sum(d.get("mcp_tool_calls") or 0 for d in days) * 30 // max(1, len(days)),
        "iserror_pct": (
            round(statistics.fmean(iserrors), 2) if iserrors else None
        ),
        "llms_relative_to_html": (
            round(statistics.fmean(d["llms_relative_to_html"] for d in days), 3)
            if days
            else None
        ),
        "agent_tokens_issued": sum(d.get("agent_tokens") or 0 for d in days),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window-days",
        type=int,
        default=_WINDOW_DAYS,
        help="Rolling window size (default: 7).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the rollup and emit the JSON to stdout without "
        "writing the output file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_OUT_PATH,
        help=f"Output path (default: {_OUT_PATH}).",
    )
    args = parser.parse_args(argv)

    days = _build_series(args.window_days)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": args.window_days,
        "days": days,
        "summary": _summary(days),
    }

    if args.dry_run:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(
        f"[ax_metrics] wrote {args.out.relative_to(_REPO_ROOT)} "
        f"days={len(days)} agent_ratio_p50={payload['summary']['agent_ratio_p50']}"
    )
    return 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        sys.exit(main())
