# W19 — Python 3.12 並走 venv (`.venv312/`)

**作成日**: 2026-05-05
**対象**: corpus pre-embedding (`tools/offline/embed_corpus_local.py`)
**operator-only**: 本番 import path には登場しない

## 作成理由

既存 `.venv/` は **Python 3.13.12** で構築されており、`torch` の安定版 wheel が
PyPI / pytorch.org いずれにもまだ無い (W19-13 で確認)。`sentence-transformers`
が `torch` に依存するため、`.venv/` 上では `embed_corpus_local.py` が import
時点で失敗する。

回避策として `~/.local/bin/python3.12` (Python 3.12.13) を使い、jpcite repo
直下に**並走 venv** `.venv312/` を立てて、**embed batch 専用**の隔離環境を用意した。
既存 `.venv/` は production code path で利用中なので一切触らない。

## 使い分け

| 用途 | venv | 備考 |
|------|------|------|
| FastAPI (`autonomath-api`) | `.venv/` | Python 3.13、production runtime |
| MCP server (`autonomath-mcp`) | `.venv/` | Python 3.13、production runtime |
| pytest / mypy / ruff | `.venv/` | dev tooling 全般 |
| **`embed_corpus_local.py` (corpus 事前埋め込み)** | **`.venv312/`** | torch + sentence-transformers + sqlite-vec |

`.venv312/` は **embed batch 専用**。それ以外の script を走らせない。

## install 内容 (2026-05-05 現在)

```text
torch                  2.11.0   (CPU-only; --index-url https://download.pytorch.org/whl/cpu)
sentence-transformers  5.4.1
transformers           5.7.0
tokenizers             0.22.2
huggingface-hub        1.13.0
sqlite-vec             0.1.9
tqdm                   4.67.3
numpy                  2.4.4
scipy                  1.17.1
scikit-learn           1.8.0
```

完全な依存解決は `.venv312/bin/pip freeze` で確認できる。

## 利用方法

```bash
cd /Users/shigetoumeda/jpcite

# dry-run (model load 不要、SELECT count のみ)
.venv312/bin/python tools/offline/embed_corpus_local.py --corpus saiketsu --dry-run

# 全 7 corpus dry-run
.venv312/bin/python tools/offline/embed_corpus_local.py --dry-run

# 実走 (1 corpus、cap あり)
.venv312/bin/python tools/offline/embed_corpus_local.py --corpus programs --max-rows 5000

# 7 corpus 順次
for c in programs laws cases tsutatsu saiketsu court adoptions; do
    .venv312/bin/python tools/offline/embed_corpus_local.py --corpus $c
done
```

> 実走には事前に `am_entities_vec_<S/L/C/T/K/J/A>` 7 vec table の CREATE が
> 必要 (script 冒頭の docstring 参照)。dry-run は vec table を触らない。

## smoke test

```bash
.venv312/bin/python -c "import torch, sentence_transformers, sqlite_vec; print('all imports ok')"
# 期待出力: all imports ok

.venv312/bin/python tools/offline/embed_corpus_local.py --corpus saiketsu --dry-run
# 期待出力末尾: candidate=137 embedded=0
```

2026-05-05 build 時点で saiketsu corpus は **137 行** (`autonomath.nta_saiketsu`)。

## 再構築手順 (zero から)

```bash
cd /Users/shigetoumeda/jpcite
rm -rf .venv312                 # 既存 .venv は触らない
~/.local/bin/python3.12 -m venv .venv312
.venv312/bin/pip install --upgrade pip setuptools wheel
.venv312/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv312/bin/pip install sentence-transformers sqlite-vec tqdm
```

所要時間: 約 90 秒 (CPU-only torch wheel = 80.5 MB)。

## .gitignore

`.gitignore` の `.venv/` + `venv/` は `.venv312/` をカバーしない。
追加推奨 (まだ未追加):

```gitignore
.venv312/
```

## 既存 `.venv/` を絶対に触らない

- production runtime (FastAPI / MCP) が `.venv/` 配下の Python 3.13 binary を使う。
- `.venv312/` は **embed_corpus_local.py 専用**。`.venv312/bin/uvicorn` で API を
  立てる等の流用は禁止 (依存 lock していない)。

## 関連

- `tools/offline/embed_corpus_local.py` — embed pipeline 本体
- `docs/_internal/W19_PYPI_PUBLISH_READY.md` — Python 3.13 / PyPI publish runbook
- `feedback_no_operator_llm_api.md` — operator-LLM API 呼出禁止原則
  (本 venv は **ローカル CPU 推論のみ**で完結、API key 不要)
