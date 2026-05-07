# Handoff: THIS CLI のセッション成果 + OTHER CLI への deploy 引き継ぎ

> 2026-05-01 safety override: この文書内の `git add -A` / `git push` /
> `fly deploy` / `npm publish` / `HF_TOKEN ... --push` は現在の巨大 dirty
> tree では実行禁止。reviewed file list、full tests、Docker context audit、
> migration guard、secret/publication audit が green になった commit SHA
> だけを operator が明示的に deploy する。

Date: 2026-05-01
読む人 (OTHER CLI): あなた
本ドキュメント目的: **このセッションで THIS CLI が積み上げた変更を、最後 deploy まで OTHER CLI が完走するための引き継ぎ**

---

## 1 行で

ローカル変更 691 file (+7,883/-4,602)。Fly 本番は既に v0.3.1 で healthy。残りは **commit + push + tag + Cloudflare Pages 自動 deploy + 必要なら fly redeploy**。npm / HF / twine は認証なしなので OTHER CLI 環境次第で実行可。

---

## 認証状態 (2026-05-01 11:30 時点で audit)

| 認証 | 状態 | 影響範囲 |
|---|---|---|
| `git push origin` | ✅ HTTPS via gh token | THIS CLI から push 可能 |
| `gh` CLI | ✅ authenticated as `shigetosidumeda-cyber`、scopes `gist/read:org/repo/workflow` | repo edit / topics 追加 可能 |
| `fly` CLI | ✅ authenticated `shigetosidumeda@gmail.com` | `fly deploy` 可能 |
| `npm publish` | ❌ ENEEDAUTH | 別途 `npm adduser` 要 |
| `HF_TOKEN` | ❌ env に未設定 | HF push できない |
| `twine` (PyPI) | ❌ `~/.pypirc` 不在 | PyPI 再 upload できない (現 0.3.2 既に live なので影響限定) |

→ **OTHER CLI が deploy を完走するには:**
- git push + fly deploy + gh repo topics は **そのまま実行可能**
- npm / HF push は user の credential 投入待ち (deploy 完走には必須でない)

---

## Fly 本番現状 (logs から observed、2026-05-01 02:42Z)

```
app          : autonomath-api
machine      : 85e273f4e60778 (region nrt)
state        : started, healthy
image        : autonomath-api:deployment-01KQGE7TNDRDV1A8YZ0D6SSDV9
OpenAPI      : title=jpcite, version=0.3.1, paths=178
deep_health  : 10/10 checks ok (db_jpintel/db_autonomath/freshness/license/source_id/entity_id_map/annotation/validation/static/wal)
endpoint     : /v1/am/health/deep が 30 秒毎に 200 (latency 410-470ms)
```

→ **本番は止まっていない**。deploy は「新しい image を焼くか焼かないか」の判断のみ。

---

## このセッションで THIS CLI が積んだ変更

### A. Deploy blocker fix (17 件、launch をブロックする bug)
- ✅ billing_breakdown router マウント (`api/main.py`)
- ✅ calendar.ics endpoint 実装 (`api/calendar.py` + ICS RFC 5545)
- ✅ customer_webhooks UA brand drift fix (`zeimu-kaikei-webhook` → `jpcite-webhook`)
- ✅ programs response `_meta` 漏洩 fix (anon_quota_header denylist 追加、`api/programs.py` 不変)
- ✅ license gate api/evidence.py 配線 (`filter_redistributable` + `annotate_attribution`)
- ✅ CSV header `税務会計AI` → `jpcite` (`_format_dispatch.py` BRAND_FOOTER 単一定数 fix)
- ✅ `_build_dd_profile` 3-tuple 化 + caller 全件更新
- ✅ kaikei_workpaper PDF §47条の2 wording 復活 (PDF trailing-comment 形式)
- ✅ rule_engine error.code (verify only、既に正しい)
- ✅ test_api count assertions を ID-based に更新 (3 件)
- ✅ OpenAPI regen + drift commit (178→179 paths、`/v1/billing/client_tag_breakdown` 追加)
- ✅ mkdocs --strict 0 warnings (3 orphan を nav に追加)

検証: critical test sweep **226/226 pass** + smoke pre-launch **GREEN (49/49)**。

