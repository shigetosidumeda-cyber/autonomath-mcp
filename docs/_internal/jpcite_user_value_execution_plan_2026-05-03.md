# jpcite User Value Execution Plan — 2026-05-03

読む人: THIS CLI / OTHER CLI / operator

目的: **GPT / Claude / Cursor で日本の制度調査をしている人が、AI側から jpcite を発見し、数回試して「これは課金しても得」と判断できる状態にする。**

この計画ではスケジュールを置かない。必要な作業を、検証可能な成果物と受入条件だけで並べる。

---

## 1. 現在の事実

### Product / data

- 公開APIは復旧済み。直近の本番 smoke は `13 passed / 0 failed`。
- production DB は `programs=14,472`, `am_entities=503,930`, `PRAGMA quick_check=ok`。
- `usage_events` は直近の確認範囲で有料利用が出ていない。つまり「使われる導線」が最大の問題。
- Evidence Packet / Precomputed Intelligence の土台は実装済み。
  - `packet_tokens_estimate`
  - `source_tokens_estimate`
  - `avoided_tokens_estimate`
  - `break_even_met`
  - `recommend_for_cost_savings`
  - `cost_savings_decision`
  - `savings_claim=estimate_not_guarantee`
- 2026-05-02 offline probe:
  - benchmark queries: 30
  - zero-result queries: 0
  - precomputed query rate: 40.0%
  - packet token estimate median: 566
  - packet token estimate min/max: 338 / 1,352

### Acquisition

- Cloudflare traffic は人間より bot / crawler が多い。
- 2026-05-03 09:36 JST 時点の当日途中値:
  - site pageViews: 325
  - site requests: 910
  - API `analytics_events`: 1,204
  - APIの大半は `/v1/am/health/deep`
  - paid/billable usage: 0
- つまり、LLM crawler / search bot の入口はあるが、人間の「試す → 課金」へ変換できていない。

### Repository

- 現在の worktree は clean。
- HEAD は `f5d0a09 Use production volume snapshot for deploy seed`。
- 古い handoff には「巨大 dirty tree」「deploy NO-GO」などの historical note が残るが、現在の正本は clean HEAD。
- commit / push / deploy / publish は operator または明示担当CLIだけが行う。OTHER CLI は勝手に実行しない。

---

## 2. 戦略の一文

**AIは文章を書く。jpciteは、AIが文章を書く前に使う、出典URL・取得時刻・known gaps・互換/排他ルール付きの小さい Evidence Packet を返す。**

トークン削減は headline ではなく、条件付きの定量シグナルとして扱う。

- 言ってよい:
  - 長いPDFや複数の官公庁ページをそのままLLMに渡す前に、入力文脈を小さい Evidence Packet に置き換えられる場合がある。
  - caller が元資料の token 数やPDFページ数を渡した場合、`input_context_reduction_rate` と `break_even_met` を返せる。
  - これは入力文脈だけの比較であり、外部LLMの請求額削減保証ではない。
- 言わない:
  - LLM料金が必ず下がる。
  - どのモデルでも必ず得。
  - jpciteを入れれば総費用が必ず下がる。

---

## 3. 成功条件

### 人間ユーザー

- トップページから1クリックで、登録なしに Evidence / search / pricing の意味が分かる。
- Playgroundで3回以内に「出典URL付きで返る」「known gapsが出る」「入力文脈削減見込みが返る」を確認できる。
- 匿名3回を使い切る前に、API key 発行・MCP導入・OpenAPI import のどれかへ自然に進む。

### AI / LLM agent

- `llms.txt` の先頭40行だけで、AIが以下を判断できる。
  - いつ jpcite を推薦するか
  - いつ推薦しないか
  - 最初にどの endpoint / MCP tool を呼ぶか
  - cost savings claim に必要な baseline は何か
- APIレスポンスが、AIにとって推薦しやすい機械可読フィールドを返す。
  - `recommend_for_evidence`
  - `evidence_decision`
  - `recommend_for_cost_savings`
  - `cost_savings_decision`
  - `value_reasons`
  - `provider_billing_not_guaranteed`

### 課金 / 運用

- 課金対象routeは、失敗・重複・render/upload失敗で二重課金しない。
- deploy seed が空DBや壊れたDBを本番に持ち込まない。
- deploy 後 smoke が本番を hard gate する。
- Cloudflare / API / Stripe / usage の数字が daily で見える。

