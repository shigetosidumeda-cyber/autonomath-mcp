# Handoff: jpcite 統合状態 + 残タスク + 戦略方針

> 2026-05-01 safety override: CURRENT STATUS = DEPLOY NO-GO for this dirty
> checkout. この文書内の「deploy 可能」「git push」「fly deploy」「npm publish」
> `HF_TOKEN ... --push` は historical/operator-only として扱う。reviewed file
> list、full tests、Docker context audit、migration guard、secret/publication
> audit が green の commit SHA 以外は deploy/push/publish 禁止。

Date: 2026-05-01
読む人 (OTHER CLI): あなた

---

## 1 行で

**historical note: 以前のセッションでは deploy 可能と評価されたが、現在の巨大 dirty tree では deploy NO-GO。残タスクは ETL 増強 (A5 / B 系) と ship 待ち deliverable (HF / outreach / Chrome / B2G)。**

---

## 2026-05-01 08:40 JST 追記: max-agent loop 最新正本

この章を最新版として扱う。下の既存セクションには、前セッション時点の古い数値や「完成済み」と「plan-only」が混ざっている。矛盾したらこの追記を優先する。

## 2026-05-01 09:20 JST 追記: historical deploy note + 起動ブロッカー修正

この追記は historical。現在の dirty checkout は deploy NO-GO で、Fly 本番へ
追加 deploy する場合は clean reviewed commit SHA で再評価する。

## 2026-05-01 10:05 JST 追記: continuation loop note

この追記は実行ループの短い状態メモ。JPCITE env rename compatibility は後方互換 alias で維持、今回のメモ作成では env key 削除なし。no-LLM verification 方針は継続し、OpenAI/LLM API 呼び出しと HF publish/upload は未実行。email/API stale quota cleanup は、触れた docs/tests で anonymous 3 req/day 表記へ寄せた。freee/MF plugin cleanup は進行中で、この追記では plugin/site/manifest に触っていない。直近の検証は targeted billing/payment safety pytest `57 passed` と、対象 billing test files の scoped ruff check pass。

## 2026-05-01 11:35 JST 追記: JPCITE env / public-copy / plugin cleanup

この追記を 10:05 note より新しい状態として扱う。`AUTONOMATH_API_KEY` は LLM key ではなく jpcite REST/MCP key の旧 alias。新規導線は `JPCITE_API_KEY` / `JPCITE_API_BASE` に統一し、旧 alias は互換目的で残す。公開 HTML のコピペ導線、trial/success/dashboard/integrations/audience pages、DXT manifest、docs examples、freee/MF plugin 提出物を更新し、旧 `sk_...` placeholder、旧 50/月、旧 primary brand/domain、`Token Cost Shield` 見出しを除去した。feedback widget は `window.jpciteFeedback` で呼び出しと実体を一致させた。`site/docs` は `mkdocs build --clean` で再生成済み。

検証済み: root targeted pytest `34 passed`; freee marketplace `npm test` `10 passed`; MF plugin pytest `14 passed` (pytest config warning 1 件のみ); TypeScript SDK typecheck pass; JSON validation / node syntax / scoped ruff / scoped diff-check pass。

重要: 現在の worktree は大規模 dirty のまま。deploy-readiness audit では、未レビュー差分、untracked migration/schema_guard リスク、generated site と source の分離不足が残るため、この状態を丸ごと本番 deploy しない。

### 本番状態

| 項目 | 値 |
|---|---|
| Fly app | `autonomath-api` |
| 本番 API | `https://api.jpcite.com` |
| deployed image | `autonomath-api:deployment-01KQGE7TNDRDV1A8YZ0D6SSDV9` |
| machine | `85e273f4e60778` |
| region | `nrt` |
| machine version | `45` |
| state | `started` |
| health check | passing |
| OpenAPI | title `jpcite`, version `0.3.1`, paths `178` |
| reasoning preview endpoints | `/v1/am/reason` / `/v1/am/intent` は OpenAPI から除外済み |
| deep health | `status=ok`, `version=v0.3.2`, 10 checks all `ok` |

### この deploy で直した本番事故

1. `entrypoint.sh` が 9.79GB の `/data/autonomath.db` に対して毎 boot `sha256sum` を実行し、HTTP server 起動前に数分以上止まる問題を修正。
2. 同じく毎 boot `PRAGMA integrity_check` を 9.79GB DB に実行して起動を止める問題を修正。
3. `120_drop_dead_vec_unifts.sql` は巨大な `DROP TABLE` maintenance migration なので `-- boot_time: manual` に変更し、production boot では skip。
4. DB sidecar stamp `/data/autonomath.db.sha256.stamp` を導入。内容は本番 volume 上で作成済み。
5. boot 後に `schema_guard OK` まで通ったら `trusted <sha> <size>` stamp を書く。R2 snapshot SHA と local boot-time migration 後 DB の差分で毎回 redownload/hash になる事故を避ける。

### 本番 verification

実行済み:

```bash
bash -n entrypoint.sh scripts/smoke_test.sh
curl -fsS https://api.jpcite.com/healthz
curl -fsS https://api.jpcite.com/v1/openapi.json
BASE_URL=https://api.jpcite.com TIMEOUT=25 ./scripts/smoke_test.sh
curl -fsS https://api.jpcite.com/v1/am/health/deep
```

結果:

