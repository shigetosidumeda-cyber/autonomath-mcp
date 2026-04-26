# AUTONOMATH_DB_MANIFEST

本ファイルは `/Users/shigetoumeda/jpintel-mcp/autonomath.db` の内容を記述する。
併存する `/Users/shigetoumeda/jpintel-mcp/data/jpintel.db` とは **schema が異なる** 別ファイル。

## 生成経緯

- 2026-04-24 14:58 他 CLI が 0-byte placeholder として `autonomath.db` を作成
- 2026-04-24 23:26 /tmp/autonomath_infra_2026-04-24/autonomath.db (Wave 4-17 全成果) から `sqlite3 .backup` で atomic consistent copy
- 2026-04-25 他 CLI による追加 ingest で entities +14k / aliases +95k / acceptance_stat 8x / amendment_snapshot 2x 等
- サイズ: 7,903,059,968 bytes (7.36 GiB) as of 2026-04-25
- PRAGMA integrity_check: ok

## 配布 (R2 bootstrap)

Deployers who don't check the binary into git should set two env vars before
running `scripts/bootstrap_db.sh`:

```
AUTONOMATH_DB_URL=https://<r2-bucket>/autonomath.db   # pre-signed or public
AUTONOMATH_DB_SHA256=<hex>                            # captured at upload time
```

The bootstrap script is idempotent: if the local `autonomath.db` already
matches the expected SHA-256 it skips the download; a mismatched file is
re-downloaded and re-verified.

**How to capture the SHA-256 for upload:**

1. Stop the API + MCP server (and any other process that has a SQLite handle
   on `autonomath.db`). An open connection will trigger WAL activity that
   mutates the main file even on read-only queries, so the hash will drift
   until the WAL is checkpointed and the connection released.
2. Verify no WAL is outstanding:
   ```
   ls autonomath.db-wal autonomath.db-shm 2>/dev/null  # should be empty/absent
   ```
3. Compute the hash and upload that same file:
   ```
   shasum -a 256 autonomath.db | awk '{print $1}'
   ```
4. Set `AUTONOMATH_DB_SHA256` secret in Fly (and update this manifest) with
   that hex string. Any `am_*` table update → re-upload → re-capture → re-set.

## Schema (am_* 系)

`data/jpintel.db` の `programs` / `loan_programs` / `enforcement_cases` / `case_studies` / `laws` / `tax_rulesets` / `invoice_registrants` とは独立した、正規化された entity-fact schema。

| table | rows | description |
|---|---:|---|
| `am_entities` | 402,987 | 補助金 / 税制 / 認定 / 採択事例 / 行政処分 / 融資 / SIB / 共済 等を一元化した entity。record_kind で分類 |
| `am_entity_facts` | 5,263,853 | 各 entity に紐付く attribute (EAV pattern)。raw.* namespace で一次資料原文保持 |
| `am_amount_condition` | 35,713 | 補助率 / 上限額 / 単価 等の数値条件 |
| `am_relation` | 23,749 | 14 enum canonical relation (has_authority / references_law / applies_to_* / compatible / prerequisite / replaces / successor_of / bonus_points / part_of 他) |
| `am_law_reference` | 5,523 | 制度 → 法令 参照 (canonical_law_id 解決 99.9%) |
| `am_law_article` | 460 | 主要法令 × 条項レベル structured (租特法 41条の19 / 42条の12の7 等)。2026-04-25 拡張で 101 → 460 |
| `am_source` | 97,268 | 一次資料 URL + fetched_at (aggregator ban 遵守) |
| `am_entity_source` | 279,841 | entity ↔ source edge |
| `am_alias` | 335,605 | 別名 / 略称 / 英語名 / legacy canonical_id (historical lookup) |
| `am_authority` | 556 | 所管官庁・自治体・財団 (pref: / city: / ward: / ministry: naming unified) |
| `am_region` | 1,966 | 47 都道府県 + 1,898 市町村 + 20 政令市 (population_exact 100% 実数値) |
| `am_tax_rule` | 145 | 税制優遇の rule (credit / deduction / reduction / special_depreciation / exemption / immediate_writeoff)、article_ref 76% |
| `am_subsidy_rule` | 44 | 交付金 rule (農業直接支払 / 介護処遇改善 等) |
| `am_loan_product` | 45 | 融資 product (JFC 27 / 保証協会 14 / 商工中金 3 / プロパー 1) |
| `am_acceptance_stat` | 522 | 採択率 (事業再構築 第12回 26.5% / ものづくり 21次 等)。2026-04-25 拡張で 68 → 522 |
| `am_application_round` | 1,256 | 開催回 + 応募開始 / 締切 / 交付決定 (deadline_reminder 用) |
| `am_insurance_mutual` | 31 | 共済 (小規模企業 / 中退共 / iDeCo / セーフティ / 国保 等) |
| `am_webhook_subscription` / `am_webhook_delivery` | 0 | webhook 配信 (schema 既成、運用 launch 後) |
| `am_amendment_snapshot` | 14,596 | 制度改正 diff 検知用 version snapshot。2026-04-25 拡張で 7,298 → 14,596 (2x) |
| `am_entities_fts` / `am_entities_fts_uni` | 402,600 each | trigram + unigram 双方 index (1-2 char 検索は unigram) |
| `am_entities_vec` / `am_vec_tier_a` | 402,987 each | e5-small 384d embedding (local model、API 不要) |

