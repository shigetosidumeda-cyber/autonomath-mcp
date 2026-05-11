# GEO weekly bench methodology v3

Status: measurement protocol for **Generative Engine Optimization** —
how often jpcite is cited when an AI surface (ChatGPT / Claude / Cursor / Codex / Gemini)
is asked a Japanese question in our target query distribution.

> Harness: `scripts/ops/geo_weekly_bench_v3.py`
> Question corpus: `data/geo_questions.json` (100 ja + 4 en overflow, schema_version 1.0)
> Output dir: `docs/bench/geo_week_{ISO_WEEK}.{json,md}`

This document specifies how to run the bench. It does NOT publish results.
Results are the per-week artifacts in `docs/bench/`.

## 0. Why this bench exists

jpcite's acquisition strategy is **100% organic** (memory:
`feedback_organic_only_no_ads`). The single most important leading
indicator for organic growth on AI surfaces is **whether the AI cites jpcite**
when a user asks a question we should plausibly own. The weekly bench
quantifies that for 5 surfaces × 5 question categories so we can see
SEO/GEO copy changes show up as citation-rate deltas.

## 1. Non-negotiable constraints

These constraints come from `MEMORY.md` and shape the entire design:

1. **No LLM API import.** Anthropic / OpenAI / Google SDK の import 完全禁止
   (memory: `feedback_no_operator_llm_api`, `feedback_autonomath_no_api_use`).
   We charge ¥3/req. If the harness itself calls an LLM API we are
   immediately under water on every benchmark run. The CI guard
   `tests/test_no_llm_in_production.py` already enforces this for
   `src/` / `scripts/cron/` / `scripts/etl/`; the GEO bench harness
   lives under `scripts/ops/` and follows the same rule voluntarily.
2. **Organic only.** No paid acquisition, no sales call, no cold outreach.
   The bench is a measurement instrument — it does not write to any
   surface, does not optimize copy automatically, does not send anything
   to a third party. SEO / GEO copy changes are tracked under
   `docs/_internal/seo_geo_strategy.md` and applied by the operator.
3. **破壊なき整理整頓** (memory: `feedback_destruction_free_organization`).
   Existing GEO artifacts (`tests/geo/bench_harness.py`,
   `.github/workflows/geo_eval.yml`,
   `analytics/geo_baseline_2026-04-29.jsonl`) stay in place. v3 lives
   beside them as a parallel weekly cadence; no file is moved or deleted.

## 2. Measurement method: CSV import (not WebFetch)

### 2.1 Decision

The harness reads **CSV files filled in by the operator** —
one CSV per surface per ISO week — and computes citation rates from those.
No automated browser walk, no API call, no scraping.

### 2.2 Why CSV import beats WebFetch in this context

We considered a `WebFetch` based path (have Claude Code's WebFetch tool
walk the public search UI for each surface and parse the rendered
response). We rejected it for three reasons:

1. **No clean public endpoint.** None of the 5 target surfaces expose a
   stable, login-less HTTP endpoint that returns a citation-bearing
   answer for an arbitrary Japanese query. Each one requires a session
   token or a logged-in browser session; "公開検索 UI 直叩き" is in
   practice indistinguishable from a bot.
2. **ToS exposure.** Memory `feedback_data_collection_tos_ignore`
   explicitly scopes "ignore ToS for the sake of acquisition" to
   **government data** (METI / JST / e-Gov etc.). It does NOT extend to
   LLM SaaS web UIs. Treating ChatGPT / Claude / Gemini's web UI as a
   public corpus would put the operator under Anthropic / OpenAI /
   Google's bot ToS in the wrong direction.
3. **Manual cost is bounded.** 100 questions × 5 surfaces × weekly =
   500 prompts/week. At ~30 seconds per prompt (paste, wait, copy answer)
   that is 4 hours/week of human time — acceptable for a weekly measure
   and less risky than a brittle browser-automation surface.

### 2.3 What "citation" means in v3

`jpcite_cited = True` for a question/surface pair iff **any** of the
following hold:

- `response_text` contains, case-insensitive, one of:
  `jpcite.com` / `jpcite` / `autonomath-mcp` / `zeimu-kaikei.ai`
  / `api.jpcite.com`.
- `citation_url` column on the row contains one of the above hosts.

Note that this includes the legacy distribution name `autonomath-mcp` and
the legacy domain `zeimu-kaikei.ai` (memory:
`feedback_legacy_brand_marker` — keep these as recognition markers,
not as front-line brand strings).