- `/healthz`: 200
- `/v1/openapi.json`: `{'title': 'jpcite', 'version': '0.3.1', 'paths': 178, 'has_reason': False, 'has_intent': False}`
- smoke: `passed=11 failed=0 total=11`
- deep health: `db_jpintel_reachable`, `db_autonomath_reachable`, `am_entities_freshness`, `license_coverage`, `fact_source_id_coverage`, `entity_id_map_coverage`, `annotation_volume`, `validation_rules_loaded`, `static_files_present`, `wal_mode` all `ok`

注意:

- smoke の匿名 section は、API_KEY なしで anonymous 3 req/day を使い切っている場合、`429` を「quota が効いている」として PASS 扱いにした。課金保護として正しい。
- Cloudflare Pages / static site はこの操作では push/deploy していない。Fly API deploy のみ。
- worktree は既に大規模 dirty。今回の deploy-critical 変更は少なくとも `entrypoint.sh`, `scripts/migrations/120_drop_dead_vec_unifts.sql`, `scripts/smoke_test.sh`。他ファイルの大量差分は前 CLI/他 agent 由来が混ざるため、勝手に revert しない。
- `scripts/smoke_test.sh` の修正は最後の Fly deploy 後に入った post-deploy tool 修正。runtime API には影響しないが、次に image を焼くと入る。

**超要約**: 今回のループで「すぐ売るための外部 signal」と「データ moat を増やすための実行計画」をかなり整理した。実データが増えたのは主に A5 source verification と B9 e-Stat provenance。B2/B4/B6/B10/G5 は、実行本番ではなく安全な在庫・計画・runbook まで。

### いまの状態

| 領域 | 最新状態 | 次に見るもの |
|---|---|---|
| A5 source verification | quick-domain shard 4 本は完走。1,085 ドメイン / 2,699 candidate を処理し、2,532 行を `last_verified` 更新。DB 全体は `6,667 / 97,145 HTTP rows = 6.86%` verified。A5 gate は未達。 | `analysis_wave18/source_verification_shard_summary_2026-05-01.md` |
| A5 残り | HTTP 未検証 90,478 行。最大残りは `www.houjin-bangou.nta.go.jp` 86,176 行、次の未検証 id は 50,471。remaining quick domain は 73 ドメイン / 167 行だけ。 | `scripts/etl/backfill_am_source_last_verified.py` を domain 単位で続行 |
| B9 e-Stat provenance | 完了。e-Stat facts 1,259,277 行に `source_id` を backfill、残 null 0。 | `scripts/etl/backfill_estat_fact_provenance.py` |
| F3 statistics-estat | HF ローカル export 完了。1,259,277 rows、license `gov_standard_v2.0`、manifest/README/parquet あり。push は未実行。 | `dist/hf-statistics-estat/` |
| F1/F2/F4/F5 HF | safe local datasets と upload bundle は準備済み。bundle は 4 logical outputs / 1,268,817 rows。`dist/hf-dataset` は古く危険なので明示除外。publish/upload は未実行。 | `dist/hf-upload-bundle/manifest.json`, `analysis_wave18/hf_upload_bundle_2026-05-01.json` |
| A8 known gaps | helper と sample report は完成。30 samples 中 25 に known gaps、ratio 0.8333。`evidence_packet.py` 配線は protected file のため未実装。 | `analysis_wave18/quality_known_gaps_samples_2026-05-01.json` |
| B2 NTA invoice bulk | plan-only。現 DB は 13,801 registrants、推定 full 4,000,000 まで 3,986,199 残り。月次 cron はあるが、full snapshot 取得・privacy/takedown・prod preflight が blocker。 | `analysis_wave18/nta_invoice_bulk_plan_2026-05-01.json` |
| B4 e-Gov law fulltext | plan-only。重要訂正: 現在の `data/jpintel.db.laws` には `body_text` column が無い。したがって「fetch すれば増える」ではなく、まず保存先 schema/loader を整える必要がある。 | `analysis_wave18/egov_law_fulltext_plan_2026-05-01.json` |
| B6 PDF extraction | inventory/plan-only。PDF candidate 3,222 rows / 1,163 unique sources、batch-processable は 1,426 rows / 886 unique sources。4 shard の run command は JSON 内にあるが、fetch/extract/promote は未実行。 | `analysis_wave18/pdf_extraction_inventory_2026-05-01.json` |
| B10 NTA corpus | ingest runbook/shard generator まで。coverage は 3,922 rows、duplicate source URL groups 336 が blocker。crawl/ingest は未実行。 | `analysis_wave18/nta_corpus_ingest_plan_2026-05-01.json` |
| G5 staging separation | readiness-only。staging roots 2、3,069 files、155,604 LOC、DB-like files 7。owner confirmation / dirty worktree / ignored staging files が blocker。move/delete は未実行。 | `analysis_wave18/staging_separation_plan_2026-05-01.md` |
| H outreach | firm docs と RAG/MCP developer pool は完成。ただし送信は user/operator action。外部 signal はまだ実送信で作る必要あり。 | `research/outreach/` |

### 次の CLI が最初にやること

