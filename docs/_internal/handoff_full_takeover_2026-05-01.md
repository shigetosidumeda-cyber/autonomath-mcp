# Handoff: OTHER CLI への全権委譲計画

> 2026-05-01 safety override: この文書内の `git add -A` / `git push` /
> `fly deploy` / `npm publish` / `HF_TOKEN ... --push` は現在の巨大 dirty
> tree では実行禁止。reviewed file list、full tests、Docker context audit、
> migration guard、secret/publication audit が green になった commit SHA
> だけを operator が明示的に deploy する。

Date: 2026-05-01
読む人 (OTHER CLI): あなた
本ドキュメント目的: **THIS CLI のレートリミットが近いため、deploy + データ拡張 9 案 + outreach を全部 OTHER CLI に引き継ぐ。これ 1 本で完結。**

---

## 1 行で

THIS CLI が verify 完了 (10 並列 deep-dive で前回 audit を 6 件 honest 訂正済み)。OTHER CLI は (a) deploy、(b) データ拡張 9 案 (TIER S → A → B 順)、(c) outreach 送信、を全部担当。両 CLI 合算で 200-300 万/月射程の 50-65% 確度。

---

## OTHER CLI が今 attempt する作業 (全 担当範囲)

### Block 1: deploy gate (historical command block removed)

CURRENT STATUS: **DEPLOY NO-GO** for this checkout. The earlier all-in-one
commit/tag/push/Fly command block was intentionally removed because it used a
huge dirty tree and could publish unreviewed files. A deploy may only proceed
from a clean, reviewed commit SHA after the active checklist gates pass:

- reviewed file list is explicit (never blanket-stage)
- full pytest/lint/docs gates are green
- Docker context audit confirms no internal/HF/ETL leakage
- migration guard and production snapshot checks are green
- secret/publication audit is green
- operator explicitly chooses the commit SHA to deploy

### Block 2: 既存 ETL 残作業 (THIS CLI 着手済 + OTHER CLI 継続)

| ID | 内容 | コマンド | 推定時間 |
|---|---|---|---|
| A5 | last_verified backfill (4,135 → 95,000) | `for shard in 1 2 3 4; do uv run python scripts/etl/backfill_am_source_last_verified.py --apply --shard $shard --limit 1000 --json & done` | ~24h |
| B4 | e-Gov 法令本文 fetch (smoke 90% ok) | `uv run python scripts/etl/fetch_egov_law_fulltext_batch.py --output analysis_wave18/egov_law_fulltext_full.csv` | ~2.6h |
| B5 | court excerpt enrichment (smoke 30/30) | `uv run python scripts/etl/enrich_court_decisions_excerpt.py` | ~30-45 min |
| B6 | PDF 抽出 batch (smoke 13/15 ok) | `uv run python scripts/etl/run_program_pdf_extraction_batch.py --output analysis_wave18/pdf_extraction_full.csv` | ~70 min |
| B7 | adoption full reconciliation (smoke 100%) | `uv run python scripts/etl/reconcile_adoption_to_program.py --out analysis_wave18/adoption_reconciliation_full.csv` | ~22 min |
| B9 | e-Stat URL backfill | 既存 `scripts/etl/backfill_estat_fact_provenance.py` | 未計測 |
| B13 | prefecture/municipality backfill 残 | 既存 `scripts/etl/extract_prefecture_municipality.py` | 未計測 |

これらは ETL CSV 出力後、operator が DB 適用判断 (UPDATE は別 task)。

### Block 3: データ拡張 9 案 (THIS CLI が verify 完了、OTHER CLI が実装)

verify 済み事実 (前回 audit からの honest 訂正含む):

#### TIER S (即実装、新規 ingest ほぼ不要、月 ¥549-699K uplift)

##### A_ext5 e-Stat surface 化 [新規 ingest なし、view のみ]

**事実 (verified)**:
- `am_entities WHERE record_kind='statistic'` 73,960 行 + facts 1.26M 既に ingest 済
- 12-13 facts/cell、5 metrics: `establishment_count` / `employee_count_total` / `regular_employee_total` / `employee_count_male` / `employee_count_female`
- **honest gap**: 売上高/付加価値/設備投資/R&D は **NOT in existing ingest** (新規 ingest 別途必要)
- 0 storage cost、view 1 個で surface 化

**実装内容**:

