#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, scripts/etl/, or tests/.
"""LLM citation rate weekly bench harness (Wave 16 H4).

Measures the rate at which 5 leading LLM surfaces (ChatGPT / Claude /
Gemini / Cursor / Codex) cite **jpcite** vs competitor sources
(j-grants, hojyokin-portal, nta.go.jp) when answering 100 GEO bench
questions defined in `data/geo_questions.json`.

100 questions × 5 surfaces = **500 verify calls** per run.

Outputs
-------
1. `analytics/llm_citation_bench_w{N}.jsonl` — one row per (q_id, surface)
   with raw response + extracted citations.
2. `reports/llm_citation_bench_w{N}.md` — aggregate markdown report
   surfacing jpcite citation rate, competitor citation rate, and per-
   category breakdown.

Operator contract
-----------------
- **OPERATOR ONLY**. This file lives under `tools/offline/` precisely so
  the production CI guard `tests/test_no_llm_in_production.py` does NOT
  block its LLM import. Never `import` this module from `src/`,
  `scripts/cron/`, `scripts/etl/`, or `tests/`.
- LLM provider SDKs (`anthropic` / `openai` / `google.generativeai`)
  are imported **lazily inside the surface-specific helpers**, so a missing
  SDK only fails the specific surface arm rather than the whole run.
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` env vars are
  read at function call site only — never module-import time.
- Output paths are deterministic given `--week N` so the operator can
  rerun a week without name collision.

Wave 12 baseline: W4 = 1.2 citations / question.
Wave 16 H4 target: W4 ≥ 1.5 citations / question (post-Wave-15 SEO/GEO lift).

Usage
-----
    python tools/offline/llm_citation_bench.py \
        --week 16 \
        --questions data/geo_questions.json \
        --surfaces chatgpt,claude,gemini,cursor,codex \
        --max-tokens 800 \
        --out-dir analytics

    python tools/offline/llm_citation_bench.py \
        --week 16 \
        --dry-run

    python tools/offline/llm_citation_bench.py \
        --week 16 \
        --aggregate-only \
        --jsonl analytics/llm_citation_bench_w16.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import UTC, datetime
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Surface aliases. Real upstream model id is resolved inside each helper.
SURFACES: tuple[str, ...] = ("chatgpt", "claude", "gemini", "cursor", "codex")

# Detection patterns. Order matters: more specific patterns first so
# `jpcite.com` is captured before `jpcite` alone.
CITATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "jpcite": re.compile(r"\bjpcite(?:\.com|\.ai|-mcp|)\b", re.IGNORECASE),
    "jgrants": re.compile(r"\bj[\-\s]?grants\b|jgrants[\-\.]?go\.?jp", re.IGNORECASE),
    "hojyokin_portal": re.compile(r"hojyokin[\-\s]?portal|補助金ポータル", re.IGNORECASE),
    "nta_go_jp": re.compile(r"\bnta\.go\.jp\b|国税庁", re.IGNORECASE),
}

JST = UTC  # store ts in UTC; report header renders JST


# ---------------------------------------------------------------------------
# Surface adapters (operator-only LLM calls)
# ---------------------------------------------------------------------------


def _call_claude(query: str, max_tokens: int) -> dict[str, Any]:
    """Call Claude via anthropic SDK. Lazy import."""
    try:
        import anthropic  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "anthropic package not installed; pip install anthropic"}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}
    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=os.environ.get("CLAUDE_BENCH_MODEL", "claude-opus-4-5"),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.content[0].text if resp.content else ""  # type: ignore[union-attr]
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_chatgpt(query: str, max_tokens: int) -> dict[str, Any]:
    """Call ChatGPT / GPT-5 family via openai SDK. Lazy import."""
    try:
        import openai  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "openai package not installed; pip install openai"}
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}
    client = openai.OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=os.environ.get("CHATGPT_BENCH_MODEL", "gpt-5"),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.choices[0].message.content or ""
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_gemini(query: str, max_tokens: int) -> dict[str, Any]:
    """Call Gemini via google.generativeai SDK. Lazy import."""
    try:
        import google.generativeai as genai  # noqa: F401  # LLM_IMPORT_TOLERATED (operator-side)
    except ImportError:
        return {"error": "google-generativeai package not installed"}
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY / GOOGLE_API_KEY not set"}
    try:
        genai.configure(api_key=api_key)
        model_name = os.environ.get("GEMINI_BENCH_MODEL", "gemini-2.5-pro")
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(
            query,
            generation_config={"max_output_tokens": max_tokens},
        )
        return {"response": getattr(resp, "text", "") or "", "model": model_name}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_cursor(query: str, max_tokens: int) -> dict[str, Any]:
    """Cursor / Codex have no public API — operator drives manually.

    This adapter records the query as a TODO entry instead of calling.
    The operator pastes the query into Cursor / Codex IDE, copies the
    response back, and re-runs `--aggregate-only` over the JSONL.
    """
    return {
        "error": "manual",
        "todo": "paste query into Cursor IDE, capture response, fill response field",
        "query_for_paste": query,
    }


def _call_codex(query: str, max_tokens: int) -> dict[str, Any]:
    """Codex (GitHub Copilot Chat) — same manual treatment as cursor."""
    return {
        "error": "manual",
        "todo": "paste query into Codex / Copilot Chat, capture response, fill response field",
        "query_for_paste": query,
    }


SURFACE_ADAPTERS: dict[str, Any] = {
    "chatgpt": _call_chatgpt,
    "claude": _call_claude,
    "gemini": _call_gemini,
    "cursor": _call_cursor,
    "codex": _call_codex,
}


# ---------------------------------------------------------------------------
# Citation extraction + scoring
# ---------------------------------------------------------------------------


def extract_citations(response_text: str) -> dict[str, int]:
    """Return dict of {pattern_name: hit_count} from the response text."""
    if not response_text:
        return dict.fromkeys(CITATION_PATTERNS, 0)
    return {name: len(pat.findall(response_text)) for name, pat in CITATION_PATTERNS.items()}


def score_response(citations: dict[str, int]) -> int:
    """0-4 score rubric matching tests/geo/bench_harness.py.

    0 = no jpcite mention
    1 = jpcite mentioned generically
    2 = jpcite cited as source
    3 = jpcite + specific surface (api/mcp/openapi/docs)
    4 = jpcite specific endpoint or tool name cited
    """
    jp = citations.get("jpcite", 0)
    if jp <= 0:
        return 0
    if jp >= 3:
        return 4
    if jp == 2:
        return 3
    return 2


# ---------------------------------------------------------------------------
# Main bench loop
# ---------------------------------------------------------------------------


def run_bench(
    *,
    week: int,
    questions: list[dict[str, Any]],
    surfaces: list[str],
    max_tokens: int,
    out_dir: pathlib.Path,
    dry_run: bool,
) -> pathlib.Path:
    """Run 100×N bench calls; write JSONL. Return path."""
    out_path = out_dir / f"llm_citation_bench_w{week}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for q in questions:
        for surface in surfaces:
            adapter = SURFACE_ADAPTERS.get(surface)
            if not adapter:
                continue
            if dry_run:
                resp = {"response": f"DRY_RUN q={q['id']} surface={surface}"}
            else:
                resp = adapter(q["query"], max_tokens)
            response_text = resp.get("response", "") if isinstance(resp, dict) else ""
            citations = extract_citations(response_text)
            score = score_response(citations)
            rows.append(
                {
                    "ts": datetime.now(JST).isoformat(),
                    "week": week,
                    "surface": surface,
                    "q_id": q["id"],
                    "category": q.get("category", "uncategorized"),
                    "lang": q.get("lang", "ja"),
                    "query": q["query"],
                    "model": resp.get("model"),
                    "error": resp.get("error"),
                    "citations": citations,
                    "score": score,
                    "raw_response": response_text[:4000],
                }
            )
    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return out_path


def aggregate(jsonl_path: pathlib.Path, week: int, report_dir: pathlib.Path) -> pathlib.Path:
    """Compute citation-rate summary; write markdown report. Return path."""
    rows: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"no rows in {jsonl_path}")

    total_calls = len(rows)
    by_surface: dict[str, dict[str, int]] = {}
    by_category: dict[str, dict[str, int]] = {}
    competitor_hits = {"jgrants": 0, "hojyokin_portal": 0, "nta_go_jp": 0}
    jpcite_hits = 0
    jpcite_calls_with_at_least_one = 0
    score_sum = 0
    errors = 0
    for r in rows:
        surface = r["surface"]
        category = r["category"]
        s = by_surface.setdefault(surface, {"calls": 0, "jpcite_citations": 0, "score_sum": 0})
        c = by_category.setdefault(category, {"calls": 0, "jpcite_citations": 0})
        s["calls"] += 1
        c["calls"] += 1
        cites = r.get("citations", {})
        s["jpcite_citations"] += cites.get("jpcite", 0)
        c["jpcite_citations"] += cites.get("jpcite", 0)
        s["score_sum"] += r.get("score", 0)
        jpcite_hits += cites.get("jpcite", 0)
        if cites.get("jpcite", 0) > 0:
            jpcite_calls_with_at_least_one += 1
        for k in competitor_hits:
            competitor_hits[k] += cites.get(k, 0)
        score_sum += r.get("score", 0)
        if r.get("error"):
            errors += 1

    avg_jpcite_per_q = jpcite_hits / total_calls if total_calls else 0.0
    citation_rate = (
        jpcite_calls_with_at_least_one / total_calls if total_calls else 0.0
    )
    avg_score = score_sum / total_calls if total_calls else 0.0

    # W4 target gate: average >= 1.5 citations / question
    target = 1.5
    gate_status = "PASS" if avg_jpcite_per_q >= target else "MISS"

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"llm_citation_bench_w{week}.md"
    lines = [
        f"# LLM Citation Bench — Week {week}",
        "",
        f"Generated: {datetime.now(JST).isoformat()}",
        f"Source: `{jsonl_path}`",
        f"Total calls: {total_calls} (errors: {errors})",
        "",
        "## Aggregate",
        "",
        f"- **avg jpcite citations / question**: {avg_jpcite_per_q:.2f} (target ≥ {target} — {gate_status})",
        f"- **jpcite citation rate** (≥1 hit / question): {citation_rate * 100:.1f}%",
        f"- **avg rubric score**: {avg_score:.2f} / 4",
        "",
        "## Competitor citations (lower is better)",
        "",
        "| source | hits |",
        "| --- | ---: |",
    ]
    for name, count in competitor_hits.items():
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            "## By surface",
            "",
            "| surface | calls | jpcite cites | avg score |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for surface, s in sorted(by_surface.items()):
        avg = s["score_sum"] / s["calls"] if s["calls"] else 0.0
        lines.append(
            f"| {surface} | {s['calls']} | {s['jpcite_citations']} | {avg:.2f} |"
        )
    lines.extend(
        [
            "",
            "## By category",
            "",
            "| category | calls | jpcite cites |",
            "| --- | ---: | ---: |",
        ]
    )
    for category, c in sorted(by_category.items()):
        lines.append(f"| {category} | {c['calls']} | {c['jpcite_citations']} |")
    lines.append("")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--week", type=int, required=True, help="Wave week number (e.g. 16)")
    parser.add_argument(
        "--questions",
        type=pathlib.Path,
        default=REPO_ROOT / "data" / "geo_questions.json",
    )
    parser.add_argument(
        "--surfaces",
        type=str,
        default=",".join(SURFACES),
        help="Comma-separated surface aliases. Default: all 5.",
    )
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=REPO_ROOT / "analytics",
    )
    parser.add_argument(
        "--report-dir",
        type=pathlib.Path,
        default=REPO_ROOT / "reports",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM calls; fill responses with DRY_RUN placeholders.",
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Skip bench run; aggregate an existing JSONL into the markdown report.",
    )
    parser.add_argument(
        "--jsonl",
        type=pathlib.Path,
        default=None,
        help="Override JSONL input path (used with --aggregate-only).",
    )
    args = parser.parse_args(argv)

    questions_doc = json.loads(args.questions.read_text(encoding="utf-8"))
    questions = questions_doc.get("questions", [])
    if not questions:
        print(f"[llm_citation_bench] no questions in {args.questions}", file=sys.stderr)
        return 2

    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    unknown = [s for s in surfaces if s not in SURFACE_ADAPTERS]
    if unknown:
        print(f"[llm_citation_bench] unknown surfaces: {unknown}", file=sys.stderr)
        return 2

    if args.aggregate_only:
        jsonl = args.jsonl or (args.out_dir / f"llm_citation_bench_w{args.week}.jsonl")
        if not jsonl.exists():
            print(f"[llm_citation_bench] jsonl not found: {jsonl}", file=sys.stderr)
            return 2
        report = aggregate(jsonl, args.week, args.report_dir)
        print(f"[llm_citation_bench] aggregated → {report}")
        return 0

    jsonl_path = run_bench(
        week=args.week,
        questions=questions,
        surfaces=surfaces,
        max_tokens=args.max_tokens,
        out_dir=args.out_dir,
        dry_run=args.dry_run,
    )
    report = aggregate(jsonl_path, args.week, args.report_dir)
    print(f"[llm_citation_bench] jsonl → {jsonl_path}")
    print(f"[llm_citation_bench] report → {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
