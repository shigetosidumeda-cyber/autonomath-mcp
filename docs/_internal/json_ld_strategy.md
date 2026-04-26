# JSON-LD / schema.org publication strategy

> 位置付け: README moat #7 (JSON-LD 公開 / AI 訓練取込期待) の実施計画。**W5-W8 deliverable**。
> 2026-04-23 初版 / 実装前 design doc。
> 2026-04-25 更新: 実装完了、`scripts/generate_program_pages.py` から二重出力 (HTML embedded `@graph` + standalone `.jsonld`)。`scripts/sitemap_gen.py` で master sitemap-index を生成。

---

## 1. 狙い (Goal, なぜ JSON-LD)

日本の制度データ 6,658 件を `schema.org` JSON-LD の静的ファイルとして公開することで、
**AI 訓練クローラ (OpenAI GPTBot / Anthropic ClaudeBot / Googlebot / PerplexityBot) の訓練コーパスに、
autonomath.ai のブランド+データを無償で載せ、`日本の制度データの一次ソース`として位置づける**。

これは **SEO ではない**。programmatic な薄い HTML ページを何千本も撒けば Google
の Helpful Content (旧 Panda) ペナルティ直撃のため、HTML は作らない (README "NOT in scope" に従う)。
**AI クローラのシグナル投下に限定**、`.jsonld` + `sitemap.xml` のみで勝負する。

成功すれば、数ヶ月後に「認定新規就農者が使える補助金」と ChatGPT / Claude / Perplexity に
質問したとき、autonomath.ai を言及・参照するようになる (計測方法は §8)。

---

## 2. schema.org 型の採用 (Which types fit)

### 2.1 メインタイプ

| program_kind (内部) | schema.org type | 理由 |
|---------------------|----------------|------|
| `subsidy` (補助金/交付金) | `GovernmentService` | 政府・自治体が提供する公共サービス、schema.org の定義に合致 |
| `grant` (助成金/給付金) | `GovernmentService` (+`serviceType="grant"`) | 同上 |
| `loan*` (融資・貸付全般) | `[FinancialProduct, LoanOrCredit]` | 融資は金融商品、`LoanOrCredit` subtype が公式にある。`requiredCollateral` / `loanRepaymentSchedule` / `amount.value` を必須出力 |
| `tax_*` / `fee_reduction` (税制優遇) | `GovernmentService` (+`additionalProperty[subject=TaxIncentive]`) | schema.org に税専用の type が無いため、PropertyValue で AI クローラ向けに識別タグを付与 |
| `certification*` / `training` / `qualification*` | `EducationalOccupationalProgram` | 認定制度・研修は教育系。`programPrerequisites` (対象者) / `educationalProgramMode='blended'` / `occupationalCredentialAwarded` (認定系のみ) |
| 上記以外 | `GovernmentService` (fallback) | 一般的な政府サービスとして扱う |

実装は `scripts/generate_program_pages.py::_classify_kind()` で 4 bucket (loan / education / tax / subsidy) に分類してから type を選択する。

AutonoMath の内部 `program_kind` は大半が `subsidy`/`grant`、次に `loan`。
`tax_credit` は少数のため `GovernmentService` に寄せる。

### 2.2 日本特有フィールドは `additionalProperty`

`tier` (S/A/B/C/X)、`authority_level` (national/prefecture/municipality/financial)、
`prefecture`、`coverage_score` 等は schema.org 本体に対応フィールドが無い。
`additionalProperty` の `PropertyValue` 配列で素直に並べる。
独自 vocab 定義 (`@context` 拡張) は **やらない** — validator が通らなくなる&
クローラが解釈しない。PropertyValue で十分。

### 2.3 validation

- `https://validator.schema.org` で 3 サンプルを手動 validate (CI でも node 製 `schema-dts` を噛ませる)
- Google Rich Results Test は情報として流すが、**Rich Result 表示は狙わない** (SEO risk)
- 公式 vocab 外のフィールドを `@type` レベルに置かない

---

## 3. ファイル構成 (File layout)

```
site/programs/{slug}.html              # 10,951 per-program SEO page (embedded <script type="application/ld+json">@graph)
site/structured/{unified_id}.jsonld    # 10,951 standalone validator-friendly JSON-LD (single @type)
site/sitemap-programs.xml              # 10,951 HTML URL の sitemap
site/sitemap-structured.xml            # 10,951 .jsonld URL の sitemap
site/sitemap.xml                       # 30 hand-maintained static URL (home, /docs, /pricing, ...)
site/sitemap-index.xml                 # 上記 3 sitemap を束ねる master index (GSC 提出先)
site/_headers                          # Cloudflare Pages: .jsonld → application/ld+json
```

