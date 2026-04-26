# jpintel-mcp public evaluation suite

A reproducible, gold-standard recall/precision benchmark for AutonoMath's
MCP tools. Anyone can clone this repo, run `python evals/run.py`, and see
exactly how the live tools score against a frozen set of canonical
queries.

This is in the repo for three reasons:

1. **Public transparency.** Reviewers (MCP registry, registry of registries,
   future enterprise customers) can verify tool quality without having to
   take our marketing copy at face value.
2. **Regression catcher.** CI runs the suite on every PR. A migration that
   silently re-orders FTS5 results, a tier filter that flips an X-tier row
   into the default response, or a `prescreen_programs` ranking change all
   show up as a failed query.
3. **Trust signal for downstream agents.** AutonoMath ships into Claude
   Desktop, Cursor, ChatGPT, etc. Each agent's correctness depends on our
   tools doing what their docs claim. The eval suite is our standing
   demonstration that we still do.

## Quick start

```bash
# From repo root, with the project venv (.venv/bin/python).
.venv/bin/python evals/run.py

# JSON output (for CI logs):
.venv/bin/python evals/run.py --json

# Subset of queries (substring match on id):
.venv/bin/python evals/run.py --filter agri_
.venv/bin/python evals/run.py --filter pref_005

# Use a different DB:
JPINTEL_DB=/path/to/snapshot.db .venv/bin/python evals/run.py
```

Exit code is `0` on a clean pass, `1` on any failure. The suite is fast:
~1.5 s wall clock on a stock M-series Mac for the full 49 queries.

## Anatomy of a gold query

All queries live in [`gold.yaml`](./gold.yaml). One entry looks like:

```yaml
- id: it_001_donyu_subsidy
  query_text: IT導入補助金について最新の情報を教えてください。
  tool_name: search_programs
  tool_args:
    q: IT導入補助金
    tier: [S, A, B]
    limit: 10
    fields: minimal
  expected_ids:
    - UNI-3ff8188a8e
    - UNI-71f6029070
    - UNI-d17980c957
    # ... 7 more
  forbidden_ids:
    - UNI-158e0bb965    # tier=X excluded; MUST NOT appear
  min_precision_at_10: 0.7
  note: |
    The exclusion test: UNI-158e0bb965 is tier=X 'IT導入補助金2024（セキュリティ
    対策推進枠）' and must be filtered. Regression here = silent inclusion of
    quarantined rows = trust kill.
```

Field reference:

| Field | Meaning |
|---|---|
| `id` | Stable slug used in CI logs. Use `<category>_NNN_<short>`. |
| `query_text` | Japanese natural-language question (the user story). Documentation only — the runner does NOT parse this; it calls `tool_name(**tool_args)` directly. |
| `tool_name` | Which MCP tool a correct agent should select for this query. Must match a function name in `src/jpintel_mcp/mcp/server.py`. |
| `tool_args` | Literal kwargs that the runner passes into the tool. |
| `expected_ids` | The IDs we expect to see in the top-K of the response (recall). Generated from a real run against the live DB; not hand-curated wishes. |
| `forbidden_ids` | IDs that MUST NOT appear in the top-K. Their presence fails the query irrespective of `min_precision_at_10`. Use this for tier=X exclusion tests, opposite-prefecture leakage, etc. |
| `min_precision_at_10` | Pass threshold. `0.7` means at least 7 of the top 10 returned IDs must be in `expected_ids`. Use `0.0` for diagnostic queries (edge cases) where you only care that the call doesn't crash. |
| `note` | Why this query is interesting; what bug a regression would imply. Surfaced in `--json` output so reviewers don't have to dig. |

## Categories

Queries are grouped by use case so a partial run (`--filter agri_`) is
meaningful by itself. Current breakdown:

