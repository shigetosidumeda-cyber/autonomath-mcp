# Post-Deploy W5-W8 Continuation Plan

**期間**: 2026-05-06 (launch day) → 2026-06-03 (4 週間)
**稼働**: 1,000h (Claude 本体 + 並列 sub-agent 6-12/日)
**前身計画**: `~/.claude/projects/-Users-shigetoumeda/memory/project_jpintel_1000h_plan.md` (W1-W4)
**依拠 SSOT**: `LAUNCH_READINESS.md` / `LAUNCH_GAPS_AUDIT.md` / `README.md` / `research/competitive_landscape.md` / `research/content_calendar.md`

---

## 0. 目的と前提 (Problem frame)

W1-W4 は「汎用 API として公開できる品質に届かせる」計画で、5/6 がそのゴール。W5-W8 は **「公開しただけでは売れない」** を前提に、**deploy → access → signup → paid → retention** ファネルを包括的に埋める。

- agri niche を残したまま汎用化を進める (Fork 判断は W8 末に延期)
- 対人営業ゼロ、docs とコードだけで成立
- CONSTITUTION 13.2 の 5 禁止事項 (η, 階層検証, Bayesian, AIでAI, 独自wire) を完全遵守
- 買わせ策 (dark pattern) ではなく **「買う価値を生む」** 方向の投入だけ

---

## 1. North-star metrics (3 numbers, measurable)

| Metric | 計測方法 | D+7 (5/13) | D+14 (5/20) | D+21 (5/27) | D+28 (6/03) |
|---|---|---|---|---|---|
| **MAU (free + paid)** | `usage_log` 内 distinct `api_key_id` / 月次 rolling | 300 | 700 | 1,200 | 1,800 |
| **Paid conversions** (Paid tier 累計) | `subscriptions` table WHERE status='active' | 5 | 15 | 28 | 45 |
| **Search requests/day** (90d trailing avg) | `usage_log` 日次合計 → 90d MA | 2,000 | 6,000 | 12,000 | 20,000 |

- **失敗境界**: D+14 paid=0 → ピボット検討 / D+28 MAU<100 → PMF 仮説見直し (§9)
- **ダッシュボード**: `/v1/admin/metrics` (W6 実装、§6 参照)
- **自動集計**: 日次 cron (`scripts/daily_metrics.py`) が `research/metrics/YYYY-MM-DD.json` に追記 (owner: operator agent)

---

## 2. Week 5 (2026-05-06 → 2026-05-13, 250h) — 立ち上がり観測 + 緊急調整

Launch day を含む babysit 週。**新機能は凍結**、観測と conversion 修正に全振り。

### 2.1 Operations / monitoring / incident response (~80h, owner: operator agent + Claude 本体)

- [ ] **Sentry triage daily** (8h): 毎朝 09:00 JST、P0 errors trigger hotfix within 2h. 成功基準: D+7 時点で P0 0 件持ち越し
- [ ] **429 / 401 / 5xx rate daily report** (7h): `/v1/admin/metrics` RSS → Slack (自分宛 DM)
- [ ] **Fly.io health + memory watchdog** (8h): `flyctl status` 30 min cron + memory>80% alert
- [ ] **Stripe webhook failure replay** (10h): failed events を `scripts/replay_stripe_events.py` で reconcile、対象 event 5 種 (§LAUNCH_READINESS A1-3)
- [ ] **Incident runbook drill** (6h): `docs/incident_runbook.md` を 1 度は自分で実行して所要時間を計測
- [ ] **Hotfix queue** (35h): HN/Zenn/X から上がる top 10 bugs を 48h 以内 deploy、rolling strategy
- [ ] **Daily retro log** (6h): `research/retro/d+{1..7}.md` — 数字 + 外部反応 + 次日判断

**成功基準**: D+7 までに 2xx 率 ≥ 98%, p95 latency < 400ms, uncaught Sentry errors < 5/day

### 2.2 Customer development (~60h, owner: research agent + user)

