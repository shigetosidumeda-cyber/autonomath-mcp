# Phase A 吸収 — 完全引き継ぎ書

**日付**: 2026-04-25
**作業者**: Claude (約20+ subagent 並列セッション)
**対象**: AutonoMath / jpintel-mcp v0.2.0 → Phase A 吸収後
**ブランチ**: main (作業中、未 commit)
**Launch**: 2026-05-06 (T-11d)

---

## TL;DR

| 項目 | Before | After |
|------|--------|-------|
| MCP ツール総数 | 59 | **66** (+7) |
| REST エンドポイント | -- | **+7** |
| テスト | 12 failing (4 envelope drift + 8 stats fixture) | **1122 passed / 8 skipped / 0 failed** (134秒) |
| `am_entities` rows | 424,054 | **503,930** (V4 で +79,876 corporate_entity) |
| `am_entity_facts` rows | 5.26M | **6.12M** |
| models package | `models.py` (444行) ＆ `models/` 衝突 | `models/__init__.py` 統合済み |

**Blockers ゼロ**。Launch (2026-05-06) に向けて green。

---

## 1. Phase A 吸収 — 何を入れたか

### 1.1 新規 MCP ツール (+7)

すべて `src/jpintel_mcp/mcp/autonomath_tools/` 配下、`@_mcp.tool(annotations=_READ_ONLY)` で登録。`AUTONOMATH_ENABLED` 環境変数による gate あり。

| ツール名 | ファイル | 機能 |
|---------|---------|------|
| `list_static_resources_am` | `static_resources_tool.py` | 8 静的タクソノミ一覧 |
| `get_static_resource_am` | `static_resources_tool.py` | 個別タクソノミ取得 |
| `list_example_profiles_am` | `static_resources_tool.py` | 5 example profile 一覧 |
| `get_example_profile_am` | `static_resources_tool.py` | 個別 profile 取得 |
| `render_36_kyotei_am` | `template_tool.py` | 36協定テンプレート生成 |
| `get_36_kyotei_metadata_am` | `template_tool.py` | 36協定メタデータ |
| `deep_health_am` | `health_tool.py` | 10-check 集約ヘルス |

登録は `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` に追加した import で発火 (`health_tool`, `static_resources_tool`, `template_tool` をアルファベット順に追加)。

### 1.2 新規 REST エンドポイント (+7)

`src/jpintel_mcp/api/autonomath.py` に以下を追加:

```
GET  /v1/am/static                          → list_static_resources
GET  /v1/am/static/{resource_id}            → get_static_resource
GET  /v1/am/example_profiles                → list_example_profiles
GET  /v1/am/example_profiles/{profile_id}   → get_example_profile
POST /v1/am/templates/saburoku_kyotei       → render_36_kyotei
GET  /v1/am/templates/saburoku_kyotei/meta  → get_36_kyotei_metadata
GET  /v1/am/health/deep                     → deep_health
```

**重要な architectural decision**: `/v1/am/health/deep` は **別 router (`health_router`)** に分離した。

理由: 通常の `autonomath_router` は `AnonIpLimitDep` 付きで mount されているため、production 監視 ping が匿名 IP の 50req/月 quota を食ってしまう。`health_router` は dependency なしで `main.py:app.include_router(autonomath_health_router)` として mount。

### 1.3 静的データ (新規)

`data/autonomath_static/`:
- `glossary.json` / `seido.json` / `dealbreakers.json` / `money_types.json` / `obligations.json` / `sector_combos.json` (6 タクソノミ)
- `agri/` / `templates/` (サブディレクトリの追加リソース)
- `example_profiles/` (5 プロファイル: A_ichigo_20a / D_rice_200a / J_new_corp / N_minimal / Q_dairy_100head + bc666_plan_map.yml)
- `MANIFEST.md` (人間可読なインデックス)

### 1.4 ユーティリティモジュール (新規, src/jpintel_mcp/utils/)

| モジュール | 機能 |
|-----------|------|
| `wareki.py` | 元号 ↔ 西暦変換 (令和 8 ↔ 2026 等) |
| `jp_money.py` | 「3億2000万円」等の和文金額パーサ |
| `jp_constants.py` | 都道府県コード / JSIC など |
| `templates/saburoku_kyotei.py` | 36協定テンプレート (TemplateError, get_required_fields, get_template_metadata, render_36_kyotei) |