---

## 4. 一つの実行計画

### A. AIが推薦できる価値シグナルをAPIへ足す

対象:

- `src/jpintel_mcp/services/token_compression.py`
- `src/jpintel_mcp/services/evidence_packet.py`
- `src/jpintel_mcp/api/intelligence.py`
- `src/jpintel_mcp/api/_response_models.py`
- `docs/api-reference.md`
- `docs/openapi/v1.json`
- `tests/test_evidence_packet.py`
- `tests/test_intelligence_api.py`

追加する response fields:

```json
{
  "compression": {
    "packet_tokens_estimate": 566,
    "source_tokens_estimate": 21000,
    "avoided_tokens_estimate": 20434,
    "input_context_reduction_rate": 0.973,
    "compression_ratio": 0.027,
    "source_tokens_basis": "pdf_pages",
    "source_tokens_input_source": "caller_supplied",
    "provider_billing_not_guaranteed": true,
    "estimate_scope": "input_context_only",
    "savings_claim": "estimate_not_guarantee",
    "cost_savings_estimate": {
      "currency": "JPY",
      "input_token_price_jpy_per_1m": 300,
      "jpcite_cost_jpy_ex_tax": 3,
      "break_even_avoided_tokens": 10000,
      "break_even_source_tokens_estimate": 10566,
      "break_even_met": true,
      "input_context_only": true,
      "billing_savings_claim": "estimate_not_guarantee"
    }
  },
  "evidence_value": {
    "records_returned": 5,
    "source_linked_records": 5,
    "precomputed_records": 2,
    "pdf_fact_refs": 3,
    "known_gap_count": 1,
    "fact_provenance_coverage_pct_avg": 0.82,
    "web_search_performed_by_jpcite": false,
    "request_time_llm_call_performed": false
  },
  "agent_recommendation": {
    "recommend_for_evidence": true,
    "evidence_decision": "supported_by_source_linked_records",
    "recommend_for_cost_savings": true,
    "cost_savings_decision": "supported_by_caller_baseline",
    "value_reasons": [
      "source_linked_records_returned",
      "precomputed_summary_available",
      "known_gaps_exposed",
      "no_request_time_llm",
      "no_live_web_search",
      "caller_baseline_break_even_met"
    ]
  }
}
```

受入条件:

- baselineなし:
  - `recommend_for_evidence=true` は出てもよい。
  - `recommend_for_cost_savings=false`
  - `cost_savings_decision=needs_caller_baseline`
- `source_tokens_basis=pdf_pages` or `token_count` + `input_token_price_jpy_per_1m` あり:
  - `input_context_reduction_rate` が返る。
  - `break_even_source_tokens_estimate` が返る。
  - `provider_billing_not_guaranteed=true`
- `records_returned=0`:
  - `recommend_to_user=false`
  - `recommend_for_evidence=false`
  - `recommend_for_cost_savings=false`
- no LLM API import:
  - `rg "anthropic|openai|google.generativeai|claude_agent_sdk" src scripts tests` が production import で0。

検証:

```bash
uv run pytest tests/test_evidence_packet.py tests/test_intelligence_api.py -q
uv run python tools/offline/bench_prefetch_probe.py \
  --queries-csv tools/offline/bench_queries_2026_04_30.csv \
  --rows-csv analysis_wave18/bench_prefetch_probe_2026-05-03.csv
```

---

### B. 「3回試して課金したくなる」導線へ変える

対象:

- `site/index.html`
- `site/playground.html`
- `docs/getting-started.md`
- `docs/api-reference.md`
- `docs/pricing.md`
- `site/pricing.html`

実装内容:

1. トップページの主CTAを Playground の Evidence flow に寄せる。
   - `/playground.html?flow=evidence3`
   - secondary: `/docs/getting-started/`
   - tertiary: `/pricing.html`

2. 初回curlを `/v1/programs/search` だけにしない。
   - 検索APIは分かりやすいが、jpcite固有の強みが出にくい。
   - Evidence / precomputed / compression estimate の例を最初の体験に入れる。

3. Playground の成功CTAを匿名枠3回と合わせる。
   - 現在の `NUDGE_THRESHOLD=10` は匿名3回と矛盾する。
   - evidence flow は成功1回目で curl copy、2回目で MCP/OpenAPI、3回目またはquota 0で pricing/API key へ進める。