- [ ] **30 first-user interviews** (40h): HN comment / Zenn リアクション / X reply / newsletter 返信からリクルート。**対人営業ではなく product feedback** として行う。所要 30min/人、テキスト or 非同期可。`research/interviews/YYYY-MM-DD_{handle}.md`
- [ ] **質問 template 固定** (3h): (1) 今日何を解決しようとしてた? (2) どこで詰まった? (3) 価格は妥当? (4) 誰に紹介する? (5) 次に欲しい機能は? → `research/interview_template.md`
- [ ] **Feedback aggregation** (10h): `research/retro_week5.md` に top 10 pain + top 5 feature ask を抽出
- [ ] **Painkiller vs vitamin 判定** (7h): 各要望に "paid で解決可 / free で十分 / そもそも別" タグ付け。W6 優先度の input

**成功基準**: 30 件 interview 完了 + top 5 feature ask 確定

### 2.3 Quick conversion fixes (~60h, owner: Claude 本体 + content writer)

landing → signup → checkout → first call のファネル drop を 48h サイクルで潰す。

- [ ] **Landing copy A/B** (15h): `site/index.html` hero 3 variant (problem-first / social-proof / code-first), 1,000 visits/variant で stat test. UTM + Plausible goals. `site/_experiments/hero_variant_b.html` lane 分離
- [ ] **Pricing page 明細化** (10h): `site/pricing.html` に "Free で何ができる / Paid でいくら使うと何円になる" を 1-line × 10 で並置。競合 (エネがえる ¥300k/mo, Stayway contact-only) との対比表追加
- [ ] **Onboarding friction 測定 + 修正** (15h): signup→API key→first call の median time 計測 (`docs/api-reference.md` の `curl` 例を 3-click copy 対応)、5min→2min 目標
- [ ] **Checkout abandon rescue** (10h): Stripe `checkout.session.expired` webhook で 24h 後に 1 回だけ reminder email (非 dark-pattern: 「料金に変更ありません」文言のみ、セール/煽り禁止)
- [ ] **Docs quickstart 再確認** (10h): `docs/getting-started.md` を自分で 0→first-call で実行して段差潰し

**成功基準**: D+7 時点で signup→first-call 転換 ≥ 40%、landing→signup ≥ 5%

### 2.4 Content flywheel start (~50h, owner: content writer agent × 2)

- [ ] **長文 × 5** (30h): `research/content_calendar.md` の W1-W2 予定 (P1-P3 各 1 + P4 × 2) を入稿。cross-post (Zenn + /blog/ + canonical URL)
  - Build an Agri-Subsidy Agent in 50 Lines (EN, Dev.to)
  - 6,658 件全部マップ化した話 (JP, Zenn)
  - Claude Desktop × jpintel 5分セットアップ (JP, Zenn)
  - 奈良・滋賀・石川が 9 件しかない理由 (JP, /blog/)
  - 5 MCP Servers for Public Data (EN, Dev.to)
- [ ] **都道府県 × 業種 deep-dive × 3** (20h): `/blog/prefecture/{nara,shiga,ishikawa}.md` 雛形で 47 中 3 県版を先行公開、残り 44 は W7 以降自動生成 (薄 SEO 回避のため実データ駆動)

**成功基準**: 8 記事公開、被リンク 5+ (集計は W8 末)

---

## 3. Week 6 (2026-05-13 → 2026-05-20, 250h) — 汎用化深化 (agri → 全分野)

W5 で集めた feedback を元に、agri に依存しない価値提案を積む週。

### 3.1 Non-agri exclusion W3 schema extension / condition-state tags (~80h, owner: data ingest agent × 2)

現状 35 rules (22 agri + 13 non-agri) は program-to-program mutex のみ。W6 で **条件状態 tags** を拡張: 解雇禁止・みなし大企業・売上減要件 etc.

