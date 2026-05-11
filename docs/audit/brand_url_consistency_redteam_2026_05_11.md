# Brand / URL Consistency Red-Team Audit — 2026-05-11

Read-only audit; no code touched (memory `feedback_destruction_free_organization`「破壊なき整理整頓」遵守 — 修正は提案のみ). Scope: jpcite ブランド一貫性 + URL/endpoint 命名の Silicon Valley top-tier (Stripe / Vercel / Linear / Notion) 目線審査。

## Scope

- `site/*.html` 41 ファイル (top-level) + 12,575 nested (audiences / cities / cross / enforcement / programs / docs etc.)
- `site/.well-known/{mcp,ai-plugin,agents,security,trust}.json` 5 files
- `site/openapi.agent.json` + `site/openapi.agent.gpt30.json`
- `site/llms.txt` + `site/llms-full.txt` + `site/llms.en.txt` + `site/llms-full.en.txt`
- `site/sitemap*.xml` 11 files
- `site/mcp-server.json` + `site/mcp-server.full.json` + `site/server.json` (auxiliary)
- `site/docs/openapi/v1.json` (production OpenAPI; 220 paths)
- SOT: `CLAUDE.md`

## SOT 値 (CLAUDE.md より固定)

| 項目 | 正本値 |
|---|---|
| canonical web | `jpcite.com` |
| canonical API | `api.jpcite.com` |
| brand | jpcite (lowercase) |
| operator | Bookyou株式会社 (En: Bookyou Inc.) |
| 法人番号 | `8010001213708` |
| JCT (適格請求書発行事業者番号) | `T8010001213708` |
| 住所 | 東京都文京区小日向 2-22-1 (〒112-0006) |
| contact email | `info@bookyou.net` |
| PyPI canonical dist | `autonomath-mcp` (legacy retained) |
| PyPI alias meta-package | `jpcite` (real; `pypi-jpcite-meta/pyproject.toml` 存在確認) |
| API key prefix | `am_` (例: `X-API-Key: am_xxxx...`) |
| 価格 | ¥3/billable unit ex tax、税込 ¥3.30 |
| 匿名枠 | 3 リクエスト/IP/日 (JST 翌日 00:00 リセット) |
| legacy brand markers | 税務会計AI / AutonoMath / zeimu-kaikei.ai (許可場所: llms\*.txt / trust.json `previous_brands` / index.html JSON-LD `alternateName`+`sameAs`) |

---

## 7 軸 集計

| Axis | 評価 | 検出件数 | 一言 |
|---|---|---|---|
| A. canonical hostname | green | 1 dead PyPI link, 5 trailing-dot prose | 旧 `autonomath.ai` 0 件、`zeimu-kaikei.ai` は SEO bridge 許可域内 |
| B. brand 表記 | yellow | 10 件 `Jpcite` (PascalCase) + 4 `Bookyou Inc..` (double-period typo) | レアだが SV-tier では即修正レベル |
| C. operator 情報 | yellow | 2 件 `no-reply@jpcite.com` (mock or 実装?) + 4 住所 spacing 揺れ + 1 `query@parse.jpcite.com` (openapi default) | email 単一化未達 |
| D. URL endpoint 命名 | **red** | 21 kebab-case paths vs 76 snake_case (production 220 paths) + 33 `/v1/am/*` 旧 prefix が public 露出 | SV top-tier では一目で内部リファクタ未完了と見える |
| E. MCP tool / workflow 命名 | **red** | 33/34 operationId が camelCase、139/139 tool name が snake_case、両方を 1 行に混在記述 (llms.txt:36-39) | agent 側コードジェネレータで symbol 衝突を起こす |
| F. pricing 表記 | yellow | 6 variants × 価格、4 variants × anonymous 枠 | 表記揺れ multiple、ただし契約文言は OK |
| G. announce docs ↔ filename | green | 全 8 本 jpcite 命名整合、autonomath 言及は `autonomath-mcp` (PyPI 名) のみ | 言及 0/0/2/3/5/0/0/0 全て legitimate |

