<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "税務会計AI Vetted Examples (8 query patterns)",
  "description": "税務会計AI で本番 API に対して動作確認済みの 8 つのクエリ例。curl と MCP ツール呼び出しの両方、レスポンス形状、結果の解釈、データ充足の限界まで明示。",
  "datePublished": "2026-04-26",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://jpcite.com/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社"
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/examples/"
  }
}
</script>

# 税務会計AI examples

8 つの実動作クエリ例。`curl` 形式と MCP 形式を併記。レスポンス例は DB 行から組み立てた **expected behavior** で、行の追加 / 削除で若干変わる。

料金 / quota は [pricing.md](./pricing.md)。

```bash
export AUTONOMATH_API_BASE=https://api.jpcite.com
export AUTONOMATH_API_KEY=am_xxxx   # 任意; 未設定なら anonymous 50/月
```

## 1. 都道府県 + 業種で補助金検索

「青森県の S/A tier 制度を 10 件」。FTS5 と `prefecture` filter を組み合わせる
最も基本的な使い方。

```bash
curl -s "$AUTONOMATH_API_BASE/v1/programs/search?q=新規就農&prefecture=青森県&tier=S&tier=A&limit=10" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP:

```yaml
- tool: search_programs
  args:
    q: 新規就農
    prefecture: 青森県
    tier: [S, A]
    limit: 10
```

レスポンス形状 (expected behavior; `total` は FTS が enriched_json まで
舐めるため `q` の語彙で揺れる):

```json
{
  "total": 12,
  "limit": 10,
  "offset": 0,
  "results": [
    {
      "unified_id": "UNI-042f742d2d",
      "primary_name": "新規就農者育成支援（経営開始資金）",
      "tier": "A",
      "authority_level": "national",
      "authority_name": "農林水産省",
      "prefecture": "全国",
      "amount_max_man_yen": 1500
    }
  ]
}
```

**解釈**: `unified_id` を `get_program` (詳細) や `check_exclusions` に渡す。
`prefecture: 全国` は国制度が混じった結果で、青森県 limited 制度は `prefecture`
列が `青森県` のもの。青森県 + tier S/A は **21 件** 在庫があり、`q` で絞ると
ここから `新規就農` などの語彙で narrow される。`q` を空にして tier だけで
絞ると棚卸しに使える。

---

## 2. 法律名 + 条文で本文取得

「中小企業基本法 第 5 条」。法令データは e-Gov 法令 API (CC-BY 4.0) で 法令本文 154 件 + 法令メタデータ 9,484 件 (本文ロード継続中)、`unified_id` 経由で個別本文を引く。 全文検索が可能なのは現時点で 154 件、 残りは法令名 / 法令番号 / e-Gov リンクの resolver として参照可能。

```bash
# まず id 解決
curl -s "$AUTONOMATH_API_BASE/v1/laws/search?q=中小企業基本法&limit=3" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"

# 該当 unified_id で本文
curl -s "$AUTONOMATH_API_BASE/v1/laws/LAW-956ad0e0e4" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP:

```yaml
- tool: search_laws
  args:
    q: 中小企業基本法
    limit: 3
- tool: get_law
  args:
    unified_id: LAW-956ad0e0e4
```

**解釈**: 条文単位で取りたい場合は autonomath-side `get_law_article_am`
(MCP only) を使うと `am_law_article` (28,048 行) から条番号で直引きできる。
`law_short_title` は別名・略称を含むので、ヒットが複数になることがある
(例: `中小企業団体法` と `中小企業労働力確保法` 等が `q=中小企業` で混ざる)。

---

## 3. 行政処分を都道府県 + イベント種別で検索

「補助金返還命令を受けた事例を北海道で」。`enforcement_cases` 1,185 件のうち
clawback 668 / penalty 517。

```bash
curl -s "$AUTONOMATH_API_BASE/v1/enforcement-cases/search?event_type=clawback&prefecture=北海道&limit=10" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP:

```yaml
- tool: search_enforcement_cases
  args:
    event_type: clawback
    prefecture: 北海道
    limit: 10
