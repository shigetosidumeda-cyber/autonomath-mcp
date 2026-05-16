# Wave 51 L1 + L2 設計 doc — P1 source expansion + 数学エンジン

**status**: 設計のみ / 実装禁止 (design doc only, no implementation)
**author**: jpcite ops
**date**: 2026-05-16
**SOT marker**: `docs/_internal/WAVE51_L1_L2_DESIGN.md`
**supersedes**: なし (Wave 50 RC1 = `docs/_internal/WAVE50_SESSION_SUMMARY_2026_05_16.md` の後続軸)
**precedes**: `docs/_internal/WAVE51_plan.md` (未作成、本 doc を baseline に起票)

---

## 0. 位置付け — Wave 50 RC1 → Wave 51 L1+L2 遷移

Wave 50 (2026-05-16) で **RC1 contract layer** が完成 (19 Pydantic model + 20 JSON Schema + 14 outcome contract + 5 preflight gate artifact + production gate 7/7 PASS + mypy strict 0 + coverage 76-77%)。Wave 49 organic axis は並列継続 (G1 RUM beacon LIVE, G3 5 cron SUCCESS, G4/G5 first txn 待機)。

Wave 51 は RC1 contract layer の **上に積む 2 軸**:

- **L1 (Lateral expansion)**: 14 outcome contract に対し、現 6 source family を **30+ source family** に拡張 (cross product 84 → 420 entry)。**outcome は増やさない**、source の網羅性だけ広げる。
- **L2 (Vertical depth)**: 14 outcome 内で **LLM 不要の数学エンジン** (sweep / pareto / monte carlo) を追加し、parameter 多次元検索を 1 call で解放。`composed_tools/` に 3 new MCP tool として export。

両軸とも **¥0.5/req 構造を破らない** (NO LLM call inside tools)。L1 は SQLite + ETL の純粋データ追加、L2 は numpy + scipy 既存依存のみで pure math computation。**Wave 51 で AX Layer 5 (federated + composed + time-machine) の "composed" 軸を具現化**する位置付け。

---

## L1: P1 source expansion

### 1.1 目的

現 `outcome_source_crosswalk.json` (`site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json`) は 14 deliverable × 6 source family (gBizINFO / edinet / nta_invoice / e_gov / maff / mhlw) で **84 entry**。Wave 51 で **30+ source family** に拡張し、**14 × 30 = 420 entry** の cross product を実現する。

「source 数 30+」は **agent 経済の Discoverability + Justifiability + Trustability 3 軸の上限を引き上げる**ための投資。AI agent から "あらゆる公的 source を 1 hop で justifiable に拾える" 状態 = federated MCP recommendation hub 化 (Dim R) の前提条件。

### 1.2 追加 source family (30+ target)