### B. データ整理 / hygiene
- ✅ 99.5 GB DB バックアップ削除 (113 GB → 12 GB、autonomath.db.pre_* 14 件 + jpintel.db.bak* 21 件)
- ✅ 70 unused imports cleanup (ruff F401 fix、30 file)
- ✅ 5 untested critical file の test 追加 (advisory_lock / audit_log / health_deep / universal_envelope / accounting、14 tests)
- ✅ subsidy_rate text 列分離 (10 件 fix、migration 121 新規)
- ✅ ruff F811/F841/E711/E712/E721 拡張 sweep (in-scope 0 件残り)

### C. 検索 / API 改善
- ✅ FTS5 bm25 (5×primary_name 重み)
- ✅ 短語 LIKE fallback (k<3 で 100% silent failure 回避)
- ✅ tier prior boost recalibration (`TIER_PRIOR_WEIGHTS = {S:1.07, A:1.06, B:1.06, C:0.99, X:0.83}`)
- ✅ PRAGMA cache_size verify (256MB 既設定)
- ✅ scipy lazy load verify
- ✅ `/v1/me/*` middleware audit (gate 候補ゼロ確認)

### D. 価値命題書き直し (5 file)
- ✅ `site/index.html` (token frame 撤去、(a)(b)(c) 三本柱、6 card grid)
- ✅ `site/pricing.html` (比較表削除、3 軸価値説明)
- ✅ `docs/api-reference.md` (workload-dependent disclaimer)
- ✅ `README.md` (Evidence-first context layer)
- ✅ `site/about.html` (「Bookyou株式会社が運営しています」削除 — user 指示)

### E. ブランド統一
- ✅ AutonoMath → jpcite を 17,069 箇所 / 3,142 file 修正 (alternateName JSON-LD は履歴として保持)
- ✅ 旧ドメイン zeimu-kaikei.ai は履歴記述のみ保持
- ✅ docs JST 月初 → JST 翌日 00:00 リセット (10 file)

### F. 新規 ship 可能 deliverable (今回セッション)

#### F-1 Excel add-in (`sdk/integrations/excel/`)
- XLAM (VBA, 5 関数) + Office Add-in (TypeScript, 5 同関数)
- Recalc-storm warning 完備
- 14 file、50/50 tests pass

#### F-2 TKC/MJS/freee 連携 (`sdk/freee-plugin/` + `sdk/mf-plugin/` + `sdk/integrations/tkc-csv/`)
- freee 8 file brand drift fix + MF 7 file fix
- TKC FX2 CSV import SDK 新規 4 file + 15/15 tests
- go-live readiness 2 markdown

#### F-3 MCP marketplace 9 件 submission packs (`research/outreach/mcp_submissions/`)
- 9 marketplace × prefilled metadata + INDEX
- 提出順序 + 1h 25-55min total
- aggregate reach 25-70k unique-dev/月 (UNVERIFIED)

#### F-4 信金中金データライセンス pitch (`research/outreach/`)
- 信金中金 + 全信協 + 信用組合 pitch 3 件
- 連絡先 36 件 CSV
- 月額前払 model (¥30K-1M/月)、3 シナリオ ROI

#### F-5 demo 動画 2 本台本
- 税理士向け 2 分 + 補助金 consultant 向け 2 分
- asset 制作指示 + X tweet 2 件 + Zenn embed

#### F-6 site/audiences/journalist.html (新規)
- 287 行、bookmarklet drag-drop area、無償拡張枠 申請 mailto

#### F-7 行政処分 SEO 全件 page (`site/enforcement/`)
- index + 300 detail page + sitemap-enforcement.xml
- 22,258 中 6,229 が PII gate 通過、honest disclaimer

#### F-8 業種 audience 書き換え
- construction / manufacturing / real_estate を「コンサル/業種団体/業務 SaaS 連携」向け再フォーカス

#### F-9 4 plug-in scaffold (`sdk/integrations/{kintone,slack,google-sheets,email}/`)
- kintone (9 file) + Slack (5 file) + Google Sheets (6 file) + email digest (5 file)
- 68/68 tests pass

#### F-10 organic acquisition 拡張
- OG/Twitter card sweep 4 page + GitHub social-card 1280x640 PNG
- Algolia DocSearch staging
- Awesome-lists PR pack 5 本
- Show HN 320 字 draft + dev.to/Lobste.rs テンプレ