総合: **red 2 axis (D, E) / yellow 3 axis (B, C, F) / green 2 axis (A, G)**。

A/G は SV top-tier 比較で許容内。**D と E が SV top-tier 比較で恥ずかしいレベル** — Stripe / Vercel / Linear / Notion は public API path と SDK 関数命名で snake/kebab/camel 混在を許さない (Stripe 全 snake、Linear 全 kebab、Notion 全 snake、Vercel 全 kebab → どれも単一規則)。

---

## Axis A — canonical hostname (green)

### 検出

- `https://jpcite.com` 1,363 件 (HTML 1,120 + well-known/openapi/llms 243)
- `https://api.jpcite.com` 115 件 (HTML 63 + 上記 52) — split は web / API で適切
- 旧 `autonomath.ai`: **0 件** (active link, JSON-LD, redirect target 全てゼロ)
- 旧 `zeimu-kaikei.ai`: 9 件 — 全て legitimate SEO bridge context
  - `site/index.html:87, 110, 122, 123` (JSON-LD `alternateName` + `sameAs`)
  - `site/llms.txt:2`, `site/llms.en.txt:2`, `site/llms-full.txt:2`, `site/llms-full.en.txt:2`, `site/en/llms.txt:3` (brand history declaration)
  - `site/.well-known/trust.json:20` (`previous_brands` array)
- `https://api.jpcite.com/mcp` (MCP HTTP endpoint) consistent 全域
- sitemap.xml は 12,673 件全て `https://jpcite.com`

### 唯一の defect

- `site/index.html:111` の JSON-LD `sameAs` に `"https://pypi.org/project/jpcite/"` あり。これは `pypi-jpcite-meta/pyproject.toml` で実在する **meta-package** なので dead link ではない (確認済)。ただし `trust.json:23` の `pypi_distribution: "autonomath-mcp"` と並列に 2 PyPI 同居している事実は user-facing には明示されておらず、混乱要因の yellow flag が残る (Axis A としては green、Axis B/E にスピルオーバー)。

### Trailing-dot 文体差 (5 件)

文末に `https://jpcite.com.` のように "." がつく散文 5 箇所 — URL の終端を「文末ピリオド」と誤読される typography risk。SV top-tier の docs/marketing は文末 URL の後で改行か `</a>.` で trailing punctuation を URL から離す。
- `site/llms.txt:169`
- `site/llms.en.txt:19`
- `site/llms-full.en.txt:23226`
- `site/sitemap.xml:4` (XML comment)
- `site/openapi.agent.json:13583` + `openapi.agent.gpt30.json:12874` ("on jpcite.com." — schema description フィールド)

評価: SV bar では微差。green 維持。

---

## Axis B — brand 表記揺れ (yellow)

### 検出

- `jpcite` (lowercase, canonical): 1,959 件 (HTML) + 918 件 (well-known/openapi/llms) = 2,877+ 件
- `Jpcite` (PascalCase, 想定外): **10 件**
  - `site/openapi.agent.json:8644, 8669, 9202, 11643, 13494` (Pydantic auto-generated `title` フィールド — "Call Jpcite First For" / "No Llm Called By Jpcite" / "Use Jpcite Next" / "Web Search Performed By Jpcite" / "Jpcite Requests")
  - `site/openapi.agent.gpt30.json:8294, 8319, 8852, 11227, 12785` (同上 5 件、 gpt30 slim 版)
- `JPCite` / `JPCITE` / `jpcite` 揺れ大文字小文字: 0 件 (good)
- `Bookyou株式会社` 21,789 件、`Bookyou Inc.` 200 件 (en/ 配下 + trust.json + RSS) — context-dependent で正しい使い分け (ja=株式会社、en=Inc.)
- `BookYou` / `BOOKYOU` / `Bookyou Co.` / `bookyou株式会社` 揺れ: 0 件 (good)

### Defect