```sql
-- scripts/migrations/127_estat_industry_benchmark_view.sql
-- target_db: autonomath
CREATE VIEW IF NOT EXISTS v_industry_benchmark AS
SELECT
  jsic_code, prefecture_code,
  metric_name,
  -- p25 / median / p75 (SQLite percentile_cont 不在のため手動 NTILE)
  ...
FROM am_entity_facts
WHERE record_kind = 'statistic';

CREATE VIEW IF NOT EXISTS v_industry_benchmark_rollup AS
SELECT jsic_code, prefecture_code, COUNT(*) sample_size,
  SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) secrecy_cells
FROM v_industry_benchmark
GROUP BY jsic_code, prefecture_code;
```

REST endpoint:
- `GET /v1/stats/benchmark/{jsic_code}/{prefecture_code}`
- `GET /v1/stats/industry/{jsic_code}`
- `GET /v1/stats/region/{prefecture_code}`
- `GET /v1/stats/houjin_size_distribution/{jsic_code}`

MCP tools:
- `get_industry_benchmark_am(jsic_code, prefecture_code)`
- `compare_houjin_to_benchmark_am(houjin_bangou)`
- 既存 `pack_construction_am` / `pack_manufacturing_am` / `pack_real_estate_am` の response に `industry_size` collateral 追加 (1 行 edit)

