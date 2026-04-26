# LAUNCH_CONVERGENCE_2026-05-06

2026-05-06 本番 launch に向けた、**2 つの並走 CLI の成果を統合するための master plan**。
本ファイルは user + 他 CLI + 私 (このセッション) 3 者の共通 protocol。

作成: 2026-04-24 23:30 JST

---

## 現状 snapshot

### repo 2 分割

| 場所 | 作業主体 | 焦点 | DB | Schema |
|---|---|---|---|---|
| `/Users/shigetoumeda/jpintel-mcp/` | 他 CLI | 本番 polish (REST / MCP / Stripe / site) | `data/jpintel.db` 187MB | `programs` / `loan_programs` / `enforcement_cases` / `case_studies` / `laws` / `tax_rulesets` / `invoice_registrants` |
| `/tmp/autonomath_infra_2026-04-24/` | 私 | data rigor (Layer 2-10) | `autonomath.db` 7.3GB | `am_entities` / `am_entity_facts` / `am_*` 正規化 |

### 2026-04-24 23:26 で **物理 data 移送完了**

`/Users/shigetoumeda/jpintel-mcp/autonomath.db` (7.3 GB) は 0-byte placeholder から 7.3 GB 実 DB に sqlite3 `.backup` API で atomic 転送済。
- integrity_check: ok
- 全 13 table 行数 parity verified
- `AUTONOMATH_DB_MANIFEST.md` 冒頭で schema 開示済

**ただし本番 code (`src/jpintel_mcp/mcp/server.py` 等) はこの autonomath.db を未参照**。wiring が要る。

---

## 我々 (私) の成果 17 Wave 総覧

| Wave | 主要成果 |
|---|---|
| W3 | 性能 最適化 (bind_i03 4,410x / worst p95 6.2x)、21 index 追加 |
| W4 | Layer 2 (law_reference canonical) / Layer 3 (relation) / Layer 5 (semantic) / dedup / 出典 100% 一次資料 |
| W5 | am_amount_condition 34k / meti fallback / SPA fetch / FTS 224k backfill / adoption +145k / graph rescue 947 |
| W6 | unigram FTS / re-sweep / vec rebuild 424k / i08 population_exact 切替 / smoke_quick.sh / pepper rotation |
| W7 | proactive Layer 10 E2E / primary_source probe / cert 誤タグ / adoption announced_at 100% / customer walk 10/10 |
| W8 | 採択率 stats / tax_rule 9 / application_round / **DB swap 事件** → 復旧 + 14 base canonical 新設 |
| W9 | learning middleware v2 / /v1/meta/usage 透明性 / Zenn 3 記事 / examples repo / LP+registry / smoke+runbook / tax_rule 142 / SIB 35 / 政令市 20 / adoption amount 100% |
| W10 | vec sync / schema_lock (Wave 8 再発防止) / alias 270 / relation 625 / R&D 74 / synonym+router / dedup 2nd |
| W11 | 中核市 62 / amendment_snapshot 7,298 / subsidy_rule 44 / perf regression 5,975x / CLAUDE.md lessons draft / envelope v2 |
| W12 | am_loan 45 / FTS rewrite 2,591x / PyPI SDK autonomath / enforcement detail 1,186 / CI/CD 7 yaml / test 1,068 @ 81% coverage |
| W13 | GX/EV 52 / 特別区+一般市 159 / am_law_article 101 / Prometheus /metrics / TS SDK @autonomath/sdk |
| W14 | per-tool MCP docs 27 / EN docs 9 / Dockerfile draft / authority dedup 499→493 / cache layer 855x / webhook 2 table + 11 tests |
| W15 | status + freshness / API key scope+quota+rotation / compliance 6 docs 1,314 行 / release v0.1.0 / DR runbook 5 docs / 4-lang SDK (Deno/Swift/Kotlin/Go) |
| W16 | 医療/福祉/介護 60 / 観光/漁業/文化/教育 51 / batch endpoint / Jupyter notebook 6 / Postman etc. 4 format / 住宅/移住/災害/海外 60 |
| W17 | partner 6 integration / MCP resources 15 + prompts 12 / prompt injection defense 56 pattern / LP HTML mockup / 共済保険 31 / integrity sweep (+458 fix) |

