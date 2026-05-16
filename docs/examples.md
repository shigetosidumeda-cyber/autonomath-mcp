<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Vetted Examples (8 query patterns)",
  "description": "jpcite で本番 API に対して動作確認済みの 8 つのクエリ例。curl と MCP ツール呼び出しの両方、レスポンス形状、結果の解釈、データ充足の限界まで明示。",
  "datePublished": "2026-04-26",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com/"
  },
  "publisher": {
    "@type": "Organization",
    "name": "jpcite"
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/examples/"
  }
}
</script>

# jpcite examples

8 つの実動作クエリ例。`curl` 形式と MCP 形式を併記。レスポンス例は DB 行から組み立てた **expected behavior** で、行の追加 / 削除で若干変わる。

料金 / quota は [pricing.md](./pricing.md)。

```bash
export JPCITE_API_BASE=https://api.jpcite.com
export JPCITE_API_KEY=jc_xxxx   # 任意; 未設定なら anonymous 3/日
```

## 1. 都道府県 + 業種で制度根拠の Evidence Packet を取得

「東京都の S/A tier 制度を 10 件」。FTS5 と `prefecture` filter を組み合わせる
最も基本的な使い方。

```bash
curl -s "$JPCITE_API_BASE/v1/programs/search?q=設備投資&prefecture=東京都&tier=S&tier=A&limit=10" \
  -H "X-API-Key: $JPCITE_API_KEY"
```

MCP:

```yaml
- tool: search_programs
  args:
    q: 設備投資
    prefecture: 東京都
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
      "unified_id": "UNI-example-energy-dx",
      "primary_name": "東京都 中小企業 省エネ設備導入支援",
      "tier": "A",
      "authority_level": "prefecture",
      "authority_name": "東京都",
      "prefecture": "東京都",
      "amount_max_man_yen": 500
    }
  ]
}
```

**解釈**: `unified_id` を `get_program` (詳細) や `check_exclusions` に渡す。
`prefecture: 全国` は国制度が混じった結果で、東京都 limited 制度は `prefecture`
列が `東京都` のもの。東京都 + tier S/A の棚卸しに対して、`q` で絞ると
ここから `設備投資` などの語彙で narrow される。`q` を空にして tier だけで
絞ると棚卸しに使える。

---

## 2. 法律名 + 条文参照を取得

「中小企業基本法 第 5 条」。法令データは e-Gov 法令 API (CC-BY 4.0) を出典に、法令メタデータと利用可能な条文参照を返す。`unified_id` 経由で法令名・法令番号・e-Gov 参照 URL を引ける。条文本文の取得可否はレコードごとに異なる。

```bash
# まず id 解決
curl -s "$JPCITE_API_BASE/v1/laws/search?q=中小企業基本法&limit=3" \
  -H "X-API-Key: $JPCITE_API_KEY"

# 該当 unified_id で本文
curl -s "$JPCITE_API_BASE/v1/laws/{unified_id}" \
  -H "X-API-Key: $JPCITE_API_KEY"
```

MCP:

```yaml
- tool: search_laws
  args:
    q: 中小企業基本法
    limit: 3
- tool: get_law
  args:
    unified_id: "{unified_id}"
```

**解釈**: 条文単位で取りたい場合は MCP の条文取得ツール
(MCP only) を使うと条番号で直引きできる。
`law_short_title` は別名・略称を含むので、ヒットが複数になることがある
(例: `中小企業団体法` と `中小企業労働力確保法` 等が `q=中小企業` で混ざる)。

---

## 3. 行政処分を都道府県 + イベント種別で検索

「補助金返還命令を受けた事例を北海道で」。`enforcement_cases` 1,185 件のうち
clawback 668 / penalty 517。