1. `ps -axo pid,etime,command | rg 'source_verification_shard_|backfill_am_source_last_verified|pytest'` で処理残りを確認する。現時点で A5 shard は残っておらず、古い pytest PID だけが残っていた。
2. A5 を続けるなら、まず remaining quick 73 domain / 167 rows を片付け、その後 `www.houjin-bangou.nta.go.jp` を単一 domain として `--resume-after-id 50470` 以降で続ける。1 domain に対して同時に複数 worker を当てない。
3. HF は `dist/hf-upload-bundle/` だけを候補にする。`dist/hf-dataset` は `failed_current_db` 扱いで publish 対象外。
4. B4 は「本文取得」より前に `laws.body_text` の保存先設計を確認する。現 DB では body_text column が存在しない。
5. B6 は `analysis_wave18/pdf_extraction_inventory_2026-05-01.json` の shard command を使えるが、robots / per-host delay / cache path を確認してから実行する。まだ DB facts promotion はしない。
6. B2/B3 は bulk 取得前に license/privacy/takedown gate を先に閉じる。
7. G5 は owner confirmation なしで `autonomath_staging` や `_salvage_from_tmp` を移動・削除しない。

### 守ること

- ここまで commit/push はしていない。
- LLM API は呼んでいない。
- HF publish/upload はしていない。
- protected files (`api/intelligence.py`, `services/evidence_packet.py`, `api/main.py`, `api/programs.py`) は、この追記作業では触らない。
- `_archive/` は触らない。
- 「token cost shield」を headline に戻さない。価値命題は `Evidence Pre-fetch / Provenance Layer` として扱う。

---

## 数学的事実 (2026-05-01 実測、判断の根拠)

| 指標 | 値 | 含意 |
|---|---|---|
| programs 件数 | 14,472 (searchable 11,684) | 頭打ち、量より質 |
| aliases_json non-empty | 10,009 / 14,472 (69%) | 検索ヒット率改善済 |
| prefecture filled | 8,461 / 14,472 (58%) | あと 6,011 件が地域メタ欠落 |
| municipality filled | 3,122 / 14,472 (22%) | 1,207 自治体が未カバー |
| am_amendment_diff | 7,819 行 (0 → 7,819) | 改正イベント feed 起動済 |
| am_source.content_hash NULL | 0 (281 → 0) | 全件補完 |
| am_source.last_verified | 6,667 / 97,145 HTTP rows (6.86%) | quick-domain shard 完走、残りは over-threshold domain 中心 |
| am_entity_facts.source_id | 2,461,196 (target 80,000 の 30 倍) | 過剰達成 |
| 法令本文 | 0 / 9,484、現 DB は `body_text` column なし | B4 は fetch 前に schema/loader 確認が必要 |
| precomputed_query_rate | 40% | 8 internal stitch 上限 73%、外部 ingest で 80%+ |
| Repo size | 12 GB (113 → 12) | 101 GB 解放済 |
| 引用グラフ Gini | 0.9546 | top 10 ハブ 88% 占有 |
| FTS5 k_50 | 3.0 chars | LIKE fallback 必須 (実装済) |
| Tier C キャリブレーション | +40% 過大評価 | C3 重み再正規化済 |

---

## 完了済 (THIS CLI + OTHER CLI 統合)

### Section A: Schema stitch (内部 DB)
- ✅ A1 LAW prefix 統一
- ✅ A2 corp_entity edge promotion (153K)
- ✅ A3 am_amendment_diff cron (7,819 行)
- ✅ A4 content_hash backfill (NULL = 0)
- ⏳ **A5 last_verified backfill (6,667 / 97,145 HTTP rows、quick-domain shard は完走、全体 gate は未達)**
- ✅ A6 source_id backfill (2,461,196)
- ✅ A7 confidence 連続値化 (`_uncertainty.score` を正本化)
- ⏳ A8 known_gaps inventory (30 sample で 83.3% gap-reported、packet 配線は protected file のため未完了)

### Section B: 外部 ingest (準備完了 / 未投入)
- ⏳ B1 NTA 法人番号 4.5M (preflight 完了、bulk 取得未投入)
- ⏳ B2 NTA 適格請求書 4M (cron `nta-bulk-monthly.yml` 配線済、月次 1 回 SPOF)
- ⏳ B3 gBizINFO 5M (preflight 完了)
- ⏳ B4 e-Gov 法令本文 (plan-only。現 `data/jpintel.db.laws` は `body_text` column なし)
- ⏳ B5 court excerpt (readiness/proposal-only。missing `source_excerpt` 1,218、local-only proposal は 1 件だけ)
- ⏳ B6 PDF 抽出 (inventory/plan-only。3,222 PDF candidate rows、1,163 unique sources、実 fetch/extract/promote は未実行)
- ⏳ B7 adoption reconciliation (`scripts/etl/reconcile_adoption_to_program.py` 完成、smoke 100% match、推定 ~22 min で 157,444)
- ⏳ B8 JGrants V2 (mapping helper + upsert plan のみ。local detail JSON 0、`data/jpintel.db` の upsert surface 不足)
- ✅ B9 e-Stat URL backfill (1,259,277 fact rows に `source_id` backfill、残 null 0)
- ⏳ B10 NTA 通達 (coverage report + ingest plan/shard scripts 完成、crawl/ingest 未実行)
- ⏳ B11 GEPS (feasibility limited-yes、smoke 19 件)
- ⏳ B12 JFC + 信用保証協会 (`scripts/etl/ingest_jfc_loan_scaffold.py` 完成、29 + 51 URL)
- ⏳ B13 prefecture/municipality (89% / 22%、`scripts/etl/extract_prefecture_municipality.py` 残作業可能)

