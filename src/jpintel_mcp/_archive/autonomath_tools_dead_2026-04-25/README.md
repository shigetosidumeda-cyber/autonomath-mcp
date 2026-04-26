# autonomath_tools dead modules — archived 2026-04-25

## Why archived
K3 audit (`analysis_wave18/_k3_dead_code_2026-04-25.md`) で「真の dead」と判定した `mcp/autonomath_tools/` 直下 8 file。`__init__.py` の register list (annotation_tools / autonomath_wrappers / health_tool / provenance_tools / static_resources_tool / sunset_tool / tax_rule_tool / template_tool / tools / validation_tools) に**含まれない**ため、MCP tool surface に出ない / API router に出ない / 他の active module からも参照されない。

L5 が wire した `envelope_wrapper.py` / `tools_envelope.py` / `cs_features.py` は **archive せず alive 扱い**。Phase A active な `static_resources_tool.py` / `static_resources.py` / `template_tool.py` / `health_tool.py` も touch しない。

## Files (8)

| file | wave/起源 | 元の purpose | archive reason |
| --- | --- | --- | --- |
| `acceptance_stats_tool.py` | Wave 8 #1 | `search_acceptance_stats` MCP tool stub | `__init__.py` import 無し。`tools.search_acceptance_stats_am` + `server.search_acceptance_stats` 再 export で代替済み |
| `sib_tool.py` | Wave 9+ Agent #8 | SIB / PFS 契約検索 | `autonomath_wrappers.py` の comment で "intentionally skipped — am_sib_contract has 35 rows but tool not yet stabilized" 明記 |
| `cache.py` | Wave 14 Agent #5 | hot query caching layer | 0 consumer。`cache/l4.py` と二重実装 |
| `batch_tool.py` | dd_v8 | `/v1/batch` MCP entrypoint stub | api 側に router 無し、`am_batch_execute` も未 register |
| `batch_handler.py` | dd_v8 | batch_tool 内部 helper | `batch_tool.py` (これも dead) からのみ参照 |
| `prompt_injection_sanitizer.py` | Wave 17 baseline | prompt-injection 検出器 | `response_sanitizer.py` (これも dead) からのみ参照 |
| `response_sanitizer.py` | Wave 17 | response-time sanitizer | `api/response_sanitizer.py` middleware と二重。MCP server.py から呼ばれない |
| `unigram_search.py` | Wave 6 #1 | am_entities_fts unigram wrapper | `embedding/unigram_fallback.py` (これも dead) からのみ参照 |

## When to revive

**`acceptance_stats_tool`** — `search_acceptance_stats_am` の cross-DB JOIN を強化したくなり、別 entrypoint で walk したいとき。但し既存の thin re-export (`server.search_acceptance_stats`) が同等の surface を提供しているので revival はほぼ不要。

**`sib_tool`** — `am_sib_contract` を 200 rows 以上に拡充して安定 query が立ったとき。`autonomath_wrappers.py` の skip comment を消して `from .sib_tool import search_sib_programs` を有効化する。

**`cache`** — `cache/l4.py` 経路を捨てて autonomath_tools 局所 cache に統一したい場合 (現行 launch では l4 を維持するので revival 想定無し)。

**`batch_tool` + `batch_handler`** — `/v1/batch` REST endpoint または `am_batch_execute` MCP tool を launch surface に出す判断が下りたとき (現状は ¥3/req metered のみ、batch SKU は post-launch 検討)。

**`prompt_injection_sanitizer` + `response_sanitizer`** — `api/response_sanitizer.py` middleware を捨てて MCP-side sanitizer に統合したい場合 (二重実装解消のリファクタ。現状は middleware 側で十分)。

**`unigram_search`** — `embedding/` を revive して unigram fallback を再投入する場合 (連鎖 revive)。

## Recovery steps
```bash
# 個別 file
mv src/jpintel_mcp/_archive/autonomath_tools_dead_2026-04-25/<file>.py \
   src/jpintel_mcp/mcp/autonomath_tools/<file>.py
# 必要なら mcp/autonomath_tools/__init__.py の `from . import (...)` に追加
.venv/bin/pytest tests/test_autonomath_tools.py tests/mcp/ -q
```