When `jpcite_cited=True` and the `citation_url` column is empty, the
harness will attempt to extract the first jpcite-host URL from
`response_text` via regex and fill it into the JSON output. If no
clickable URL is present, `citation_url=null` is recorded (text-only mention).

## 3. CSV contract

Path: `data/geo_responses/{surface}_{ISO_WEEK}.csv`
Encoding: UTF-8, newline-terminated, CSV with standard quoting.

Header (required, exact order):

```
question_id,response_text,citation_url,citation_position
```

| column | type | required | meaning |
|---|---|---|---|
| `question_id` | str | yes | matches `id` in `data/geo_questions.json` (e.g. `B01`, `S17`, `D14`, `R11`, `C20`) |
| `response_text` | str | yes if answered | raw response from the surface; multi-line allowed inside CSV quotes |
| `citation_url` | str | no | optional explicit citation URL; if empty the harness greps `response_text` |
| `citation_position` | int | no | 1-indexed position in the surface's citation list (left blank for surfaces that don't render an explicit list) |

Empty `response_text` means "not answered this week" — that row is
excluded from both `answered_count` and `cited_count` denominators.

To generate a blank scaffold:

```bash
python3 scripts/ops/geo_weekly_bench_v3.py --emit-template chatgpt --week 2026-W19
```

repeated for each of `chatgpt`, `claude`, `cursor`, `codex`, `gemini`.

## 4. Surfaces

| surface key | UI used | login |
|---|---|---|
| `chatgpt` | chat.openai.com (GPT-4o default model, web search ON) | required |
| `claude` | claude.ai (Sonnet 4 default, web search ON) | required |
| `cursor` | Cursor IDE chat (default model) | required |
| `codex` | OpenAI Codex CLI / Code Interpreter mode | required |
| `gemini` | gemini.google.com (default 1.5/2.x, grounding ON) | required |

The set is deliberately 5: it covers the two biggest consumer surfaces
(ChatGPT, Gemini), the agentic-coding surfaces where we actually ship
an MCP (Claude, Cursor, Codex), and avoids surfaces where we have no
practical way for a user to cite an MCP (e.g. Bing Copilot).

## 5. Output schema

### 5.1 JSON — `docs/bench/geo_week_{ISO_WEEK}.json`

```json
{
  "schema_version": "geo_weekly_v3",
  "week": "2026-W19",
  "generated_at": "2026-05-11T...",
  "method": "csv_import",
  "harness": "scripts/ops/geo_weekly_bench_v3.py",
  "input_dir": "data/geo_responses",
  "total_questions": 104,
  "surfaces": {
    "chatgpt": {
      "surface": "chatgpt",
      "week": "2026-W19",
      "csv_present": true,
      "answered_count": 100,
      "total_questions": 104,
      "cited_count": 17,
      "citation_rate_pct": 17.00,
      "by_category": {
        "branded":            {"answered": 20, "cited": 14, "citation_rate_pct": 70.0, "prefix": "B"},
        "non-branded.business": {"answered": 25, "cited": 1,  "citation_rate_pct": 4.0,  "prefix": "S"},
        "non-branded.data":     {"answered": 20, "cited": 0,  "citation_rate_pct": 0.0,  "prefix": "D"},
        "non-branded.subsidy":  {"answered": 15, "cited": 1,  "citation_rate_pct": 6.67, "prefix": "R"},
        "competitor":           {"answered": 20, "cited": 1,  "citation_rate_pct": 5.0,  "prefix": "C"}
      },
      "per_question": [
        {"question_id":"B01","category":"branded","jpcite_cited":true,"citation_url":"https://jpcite.com/...","citation_position":3},
        ...
      ]
    },
    "claude":  { ... },
    "cursor":  { ... },
    "codex":   { ... },
    "gemini":  { ... }
  },
  "prev_week": {
    "chatgpt": 12.0, "claude": 9.0, "cursor": 14.0, "codex": 8.0, "gemini": 5.0,
    "__by_cat__": { "chatgpt": { "branded": 60.0, ... }, ... }
  },
  "trend_4w": {
    "2026-W16": { "chatgpt": 5.0, "claude": 4.0, ... },
    "2026-W17": { "chatgpt": 8.0, "claude": 6.0, ... },
    "2026-W18": { "chatgpt": 12.0, "claude": 9.0, ... },
    "2026-W19": { "chatgpt": 17.0, "claude": 11.0, ... }
  },
  "constraints": {
    "no_llm_api_import": true,
    "method": "user pastes surface responses into CSV; harness only greps for citation",
    "policy_refs": ["feedback_no_operator_llm_api","feedback_autonomath_no_api_use","feedback_destruction_free_organization"]
  }
}
```

