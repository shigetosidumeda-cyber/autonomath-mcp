# Cache architecture (4-Layer L0–L4)

jpcite の API は **Pre-computed Reasoning Layer** で動作する。1 リクエストあたり ad-hoc join / FTS scan / multi-tool plan は走らず、夜間に事前計算した結果か、ホットキャッシュ行から返される。

## なぜ 4 層に分けるか

1 req は以下を amortise する:

- FTS / index lookup (~µs)
- 0+ 個のテーブル間 join (~ms)
- 0+ 個の cross-DB lookup (`jpintel.db` ⇄ `autonomath.db` は ATTACH-join 不可、2 connection 必要)
- JSON encoding (~ms — 高 cardinality enum で p95 を支配)

page cache だけでは Fly machine 再起動で cold 化、レスポンス blob だけでは rare params に storage を浪費する。よって 4 層に分割し、各層で freshness contract を持つ:

| Layer | Name | Storage | Freshness | Rebuild cost |
| ----- | ---- | ------- | --------- | ------------ |
| **L0** | Storage | Raw SQLite + FTS5 | ingest 書込時 | 数時間 (full reingest) |
| **L1** | Atomic | 単一行 lookup (PK / unique index) | live | µs |
| **L2** | Composite | テーブル間 join | live | ms |
| **L3** | Reasoner | `pc_*` materialized views | 夜次 | 数分 |
| **L4** | Cache | `l4_query_cache` blobs | 1 行ごとの TTL | µs (hit) / L3 cost (miss) |

## L0 — Storage

- `data/jpintel.db` — `programs`, `case_studies`, `loan_programs`, `enforcement_cases`, `laws`, `court_decisions`, `bids`, `tax_rulesets`, `invoice_registrants` 等
- `autonomath.db` — entity-fact EAV (503,930 entities / 6.12M facts / 177,381 relations / 335,605 aliases / 別名・略称 index / 所管庁 index / 地域 index 等)。API repo は read-only

L0 のみが ground truth。他層は projection / cache。

## L1 — Atomic

PK / unique index 単一行 lookup。b-tree depth 3-4、< 1 µs warm。L0 から直接 serve。

例:
- `SELECT * FROM programs WHERE program_id = ?`
- `SELECT * FROM laws WHERE law_id = ?`

## L2 — Composite

2-3 テーブル join、SQLite planner で single-digit ms。L3 materialized view の入力。

例:
- 法律 X を引用する programs → `programs ⨝ program_law_refs`
- 県 Y の loans → `loan_programs ⨝ region`
- FY 2025 の adoptions → `adoption_records ⨝ programs`

## L3 — Reasoner (`pc_*` 層)

multi-tool / multi-DB / aggregate query を夜次に `pc_*` テーブルへ事前計算。dimension 例: industry × top 20、47 prefectures × top 20、`law_id` → `program_ids[]` (citation graph)、`program_id` → `amendment_ids[]` (change-history)、月 × programs (deadline calendar)、collateral × top loans 等。

DELETE-then-INSERT パターンを 1 transaction で実行する nightly cron で更新。`pc_*` miss 時は L0/L1/L2 にフォールスルーするため、cache が cold な状態でも正しい結果が返る。

## L4 — Hot blob cache (`l4_query_cache`)

L3 の **上** に位置し、**serialized API response blob** をキャッシュする (rows ではない)。

```sql
CREATE TABLE l4_query_cache (
    cache_key   TEXT PRIMARY KEY,        -- sha256(tool + canonical_json(params))
    tool_name   TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    hit_count   INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT,
    ttl_seconds INTEGER NOT NULL DEFAULT 86400,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### なぜ blob か

Zipf-shaped traffic tail (top ~100 distinct param sets per tool) は steady state で全 call の ~80%。同 query を再実行する CPU 浪費を回避し、JOIN + JSON encoding + response model validation を一括でスキップ。

### Key 形

```python
def canonical_cache_key(tool_name: str, params: dict) -> str:
    payload = f"{tool_name}\n{canonical_params(params)}".encode()
    return hashlib.sha256(payload).hexdigest()
```

`canonical_params` = `json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。**hand-roll の sha256 禁止** (差分が出てキャッシュが silently miss する)。

### Read 経路

```python
from jpintel_mcp.cache import canonical_cache_key, get_or_compute

key = canonical_cache_key("search_tax_incentives", params)
result = get_or_compute(
    cache_key=key,
    tool="search_tax_incentives",
    params=params,
    compute=lambda: _real_search(params),
    ttl=86400,
)
```

hit 時はキャッシュ値を返す、miss 時は `compute()` を呼んで結果を保存。stale (TTL 期限切れ) は miss 扱い (read-on-delete はしない)。

### Write 経路 / Eviction

L4 は customer traffic が流れる中で organic に populate される (pre-launch は意図的に空)。daily cron が `usage_events` 直近 7 日から Zipf 上位を読み、必要に応じて re-warm + TTL 期限切れ sweep + soft cap (default 1000 行) で trim する。

`l4_query_cache` の 1 行は ≤ 32 KB compressed、1000 行で ~30 MB。

## Layer cooperation (read flow)

```
                     ┌────────────────────────────┐
                     │   incoming /v1 request     │
                     └──────────────┬─────────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │   L4 cache?      │ ← hash(tool, params)
                          └─────┬────────────┘
                                │ hit
                                │  └──────────────► serialised JSON ▶ response
                                │ miss
                                ▼
                          ┌──────────────────┐
                          │   L3 pc_* row?   │ ← materialized view
                          └─────┬────────────┘
                                │ hit
                                │  └──────────────► row(s) → L4 INSERT ▶ response
                                │ miss
                                ▼
                          ┌──────────────────┐
                          │   L2 join        │ ← live JOIN
                          └─────┬────────────┘
                                │
                                ▼
                          ┌──────────────────┐
                          │   L1 atomic      │ ← single-row b-tree
                          └─────┬────────────┘
                                │
                                ▼
                          ┌──────────────────┐
                          │   L0 storage     │ ← bytes on disk
                          └──────────────────┘
```

任意の層での miss は下層へフォールスルー。**cache wall は無く、cache 有無で結果は同じ**。

## Layer cooperation (write flow)

L0 は ingest で mutate。L1 / L2 は live view、別 write 経路無し。L3 は nightly に DELETE-then-INSERT で再構築。L4 は以下で invalidate される:

- TTL (default 24h、amendment-coupled tools は 1h)
- `cache.l4.invalidate_tool(tool_name)` (schema / source 変更時の明示)
- nightly refresh の sweep step