- **double-period typo**: `Bookyou Inc..` (period 2 個) が 4 ファイル × 4 行
  - `site/widget/jpcite.js:23`
  - `site/widget/autonomath.src.js:23`
  - `site/widget/autonomath.js:23`
  - `site/widget/autonomath.src.css:20`
  ファイル末尾は ".." だが JS comment、CSS comment 内。視覚汚染レベル。

- **Pydantic `title` PascalCase 漏れ**: 10 件の `Jpcite ...` 表記は Pydantic が `class JpciteRequests(BaseModel)` 等で `model.schema()` を呼んで `title` を自動生成した跡。SV top-tier の OpenAPI spec は title を手動で `"jpcite Requests"` (小文字維持) にする。lowercase ブランドポリシーの一貫性を最も外部 LLM (ChatGPT GPT Actions / Claude Tool) が読む場所で破っているのは red 寄り yellow。

- **PyPI 名前 2 重存在**: index.html の JSON-LD sameAs に `pypi.org/project/jpcite/` と `pypi.org/project/autonomath-mcp/` が並列。trust.json は autonomath-mcp 1 本のみ。ユーザーから見ると「どっちを install するの?」の問いに答える single source が存在しない。Axis B にスピル。

---

## Axis C — operator 情報 (yellow)

### 検出

- `info@bookyou.net` 13,718 件 — 圧倒的に統一
- `martin.donath@squidfunk.com` 91 件 — mkdocs-material の library author メタデータ、本筋に無関係 (green)
- `taku@chasen.org` 1 件 — pykakasi 由来、 同上 (green)
- `no-reply@jpcite.com` **2 件** — 想定: メール文例の差出人 mock
  - `site/alerts.html:406` (JP version preview)
  - `site/en/alerts.html:299` (EN version preview)
- `query@parse.jpcite.com` **1 件** — openapi v1.json:7003 の default value (cron-parse 用 placeholder)

### 法人番号 / JCT

- `T8010001213708` (JCT, T-prefix): 9,408 件
- `8010001213708` (法人番号, bare): 9,382 件
- 両方が CLAUDE.md SOT 値で、context-dependent に正しい使い分け (JCT 文脈は T 付き、法人番号文脈は bare)。trust.json は両方を別キーで持つ canonical 構造を示しており green。

### 住所表記

- `東京都文京区小日向2-22-1` (空白なし): 93 件
- `東京都文京区小日向 2-22-1` (1 空白あり): **4 件**
  - `site/tokushoho.html:215` (特商法表記の最重要箇所)
  - `site/tos.html:465`
  - `site/docs/compliance/tokushoho/index.html:2023, 2158`

SV top-tier では tokushoho/tos の住所 spacing 揺れは法務照査で必ず叩かれる項目。yellow。

### Email mock の判断

`no-reply@jpcite.com` 2 件は alerts.html のメール preview の `From:` フィールド。今後実装する transactional mail で実際に `no-reply@jpcite.com` を SPF/DKIM 立てるなら問題なし。立てない場合は `info@bookyou.net` などに置換すべき (memory: bookyou.net mail は xrea で `s374.xrea.com:587`、`no-reply@jpcite.com` は別 namespace 必要)。

---

## Axis D — URL endpoint 命名 (red)

### Production OpenAPI (`docs/openapi/v1.json`, 220 paths) 内 case 分布

```
snake_case path segment: 76 paths
kebab-case path segment: 21 paths
camelCase / PascalCase  : 0 paths
mixed in same path      : 0 paths
```

### kebab-case の侵入箇所 (production 21 件)

```
/v1/advisors/report-conversion
/v1/advisors/verify-houjin/{advisor_id}
/v1/advisors/{advisor_id}/dashboard-data
/v1/am/audit-log
/v1/am/data-freshness
/v1/billing/keys/from-checkout
/v1/case-studies/search
/v1/case-studies/{case_id}
/v1/compliance/stripe-checkout
/v1/court-decisions/by-statute
/v1/court-decisions/search
/v1/court-decisions/{unified_id}
/v1/enforcement-cases/details/search
/v1/enforcement-cases/search
/v1/enforcement-cases/{case_id}
/v1/laws/{unified_id}/related-programs
/v1/loan-programs/search
/v1/loan-programs/{loan_id}
/v1/me/billing-portal
/v1/me/rotate-key
/v1/widget/keys/from-checkout
```