```

**解釈**: `recipient_houjin_bangou` 列は **100% NULL** (会計検査院は法人番号を
publish しない) ので法人番号 filter は使わない。法人名で当てたい場合は
`q=<会社名>` で `source_title` / `reason_excerpt` / `program_name_hint` を
LIKE 検索する。`amount_yen` は clawback 668 行のうち詳細金額が出ている部分のみ
充足 (autonomath 側の `am_enforcement_detail` では 1,498 行に拡張されているが、
それは別テーブル)。

---

## 4. 税制 ruleset を年度 + カテゴリで検索

「令和 6 年度以降施行の消費税関連制度」。`tax_rulesets` 35 行 (consumption 27 /
corporate 6 / income 2)。`/search` は `effective_from`/`effective_until` 列を
直接 filter するわけでないので、結果側の日付を使って絞る。

```bash
curl -s "$AUTONOMATH_API_BASE/v1/tax_rulesets/search?tax_category=consumption&limit=30" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP (autonomath-side、より精密な date pin):

```yaml
- tool: get_am_tax_rule
  args:
    tax_category: consumption
    effective_on: "2026-04-01"
```

**解釈**: cliff date が 3 つ既知 — 2026-09-30 (2割特例終了)、2027-09-30
(80% 経過措置終了)、2029-09-30 (50% 経過措置 / 少額特例終了)。これらに
当たる ruleset は `effective_until` で識別可能。`POST /v1/tax_rulesets/evaluate`
で構造化条件 (`eligibility_conditions_json`) に対する判定もできる。

---

## 5. 認定区分で 認定・認証制度をリスト

「健康経営優良法人 / えるぼし / くるみん などの取得可能制度」。autonomath
DB の `record_kind='certification'` (66 行) を引く。

```bash
curl -s "$AUTONOMATH_API_BASE/v1/am/certifications?authority=厚生労働省&limit=20" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP:

```yaml
- tool: search_certifications
  args:
    authority: 厚生労働省
    limit: 20
```

**解釈**: `authority` enum は `経済産業省` / `厚生労働省` / `内閣府` 等
固定値。`size=small` 等で従業員規模を絞り、`industry=` で業種絞り込みも
可能。認定の取得は補助金加点要件になることが多いので、`search_programs`
の上流で取って制度マッチングに使う。

---

## 6. 採択事例を業種 + 都道府県で検索

「青森県の農業 (JSIC=A) 採択事例」。`case_studies` 2,286 件、ただし
`industry_jsic` は 1,103 行が空、`total_subsidy_received_yen` は **4 行 / 2,286 (<1%)**
しか充足していない。

```bash
curl -s "$AUTONOMATH_API_BASE/v1/case-studies/search?industry_jsic=A&prefecture=青森県&limit=10" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP:

```yaml
- tool: search_case_studies
  args:
    industry_jsic: A
    prefecture: 青森県
    limit: 10
```

**解釈**: `programs_used_json` で過去同制度を取った企業を辿れる。
`min_subsidy_yen` / `max_subsidy_yen` は <1% 充足なのでデフォルトで
使わない (フィルタすると 99% が消える)。`publication_date` 範囲は
2020-03-23 〜 2026-03-17。

---

## 7. 排他ルール一括チェック

「複数制度を同時申請可能か」を判定。181 ルール (排他 125 + 前提 17 +
absolute 15 + その他 24) に対して program_id セットを叩く。

```bash
curl -s -X POST "$AUTONOMATH_API_BASE/v1/exclusions/check" \
  -H "X-API-Key: $AUTONOMATH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"program_ids": ["UNI-042f742d2d", "UNI-08f87b0586"]}'
```

MCP:

```yaml
- tool: check_exclusions
  args:
    program_ids:
      - UNI-042f742d2d   # 経営開始資金
      - UNI-08f87b0586   # 青年等就農資金
```

期待されるレスポンス形状:

```json
{
  "hits": [
    {
      "rule_id": "excl-keiei-kaishi-vs-seinen-shuno",
      "kind": "exclude",
      "severity": "absolute",
      "program_ids": ["UNI-042f742d2d", "UNI-08f87b0586"],
      "reason": "経営開始資金と青年等就農資金は併給不可"
    }
  ]
}
```

**解釈**: `severity` が `absolute` なら同時取得不可、`conditional` なら減額や
時系列条件付き、`prerequisite` は前提制度の取得が必要 (例: 認定新規就農者
取得が前提)。`hits` が空なら矛盾なし。

---

## 8. 公庫融資の担保 / 保証人 3 軸で検索

「無担保・無保証人で借りられる融資」。`loan_programs` 108 行、担保 / 個人保証人
/ 第三者保証人を独立 enum 化済み。各軸の enum は
`required` / `not_required` / `negotiable` / `unknown` の 4 値。