- [ ] **Schema v3 設計** (10h): `src/jpintel_mcp/models.py` に `ConditionTag` テーブル追加 (tag_code, severity, description, source_url). `docs/exclusions.md` 改訂
- [ ] **Non-agri 50 件拡張** (40h): IT導入・持続化・ものづくり・事業再構築・成長加速化・中小M&A 等を対象、各 8-10 件。`data/non_agri/condition_rules_v3.json`
- [ ] **Migration + tests** (15h): `alembic` (or 手書き migration), 25 tests 追加
- [ ] **`/v1/exclusions/check` v2 response** (15h): backward-compat で `conditions: [...]` フィールド追加. API changelog `docs/changelog/2026-05-20.md`

**成功基準**: 全 exclusion rules 85+ 件、non-agri 63+ 件、API test 全 pass

### 3.2 gBizINFO 採択事例 138K ingest + `adoption.find_similar` endpoint (~90h, owner: data ingest agent × 2 + Claude 本体)

README Month 2+ の key differentiator。**metadata 30-50% null のため filter 必須** (既知問題).

- [ ] **Ingest pipeline** (30h): `src/jpintel_mcp/ingest/gbizinfo_adoption.py` — DuckDB に parquet 落とし、SQLite にはサマリーのみ, lineage (`source_url`, `fetched_at`, `checksum`) 全件付与
- [ ] **Quality filter** (15h): `metadata_completeness >= 0.5` で絞って 40-50K 件を default 公開、全量は opt-in フラグ
- [ ] **FAISS / sqlite-vec 類似検索 index** (20h): 事業概要 + keywords を embed (multilingual-e5-base, local), index サイズ ~500MB, Fly volume に乗せる
- [ ] **`GET /v1/adoption/find_similar`** (15h): input=`program_id` or `free_text`, top-k=20, filter=`prefecture/year/amount`. レスポンス内に `evidence_url` 必須 (社名 mask)
- [ ] **MCP tool `find_similar_adoption` 追加** (5h): `src/jpintel_mcp/mcp/server.py`
- [ ] **docs + blog** (5h): `docs/api-reference.md#adoption-find-similar` + "採択事例 40K 件を MCP で引く" 記事 1 本

**成功基準**: 50K 件以上 ingest、p95 検索 < 500ms、test 15 件、MCP tool から引ける

### 3.3 Tier B enrichment 昇格 (584 → 2,000 quality≥0.6) (~60h, owner: data ingest agent)

- [ ] **Enrichment walker 並列化** (15h): `scripts/enrich_tier_b.py` で 10 並列、rate-limit 遵守 (各 source 1 req/sec)
- [ ] **Quality scoring** (10h): `quality_score` = 項目充足率 (0-1)、0.6 閾値で Tier S/A にリラベル
- [ ] **Canonical source walk** (30h): `reference_canonical_enrichment.md` の 7-rung walk を自動化、失敗時は null で done (§enrichment done 基準)
- [ ] **Daily delta cron** (5h): `.github/workflows/daily-enrich.yml` で 500 件/日 処理

**成功基準**: 5/20 時点で quality≥0.6 の件数 1,500+、Tier S/A 合算 1,000+

### 3.4 Legal / accounting / calendar endpoint 配線 (~20h, owner: Claude 本体)

README で約束した 188 法令 / 116 勘定 / 122 calendar を read-only で公開。**個別アドバイス禁止、一般情報のみ** (§7).

- [ ] `GET /v1/legal/items` (6h): 188 項目 read-only list + filter (category=税務/労務/...)
- [ ] `GET /v1/accounting/chart` (6h): 116 科目 + tax_division 返す
- [ ] `GET /v1/calendar/events` (5h): 122 イベント、date-range filter
- [ ] MCP 3 tool 追加 (3h)

**成功基準**: 3 endpoint + 3 MCP tool 稼働、各 5 tests

---

## 4. Week 7 (2026-05-20 → 2026-05-27, 250h) — 流入 + retention

"access → buy" から "buy → retain" に重点シフト。MAU 伸ばし + 離脱防止。

