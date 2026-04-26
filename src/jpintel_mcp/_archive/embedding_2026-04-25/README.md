# embedding/ — archived 2026-04-25

## Why archived
Wave 4 大型 unimplement. 設計のみ実装で本番 path に 1 度も流れていない。
K3 audit (`analysis_wave18/_k3_dead_code_2026-04-25.md`) confirmed:
- `from jpintel_mcp.embedding import …` 直接 import は src/ tests/ scripts/ 全体で 0 件
- `embedding/__init__.py` の lazy re-export (config / smart_search / rerank / query_cache) を呼ぶ consumer も 0
- 内部 cross-imports のみで自己完結 (smart_search ↔ unigram_fallback ↔ query_cache 等)

本番 launch (2026-05-06) は FTS5 trigram + sqlite-vec で 6 ヶ月戦える前提。
embedding/ は post-launch wave で wiring or 最終削除を判定する。

## When to revive
- `from jpintel_mcp.embedding.smart_search import smart_search` を `mcp/server.py` のいずれかの search_* tool で wire したくなったとき
- e5-small / cross-encoder reranker を本番に投入する判断 (model 500MB 上限の余地確認要)
- Tier B facet 自動生成 (`facet_synthesis.py`) を am_entities backfill に使うとき

## Recovery steps
```bash
mv src/jpintel_mcp/_archive/embedding_2026-04-25 src/jpintel_mcp/embedding
# 必要なら `pip install sentence-transformers sqlite-vec` を再確認
.venv/bin/pytest tests/ --ignore=tests/e2e -q
```

## Files (12)
- `__init__.py` lazy re-export hub
- `config.py` DB_PATH / DEFAULT_MODEL
- `db.py` sqlite-vec wrapper
- `facet_synthesis.py` Tier B facet 生成
- `model.py` e5-small loader
- `query_cache.py` LRU cache
- `records.py` record encoder
- `rerank.py` cross-encoder reranker
- `schema.sql` embedding/ 内 sqlite schema
- `search.py` hybrid 検索
- `smart_search.py` full retrieval API
- `unigram_fallback.py` `unigram_search.py` 連鎖 (K3 listed)