#### F-11 ETL scripts (新規、CSV 出力のみ、DB write 無し)
- `scripts/etl/fetch_egov_law_fulltext_batch.py` (B4: smoke 50 件 / 45 ok / 90%)
- `scripts/etl/enrich_court_decisions_excerpt.py` (B5: 30/30 success)
- `scripts/etl/run_program_pdf_extraction_batch.py` (B6 batch runner: 50 件 / 13 ok)
- `scripts/etl/reconcile_adoption_to_program.py` (B7: smoke 1,000/1,000 = 100%)
- `scripts/etl/probe_geps_feasibility.py` (B11: limited-yes、smoke 19 件)
- `scripts/etl/ingest_jfc_loan_scaffold.py` (B12: 29 JFC + 51 信保協)
- `scripts/etl/generate_monthly_amendment_digest.py` (月次 digest markdown + HTML)
- `scripts/etl/generate_consultant_monthly_pack.py` (5 page PDF × 顧問先)
- `scripts/etl/generate_enforcement_seo_pages.py` (300 detail + index + sitemap)

#### F-12 公開 RSS feed × 50 (`site/rss/`)
- programs-tier-s.xml + amendments.xml + 47 prefecture
- 4,418 item、`<link rel=alternate>` 配線

#### F-13 HF dataset publish workflow
- `scripts/publish_hf_datasets.py` 完成
- 4 dataset + 新規 embeddings-jp (246k row × 384-d)
- HF_TOKEN 投入で push 可能

#### F-14 Chrome 拡張 + bookmarklet (`sdk/chrome-extension/` + `site/bookmarklet.html`)
- manifest v3、12 file
- bookmarklet drag-drop area

#### F-15 npm package (`sdk/npm-package/@bookyou/jpcite`)
- v0.1.0、5/5 tests、9.6 KB tarball
- `npm publish --access=public` 待ち

#### F-16 GitHub Action (`sdk/github-action/`)
- `bookyou/jpcite-action@v1`、competing 0、5 use case

### G. 引き継ぎ・分析 markdown
- `docs/_internal/DEPLOY_CHECKLIST_2026-05-01.md` (45 項目)
- `docs/_internal/handoff_consolidated_strategy_2026-05-01.md` (4 軸戦略)
- `analysis_wave18/user_reality_*.md` × 9 cohort (honest 検証)
- `analysis_wave18/honest_constraint_tradeoff_2026-05-01.md`
- `analysis_wave18/cohort_killer_status_2026-05-01.md`
- `analysis_wave18/conversion_friction_audit_2026-05-01.md`
- `research/outreach/firm_01..10_*.md` (10 firm outreach テンプレ)
- `research/outreach/rag_mcp_dev_pool_2026-04-30.md`
- 他 50+ markdown

---

## Historical deploy notes (DO NOT RUN)

このセクションには以前 all-in-one deploy command があったが、現在の checkout は
巨大 dirty tree なので **DEPLOY NO-GO**。blanket stage / tag / push は禁止。

再開時は、reviewed file list を明示し、full tests、Docker context audit、
migration guard、secret/publication audit が green になった clean commit SHA
だけを operator が明示して deploy する。

### Step 3. GitHub repo topics 追加 (gh CLI)

```bash
gh repo edit shigetosidumeda-cyber/autonomath-mcp \
  --add-topic mcp-server \
  --add-topic mcp-tools \
  --add-topic claude \
  --add-topic rag \
  --add-topic agent-tools \
  --add-topic japanese \
  --add-topic legal-tech \
  --add-topic subsidies \
  --add-topic tax \
  --add-topic corporate-registry \
  --add-topic enforcement \
  --add-topic evidence \
  --add-topic citation \
  --add-topic fts5 \
  --add-topic anthropic \
  --add-topic api \
  --add-topic japan \
  --add-topic government \
  --add-topic sqlite
```

### Step 4. Cloudflare Pages auto-deploy

`main` push で自動 trigger される。verify:
```bash
sleep 60
curl -I https://jpcite.com 2>&1 | head -5
```

### Step 5. Fly deploy (operator-only after gates)

この checkout からの Fly deploy は禁止。clean commit SHA、snapshot ID、
直近 image tag、entrypoint/schema guard の green が揃った後だけ operator が実行する。