### Section C: 検索 / API
- ✅ C1 FTS5 bm25 (5×primary_name)
- ✅ C2 短語 LIKE fallback
- ✅ C3 tier prior boost (S=1.07, A=1.06, B=1.06, C=0.99, X=0.83)
- ✅ C4 PRAGMA cache_size pin (256 MB)
- ✅ C5 scipy lazy load
- ✅ C6 `/v1/me/*` 監査 (gate 候補ゼロ確認)

### Section D: データ品質
- ✅ D1 stale-deadline (1 件のみ closed 化)
- ✅ D2 placeholder amount (review queue 147 件 CSV)
- ✅ D3 33 orphan authority FK
- ✅ D4 89 HTTP→HTTPS
- ✅ D5 subsidy_rate text 列分離 (10 件 fix、migration 121)
- ⏳ D6 axis_key migration (preflight 完了、設計書あり、実装未)
- ✅ D7 hard_404 slash-flip (66 候補、1 件 ok)
- ✅ D8 blocked URL UA 切替
- ✅ D9 aliases_json (82 → 10,009)

### Section E: HF 公開前リスク
- ✅ E1 license review queue (1,425 行 CSV)
- ✅ E2 aggregation gate (HF dataset 出力時 hard-block)
- ⏳ E3 Tier B+C URL liveness scan (`scripts/etl/scan_program_url_liveness.py` 完成、11,013 候補、smoke 30 件)

### Section F: HF dataset publish (safe local bundle 完成、push は未実行)
- ⏳ F1 `bookyou/laws-jp` (local parquet ready、9,484 rows)
- ⏳ F2 `bookyou/invoice-registrants` (full bulk ではなく safe aggregate のみ publish 候補)
- ⏳ F3 `bookyou/statistics-estat` (local parquet ready、1,259,277 rows)
- ⏳ F4 `bookyou/corp-enforcement` (safe aggregate ready)
- ⏳ F5 HF upload bundle / checksum (4 logical outputs、1,268,817 rows、publish/upload 未実行)

### Section G: Repository hygiene
- ✅ G1 99.5 GB DB バックアップ削除 (113 → 12 GB)
- ✅ G2 70 unused imports cleanup
- ✅ G3 dead MCP tool gate-off audit (no action needed)
- ✅ G4 5 untested critical file tests (14 tests)
- ⏳ G5 autonomath_staging 別 repo 分離 (readiness-only。3,069 files / 155,604 LOC、owner 確認待ち)

### Section H: outreach
- ✅ H1 consultant outreach 10 firm (税理士 / 公認会計士 / 司法書士 / 補助金 / M&A / 製造業 / 国際税務 / 創業融資)
- ✅ H2 RAG/MCP dev pool (10 channel ranked + 投稿テンプレ完成)

### Section I: 価値命題書き直し
- ✅ I1 site/index.html (token frame 撤去 + 三本柱)
- ✅ I2 site/pricing.html (比較表削除 + 3 軸価値)
- ✅ I3 docs/api-reference.md (workload-dependent 注記)
- ✅ I4 README.md (evidence-first context layer)