**累計:** am_entities 388,967 / facts 5.26M / tax_rule 145 / 採択率 68 / app_round 1,106 / 法令条文 101 / 融資 45 / SIB 35 / 処分 1,186 / 共済 31 / FTS+unigram 各 388,967 / embedding 424,277 / 1,068 tests 81% coverage

---

## 他 CLI の成果 (CHANGELOG / CLAUDE.md から観測)

- `data/jpintel.db` で 9,998 programs + 2,286 採択事例 + 108 融資 + 1,185 行政処分 + 181 exclusion
- expansion tables: laws 6,850 継続 load / tax_rulesets 35 / invoice_registrants 13,801 (PDL v1.0)
- MCP 13 tool docstrings rewrite (2026 arxiv 2602.14878 negative prompt 排除)
- `/v1/meta` + `/v1/openapi.json` endpoint (308 redirect)
- `site/404.html` / `site/rss.xml` / `site/_redirects`
- JP-localized 429/422 error
- Stripe `consent_collection.terms_of_service` 500 修正
- `scripts/refresh_sources.py` nightly URL scan + 3-strike quarantine
- tier-badge / "Free tier" 削除、metered ¥3/req 統一

---

## 統合決定が必要な 8 項目

### D1. autonomath.db wiring (最優先)

`src/jpintel_mcp/mcp/server.py` が autonomath.db を叩く path を追加するか?
- **Yes (wire-in)**: 新 MCP tools 10+ が利用可能に。launch で使える data が 40x 以上増
- **No (defer)**: launch 時は既存 13 tools + `data/jpintel.db` だけ。autonomath.db は T+N 日 で合流
- 推奨: **Yes、ただし feature flag で fail-safe** (`AUTONOMATH_DB_ENABLED=true` env)

### D2. MCP tool 数

現状: 本番 13 + staging 10+ 新規 = 23+。CLAUDE.md は 31 (stale)、ops reality 不明。
- 最小: 13 (既存のみ)
- 中庸: 13 + Wave 8-17 の 10 (reason_answer / get_tax_rule / search_acceptance_stats 等) = 23
- 全部: 30+ (SIB / 共済 / GX / 条文 含む)
- 推奨: **23** (実装済 10 を drop-in、残は launch 後)

### D3. DB file 数

- 本番 file 2 枚体制 (`data/jpintel.db` 187MB + `autonomath.db` 7.3GB): ATTACH or 別 connection
- 1 枚統合 (am_* を jpintel.db に INSERT): migration 手間あり、しかし運用単純
- 推奨: **2 枚体制 launch → T+30日 で 1 枚統合判断**

### D4. Fly.io volume

現行推定: 3GB default。autonomath.db 7.3GB で足りない。
- 20GB vol に extend 必須 (Wave 14 Dockerfile agent が計画済)
- R2 から cold-start download (bootstrap 3-10min、Wave 14 entrypoint.sh 済)
- 推奨: **volume 20GB extend + R2 snapshot URL 経由 cold-start**

### D5. Docker image

現行 image (推定 185MB) に 7GB DB 同梱 or 分離?
- 同梱: pull 長い (7+GB image)、 rollback 時は 2 image ある方 recoverable
- 分離: image 軽い (<1GB)、 DB は volume に残す
- 推奨: **分離 (volume 運用)、image は embedding model + sqlite-vec + 実行 code のみ**

### D6. 新 MCP tools の wiring ソース

/tmp/autonomath_infra_2026-04-24/mcp_new/ に 10+ tool 実装済。
- `tools.py` (2,600 行) + `envelope_wrapper.py` (Wave 11 v2) + tool 別 file 10
- option A: 全部 本番 repo に copy (src/jpintel_mcp/mcp/autonomath_tools/)
- option B: 段階移植 (重要 3 tool のみ launch、残 post-launch)
- 推奨: **option A、ただし unregistered (register は D2 判断後に 1 行 import で完了)**