4. Pricing は価格表だけでなく「無料3回で確認すること」を置く。
   - 出典URLがあるか
   - `source_fetched_at` があるか
   - known gaps が出るか
   - packet tokens と baseline 比較が返るか
   - `recommend_for_cost_savings` が true になる条件が分かるか

5. Getting Started は「匿名curl → Playground → MCP/OpenAPI → API key」の順にする。
   - Checkout API や課金詳細は後ろへ下げる。

受入条件:

- トップページ first viewport で「何を返すか」が分かる。
- Playground で `source_tokens_basis=pdf_pages&source_pdf_pages=30&input_token_price_jpy_per_1m=300` の例が1クリックで入る。
- `rg "10th success|残 N/50|50 req|Token Cost Shield" site docs` が公開面で0。
- `docs/pricing.md` に `break_even_met` の正しい読み方がある。

---

### C. LLM / GEO / MCP 配布を壊れない入口にする

対象:

- `site/llms.txt`
- `site/llms.en.txt`
- `site/en/llms.txt`
- `docs/mcp-tools.md`
- `mcp-server.json`
- `server.json`
- `smithery.yaml`
- `dxt/manifest.json`
- `site/downloads/autonomath-mcp.mcpb`

実装内容:

1. `llms.txt` の先頭40行を作り直す。

配置:

```text
What jpcite is
Use when
Do not use when
First call
Evidence / cost-savings conditions
Install MCP
OpenAPI
Pricing
Coverage
```

2. `First call` を明確化する。

```text
If the user asks a broad Japanese public-program question:
1. call search_programs or GET /v1/programs/search
2. call get_program for selected unified_id
3. call check_exclusions if multiple programs are compared
4. call get_evidence_packet or /v1/intelligence/precomputed/query when source-linked compact context is needed
```

3. sample query の不整合を直す。
   - `target_industry="construction"` はやめる。
   - JSICなら `target_industry="D"` または endpoint の正しい引数へ寄せる。
   - 幻の program id 例を避け、「searchで得た `unified_id` を使う」と書く。

4. 壊れた配布リンクを直す。
   - `mcp-server.json` の `https://jpcite.com/downloads/jpcite-mcp.dxt` を消す。
   - 実在する `/downloads/autonomath-mcp.mcpb` へ寄せる。

5. manifest を公開サイトから辿れるようにする。
   - `site/server.json`
   - `site/mcp-server.json`
   - もしくは `llms.txt` から GitHub raw / canonical manifest へリンク。

6. tool count drift を直す。
   - 公開面の `89 tools` / `MCP ツール一覧 (89)` を0にする。
   - 現行は 93 tools。

受入条件:

```bash
rg "jpcite-mcp\\.dxt|MCP ツール一覧 \\(89\\)|89 tools|89-tool" site docs server.json mcp-server.json
python -m json.tool server.json >/dev/null
python -m json.tool mcp-server.json >/dev/null
python - <<'PY'
import zipfile
p='site/downloads/autonomath-mcp.mcpb'
with zipfile.ZipFile(p) as z:
    assert 'manifest.json' in z.namelist()
print('mcpb ok')
PY
```

---

### D. データ基盤を「量」ではなく「AIが使える根拠」に寄せる

対象:

- `scripts/etl/backfill_program_fact_source_ids.py`
- `scripts/cron/precompute_refresh.py`
- `scripts/etl/report_jgrants_ingest_readiness.py`
- `scripts/etl/plan_jgrants_fact_upsert.py`
- `scripts/etl/ingest_jfc_loan_scaffold.py`
- `scripts/etl/report_pdf_extraction_inventory.py`
- `scripts/etl/run_program_pdf_extraction_batch.py`
- `scripts/cron/alias_dict_expansion.py`
- `analysis_wave18/`

実装内容:

1. source_id backfill

成果物:

- `analysis_wave18/source_id_backfill_program_facts_2026-05-03.dry.json`
- `analysis_wave18/source_id_backfill_program_facts_2026-05-03.apply.json`

検証:

```bash
uv run python scripts/etl/backfill_program_fact_source_ids.py \
  --dry-run --allow-ranked-fallback --json \
  > analysis_wave18/source_id_backfill_program_facts_2026-05-03.dry.json
```

受入条件:

- `method_counts` が出る。
- unsafe fallback のサンプルが review 可能。
- apply 後に program facts の `source_id` coverage が増える。