### 4.1 MCP registry 再 submit + tracking (~30h, owner: operator agent)

- [ ] **8 registry 週次 metrics** (10h): 公式 / Glama / mcpt / Awesome MCP / MCP Hunt / MCP Market / PulseMCP / MCP Server Finder、各登録 ID + view count を `research/registry_metrics.csv` で週次追跡
- [ ] **掲載品質向上** (10h): README 更新後の reflect, cover image 更新, rating 依頼 (dark pattern でない自然な "もし良ければ" CTA)
- [ ] **未掲載分の submit** (5h): W3 で 5 済。残り 3 箇所を submit
- [ ] **PulseMCP auto-ingest 対応** (5h): RSS or webhook 対応で自動反映

**成功基準**: 8/8 掲載、週次 view 合計 1,000+

### 4.2 SDK v1.0 stable + 3 demo apps (~80h, owner: SDK/demo builder agent × 2)

- [ ] **`@jpintel/sdk` (npm, TS) v1.0** (25h): 型生成 openapi2ts, 6 REST + 5 MCP カバー、retry + rate-limit aware. `packages/sdk-ts/`
- [ ] **`jpintel` (PyPI) v1.0** (20h): pydantic model, async/sync 両対応. `packages/sdk-py/`
- [ ] **Demo app 1: Next.js 補助金検索 UI** (15h): `examples/nextjs-search/`, Vercel deploy, SSR + server component で SDK 使用
- [ ] **Demo app 2: Claude Desktop × agri agent** (10h): `examples/claude-agent/`, MCP config + system prompt 同梱
- [ ] **Demo app 3: Slack bot (採択事例 daily digest)** (10h): `examples/slack-digest/`, Bolt + cron

**成功基準**: 両 SDK npm/PyPI publish、demo 3 本 GitHub star 30+ 合計

### 4.3 Retention email digest "weekly 制度 matches" (~40h, owner: Claude 本体 + operator)

**Opt-in only / unsubscribe 1-click / 法的助言なし** の制約で週次 digest を配信。

- [ ] **Subscriber schema** (5h): `email_digest_subscribers` table, 条件 JSON (prefecture, target_type, funding_purpose)
- [ ] **Digest generator** (15h): `scripts/weekly_digest.py` — 購読者毎に新規マッチ制度 top 10 + 今週の changelog + 新 blog 1 件
- [ ] **SendGrid / Resend 連携** (10h): transactional only, bounce handling, APPI compliant
- [ ] **Unsubscribe UX** (5h): 1-click footer link, confirmation なし即停止
- [ ] **Plausible goal tracking** (5h): open / click / return-visit 計測

**成功基準**: 100+ 購読、open rate 30%+、return-visit 15%+

### 4.4 長文記事 × 15 (~60h, owner: content writer agent × 2)

`research/content_calendar.md` W3-W7 予定 + 追加 5 本。P4 (業種別 long-form) 中心。**programmatic 薄ページ禁止** (Google Helpful Content penalty 回避).

- 農業法人 × 認定新規就農者 / 中小製造業 × IT 導入 / 観光 × 地方創生 / スタートアップ税制 / M&A 等
- 各 3,000-5,000 字、実データ (制度 ID + amount + source_url) 引用必須

**成功基準**: 15 本公開、累計 PV 10K+、被リンク 20+ 累計

### 4.5 Growth experiments A/B (free-tier limits, conversion UX) (~40h, owner: Claude 本体)

- [ ] **Free tier limit 実測** (10h): 現 100 calls/day → 50 / 100 / 200 の 3 pool 分割、14 日で Paid 転換率比較
- [ ] **Paid unit price 感度** (15h): ¥0.3/req vs ¥0.5/req vs ¥0.8/req の 3 landing variant (Stripe Price の `lookup_key` 切替)。**既存契約者は影響なし** (grandfathered, 旧 Price は active subscription 維持)
- [ ] **Onboarding credit A/B** (10h): signup 時 ¥0 vs ¥500 (1,000 req 分) の無料 credit 付与で 30 日転換率比較
- [ ] **結果 decision** (5h): `research/growth_experiments/w7_summary.md` に stat sig + 採用変更