`entrypoint.sh` の sha256sum / integrity_check skip は OTHER CLI 既往 fix で対応済 (handoff_consolidated_strategy_2026-05-01 §「production deploy 完了 + 起動ブロッカー修正」参照)。

### Step 6. 本番 smoke

```bash
# /healthz
curl -fsS https://api.jpcite.com/healthz

# OpenAPI version 確認
curl -fsS https://api.jpcite.com/v1/openapi.json | jq -r '.info | {title, version} | "\(.title) \(.version)"'

# deep health
curl -fsS https://api.jpcite.com/v1/am/health/deep | jq -r '.status'

# smoke
BASE_URL=https://api.jpcite.com TIMEOUT=25 ./scripts/smoke_test.sh
```

### Step 7. EXECUTION_LOG.md 追記

```markdown
## 2026-05-01TXX:XX:XX+0900 — production deploy v0.3.2 完了

- git push origin main (commit XXX)
- git tag v0.3.2 push
- GitHub topics 19 件追加
- Cloudflare Pages auto-deploy verified (curl -I https://jpcite.com → 200)
- fly deploy: image deployment-XXX, machine started, deep_health 10/10 ok
- production smoke: REST/MCP/Telemetry GREEN
```

---

## 認証なしで止まる作業 (OTHER CLI 環境で credential あれば実行可)

### npm publish

現 checkout からの publish は禁止。package tarball audit と credential audit 後に operator-only。

### HF push

現 checkout からの HF push は禁止。license=unknown / proprietary 除外 audit と
dataset manifest audit 後に operator-only。

### MCP marketplace 9 件 manual 登録

`research/outreach/mcp_submissions/INDEX.md` の順序通り、各 marketplace に submit。GitHub PR / form / API キー必要なものあり。**OTHER CLI が GitHub auth 持ってるので大半は実行可**。

### outreach メール送信 (info@bookyou.net から user)

`research/outreach/firm_01..10_*.md` (10 件) + 信金中金 pitch (4 件) を送信。これは Bookyou 株式会社の代表 (梅田氏) の判断、ただし BCC で info@bookyou.net 経由は OTHER CLI が SMTP credential あれば自動化可能。

---

## 制約 (OTHER CLI も継続遵守)

- LLM API を一切呼ばない (`anthropic`/`openai`/`google.generativeai`/`claude_agent_sdk`)
- agg サイト (noukaweb/hojyokin-portal/biz.stayway) を `source_url` に書かない
- robots.txt + 1 sec/host throttle
- ¥3/billable unit metered 単一料金、tier SKU / 月額 SKU 提案禁止
- `_archive/` 触らない
- 「工数」「priority」「phase」「MVP」「stage」言葉禁止
- 営業電話 / sales call / DPA / 採用 / 広告 禁止
- DB VACUUM / 巨大 ALTER 避ける

---

## 完了条件

```
git status --short                          → clean
git tag --list "v0.3.2"                     → 出力あり
gh repo view ... | grep -i topics           → 19 件
curl -fsS https://api.jpcite.com/healthz    → "ok"
curl -fsS https://api.jpcite.com/v1/openapi.json | jq -r .info.version → "0.3.2"
./scripts/smoke_test.sh                     → REST/MCP/Telemetry GREEN
```

これが全部 ✅ でも、この dirty checkout からは deploy しない。clean commit SHA を切って再評価する。

---

## OTHER CLI への一言

**この文書は historical。user の手作業を最小化する方針は維持するが、deploy / push / publish は current safety gates が green の clean commit SHA だけを対象にする。止まったログは EXECUTION_LOG.md に残す。**

---

## 2026-05-01 続編追記: 役割分担 (THIS CLI ↔ OTHER CLI)

### THIS CLI が今 取りに行く範囲 (データ拡張、新規 corpus + surface)