```bash
curl -s "$AUTONOMATH_API_BASE/v1/loan-programs/search?collateral_required=not_required&personal_guarantor_required=not_required&limit=20" \
  -H "X-API-Key: $AUTONOMATH_API_KEY"
```

MCP (boolean フラグ; 無担保 / 無個人保証 / 無第三者保証 を独立に絞る):

```yaml
- tool: search_loans_am
  args:
    no_collateral: true
    no_personal_guarantor: true
    limit: 20
```

**解釈**: 「要相談」(= `negotiable`) と 「無し」(= `not_required`) を 1 値でまとめ
ないのが本 DB のポイント。REST 側は `required | not_required | negotiable |
unknown` の 4 値 enum で 3 軸別々に判定でき、MCP 側は `not_required` 狙い撃ちの
boolean 糖衣を提供。`max_interest_rate=0.015` で年利 1.5% 上限、
`min_loan_period_years=10` で 10 年以上の長期も追加 filter 可能。

---

## Limitations (正直な制約)

データを売って詐欺リスクを取れない設計上、以下は **正面から書いておく**。
見落として顧客に渡すと不利益が出るので、回答前にこの範囲を確認すること。

### A. FTS5 trigram tokenizer は単漢字でかぶる

`programs_fts` / `case_studies_fts` / `tax_rulesets_fts` は SQLite trigram。
`q=税` のような 1 文字検索は `納税` も `税額` も `所得税` も全部ヒットする。
2 文字以上の漢字熟語を狙う場合は **必ず引用符付き** で `q="税額控除"` と
書く (programs.py 387 行付近の workaround)。

### B. 公開保留中の制度は検索路から除外される

公開保留 (1,923 件、二次レビュー待ち) は `programs.search` / 静的ページ生成 /
MCP すべての路で `excluded=0 AND COALESCE(tier,'X') != 'X'` ガードに
弾かれる。`include_excluded=true` を渡せば見えるが、そこに居る理由
(external_info_entry / no_amount_data / placeholder_url 等) を確認した上で
使うこと。

### C. `am_amendment_snapshot` の改正履歴は **部分的**

`am_amendment_snapshot` 14,596 行のうち、内部監査 (Z3 finding) で
**eligibility_hash の 82% が空 / 重複** で、v1 と v2 の差分が
hashes 上は同一に見える。要するに「過去時点の eligibility 条件を完全に
復元できる」という保証はない。`active_programs_at` / `query_at_snapshot`
の歴史照会は「公布日時点の名目的状態」までで、**条件文をある時点に
正確に復元することは信用しない**。

### D. `compat_matrix` は heuristic、出典付きは 9%

「制度 A と制度 B が併用可」を表す互換マトリクスは、明示的に出典 (告示 /
要綱 / Q&A) で裏取りされたものは **9% に過ぎない**。残り 91% は名前 / カテゴリ
ベースのヒューリスティック推論。`check_exclusions` の `hits` が **0 件 = 必ず
併用可** ではない。重要案件では制度本体の Q&A や 認定経営革新等支援機関に
当たって最終確認すること。

### E. `recipient_houjin_bangou` は 100% NULL

行政処分側の法人番号は会計検査院が publish していないため、
`enforcement_cases.recipient_houjin_bangou` を filter に使うと必ず 0 件。
法人名で `q=<社名>` か、桁違いの `q=<houjin_bangou>` substring で当てる。

### F. `case_studies.total_subsidy_received_yen` は <1% 充足

採択は publish するが交付額を出す省庁は少ない。`min_subsidy_yen` /
`max_subsidy_yen` で絞ると **99% が消える**。金額帯で絞りたい場合は
`programs` 側の `amount_max_man_yen` で代替する。

---

## Errors

| code | 意味 | 対応 |
|------|------|------|
| 401 | API key 不正 / 未設定 | header 確認、anonymous は header を付けない |
| 404 | unified_id / case_id / law_id 不在 | search で id 解決を先にやる |
| 429 | quota 超過 | `Retry-After` ヘッダ秒数だけ待つ |
| 5xx | サーバ側 | `error.trace_id` を info@bookyou.net に送る |

## See Also

- [mcp-tools.md](./mcp-tools.md) — 全 72 ツールのスキーマ
- [api-reference.md](./api-reference.md) — REST 全エンドポイント
- [exclusions.md](./exclusions.md) — 排他ルールの kind / severity 分類
- [prompt_cookbook.md](./prompt_cookbook.md) — agent flow のレシピ集