snake-case では `/v1/tax_rulesets/search`、`/v1/invoice_registrants/search`、`/v1/funding_stack/check` のように複合名詞が一貫して `_` を使う。同じ「複合名詞 + /search」のパターンで `case-studies/search` vs `tax_rulesets/search` が同居しているのは **SV top-tier (Stripe / Linear / Notion / Vercel) では絶対に起きない** レベルの内部リファクタ未完了サイン。

### `/v1/am/*` legacy prefix の public 露出 (33 paths)

`am` = autonomath の 2 文字略 — production OpenAPI v1.json に **33 paths** 残存。public LLM agent から見て、`/v1/am/tax_rule` は意味不明 (am = morning? account-manager? AutonoMath? — context なし)。CLAUDE.md でも「user-visible strings は jpcite ブランドのみ」と縛っているため、`/v1/am/health/deep`, `/v1/am/tax_incentives`, `/v1/am/loans` などは旧 brand リーク。

### 評価

D 軸は SV top-tier 比較で **red**。修正提案:
1. 全 kebab-case path に snake_case alias を追加 (`/v1/case-studies/search` → `/v1/case_studies/search` を canonical、kebab は 301 alias)。リネームは public API なので 90 day deprecation window 必須。
2. `/v1/am/*` は `/v1/<domain>/*` への semantic rename (例: `/v1/am/tax_incentives` → `/v1/tax_incentives`)。両方を v1 で並走、`/v1/am/*` は `Deprecation: <date>` ヘッダ。

---

## Axis E — MCP tool / workflow 命名 (red)

### MCP tool 名前 (mcp-server.json, 139 tools)

- 全 139/139 が **snake_case** で 0 大文字混在 (good — single rule)
- `_am` suffix legacy 残存: **20 tools**
  - `dd_profile_am`, `enum_values_am`, `search_acceptance_stats_am`, `search_gx_programs_am`, `search_loans_am`, `check_enforcement_am`, `search_mutual_plans_am`, `get_law_article_am`, `apply_eligibility_chain_am`, `find_complementary_programs_am`, `simulate_application_am`, `track_amendment_lineage_am`, `program_active_periods_am`, `get_houjin_360_am`, `check_funding_stack_am`, `deep_health_am`, `list_static_resources_am`, `get_static_resource_am`, `list_example_profiles_am`, `get_example_profile_am`

`_am` は autonomath の 2 文字略。`/v1/am/*` REST path と同根の legacy リーク。user-facing 露出。

### OpenAPI operationId (openapi.agent.json, 34 ops)

```
camelCase   : 33  (prefetchIntelligence / queryEvidencePacket / searchPrograms /
                   prescreenPrograms / getProgram / previewCost / getUsageStatus /
                   searchLaws / getLaw / getLawArticle / ...)
snake_case  :  1  (match_advisors_v1_advisors_match_get — Pydantic auto-gen mode)
```

### 致命的 inconsistency — server.json + mcp.json + llms.txt の workflow sequence

```jsonc
// server.json:50-60 (and .well-known/mcp.json:65-80)
"workflows": [
  {
    "id": "company_folder_intake",
    "first_paid_call": "createCompanyPublicBaseline",  // camelCase
    "sequence": [
      "previewCost",                  // camelCase  (実体: REST /v1/cost/preview / op_id previewCost)
      "createCompanyPublicBaseline",  // camelCase  (実体: REST /v1/artifacts/company_public_baseline)
      "createCompanyFolderBrief",     // camelCase  (実体: REST /v1/artifacts/company_folder_brief)
      "queryEvidencePacket"           // camelCase  (実体: REST /v1/evidence/packets/query)
    ]
  }
]
```