```bash
curl -s "$JPCITE_API_BASE/v1/enforcement-cases/search?event_type=clawback&prefecture=北海道&limit=10" \
  -H "X-API-Key: $JPCITE_API_KEY"
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
充足。より詳細なデータが必要な場合は、行政処分 detail 系 endpoint を併用する。

---

## 4. 税制 ruleset を年度 + カテゴリで検索

「令和 6 年度以降施行の消費税関連制度」。`tax_rulesets` 35 行 (consumption 27 /
corporate 6 / income 2)。`/search` は `effective_from`/`effective_until` 列を
直接 filter するわけでないので、結果側の日付を使って絞る。

```bash
curl -s "$JPCITE_API_BASE/v1/tax_rulesets/search?tax_category=consumption&limit=30" \
  -H "X-API-Key: $JPCITE_API_KEY"
```

適用日を厳密に見る場合は、`effective_on` を指定できる tax ruleset 系の取得・評価 endpoint を使う。

**解釈**: cliff date が 3 つ既知 — 2026-09-30 (2割特例終了)、2027-09-30
(80% 経過措置終了)、2029-09-30 (50% 経過措置 / 少額特例終了)。これらに
当たる ruleset は `effective_until` で識別可能。`POST /v1/tax_rulesets/evaluate`
で構造化条件 (`eligibility_conditions_json`) に対する判定もできる。

---

## 5. 認定区分で 認定・認証制度をリスト

「健康経営優良法人 / えるぼし / くるみん などの取得可能制度」。認定・認証制度データを引く。

```bash
curl -s "$JPCITE_API_BASE/v1/am/certifications?authority=厚生労働省&limit=20" \
  -H "X-API-Key: $JPCITE_API_KEY"
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

「愛知県の製造業 (JSIC=E) 採択事例」。`case_studies` 2,286 件、ただし
`industry_jsic` は 1,103 行が空、`total_subsidy_received_yen` は **4 行 / 2,286 (<1%)**
しか充足していない。

```bash
curl -s "$JPCITE_API_BASE/v1/case-studies/search?industry_jsic=E&prefecture=愛知県&limit=10" \
  -H "X-API-Key: $JPCITE_API_KEY"
```

MCP:

```yaml
- tool: search_case_studies
  args:
    industry_jsic: E
    prefecture: 愛知県
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
curl -s -X POST "$JPCITE_API_BASE/v1/exclusions/check" \
  -H "X-API-Key: $JPCITE_API_KEY" \
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
curl -s "$JPCITE_API_BASE/v1/loan-programs/search?collateral_required=not_required&personal_guarantor_required=not_required&limit=20" \
  -H "X-API-Key: $JPCITE_API_KEY"
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

実務で誤解しやすい点をまとめます。重要な判断では、返却された一次資料 URL を必ず確認してください。

### A. 短すぎる検索語は広く一致する

`q=税` のような 1 文字検索は `納税` も `税額` も `所得税` も全部ヒットする。
2 文字以上の漢字熟語を狙う場合は、`q="税額控除"` のように具体的に指定してください。

### B. 品質条件を満たさない制度は検索路から除外される

出典 URL や金額などの主要項目が不足している制度は、通常検索と MCP の結果から除外されます。除外された制度は公開検索・batch・MCP では返りません。重要案件では一次資料で最新状態を確認してください。

### C. 改正履歴は部分的

制度の過去状態は、すべての条件文を完全に復元できるわけではありません。過去時点の判断が必要な場合は、当時の公募要領や告示を確認してください。

### D. 併用チェックは安全保証ではない

`check_exclusions` の `hits` が 0 件でも、必ず併用できるという意味ではありません。重要案件では制度本体の Q&A、担当窓口、専門家に当たって最終確認してください。

### E. 行政処分は法人番号で探せない場合がある

公開元が法人番号を出していない行政処分は、法人番号検索では見つからない場合があります。法人名、代表的な事業名、所在地などでも確認してください。

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
| 5xx | サーバ側 | `error.trace_id` を添えて問い合わせる |

## See Also

- [mcp-tools.md](./mcp-tools.md) — 全 155 ツールのスキーマ
- [api-reference.md](./api-reference.md) — REST 全エンドポイント
- [exclusions.md](./exclusions.md) — 排他ルールの kind / severity 分類
- [prompt_cookbook.md](./prompt_cookbook.md) — agent flow のレシピ集