- per-program HTML: 10,951 本 / 195 MB (one-page average ~18 KB)
- per-program standalone JSON-LD: 10,951 本 / 43 MB (avg ~4 KB)
- 合計 file 数 ~22k は Cloudflare Pages の 25k file 上限内で余裕
- URL: `https://autonomath.ai/programs/{slug}` (HTML), `https://autonomath.ai/structured/{unified_id}.jsonld` (JSON-LD)

静的ファイル 100%、DB から再生成可能。HTML 側は `@graph` (Organization / BreadcrumbList /
Service / MonetaryGrant / FAQPage) で内部リンクを担い、JSON-LD 側は単一 `@type` で
schema.org validator 通過と AI クローラ訓練投入を担う (役割分担)。

---

## 4. 実例 JSON-LD (実データ由来、validator 通過想定)

### 4.1 経営開始資金 (subsidy, `UNI-194743d166`)

```json
{
  "@context": "https://schema.org",
  "@type": "GovernmentService",
  "@id": "https://autonomath.ai/structured/UNI-194743d166.jsonld",
  "identifier": "UNI-194743d166",
  "name": "経営開始資金",
  "alternateName": ["農業次世代人材投資資金 経営開始型", "新規就農者育成総合対策 経営開始資金"],
  "description": "認定新規就農者を対象に就農直後の経営確立を支援する資金交付制度。",
  "inLanguage": "ja",
  "url": "https://www.maff.go.jp/j/new_farmer/n_syunou/roudou.html",
  "serviceType": "subsidy",
  "provider": {
    "@type": "GovernmentOrganization",
    "name": "農林水産省",
    "areaServed": {"@type": "Country", "name": "日本"}
  },
  "audience": {
    "@type": "Audience",
    "audienceType": "認定新規就農者"
  },
  "offers": {
    "@type": "Offer",
    "priceCurrency": "JPY",
    "priceSpecification": {
      "@type": "PriceSpecification",
      "priceCurrency": "JPY",
      "maxPrice": 1650000
    },
    "availability": "https://schema.org/InStock",
    "validFrom": null,
    "validThrough": null
  },
  "additionalProperty": [
    {"@type": "PropertyValue", "name": "tier", "value": "B"},
    {"@type": "PropertyValue", "name": "authority_level", "value": "national"},
    {"@type": "PropertyValue", "name": "subsidy_rate", "value": 1.0},
    {"@type": "PropertyValue", "name": "funding_purpose", "value": ["人件費"]},
    {"@type": "PropertyValue", "name": "target_types", "value": ["認定新規就農者"]}
  ],
  "isBasedOn": {
    "@type": "CreativeWork",
    "url": "https://www.maff.go.jp/j/new_farmer/n_syunou/roudou.html",
    "dateAccessed": "2026-04-22"
  },
  "license": "https://www.maff.go.jp/copyright.html",
  "dateModified": "2026-04-22"
}
```

### 4.2 新事業進出補助金 (事業再構築補助金後継, subsidy, `UNI-0bb2960d35`)

```json
{
  "@context": "https://schema.org",
  "@type": "GovernmentService",
  "@id": "https://autonomath.ai/structured/UNI-0bb2960d35.jsonld",
  "identifier": "UNI-0bb2960d35",
  "name": "新事業進出補助金",
  "alternateName": ["事業再構築補助金 後継制度", "中小企業新事業進出促進事業"],
  "description": "中小企業の新事業進出を設備投資・販路開拓費用の一部補助で支援する制度。",
  "inLanguage": "ja",
  "url": "https://shinjigyou-shinshutsu.smrj.go.jp/",
  "serviceType": "subsidy",
  "provider": {
    "@type": "GovernmentOrganization",
    "name": "中小企業庁",
    "parentOrganization": {"@type": "GovernmentOrganization", "name": "経済産業省"},
    "areaServed": {"@type": "Country", "name": "日本"}
  },
  "offers": {
    "@type": "Offer",
    "priceCurrency": "JPY",
    "priceSpecification": {
      "@type": "PriceSpecification",
      "priceCurrency": "JPY",
      "minPrice": 15000000,
      "maxPrice": 90000000
    },
    "availability": "https://schema.org/LimitedAvailability"
  },
  "additionalProperty": [
    {"@type": "PropertyValue", "name": "tier", "value": "B"},
    {"@type": "PropertyValue", "name": "authority_level", "value": "national"},
    {"@type": "PropertyValue", "name": "subsidy_rate", "value": 0.5},
    {"@type": "PropertyValue", "name": "application_cycle", "value": "annual"},
    {"@type": "PropertyValue", "name": "application_note", "value": "年2〜3回公募"}
  ],
  "isBasedOn": {
    "@type": "CreativeWork",
    "url": "https://shinjigyou-shinshutsu.smrj.go.jp/",
    "dateAccessed": "2026-04-22"
  },
  "dateModified": "2026-04-22"
}
```