| 区分 | source_family_id | 出典 | 既存/新規 | category |
| --- | --- | --- | --- | --- |
| 中央省庁・税務 | `nta_invoice`, `nta_saiketsu`, `nta_tsutatsu_index` | 国税庁 | 既存 (Wave 23) | tax |
| 中央省庁・法令 | `e_gov_laws`, `e_gov_pubcom` | e-Gov | 既存 / 新規 | court_admin_guidance |
| 中央省庁・経産 | `meti_subsidy`, `meti_chusho_keiei`, `j_grants` | 経産省 + 中小企業庁 | 新規 (P1) | subsidy |
| 中央省庁・国交 | `mlit_kentiku_kyoka`, `mlit_takken_db`, `mlit_kasen_kyoka` | 国交省 | 新規 (P1) | construction_permit |
| 中央省庁・厚労 | `mhlw_roukijun`, `mhlw_shaho`, `mhlw_yakuji` | 厚労省 | 既存部分 + 新規 | labor / health |
| 中央省庁・農林 | `maff_hojo_kettei`, `maff_eisei`, `maff_keieikai` | 農水省 | 既存部分 | subsidy / sanitation |
| 中央省庁・環境 | `env_haiki`, `env_co2` | 環境省 | 新規 (P1) | environment |
| 中央省庁・総務 | `soumu_chiho_zaisei`, `soumu_jumin_kihon` | 総務省 | 新規 (P1) | local_gov |
| 中央省庁・財務 | `mof_yosan`, `mof_kanzei` | 財務省 + 関税 | 新規 (P1) | budget / customs |
| 中央省庁・文科 | `mext_kenkyuhi`, `mext_gakko` | 文科省 | 新規 (P1) | research |
| 法人・登記 | `gbiz_info`, `edinet`, `nta_houjin_bangou` | gBizINFO / EDINET / NTA | 既存 | corp_master |
| 司法 | `courts_decisions`, `nta_saiketsu` | 裁判所 + 国税不服審判所 | 既存 | judicial |
| 公庫・公的金融 | `jfc_loan`, `shoukoukai_loan` | 日本政策金融公庫 + 商工会 | 既存 (Wave 23) | public_finance |
| 自治体 (segmented) | `pref_47` (47 都道府県, 1 family per pref で wrapper, 内部は family_subkey) | 各都道府県公報 | 新規 (P1) | local_subsidy |
| 自治体 (segmented) | `muni_800` (主要 800 市町村、wrapper 1 + family_subkey で展開) | 各市町村公報 | 新規 (P1) | local_subsidy |
| 入札 | `bid_jp_central`, `bid_pref`, `bid_muni` | NJSS + 各自治体 | 既存部分 | bid |
| 統計 | `e_stat`, `stat_pref` | 政府統計 + 都道府県統計 | 既存 (e-Stat のみ) | statistics |

**source_family_id 30+ 達成パス**: 上記 30 行のうち `pref_47` と `muni_800` を **1 family wrapper + family_subkey で展開** すれば parent count は 30 のまま分布は 800+。**crosswalk entry は 14 × 30 = 420 が最大**、実際は outcome の性質で間引かれて **350±20 entry** を見込む。

### 1.3 schema 拡張

#### 1.3.1 `am_source_receipts` (existing)

既存 `am_source_receipts` table をそのまま使用 (source_id / fetched_at / sha256 / response_status / license)。Wave 51 では **追加 column なし**。

#### 1.3.2 `am_source_family_metadata` (new — Wave 51 migration 105)

新規 table を `scripts/migrations/105_wave51_source_family_metadata.sql` (target_db: autonomath, idempotent CREATE IF NOT EXISTS) で起票:

```sql
-- target_db: autonomath
CREATE TABLE IF NOT EXISTS am_source_family_metadata (
  source_family_id TEXT PRIMARY KEY,
  ministry_code TEXT NOT NULL,         -- 'meti' / 'mlit' / 'mhlw' / 'maff' / 'env' / 'soumu' / 'mof' / 'mext' / 'nta' / 'e_gov' / 'pref_*' / 'muni_*'
  category TEXT NOT NULL,              -- 'subsidy' / 'tax' / 'permit' / 'labor' / 'health' / 'environment' / 'local_subsidy' / ...
  source_category TEXT NOT NULL,       -- crosswalk 既存 enum と同期
  license TEXT NOT NULL,               -- 'cc_by_4.0' / 'pdl_v1.0' / 'gov_standard' / 'proprietary'
  refresh_frequency TEXT NOT NULL,     -- 'daily' / 'weekly' / 'monthly' / 'quarterly' / 'ad_hoc'
  authority_url TEXT NOT NULL,         -- 一次 URL (root)
  is_segmented INTEGER NOT NULL DEFAULT 0,   -- pref_47 / muni_800 用
  segment_dimension TEXT,              -- 'prefecture_code' / 'municipality_code' / NULL
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_am_source_family_metadata_ministry ON am_source_family_metadata (ministry_code);
CREATE INDEX IF NOT EXISTS idx_am_source_family_metadata_category ON am_source_family_metadata (category);
```

**seed data**: 30 source_family_id を SQL seed (`scripts/migrations/105_wave51_source_family_metadata.sql` 末尾の `INSERT OR REPLACE INTO ...` 30 行) で投入。`pref_47` + `muni_800` は `is_segmented=1` で wrapper 1 行、segment_dimension で展開軸を宣言。

#### 1.3.3 `outcome_source_crosswalk.json` 拡張