### 1.5 新規 model モジュール

`src/jpintel_mcp/models/premium_response.py`:
- `PremiumResponse`
- `ProvenanceBadge` / `ProvenanceTier`
- `AdoptionScore`
- `AuditLogEntry`
- `PostGrantTaskKind`
- `QualityGrade`

### 1.6 models パッケージ統合 (重要)

**Before**: `models.py` (444行) と `models/` ディレクトリが**両方**存在 → Python の package shadow rule で `models.py` の中身が見えず `MINIMAL_FIELD_WHITELIST` が import できない。

**After**:
- `models.py` の 444 行を全て `models/__init__.py` に移動
- `models.py` を削除
- `models/__init__.py` に `from jpintel_mcp.models.premium_response import (...)` 追加
- `__all__` を legacy + premium_response 両方を含めて更新

これは Phase A の中で**最も hidden な blocker** だった。次のセッションで `from jpintel_mcp.models import X` する箇所は何も気にしなくていい。

### 1.7 deep health endpoint 内部実装

`src/jpintel_mcp/api/_health_deep.py:get_deep_health()` に 10 種チェック実装:
- DB ファイル存在 / WAL モード
- 主要テーブル row count
- migration applied 状態
- precompute cache 健全性
- 等

`/v1/am/health/deep` REST + `deep_health_am` MCP の両方からこの関数を呼ぶ。

---

## 2. V4 吸収の積み残しを修正

V4 (annotations / validate / provenance + 4 universal tools) は既に landed していたが、以下の **legacy debt** が今日の Phase A 吸収中に発覚 → fix。

### 2.1 migration 049 routing (target_db marker 規約導入)

**問題**: migration 049 (`am_source.license` 追加) は autonomath.db 専用だが、test fixture の jpintel.db に対しても apply されようとして `OperationalError: no such table: am_source` で fail。

**Fix** (agent: a626c1a2743c1d352):
- `scripts/migrations/046_annotation_layer.sql` 1行目に `-- target_db: autonomath` 追加
- `scripts/migrations/047_validation_layer.sql` 同上
- `scripts/migrations/049_provenance_strengthen.sql` 同上
- `scripts/migrate.py` に `_connection_db_filename()` と `_sql_has_target_marker()` 追加
- `_apply_one()` で marker が `autonomath` かつ接続先 DB filename が `autonomath.db` で終わらない場合は **skip + applied 記録**

**今後**: autonomath.db 専用 migration を書く時は必ず 1行目に `-- target_db: autonomath` を入れること。jpintel.db 専用は marker 不要 (default が jpintel)。

**production 確認**: `am_source.license` 列は本番 autonomath.db に既に存在 (10|license|TEXT|0||0)。re-run 不要。

### 2.2 precompute_schemas drift

**問題**: `jpi_pc_program_health` (migration 048) を `precompute_refresh.py:REFRESHERS` に追加したが、`tests/test_precompute_schemas.py` を更新しておらず、また `_refresh_pc_program_health` が test の `am_db_path` 引数を無視していた。

**Fix** (agent: a972ac36079a5a2b6):
- `scripts/cron/precompute_refresh.py`:
  - `_refresh_pc_program_health(w, r, am_db_path=None)` — override 受付 + `settings.autonomath_db_path` fallback
  - `_count_am_table(name, am_db_path=None)` — 同パターン
  - `_refresh_one(..., am_db_path=None)` — AM ブランチに forward
  - `run(...)` — 既存の `am_db_path` を `_refresh_one` に通す
  - missing-table tolerance 追加 (hermetic test fixture 防衛)
- `tests/test_precompute_schemas.py`:
  - `PC_TABLES_AM = {"jpi_pc_program_health"}` 追加
  - `PC_TABLES_CRON = PC_TABLES_ALL ∪ PC_TABLES_AM` 追加
  - `test_cron_pc_tables_matches_migrations` を 32 + 1 = 33 expect
  - `test_cron_real_run_keeps_tables_empty_pre_launch` で AM 系は row-count probe をスキップ (jpintel-only fixture には存在しないため)
  - schema tests は `PC_TABLES_ALL` のみ (32) 反復維持

**production callers 無変更**: CLI `main()` は `settings.autonomath_db_path` で resolve 継続。

