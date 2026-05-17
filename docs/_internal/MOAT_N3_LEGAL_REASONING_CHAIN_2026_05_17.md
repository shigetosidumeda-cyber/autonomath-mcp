# Moat Lane N3 — Legal Reasoning Chain DB (2026-05-17)

SOT: this document. Migration: `scripts/migrations/wave24_202_am_legal_reasoning_chain.sql`.
Composer: `scripts/build_legal_reasoning_chain.py`. MCP: `src/jpintel_mcp/mcp/moat_lane_tools/moat_n3_reasoning.py`.
Tests: `tests/test_moat_n3_reasoning.py`. Topic taxonomy: `data/legal_topics/{税法|消費税|補助金|労務|商事}.yaml`.

## Mission

When a 税理士 / 会計士 / 法務 / 補助金コンサル agent asks "この処理は安全か?",
return a deterministic 三段論法 (syllogistic) reasoning chain backed by 法令 + 通達 + 判例 + 採決 —
no LLM inference, no hallucinated text, no fabricated citations.

## Cohort

| topic family    | label   | topic count | chain count (×5 viewpoint slices) |
| --------------- | ------- | ----------- | --------------------------------- |
| corporate_tax   | 税法    | 50          | 250                               |
| consumption_tax | 消費税  | 30          | 150                               |
| subsidy         | 補助金  | 30          | 150                               |
| labor           | 労務    | 20          | 100                               |
| commerce        | 商事    | 30          | 150                               |
| **total**       |         | **160**     | **800**                           |

Topic taxonomy is canonical in `scripts/build_legal_reasoning_chain.py :: all_topics()` and
mirrored to `data/legal_topics/*.yaml` for non-Python downstream consumers.

## Schema (migration wave24_202)

```
am_legal_reasoning_chain (
    chain_id                     TEXT PRIMARY KEY  -- LRC-<10 lowercase hex>
    topic_id                     TEXT NOT NULL     -- e.g. corporate_tax:yakuin_hosyu
    topic_label                  TEXT NOT NULL
    tax_category                 TEXT NOT NULL     -- closed taxonomy (CHECK)
    premise_law_article_ids      TEXT NOT NULL DEFAULT '[]'   -- JSON [int]
    premise_tsutatsu_ids         TEXT NOT NULL DEFAULT '[]'   -- JSON [int]
    minor_premise_judgment_ids   TEXT NOT NULL DEFAULT '[]'   -- JSON [str: HAN-* / NTA-SAI-*]
    conclusion_text              TEXT NOT NULL
    confidence                   REAL NOT NULL DEFAULT 0.5    -- CHECK 0..1
    opposing_view_text           TEXT
    citations                    TEXT NOT NULL DEFAULT '{}'   -- JSON envelope
    computed_by_model            TEXT NOT NULL DEFAULT 'rule_engine_v1'
    computed_at                  TEXT NOT NULL                -- ISO-8601 UTC
)
```

Indexes: `idx_amlrc_topic(topic_id)`, `idx_amlrc_category(tax_category, confidence DESC)`,
`idx_amlrc_computed(computed_at DESC)`. View: `v_am_legal_reasoning_chain_confident`
(confidence >= 0.6).

## Composer

Pure-Python (`scripts/build_legal_reasoning_chain.py`):

1. Open `autonomath.db` + `data/jpintel.db` (cross-DB JOIN forbidden per CLAUDE.md — open both, merge in Python).
2. For each canonical Topic, pull:
   - `am_law_article` rows matching `(law_canonical_id, article_numbers)` → 法令.
   - `am_law_article` rows on `law:*-tsutatsu` canonical ids matching `tsutatsu_article_prefix` → 通達.
   - `court_decisions` rows (jpintel.db) matching `keywords` via `key_ruling LIKE` → 判例 (HAN-*).
   - `nta_saiketsu` rows (autonomath.db) matching `keywords` via `title/decision_summary LIKE` → 採決 (NTA-SAI-*).
