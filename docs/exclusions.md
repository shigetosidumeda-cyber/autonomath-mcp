# 排他ルール (Exclusion Rules)

「複数制度の併用で失格・減額・前提違反になる組み合わせ」をデータ化したもの。**181 件** 収録 (内訳: exclude 125 / prerequisite 17 / absolute 15 / その他 24)。

## なぜ必要か

日本の補助金 / 融資制度には、同時応募で失格になる / 片方の前提条件を満たさないと応募できない 組み合わせが存在する。例:

- 経営開始資金と雇用就農資金は同時受給不可 (MAFF 要綱)
- 認定新規就農者の資格が無いとスーパー L 資金の特例条件が適用されない

これらは各制度の要綱・Q&A に散在しており、人力で全組み合わせを読み解くのは現実的に不可能。誤って併用申請すると「発覚時に失格 + 既受給分の返還」のリスク。

jpcite は構造化データとして API で返すことで、候補選定フェーズで自動化する。

## ルール種別

### `mutex` — 相互排他

2 つ以上の制度を同時受給できない。両方を候補に含めると `hit`。

```json
{
  "rule_id": "agri-001",
  "kind": "mutex",
  "severity": "absolute",
  "program_a": "UNI-71f6029070",
  "program_b": "koyo-shuno-shikin",
  "description": "経営開始資金と雇用就農資金は同時受給不可",
  "source_urls": ["https://www.maff.go.jp/j/kobo/..."]
}
```

`severity`: `absolute` (例外なし) / `conditional` (条件付き) etc.

### `prerequisite` — 前提条件

A を受けるには B (制度 / 資格) が必要。`B` 不在で `A` だけ含むと triggered。

```json
{
  "rule_id": "agri-005",
  "kind": "prerequisite",
  "program_a": "super-l-shikin",
  "program_b": "nintei-nougyou-sha",
  "description": "スーパー L 資金の前提に認定農業者資格が必要"
}
```

### `conditional_reduction` — 条件付き減額

併用可だが受給額が減額される等。`hits` に severity 付きで表示される。

## API で使う

### 全ルール一覧

```bash
curl https://api.jpcite.com/v1/exclusions/rules
```

### 候補セット検証

```bash
curl -X POST https://api.jpcite.com/v1/exclusions/check \
  -H "Content-Type: application/json" \
  -d '{
    "program_ids": [
      "UNI-71f6029070",
      "koyo-shuno-shikin",
      "super-l-shikin"
    ]
  }'
```

`hits[]` が空なら併用安全、1 件以上あれば `description` と `source_urls` を確認して判断。

### MCP ツール

`check_exclusions` / `list_exclusion_rules` ([mcp-tools.md](./mcp-tools.md))。

詳細仕様: [api-reference.md#exclusions](./api-reference.md)。

## サンプル

```json
{
  "rule_id": "agri-001",
  "kind": "mutex",
  "severity": "absolute",
  "program_a": "UNI-71f6029070",
  "program_b": "koyo-shuno-shikin",
  "description": "経営開始資金 (旧: 農業次世代人材投資資金) と雇用就農資金 (雇用型) は同一期間に受給できない。",
  "source_notes": "農林水産省「新規就農者育成総合対策 実施要綱」第3条第2項",
  "source_urls": [
    "https://www.maff.go.jp/j/kobo/..."
  ]
}
```

最新ルールは `/v1/exclusions/rules` で取得 (上記は説明用フォーマット引用)。

## 内訳 (181 件)

| カテゴリ | 件数 | 説明 |
|----------|------|------|
| hand-seeded (named) | 35 | 人手で要綱から構造化した中核ルール (agri 22 + non-agri 13) |
| heuristic-extracted (`excl-ext-*`) | 146 | 要綱 / 公募要領 PDF から rule-based heuristic で抽出、人手レビュー済み |
| **合計** | **181** | — |

`kind` 内訳: `exclude` 125 / `prerequisite` 17 / `absolute` 15 / `combine_ok` 9 / `conditional_reduction` 6 / `same_asset_exclusive` 3 / `cross_tier_same_asset` 2 / `area_allocation` 1 / `cross_tier_loan_interest` 1 / `entity_scope_restriction` 1 / `mutex_certification` 1。

### agri 核心 22 件

- 新規就農者育成総合対策: 経営開始資金 / 雇用就農資金 / 経営発展支援事業
- 青年等就農資金 / スーパー L 資金 (JFC)
- 認定新規就農者 / 認定農業者 資格との関係

### non-agri 主要制度 13 件

- IT導入補助金 系の cooldown / お助け隊重複禁止
- 小規模事業者持続化補助金 (一般型通常枠 × 創業型)
- キャリアアップ助成金 (正社員化) × 両立支援等助成金
- 雇用調整助成金 × 産業雇用安定助成金 / キャリアアップ助成金
- トライアル雇用 × 特定求職者雇用開発
- 中小企業経営強化税制 × 中小企業投資促進税制 (同一資産重複不可)
- 先端設備等導入計画 × 中小企業経営強化税制
- 中小企業成長加速化補助金 × 事業再構築補助金 (同一スコープ)
- キャリアアップ助成金 (正社員化 × 障害者正社員化) 同一労働者併給不可

### heuristic 抽出 146 件 (`excl-ext-*`)

要綱 / 公募要領 PDF から rule-based heuristic で抽出。すべて `source_url` (要綱原典) + `source_excerpt` 付。地域創生推進交付金系 / 雇用助成金系 / 業種別補助金 (医療・介護・建設・造船 等) の同一資産重複・交付期限重複・クーリング期間違反をカバー。

> **限界:** rule-based 抽出のため取りこぼし / 誤検出が起こり得る。確定的判定には `source_url` 一次資料の人手確認を必ず行う。「ルール未登録 = 安全」ではない。

`list_exclusion_rules` または `GET /v1/exclusions/rules` で全量取得可。`GET /v1/meta` の `exclusion_rules_count` で現在件数確認。

## 制約

1. seed 済みルールのみ triggered。181 件外の組み合わせは `hits: []` でも安全保証ではない
2. 個別判断は常に一次資料で確認 (`source_urls` 添付)。要綱改訂時の timing lag あり
3. 法的アドバイスではない (構造化情報の提供のみ)。可否判断は行政書士・税理士・担当窓口へ

## 関連

- [api-reference.md](./api-reference.md) — `/v1/exclusions/*` の完全仕様
- [mcp-tools.md](./mcp-tools.md) — `list_exclusion_rules` / `check_exclusions` ツール
- [faq.md](./faq.md) — データ正確性の扱い