```text
// llms.txt:36-39 (顧問先ワークフロー説明)
- 会社フォルダ作成: `previewCost` -> `company_public_baseline` -> `company_folder_brief` -> 必要なら `evidence/packets/query`。
- 月次顧問先レビュー: `previewCost` -> `company_public_baseline` -> `prescreenPrograms` -> `evidence/packets/query`。
- AI回答前の根拠取得: `getUsageStatus` -> `previewCost` -> `evidence/packets/query` -> 必要なら `/v1/citations/verify`。
```

→ **camelCase identifier (operationId) と snake_case REST 名 (company_public_baseline) と path-relative (evidence/packets/query) を同じ 1 行に混ぜている**。

agent コードジェネレータ (Stainless / Speakeasy 等) は operationId を SDK 関数名にする。Stripe / Plaid / Twilio はすべて operationId を「path から導出した snake_case (Python SDK) または camelCase (TS SDK)」に 100% 統一しているため、同じ tool 群を Python SDK / TS SDK でそれぞれ別命名で公開できる。jpcite の現状は llms.txt 内で `previewCost`(camelCase, op_id)、`company_public_baseline`(snake_case, path segment)、`prescreenPrograms`(camelCase, op_id) を混在記述しており、agent LLM がどれを「実在 tool name」と判断するか確率的に揺れる。

### Workflow sequence 内 1 件の混入

`server.json:75` の `counterparty_dd_and_audit_prep` workflow sequence 内に `match_advisors_v1_advisors_match_get` (snake-case + 異常に長い auto-gen 名)。他は全 camelCase。これは Pydantic + FastAPI auto-gen の typical 副作用で、SV top-tier ではビルド時に `operation_id_generator` を override して手動命名する。

### 評価

E 軸は SV top-tier 比較で **red**。直接の悪影響:
- agent 開発者が `previewCost()` を呼ぼうとして「該当 tool が見つからない」と詰む (実体 MCP tool 名は snake_case `preview_cost` 想定だが、実は MCP には preview_cost 自体が無く、REST endpoint `/v1/cost/preview` だけ)
- llms.txt の混在記述で Claude / GPT-4o が wrong tool name を hallucinate しやすい

---

## Axis F — pricing 表記 (yellow)

### ¥3/single-request

| variant | 件数 |
|---|---:|
| `¥3/billable unit` | 295 |
| `¥3/req` | 50 |
| `¥3 per billable unit` | 23 |
| `¥3 per request` | 3 |
| `税込 ¥3.30` | 140 |
| `¥3.30 tax(-incl/-include)` | 39 |
| `(¥3/billable_unit, tax-incl ¥3.30)` (underscore form, ai-plugin.json) | 1 |

canonical (CLAUDE.md) は `¥3/billable unit` + `税込 ¥3.30`、それ以外は SEO/marketing context で軽く許容。`¥3/req` は短縮形として llms.txt + announce で使用 → SV bar では「short-form は許容」が普通なので yellow 維持。

### 匿名枠

| variant | 件数 |
|---|---:|
| `3 リクエスト/日` | 11,479 |
| `3 req/日` | 113 |
| `3 req/day` | 73 |
| `3 req/IP/日` | 38 |
| `3 requests/day` | 27 |

canonical は memory より `3 req/day per IP` (mcp.json:25) または `3 リクエスト/IP/日`。SV top-tier は user-facing marketing で「N requests per IP per day」固定が一般的。jpcite は IP 軸の明示が件数比で薄い (3 リクエスト/日 11,479 件中 IP 明示は ~38 件のみ → 大半は「3 リクエスト/日」だけで IP 軸が落ちている)。これは課金紛争のリスク (1 user × N IP で N × 3 req 享受可能、を明示しないと景表法リスク)。yellow → 場合により orange。

### API key prefix 混在

- **defect**: `site/.well-known/ai-plugin.json:6, 9` で `"X-API-Key: sk_..."` と書いている
- 他全箇所 (llms-full.txt × 11、docs/api-reference/index.html × 5、qa/llm-evidence/context-savings.html × 2 等) は **`am_...`**