base canonical (全国 scope の代表 entity): 14 件 (ものづくり / 事業再構築 / IT導入 / 持続化 / 事業承継M&A / 中小省力化 / 新事業進出 / 業務改善 / キャリアアップ / エネ 等)

## 既存 `data/jpintel.db` との関係

autonomath.db は `data/jpintel.db` を置き換えない。当面は:

- `data/jpintel.db` → FastAPI REST v1 / FastMCP 既存 13 tools が参照 (launch 時点の primary)
- `autonomath.db` → 追加 MCP tools (get_tax_rule / search_acceptance_stats / search_sib_contracts / search_loans / check_enforcement / search_gx_programs / reason_answer / intent_of 他) が参照する secondary DB として ATTACH or separate connection

code 側の wiring は `src/jpintel_mcp/mcp/server.py` と `src/jpintel_mcp/db/` で分岐可能。

## 新 MCP tools (merge 完了)

`src/jpintel_mcp/mcp/autonomath_tools/` 配下に 16 tools live (2026-04-25 時点)。`AUTONOMATH_ENABLED=1` で `server.py` から登録:

- `tools.py` — reason_answer / intent_of / related_programs / active_programs_at / list_open_programs / search_acceptance_stats_am / enum_values_am / search_tax_incentives / search_certifications / search_by_law
- `tax_rule_tool.py` — get_am_tax_rule (am_tax_rule)
- `autonomath_wrappers.py` — search_loans_am / check_enforcement_am / search_gx_programs_am / search_mutual_plans_am / get_law_article_am

`/tmp/autonomath_infra_2026-04-24/migration/` の draft はすべて adoption 済。`/tmp/autonomath_infra_2026-04-24/mcp_new/` の `search_sib_contracts` / `batch_execute` は未 merge (SIB は am_sib_contract 未 ingest、batch_execute は MCP 仕様外で deferred)。

## 非機能

- 一次資料率 (active program の primary source): 100% (aggregator ban 済 — hojyokin-portal / biz.stayway / noukaweb / nikkei / prtimes / wikipedia 全て 0 件)
- schema_guard: `scripts/schema_guard.py` で `programs` table 検出時 abort、`am_entities` 必須 assert
- FK 違反: 0 (Wave 8 + Wave 14 + Wave 17 で段階 consolidate)
- PII redaction: learning middleware query_log_v2 で自動 (氏名 / 法人名 / email / 電話 / 法人番号 全部 placeholder 化)
- prompt injection defense: 56 pattern regex + unicode smuggling 対応 (全 424k entity 済、0 hit)

## 他 CLI / 本 repo 担当者への note

- この DB は **read-only primary source as of 2026-04-25**。追加 ingest は `/tmp/autonomath_infra_2026-04-24/` で実行してから再度 `.backup` で差し替える運用を推奨
- 本 repo 既存 `data/jpintel.db` / ingest pipeline は一切触っていない
- 新 MCP tools の wire-in は **完了済 (16 tools live)**。autonomath_tools 以下に集約され `AUTONOMATH_ENABLED` で gate
- 本 manifest の rows 数は 2026-04-25 時点、以降 update 時は本ファイル冒頭を更新

## 連絡

Bookyou株式会社 / 梅田茂利 / info@bookyou.net / T8010001213708