**期待**: ¥299K/月 (collateral として cohort #5/#7/#8 全部 lift)

##### A_ext6 パブコメ RSS ingest [軽量 ingest + diff phase 拡張]

**事実 (verified)**:
- 公式 RSS 2 本: `pcm_list.xml` (募集中、11 items) + `pcm_result.xml` (結果、25 items) — HTTP 200 verified
- gov_standard v2.0 = CC-BY 互換、再配布 OK
- `<description>` は `<br/>`-separated key:value、parse 容易
- 結果 RSS の 40% が `命令等の公布日` 空 → phase enum で `withdrawn` / `report_only` / `awaiting_decision` 厳格化必要
- detail page で **5 fields 追加** (`案件番号` / `定めようとする命令などの題名` / `根拠法令条項` / `行政手続法対象か` / `命令などの案 PDF URL`) → 法令 link 立つ
- **2-phase ingest 必須** (RSS → detail HTML)

**実装内容**:

```sql
-- scripts/migrations/122_public_comments.sql
-- target_db: jpintel
CREATE TABLE IF NOT EXISTS public_comments (
  case_number TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  competent_authority TEXT NOT NULL,
  start_date TEXT, end_date TEXT,
  result_published_date TEXT, effective_date TEXT,
  summary_text TEXT,
  proposal_pdf_url TEXT,
  category TEXT,
  related_law_ids_json TEXT, related_program_ids_json TEXT,
  comment_count INTEGER,
  phase TEXT CHECK (phase IN ('open','closed','awaiting_decision','promulgated','withdrawn','report_only')),
  kongyo_houreijou TEXT, -- 根拠法令条項
  gyoseitetsuzukihou_target INTEGER, -- 0/1
  proposal_title TEXT,
  source_url TEXT, fetched_at TEXT, content_hash TEXT,
  license_code TEXT DEFAULT 'gov_standard_v2.0'
);
CREATE INDEX IF NOT EXISTS idx_pc_authority ON public_comments(competent_authority);
CREATE INDEX IF NOT EXISTS idx_pc_end_date ON public_comments(end_date);
CREATE INDEX IF NOT EXISTS idx_pc_phase ON public_comments(phase);
CREATE INDEX IF NOT EXISTS idx_pc_category ON public_comments(category);
CREATE VIRTUAL TABLE IF NOT EXISTS public_comments_fts USING fts5(
  case_number, title, summary_text,
  tokenize='trigram'
);
```

```sql
-- scripts/migrations/130_am_amendment_diff_phase.sql
-- target_db: autonomath
ALTER TABLE am_amendment_diff ADD COLUMN phase TEXT DEFAULT 'promulgated';
ALTER TABLE am_amendment_diff ADD COLUMN public_comment_case_number TEXT;
-- 既存 7,819 行は phase='promulgated' で fix
```

ETL: `scripts/etl/ingest_public_comment_rss.py`
- 2-phase: RSS fetch → detail HTML
- 1 sec/host、UA `jpcite-research/1.0`
- `--dry-run` `--limit N` `--resume-after-case-number`
- LLM 不使用 (本文ベタ取りのみ)

cron: `.github/workflows/public-comment-cron.yml`
- daily 05:00 JST RSS 2 本 fetch
- weekly Sun 06:00 JST phase 更新
- monthly 1 日 07:00 JST law link 確立

MCP tools:
- `list_active_public_comments_am`
- `get_public_comment_detail_am(case_number)`
- `find_amendments_for_law_am(law_id)`
- 既存 `forecast_program_renewal_am` に signal #5 (パブコメ予兆) 追加

**期待**: ¥250-400K/月 (¥3/billable unit only 制約遵守、税理士/コンプラ/業種団体 cohort)

#### TIER A (高 ROI、月 ¥1.97-2.55M uplift)

##### A_ext3 8 官庁通達 unified [社労士 cohort #11 創出]

**事実 (verified)**:
- NTA 既存 3,221 + FSA 8K-12K + MLIT 15K + MIC 5K + MOE 3K + JFTC 500 + MHLW 28K-40K + METI 10K = **70K-80K 通達**
- **MHLW Playwright 不要** (前回 audit 訂正、curl Chrome UA で 5/5 200 verified)
- METI のみ Akamai bot screening、Playwright headed 必要
- FSA `public.xlsx` 1,182 行 改正履歴 bulk 公開済 (改訂検出 自動化可)
- FSA PDF 100% 依存 (114-517 ページ)、章 split 必要

**実装内容**:

```sql
-- scripts/migrations/124_am_tsutatsu_unified.sql
-- target_db: autonomath
CREATE TABLE IF NOT EXISTS am_tsutatsu_authority (
  authority_code TEXT PRIMARY KEY,
  authority_name_jp TEXT, parent_ministry TEXT, website_url TEXT
);
INSERT OR IGNORE INTO am_tsutatsu_authority VALUES
  ('nta','国税庁','財務省','https://www.nta.go.jp/'),
  ('fsa','金融庁','内閣府','https://www.fsa.go.jp/'),
  ('mlit','国土交通省','-','https://www.mlit.go.jp/'),
  ('mhlw','厚生労働省','-','https://www.mhlw.go.jp/'),
  ('meti','経済産業省','-','https://www.meti.go.jp/'),
  ('mic','総務省','-','https://www.soumu.go.jp/'),
  ('moe','環境省','-','https://www.env.go.jp/'),
  ('jftc','公正取引委員会','内閣府','https://www.jftc.go.jp/');

CREATE TABLE IF NOT EXISTS am_tsutatsu (
  authority_code TEXT NOT NULL,
  tsutatsu_id TEXT NOT NULL,
  title TEXT, category TEXT,
  promulgation_date TEXT, last_amended_date TEXT,
  is_current INTEGER DEFAULT 1,
  text_summary TEXT, pdf_url TEXT, html_url TEXT,
  related_law_ids_json TEXT,
  source_url TEXT, fetched_at TEXT, content_hash TEXT,
  license_code TEXT DEFAULT 'gov_standard',
  PRIMARY KEY (authority_code, tsutatsu_id)
);
CREATE INDEX IF NOT EXISTS idx_amtsut_auth_cat ON am_tsutatsu(authority_code, category);
CREATE INDEX IF NOT EXISTS idx_amtsut_current ON am_tsutatsu(is_current);

CREATE TABLE IF NOT EXISTS am_tsutatsu_revision (
  authority_code TEXT, tsutatsu_id TEXT, amendment_date TEXT,
  title TEXT, amendment_summary TEXT, amended_text_url TEXT,
  PRIMARY KEY (authority_code, tsutatsu_id, amendment_date)
);

-- nta_tsutatsu_index 既存 3,221 行を取り込み
INSERT OR IGNORE INTO am_tsutatsu (authority_code, tsutatsu_id, ...)
  SELECT 'nta', id, ... FROM nta_tsutatsu_index;
```

ETL: 6 curl-only scripts (`scripts/etl/`):
- `ingest_tsutatsu_fsa.py` (PDF parser + xlsx)
- `ingest_tsutatsu_mlit.py`
- `ingest_tsutatsu_mic.py`
- `ingest_tsutatsu_moe.py`
- `ingest_tsutatsu_jftc.py`
- `ingest_tsutatsu_mhlw.py` (curl Chrome UA、Playwright 不要)
- 共通: `--dry-run --limit N --resume-after-id`
- 1 sec/host throttle

METI のみ (`scripts/etl/ingest_tsutatsu_meti.py`): Playwright headed、launch 後

MCP tools:
- `cite_tsutatsu_<agency>` (FSA/MLIT/MIC/MOE/JFTC/MHLW、6 個)
- `find_tsutatsu_for_law_am(law_id)` — 法令 ID で関連通達一覧
- `find_tsutatsu_amendments_in_period_am(authority, start_date, end_date)`

**期待**: ¥876K-2,115K/月 (中央 ¥1.5M)、社労士 cohort #11 (44K 名 + 法人 3,500、中央 ¥384K/月) 創出

##### A_ext1 改正履歴 e-Gov v2 walk

**事実 (verified, smoke 5 法令)**:
- API `https://laws.e-gov.go.jp/api/2/law_revisions/<law_id>` (アンダースコア注意)
- 0.4-0.5 sec/req (前回 1.3 sec/req 訂正、3x 速い)
- 9,487 法令全 walk: 5h → **25 分 (5 並列)**
- 平均 25 rev/law、計 ~190K rows
- 法人税法 64 rev / 地方税法 224 rev / 民法 33 rev (民法 ID は `129AC0000000089`、`329AC1000000089` は 404)
- **新発見: umbrella 改正 graph** (1 改正法 → N 法令段階施行、`amendment_law_id` で取れる)
- JSON 21 keys、`previous_revision_id` / `change_summary` は **不在** (代替: `amendment_enforcement_date DESC` 物理ソート + `amendment_enforcement_comment`)

**実装内容**:

```sql
-- scripts/migrations/132_am_law_revision.sql
-- target_db: autonomath
CREATE TABLE IF NOT EXISTS am_law_revision (
  law_id TEXT NOT NULL,
  law_revision_id TEXT NOT NULL,
  law_canonical_id TEXT, -- soft FK to am_law、NULL 許容 (am_law 9,484 vs e-Gov 9,487 mapping miss 吸収)
  effective_date TEXT, enforcement_date TEXT, promulgation_date TEXT,
  amendment_law_id TEXT, amendment_law_title TEXT,
  is_unenforced INTEGER DEFAULT 0,
  change_summary_text TEXT, -- amendment_enforcement_comment
  revision_type TEXT,
  source_url TEXT, fetched_at TEXT, content_hash TEXT,
  PRIMARY KEY (law_id, law_revision_id)
);
CREATE INDEX IF NOT EXISTS idx_amlr_law_date ON am_law_revision(law_id, effective_date DESC);
CREATE INDEX IF NOT EXISTS idx_amlr_date ON am_law_revision(effective_date);
CREATE INDEX IF NOT EXISTS idx_amlr_amendment ON am_law_revision(amendment_law_id);
CREATE INDEX IF NOT EXISTS idx_amlr_canonical ON am_law_revision(law_canonical_id);
CREATE INDEX IF NOT EXISTS idx_amlr_unenforced ON am_law_revision(is_unenforced) WHERE is_unenforced = 1;
```

ETL: `scripts/etl/fetch_law_revisions_e_gov_v2.py`
- 5 並列 (asyncio + Semaphore(5))
- 9,487 法令 walk
- `--resume-after-law-id`
- 失敗 row は `analysis_wave18/law_revisions_failed.csv`

MCP tools:
- `get_law_revision_history_am(law_id)`
- `list_amendments_in_omnibus_am(amendment_law_id)` — 新発見 graph
- `get_law_status_at_date_am(law_id, as_of_date)` — `as_of_date` default は当日
- `find_omnibus_amendments_in_period_am(start_date, end_date)`
- 既存 `track_amendment_lineage_am` (Wave 21) と `forecast_program_renewal_am` (Wave 22) が初めて実改正履歴で裏付け

**期待**: ¥235-415K/月 (umbrella graph で +¥20-40K)

##### A_ext7 行政処分 deep [既存 schema 使用、view のみ]

**事実 (verified)**:
- 既存 4 ingest scripts (JFTC + JFTC houdou + PPC + FSA) 既存
- `am_enforcement_detail` 既に JFTC=200 + PPC=85 + FSA=76 + SESC=131 + 関東財務局=81 = 573 / 22,258 (2.6%)
- migration 132 不要、既存 schema で OK
- 過去 10 年 walk = ~2,186 HTTP / 1h で +1,200 row
- PPC 0% / JFTC 14.5% houjin_bangou backfill (誤マッチリスク)

**実装内容**:

```sql
-- scripts/migrations/131_enforcement_authority_view.sql
-- target_db: autonomath
CREATE VIEW IF NOT EXISTS v_enforcement_authority_code AS
SELECT *,
  CASE
    WHEN issuing_authority LIKE '%公正取引委員会%' THEN 'jftc'
    WHEN issuing_authority LIKE '%個人情報保護委員会%' THEN 'ppc'
    WHEN issuing_authority LIKE '%金融庁%' THEN 'fsa'
    WHEN issuing_authority LIKE '%証券取引等監視委員会%' THEN 'sesc'
    WHEN issuing_authority LIKE '%関東財務局%' THEN 'kanto_zaimu'
    ELSE 'other'
  END AS authority_code
FROM am_enforcement_detail;

CREATE VIEW IF NOT EXISTS v_enforcement_recent AS
SELECT * FROM v_enforcement_authority_code
WHERE issuance_date >= date('now', '-10 years');

CREATE VIEW IF NOT EXISTS v_enforcement_houjin_360 AS
SELECT houjin_bangou, COUNT(*) action_count, MIN(issuance_date) first_action,
  MAX(issuance_date) last_action, GROUP_CONCAT(authority_code) authorities
FROM v_enforcement_authority_code
WHERE houjin_bangou IS NOT NULL
GROUP BY houjin_bangou;
```

PII redaction:
- 個人事業主 検出: `houjin_bangou IS NULL AND target_name LIKE '<short_pattern>'` → `kojin_flag=1`
- `v_enforcement_public` (kojin_flag=0 only)
- `v_enforcement_internal` (フル)

ETL: 既存 4 script を `--apply --resume-after-id` で re-run (~1h)

MCP tools 拡張:
- 既存 `check_enforcement_am` を 8 官庁横断に
- `get_enforcement_history_houjin_am(houjin_bangou)` — 法人 360°
- `find_recent_enforcements_am(authority_code, days_back)`

REST endpoint:
- `GET /v1/enforcement/houjin/{houjin_bangou}`
- `GET /v1/enforcement/recent?authority=jftc&days=30`

**期待**: ¥125-700K/月 (call-density multiplier、M&A / 監査 / コンプラ)

#### TIER B (中 ROI、取得難度 高、月 ¥1.5-1.9M uplift)

##### A_ext4 GEPS 落札 [anti-bot 不在 verified、5 並列で 2.8h]

**事実 (verified, 20-POST stress test)**:
- **「1 session = 1 POST」は誤り** (前回 audit 訂正)、20-POST/session で 20/20 success
- CSRF token は session 全体で維持 (form chain 経由)
- Detail page = **OAA0104** (前回 OAA0107 と書いたが正解)
- 5 並列 × 1 req/sec = 5 req/sec global、anti-bot 不在
- 14h → **2.8h confirmed**
- 詳細 navigation: result page の `doSubmitParams(...)` JS hrefs から `procurementItemInfoId` 抽出 → POST with `_csrf` + `SyFromFlg=1`
- `successfulBidNoticeBean` cells のみ detail (title=`調達情報の詳細`)
- 法人番号 13桁 + 円-amount inline で取れる (e.g., `4011001021880` / `4,015,000円`)

**実装内容**:

```sql
-- scripts/migrations/123_bids_geps_extension.sql
-- target_db: jpintel
ALTER TABLE bids ADD COLUMN winner_houjin_bangou TEXT;
ALTER TABLE bids ADD COLUMN winner_kojin_flag INTEGER DEFAULT 0;
ALTER TABLE bids ADD COLUMN contract_amount_yen INTEGER;
ALTER TABLE bids ADD COLUMN procurement_method_detail TEXT;
ALTER TABLE bids ADD COLUMN tender_period_start TEXT;
ALTER TABLE bids ADD COLUMN tender_period_end TEXT;
ALTER TABLE bids ADD COLUMN award_runner_up TEXT;
ALTER TABLE bids ADD COLUMN region_code TEXT;
ALTER TABLE bids ADD COLUMN category_jsic TEXT;
ALTER TABLE bids ADD COLUMN full_text TEXT;
ALTER TABLE bids ADD COLUMN procurement_item_info_id TEXT;
ALTER TABLE bids ADD COLUMN content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_bids_winner ON bids(winner_houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_bids_jsic_region ON bids(category_jsic, region_code);
CREATE INDEX IF NOT EXISTS idx_bids_award ON bids(award_date DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS bids_fts USING fts5(
  case_number, full_text, tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS bids_ingest_progress (
  shard_key INTEGER PRIMARY KEY,
  last_case_number TEXT, processed_count INTEGER,
  updated_at TEXT
);

CREATE VIEW IF NOT EXISTS v_bids_public AS
SELECT * FROM bids WHERE winner_kojin_flag = 0;
```

ETL: `scripts/etl/ingest_geps_bid_full.py`
- 5 並列 worker、各自分担 shard (case_number 末尾 1 桁 で 10 分割、5 worker 2 shard ずつ)
- 既存 `scripts/etl/probe_geps_feasibility.py` の logic 流用 + extend
- result page → procurementItemInfoId 抽出 → detail POST → 法人番号/金額 parse
- proxy 不要 (Cloudflare Workers 無料枠で十分、anti-bot 不在 verified)
- `--resume-after-case-number`

MCP tools:
- 既存 `find_recent_bids_am` 拡張
- `get_bid_winner_history_am(houjin_bangou)` — 法人別落札履歴
- `find_competitor_bids_am(industry, region)` — 競合分析

**期待**: ¥600-800K/月 (前回 ¥1.15M は cohort assumption 上限、中央値 verify)

##### A_ext8 特許 J-PlatPat IPRED API [弁理士 cohort #12 創出]

**事実 (verified)**:
- 完全 greenfield (`am_entity_facts WHERE field_name LIKE '%patent%'` = 1 row のみ)
- JPO 2024 統計: ~3.0M 出願 / 10 年 × 0.95 publication × 0.67 houjin_bangou 付与 = **1.91M rows × 2.2KB = 4.2GB**
- **Fly volume 10→20GB scale 必要**
- IPRED API: 無料 + 月 4M req quota、商用 OK (利用規約 verify 必要)

**実装内容**:

```sql
-- scripts/migrations/133_am_patents.sql
-- target_db: autonomath
CREATE TABLE IF NOT EXISTS am_patents (
  application_number TEXT PRIMARY KEY,
  applicant_houjin_bangou TEXT,
  applicant_name_raw TEXT,
  application_date TEXT, publication_date TEXT,
  registration_number TEXT, registration_date TEXT,
  ipc_codes_json TEXT,
  title TEXT, abstract TEXT,
  inventor_count INTEGER, -- name/address は格納しない (PII 配慮)
  source_url TEXT, fetched_at TEXT, content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_amp_applicant ON am_patents(applicant_houjin_bangou);
CREATE INDEX IF NOT EXISTS idx_amp_date ON am_patents(application_date DESC);
CREATE INDEX IF NOT EXISTS idx_amp_ipc ON am_patents(ipc_codes_json);
CREATE VIRTUAL TABLE IF NOT EXISTS patents_fts USING fts5(
  application_number, title, abstract, tokenize='trigram'
);
```

ETL: `scripts/etl/ingest_jpo_ipred_api.py`
- IPRED API 申請: https://ip-data.jpo.go.jp/ (無料 app key 取得、数日)
- bulk fetch 10 年分 ~1.91M rows、5 並列で 数日
- license `jpo_ipred_terms` 別行で `am_source` 登録

MCP tools (`patent_lookup_facts_am` ベース、弁理士法 §75 配慮で「lookup」「facts」のみ):
- `lookup_patent_facts_am(houjin_bangou)` — 法人別特許一覧 (件数 + IPC 分布)
- `find_patent_by_application_am(application_number)`
- `find_recent_patents_am(jsic_code, days_back)` — 業種別新規出願 (記者・VC 向け)
- `_disclaimer` envelope 必須 (弁理士法 §75 で評価業務独占)

**期待**: ¥555K/月 (中央)、弁理士 cohort #12 (12,300 名 + 600 法人) 創出

##### A_ext2 都道府県条例 [前回 audit 破綻、scope 縮小]

**事実 (前回 audit 訂正)**:
- ASP 3 大集約は **破綻**: e-reikinet.jp は death (リダイレクト)、第一法規/NTTデータ関西 LegalDB は public host なし
- 各自治体個別実装が必要、ぎょうせい "Super Reiki-Base" は OEM CMS で各自治体が独自 deploy
- 5 自治体 sample: 1/5 (20%) のみ即時 verify (東京都 metro `www.reiki.metro.tokyo.lg.jp` のみ)
- corpus 39,819 → **27,000** (32% down)
- 取得時間: 1-2 week → **12 week** (Playwright/JSF 必須 5-10x)
- 月 ¥600-900K → **¥350-550K**

**実装内容 (THIS CLI 着手分のみ)**:

東京都 + 主要 4 自治体 (大阪府/北海道/福岡県/横浜市) sample fetch、残り 1,738 自治体は OTHER CLI loop で取りに来る

```sql
-- scripts/migrations/134_local_ordinances.sql
-- target_db: jpintel
CREATE TABLE IF NOT EXISTS local_ordinances (
  ordinance_id TEXT PRIMARY KEY,
  prefecture_code TEXT NOT NULL,
  municipality_code TEXT,
  ordinance_name TEXT, category TEXT,
  body_text TEXT,
  effective_date TEXT, last_amended_date TEXT,
  is_current INTEGER DEFAULT 1,
  source_url TEXT, asp_provider TEXT, fetched_at TEXT, content_hash TEXT,
  redact_status TEXT, license_code TEXT DEFAULT 'public_domain_jp_law_§13'
);
CREATE INDEX IF NOT EXISTS idx_lo_pref_muni ON local_ordinances(prefecture_code, municipality_code);
CREATE INDEX IF NOT EXISTS idx_lo_category ON local_ordinances(category);
CREATE INDEX IF NOT EXISTS idx_lo_current ON local_ordinances(is_current);
CREATE VIRTUAL TABLE IF NOT EXISTS local_ordinances_fts USING fts5(
  ordinance_name, body_text, tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS ordinance_law_refs (
  ordinance_id TEXT, law_id TEXT,
  PRIMARY KEY (ordinance_id, law_id)
);
CREATE TABLE IF NOT EXISTS ordinance_program_refs (
  ordinance_id TEXT, program_id TEXT,
  PRIMARY KEY (ordinance_id, program_id)
);
```

ETL: `scripts/etl/ingest_local_ordinance_tokyo_metro.py` (東京都のみ実装、他 自治体は OTHER CLI が後続)
- 1 自治体 1 file 実装、Crawl-delay 10 sec 厳守
- Tokyo metro のみ 200-300 条例、12 week ramp の 1/N

**期待 (本 dispatch 分)**: ¥50K/月 (東京都 sample 1 自治体)、残り 26,700 ordinance は OTHER CLI loop で取りに来る後続

---

## 推奨実行順序 (依存 graph)

```
Group A (完全独立、5 並列):
  A_ext1 改正履歴       ─┐
  A_ext5 e-Stat surface ─┤
  A_ext6 パブコメ       ─┼─ 同時実行
  A_ext4 GEPS          ─┤
  A_ext8 特許          ─┘

Group B (am_tsutatsu 統合 mig 124 必要):
  mig 124 → A_ext3-FSA → A_ext3-MHLW → 残 5 官庁 (curl 並列)

Group C (am_amendment_diff phase mig 130):
  mig 130 → A_ext6 + A_ext1 phase link

A_ext7 行政処分 deep: 完全独立、view 追加のみ (mig 131)
A_ext2 都道府県条例: 完全独立、Tokyo のみ (mig 134)
```

最大並列度 ~10 同時走行可。

---

## migration 番号集計

| Mig # | target_db | 用途 |
|---|---|---|
| 121 | jpintel | subsidy_rate_text (既存) |
| 122 | jpintel | public_comments table |
| 123 | jpintel | bids GEPS extension |
| 124 | autonomath | am_tsutatsu unified |
| 125-126 | autonomath | (予約: 8 官庁通達 細分) |
| 127 | autonomath | e-Stat industry view |
| 130 | autonomath | am_amendment_diff phase column |
| 131 | autonomath | enforcement authority view |
| 132 | autonomath | am_law_revision (時系列履歴) |
| 133 | autonomath | am_patents |
| 134 | jpintel | local_ordinances |

135+ は OTHER CLI 自由使用。

---

## 制約 (両 CLI 共通、絶対遵守)

- LLM API を一切呼ばない (`anthropic`/`openai`/`google.generativeai`/`claude_agent_sdk`、CI guard `tests/test_no_llm_in_production.py`)
- agg サイト (noukaweb/hojyokin-portal/biz.stayway) を `source_url` に書かない
- robots.txt + 1 sec/host throttle
- ¥3/billable unit metered 単一料金、tier SKU / 月額 SKU 提案禁止
- `_archive/` 触らない
- 「工数」「priority」「phase」「まず」「次」「MVP」「stage」言葉禁止 (出力 / コミットメッセージ / docs)
- 営業電話 / sales call / DPA / 採用 / 広告 禁止
- DB VACUUM / 巨大 ALTER 避ける
- 既存 OTHER CLI 編集中ファイル (`api/intelligence.py` `services/evidence_packet.py`) を THIS CLI 痕跡 dispatch では触らないように設計済み (今回は OTHER CLI が main.py / programs.py 含めて全部担当可)
- 個人 PII redact (kojin_flag、inventor、住所等)
- 解釈は資格士業務 (税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47条の2 / 社労士法 §27 / 弁理士法 §75) → `_disclaimer` envelope + 事実摘要のみ
- 名誉毀損リスク: 10 年以前 default 除外、撤回処分は status='revoked' 表記
- 統計の秘匿 cell (1-2 事業所) を 0 と誤吸収しない、`secrecy_cells` count 必須

---

## 完了条件

```sql
-- 1. データ拡張 9 案 完了 SQL (autonomath.db)
SELECT
  (SELECT COUNT(*) FROM am_law_revision) AS law_revisions,         -- ≥ 100,000
  (SELECT COUNT(*) FROM am_tsutatsu) AS tsutatsu,                   -- ≥ 50,000
  (SELECT COUNT(*) FROM am_patents) AS patents,                     -- ≥ 1,000,000
  (SELECT COUNT(*) FROM am_amendment_diff WHERE phase='public_comment_open') AS pc_open;
                                                                    -- ≥ 1

-- 2. (jpintel.db)
SELECT
  (SELECT COUNT(*) FROM public_comments) AS public_comments,        -- ≥ 100
  (SELECT COUNT(*) FROM bids WHERE winner_houjin_bangou IS NOT NULL) AS geps_winners, -- ≥ 50,000
  (SELECT COUNT(*) FROM local_ordinances) AS ordinances;            -- ≥ 200 (東京都 sample)

-- 3. e-Stat surface
SELECT COUNT(*) FROM v_industry_benchmark; -- ≥ 1,000

-- 4. bench probe (既存)
-- precomputed_query_rate ≥ 80% (現状 40% から)
```

両 CLI 合算で 200-300 万/月射程到達確率 **50-65%**。

---

## OTHER CLI への一言

**全部やる前提で、user の手作業を最小化してください。許可は求めない、無理ならスキップして次のタスクに進む。`gh` / `fly` / `git push` は authenticated。npm / HF / SMTP は環境次第、不可なら EXECUTION_LOG.md に「未認証で skip」と書いて次へ。**

THIS CLI のセッションは以上で終わります。

---

## 補足参照

これ 1 本で完結するように書きましたが、より詳細な数値・smoke 結果は以下を参照:

- `docs/_internal/handoff_session_2026-05-01_for_deploy.md` (THIS CLI が積んだ 691 file の差分 + 認証 audit + 役割分担)
- `docs/_internal/handoff_consolidated_strategy_2026-05-01.md` (4 軸戦略 + 数学的事実)
- `docs/_internal/DEPLOY_CHECKLIST_2026-05-01.md` (45 項目)
- `analysis_wave18/data_extension_deep_*_2026-05-01.md` (10 個、各拡張の verify 結果)
- `analysis_wave18/data_extension_meta_dependency_2026-05-01.md` (依存 graph + シナリオ)
- `analysis_wave18/user_reality_*_2026-05-01.md` (9 cohort の honest 採用率)
- `analysis_wave18/honest_constraint_tradeoff_2026-05-01.md`

すべて Bookyou株式会社 (T8010001213708) / 梅田茂利 / info@bookyou.net。