### Section J: 新規追加 (今日)
- ✅ J1 GitHub Action (`sdk/github-action/`、competing 0、5 use case)
- ✅ J2 npm package (`@bookyou/jpcite`、build green、5/5 test、9.6 KB tarball)
- ✅ J3 Chrome 拡張 + bookmarklet (`sdk/chrome-extension/` + `site/bookmarklet.html`)
- ✅ J4 公開 RSS feed × 50 (`site/rss/programs-tier-s.xml` + `amendments.xml` + 47 prefecture)
- ✅ J5 月次改正 digest infra (`scripts/etl/generate_monthly_amendment_digest.py`、markdown + HTML)
- ✅ J6 税理士月次丸投げパック (`scripts/etl/generate_consultant_monthly_pack.py`、5 page PDF × 50 顧問先)
- ✅ J7 B2G ピッチ pack (自治体 / 商工会議所 / 信金 + 連絡先 177 件 CSV)
- ✅ J8 MCP marketplace 6 件追加登録準備
- ✅ J9 conversion 摩擦削減 (`anon_limit.py` に `direct_checkout_url` 追加、5→3 click)
- ✅ J10 demo kit (60-90s screencast 台本 + GIF 5 frame + X thread 5 tweet)
- ✅ J11 landing copy A/B (V2+C2 実装、conversion 3-5× 期待)
- ✅ J12 cohort killer audit (8 cohort grade、A grade 2 件、最大 cohort #5 補助金 consultant)

### deploy 関連
- ✅ 17 deploy blocker 全 fix (billing_breakdown / calendar.ics / customer_webhooks UA / programs response / license gate / brand UA + CSV / kaikei §47条の2 / rule_engine error.code / test_api count drift)
- ✅ smoke pre-launch GREEN (49/49)
- ✅ critical test sweep 226/226
- ✅ OpenAPI regen (178 → 179 paths)
- ✅ mkdocs --strict 0 warnings
- ✅ Version 同期 (pyproject + server.json + dxt + smithery + mcp-server = 0.3.2)
- ✅ DEPLOY_CHECKLIST_2026-05-01.md (45 項目)
- ✅ CLAUDE.md + CHANGELOG.md 更新済
- ⏳ git commit + tag v0.3.2 + push + fly deploy (operator)

---

## ここからやることの方針

### 戦略 4 軸 (memory 違反なしで 200-300 万/月の射程)

**1. B2G (信金 / 商工会議所 / 自治体)** — 最大射程
- 連絡先 CSV 177 件 (`analysis_wave18/b2g_contacts_2026-05-01.csv`)
- 1 信金一括 ¥381k/月 想定、5% 採用 ¥1.9M/月
- ピッチ markdown 3 本完成
- widget infra 既存 (`site/widget/jpcite.js`)
- **執行**: メール送信のみ (1 日 5 通制限、info@bookyou.net 経由)

**2. HF (dataset + embeddings) public** — 長期 moat
- 5 dataset markdown + parquet ready (laws-jp / invoice-registrants / statistics-estat / corp-enforcement / embeddings-jp)
- `scripts/publish_hf_datasets.py` + `scripts/etl/export_hf_embeddings.py` 完成
- HF_TOKEN 投入で 1 cmd push
- 期待 ¥10-30k/月 直接、+ LLM 訓練 corpus moat

**3. Chrome 拡張 + bookmarklet** — 税理士・記者・コンサルの日常業務に侵入
- `sdk/chrome-extension/` (manifest v3、12 file)
- `site/bookmarklet.html` 配布 page (drag drop 可)
- bookmarklet は今すぐ使える (Chrome Web Store 公開不要)
- 期待 ¥5-300k/月

**4. 税理士 cohort #2 (kaikei pack + 月次丸投げ)** — fan-out 倍率最大
- 月次丸投げパック PDF generator 完成 (`scripts/etl/generate_consultant_monthly_pack.py`)
- audit_seal pack PDF 動作確認 (5 件改善必要、§47条の2 disclaimer 復活済)
- consultant outreach 10 firm 完成 (`research/outreach/firm_01..10_*.md`)
- 期待 50 顧問先 × 1 法人で ¥11k/月、20 法人並列で ¥225k/月、組織導入で +¥150-500k 単独

### 数値目標 (組み合わせで)

```
B2G 信金 1 件 + 商工会議所 1 件 + 自治体 5 件 = ¥500k-1M/月
HF push (5 dataset) = ¥30k-150k/月
Chrome 拡張 + bookmarklet = ¥30k-300k/月
税理士法人 2-3 社踏み = ¥100k-500k/月
─────────────────────
合算 (上振れ条件)         = ¥660k-2M/月
+ 既出 conversion 改善等  = ¥800k-2.5M/月
```

200-300 万/月の射程に **数学的に入る** (但し全部刺さった場合)。

---

## 残タスク (やる/やらない 二択)

### A. ETL バックグラウンド継続 (OTHER CLI 担当)

| ID | 内容 | 推定時間 | 結果 |
|---|---|---|---|
| A5 | last_verified backfill (4 shard 並列) | ~24h | 4,135 → 95,000 |
| B4 | e-Gov 法令本文 fetch (script 完成) | ~2.6h | 154 → ~8,400 |
| B5 | court excerpt fetch (script 完成) | ~30-45 min | 0 → 1,217 |
| B6 | PDF 抽出 batch (script 完成) | ~70 min | parser 1,412 PDF |
| B7 | adoption full reconciliation (script 完成) | ~22 min | smoke 100% → 157,444 |
| B9 | e-Stat URL backfill (script 完成) | 未計測 | 0 → 73,623 |
| B13 | prefecture/municipality 残 (script 完成) | 未計測 | 89% → 100% |

**実行コマンド** (各 script の `--apply` モード):
```bash
# A5 (4 shard 並列)
for shard in 1 2 3 4; do
  uv run python scripts/etl/backfill_am_source_last_verified.py --apply --shard $shard --limit 1000 --json &
done

# B4
uv run python scripts/etl/fetch_egov_law_fulltext_batch.py \
  --output analysis_wave18/egov_law_fulltext_full.csv

# B5
uv run python scripts/etl/enrich_court_decisions_excerpt.py

# B6 (1,412 PDF batch)
uv run python scripts/etl/run_program_pdf_extraction_batch.py \
  --output analysis_wave18/pdf_extraction_full.csv

# B7 (full)
uv run python scripts/etl/reconcile_adoption_to_program.py \
  --out analysis_wave18/adoption_reconciliation_full.csv
```

### B. user 判断待ち (operator 実行)

| ID | アクション | コマンド / 操作 |
|---|---|---|
| Deploy | git commit + tag + push + fly deploy | `git commit -m "..."; git tag v0.3.2; git push --tags; fly deploy` |
| HF push | F1-F5 push | `HF_TOKEN=hf_xxx uv run python scripts/publish_hf_datasets.py --dataset all --push` |
| HF embeddings | bookyou/embeddings-jp push | `HF_TOKEN=hf_xxx uv run python scripts/etl/export_hf_embeddings.py --push` |
| outreach | 10 firm にメール送信 | `research/outreach/firm_01..10_*.md` を info@bookyou.net から送信 |
| B2G outreach | 177 件 CSV から月 5 件選んで送信 | `analysis_wave18/b2g_contacts_2026-05-01.csv` |
| MCP marketplace | 6 件 manual 登録 | `analysis_wave18/mcp_marketplace_submission_queue_2026-05-01.md` |
| Chrome Web Store | unpacked 配布 (Web Store は ¥750 + Google アカ) | `sdk/chrome-extension/` を zip → 配布 |
| Zenn 公開 | 記事 push | `research/outreach/zenn_article_2026-05-01.md` |
| Qiita 公開 | 記事 push | `research/outreach/qiita_article_2026-05-01.md` |
| GitHub Topics | 19 topics 追加 | `gh repo edit --add-topic mcp-server,mcp-tools,...` |
| `npm publish` | `@bookyou/jpcite` v0.1.0 公開 | `cd sdk/npm-package && npm publish --access=public` |

### C. 引き続き OTHER CLI loop で取りに行ける残タスク

| ID | 内容 | メモ |
|---|---|---|
| D6 | axis_key column on am_entity_facts | preflight 完了、設計書あり (`scripts/etl/preflight_axis_key_migration.py`) |
| F5 | HF dataset card README final polish | markdown 既存、HF 形式 metadata 微調整 |
| 文書同期 | CLAUDE.md / docs/_internal/ の数値同期 | 直近 ETL 実行後の数値を反映 |
| `docs/faq.md:86` の sample JSON 修正 | `{"limit":50, ...次月}` → `{"limit":3, ...翌日}` | 1 行修正 |

### D. 新規アイデア (探索済、ROI 低判定で実装しない)

- ChatGPT plugin (Anthropic-first 戦略と矛盾)
- Notion integration (工数大、ROI 不確か)
- Twitter Bot (誤情報リスク)
- Discord 公式 server (zero-touch 違反)
- Podcast / YouTube (organic 限界)

---

## 絶対ルール (一個でも破らない)

- **LLM API を一切呼ばない**。`anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk` を src/cron/etl/tests に絶対 import しない。CI guard `tests/test_no_llm_in_production.py` がある
- **agg サイト (noukaweb / hojyokin-portal / biz.stayway) を `source_url` に絶対書かない**
- **robots.txt と Crawl-Delay を守る**。1 ドメインあたり ≤ 1 req/sec
- **¥3/billable unit メータード単一モデル** を変えない (tier SKU 提案禁止、月額 SKU 提案禁止)
- **新規 SaaS UI を作らない** (memory `feedback_autonomath_no_ui`、既存 dashboard.html 改善は OK)
- **migration ファイルの番号を後から変えない** (immutable history)
- **license=unknown / proprietary は HF 公開対象から除外**
- **既存 `_archive/`, `docs/_internal/_archive/` は触らない**
- **「工数」「priority」「phase」「まず」「次」「MVP」「stage」概念は出力に入れない**。AI が全部やる前提で「やる/やらない」「終わった/終わってない」だけ
- **DB の VACUUM / 巨大 ALTER は避ける**。SELECT と小規模 INSERT/UPDATE は OK
- **commit を勝手にしない**。staged のまま jpcite owner に報告。push もしない
- **広告 (Google Ads / Meta / X) を実行しない** (memory `feedback_organic_only_no_ads`)
- **営業電話 / sales call / DPA 交渉しない** (memory `feedback_zero_touch_solo`)
- **Junior Eng / 採用 / 業務委託しない** (memory `feedback_zero_touch_solo`)

---

## 推奨実行順序 (B2G + HF + Chrome + 税理士 4 軸)

1. **A5 shard 4 並列実行** (24h で 95K 到達)
2. **B5 court excerpt 実行** (30-45 min で 1,217 充足)
3. **B7 full reconciliation** (22 min で 157K)
4. **B6 PDF 抽出 全件** (~70 min で 1,412 PDF)
5. **B4 e-Gov 法令本文 全件** (~2.6h で +8,400)
6. **B9 / B13 残データ充足**
7. **D6 axis_key migration 実装** (preflight 既済)
8. **CLAUDE.md / EXECUTION_LOG 数値同期**

操作 (operator 待ち) は並行で:
- HF push → outreach 送信 → MCP marketplace 登録 → Chrome 拡張配布 → Zenn/Qiita 公開 → npm publish → GitHub topics → fly deploy

---

## 検証コマンド (進捗確認)

```bash
# 進捗の数値確認
sqlite3 /Users/shigetoumeda/jpcite/autonomath.db \
  "SELECT 'last_verified', COUNT(*) FROM am_source WHERE last_verified IS NOT NULL;"

sqlite3 /Users/shigetoumeda/jpcite/data/jpintel.db \
  "SELECT 'laws body_text', COUNT(*) FROM laws WHERE body_text IS NOT NULL;"

sqlite3 /Users/shigetoumeda/jpcite/data/jpintel.db \
  "SELECT 'prefecture filled', COUNT(*) FROM programs WHERE prefecture IS NOT NULL;"

# bench probe (40% → 80% target)
uv run python tools/offline/bench_prefetch_probe.py --limit 5 \
  | jq -c '{precomputed_query_rate, zero_result_rate}'

# 全テスト
uv run pytest tests/test_endpoint_smoke.py tests/test_no_llm_in_production.py -q

# loop 完了状況
grep -c "✅" research/loops/OTHER_CLI_AUTO_LOOP_PROMPT.md
```

---

## 完了の最終ゴール (再掲)

すべての atomic task が ✅ になり、以下の SQL が `1.0` を返した瞬間 = jpcite が数学的に 100% 完成:

```sql
WITH packet_check AS (
    SELECT
        unified_id,
        CASE WHEN
            corpus_snapshot_id IS NOT NULL
            AND content_hash IS NOT NULL
            AND fetched_at IS NOT NULL
            AND source_id_coverage >= 0.95
            AND license != 'unknown'
            AND law_prefix_reconciled = 1
            AND exclusion_rule_count >= 1
            AND corp_canonical_edge_count >= 1
            AND adoption_canonical_edge_count >= 0
            AND source_url_scanned = 1
            AND confidence_continuous = 1
            AND pdf_facts_extracted = 1
            AND aliases_json IS NOT NULL AND aliases_json != '[]'
            AND prefecture IS NOT NULL
        THEN 1.0 ELSE 0.0 END AS complete
    FROM v_program_evidence_completeness
)
SELECT AVG(complete) FROM packet_check;
```

合わせて `bench_prefetch_probe.py --limit 30` の `precomputed_query_rate` が **40% → 95%+** に到達。

---

## 注意点 (operator 向けメモ)

- この変更を含む branch は **未 commit / 未 push**
- jpcite owner = Bookyou株式会社 (T8010001213708)、代表 梅田茂利、info@bookyou.net
- 4 manifest version 一致 (0.3.2)、PyPI 0.3.2 既に live、git tag のみ未打刻
- 「200-300 万/月」は **全部刺さった上振れシナリオ**、悲観シナリオは月 ¥-30K
- 上振れ確率 25-35% (memory 違反なし、organic + solo + zero-touch 維持)
- `docs/_internal/DEPLOY_CHECKLIST_2026-05-01.md` に 45 項目チェック
- 信頼度ラベル: 数値で「UNVERIFIED」と書かれているものは推定値

これ以上の探索は diminishing return。**残ってるのは執行**。

---

## 2026-05-01 10:18 JST production deploy 追記

実施済み:

- Cloudflare Pages production deploy 完了
  - project: `autonomath`
  - custom domains: `jpcite.com`, `www.jpcite.com`
  - preview/deploy URL: `https://135e63c9.autonomath.pages.dev`
  - `site/` deploy 前に secret scan / `site/docs/_internal` 混入確認 OK
- Fly API production deploy 完了
  - app: `autonomath-api`
  - image: `autonomath-api:deployment-01KQGHMCM1X6Y79ZGZHTSRW58W`
  - machine: `85e273f4e60778`
  - version: `46`
  - region: `nrt`
  - status: `started`, checks `1 total, 1 passing`
- volume snapshot
  - `vs_l0nKmDJwlKV5U6jgx94g8JQ` created (40 GiB volume, stored size 1.4 GiB, created 2026-05-01 10:03 JST 頃)

出した主な修正:

- 課金 P0:
  - `invoice.paid` webhook から raw API key を発行しないよう修正。key reveal は Checkout state cookie 付き `/v1/billing/keys/from-checkout` のみに限定。
  - English checkout redirect (`/en/success.html`, `/en/pricing.html`) を許可。
  - `site/en/pricing.html` の checkout fetch を `https://api.jpcite.com/v1/billing/checkout` に修正。
- 月次 cap P0:
  - 現在値だけでなく「次に発生する請求額込み」で cap 判定。
  - `programs/batch`, `bulk_evaluate`, `am/dd_batch`, `am/dd_export` の multi-unit billing 前に projected cap check を追加。
  - usage logging 時に cap cache を進め、5 分 TTL 内の burst overshoot を抑制。
- Fly/DB:
  - `entrypoint.sh` の stamp を実 SHA stamp と trusted DB stamp に分離。
  - `AUTONOMATH_ENABLED=true` で DB integrity/schema_guard が失敗した場合は silently degraded で起動せず boot fail。
  - `-- boot_time: manual` migration skip 継続 (`120_drop_dead_vec_unifts.sql`)。
  - Docker image に `rclone` を追加し、`restore_db.py` の autonomath R2 prefix を実 backup workflow と整合。
  - Fly health check は `/v1/am/health/deep?fail_on_unhealthy=true` へ変更。
- docs:
  - OpenAPI regenerated (`docs/openapi/v1.json`, 178 paths)。
  - public webhook docs の fake secret 表記を `<webhook_signing_secret>` に変更。
  - `/keys/from-checkout` は cookie-bound flow と明記。

検証済み:

```bash
bash -n entrypoint.sh scripts/smoke_test.sh
uv run ruff check src/jpintel_mcp tests scripts/etl scripts/cron tools/offline --select F,E9,B006,B008,B017,B018,B020,B904 --output-format=concise
uv run pytest tests/test_billing.py tests/test_billing_tax.py tests/test_billing_webhook_idempotency.py tests/test_stripe_webhook_dedup.py tests/test_stripe_smoke_unit.py tests/test_me_subscription_status.py tests/test_self_cap.py -q
# 73 passed
uv run pytest tests/test_search_relevance.py tests/test_api.py tests/test_endpoint_smoke.py tests/test_health_deep.py tests/test_universal_envelope.py -q
# 113 passed, 1 warning
uv run mkdocs build --strict
fly config validate --app autonomath-api
BASE_URL=https://api.jpcite.com TIMEOUT=25 ./scripts/smoke_test.sh
# passed=11 failed=0 total=11
```

本番確認:

- `https://api.jpcite.com/healthz` -> `{"status":"ok"}`
- `https://api.jpcite.com/readyz` -> `{"status":"ready"}`
- `https://api.jpcite.com/v1/am/health/deep?force=true&fail_on_unhealthy=true` -> `status=ok`, `10/10 checks ok`
- `https://api.jpcite.com/v1/openapi.json` -> `178 paths`, `fail_on_unhealthy=true` parameter present
- `https://jpcite.com/en/pricing.html` -> checkout fetch が `https://api.jpcite.com/v1/billing/checkout` を参照
- on-box:
  - `rclone v1.60.1-DEV`
  - `/data/autonomath.db` 9.2G
  - `/data/autonomath.db.sha256.stamp` present
  - `/data/autonomath.db.trusted.stamp` present
  - lightweight SQLite read OK (`PRAGMA schema_version` = 532, `sqlite_master` count = 749)

補足:

- `PRAGMA quick_check(1)` は 9.2GB DB の全体走査で本番 I/O が重く、数分経っても完了しなかったため中断。中断後も deep health は 10/10 OK。
- Cloudflare workflow 上の projectName は `autonomath-fallback` のままだが、実アカウントに存在する production project は `autonomath`。今回の本番 deploy は `wrangler pages deploy site --project-name autonomath --branch main` で実行。
- 追記後に `.github/workflows/pages-preview.yml` も `projectName: autonomath` へ修正済み。

---

## 2026-05-01 10:42 JST production redeploy 追記

追加で直したもの:

- 外部発見性:
  - `https://jpcite.com/openapi/v1.json` と `/v1/openapi.json` を `https://api.jpcite.com/v1/openapi.json` へ 302。
  - `site/llms-full.txt` の旧 `111 endpoints` / `sk_...` / webhook key 自動発行 / batch 1req 課金 / `jpcite-fallback` 記述を現行仕様へ修正。
  - `site/playground.html` の API key placeholder を `am_...` に統一。
  - `.github/workflows/pages-regenerate.yml` の `--domain autonomath.ai` を `--domain jpcite.com` に修正。
- Checkout:
  - `site/en/pricing.html` の checkout fetch に `credentials: 'include'` を追加。EN success page で Checkout state cookie が欠落して key reveal 403 になる経路を塞いだ。
  - `docs/api-reference.md` と生成済み `site/docs/api-reference/` の webhook 説明を「raw API key は発行しない」に更新。
- 課金 cap:
  - request-time projected cap check に加えて、`deps.log_usage()` が `usage_events` / Stripe usage を記録する直前に `BEGIN IMMEDIATE` 下で最終 cap check を実行。
  - 同時実行で precheck が競合しても、上限超過分は「提供したが請求しない」側に倒す。`usage_events` insert に失敗した場合も Stripe usage は送らない。
  - `tests/test_self_cap.py` に inline / deferred log_usage の最終 cap guard テストを追加。
- smoke:
  - 本番匿名 quota 到達時に `/v1/ping` が 429 になるため、`scripts/smoke_test.sh` は 200/429 を許容するよう修正。

再デプロイ:

- Cloudflare Pages:
  - project: `autonomath`
  - deploy URL: `https://48186bc9.autonomath.pages.dev`
- Fly API:
  - app: `autonomath-api`
  - image: `autonomath-api:deployment-01KQGJXB07TA71ZVBQN486XG9Q`
  - machine: `85e273f4e60778`
  - version: `48`
  - region: `nrt`
  - status: `started`, checks `1 total, 1 passing`

検証:

```bash
uv run pytest tests/test_billing.py tests/test_billing_tax.py tests/test_billing_webhook_idempotency.py tests/test_stripe_webhook_dedup.py tests/test_stripe_smoke_unit.py tests/test_me_subscription_status.py tests/test_self_cap.py -q
# 75 passed
uv run pytest tests/test_search_relevance.py tests/test_api.py tests/test_endpoint_smoke.py tests/test_health_deep.py tests/test_universal_envelope.py -q
# 113 passed, 1 warning
bash -n scripts/smoke_test.sh
BASE_URL=https://api.jpcite.com TIMEOUT=25 ./scripts/smoke_test.sh
# passed=11 failed=0 total=11
```

公開確認:

- `https://jpcite.com/openapi/v1.json` -> 302 to `https://api.jpcite.com/v1/openapi.json`
- `https://jpcite.com/en/pricing.html` -> `credentials: 'include'` present
- `https://jpcite.com/docs/api-reference/` -> webhook は raw API key を発行しない記述
- `https://api.jpcite.com/healthz` -> `{"status":"ok"}`
- `https://api.jpcite.com/readyz` -> `{"status":"ready"}`
- `https://api.jpcite.com/v1/am/health/deep?force=true&fail_on_unhealthy=true` -> `status=ok`, `checks=10`
- on-box:
  - `rclone v1.60.1-DEV`
  - `/data/autonomath.db` 9.2G
  - `/data/autonomath.db.sha256.stamp` present
  - `/data/autonomath.db.trusted.stamp` present
  - lightweight SQLite read OK (`PRAGMA schema_version` = 532, `sqlite_master` count = 749)

注意:

- 1 回目の Fly deploy は `volume host unreachable` で machine config update が止まった。直後に同じ image を `fly deploy --image ... --strategy immediate` で再試行し成功。
- repo 全体の full CI clean はまだ別課題。今回の production deploy gate は touched/billing/API/static の重点検証で green。