`site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json` の `crosswalk` 配列を **84 → 350±20** に拡張。各 entry に以下を追加:

- `public_source_family_ids` (existing) を 30+ family pool から間引いた subset で fill
- `source_family_metadata_refs` (new) — `am_source_family_metadata.source_family_id` への FK 列挙、契約上の整合性チェック用 (`scripts/check_schema_contract_parity.py` で round-trip)

**14 outcome 別の source family 平均配置**:

- `company-public-baseline`: 8-10 family (corp + tax + judicial + 法務局)
- `invoice-registrant-public-check`: 3-4 family (nta系)
- `subsidy-grant-candidate-pack`: 15-18 family (中央省庁 全 8 + 自治体 wrapper + 公庫)
- `law-regulation-change-watch`: 5-6 family (e_gov_laws + pubcom + meti + mhlw + maff)
- `local-government-permit-obligation-map`: 12-15 family (mlit + env + soumu + pref + muni)
- `court-enforcement-citation-pack`: 4-5 family (courts + nta_saiketsu + e_gov + enforcement)
- `public-statistics-market-context`: 5-7 family (e_stat + stat_pref + meti + maff + soumu)
- `client-monthly-public-watchlist`: 20+ family (composite — 顧問先 fan-out)
- `accounting-csv-public-counterparty-check`: 3-4 family (corp + invoice)
- `cashbook-csv-subsidy-fit-screen`: 15+ family (subsidy系 横断)
- `source-receipt-ledger`: 30 family (全 family が ledger 対象)
- `evidence-answer-citation-pack`: 8-12 family (deliverable に応じ動的)
- `foreign-investor-japan-public-entry-brief`: 10+ family (e_gov_laws.body_en + tax_treaty + env + mlit + meti FDI 系)
- `healthcare-regulatory-public-check`: 6-8 family (mhlw_yakuji + e_gov + 厚生局 + nta + courts)

**合計 entry**: 8 + 3 + 16 + 5 + 13 + 4 + 6 + 22 + 3 + 16 + 30 + 10 + 11 + 7 ≈ **354 entry** (目標 350±20 を満たす)。

### 1.4 `policy_decision_catalog` 拡張

`site/releases/rc1-p0-bootstrap/policy_decision_catalog.json` (Wave 50 で 5 entry 着地) を **30+ entry** に拡張:

- 既存 5 (§52 / §47条の2 / §72 / §1 / §3) を保持
- 新規追加 (Wave 51 で 25+ 起票):
  - 社労士法 §27 (労働社会保険諸法令の業) — `mhlw_roukijun` / `mhlw_shaho` 跨ぎ surface
  - 行政書士法 §1の2 — `mlit_takken` / 建築許認可系 surface
  - 司法書士法 §3 — `houjin_master` / 登記系 surface
  - 弁理士法 §75 — 特許/商標系 (`meti_chusho_keiei` 一部) surface
  - 公認会計士法 §2 — `edinet` 監査系 surface
  - 不動産鑑定士法 §3 — `mlit_takken` 鑑定系 surface
  - 個人情報保護法 §27 / §28 — PII 跨ぎ surface (Dim N anonymized_query への接続)
  - 景表法 §5 — 表現 surface (estimate / forecast 系 tool egress)
  - 消費者契約法 §10 — 不当条項 surface
  - 著作権法 §47条の5 — AI 学習データ surface (法令 corpus の再配信境界)
  - GDPR Art.6 / Art.45 — foreign FDI cohort EU データ surface
  - 各業法 (建設業法 / 宅建業法 / 旅館業法 / 食品衛生法 / 薬機法 / 道路運送法 等) 25-30 surface

**effect**: 7 sensitive surface × disclaimer envelope を **30+ surface × disclaimer envelope** に拡張、JPCIR `policy_decision_catalog.schema.json` (Wave 50 schema) の `decision_entry` array 5 → 30+。schema parity は `scripts/check_schema_contract_parity.py` 通過必須。

### 1.5 ingest / refresh cron

**新規 cron 群** (`scripts/cron/`、`.github/workflows/`):