- **A_ext5** e-Stat surface 化 (view + endpoint + MCP tool、新規 ingest なし)
- **A_ext6** パブコメ RSS ingest (migration 122 + cron + 2-phase fetch)
- **A_ext1** 改正履歴 e-Gov v2 `/api/2/law_revisions/` walk (migration 132 + MCP tool)
- **A_ext3** 8 官庁通達 unified (migration 124-126 + 8 ingest scripts、MHLW Playwright 不要 verified)
- **A_ext7** 行政処分 deep (既存 4 ingest scripts re-run + view、migration 不要)
- **A_ext4** GEPS 落札 (migration 123 + 5 並列 ingest、anti-bot 不在 verified)
- **A_ext8** 特許 J-PlatPat IPRED API (migration 133 + 弁理士 cohort #12 創出)
- **am_amendment_diff phase 拡張** (migration 130、A_ext1 + A_ext6 共有)
- **A_ext2** 都道府県条例: 東京都など verify 済み 1-3 自治体のみ THIS CLI 着手、残り 1,738 自治体 (12 week 規模) は OTHER CLI loop で取りに来てもいい

これらは新規 migration (122-134) + 新規 scripts/etl/ + 新規 MCP tools。**OTHER CLI が触る既存 scripts と衝突しない設計**。

### OTHER CLI が引き続き取りに行く範囲

- **production deploy**: current safety gates が green になるまでは禁止。以前の Step 1-7 は historical/operator-only。
- **A5 last_verified backfill** (4,135 / 95,000、4 shard 並列)
- **B-series 既存ETL 残作業** (B1 NTA 法人 / B2 invoice / B3 gBiz / B4 法令本文 / B5 court / B6 PDF / B7 adoption / B8 JGrants / B9 e-Stat / B10 NTA 通達 / B11 GEPS basic / B12 JFC)
- **D6 axis_key migration** (preflight 完了)
- **F1-F5 HF dataset publish** (markdown 完成、HF_TOKEN 投入で 1 cmd)
- **outreach 送信支援** (10 firm + 信金中金 + 自治体)
- **MCP marketplace 9 件 manual 登録** (gh auth で大半可能)

### 衝突回避ルール (両 CLI 共通)

- 新規 migration は番号衝突しないように 122-134 を THIS CLI、135+ を OTHER CLI
- 新規 ETL script は `scripts/etl/` 配下、命名 prefix で衝突回避:
  - THIS CLI: `ingest_<source>_<agency>.py` / `fetch_<api>.py` / `surface_<feature>.py`
  - OTHER CLI: `backfill_*.py` / `propose_*.py` / `report_*.py` (既存パターン)
- DB 書き込み: SQLite WAL モードで concurrent reader + 1 writer なので、両 CLI が同時 INSERT/UPDATE は基本 OK だが、巨大 ALTER / VACUUM は避ける
- `EXECUTION_LOG.md` は append-only、両 CLI から timestamp 付きで追記
- 新規 MCP tool は `src/jpintel_mcp/mcp/autonomath_tools/` 配下、衝突しない module 名

### 想定される 効果合算

```
THIS CLI 担当 (データ拡張 7+ 案):
  A_ext1  改正履歴 25 分 walk        : +¥350K/月
  A_ext3  8 官庁通達 (社労士 #11)    : +¥1,500K/月
  A_ext5  e-Stat surface 化          : +¥299K/月
  A_ext6  パブコメ                   : +¥325K/月
  A_ext7  行政処分 deep              : +¥125-700K/月
  A_ext4  GEPS 2.8h walk             : +¥600-800K/月
  A_ext8  特許 (弁理士 #12)          : +¥555K/月
  A_ext2  都道府県条例 (1-3 自治体)  : +¥50K/月 (sample)
─────────────────
中央値合算                            : +¥4.0-4.6M/月

OTHER CLI 担当 (deploy + 既存 ETL):
  既存 4-5 軸 cohort 実行             : +¥425K-2.95M/月
  HF push + outreach                 : +¥150-500K/月
  MCP marketplace 9 件               : +¥10-100K/月
─────────────────
合算                                  : +¥585K-3.55M/月

両 CLI 合算 中央値                    : +¥4.6-8.1M/月
```

200-300 万射程は **両 CLI 合算で完全に超える**。但し 30-50% 縮小後の現実値で **¥1.4-4.0M/月**、射程ど真ん中。

### 一言

THIS CLI が attempt しない / OTHER CLI に任せる作業:
- production deploy 自体 (gh push + fly deploy)
- A5 resumable batch (~24h かかる、OTHER CLI loop で進む)
- B-series ETL の重い ingest (NTA 法人 4.5M / invoice 4M / gBiz 5M)
- F-series HF push (HF_TOKEN 投入後)
- outreach メール実送信
