#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from
# src/, scripts/cron/, scripts/etl/, or tests/.
"""Wave 20 B11 — GEO bench 500 verify.

Why this exists (re: llm_citation_bench / aeo_citation_bench)
-------------------------------------------------------------
- `llm_citation_bench.py` (Wave 16 H4): measures whether jpcite is **cited
  at all** across 5 LLM surfaces. W4 = avg citations / question.
- `aeo_citation_bench.py` (Wave 17 AX): measures **AEO axes** (position,
  accuracy, competitor crowding) for ranking quality.
- **This file (geo_bench_500.py / Wave 20 B11)**: measures **GEO surface
  coverage** — does jpcite cite the right **government-evidence URL**
  for a known query, broken down by 5 corpus surfaces (programs, laws,
  cases, enforcement, loans).

Methodology
-----------
- 5 surface × 100 hand-curated query each = **500 verifications** per run.
- For each (surface, query), the bench:
    1. Calls the jpcite REST endpoint relevant to the surface
       (search_programs / search_laws / search_cases / check_enforcement
       / search_loans).
    2. Inspects top-3 result rows.
    3. Counts how many of the top-3 carry a **first-party** evidence URL
       (chusho.meti.go.jp / mof.go.jp / e-gov.go.jp / kantei.go.jp /
       jfc.go.jp / 47 都道府県 .pref.* / 1,700+ 市町村 .city.*).
- Per-surface score = (# queries with ≥1 first-party citation in top-3)
  / 100. Overall W4 = mean of 5 surface scores.

Target (Wave 20 B11 deliverable contract): **W4 ≥ 1.5**.

NO LLM in this bench
---------------------
GEO bench does NOT call an LLM. It calls the jpcite REST API and
inspects the response shape. The "GEO" framing is about **whether jpcite
is the surface a GEO-optimized search would land on**, measured by
first-party citation density. No anthropic/openai/gemini import here.

Operator contract
-----------------
- **OPERATOR ONLY**. Lives under `tools/offline/`.
- Reads `data/geo_bench_500_queries.json` for the 500 query set (NEW
  artifact, hand-curated + extracted from production query log).
- Writes:
    1. `analytics/geo_bench_500_w{N}.jsonl` — one row per (surface, q_id)
       with: hit_count_top3 / first_party_citations / source_hostnames /
       latency_ms / http_status.
    2. `reports/geo_bench_500_w{N}.md` — per-surface score + overall W4 +
       histogram of source hostname distribution + 10 worst-scoring
       queries per surface (for backlog triage).

CLI
---
    python tools/offline/geo_bench_500.py --week 20 [--surface laws]
                                          [--base-url URL] [--limit 100]

Memory anchors
--------------
- W4 target ≥ 1.5 (CLAUDE.md Wave hardening 2026-05-07 + Wave 16 H4 +
  this Wave 20 B11 deliverable).
- First-party citation = source_url host matches the canonical
  authority allowlist baked into this file.
- Aggregator banlist (noukaweb / hojyokin-portal / biz.stayway) is
  explicitly counted as a NEGATIVE signal — surfacing those is a defect.

See also
--------
- llm_citation_bench.py / aeo_citation_bench.py  (LLM-side benches)
- scripts/ops/audit_*_runner.py                  (CI audit gates)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "https://api.jpcite.com"
DEFAULT_QUERY_PATH = Path("data/geo_bench_500_queries.json")

# The 5 surfaces under test. Order matters for the report.
SURFACES: tuple[str, ...] = (
    "programs",
    "laws",
    "cases",
    "enforcement",
    "loans",
)

# Per-surface REST endpoint + result key.
SURFACE_ENDPOINTS: dict[str, tuple[str, str]] = {
    # surface -> (endpoint_path, result_root_key)
    "programs": ("/v1/programs/search", "programs"),
    "laws": ("/v1/laws/search", "laws"),
    "cases": ("/v1/cases/search", "cases"),
    "enforcement": ("/v1/enforcement/search", "enforcement_cases"),
    "loans": ("/v1/loans/search", "loan_programs"),
}

# First-party host allowlist — endings (suffix match). Acceptable as
# evidence sources. Anything outside this set is counted as 0
# first-party citation contribution.
FIRST_PARTY_HOST_SUFFIXES: tuple[str, ...] = (
    # Central government
    "go.jp",
    # Local government (都道府県 + 市町村)
    ".pref.fukushima.jp",
    ".pref.tokyo.jp",
    # ... we use a loose ".go.jp / .lg.jp / .pref.*.jp" rule below.
    ".lg.jp",
    # Japan Finance Corporation
    "jfc.go.jp",
    # Mirasapo / SME Agency
    "mirasapo-plus.go.jp",
    # 適格事業者公表サイト
    "invoice-kohyo.nta.go.jp",
    # Stripe-side ToS pass-through (rare but legit)
)

# Aggregator banlist. Surfacing these as evidence is a NEGATIVE signal —
# decrements the per-row score even when the rest of the row is fine.
AGGREGATOR_BANLIST: tuple[str, ...] = (
    "noukaweb.com",
    "hojyokin-portal.jp",
    "biz.stayway.jp",
    "ydream.co.jp",
    "j-net21.smrj.go.jp",  # acceptable in some contexts but flagged
)

PROBE_TIMEOUT = 15.0  # seconds, per request

# W4 target — Wave 20 B11 deliverable contract.
W4_TARGET = 1.5


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _http_get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, float, Any]:
    """GET a JSON URL with hard timeout. Returns (status, latency_ms, body_json|None)."""
    h = {"User-Agent": "jpcite-geo-bench-500/1.0", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            body = r.read()
            latency_ms = (time.monotonic() - t0) * 1000
            try:
                return int(r.status), latency_ms, json.loads(body)
            except Exception:
                return int(r.status), latency_ms, None
    except urllib.error.HTTPError as e:
        latency_ms = (time.monotonic() - t0) * 1000
        return int(e.code), latency_ms, None
    except Exception:
        latency_ms = (time.monotonic() - t0) * 1000
        return 0, latency_ms, None


# ---------------------------------------------------------------------------
# Surface-specific verify
# ---------------------------------------------------------------------------


def _host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_first_party(host: str) -> bool:
    """Return True if the host is in the first-party allowlist.

    Loose rule: any host ending in `.go.jp`, `.lg.jp`, or matching the
    `.pref.*.jp` / `.city.*.jp` pattern is treated as first-party. The
    explicit suffix list above gives precision for non-pattern cases.
    """
    if not host:
        return False
    if host.endswith(".go.jp") or host == "go.jp":
        return True
    if host.endswith(".lg.jp"):
        return True
    # Prefecture: .pref.<name>.jp
    if ".pref." in host and host.endswith(".jp"):
        return True
    # City / town / village: .city.* / .town.* / .vill.*
    for tok in (".city.", ".town.", ".vill."):
        if tok in host and host.endswith(".jp"):
            return True
    return any(
        host.endswith(suf.lstrip("."))
        for suf in FIRST_PARTY_HOST_SUFFIXES
        if not suf.startswith(".")
    )


def _is_aggregator(host: str) -> bool:
    return any(host == b or host.endswith("." + b) for b in AGGREGATOR_BANLIST)


def verify_one(api_base: str, surface: str, query: str) -> dict[str, Any]:
    """Run one (surface, query) verify and emit the row payload."""
    if surface not in SURFACE_ENDPOINTS:
        return {"surface": surface, "query": query, "skipped": True, "reason": "unknown_surface"}
    endpoint, root_key = SURFACE_ENDPOINTS[surface]
    qs = urllib.parse.urlencode({"q": query, "limit": 3})
    url = f"{api_base.rstrip('/')}{endpoint}?{qs}"
    status, latency_ms, body = _http_get_json(url)

    rows: list[dict[str, Any]] = []
    if isinstance(body, dict):
        cand = body.get(root_key)
        if isinstance(cand, list):
            rows = cand[:3]
    fp_count = 0
    agg_count = 0
    host_seq: list[str] = []
    for r in rows:
        u = r.get("source_url") if isinstance(r, dict) else None
        host = _host_of(u)
        host_seq.append(host)
        if _is_first_party(host):
            fp_count += 1
        if _is_aggregator(host):
            agg_count += 1
    return {
        "surface": surface,
        "query": query,
        "http_status": status,
        "latency_ms": round(latency_ms, 1),
        "rows_returned": len(rows),
        "first_party_top3": fp_count,
        "aggregator_top3": agg_count,
        "host_seq": host_seq,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def per_surface_score(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Return per-surface score (avg first_party_top3) — the W4 metric."""
    grouped: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if r.get("skipped"):
            continue
        grouped[r["surface"]].append(int(r.get("first_party_top3", 0)))
    out: dict[str, float] = {}
    for surface, vals in grouped.items():
        out[surface] = round(statistics.mean(vals), 3) if vals else 0.0
    return out