**成功基準**: 少なくとも 1 個の実験で p<0.1 の有意差、採用判断済

---

## 5. Week 8 (2026-05-27 → 2026-06-03, 250h) — 顧客 pipeline / 汎用 API 熟成

売上立ち上げと次四半期の仕込み。

### 5.1 Pure metered billing 運用成熟 (~60h, owner: Claude 本体)

- [ ] **Usage reporting 堅牢化** (20h): `stripe_usage.py` の retry backoff, Stripe API 5xx リトライキュー, dead-letter 検知 alert
- [ ] **Invoice reconciliation** (15h): 日次 cron で `usage_events` (自社 DB) と Stripe `invoice.lines.data[].quantity` を突き合わせ、drift 検知
- [ ] **Billing 透明性 dashboard** (10h): 顧客が今月の usage + 予測請求額を `/v1/me/usage` で JSON 取得、dashboard UI 表示
- [ ] **Dunning + failed-payment 自動通知** (5h): `invoice.payment_failed` → Postmark で D+0 / D+3 / D+7 リマインド (既存 onboarding_emails の仕組み転用)
- [ ] **Refund runbook** (10h): incident 起因で使用量超過が発生した場合の credit 発行手順、Stripe Customer Portal 誘導 template

**成功基準**: Paid 継続 MRR ≥ ¥50,000 (monthly recurring usage、100,000 req/月 相当)、dunning 完遂率 ≥ 95%

### 5.2 JSON-LD publish (schema.org, AI training crawler bait) (~20h, owner: Claude 本体)

- [ ] **Schema 設計** (5h): 制度 = `schema.org/GovernmentService` + custom `jpintel:ProgramTier` extension
- [ ] **全 6,658 件 JSON-LD 生成** (5h): `scripts/generate_jsonld.py` → `site/data/programs/{unified_id}.jsonld`
- [ ] **Sitemap + robots.txt** (5h): AI crawler (GPTBot, ClaudeBot, Google-Extended) allowlist
- [ ] **GitHub public mirror** (5h): `jpintel/jsonld-mirror` repo、自動 sync

**成功基準**: 6,658 件 lintable JSON-LD 公開、crawler 初回取得 evidence (server log)

### 5.3 English i18n for landing + docs (~80h, owner: content writer agent × 2 + Claude 本体)

- [ ] **Landing EN** (15h): `site/en/index.html` + hero / pricing / feature の翻訳. 機械翻訳 + 人校閲
- [ ] **Docs EN** (50h): `docs/en/` 以下に 8 本核心 docs の翻訳 (getting-started, api-reference, mcp-tools, pricing, sla, faq, exclusions, incident_runbook は除外=ops 用)
- [ ] **Header 言語切替** (5h): `/ja/` `/en/` prefix, hreflang 設定
- [ ] **English HN + PH 再告知** (10h): W8 末 (6/03 頃) に "we now have English docs" re-launch

**成功基準**: 8 docs EN 公開、hreflang valid、GSC 登録

### 5.4 Programmatic PR / backlink (公的機関 etc.) (~40h, owner: research agent + Claude 本体)

- [ ] **Target リスト** (5h): Digital 庁 dev community / 経産省 open data catalog / e-Stat / JFC open API / 中企庁 mirasapo — 15 候補
- [ ] **Submission copy 作成** (15h): 各機関 fit する one-pager (技術価値 / 出典明記 / 遵守事項). 機関毎 customize
- [ ] **送付 + 追跡** (20h): 自動営業ではなく、dev community への純粋な情報共有 (対人営業禁止 §7). 返信は user 判断で対応

**成功基準**: 3 機関から dev community 掲載 or 言及 (メルマガ / blog / registry)

### 5.5 Week 9+ 計画 / 次の 1000h 更新 (~50h, owner: Claude 本体)