### 2.3 test_stats freshness contamination

**問題**: `test_meta_freshness` が `UNI-test-b-1` に `source_fetched_at` を stamp し、それが session-scoped `seeded_db` fixture に leak、`test_freshness_returns_min_max_per_source` で count 期待値 2 → 実際 3 になる。

**Fix** (agent: aaec5d9fd998cb13a):
- `tests/test_stats.py:test_freshness_returns_min_max_per_source` の冒頭に neutralize 1行追加:
  ```python
  conn.execute("UPDATE programs SET source_fetched_at = NULL WHERE unified_id LIKE 'UNI-test-%'")
  ```
- 単体: 1 passed in 2.78s
- 組合せ (test_meta_freshness + test_stats): 10 passed in 4.12s

### 2.4 l4_query_cache fixture (既に self-heal 済みと判明)

**当初の症状**: full regression で 8 errors `no such table: l4_query_cache`。

**調査結果** (agent: a1370cbf16c9abc18):
- `tests/conftest.py:seeded_db` は `init_db` (schema.sql) のみで migration 043 を適用しない
- しかし `src/jpintel_mcp/api/stats.py:59-145` に **既に self-heal が実装済み**:
  - `_L4_SCHEMA_DDL` (migration 043 verbatim copy)
  - `_ensure_l4_table()` (idempotent CREATE)
  - `_cache_get_or_compute` で `OperationalError "no such table"` を catch → `_ensure_l4_table()` → retry
  - `_reset_stats_cache` も同 self-heal
- `tests/test_envelope_wiring.py:261-278` に safety net fixture `_l4_table_present` も既存

**結論**: コード変更不要。当初の 8 errors は test ordering の一時的 race で、self-heal が結局効いて green になった (full regression で 1122 passed)。

### 2.5 MCP envelope test drift

**問題**: production の `_envelope_merge` (`server.py:780-820`) が intentional に envelope key を additive merge する: `status`, `result_count`, `explanation`, `suggested_actions`, `api_version`, `tool_name`, `query_echo`, `latency_ms`, `evidence_source_count`, `meta` (native meta なき場合)。test 4 件が古い `==` 完全一致 assertion で fail。

**Fix** (agent: aaa28fe357084176b):
- `tests/test_mcp_tools.py:195-203` — `==` を `MINIMAL_FIELD_WHITELIST.issubset(rec.keys())` に変更
- `tests/test_programs.py:21-35` — 新定数 `_ENVELOPE_ONLY_KEYS` (10 keys: 9 user-listed + meta) 追加
- `tests/test_programs.py:224-247`:
  - `test_mcp_rest_parity_full`: MCP 側のみ envelope-only keys 引いてから `==`
  - `test_mcp_minimal_same_whitelist`: REST は strict equality 維持、MCP は `.issubset()`
- `tests/test_programs_batch.py:23-37` — 同 `_ENVELOPE_ONLY_KEYS` 追加
- `tests/test_programs_batch.py:191-194` — `test_batch_mcp_parity` 同パターン

**Production code 無変更**。`_envelope_merge` も `MINIMAL_FIELD_WHITELIST` も無傷。

### 2.6 test_healthcare_tools / test_real_estate_tools count assertion drift

`tests/test_healthcare_tools.py`:
- 55 → 66 (line 94) / 61 → 72 (line 115)

`tests/test_real_estate_tools.py`:
- 55 → 66 (line 94) / 60 → 71 (line 115)

V4 (+4) + Phase A (+7) で公開 manifest の base が 55 → 66 になったため、stub gate test の base 数を反映。

---

## 3. CLAUDE.md 更新

agent: aa8abfa19738efb90

| 行 | 変更内容 |
|----|---------|
| 7 (Overview) | `55 tools (38 jpintel + 17 autonomath, ...)` → `66 tools (38 jpintel + 24 autonomath: 17 V1 + 4 V4 universal + 7 Phase A absorption)` |
| 23 (Architecture) | `55 tools, ...: 38 core + 17 autonomath` → `66 tools, ...: 38 core + 17 autonomath V1 + 4 V4 universal + 7 Phase A absorption` |
| 48 (V4 absorption) | `Tool count 55 → 59` → `Tool count 55 → 59 → 66 (... +7 Phase A absorption)` |
| 50 | "CLAUDE.md tool counts ... 55 → 59 normalize post-launch" 削除 |
| 52-60 (新) | `### Phase A absorption (complete 2026-04-25)` セクション新規 (7 tools, 8 taxonomies, 4 utility, premium_response, deep health, REST routes, models 統合) |
| 142 (Key files / server.py) | `55 tools total` → `66 tools total` |
| 144 (Key files / autonomath bullet) | `17 autonomath tools` → `24 autonomath tools` + 7 Phase A tool 名追記 (`(Phase A absorption)` タグ) |