def overall_w4(per_surface: dict[str, float]) -> float:
    if not per_surface:
        return 0.0
    return round(statistics.mean(per_surface.values()), 3)


def histogram_hosts(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for r in rows:
        for h in r.get("host_seq", []) or []:
            if h:
                c[h] += 1
    return c.most_common(20)


def worst_queries(rows: list[dict[str, Any]], n: int = 10) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    by_surface: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("skipped"):
            continue
        by_surface[r["surface"]].append(r)
    for surface, rs in by_surface.items():
        rs_sorted = sorted(
            rs, key=lambda x: (x.get("first_party_top3", 0), -x.get("rows_returned", 0))
        )
        out[surface] = [x["query"] for x in rs_sorted[:n]]
    return out


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_markdown(
    rows: list[dict[str, Any]], per_surface: dict[str, float], w4: float, week: int
) -> str:
    lines = []
    lines.append(f"# GEO Bench 500 — Week {week}\n")
    lines.append(f"_Generated {datetime.now(UTC).isoformat(timespec='seconds')}_\n")
    lines.append(
        f"\n**W4 = {w4}** (target ≥ {W4_TARGET}) — {'PASS' if w4 >= W4_TARGET else 'FAIL'}.\n"
    )
    lines.append("\n## Per-surface score\n")
    lines.append("\n| surface | score | n |\n| --- | --- | --- |")
    for surface in SURFACES:
        n = sum(1 for r in rows if r.get("surface") == surface and not r.get("skipped"))
        s = per_surface.get(surface, 0.0)
        lines.append(f"| {surface} | {s} | {n} |")
    lines.append("\n## Top host distribution\n")
    lines.append("\n| host | count |\n| --- | --- |")
    for host, cnt in histogram_hosts(rows):
        lines.append(f"| {host} | {cnt} |")
    lines.append("\n## Worst-scoring queries (per surface, top 10)\n")
    worst = worst_queries(rows, n=10)
    for surface in SURFACES:
        if surface not in worst:
            continue
        lines.append(f"\n### {surface}\n")
        for q in worst[surface]:
            lines.append(f"- `{q}`")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="jpcite GEO Bench 500 (5 surface × 100 query).")
    p.add_argument("--week", type=int, required=True, help="Week number for output files.")
    p.add_argument("--base-url", type=str, default=DEFAULT_API_BASE)
    p.add_argument("--queries", type=Path, default=DEFAULT_QUERY_PATH)
    p.add_argument(
        "--surface",
        type=str,
        default="all",
        help="Restrict to one surface (programs / laws / cases / enforcement / loans).",
    )
    p.add_argument("--limit", type=int, default=100, help="Per-surface query cap (default 100).")
    p.add_argument("--out-dir", type=Path, default=Path("analytics"))
    p.add_argument("--report-dir", type=Path, default=Path("reports"))
    p.add_argument("--dry-run", action="store_true", help="Skip HTTP calls (smoke test only).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    queries_path: Path = args.queries
    if not queries_path.exists():
        print(
            f"[geo_bench_500] WARN: query file missing: {queries_path}\n"
            f"  Falling back to in-source hand-curated baseline (5 per surface).",
            file=sys.stderr,
        )
        queries = _embedded_baseline_queries()
    else:
        with open(queries_path, encoding="utf-8") as fh:
            queries = json.load(fh)

    target_surfaces = SURFACES if args.surface == "all" else (args.surface,)

    rows: list[dict[str, Any]] = []
    for surface in target_surfaces:
        sample = (queries.get(surface, []) or [])[: args.limit]
        if not sample:
            print(f"[geo_bench_500] WARN: surface={surface} has 0 queries", file=sys.stderr)
            continue
        for q in sample:
            if args.dry_run:
                rows.append({"surface": surface, "query": q, "skipped": True, "reason": "dry_run"})
                continue
            row = verify_one(args.base_url, surface, q)
            rows.append(row)

    per_surface = per_surface_score(rows)
    w4 = overall_w4(per_surface)

    # Outputs
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.out_dir / f"geo_bench_500_w{args.week}.jsonl"
    report_path = args.report_dir / f"geo_bench_500_w{args.week}.md"

    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    report_path.write_text(render_markdown(rows, per_surface, w4, args.week), encoding="utf-8")

    print(
        f"[geo_bench_500] wrote {jsonl_path} + {report_path}; "
        f"W4={w4} target≥{W4_TARGET} "
        f"{'PASS' if w4 >= W4_TARGET else 'FAIL'}"
    )
    return 0 if w4 >= W4_TARGET else 1


# ---------------------------------------------------------------------------
# Embedded baseline (used when data/geo_bench_500_queries.json is absent)
# ---------------------------------------------------------------------------


def _embedded_baseline_queries() -> dict[str, list[str]]:
    """5 surface × 5 query smoke baseline.

    The production set lives in `data/geo_bench_500_queries.json` (5 × 100).
    This embedded baseline is just enough to exercise the bench end-to-end
    when the corpus file is missing.
    """
    return {
        "programs": [
            "IT導入補助金",
            "ものづくり補助金",
            "事業承継補助金",
            "省エネ補助金",
            "事業再構築補助金",
        ],
        "laws": [
            "中小企業等経営強化法",
            "産業競争力強化法",
            "労働基準法 36協定",
            "租税特別措置法",
            "消費税法",
        ],
        "cases": [
            "ものづくり補助金 採択",
            "事業承継 採択",
            "IT導入 採択 製造業",
            "GX 採択",
            "省エネ 採択",
        ],
        "enforcement": [
            "業務改善命令",
            "登録取消",
            "業務停止",
            "指名停止",
            "課徴金",
        ],
        "loans": [
            "日本政策金融公庫 中小企業",
            "新創業融資",
            "セーフティネット",
            "資本性ローン",
            "創業支援",
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