- [ ] **W5-W8 実測 vs 目標 diff** (10h): `research/retro_week5_8.md` で全 metric 比較
- [ ] **Fork A / Fork B signal 評価** (10h): §10 の trigger 条件に照らして次方針を決定
- [ ] **W9-W12 計画 draft** (20h): `docs/NEXT_QUARTER_PLAN.md` に 3 月計画。user review → 4/22 と同じ reiteration process
- [ ] **Constitution audit** (5h): CONSTITUTION 13.2 の 5 禁止事項を今期実装で踏んでないか目視点検
- [ ] **Memory 更新** (5h): `~/.claude/projects/-Users-shigetoumeda/memory/project_jpintel_1000h_plan.md` を W5-W8 版に書き換え + 新 fork を記録

**成功基準**: W9 計画 draft 完、user 承認

---

## 6. Conversion funnel instrumentation (~40h, owner: Claude 本体)

**landing visit → signup CTA click → Stripe Checkout → successful payment → API key fetch → first call → D+7 retention**

| Step | 計測 | Tool | W5 baseline 仮説 | 目標 (D+28) |
|---|---|---|---|---|
| Landing visit | Plausible pageview | Plausible | 100% | — |
| Signup CTA click | Plausible goal `signup_click` | Plausible | 30% | 50% |
| Stripe Checkout start | Stripe `checkout.session.created` | Stripe | 5% | 8% |
| Successful payment | Stripe `invoice.paid` | Stripe | 3% | 6% |
| API key fetch | `api_keys.created_at` | SQLite | 90% of paid | 95% |
| First call | `usage_log` first row / key | SQLite | 70% | 85% |
| D+7 retention | `usage_log` has row in [d+1, d+7] | SQLite | — | 40% |

### 6.1 Dropoff-specific fix 手段

- **Visit → CTA 低**: hero A/B (§2.3), problem-first copy
- **CTA → Checkout 低**: pricing 明細 (§2.3), free tier 先訴求
- **Checkout → paid 低**: JCT compliant footer (既存), T-号 表示, card-only friction 削減
- **Paid → API key 低**: Checkout 成功画面で即 API key 表示 (現状 Portal 経由なら 1-step 化)
- **API key → first call 低**: `docs/getting-started.md` の curl 3-click copy 強化、staging playground 追加
- **first call → D+7 retention 低**: email digest (§4.3), changelog 通知

### 6.2 Attribution

- [ ] **UTM on all external links** (5h): HN / Zenn / X / PH / registry 全 outbound に `utm_source/utm_medium/utm_campaign` 付与
- [ ] **Referer parsing** (5h): `/v1/subscribers` 登録時に document.referrer を格納
- [ ] **`/v1/admin/metrics` dashboard** (25h, W6 配線): `src/jpintel_mcp/api/admin.py` に 管理者 only endpoint, 日次 funnel + attribution table 返却. HTML view `site/admin.html` (basic auth)
- [ ] **Daily Slack summary** (5h): 前日の funnel 各 step の数を自分宛 DM

**成功基準**: 毎日 funnel 6 step + attribution 上位 5 source が可視、drop 最大 step を特定済

---

## 7. Guard rails (禁止事項)

**絶対に実装しない / ドリフトしない**:

- **対人営業禁止**: cold email / pilot 提案 / 電話 / 説明会、やらない (§PR は dev community への情報共有に限る)
- **書類生成 / 個別法的助言 禁止**: 行政書士法 / 税理士法 / 弁護士法 / 金商法 抵触リスクを構造的に排除. API response は一般情報のみ
- **Dark pattern / false advertising 禁止**:
  - FOMO 煽り ("残り X 枠", fake scarcity) 禁止
  - 申告 / 成功報酬 claim 禁止 ("X 万円もらえる" 表現禁止)
  - 社名 / 採択事例の mask 必須 (個情法)
  - Checkout の opt-out チェックボックス trap 禁止
  - Dark-pattern unsub (unsubscribe 3-step 以上) 禁止