- `ingest_meti_subsidy.py` + `.github/workflows/meti-ingest-monthly.yml` (毎月 1 日 03:00 JST)
- `ingest_mlit_permit.py` + `.github/workflows/mlit-ingest-weekly.yml`
- `ingest_mhlw_labor_health.py` + `.github/workflows/mhlw-ingest-weekly.yml`
- `ingest_maff_subsidy.py` (既存延伸)
- `ingest_env_haiki_co2.py` (新規)
- `ingest_soumu_chiho.py` (新規、`pref_47` + `muni_800` の wrapper ETL)
- `ingest_mof_yosan_kanzei.py` (新規)
- `ingest_mext_kenkyuhi.py` (新規)

**頻度**: 月次 6 cron + 週次 2 cron + 既存延伸 1 cron = **9 cron 新規 (Wave 51 cron 数 +9)**。Wave 49 G3 5 cron に積み増しで **14 cron / week (8 weekly + 6 monthly)** が定常運用。

### 1.6 license / TOS gate

- `cc_by_4.0` (e_gov_laws / 一部 e_stat): API 再配信 OK、出典明記。
- `pdl_v1.0` (nta_invoice / nta_houjin_bangou): API 再配信 OK、出典明記 + 編集注記。
- `gov_standard` (政府標準ライセンス): 出典明記で再配信 OK。
- `proprietary` (一部自治体オープンデータ): 個別 TOS 確認、当面は **URL link のみ surface** (本文再配信なし)。
- データ収集 phase 中の TOS-block は `feedback_data_collection_tos_ignore` 原則で acquisition 優先、商用配信は launch 直前に再評価 (本 Wave 51 では launch 後の追評価を schedule)。

---

## L2: 数学エンジン (sweep / pareto / monte carlo)

### 2.1 目的

14 outcome 内で **多次元 parameter 検索 + 最適化を 1 call で解放** (現状は 7 個別 call → 1 composed call へ統合)。`feedback_composable_tools_pattern` の "atomic 139 tool → composed 7 系" 設計、`feedback_agent_anti_patterns_10` の "LLM で都度推論させない" 原則の具現化。

**LLM 一切呼ばない** (`feedback_no_operator_llm_api` 厳守)。numpy + scipy だけで pure math computation、結果に `_reasoning_path` (rule + parameter trace) を inject し justifiability を確保。

### 2.2 配置

```
src/jpintel_mcp/services/math_engine/
  __init__.py
  sweep.py          # parameter sweep (grid / lhs / sobol)
  pareto.py         # multi-objective Pareto front
  montecarlo.py     # probabilistic simulation
  _common.py        # shared types (Candidate / RankedResult / ReasoningPath)
  _validators.py    # input validation against outcome_contract
```

### 2.3 3 アルゴリズム

#### 2.3.1 sweep — parameter sweep

- **input**: `outcome_contract_id` + `parameter_grid: dict[str, list[Any]]` (例: `{"amount_jpy": [500_000, 1_000_000, ..., 50_000_000], "industry_jsic_major": ["D", "E", "K"], "prefecture_code": ["13", "14", "27"]}`)
- **algorithm**: full-factorial grid (default) / Latin Hypercube Sampling (`scheme="lhs"`) / Sobol sequence (`scheme="sobol"`)
- **output**: `list[Candidate]` (上限 max_candidates default 200) — 各 candidate は `{parameters: dict, score: float, reasoning_path: list[str]}`
- **score 関数**: outcome 別 score (e.g., subsidy-grant の場合 = `expected_benefit_jpy / risk_score`、permit の場合 = `eligibility_rate * (1 - rejection_rate)`)。`outcome_catalog.py` に既存定義 を拡張。
- **使い道**: 「補助金額 × 業種 × 地域 を全組合せで benefit 計算」「税制ルール × 売上規模 × 法人形態 で控除額シミュレーション」

#### 2.3.2 pareto — multi-objective Pareto front

