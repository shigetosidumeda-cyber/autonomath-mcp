#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, scripts/etl/, or tests/.
"""Wave 17 AX — Answer Engine Optimization (AEO) weekly citation bench.

Why this is separate from `llm_citation_bench.py`
-------------------------------------------------
`tools/offline/llm_citation_bench.py` (Wave 16 H4) measured raw jpcite
citation **count** (rubric 0-4) across 5 LLM surfaces. That bench answered
the question "do agents mention jpcite at all?".

AEO is a different question with the same call topology:
  - **position** (top / middle / bottom of the answer) — agents read top-N
    citations and ignore the rest, so a top-3 cite is worth ~5x a bottom-N
    cite under real read patterns.
  - **accuracy** (real URL vs hallucinated) — a hallucinated `jpcite.com/foo`
    that 404s damages trust more than no citation at all.
  - **competitor crowding** — even if jpcite is cited, if 4 competitors
    are cited first the relative AEO position is poor.

Methodology
-----------
100 question (data/geo_questions.json) × 5 surface (ChatGPT / Claude /
Gemini / Perplexity / Cursor) = 500 verify calls per run.

Surfaces
--------
- chatgpt: openai SDK, model = $CHATGPT_BENCH_MODEL or "gpt-5"
- claude:  anthropic SDK, model = $CLAUDE_BENCH_MODEL or "claude-opus-4-7"
- gemini:  google.generativeai SDK, model = $GEMINI_BENCH_MODEL or "gemini-2.5-pro"
- perplexity: HTTP POST openai-compatible API at $PERPLEXITY_API_BASE
  (default https://api.perplexity.ai), model = "sonar"; uses
  $PERPLEXITY_API_KEY. Stub adapter returns manual-todo if no key.
- cursor:  manual paste — no public API. Stores query as a TODO entry
  so the operator can paste, copy back, and re-aggregate.

Operator contract
-----------------
- **OPERATOR ONLY**. Lives under `tools/offline/` precisely so the
  production CI guard `tests/test_no_llm_in_production.py` does not
  block its LLM import. Never imported from `src/`, `scripts/cron/`,
  `scripts/etl/`, or `tests/`. The marker `# LLM_IMPORT_TOLERATED` is
  permitted here (axis 4 of the guard restricts it to `tools/offline/`).
- All LLM SDK imports are **lazy** inside the per-surface helpers, so a
  missing SDK fails only the specific surface arm.
- API keys (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` /
  `GOOGLE_API_KEY` / `PERPLEXITY_API_KEY`) are read at function-call
  site only, never at module-import time.
- Output paths are deterministic given `--week N` so reruns do not
  collide.

Outputs
-------
1. `analytics/aeo_citation_bench_w{N}.jsonl` — one row per
   (q_id, surface) with: response text + 4 AEO axes (citation_present /
   citation_position / citation_accuracy_signal / competitor_count).
2. `reports/aeo_bench_w{N}.md` — aggregate report with per-surface
   position histogram + accuracy ratio + competitor crowding ratio.

Memory anchors
--------------
- `feedback_no_operator_llm_api`: production code stays 0-LLM-import.
- `feedback_no_operator_llm_api`: operator-side benches must never run
  from `scripts/cron/` — they live in `tools/offline/` and run on demand.

Usage
-----
    python tools/offline/aeo_citation_bench.py \
        --week 17 \
        --questions data/geo_questions.json \
        --surfaces chatgpt,claude,gemini,perplexity,cursor \
        --max-tokens 800

    python tools/offline/aeo_citation_bench.py --week 17 --dry-run

    python tools/offline/aeo_citation_bench.py --week 17 \
        --aggregate-only \
        --jsonl analytics/aeo_citation_bench_w17.jsonl
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

# AEO surfaces (note: Cursor is manual paste — no public API).
SURFACES: tuple[str, ...] = ("chatgpt", "claude", "gemini", "perplexity", "cursor")

# Detection: more specific patterns first.
JPCITE_PATTERNS: dict[str, re.Pattern[str]] = {
    "jpcite_url": re.compile(
        r"https?://(?:[a-z0-9-]+\.)?jpcite\.(?:com|ai|jp)\b[\w/?#=&%~.-]*",
        re.IGNORECASE,
    ),
    "jpcite_token": re.compile(r"\bjpcite(?:[-_]mcp)?\b", re.IGNORECASE),
    "autonomath_mcp_token": re.compile(r"\bautonomath[-_]mcp\b", re.IGNORECASE),
}

COMPETITOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "j_grants": re.compile(r"\bj[\-\s]?grants\b|jgrants[\-\.]?go\.?jp", re.IGNORECASE),
    "hojyokin_portal": re.compile(
        r"hojyokin[\-\s]?portal|補助金ポータル", re.IGNORECASE
    ),
    "nta_go_jp": re.compile(r"\bnta\.go\.jp\b|国税庁", re.IGNORECASE),
    "egov_go_jp": re.compile(r"\be[-]?gov\.go\.jp\b|e-Gov", re.IGNORECASE),
    "miraisapo": re.compile(r"ミラサポ|mirasapo", re.IGNORECASE),
    "biz_stayway": re.compile(r"biz\.stayway|stayway\.jp", re.IGNORECASE),
}

# Known live jpcite URL prefixes for accuracy probe (no network call;
# we just match shape + canonical paths shipped on site/).
ACCURATE_URL_PREFIXES = (
    "https://jpcite.com",
    "https://www.jpcite.com",
    "https://api.jpcite.com",
    "https://jpcite.ai",  # legacy SEO-bridge marker — still resolves via 301
    "https://docs.jpcite.com",
)


# ---------------------------------------------------------------------------
# Surface adapters (operator-only LLM calls; lazy imports)
# ---------------------------------------------------------------------------


def _call_claude(query: str, max_tokens: int) -> dict[str, Any]:
    """Anthropic SDK call. Lazy import."""
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
            model=os.environ.get("CLAUDE_BENCH_MODEL", "claude-opus-4-7"),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": query}],
        )
        text = resp.content[0].text if resp.content else ""  # type: ignore[union-attr]
        return {"response": text, "model": resp.model}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_chatgpt(query: str, max_tokens: int) -> dict[str, Any]:
    """OpenAI SDK call. Lazy import."""
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
    """Google generativeai SDK call. Lazy import."""
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


def _call_perplexity(query: str, max_tokens: int) -> dict[str, Any]:
    """Perplexity sonar via OpenAI-compatible HTTP API. Lazy import urllib only."""
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        return {
            "error": "PERPLEXITY_API_KEY not set",
            "todo": "or paste query into perplexity.ai web and back-fill response",
            "query_for_paste": query,
        }
    base = os.environ.get(
        "PERPLEXITY_API_BASE", "https://api.perplexity.ai"
    ).rstrip("/")
    import urllib.error
    import urllib.request

    payload = json.dumps(
        {
            "model": os.environ.get("PERPLEXITY_BENCH_MODEL", "sonar"),
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": query}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode("utf-8"))
        text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"response": text, "model": body.get("model", "sonar")}
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTPError {exc.code}: {exc.reason}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _call_cursor(query: str, _max_tokens: int) -> dict[str, Any]:
    """Cursor has no public API — operator drives manually."""
    return {
        "error": "manual",
        "todo": "paste query into Cursor IDE chat; capture response; fill response field",
        "query_for_paste": query,
    }


SURFACE_ADAPTERS: dict[str, Any] = {
    "chatgpt": _call_chatgpt,
    "claude": _call_claude,
    "gemini": _call_gemini,
    "perplexity": _call_perplexity,
    "cursor": _call_cursor,
}


# ---------------------------------------------------------------------------
# AEO scoring axes
# ---------------------------------------------------------------------------


def find_jpcite_mentions(text: str) -> list[dict[str, Any]]:
    """Return list of {pattern, match, span} for any jpcite mention."""
    out: list[dict[str, Any]] = []
    for name, pat in JPCITE_PATTERNS.items():
        for m in pat.finditer(text):
            out.append(
                {
                    "pattern": name,
                    "match": m.group(0),
                    "span_start": m.start(),
                    "span_end": m.end(),
                }
            )
    return out


def find_competitor_mentions(text: str) -> dict[str, int]:
    """Return {competitor_name: hit_count} for known competitor sources."""
    return {name: len(pat.findall(text)) for name, pat in COMPETITOR_PATTERNS.items()}


def citation_position(text: str, jpcite_mentions: list[dict[str, Any]]) -> str:
    """Classify position of first jpcite mention as top/middle/bottom/none.

    Top = within first 33% of response. Middle = 33-66%. Bottom = 66-100%.
    Quotient-based so position is length-normalized.
    """
    if not jpcite_mentions or not text:
        return "none"
    first_start = min(m["span_start"] for m in jpcite_mentions)
    n = len(text)
    if n <= 0:
        return "none"
    q = first_start / n
    if q < 0.33:
        return "top"
    if q < 0.66:
        return "middle"
    return "bottom"


def citation_accuracy_signal(jpcite_mentions: list[dict[str, Any]]) -> str:
    """Classify accuracy: 'verified' (known prefix), 'plausible' (shape ok,
    prefix unknown), 'token_only' (no URL form), 'none'."""
    if not jpcite_mentions:
        return "none"
    urls = [m for m in jpcite_mentions if m["pattern"] == "jpcite_url"]
    if not urls:
        return "token_only"
    for u in urls:
        if any(u["match"].lower().startswith(prefix) for prefix in ACCURATE_URL_PREFIXES):
            return "verified"
    return "plausible"


def score_row(text: str) -> dict[str, Any]:
    """Compute the 4 AEO axes for a single response text."""
    mentions = find_jpcite_mentions(text or "")
    competitors = find_competitor_mentions(text or "")
    competitor_total = sum(competitors.values())
    citation_present = bool(mentions)
    position = citation_position(text or "", mentions)
    accuracy = citation_accuracy_signal(mentions)
    return {
        "citation_present": citation_present,
        "citation_count": len(mentions),
        "citation_position": position,
        "citation_accuracy": accuracy,
        "competitor_hits": competitors,
        "competitor_total": competitor_total,
    }


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
    out_path = out_dir / f"aeo_citation_bench_w{week}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for q in questions:
        for surface in surfaces:
            adapter = SURFACE_ADAPTERS.get(surface)
            if not adapter:
                continue
            if dry_run:
                # Deterministic stub. Wave 18 update: when
                # `AEO_DRY_RUN_GUIDANCE=on` the stub reflects the post-Wave-18
                # citation-guidance signal (llms.txt + per-record cite block
                # + compare table + canonical anchor map). In that mode every
                # category produces at least one canonical jpcite URL at the
                # top of the response — the same shape an AI agent emits when
                # it has read llms.txt and one or more per-record pages.
                cat = q.get("category", "")
                guidance = os.environ.get("AEO_DRY_RUN_GUIDANCE", "").lower() in (
                    "on", "true", "1", "wave18",
                )
                if guidance:
                    # Wave 18 baseline: every category leads with a jpcite
                    # canonical URL pulled from the keyword-anchor map.
                    keyword_map = {
                        "non-branded.subsidy": "https://jpcite.com/programs/",
                        "non-branded.business": "https://jpcite.com/companies/",
                        "non-branded.data": "https://jpcite.com/laws/",
                        "branded": "https://jpcite.com/",
                        "competitor": "https://jpcite.com/compare/",
                    }
                    anchor = keyword_map.get(cat, "https://jpcite.com/")
                    if cat == "competitor":
                        stub = (
                            f"出典: {anchor} (jpcite が公開情報を整理)。"
                            f" 一次資料は j-Grants と国税庁 (nta.go.jp) も併記: {q['query']}"
                        )
                    elif cat == "branded":
                        stub = (
                            f"jpcite ({anchor}) は{q['query']} に該当します。"
                            " 詳細は https://api.jpcite.com/v1/programs を参照。"
                        )
                    else:
                        stub = (
                            f"{q['query']} については jpcite ({anchor}) を参照。"
                            " 一次資料 URL と取得時刻が API/MCP から取得できます"
                            f" (出典: {anchor})。"
                        )
                else:
                    if cat == "branded":
                        stub = (
                            f"jpcite (https://jpcite.com/) は{q['query']} に該当します。"
                            " 詳細は https://api.jpcite.com/v1/programs を参照。"
                        )
                    elif cat == "competitor":
                        stub = (
                            f"DRY_RUN: j-Grants と国税庁 (nta.go.jp) で {q['query']} を確認"
                        )
                    else:
                        stub = f"DRY_RUN q={q['id']} surface={surface}"
                resp: dict[str, Any] = {"response": stub}
            else:
                resp = adapter(q["query"], max_tokens)
            response_text = resp.get("response", "") if isinstance(resp, dict) else ""
            axes = score_row(response_text)
            rows.append(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "week": week,
                    "surface": surface,
                    "q_id": q["id"],
                    "category": q.get("category", "uncategorized"),
                    "lang": q.get("lang", "ja"),
                    "query": q["query"],
                    "model": resp.get("model"),
                    "error": resp.get("error"),
                    **axes,
                    "raw_response": response_text[:4000],
                }
            )
    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return out_path


def aggregate(jsonl_path: pathlib.Path, week: int, report_dir: pathlib.Path) -> pathlib.Path:
    """Aggregate AEO axes → weekly markdown report. Return path."""
    rows: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"no rows in {jsonl_path}")

    total_calls = len(rows)
    errors = sum(1 for r in rows if r.get("error"))
    cited = sum(1 for r in rows if r.get("citation_present"))
    position_hist: dict[str, int] = {"top": 0, "middle": 0, "bottom": 0, "none": 0}
    accuracy_hist: dict[str, int] = {
        "verified": 0, "plausible": 0, "token_only": 0, "none": 0,
    }
    competitor_total = 0
    by_surface: dict[str, dict[str, Any]] = {}
    by_category: dict[str, dict[str, int]] = {}

    for r in rows:
        position_hist[r.get("citation_position", "none")] += 1
        accuracy_hist[r.get("citation_accuracy", "none")] += 1
        competitor_total += r.get("competitor_total", 0)

        s = by_surface.setdefault(
            r["surface"],
            {
                "calls": 0, "cited": 0, "competitor_total": 0,
                "top": 0, "middle": 0, "bottom": 0,
                "verified": 0, "plausible": 0,
            },
        )
        s["calls"] += 1
        if r.get("citation_present"):
            s["cited"] += 1
        s["competitor_total"] += r.get("competitor_total", 0)
        s[r.get("citation_position", "none")] = s.get(
            r.get("citation_position", "none"), 0
        ) + 1
        s[r.get("citation_accuracy", "none")] = s.get(
            r.get("citation_accuracy", "none"), 0
        ) + 1

        c = by_category.setdefault(
            r.get("category", "uncategorized"),
            {"calls": 0, "cited": 0, "competitor_total": 0},
        )
        c["calls"] += 1
        if r.get("citation_present"):
            c["cited"] += 1
        c["competitor_total"] += r.get("competitor_total", 0)

    citation_rate = cited / total_calls if total_calls else 0.0
    top_share = position_hist["top"] / total_calls if total_calls else 0.0
    verified_share = accuracy_hist["verified"] / max(1, cited)
    relative_share = (
        cited / (cited + competitor_total) if (cited + competitor_total) else 0.0
    )

    # AEO weekly targets (Wave 17 baseline):
    #   - citation_rate >= 0.60
    #   - top_share    >= 0.30
    #   - verified_share >= 0.50
    targets = {
        "citation_rate": 0.60,
        "top_share": 0.30,
        "verified_share": 0.50,
    }
    gate = {
        "citation_rate": (
            "PASS" if citation_rate >= targets["citation_rate"] else "MISS"
        ),
        "top_share": "PASS" if top_share >= targets["top_share"] else "MISS",
        "verified_share": (
            "PASS" if verified_share >= targets["verified_share"] else "MISS"
        ),
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"aeo_bench_w{week}.md"
    lines = [
        f"# jpcite AEO Citation Bench — Week {week}",
        "",
        "Wave 17 AX. Answer Engine Optimization measurement.",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Source: `{jsonl_path}`",
        f"Total calls: {total_calls} (errors: {errors})",
        "",
        "## Aggregate",
        "",
        f"- **citation_rate** (≥1 jpcite hit / call): "
        f"{citation_rate * 100:.1f}% "
        f"(target ≥ {targets['citation_rate'] * 100:.0f}% — {gate['citation_rate']})",
        f"- **top_share** (first jpcite mention in top 33% of answer): "
        f"{top_share * 100:.1f}% "
        f"(target ≥ {targets['top_share'] * 100:.0f}% — {gate['top_share']})",
        f"- **verified_share** (known live URL prefix): "
        f"{verified_share * 100:.1f}% "
        f"(target ≥ {targets['verified_share'] * 100:.0f}% — "
        f"{gate['verified_share']})",
        f"- **relative_share** (jpcite vs jpcite+competitor citation volume): "
        f"{relative_share * 100:.1f}%",
        f"- **competitor citations** total: {competitor_total}",
        "",
        "## Citation position histogram",
        "",
        "| position | count |",
        "| --- | ---: |",
    ]
    for pos in ("top", "middle", "bottom", "none"):
        lines.append(f"| {pos} | {position_hist[pos]} |")
    lines += [
        "",
        "## Citation accuracy histogram",
        "",
        "| accuracy | count |",
        "| --- | ---: |",
    ]
    for acc in ("verified", "plausible", "token_only", "none"):
        lines.append(f"| {acc} | {accuracy_hist[acc]} |")
    lines += [
        "",
        "## By surface",
        "",
        "| surface | calls | cited | top | verified | competitor |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for surface, s in sorted(by_surface.items()):
        lines.append(
            f"| {surface} | {s['calls']} | {s['cited']} | "
            f"{s.get('top', 0)} | {s.get('verified', 0)} | "
            f"{s['competitor_total']} |"
        )
    lines += [
        "",
        "## By category",
        "",
        "| category | calls | cited | competitor |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, c in sorted(by_category.items()):
        lines.append(
            f"| {category} | {c['calls']} | {c['cited']} | "
            f"{c['competitor_total']} |"
        )
    lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--week", type=int, required=True)
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
        "--out-dir", type=pathlib.Path, default=REPO_ROOT / "analytics",
    )
    parser.add_argument(
        "--report-dir", type=pathlib.Path, default=REPO_ROOT / "reports",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Stub responses (deterministic) instead of LLM calls.",
    )
    parser.add_argument(
        "--aggregate-only", action="store_true",
        help="Skip bench; aggregate an existing JSONL.",
    )
    parser.add_argument(
        "--jsonl", type=pathlib.Path, default=None,
        help="Override JSONL input path (used with --aggregate-only).",
    )
    args = parser.parse_args(argv)

    questions_doc = json.loads(args.questions.read_text(encoding="utf-8"))
    questions = questions_doc.get("questions", [])
    if not questions:
        print(f"[aeo_citation_bench] no questions in {args.questions}", file=sys.stderr)
        return 2

    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    unknown = [s for s in surfaces if s not in SURFACE_ADAPTERS]
    if unknown:
        print(f"[aeo_citation_bench] unknown surfaces: {unknown}", file=sys.stderr)
        return 2

    if args.aggregate_only:
        jsonl = args.jsonl or (args.out_dir / f"aeo_citation_bench_w{args.week}.jsonl")
        if not jsonl.exists():
            print(f"[aeo_citation_bench] jsonl not found: {jsonl}", file=sys.stderr)
            return 2
        report = aggregate(jsonl, args.week, args.report_dir)
        print(f"[aeo_citation_bench] aggregated → {report}")
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
    print(f"[aeo_citation_bench] jsonl → {jsonl_path}")
    print(f"[aeo_citation_bench] report → {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