3. For each of the 5 viewpoint slices (`原則的取扱い / 通達上の例外 / 判例の傾向 / 実務上の留意点 / 反対説の余地`),
   compose a chain row with confidence and citation envelope.
4. `INSERT OR REPLACE INTO am_legal_reasoning_chain` so re-runs are idempotent.

Confidence rubric (deterministic, pure rule):

| signal                 | contribution |
| ---------------------- | ------------ |
| base                   | 0.50         |
| ≥1 法令 article         | +0.15        |
| ≥1 通達 reference       | +0.10        |
| ≥1 判例 or 採決         | +0.10        |
| regular slice (≠反対説) | +0.05        |
| **cap** (opposing-view or 反対説 slice) | 0.85 |

## MCP Tools

Both registered under `src/jpintel_mcp/mcp/moat_lane_tools/moat_n3_reasoning.py`:

### `get_reasoning_chain(topic, limit=10)`

* `topic` can be either an `LRC-<10 hex>` id (returns 1 chain) **or** a canonical topic slug
  (returns all 5 viewpoint slices, sorted by confidence DESC).
* Pure SQLite read-only SELECT.
* `_billing_unit=1` (¥3/req per CLAUDE.md), `_disclaimer` covers §52 / §47条の2 / §72 / §1 / §3.

### `walk_reasoning_chain(query, category="all", min_confidence=0.6, limit=10)`

* Keyword walk over `topic_label / conclusion_text / opposing_view_text / topic_id`
  via case-insensitive LIKE.
* Optional `category` filter against the closed `tax_category` taxonomy.
* Pure SQLite read-only SELECT, NO LLM inference.

## Constraints (CLAUDE.md non-negotiables)

* NO LLM API call inside the composer or the MCP wrappers.
* §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope on every response.
* ¥3 / billable unit per call.
* `chain_id` shape canonical (`LRC-<10 hex>`) — agent code can pattern-match alongside
  `TAX-<10 hex>` / `HAN-<10 hex>`.

## Re-run procedure

```bash
# Dry run (counts only, no DB write)
.venv/bin/python scripts/build_legal_reasoning_chain.py --dry-run

# Real run (idempotent INSERT OR REPLACE)
.venv/bin/python scripts/build_legal_reasoning_chain.py
```

## Test plan

`tests/test_moat_n3_reasoning.py` (24 tests, all PASS):

* Migration files exist + `-- target_db: autonomath` header check (entrypoint.sh §4 boot-loop gate).
* Table / view created + roundtrip insert.
* CHECK constraints fire on bad `chain_id` shape / `tax_category` / `confidence` bounds.
* Confident-view filter drops confidence < 0.6.
* Composer chain-id derivation is deterministic + shape `LRC-<10 hex>`.
* Topic count == 160, total chain count == 800, taxonomy distribution matches spec.
* `get_reasoning_chain` by topic_id (5 slices), by chain_id (1 row), no-match status.
* `walk_reasoning_chain` filters by keyword + category + min_confidence; returns disclaimer envelope.
* No LLM SDK imports in the module source.

## Topic taxonomy YAML

For non-Python downstream consumers (audit, JP localization, docs), the 160 topic anchors
mirror at `data/legal_topics/`:

```
data/legal_topics/
  税法.yaml      (50 topics, corporate_tax)
  消費税.yaml    (30 topics, consumption_tax)
  補助金.yaml    (30 topics, subsidy)
  労務.yaml      (20 topics, labor)
  商事.yaml      (30 topics, commerce)
```

Each YAML carries: `topic_id`, `label`, `tax_category`, `law_canonical_id`,
`article_numbers`, `tsutatsu_law_id`, `tsutatsu_article_prefix`, `keywords`,
`conclusion_text`, and optional `opposing_view_text`.

## Cost posture

| stage          | cost          |
| -------------- | ------------- |
| Migration      | 0 (DDL only)  |
| Composer run   | 0 (local SQLite, no LLM, no network) |
| MCP per-call   | ¥3 (1 billable unit, pure SQLite SELECT) |
| AWS side-effect | None         |