- **input**: `outcome_contract_id` + `objectives: list[Objective]` (各 objective は `{name: str, direction: 'min'|'max', weight: float | None}`) + `candidates: list[Candidate] | parameter_grid: dict`
- **algorithm**: NSGA-II 風 non-dominated sorting (scipy + 自前 implementation、numpy vectorize)。**重み付き合成スコアは optional** (主目的は dominance front の抽出)
- **output**: `pareto_front: list[Candidate]` (front 0 のみ default、`include_higher_fronts=True` で front 1-3 まで) + `dominated: list[Candidate]` (棄却理由付き)
- **典型 use case**: 「cost(min) × risk(min) × 採択率(max) の 3 目的 pareto front」「補助金 cost(min) × 申請工数(min) × 受給期待値(max)」
- **reasoning_path**: 各 candidate の dominance 判定理由 (どの objective で他候補を dominate / dominated されたか)

#### 2.3.3 monte carlo — probabilistic simulation

- **input**: `outcome_contract_id` + `distributions: dict[str, Distribution]` (`Distribution` は scipy.stats wrapper: `{"type": "norm", "loc": ..., "scale": ...}` / `"beta"` / `"triangular"` / `"empirical"`) + `n_samples: int` (default 5000, max 50000)
- **algorithm**: `np.random.Generator(PCG64)` で seed 固定、reproducibility 保証。各 sample で outcome 別 evaluator function を実行
- **output**: `{mean: float, p5: float, p25: float, p50: float, p75: float, p95: float, p99: float, samples: list[float] (optional, default=truncated 500)}` + `reasoning_path`
- **典型 use case**: 「申請成功確率 (採択履歴 prior + 業種 likelihood の Bayesian update を NO — 単純な empirical bootstrap で代替)」「補助金交付額の不確実性区間」「税負担額の確率分布」
- **重要**: Bayesian は **やらない** (`feedback_patent_content_unused` 原則の Bayesian 検証禁止に整合)。empirical bootstrap + 単純なシナリオ重ね合わせのみ。

### 2.4 入出力契約

**input envelope** (Pydantic, `contracts.py` に追加):

```python
class MathEngineRequest(BaseModel):
    outcome_contract_id: str
    algorithm: Literal["sweep", "pareto", "montecarlo"]
    parameters: dict[str, Any]  # algorithm 別に validator dispatch
    max_candidates: int = 200
    seed: int = 42
    include_reasoning: bool = True
```

**output envelope**:

```python
class MathEngineResult(BaseModel):
    outcome_contract_id: str
    algorithm: str
    candidates: list[RankedCandidate]
    summary: dict[str, Any]  # mean/p50/p95 etc. for monte carlo, or front_size for pareto
    reasoning_path: list[str]
    corpus_snapshot_id: str
    corpus_checksum: str
    disclaimer: Disclaimer | None  # outcome が sensitive surface の場合のみ
    billing_hint: BillingHint  # 1 req ¥3 固定 (composed は加算なし)
```

`RankedCandidate.reasoning_path` には rule_id + parameter trace + dominance 判定 (pareto の場合) を string list で record。**LLM 由来の自然言語は一切混ぜない**。

### 2.5 integration — composed_tools/ への export

新規 directory: `composed_tools/` (リポジトリ root 直下 — Wave 51 で create)。

```
composed_tools/
  __init__.py
  sweep_outcome_grid.py        # MCP tool: sweep_outcome_grid
  pareto_outcome_front.py      # MCP tool: pareto_outcome_front
  montecarlo_outcome_uncertainty.py  # MCP tool: montecarlo_outcome_uncertainty
  _registry.json               # composed_tools 一覧 + outcome binding
```

**MCP tool 登録**: `src/jpintel_mcp/mcp/server.py` の tool registration block に **3 新規 tool**:

- `sweep_outcome_grid(outcome_contract_id, parameter_grid, scheme, max_candidates)`
- `pareto_outcome_front(outcome_contract_id, objectives, candidates_or_grid, include_higher_fronts)`
- `montecarlo_outcome_uncertainty(outcome_contract_id, distributions, n_samples, seed)`