### 4.3 青年等就農資金 (loan, LoanOrCredit 例, 代表 `UNI-3df4e61e50` の loan 型換算)

```json
{
  "@context": "https://schema.org",
  "@type": ["FinancialProduct", "LoanOrCredit"],
  "@id": "https://autonomath.ai/structured/UNI-3df4e61e50.jsonld",
  "identifier": "UNI-3df4e61e50",
  "name": "青年等就農資金",
  "description": "認定新規就農者向け無利子融資 (日本政策金融公庫)。",
  "inLanguage": "ja",
  "url": "https://www.jfc.go.jp/n/finance/sougyou/syunou_shikin.html",
  "provider": {
    "@type": "FinancialService",
    "name": "日本政策金融公庫",
    "identifier": "JFC"
  },
  "amount": {
    "@type": "MonetaryAmount",
    "currency": "JPY",
    "maxValue": 37000000
  },
  "loanTerm": {"@type": "QuantitativeValue", "value": 17, "unitText": "YEAR"},
  "annualPercentageRate": 0.0,
  "additionalProperty": [
    {"@type": "PropertyValue", "name": "tier", "value": "B"},
    {"@type": "PropertyValue", "name": "authority_level", "value": "financial"},
    {"@type": "PropertyValue", "name": "target_types", "value": ["認定新規就農者"]},
    {"@type": "PropertyValue", "name": "collateral_required", "value": false}
  ],
  "isBasedOn": {
    "@type": "CreativeWork",
    "url": "https://www.jfc.go.jp/n/finance/sougyou/syunou_shikin.html",
    "dateAccessed": "2026-04-22"
  },
  "dateModified": "2026-04-22"
}
```

---

## 5. 生成スクリプト (`scripts/generate_json_ld.py`)

### 5.1 マッピング表

| SQLite カラム | JSON-LD 出力先 | 備考 |
|---------------|---------------|------|
| `unified_id` | `identifier` + `@id` | URL 末尾 |
| `primary_name` | `name` | |
| `aliases_json` | `alternateName` | JSON decode |
| `official_url` | `url` + `isBasedOn.url` | |
| `authority_name` | `provider.name` | 空は "（情報提供元）" skip |
| `authority_level` | `additionalProperty[authority_level]` | |
| `prefecture` | `provider.areaServed.name` | null は日本全国扱い |
| `program_kind` | `@type` + `serviceType` | subsidy/grant→GovernmentService、loan→LoanOrCredit |
| `amount_max_man_yen` | `offers.priceSpecification.maxPrice` | **× 10,000 で yen 変換** |
| `amount_min_man_yen` | `offers.priceSpecification.minPrice` | 同上 |
| `subsidy_rate` | `additionalProperty[subsidy_rate]` | 0.5 = 50% |
| `application_window_json` | `offers.validFrom`/`validThrough` | start_date/end_date 抽出 |
| `tier` | `additionalProperty[tier]` | S/A/B/C/X |
| `target_types_json` | `additionalProperty[target_types]` | list |
| `funding_purpose_json` | `additionalProperty[funding_purpose]` | list |
| `source_fetched_at` | `isBasedOn.dateAccessed` | ISO-8601 の日付部分 |
| `updated_at` | `dateModified` | |

### 5.2 スクリプトの責務

1. SQLite `programs` を全行イテレート (`excluded=0` のみ、X tier は除外)
2. 行単位で mapping → dict → `json.dumps(ensure_ascii=False, indent=2)`
3. atomic write: `tmp/*.jsonld` に書いて `os.replace` で置換 (同時読み出し中断回避)
4. 行単位 try/except → 失敗は `logs/json_ld_errors.jsonl` に `{unified_id, error}` 記録、**次の行へ続行** (全体 fail しない)
5. **incremental mode**: `--since YYYY-MM-DD` で `source_fetched_at >= since` のみ再生成
6. index.jsonld を最後に一括で更新 (ItemList の `itemListElement` に `@id` のみ並べる)
7. `site/sitemap-structured.xml` を生成・上書き