Stripe-flavor の `sk_live_xxx` 形を ai-plugin.json が誤模倣している。ChatGPT GPT Actions が **ai-plugin.json を最優先 read する** ため、SV top-tier ではこのファイルだけ wrong prefix なのは最も外部から見える recall miss。axis F red 寄り yellow (canonical 価格表現自体は OK、API key prefix だけ defect)。

---

## Axis G — announce docs ↔ filename (green)

`docs/announce/` 直下の 8 本 (Jpcite-branded リリース寄稿) 全てで:
- ファイル名 jpcite 含む = body 内 jpcite mention ≥ 9 件
- legacy `zeimu-kaikei.ai` / `税務会計AI` 言及 = 0 件 (全 8 本)
- `autonomath` 言及 = 0-5 件、全て `pip install autonomath-mcp` / `uvx autonomath-mcp` / `github.com/.../autonomath-mcp` 等の **PyPI distribution name 文脈のみ** (CLAUDE.md 許可域)

| file | jpcite | autonomath | legacy zeimu/税務会計AI |
|---|---:|---:|---:|
| gyosei_kaiho_jpcite.md | 12 | 0 | 0 |
| ma_online_jpcite.md | 11 | 0 | 0 |
| note_jpcite_mcp.md | 11 | 2 | 0 |
| prtimes_jpcite_release.md | 11 | 3 | 0 |
| shindanshi_kaiho_jpcite.md | 9 | 0 | 0 |
| tkc_journal_jpcite.md | 14 | 0 | 0 |
| zeirishi_shimbun_jpcite.md | 10 | 0 | 0 |
| zenn_jpcite_mcp.md | 12 | 5 | 0 |

全 8 本 green。

---

## 即修正候補 top-5 (path + line, 提案のみ)

優先度 = SV top-tier 目線で 1 秒で見つかる defect + 修正コスト最小。

### #1. ai-plugin.json の API key prefix を `sk_` → `am_` (red、外部 LLM 最優先 read 箇所)

- `site/.well-known/ai-plugin.json:6` (`description_for_model` 内)
- `site/.well-known/ai-plugin.json:9` (`auth.instructions` 内)
- 修正: `"X-API-Key: sk_..."` → `"X-API-Key: am_..."` 2 箇所
- 影響: ChatGPT GPT Actions / Plugin Store が読む単一 manifest を canonical prefix に揃える

### #2. openapi.agent\*.json の `Jpcite` PascalCase → `jpcite` lowercase (yellow → 露出量大)

- `site/openapi.agent.json:8644, 8669, 9202, 11643, 13494` (5 件)
- `site/openapi.agent.gpt30.json:8294, 8319, 8852, 11227, 12785` (5 件)
- 修正: Pydantic model class 名側を変更するか、`export_openapi.py` で `title` を手動 lowercase override
- 影響: 外部 LLM が `title: "Jpcite Requests"` を読んで PascalCase が legitimate と誤学習するのを止める

### #3. widget/*.js + .css の `Bookyou Inc..` double-period 修正 (yellow, typo)

- `site/widget/jpcite.js:23`
- `site/widget/autonomath.js:23` + `autonomath.src.js:23`
- `site/widget/autonomath.src.css:20`
- 修正: `Bookyou Inc..` → `Bookyou Inc.` (period 1 個)
- 影響: copyright comment の typo を消す、source-view される widget で目立つ

### #4. tokushoho.html / tos.html 住所 spacing 統一 (yellow, 法務照査リスク)

- `site/tokushoho.html:215` (`東京都文京区小日向 2-22-1` → `東京都文京区小日向2-22-1`)
- `site/tos.html:465` 同上
- `site/docs/compliance/tokushoho/index.html:2023, 2158` 同上
- 修正: 4 箇所の半角空白除去 (trust.json:11 を canonical: `"〒112-0006 東京都文京区小日向2-22-1"`)
- 影響: 特商法表記の法務上 single SOT に揃える

### #5. server.json + mcp.json + llms.txt の workflow sequence 命名統一 (red、長期投資)