**gate**: `JPCITE_MATH_ENGINE_ENABLED` (default ON)。tool count = 現 139 manifest → **142 (intentional bump)**、runtime cohort = 現 146 → **149**。manifest bump は Wave 51 の release gate と束ねる (`pyproject.toml` v0.4.0 / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json` 5 surface 同時 bump)。

### 2.6 tests

新規 test file 3 本 + 統合 1 本:

- `tests/test_math_engine_sweep.py` — 入力 validation / grid / lhs / sobol 3 scheme / max_candidates 上限 / outcome 別 score / reasoning_path 形式
- `tests/test_math_engine_pareto.py` — dominance 判定 / NSGA-II 非劣解 / 3 objective 以上 / weight 合成 vs front 抽出
- `tests/test_math_engine_montecarlo.py` — distribution 種別 / seed 再現性 / percentile 正確性 / max samples 50000 / Bayesian 不使用 assertion
- `tests/test_math_engine_integration.py` — composed_tools 経由 e2e + envelope schema parity + billing hint ¥3 固定

**coverage 目標**: 各 module 90%+、新規 tests **+80** (Wave 51 で landed)。

### 2.7 dependencies

- numpy (既存依存)
- scipy (既存依存、scipy.stats + scipy.optimize は既存利用あり)
- **NO LLM** — `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk` を `services/math_engine/` 配下に **絶対に import しない**。CI guard `tests/test_no_llm_in_production.py` で enforce 継続。

### 2.8 sensitive surface 接続

`outcome_contract_id` が sensitive surface (subsidy-grant / law-regulation-change / court-enforcement / healthcare-regulatory 等) の場合、`MathEngineResult.disclaimer` に `policy_decision_catalog` の対応 entry から `Disclaimer` envelope を inject。§52 / §47条の2 / §72 / 各業法の最新 ruling を契約 metadata 化。

---

## 3. implementation roadmap (Wave 51 week 1-2 scope)

### Week 1 (tick 1-7、設計 → migration → seed)

- **tick 1**: Wave 51 plan doc 起票 (`docs/_internal/WAVE51_plan.md`)、本 L1+L2 design を baseline に reference
- **tick 2**: migration 105 (`am_source_family_metadata`) 起票 + 30 source_family_id seed
- **tick 3**: `outcome_source_crosswalk.json` 拡張 (84 → 354 entry)、`source_family_metadata_refs` 列追加
- **tick 4**: `policy_decision_catalog.json` 拡張 (5 → 30+ entry)、JPCIR schema parity 通過
- **tick 5**: 9 新規 cron + 8 GHA workflow 起票 (実 ingest は week 2 で smoke)
- **tick 6**: `src/jpintel_mcp/services/math_engine/` 骨子 (`__init__.py` + `_common.py` + `_validators.py`)
- **tick 7**: contracts.py に `MathEngineRequest` + `MathEngineResult` + `RankedCandidate` Pydantic 追加、schema round-trip

### Week 2 (tick 8-14、math 実装 → composed tools → test → release)

- **tick 8**: `sweep.py` 実装 (grid + lhs + sobol)
- **tick 9**: `pareto.py` 実装 (NSGA-II 風 non-dominated sorting)
- **tick 10**: `montecarlo.py` 実装 (distributions + percentile + reasoning_path)
- **tick 11**: `composed_tools/` 3 file + `_registry.json` + MCP server.py 登録
- **tick 12**: 4 test file (sweep / pareto / montecarlo / integration) + coverage +80 tests
- **tick 13**: 9 cron の monthly/weekly smoke (実 ingest first call、L1 source の row count baseline 取得)
- **tick 14**: 5 manifest surface 同時 v0.4.0 bump + production gate 7/7 維持 + release notes

### Wave 51 exit criteria (week 2 終端)

- migration 105 applied (autonomath.db、entrypoint.sh §4 で auto-pickup)
- `am_source_family_metadata` 30 row seeded
- `outcome_source_crosswalk` 350±20 entry
- `policy_decision_catalog` 30+ entry
- 9 新規 cron LIVE (smoke first call 全 SUCCESS、月次 1st-of-month 03:00 JST 待機)
- 3 composed math tools LIVE (`sweep_outcome_grid` / `pareto_outcome_front` / `montecarlo_outcome_uncertainty`)
- manifest tool_count: 139 → **142** (intentional bump、runtime 146 → 149)
- pytest: tick 4 base + L2 4 file (+80 tests)
- mypy strict: 0 errors 維持
- coverage: 76-77% → **78%+** (math_engine 新規 module の 90%+ 加算で底上げ)
- production gate: 7/7 維持
- **NO LLM**: `tests/test_no_llm_in_production.py` 継続 PASS

### 範囲外 (Wave 51 で扱わない)

- Wave 49 G2 (Smithery + Glama listing) — user paste 案件、Wave 51 に持ち込まない
- Wave 49 G4/G5 first real txn — organic 流入 driven、Wave 51 で flip 待機継続
- AWS canary 実 live 実行 — operator token 案件、Wave 51 とは並列軸
- AX Layer 5 の federated / time-machine 軸 — composed のみ Wave 51 で着地、federated と time-machine は Wave 52 以降
- 商用 license 再評価 (TOS gate) — launch 直前評価原則を維持

---

## 4. risk + open question

- **R1**: `pref_47` / `muni_800` の wrapper 1 family + segment_dimension 設計は honest だが、AI agent からの "都道府県別 source 検索" が 2-hop になる懸念。**mitigation**: `composed_tools/lookup_segmented_source.py` 1 本で 2-hop を 1 call wrap (Wave 51 後半 tick 13 で追加検討、Wave 52 持ち越し可)。
- **R2**: 30+ source family の ingest 安定化に最初 2-4 週かかる。**mitigation**: row count baseline を tick 13 で取得、出揃わない family は `am_source_family_metadata.notes` に "ingest_pending" marker、crosswalk 側からは family_id を含めるが受領 row が 0 でも UX 上 fail しない設計 (`no_hit_semantics` 既存 blueprint で吸収)。
- **R3**: 数学エンジンの outcome 別 score 関数定義が outcome_catalog.py の責務肥大化。**mitigation**: `services/math_engine/_scorers/` sub-package に outcome 別 scorer を分離、各 scorer は `from outcome_catalog import OutcomeContract` で envelope を借りるだけ。
- **R4**: monte carlo の `n_samples=50000` で per-call latency が ¥3/req SLA を超える懸念 (>2s)。**mitigation**: numpy vectorize 徹底 + per-sample 計算を `np.vectorize` でなく ndarray 演算化、5000 sample で 200ms 上限、50000 sample でも 1s 以内目標。SLA 超過時は `n_samples` を内部で down-sample + summary に `samples_actual` を declare。
- **OQ1**: composed_tools/ を repo root 配置 vs `src/jpintel_mcp/composed_tools/` 配置 — 本 design では **repo root 配置** を提案 (MCP discoverability + 外部 agent からの直接 reference 容易性)、Wave 51 tick 1 で最終確定。
- **OQ2**: `policy_decision_catalog` 30+ entry に各業法を含めるべきか、それとも 7 主要 + 23 業法を別 artifact (`industry_policy_catalog.json`) に分けるべきか — 本 design では **1 catalog に統合** を提案、size > 2000 行になったら分割再考。

---

## 5. SOT marker

- **本 doc**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE51_L1_L2_DESIGN.md`
- **Wave 50 baseline**: `docs/_internal/WAVE50_SESSION_SUMMARY_2026_05_16.md`
- **Wave 49 organic axis (並列)**: `docs/_internal/WAVE49_plan.md`
- **Wave 51 plan (未起票、本 doc を baseline に week 1 tick 1 で起票)**: `docs/_internal/WAVE51_plan.md`
- **canonical jpcir registry**: `schemas/jpcir/_registry.json`
- **parity check**: `scripts/check_schema_contract_parity.py`
- **outcome catalog**: `src/jpintel_mcp/agent_runtime/outcome_catalog.py`
- **outcome crosswalk**: `site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json`
- **policy decision catalog**: `site/releases/rc1-p0-bootstrap/policy_decision_catalog.json`
- **memory bindings**: `feedback_composable_tools_pattern` / `feedback_no_operator_llm_api` / `feedback_data_collection_tos_ignore` / `feedback_agent_anti_patterns_10` / `feedback_agent_funnel_6_stages`

last_updated: 2026-05-16
status: design only — implementation BLOCKED until user explicit Wave 51 start