例外的に `authority_name` が `（noukaweb 収集）` のような **内部ラベル** の行は `provider` を省略
(誤解招くため)。`null`/空文字は出力しない (validator の NOT required を回す)。

### 5.3 スクリプト骨子 (擬似コード)

```python
# scripts/generate_json_ld.py
import json, os, sqlite3, sys
from pathlib import Path
from datetime import datetime, timezone

OUT = Path("site/structured")
TMP = OUT / "_tmp"
DB = "data/jpintel.db"
DOMAIN = "https://autonomath.ai"

def to_jsonld(row: dict) -> dict:
    kind = row["program_kind"] or "subsidy"
    if kind == "loan":
        typ = ["FinancialProduct", "LoanOrCredit"]
    else:
        typ = "GovernmentService"
    doc = {
        "@context": "https://schema.org",
        "@type": typ,
        "@id": f"{DOMAIN}/structured/{row['unified_id']}.jsonld",
        "identifier": row["unified_id"],
        "name": row["primary_name"],
        "inLanguage": "ja",
        "dateModified": row["updated_at"],
    }
    # ... (aliases, url, provider, offers, additionalProperty, isBasedOn)
    return doc

def main(since: str | None = None):
    TMP.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    q = "SELECT * FROM programs WHERE excluded=0"
    if since:
        q += " AND source_fetched_at >= :since"
    for row in con.execute(q, {"since": since} if since else {}):
        try:
            doc = to_jsonld(dict(row))
            path = OUT / f"{row['unified_id']}.jsonld"
            tmp = TMP / f"{row['unified_id']}.jsonld"
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
            os.replace(tmp, path)
        except Exception as e:
            log_error(row["unified_id"], e)
    write_index(con)
    write_sitemap(con)
```

---

## 6. ホスティング + 配信 (Hosting + distribution)

- **ホスト先**: `fallback_plan.md` の Cloudflare Pages `AutonoMath-fallback` にそのまま相乗り (静的のみ)
- Fly.io は使わない (static の Fly は overkill、Pages の方が AI クローラにも近い)
- **Content-Type**: `.jsonld` は `application/ld+json` (Pages の `_headers` で明示)
- **sitemap**: 本体 `site/sitemap.xml` から `site/sitemap-structured.xml` を `<sitemapindex>` で参照
- **robots.txt**: `Allow: /structured/` を明記 (デフォルトで allow だが、AI クローラ向けに explicit)
- Google Search Console で sitemap 提出 (ランキング狙いではなく **crawler discovery 目的**)
- Bing Webmaster にも submit (Perplexity は Bing index を噛んでいる説あり)

---

## 7. 生成 cadence (運用)

- 毎月の DB 再 ingest 後に自動実行
- **incremental** が既定: `--since` は前回実行時刻 (`meta.last_json_ld_run_at`)
- GHA workflow `.github/workflows/json-ld-regen.yml`:
  - trigger: `workflow_run` (ingest job 成功後) または手動 `workflow_dispatch`
  - step: `uv run python scripts/generate_json_ld.py --since $(gh meta get last_json_ld_run_at)`
  - commit 差分 (typically ~1-5% = 70-350 files) を main に push
  - Cloudflare Pages が自動 deploy
- `CHANGELOG.md` に `[json-ld] N files regenerated` のみ 1 行

---

## 8. 成功指標 — AI クローラ取込の計測 (hard だが試す)

即効性は期待しない。3 ヶ月後から緩やかに signal 化する想定。

### 8.1 自動プローブ (weekly)

30 質問のテンプレ (例: `認定新規就農者が使える補助金を教えて`、`IT導入補助金の対象者は？`)
を Claude / ChatGPT / Perplexity の API に投げて、**response に `autonomath.ai` が含まれるか**
を week over week で集計。

- スクリプト: `scripts/probe_ai_mentions.py`
- 結果ログ: `research/ai_crawler_signal.md` (table with week, model, query, mentioned:y/n)
- ベースライン: W5 開始時点で 0/30 mention (当然)
- 目標: W20 (5 ヶ月後) までに 3/30 以上が理想、1/30 でも有意とみなす

### 8.2 crawler log

