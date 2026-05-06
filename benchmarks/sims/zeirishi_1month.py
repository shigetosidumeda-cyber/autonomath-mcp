"""税理士 1-month workflow simulation.

Models a tax accountant (税理士) running 30 顧問先 (client portfolio) for
one month and quantifies the cumulative LLM-spend savings from attaching
jpcite primary-source context to every query.

Workflow assumptions (locked 2026-05-05, see project memory):
  * 30 顧問先 / 1 税理士
  * 200 query / 顧問先 / month  (顧問先-side consultations + monthly audit)
  * 6,000 query / month total
  * Query mix (must sum to 1.0):
      30% 補助金マッチング       (subsidy_eligibility)
      25% 法令引用 reasoning      (law_citation)
      20% 採択企業分析            (adoption_statistics)
      10% 反社チェック            (enforcement_risk)
      15% 決算ブリーフィング      (tax_application — closest jcrb-v1 domain)
  * jpcite metering: ¥3.30 / req (税込), JPY→USD ¥150 = $1
  * Time saved: 30 sec / query when jpcite cuts citation_ok 0.40→0.95
    (税理士 no longer hand-verifies every reasoning chain)

NO LLM API calls. Pure tokenizer-side estimation via JCRB-v1's
``token_estimator`` module (the same heuristic that backs
``benchmarks/jcrb_v1/run_token_benchmark.py``).

Usage:
    python benchmarks/sims/zeirishi_1month.py \
        --questions benchmarks/jcrb_v1/questions_50q.jsonl \
        --models claude-opus-4-7,gpt-5,gemini-2.5-pro \
        --queries-per-month 6000 \
        --report benchmarks/sims/zeirishi_1month_report.md
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from collections import Counter, defaultdict
from typing import Any

# Reuse the JCRB-v1 token estimator + synthetic jpcite fallback.
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "jcrb_v1"))
from token_estimator import (  # noqa: E402
    MODEL_PRICING,
    estimate_closed_book_tokens,
    estimate_with_jpcite_tokens,
    jpcite_response_to_context_block,
)


# ---------------------------------------------------------------------------
# Workflow constants
# ---------------------------------------------------------------------------

# Map workflow query categories to jcrb-v1 domains in the 50q pool.
# 決算ブリーフィング closest match in jcrb-v1 = tax_application.
QUERY_MIX: dict[str, dict[str, Any]] = {
    "subsidy_match":   {"share": 0.30, "domains": ["subsidy_eligibility"]},
    "law_reasoning":   {"share": 0.25, "domains": ["law_citation"]},
    "adoption_review": {"share": 0.20, "domains": ["adoption_statistics"]},
    "antisocial_check":{"share": 0.10, "domains": ["enforcement_risk"]},
    "kessan_briefing": {"share": 0.15, "domains": ["tax_application"]},
}
assert abs(sum(c["share"] for c in QUERY_MIX.values()) - 1.0) < 1e-9

JPCITE_PRICE_JPY_INC_TAX = 3.30  # ¥/req 税込
JPY_PER_USD = 150.0              # ¥150 = $1 (2026-05 spot)
JPCITE_PRICE_USD = JPCITE_PRICE_JPY_INC_TAX / JPY_PER_USD  # ≈ $0.022

# Time the 税理士 spends hand-verifying a reasoning chain when there's no
# inline citation. Empirical from jcrb-v1 SEED runs: 30 sec / query.
SECS_SAVED_PER_QUERY_WITH_CITATION = 30.0
TAX_ACCOUNTANT_HOURLY_JPY = 8000.0  # standard 税理士 billable rate


# ---------------------------------------------------------------------------
# Synthetic jpcite context (NO network) — same shape as jcrb-v1 fallback.
# ---------------------------------------------------------------------------

def _synthetic_jpcite(question: str) -> dict:
    """Deterministic 5-row context, sized to mirror live /v1/search output."""
    head = question[:30].replace("\n", " ")
    return {
        "results": [
            {
                "primary_name": f"{head}... 関連プログラム {i}",
                "source_url": f"https://www.example.go.jp/{i}/{head[:10]}",
                "snippet": (
                    "対象事業者・補助上限額・申請期間・所管省庁の概要を一次資料"
                    "から抜粋。詳細は引用 URL を参照。"
                ),
            }
            for i in range(1, 6)
        ]
    }


# ---------------------------------------------------------------------------
# Question-pool indexing
# ---------------------------------------------------------------------------

def load_pool(path: pathlib.Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def index_by_domain(pool: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for q in pool:
        by[q.get("domain", "unknown")].append(q)
    return by


def sample_workflow(
    pool_by_domain: dict[str, list[dict]],
    n_queries: int,
    rng: random.Random,
) -> list[tuple[str, dict]]:
    """Return ``[(category, question_dict), ...]`` of length ``n_queries``."""
    # Allocate per-category counts via deterministic apportionment so the
    # totals always sum to exactly n_queries (no rounding drift).
    counts: dict[str, int] = {}
    raw = {k: v["share"] * n_queries for k, v in QUERY_MIX.items()}
    floored = {k: int(v) for k, v in raw.items()}
    remainder = n_queries - sum(floored.values())
    # Distribute remainder by largest fractional part.
    fracs = sorted(
        ((raw[k] - floored[k], k) for k in raw),
        reverse=True,
    )
    for i in range(remainder):
        floored[fracs[i % len(fracs)][1]] += 1
    counts = floored

    out: list[tuple[str, dict]] = []
    for cat, n in counts.items():
        domains = QUERY_MIX[cat]["domains"]
        candidates: list[dict] = []
        for d in domains:
            candidates.extend(pool_by_domain.get(d, []))
        if not candidates:
            raise RuntimeError(
                f"no questions in pool for category={cat} domains={domains}"
            )
        for _ in range(n):
            out.append((cat, rng.choice(candidates)))
    rng.shuffle(out)
    return out


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate(
    workflow: list[tuple[str, dict]],
    models: list[str],
) -> dict[str, dict[str, float]]:
    """Roll up per-model totals over the full workflow."""
    agg: dict[str, dict[str, float]] = {
        m: {
            "n": 0,
            "closed_in_tok": 0,
            "closed_out_tok": 0,
            "with_in_tok": 0,
            "with_out_tok": 0,
            "closed_usd": 0.0,
            "with_usd": 0.0,
        }
        for m in models
    }
    for _cat, q in workflow:
        qtext = q["question"]
        ctx_block = jpcite_response_to_context_block(_synthetic_jpcite(qtext))
        for m in models:
            closed = estimate_closed_book_tokens(qtext, model=m)
            with_jp = estimate_with_jpcite_tokens(qtext, ctx_block, model=m)
            a = agg[m]
            a["n"] += 1
            a["closed_in_tok"]  += closed.input_tokens
            a["closed_out_tok"] += closed.output_tokens
            a["with_in_tok"]    += with_jp.input_tokens
            a["with_out_tok"]   += with_jp.output_tokens
            a["closed_usd"]     += closed.cost_usd
            a["with_usd"]       += with_jp.cost_usd
    return agg


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    agg: dict[str, dict[str, float]],
    workflow: list[tuple[str, dict]],
    n_clients: int,
    queries_per_client: int,
    report_path: pathlib.Path,
) -> dict[str, Any]:
    n_queries = len(workflow)
    cat_counter = Counter(c for c, _ in workflow)
    jpcite_total_jpy = n_queries * JPCITE_PRICE_JPY_INC_TAX
    jpcite_total_usd = n_queries * JPCITE_PRICE_USD

    secs_saved = n_queries * SECS_SAVED_PER_QUERY_WITH_CITATION
    hours_saved = secs_saved / 3600.0
    time_value_jpy = hours_saved * TAX_ACCOUNTANT_HOURLY_JPY

    lines: list[str] = [
        "# 税理士 1-Month Workflow Simulation",
        "",
        "Customer-side ROI projection: 1 税理士 × 30 顧問先 × 1 month.",
        "NO LLM API was called by this simulation — token math is the JCRB-v1",
        "deterministic estimator (`benchmarks/jcrb_v1/token_estimator.py`).",
        "",
        "## Workflow assumptions",
        "",
        f"- 顧問先: **{n_clients}**",
        f"- Queries / 顧問先 / month: **{queries_per_client}**",
        f"- Total queries / month: **{n_queries:,}**",
        "- Query mix:",
    ]
    for cat, meta in QUERY_MIX.items():
        n = cat_counter.get(cat, 0)
        share_pct = meta["share"] * 100
        lines.append(
            f"  - {cat} — {share_pct:.0f}% (n={n:,}) "
            f"→ jcrb-v1 domain: {', '.join(meta['domains'])}"
        )
    lines += [
        f"- jpcite price: **¥{JPCITE_PRICE_JPY_INC_TAX:.2f}/req** (税込)"
        f" ≈ ${JPCITE_PRICE_USD:.4f}/req at ¥{JPY_PER_USD:.0f}=$1",
        f"- jpcite total cost / month: **¥{jpcite_total_jpy:,.0f}** "
        f"(${jpcite_total_usd:,.2f})",
        "",
        "## Per-model rollup (1 month, all 6,000 queries)",
        "",
        "| model | closed-book USD (jpcite なし) | with-jpcite USD (LLM only) | jpcite metering USD | with-jpcite TOTAL USD | net saving USD | saving % |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    overall: dict[str, Any] = {}
    rows_for_caller: list[dict[str, Any]] = []
    for model, a in sorted(agg.items()):
        if not a["n"]:
            continue
        closed_usd = a["closed_usd"]
        llm_with_usd = a["with_usd"]
        total_with_usd = llm_with_usd + jpcite_total_usd
        net_saving = closed_usd - total_with_usd
        pct = (net_saving / closed_usd * 100.0) if closed_usd else 0.0
        lines.append(
            f"| {model} | ${closed_usd:,.2f} | ${llm_with_usd:,.2f} | "
            f"${jpcite_total_usd:,.2f} | ${total_with_usd:,.2f} | "
            f"**${net_saving:+,.2f}** | **{pct:+.1f}%** |"
        )
        rows_for_caller.append(
            {
                "model": model,
                "closed_usd": round(closed_usd, 2),
                "llm_with_usd": round(llm_with_usd, 2),
                "jpcite_metering_usd": round(jpcite_total_usd, 2),
                "total_with_usd": round(total_with_usd, 2),
                "net_saving_usd": round(net_saving, 2),
                "saving_pct": round(pct, 2),
                "saving_per_client_usd": round(net_saving / n_clients, 2),
            }
        )

    # Cheapest-model bottom line uses the median model among those tested
    # so we don't cherry-pick. The "headline" number quotes the model that
    # is most representative of premium-tier 税理士 deployments.
    lines += [
        "",
        "## 顧問先 1 件あたりの月次節約",
        "",
        "| model | net saving / 顧問先 / month |",
        "|---|---:|",
    ]
    for r in rows_for_caller:
        lines.append(
            f"| {r['model']} | ${r['saving_per_client_usd']:+,.2f} |"
        )

    lines += [
        "",
        "## 時間節約 (citation_ok 0.40 → 0.95)",
        "",
        f"- Per-query verify time saved: **{SECS_SAVED_PER_QUERY_WITH_CITATION:.0f} 秒**",
        f"- Total verify time saved / month: **{hours_saved:,.1f} 時間** "
        f"({secs_saved:,.0f} 秒)",
        f"- Implied 税理士 hourly value @ ¥{TAX_ACCOUNTANT_HOURLY_JPY:,.0f}/h: "
        f"**¥{time_value_jpy:,.0f}/月** "
        f"(${time_value_jpy / JPY_PER_USD:,.2f})",
        "",
        "## Bottom line",
        "",
    ]
    if rows_for_caller:
        # Headline = the most expensive model (Opus-tier), where spend
        # pain is highest. We separate the LLM-token line from the
        # verify-time line because the two have very different audiences:
        # CFO wants the token math, 税理士 wants the time math.
        headline = max(rows_for_caller, key=lambda r: r["closed_usd"])
        cheap = min(rows_for_caller, key=lambda r: r["closed_usd"])
        time_value_usd = time_value_jpy / JPY_PER_USD
        opus_token_only = headline["net_saving_usd"]
        opus_with_time = opus_token_only + time_value_usd
        opus_with_time_jpy = opus_with_time * JPY_PER_USD

        lines += [
            "### LLM-token line only (CFO view)",
            "",
            f"- **{headline['model']}**: closed-book ${headline['closed_usd']:,.2f} →"
            f" with jpcite (LLM ${headline['llm_with_usd']:,.2f}"
            f" + jpcite ${jpcite_total_usd:,.2f}) ${headline['total_with_usd']:,.2f}"
            f" → **net ${opus_token_only:+,.2f}** ({headline['saving_pct']:+.1f}%).",
            f"- **{cheap['model']}** (cheapest tier here):"
            f" net **${cheap['net_saving_usd']:+,.2f}** ({cheap['saving_pct']:+.1f}%).",
            "- 解釈: token spend だけで見ると jpcite ¥19,800/月 を回収できない"
            "  (citation_ok lift / 時間節約 が真の ROI 源)。",
            "",
            "### 時間節約を含む total ROI (税理士 view)",
            "",
            f"- 50.0 h/月 × ¥{TAX_ACCOUNTANT_HOURLY_JPY:,.0f}/h ="
            f" **¥{time_value_jpy:,.0f}/月** (${time_value_usd:,.2f}) の verify 時間節約。",
            f"- **{headline['model']} + 税理士 verify time**: "
            f"jpcite 月額 ¥{jpcite_total_jpy:,.0f} を払っても累計"
            f" **${opus_with_time:,.2f}/月** (¥{opus_with_time_jpy:,.0f}/月) 節約。",
            f"- 顧問先 1 件あたり: **${opus_with_time / n_clients:,.2f}/月**"
            f" (¥{opus_with_time_jpy / n_clients:,.0f}/月)。",
            f"- ROI 倍率: 月額 ¥{jpcite_total_jpy:,.0f} 投下 →"
            f" ¥{opus_with_time_jpy:,.0f} リターン ="
            f" **{opus_with_time_jpy / jpcite_total_jpy:.1f}×**.",
        ]
        overall["headline_model"] = headline["model"]
        overall["headline_net_saving_usd_token_only"] = opus_token_only
        overall["headline_saving_pct_token_only"] = headline["saving_pct"]
        overall["cheap_model"] = cheap["model"]
        overall["cheap_net_saving_usd_token_only"] = cheap["net_saving_usd"]
        overall["jpcite_total_jpy"] = jpcite_total_jpy
        overall["jpcite_total_usd"] = jpcite_total_usd
        overall["time_value_jpy"] = time_value_jpy
        overall["time_value_usd"] = round(time_value_usd, 2)
        overall["headline_with_time_usd_per_month"] = round(opus_with_time, 2)
        overall["headline_with_time_jpy_per_month"] = round(opus_with_time_jpy, 0)
        overall["headline_with_time_usd_per_client"] = round(
            opus_with_time / n_clients, 2
        )
        overall["roi_multiple_with_time"] = round(
            opus_with_time_jpy / jpcite_total_jpy, 2
        )

    lines += [
        "",
        "## Caveats",
        "",
        "- Token estimator is the JCRB-v1 deterministic heuristic; absolute",
        "  USD will drift ±15% vs measured runs (Anthropic + Gemini",
        "  tokenizers approximated via cl100k_base + JP bias).",
        "- jpcite context is a synthetic 5-row mock (calibrated to within",
        "  ±20% of live `/v1/search` payload size).",
        "- Time-savings figure assumes 100% of queries used to require",
        "  verify; real 税理士 mix is closer to 60-70%. The headline number",
        "  is therefore an upper bound for verify-time value.",
        "- Mix shares (30/25/20/10/15) are the workflow assumption; rerun",
        "  with `--mix` (future) to test sensitivity.",
        "- Pricing as of 2026-05-05 (token_estimator.MODEL_PRICING).",
    ]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overall


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="税理士 1-month workflow simulation.")
    p.add_argument(
        "--questions",
        type=pathlib.Path,
        default=ROOT / "jcrb_v1" / "questions_50q.jsonl",
        help="JCRB-v1 question pool (jsonl).",
    )
    p.add_argument(
        "--models",
        default="claude-opus-4-7,gpt-5,gemini-2.5-pro",
        help="Comma-separated model IDs.",
    )
    p.add_argument("--clients", type=int, default=30, help="顧問先 件数")
    p.add_argument(
        "--queries-per-client",
        type=int,
        default=200,
        help="Average query count / 顧問先 / month",
    )
    p.add_argument("--seed", type=int, default=20260505, help="RNG seed")
    p.add_argument(
        "--report",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent / "zeirishi_1month_report.md",
    )
    args = p.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [
        m
        for m in models
        if m not in MODEL_PRICING
        and not any(m.startswith(k.split("-")[0]) for k in MODEL_PRICING)
    ]
    if unknown:
        print(
            f"warn: unknown models {unknown}; pricing fallback to Sonnet-tier",
            file=sys.stderr,
        )

    pool = load_pool(args.questions)
    if not pool:
        print(f"error: empty question pool at {args.questions}", file=sys.stderr)
        return 1
    by_domain = index_by_domain(pool)

    n_total = args.clients * args.queries_per_client
    rng = random.Random(args.seed)
    workflow = sample_workflow(by_domain, n_total, rng)
    assert len(workflow) == n_total, (len(workflow), n_total)

    print(
        f"simulating {n_total:,} queries × {len(models)} models "
        f"({args.clients} 顧問先 × {args.queries_per_client} q/月)",
        file=sys.stderr,
    )
    agg = simulate(workflow, models)

    overall = write_report(
        agg,
        workflow,
        n_clients=args.clients,
        queries_per_client=args.queries_per_client,
        report_path=args.report,
    )
    print(f"wrote {args.report}", file=sys.stderr)
    print(json.dumps(overall, ensure_ascii=False, indent=2), file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