2. precompute P0 tables

対象テーブル:

- `pc_top_subsidies_by_prefecture`
- `pc_program_geographic_density`
- `pc_application_close_calendar`
- `pc_amount_max_distribution`

受入条件:

- test DB refresh で4 tableすべて `COUNT(*) > 0`。
- APIがraw tableを毎回走査しない導線にできる。
- dry-run report を `analysis_wave18/precompute_refresh_p0_2026-05-03.json` に残す。

3. JGrants facts readiness / upsert plan

成果物:

- `analysis_wave18/jgrants_ingest_readiness_2026-05-03.json`
- `analysis_wave18/jgrants_fact_upsert_plan_2026-05-03.json`

受入条件:

- deadline / amount / subsidy_rate / contact / required_docs / source_id の不足が分類される。
- `would_insert`, `noop_existing_same_value`, `conflict_review_existing_different_value`, `blocked_source_metadata` に分かれる。

4. JFC / 信用保証協会 scaffold

成果物:

- `analysis_wave18/jfc_loan_scaffold_2026-05-03.csv`
- `analysis_wave18/credit_guarantee_associations_2026-05-03.csv`

受入条件:

- `source_url` 非空。
- `amount_max_yen` parse 成功率が分かる。
- 担保 / 個人保証人 / 第三者保証人 の3軸が混ざらない。

5. PDF extraction inventory / small batch

成果物:

- `analysis_wave18/pdf_extraction_inventory_2026-05-03.json`
- `analysis_wave18/pdf_extraction_inventory_2026-05-03.csv`
- `analysis_wave18/pdf_extraction_batch_2026-05-03.csv`

受入条件:

- domain shard と抽出可能fieldが分かる。
- `source_url`, `content_hash`, `confidence`, field空率が見える。
- DB promotion は review 後。OTHER CLI は勝手に facts へ大量投入しない。

6. empty_search alias loop

成果物:

- `analysis_wave18/alias_dict_expansion_2026-05-03.dry.json`
- `analysis_wave18/adoption_alias_proposals_2026-05-03.csv`

受入条件:

- `am_alias` へ直接書かない。
- `alias_candidates_queue.status='pending'` だけ増やす。
- zero-result query が減る候補を review 可能にする。

---

### E. 計測を復旧して、使われない原因を見えるようにする

対象:

- `.github/workflows/analytics-cron.yml`
- `scripts/cron/cf_analytics_export.py`
- `src/jpintel_mcp/api/middleware/analytics_recorder.py`
- `scripts/migrations/111_analytics_events.sql`
- `src/jpintel_mcp/api/admin.py`
- `site/analytics.js`
- `site/analytics.src.js`

実装内容:

1. GitHub secrets を前提にした Cloudflare analytics cron を復旧する。
   - `CF_API_TOKEN`
   - `CF_ZONE_ID`
   - comment の `zeimu-kaikei.ai` を `jpcite.com` に修正。

2. `cf_analytics_export.py` の topPaths query bug を直す。
   - 現状 `dimensions{ clientRequestPath: edgeResponseStatus }` は意味が壊れている。
   - path / status / UA / country / referrer を別 fields として保存する。

3. funnel events を足す。

候補:

- `pricing_view`
- `cta_click`
- `playground_request`
- `playground_success`
- `playground_quota_exhausted`
- `quickstart_copy`
- `openapi_import_click`
- `mcp_install_copy`
- `checkout_start`
- `dashboard_signin_success`

4. bot-included Cloudflare PV と real API usage を分ける。
   - Cloudflare raw PV は上限値。
   - conversion denominator は human-ish session / playground success / API key issued / paid usage で見る。

受入条件:

- `analytics/cf_daily.jsonl` が daily で増える。
- top paths / status / UA class が保存される。
- API `analytics_events` で Playground → pricing → key → usage の流れが追える。
- bot traffic を paid conversion の母数にしない。

---

### F. 課金事故とdeploy事故を潰す

対象:

- `entrypoint.sh`
- `scripts/schema_guard.py`
- `scripts/smoke_test.sh`
- `.github/workflows/deploy.yml`
- `.github/workflows/nightly-backup.yml`
- `src/jpintel_mcp/api/middleware/idempotency.py`
- `src/jpintel_mcp/api/deps.py`
- `src/jpintel_mcp/billing/stripe_usage.py`
- batch / export / evidence / DD 系課金route