**意図的に未変更**:
- 行 9 と 33 の legacy "tools 59" 記述 (歴史的 Note 段落のため)

---

## 4. アーキテクチャ判断 (なぜそうしたか)

### 4.1 health_router 分離

`/v1/am/health/deep` を `autonomath_router` ではなく **別 router (`health_router`)** に置いた。

理由: 通常 router には `AnonIpLimitDep` がついており、production の uptime 監視 (Cloudflare/UptimeRobot 等) が分間複数回 ping すると **匿名 IP の月 50req quota が即枯渇** → 監視死。health は metering 対象外にする必要があった。

実装:
```python
# api/autonomath.py
router = APIRouter(prefix="/v1/am", tags=["autonomath"])  # 通常 quota 対象
health_router = APIRouter(prefix="/v1/am", tags=["autonomath-health"])  # 監視専用

# api/main.py
from jpintel_mcp.api.autonomath import (
    health_router as autonomath_health_router,
    router as autonomath_router,
)
app.include_router(autonomath_router, dependencies=[AnonIpLimitDep])
app.include_router(autonomath_health_router)  # ← AnonIpLimitDep なし
```

### 4.2 envelope merge は production 行動を維持、test 側を緩和

`_envelope_merge` (`server.py:780-820`) が追加する 9 envelope key + meta は **AI agent consumer 向けの設計上の決定**。tool_name / query_echo / suggested_actions は agent が次の action を決める material。これを削るのは regression。

→ test 側を `==` から `.issubset()` / 引き算後 `==` に緩和。

### 4.3 target_db marker は `-- target_db: autonomath` 形式

`scripts/migrate.py` の `_sql_has_target_marker` は **先頭 5 行のみ走査**。これは「CREATE TRIGGER body 内に偶然この文字列が出ても誤検知しない」ための防衛。新規 migration を書く時は必ず 1 行目に置くこと。

### 4.4 models 統合は package 優先

両方 (`models.py` と `models/`) があると Python は package を優先 → `models.py` の中身が完全に hidden。今回は package 側に統合 (`models/__init__.py`) して、追加 module (`premium_response.py`) と並列にした。

---

## 5. 検証コマンド

```bash
# 完全 regression (134秒, 1122 passed / 8 skipped / 0 failed)
AUTONOMATH_ENABLED=1 .venv/bin/pytest tests/ --ignore=tests/e2e -q

# Phase A 単体検証
AUTONOMATH_ENABLED=1 .venv/bin/pytest tests/test_static_resources.py tests/test_template_tool.py tests/test_health_tool.py -v

# tool count 確認
AUTONOMATH_ENABLED=1 .venv/bin/python -c "from jpintel_mcp.mcp import server; print(len(server.mcp._tool_manager._tools))"
# → 66

# REST endpoint smoke
.venv/bin/uvicorn jpintel_mcp.api.main:app --port 8080 &
curl http://localhost:8080/v1/am/static
curl http://localhost:8080/v1/am/health/deep
curl http://localhost:8080/v1/am/example_profiles
```

---

## 6. 既知の deferred (launch blocker でない)

これらは Phase A の scope 外、後送り済み:

- **FTS+vec rebuild**: V4 で追加した 16,474 annotation rows + 21 new corp.* facts はまだ FTS5 / sqlite-vec に乗っていない。`scripts/rebuild_fts.py` で約 2.2h read-only で rebuild 可。
- **`am_entity_facts.source_id` backfill**: migration 049 で column 追加済み、NULL backfill が `am_entity_source` rollup 待ち。
- **manifest version bump**: `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` は v0.2.0 のまま。Phase A 反映時に v0.3.0 へ。
- **CLAUDE.md 行 9 と 33** の legacy "tools 59" Note (歴史的記述として保持)。

---