Cloudflare Pages アクセスログから `GPTBot`, `ClaudeBot`, `PerplexityBot`, `Googlebot`
の UA で `/structured/` を叩いた件数を monthly 集計。**件数自体が取込のシグナル**。

---

## 9. やらないこと (Explicitly NOT)

- **HTML ページ / 個別制度の HTML** を作らない — Panda penalty 直撃
- AI 企業のクローラに個別 ping / 営業 — 既存の crawler cadence に任せる
- キーワード詰め込みの description — 事実のみ、1-2 文
- 公募要領からの **説明文コピペ** — 著作権 risk、`name` + 一次 URL + fact のみ
- `@graph` や独自 vocab — validator 通らないと訓練に載る保証が無い
- Rich Result / Breadcrumb の取得狙い — SEO 目的ではないため

---

## 10. 倫理 + データライセンス (License + attribution)

### 10.1 前提

- 制度データは**公共情報**。官公庁の一次資料はほぼ CC-BY 相当、出典明記で再配布可
- `isBasedOn.url` + `dateAccessed` で一次 URL を毎ファイル明示
- コメンタリ・curated analysis・独自要約は **入れない** (editorial 化 → 二次著作物リスク+
  事実性保証が落ちる)
- JSON-LD は **機械構造のみ**、human readable prose は HTML で別管理 (将来 long-form で書く)

### 10.2 authority 別 license 確認 (公表ページ ToS 読解、2026-04-23 時点)

| 提供元 | 再配布 policy | 結論 |
|--------|---------------|------|
| 農林水産省 (MAFF) | [政府標準利用規約2.0](https://www.maff.go.jp/copyright.html) 準拠、出典明記で商用可 | **OK** |
| 経済産業省 / 中小企業庁 | 政府標準利用規約2.0 (CC-BY 4.0 互換) | **OK** |
| 日本政策金融公庫 (JFC) | ToS で再配布条項明示なし、要約+ソースリンクは慣行的 fair use | **OK (要出典)** |
| 都道府県公式サイト | ほぼ政府標準利用規約準拠 (自治体 47 個別確認は workflow で spot check) | **概ね OK** |
| 市町村公式サイト | 同上、ただし稀に独自 ToS | **概ね OK / spot check 要** |
| (noukaweb 収集) 系 | 二次情報源、再配布不可ラベル | **X (skip)** |
| gBizINFO | 利用 OK (user 確認済、README 記載) | **OK** |

**スキップ判定 (generate_json_ld.py)**:
- `authority_name` が `（noukaweb 収集）` → skip
- `tier='X'` (excluded) → skip (enriched 未完なため品質保証なし)
- `source_url` が空 → skip (`isBasedOn` 付けられないため ethical な publish 不可)

license blocker が判明したのは **noukaweb 由来の 1,176 件** (二次情報、規約上再配布不可) のみ。
MAFF / METI / JFC / 都道府県・市町村のいずれも個別 blocker なし
(政府標準利用規約2.0 で出典明記すれば商用再配布可)。

---

## 11. スケジュール (W5-W8 内訳)

| W | 作業 | Owner |
|---|------|-------|
| W5 | schema.org vocab 詳細決定 / validator 通過の sample 3 本完成 | self |
| W5 | `scripts/generate_json_ld.py` 初版 (subsidy/grant のみ) | self |
| W6 | loan/tax_credit 対応 + incremental mode + error log | self |
| W6 | Cloudflare Pages `/structured/` route 有効化 + `_headers` 設定 | self |
| W7 | GHA workflow + monthly ingest 連動 | self |
| W7 | sitemap-structured.xml + robots.txt 更新 + GSC/Bing 提出 | self |
| W8 | `scripts/probe_ai_mentions.py` 初版 + `research/ai_crawler_signal.md` 初回ログ | self |
| W8 | 6,658 件全件初回生成 + deploy | self |

---

## 12. 参考

- schema.org `GovernmentService`: https://schema.org/GovernmentService
- schema.org `LoanOrCredit`: https://schema.org/LoanOrCredit
- Google structured data guidelines: https://developers.google.com/search/docs/appearance/structured-data
- 政府標準利用規約2.0: https://cio.go.jp/sites/default/files/uploads/documents/hyoujun_riyoukiyaku_2.0.pdf
- fallback_plan.md (Cloudflare Pages 相乗り)
- README moat #7

---

最終更新: 2026-04-23 初版 / design doc / 実装 W5 開始。