### D7. schema_guard 本番配備

Wave 8 DB swap 事件再発防止の scripts/schema_guard.py を本番 code 起動時に先行実行
- 本番 startup で `assert_am_entities_schema(autonomath.db)` 強制
- 他 CLI の ingest_laws.py 等は `data/jpintel.db` scope で触らない
- 推奨: **本番起動時に guard を追加 (fail-fast)**

### D8. launch 後の更新経路

新制度 / 新数字 を本番 autonomath.db に反映する流れ
- /tmp staging で作業 → backup API で本番 autonomath.db に replace (launch 後 T-12h quiescent window)
- 週次 cron で自動 pull?
- 推奨: **手動、週次、user or 他 CLI が実行。自動化は post-launch 安定後**

---

## Phase plan

### Phase A — Data 搬入 ✅ 完了 (2026-04-24 23:26)
- jpintel-mcp/autonomath.db に 7.3 GB copy
- AUTONOMATH_DB_MANIFEST.md 書出し

### Phase B — wiring (推奨期限 T-5日 = 2026-05-01)
**他 CLI or user 判断**:
- B1. D1 の feature flag 追加
- B2. D2 判断で register する tool 10 選定
- B3. `/tmp/autonomath_infra_2026-04-24/mcp_new/` 内実装を `src/jpintel_mcp/mcp/autonomath_tools/` に copy
- B4. `src/jpintel_mcp/mcp/server.py` に 1-2 行 import + register 追加
- B5. Fly.io volume extend + R2 snapshot URL 設定

### Phase C — smoke + deploy (T-2日 = 2026-05-04)
- smoke_test.sh --strict (Wave 6 Agent #5)
- pre_flight.sh (Wave 10 Agent #2)
- chaos test (Wave 15 Agent #5 plan)

### Phase D — launch (2026-05-06)
- T-12h writer freeze
- T-6h final smoke
- T-3h create_launch_db.sh snapshot
- T-0 3-way deploy (flyctl + twine + mcp publish)
- T+1h post-launch observation

### Phase E — T+N 日 (post-launch)
- real query log 分析 (Wave 9 #1 middleware v2 + Wave 9 #2 /v1/meta/usage)
- empty bucket 頻出 query 特定 → data 補充
- 品質系 Wave を real traffic driven に 再開

---

## 私 (この session) が 次 やる 3 options

### A. 全部 完遂 (24-36h)
`src/jpintel_mcp/mcp/server.py` 書換えて tool wiring + Fly config + Dockerfile まで apply。**他 CLI と直接重なる。**

### B. 完全 stop
data 搬入 + manifest までで終了。 user or 他 CLI に引き継ぎ。

### C. drop-in 追加のみ (推奨)
`/tmp/autonomath_infra_2026-04-24/mcp_new/` を `src/jpintel_mcp/mcp/autonomath_tools/` に copy。**server.py は触らず、register は 1 行追加で済む形**に。他 CLI や user が最少 diff で取り込める。

---

## user 決定待ち event log

- `[ ] 2026-04-24` D1 (wiring 方針) 決定
- `[ ] 2026-04-24` D2 (tool 数) 決定
- `[ ] 2026-04-25` D3 (DB file 数) 決定
- `[ ] 2026-04-26` B1-B5 実施者指名 (user / 他 CLI / 私)
- `[ ] 2026-04-27` Fly volume extend 実施
- `[ ] 2026-04-29` Dockerfile 本番化
- `[ ] 2026-05-01` Phase B 完了目標
- `[ ] 2026-05-04` Phase C smoke complete
- `[ ] 2026-05-06` launch

---

## 連絡 / 運営

Bookyou株式会社 (T8010001213708) / 梅田茂利 代表 / info@bookyou.net

**本 md は生き文書**。各 decision が確定次第、該当 row を `[x]` + 決定内容で更新すること。