- **「買わせ策」でなく「買う価値を生む」方向のみ**: 機能 / データ / docs / SLA で説得、心理操作禁止
- **CONSTITUTION 13.2 遵守**:
  - η (情報理論的確信度) をユーザー露出しない
  - 階層検証を実装しない
  - Bayesian 段階開示を実装しない
  - AI で AI を検証しない
  - 独自 wire format を作らない
- **特許 A/B/C/D/E の中身実装しない** (2026-04-13 決定, 撤退済)

**違反チェック**: W8 末 constitution audit (§5.5) で全コード / 全 copy を目視点検

---

## 8. 並列 sub-agent 運用

**毎日 6-12 並列を想定**。lanes 分離で conflict を事前回避.

### 8.1 固定 role (同時に書く file は lane 分離)

| Role | 並列数 | 主 lane (file/dir) | 主 task |
|---|---|---|---|
| (1) operator / monitoring | 1 | `research/retro/`, `research/metrics/`, Slack DM | Sentry triage, metrics daily, hotfix queue |
| (2) content writer × 2 | 2 | `research/blog_drafts/`, `site/_drafts/`, `/blog/{slug}.md` | 長文 × 週 5-10, cross-post |
| (3) data ingest × 2 | 2 | `src/jpintel_mcp/ingest/`, `data/`, SQLite WAL | exclusion v3 / gBizINFO / enrichment |
| (4) SDK / demo builder × 2 | 2 | `packages/sdk-{ts,py}/`, `examples/` | SDK v1.0, demo × 3 |
| (5) customer research | 1 | `research/interviews/`, `research/retro_week*.md` | 30 interviews, feedback agg |
| (6) Claude 本体 | 1 (指揮) | 全 lane 跨ぎ review | 指揮 + 実装 + 最終レビュー |

### 8.2 Conflict 回避 rule

- **DB migration は Claude 本体のみ**: sub-agent は schema に触らない
- **`site/index.html` は 1 時に 1 agent のみ**: lane token = `site/_locks/index.html.lock`
- **docs 核心 ( `docs/getting-started.md` 他 8 本)** は Claude 本体 review 必須
- **並列 agent の severity ラベル盲信禁止** (memory: feedback_agent_severity_labels): P0 / critical を rollup せず自分で verify + re-label
- **完了条件は最低 blocker のみ** (memory: feedback_completion_gate_minimal): 40+ 項目全 green を次週 gate にしない、最小 5-8 本で判断

### 8.3 日次 orchestration

- 09:00 — operator が夜間 metrics report
- 09:30 — Claude 本体が day-plan (6-12 agent への task 配分)
- 10:00-18:00 — 並列実行、hourly checkpoint
- 18:00 — Claude 本体 merge + test + deploy review
- 19:00 — retro 記録 (`research/retro/d+N.md`)

---

## 9. Kill switches / 撤退条件

以下の境界で **自動で撤退判断を迫る**。user への escalation = 即時.

- **D+14 で paid=0**: positioning pivot 検討 (copy / 価格 / target tier 再設計). 実行: `research/pivot_options_2026_05_20.md` を起草
- **D+28 で MAU < 100**: PMF 仮説見直し (agri vs 汎用, niche 深化 or 完全 pivot). 実行: Fork B 強制トリガー (§10)
- **月額 Fly + Stripe + Sentry > ¥50,000 かつ MRR < ¥30,000**: 縮退 (Fly machine 1 台化, SendGrid 停止, 有料 tool 凍結). 実行: `scripts/scale_down.sh`
- **Sentry P0 が 1 週連続で 10+/day**: 新機能凍結、stabilization sprint 発動
- **商標 Intel 衝突再発火** (弁理士連絡 or 法務 letter): 24h 以内 rebrand 発動、全 registry / domain / github / npm / pypi 切替 (memory: project_jpintel_trademark_intel_risk)

各 kill switch は **数字 + 日付で自動判定**、情緒判断禁止.