- `site/server.json:54-57, 64-66, 73-75` (camelCase workflow steps)
- `site/.well-known/mcp.json:71-74, 79-82, 87-89` (同上)
- `site/llms.txt:36-39, 123, 125, 235` (camelCase + snake_case mixed 行)
- 修正案: workflow step を全て canonical operationId (camelCase) または canonical tool name (snake_case) のどちらか一方に統一し、もう一方は alias 表で別途列挙。最低限、同じ 1 行で混在を解消する
- 影響: agent SDK 生成時の symbol 衝突防止 + LLM hallucination リスク削減 (これが最も SV bar 越えに効く投資)

---

## SV top-tier 企業比較

| 項目 | Stripe | Linear | Notion | Vercel | jpcite 現状 |
|---|---|---|---|---|---|
| public API path case | snake_case 100% | kebab-case 100% | snake_case 100% | kebab-case 100% | snake 76 / kebab 21 (red) |
| operationId case | snake_case (Python SDK) | camelCase (TS SDK) | snake_case | camelCase | camelCase 33 / snake 1 (yellow) |
| MCP / SDK tool name case | snake_case 100% | camelCase 100% | n/a | camelCase 100% | snake 138 / `_am` legacy 20 |
| brand case | "Stripe" 統一 | "Linear" 統一 | "Notion" 統一 | "Vercel" 統一 | jpcite 統一 + `Jpcite` PascalCase 10 件 (yellow) |
| legacy domain 露出 | history page のみ | n/a | 0 | n/a | `zeimu-kaikei.ai` 9 件 (全て legitimate bridge) |
| pricing 表記 | "$0.029 per..." 統一 | tier 課金で N/A | tier 課金で N/A | "$X.XX/seat" 統一 | ¥3/billable unit 主体 + 6 variants (yellow) |
| API key prefix manifest | docs 単一 SOT (`sk_test_` / `sk_live_`) | n/a | n/a | n/a | ai-plugin.json で `sk_`、他は `am_` (red、SOT 分裂) |
| 特商法/法務住所表記 | n/a (海外) | n/a | n/a | n/a | 5 形式中 1 件 spacing 揺れ (yellow) |

### 距離評価

- **green axis (A, G)**: SV top-tier 同等。canonical hostname と announce docs ブランド整合は launch-grade。
- **yellow axis (B, C, F)**: SV top-tier より 1 段下。ただし即修正可能な範囲 (合計 30 行未満)。
- **red axis (D, E)**: SV top-tier の launch-grade を満たさない。public API surface の case 揺れと operationId 混在は、外部の Stripe Apps / Linear Connect / Notion API レビュアーが「内部リファクタが未完了」とラベルする典型サイン。修正コストは大 (path rename = 90 day deprecation cycle, operationId 統一 = export_openapi.py の op_id generator 書き換え)。

### Action 推奨優先度

1. **緊急 (24h 以内)**: 上記 top-5 のうち #1 (ai-plugin.json sk_ → am_)、#3 (widget double-period)、#4 (住所 spacing)
2. **短期 (1 週間)**: top-5 #2 (Pydantic title lowercase override + export_openapi.py 拡張)
3. **中期 (1 ヶ月)**: top-5 #5 (workflow step 命名統一) + Axis D `/v1/am/*` deprecation plan 起案
4. **長期 (3 ヶ月)**: Axis D kebab → snake 大移行 (90 day deprecation window, 301 alias)

memory 制約 (`feedback_destruction_free_organization`、`feedback_iterative_review.md`) より、上記は修正提案のみ。実反映は別 session でユーザー指示後。

## 参考: 主要数値

- 検出 violation 総件数 (axis B/C/D/E/F 合計): ~110 件 (大半 D/E に集中、 D=54 件 + E=20+ 件)
- 修正候補 top-5 で覆える件数: ~30 件 (3 割) + path/operationId 全鎖を含めると ~85 件 (8 割)
- 全 0 件 (green) で完了している axis: 2 (A 厳密、G 完全)
