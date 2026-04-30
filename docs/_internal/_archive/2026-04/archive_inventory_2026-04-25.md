# Archive inventory — 2026-04-25 (M4 K3 dead-code archive)

Source audit: `analysis_wave18/_k3_dead_code_2026-04-25.md`
Archive root: `src/jpintel_mcp/_archive/`
Operation: **archive (mv)**, NOT delete. recovery 手順は各 archive dir の `README.md` 参照。

## Table of contents

- [Summary](#summary)
- [Archive directories](#archive-directories)
- [embedding_2026-04-25/ (12 files)](#embedding_2026-04-25-12-files)
- [reasoning_2026-04-25/ (18 files)](#reasoning_2026-04-25-18-files)
- [autonomath_tools_dead_2026-04-25/ (8 files)](#autonomath_tools_dead_2026-04-25-8-files)
- [Not archived (live / active development)](#not-archived-live--active-development)
- [Verification](#verification)

## Summary

- **Total file archived**: 38 (`embedding/` 12 + `reasoning/` 18 + `autonomath_tools/` 8)
- **Method**: `mv <path> src/jpintel_mcp/_archive/<wave>_2026-04-25/`
- **Rationale**: K3 audit confirmed these modules have 0 import references from `src/`, `tests/`, `scripts/` (excluding intra-archive cross-references)
- **L5 wired modules retained**: `envelope_wrapper.py`, `tools_envelope.py`, `cs_features.py`
- **Phase A active retained**: `static_resources_tool.py`, `static_resources.py`, `template_tool.py`, `health_tool.py`
- **Pytest regression**: 1144 passed, 4 pre-existing failures (healthcare/real_estate tool count drift due to 36協定 gate, NOT caused by archive)

## Archive directories

| dir | files | original wave | archive reason |
| --- | --- | --- | --- |
| `embedding_2026-04-25/` | 12 | Wave 4 | 設計のみ実装、本番 path 未接続 |
| `reasoning_2026-04-25/` | 18 | Layer 7 v0.1.0 | スケルトンのみ、`__version__` 以外何も export しない |
| `autonomath_tools_dead_2026-04-25/` | 8 | Wave 6/8/9/14/17 + dd_v8 | `__init__.py` register list に含まれない 8 stub |

## embedding_2026-04-25/ (12 files)

| file | LOC | original purpose | archive reason | revive when |
| --- | --- | --- | --- | --- |
| `__init__.py` | small | lazy re-export hub | 0 consumer | embedding を本番に載せる時 |
| `config.py` | small | DB_PATH / DEFAULT_MODEL | 同上 | 同上 |
| `db.py` | medium | sqlite-vec wrapper | 同上 | sqlite-vec を別 path で使うとき |
| `facet_synthesis.py` | large | Tier B facet 自動生成 | 同上 | am_entities backfill で使うとき |
| `model.py` | medium | e5-small loader | 同上 | encoder を本番投入時 |
| `query_cache.py` | small | LRU cache | 同上 | smart_search 経由で使うとき |
| `records.py` | medium | record encoder | 同上 | 同上 |
| `rerank.py` | medium | cross-encoder reranker | 同上 | reranker 採用判断時 |
| `schema.sql` | small | embedding 内 sqlite schema | 同上 | sqlite-vec 起動時 |
| `search.py` | large | hybrid 検索 | 同上 | 同上 |
| `smart_search.py` | large | full retrieval API | 同上 | 同上 |
| `unigram_fallback.py` | small | unigram 検索 fallback | `unigram_search.py` 連鎖 dead | unigram_search 復活時 |

## reasoning_2026-04-25/ (18 files)

| file | LOC | original purpose | archive reason | revive when |
| --- | --- | --- | --- | --- |
| `__init__.py` | tiny | `__version__ = "0.1.0"` のみ | 0 consumer | reasoning を本番に載せる時 |
| `bind_i01.py` ... `bind_i10.py` | medium | 10 intent decision trees | 同上 | bind_registry を本番 routing で使うとき |
| `bind_registry.py` | medium | registry index | 同上 | 同上 |
| `bound_samples.py` | medium | precomputed bound samples | 同上 | 同上 |
| `match.py` | medium | match scorer | 同上 | retrieval ranking 投入時 |
| `precompute.py` | medium | graph cache builder | 同上 | offline cache build flow 採用時 |
| `query_route.py` | medium | route() entrypoint | `envelope_wrapper.py` の soft import (top-level path、必ず ImportError) | envelope_wrapper の explain_empty 生成で正式採用時 |
| `query_types.py` | small | enum | 同上 | 同上 |
| `samples.py` | medium | raw training samples | 同上 | 同上 |

`trees/` subdir も含む (decision tree pickle artifacts)。

## autonomath_tools_dead_2026-04-25/ (8 files)

| file | wave | original purpose | archive reason | revive when |
| --- | --- | --- | --- | --- |
| `acceptance_stats_tool.py` | Wave 8 #1 | `search_acceptance_stats` stub | `tools.search_acceptance_stats_am` + `server.search_acceptance_stats` thin re-export で代替済 | 別 cross-DB JOIN entrypoint が必要時 (revival ほぼ不要) |
| `sib_tool.py` | Wave 9+ Agent #8 | SIB/PFS 検索 | `autonomath_wrappers.py` で intentionally skipped | `am_sib_contract` 200+ rows 安定後 |
| `cache.py` | Wave 14 Agent #5 | hot query caching | `cache/l4.py` と二重実装 | autonomath_tools 局所 cache に統一する判断時 (想定無し) |
| `batch_tool.py` | dd_v8 | /v1/batch entrypoint | router 未 mount、MCP `am_batch_execute` 未 register | batch SKU を launch surface に追加時 |
| `batch_handler.py` | dd_v8 | batch_tool helper | `batch_tool.py` 連鎖 dead | batch_tool 復活時 |
| `prompt_injection_sanitizer.py` | Wave 17 baseline | prompt-injection 検出 | `response_sanitizer.py` 連鎖 dead | response_sanitizer 採用時 |
| `response_sanitizer.py` | Wave 17 | response-time sanitizer | `api/response_sanitizer.py` middleware と二重 | middleware を捨てて MCP-side に統合する判断時 |
| `unigram_search.py` | Wave 6 #1 | unigram FTS wrapper | `embedding/unigram_fallback.py` (dead) からのみ参照 | embedding/ 復活時 (連鎖 revive) |

## Not archived (live / active development)

K3 で「真の dead」と挙がっていたが **L5 wiring または Phase A active のため retain**:

- `mcp/autonomath_tools/envelope_wrapper.py` — L5 で `mcp/server.py:723` + `api/autonomath.py:108` から import 済 (live)
- `mcp/autonomath_tools/tools_envelope.py` — task instruction で「L5 wire 後 alive、archive しない」(envelope_wrapper のみ実 import、tools_envelope は同 wave 同梱で retain)
- `mcp/autonomath_tools/cs_features.py` — `scripts/cron/predictive_billing_alert.py:49` から import 済 (live)
- `mcp/autonomath_tools/static_resources.py` — `static_resources_tool.py` から import (Phase A active)
- `mcp/autonomath_tools/static_resources_tool.py` / `template_tool.py` / `health_tool.py` — Phase A active、`__init__.py` register list 入り
- `models/` / `utils/` / `templates/` / `data/autonomath_static/` — absorption CLI active development

K3 で「launch 前 wiring or 削除判断」と挙がった以下も touch せず別 ticket 行き:
- `api/_health_deep.py` — 未 mount だが `/v1/am/health/deep` (deep_health_am MCP tool) は live、`_health_deep.py` 自体は別 router 案
- `api/compliance.py`, `api/widget_auth.py` — 未 mount。launch product 判断要 (M4 scope 外)

## Verification

Post-archive checks executed:
```bash
# 0 references to archived modules from active code
grep -rn "from jpintel_mcp.embedding\|jpintel_mcp\.embedding\." src/ tests/ scripts/ \
  | grep -v "_archive/"
# returns: 0 lines

grep -rn "from jpintel_mcp.reasoning\|jpintel_mcp\.reasoning\." src/ tests/ scripts/ \
  | grep -v "_archive/"
# returns: 0 lines

# Pytest regression
.venv/bin/pytest tests/ --ignore=tests/e2e -q
# 1144 passed, 4 failed (pre-existing healthcare/real_estate count drift), 8 skipped
# 4 failures are NOT regression — they expect tool count 66/72 but the 36協定 gate
# (AUTONOMATH_36_KYOTEI_ENABLED=False default) keeps render_36_kyotei_am +
# get_36_kyotei_metadata_am hidden, dropping count to 64/70.
```

## Reference

- K3 audit: `analysis_wave18/_k3_dead_code_2026-04-25.md`
- L5 wiring: `mcp/server.py:695-723`, `api/autonomath.py:101-108`
- 36協定 gate: `CLAUDE.md` Phase A absorption section