| Prefix | Count | What it tests |
|---|---|---|
| `agri_` | 8 | Original niche: 認定新規就農者 / 6次産業 / 園芸 / スマート農業 / 中山間 / prefecture-narrowed agri |
| `mfg_` | 6 | ものづくり / 事業再構築 / 設備投資 funding_purpose / 研究開発 / national kikai filter / 中小企業投資促進税制 |
| `it_` | 4 | IT導入補助金 (with tier=X exclusion test) / DX short query / サイバーセキュリティ / デジタル化 |
| `startup_` | 4 | 創業 / スタートアップ / 事業承継 / 無担保融資 |
| `pref_` | 8 | Tokyo / Osaka / Hokkaido / Okinawa / Ishikawa / Aichi / Fukuoka / Hyogo |
| `tax_` | 3 | インボイス制度 / 中小企業税制 / 8% 経過措置 |
| `loan_` | 2 | 3-axis no-collat-no-3rd-party / startup loans |
| `case_` | 3 | ものづくり recipients / 北海道製造業 / 事業再構築 recipients |
| `prescreen_` | 3 | profile→ranked match for Tokyo IT sole-prop / Hokkaido mfg corp / Okinawa agri corp |
| `enforcement_` | 1 | 東京都 行政処分 / 不正受給 |
| `cross_` | 3 | 法人番号 invoice lookup / dd_profile_am 単一企業 / 海外展開 |
| `edge_` | 4 | unknown prefecture (typo) / empty q / short query (KANA expansion) / amount=5 boundary |
| **Total** | **49** | |

## Adding a new query

The cardinal rule: **don't make up `expected_ids`.** Generate them by
actually calling the tool against the live DB.

```python
# Probe shell snippet — adapt and paste:
import sys, os, logging
sys.path.insert(0, "src")
os.environ["JPINTEL_DB"] = "data/jpintel.db"
logging.disable(logging.WARNING)
from jpintel_mcp.mcp import server as srv

res = srv.search_programs(
    q="<your query>",
    tier=["S", "A", "B"],
    limit=10,
    fields="minimal",
)
ids = [r["unified_id"] for r in res["results"]]
print(ids, "total:", res["total"])
```

Paste those IDs into a new entry in `gold.yaml`. Pick `min_precision_at_10`
based on `total`:

- `total >= 20` → `0.7` (clean ranking expected)
- `total ~ 5–20` → `0.4–0.6` (recall-limited)
- `total < 5` → `0.1–0.3` or set `expected_ids: []` and use 0.0 (diagnostic)

Always write a `note` explaining what real bug this query would catch. A
query that "just runs without crashing" is allowed (set
`min_precision_at_10: 0.0`) but flag it explicitly.

## When a query fails

The runner prints something like:

```
Failures:
  - it_001_donyu_subsidy             p@10=0.40 (min=0.70) status=fail
      actual_top:    ['UNI-3ff8188a8e', 'UNI-71f6029070', ...]
```

Triage path:

1. **Did the data drift?** Run `sqlite3 data/jpintel.db "SELECT tier, COUNT(*) FROM programs WHERE primary_name LIKE '%IT導入%' GROUP BY tier"`. If a row's tier changed S→C, the gold list has stale rankings. Update `expected_ids` and add a CHANGELOG entry.
2. **Did the tool change behavior?** Run `git log -- src/jpintel_mcp/api/programs.py` for recent FTS / scoring changes. If the change is intentional, regenerate the gold IDs as above.
3. **Did a forbidden ID appear?** That's a real regression — a tier=X row leaked through, an opposite-prefecture row hijacked FTS, or `include_excluded` flipped to `True` somewhere. Block the deploy and root-cause it.

## Snapshot date

The current `gold.yaml` was generated against `data/jpintel.db` on
**2026-04-25** with the following counts:

```
SELECT COUNT(*) FROM programs;            -- 12,038 (excluded=0: 9,998)
SELECT COUNT(*) FROM case_studies;        --  2,286
SELECT COUNT(*) FROM loan_programs;       --    108
SELECT COUNT(*) FROM enforcement_cases;   --  1,185
SELECT COUNT(*) FROM tax_rulesets;        --     35
SELECT COUNT(*) FROM invoice_registrants; -- 13,801
```

When the data set grows materially (new ingest run, expansion-table
backfill), expect some `expected_ids` lists to need refresh. We are NOT
going to rewrite the suite to "always pass" — we'll re-snapshot with a
visible CHANGELOG entry, so historical pass rates stay comparable.

## License

The eval suite (queries + runner + this README) is MIT-licensed, same as
the rest of the repo. Public domain in spirit: copy it, fork it, snapshot
your own gold lists.