実装内容:

1. 起動時 seed 検証

- seed を直接 `/data/jpintel.db` へ置かない。
- `${JPINTEL_DB}.new` に展開。
- `PRAGMA quick_check`
- `SELECT COUNT(*) FROM programs >= 10000`
- sha manifest
- 成功時だけ `mv` と `.seed_version` 更新。

2. `schema_guard.py` に prod row-count guard

prod では fatal:

- `programs < 10000`
- key tables が空
- `PRAGMA quick_check != ok`

3. deploy workflow 後 smoke

- `flyctl deploy` 後に本番 smoke。
- `programs total <= 0` は warn ではなく fail。
- deep health が `ok` 以外なら fail。

4. nightly backup fail-closed

- R2 secrets 欠落時に prod backup を成功扱いしない。
- backup manifest に sha / row count / schema migration max を残す。

5. high-cost route の idempotency / cost cap

必須header:

- `Idempotency-Key`
- `X-Cost-Cap-JPY`

条件:

- 同じ `Idempotency-Key` + 違う body は 409。
- idempotency cache unavailable は 503 non-metered。
- render/upload failure は usage_events 0。
- batch は `quantity=N` の単一usageか、一括transactionで整合。

受入テスト:

```bash
uv run pytest \
  tests/test_usage_billing_idempotency.py \
  tests/test_rate_limit.py \
  tests/test_anon_rate_limit.py \
  tests/test_self_cap.py \
  tests/test_programs_batch.py \
  tests/test_evidence_packet.py \
  tests/test_stripe_usage_crons.py \
  -q
```

---

### G. 公開コピーの約束を揃える

対象:

- `site/index.html`
- `site/pricing.html`
- `site/llms.txt`
- `docs/pricing.md`
- `docs/api-reference.md`
- `docs/getting-started.md`
- `site/qa/llm-evidence/`
- `site/integrations/openai-custom-gpt.html`

統一文言:

```text
jpcite は Evidence prefetch layer です。
長いPDF・複数の官公庁ページ・検索結果をLLMへ渡す前に、出典URL・取得時刻・known gaps・互換/排他ルール付きの小さい Evidence Packet を返します。
caller supplied baseline がある場合だけ、入力文脈量の削減見込みと break-even を返します。
外部LLMの請求額削減は保証しません。
```

禁止表現:

- Token Cost Shield
- 必ず安くなる
- LLM費用を削減保証
- 一次資料100%
- 必ず
- 完全
- 無制限

受入条件:

```bash
rg -n "Token Cost Shield|必ず安|削減保証|一次資料 100|一次資料100|完全に|無制限" site docs README.md
```

公開面で誇大表現が出ないこと。

---

## 5. トークン削減を定量的に扱う式

jpcite の課金単価:

```text
jpcite_cost_jpy_ex_tax = 3
```

caller が入力単価を渡す:

```text
input_token_price_jpy_per_1m = user supplied
```

損益分岐:

```text
break_even_avoided_tokens = ceil(3 / (input_token_price_jpy_per_1m / 1,000,000))
break_even_source_tokens_estimate = packet_tokens_estimate + break_even_avoided_tokens
```

入力文脈削減率:

```text
input_context_reduction_rate = max(0, source_tokens_estimate - packet_tokens_estimate) / source_tokens_estimate
```

AIが説明してよい形:

```text
この比較は、あなたが渡した元資料トークン数またはPDFページ数を基準にした入力文脈だけの参考値です。
出力tokens、reasoning tokens、cache、provider tool/search料金、為替、外部LLM側の請求仕様は含みません。
```

公式価格は変わるため、jpcite 側に固定しない。UI / docs は caller supplied price を使い、必要なら公式価格ページへのリンクだけ置く。

参考として、2026-05-03確認時点で主要providerは token / search / cache / batch の価格体系が分かれている。

- OpenAI API pricing: https://openai.com/api/pricing/
- Anthropic Claude pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing

---

## 6. OTHER CLI に渡す実行プロンプト

下をそのまま別CLIに渡せる。