---

## 10. 次の 2 つの fork (month 3 以降)

W8 末 (6/03) に以下のどちらかに分岐する。**signal-driven**:

### Fork A: 汎用深化 (全制度 API、横展開)

- **Trigger**: D+28 paid ≥ 30 かつ paid 顧客の業種分布が agri < 40% (汎用需要の signal)
- **Focus**: 全 6,658 件 quality 0.8+ 昇格 / 採択事例 138K 完全 ingest / 英語版深化 / 海外 B2D (dev.to / product hunt 国際) 拡大
- **Measurable 6-month goal**: ARR ¥3,000 万 (500 顧客 × 平均 10,000 req/月 × ¥0.5 = ¥250 万/月、tax 別)
- **Risk**: 汎用は Jグランツ 公式 bulk CSV 発表で commoditize するリスク (差別化 = exclusion + tier + lineage + MCP)

### Fork B: Vertical deepening (agri subset を本命化 / 工務店 / 補助金 consultant 向け SaaS)

- **Trigger**: D+28 paid < 15 or agri 顧客比率 > 60% (niche 深化 signal)
- **Focus**: agri MAFF 943MB OCR / 畜産・米・畑作 タテ特化 / 工務店向け `/v1/programs/search?target_type=koumuten` 特化 endpoint / consulting firm 向け partnership API (OEM でなく API 提供)
- **Measurable 6-month goal**: ARR ¥2,000 万 (200 niche 顧客 × 平均 20,000 req/月 × ¥0.5 = ¥200 万/月、tax 別)
- **Risk**: niche で上限が低い / 営業チャネル不在の中で churn

### 分岐判定 (6/03 末)

```
if paid >= 30 and agri_ratio < 0.4:
    fork = "A"
elif paid < 15 or agri_ratio > 0.6:
    fork = "B"
else:  # 曖昧ゾーン
    fork = "A+B" (8 週追加観測、W9-W12 は両軸)
```

`scripts/fork_decision.py` で自動算出 → `research/fork_decision_2026_06_03.md` に記録.

---

## 11. 既存計画との接続 (continuity)

- **W1-W4 計画** (`~/.claude/projects/-Users-shigetoumeda/memory/project_jpintel_1000h_plan.md`) の exit 条件: Tier A+ 2,000 件, MAU 500+, paid 5-10 → W5 D+7 target (MAU 300, paid 5) と整合
- **README 3 ヶ月 roadmap** の Month 2 項目 (SDK / registry / 長文 10 / demo 3 / retention email / adoption + legal + accounting + calendar endpoints) は W6-W7 に完全実装
- **LAUNCH_GAPS_AUDIT** の post-launch 残項目 (rate-limit shared store, backup offsite, SLA page, press kit, DSAR playbook) は W5-W6 の hotfix queue で吸収
- **next iteration**: 6/03 で `~/.claude/projects/-Users-shigetoumeda/memory/project_jpintel_1000h_plan.md` を W5-W8 版に更新 + fork 記録

---

## 12. 受け入れ条件 (W8 end, 2026-06-03)

全部 true で 1,000h 投下を成功と判定:

- [ ] MAU ≥ 1,500 (目標 1,800 の 80%)
- [ ] paid ≥ 28 (目標 45 の 60%)
- [ ] search req/day 90d avg ≥ 10,000
- [ ] SDK v1.0 (TS + Py) publish 済
- [ ] demo app ≥ 3 本
- [ ] 長文記事累計 ≥ 20 本
- [ ] exclusion rules ≥ 85 件
- [ ] adoption endpoint 稼働 + 50K+ 件 ingest
- [ ] English docs 8 本公開
- [ ] fork A/B 判定ドキュメント commit 済
- [ ] constitution 13.2 違反 0
- [ ] p95 latency < 500ms / 2xx ≥ 98% / Sentry P0 0 持ち越し

---

最終更新: 2026-04-23
次回更新予定: 2026-06-03 (W8 exit retro 時)