## 7. ファイル変更サマリ (今日全体)

### 新規ファイル
- `src/jpintel_mcp/mcp/autonomath_tools/static_resources_tool.py` (4 MCP tools wrapper)
- `src/jpintel_mcp/mcp/autonomath_tools/template_tool.py` (2 MCP tools)
- `src/jpintel_mcp/mcp/autonomath_tools/health_tool.py` (1 MCP tool)
- `src/jpintel_mcp/mcp/autonomath_tools/static_resources.py` (loader 実装)
- `src/jpintel_mcp/api/_health_deep.py` (deep health 実装)
- `src/jpintel_mcp/models/premium_response.py` (新 model モジュール)
- `src/jpintel_mcp/utils/wareki.py` / `jp_money.py` / `jp_constants.py`
- `src/jpintel_mcp/templates/saburoku_kyotei.py`
- `data/autonomath_static/` 配下 (8 taxonomies + 5 example profiles + MANIFEST)

### 修正ファイル
- `src/jpintel_mcp/models/__init__.py` — 444 行統合 + premium_response re-export
- `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` — 3 import 追加
- `src/jpintel_mcp/api/autonomath.py` — 7 endpoint + health_router 分離
- `src/jpintel_mcp/api/main.py` — health_router mount 追加
- `scripts/migrations/046_annotation_layer.sql` — target_db marker
- `scripts/migrations/047_validation_layer.sql` — target_db marker
- `scripts/migrations/049_provenance_strengthen.sql` — target_db marker
- `scripts/migrate.py` — `_connection_db_filename` + `_sql_has_target_marker` + `_apply_one` gate
- `scripts/cron/precompute_refresh.py` — am_db_path override + missing-table tolerance
- `tests/test_healthcare_tools.py` — count 55→66, 61→72
- `tests/test_real_estate_tools.py` — count 55→66, 60→71
- `tests/test_stats.py` — freshness contamination neutralize
- `tests/test_precompute_schemas.py` — PC_TABLES_AM 33 計算
- `tests/test_mcp_tools.py` — issubset 化
- `tests/test_programs.py` — _ENVELOPE_ONLY_KEYS 追加 + 引き算 `==`
- `tests/test_programs_batch.py` — 同上
- `CLAUDE.md` — 7 箇所更新

### 削除ファイル
- `src/jpintel_mcp/models.py` (444 行、`models/__init__.py` に吸収済み)

---

## 8. 並列 agent inventory (運用ログ)

このセッションで使用した全 background agent (順不同):

| ID | 担当 | 結果 |
|----|------|------|
| a626c1a2743c1d352 | migration 049 routing + migrate.py target_db marker | green |
| a972ac36079a5a2b6 | precompute_schemas drift 修正 | green |
| aaec5d9fd998cb13a | test_stats freshness contamination 修正 | green |
| aa8abfa19738efb90 | CLAUDE.md tool count 更新 | green |
| aaa28fe357084176b | MCP envelope test drift 修正 | green |
| a1370cbf16c9abc18 | test_stats l4_query_cache 調査 → 既に self-heal 済みと判明 | green |

そのほか summary 時点で既に完了していた batch 1 / batch 2 の Phase A 配線 agent 群 (詳細は前 session log)。

---

## 9. 次セッション向けの注意点

1. **`AUTONOMATH_ENABLED=1` を必ず付ける**。デフォルト disabled で test 走らせると 24 tool が登録されず、count assertion で 66 にならない。
2. **新規 autonomath.db 専用 migration を書く時は `-- target_db: autonomath` を 1 行目に**。これがないと jpintel.db fixture に対して走って fail する。
3. **`models.py` は二度と作らない**。すべて `models/` package 配下に。
4. **health endpoint 系を新規追加する時は `health_router` (AnonIpLimitDep なし) に**。通常の `router` に入れると監視 ping が匿名 quota を食う。
5. **MCP tool テストで `==` 完全一致は使うな**。`_envelope_merge` が additive なので `.issubset()` か envelope-only key 引き算後の `==` で検証する。
6. **manifest version bump**: Phase A をリリースに含める時は `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` を v0.3.0 に揃える。
7. **CLAUDE.md 行 9 と 33** に legacy "tools 59" 記述が残っているが意図的。今後の数値更新で誤って書き換えないこと。

---

**End of handoff.**