### 5.2 Markdown — `docs/bench/geo_week_{ISO_WEEK}.md`

Auto-rendered from the JSON. Contains:

1. **Surface 別 citation rate** with `Δ vs 前週` (percentage-point delta).
2. **Category 別 citation rate** (B/S/D/R/C) as a 5×5 grid.
3. **4 週 trend** (oldest → newest) per surface — `—` for missing weeks.
4. Reminder of the no-API constraint and pointer to the CSV input
   contract.

## 6. Weekly operator workflow

Reference workflow for the 5-surface walk on a given ISO week (default:
current week):

```bash
WEEK=$(python3 -c 'from datetime import date; y,w,_=date.today().isocalendar(); print(f"{y:04d}-W{w:02d}")')

# 1. Emit 5 blank CSVs into data/geo_responses/
for s in chatgpt claude cursor codex gemini; do
  python3 scripts/ops/geo_weekly_bench_v3.py --emit-template $s --week $WEEK
done

# 2. Walk each surface manually (browser / IDE), pasting response_text per row.
#    Optionally fill citation_url + citation_position when the surface renders an explicit list.

# 3. Aggregate
python3 scripts/ops/geo_weekly_bench_v3.py --week $WEEK

# 4. Review docs/bench/geo_week_$WEEK.{json,md} and commit alongside the week's notes
```

If a CSV is partially filled (some rows blank), aggregation still
succeeds — blank rows are counted under `total_questions` but not under
`answered_count`, so `citation_rate_pct` is computed against the
answered subset and remains comparable across surfaces with partial data.

## 7. Interpretation rules

- **B (branded)** citation rate is the most direct GEO signal — when a
  user explicitly asks about jpcite, do AI surfaces actually cite us?
  Target floor: 70%+ once SEO/GEO copy + llms.txt + facts_registry are
  shipped (per `docs/_internal/seo_geo_strategy.md`).
- **S / D / R (non-branded)** is the harder, longer-tail GEO signal:
  when the user asks a business / data / subsidy question that jpcite
  is positioned to answer, do AI surfaces reach for us? This is the
  metric SEO copy work actually moves.
- **C (competitor)** rate measures whether AI surfaces include jpcite
  in comparison tables next to gBizINFO / TDB / TSR / J-Grants. Useful
  as a leading indicator for awareness in the AI surface's index.
- **4-week trend** is more reliable than week-over-week delta. We do
  not chase single-week swings; we look for a 3+ week sustained
  direction before acting on copy.
- **DO NOT publish a headline citation-rate %.** This benchmark is for
  internal direction-finding. Public claims about citation behavior
  require a paired A/B run with a documented prompt scaffold per
  `docs/bench_methodology.md` rules.

## 8. Coexistence with pre-existing GEO artifacts

Per memory `feedback_destruction_free_organization`, v3 does not
displace earlier work:

- `tests/geo/bench_harness.py` — stub used by `.github/workflows/geo_eval.yml`.
  Untouched.
- `.github/workflows/geo_eval.yml` — runs the stub on a weekly cron.
  Untouched.
- `analytics/geo_baseline_2026-04-29.jsonl` — 2026-04-29 baseline.
  Untouched, referenced as historical state.
- `reports/geo_bench_stub_*.jsonl` — old stub outputs. Untouched.

v3 outputs live under a new `docs/bench/` path and a new
`data/geo_responses/` input dir; nothing in this rollout writes to the
locations the legacy artifacts read from.

## 9. Future work (deferred, optional)

- **WebFetch fallback**: if a surface ever exposes a clean public answer
  endpoint, the harness can grow a per-surface adapter that the operator
  runs out-of-band and pipes into the same CSV contract. The CSV format
  is the stable contract — the manual UI walk is implementation detail.
- **Lint of `response_text` for hallucinated jpcite URLs**: today we
  treat any `jpcite.com` mention as a positive citation. A future
  upgrade can HEAD-check the URL via `urllib` and downgrade obvious
  hallucinations (`jpcite.com/foo` that 404s) to a separate
  `cited_but_404` bucket. Out of scope for v3.
- **Per-prompt timestamp**: today rows do not carry an answer timestamp.
  When ChatGPT/Claude version changes mid-week we may want this. Out of
  scope for v3.