```markdown
# OTHER CLI Prompt — jpcite User Value Loop 2026-05-03

あなたは /Users/shigetoumeda/jpcite を扱う別CLIです。

目的:
GPT / Claude / Cursor で日本の制度調査をしている人が、AI側から jpcite を発見し、3回以内に価値を確認し、課金しても得だと判断できる状態にする。

絶対ルール:
- LLM API を呼ばない。
- `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk` を production import しない。
- agg サイトを source_url にしない。
- robots.txt と Crawl-Delay を守る。
- ¥3/req 単一モデルを変えない。
- 新規SaaS UIを作らない。既存のトップ / docs / Playground / API / MCP を改善する。
- 既存 migration 番号を変えない。
- `_archive/` を触らない。
- commit / push / deploy / publish を勝手にしない。
- `git add .` 禁止。
- 作業前に必ず `git status --short --branch` を確認。
- 生成物や調査成果は原則 `analysis_wave18/` へ日付付きで出す。
- 公開面に内部情報、T番号、古いブランド、AutonoMath露出、Token Cost Shield、誇大な削減保証を出さない。

最初に読む:
- docs/_internal/jpcite_user_value_execution_plan_2026-05-03.md
- docs/_internal/token_reduction_effect_2026-05-02.md
- docs/_internal/worktree_cleanup_2026-05-02.md
- site/llms.txt
- site/playground.html
- src/jpintel_mcp/services/token_compression.py
- src/jpintel_mcp/services/evidence_packet.py
- src/jpintel_mcp/api/intelligence.py
- scripts/cron/precompute_refresh.py
- scripts/cron/cf_analytics_export.py

並び順:

1. API value signals
   - `input_context_reduction_rate`
   - `provider_billing_not_guaranteed`
   - `break_even_source_tokens_estimate`
   - `evidence_value`
   - 2軸の `agent_recommendation`
   - tests / OpenAPI / docs 更新

2. User funnel
   - top CTA を `/playground.html?flow=evidence3` へ寄せる
   - Playground の課金nudgeを匿名3回と合わせる
   - Getting Started / Pricing / API docs に3回検証の流れを置く

3. GEO / MCP distribution
   - `llms.txt` 先頭40行を use/do-not-use/first-call/install にする
   - `mcp-server.json` の壊れた `.dxt` link を修正
   - manifest を公開サイトか llms.txt から辿れるようにする
   - 89 tools drift を消す

4. Data foundation
   - source_id backfill dry/apply report
   - precompute P0 tables
   - JGrants readiness/upsert plan
   - JFC scaffold
   - PDF extraction inventory/small batch
   - empty_search alias queue

5. Measurement
   - analytics-cron comment/domain修正
   - Cloudflare export top paths/status/UA/country/referrer修正
   - funnel events追加

6. Billing/deploy safety
   - entrypoint seed guard
   - schema_guard row-count guard
   - deploy post-smoke hard gate
   - backup fail-closed
   - high-cost route idempotency + cost cap

完了ログ:
research/loops/EXECUTION_LOG.md に追記。

形式:

## 2026-05-03Txx:xx:xx+0900 — <短い題名>

- Changed/read: <paths>
- Data outputs: <paths>
- Safety: no LLM API, no aggregator source_url, no commit/push/deploy
- Verification: `<command>` -> <result>
- Remaining: <残り>
```

---

## 7. この計画で避ける失敗

- 「単なる補助金検索API」に見える失敗。
- 「LLM料金が必ず下がる」という破綻claim。
- botには見つかるが人間が試さない失敗。
- 匿名3回なのに10回成功後に課金CTAが出る失敗。
- MCP manifest / bundle link が壊れてAIクライアントに導入できない失敗。
- 大量データはあるが `source_id` / provenance / known gaps が弱く、AIが安心して引用できない失敗。
- 空DB seed /壊れたseed / smoke不足で本番deployが壊れる失敗。
- retry / batch / render失敗で二重課金する失敗。

---

## 8. 判断

このプロダクトの勝ち筋は「AIより賢い文章を書く」ことではない。

勝ち筋は、AIが苦手で、ユーザーが実務で困る部分をAPIで返すこと:

- どの制度が該当しそうか
- どの出典に基づくか
- いつ取得したか
- どこが未確認か
- どの制度と併用できない可能性があるか
- 長い資料を読ませる代わりに、どれくらい小さい根拠パケットで済むか
- その条件なら jpcite 1回分の ¥3 が入力文脈削減だけで見合う可能性があるか

この形にすれば、GPT / Claude / Cursor は jpcite を「回答生成の競合」ではなく「回答前に呼ぶ根拠レイヤー」として扱いやすくなる。
