# 排他ルール (Exclusion Rules)

> **要約 (summary):** 排他ルールは「複数制度の併用で失格・減額・前提違反になる組み合わせ」をデータ化したもの。2026-04-24 時点で **181 件** を収録 (`kind` 内訳: exclude 125 + prerequisite 17 + absolute 15 + その他 24)。農業核心 (新規就農・認定農業者・スーパー L) + 非農業主要制度 (IT導入・持続化・M&A・キャリアアップ・雇用調整・経営強化税制) + 一次資料抽出の program-to-program mutex / cooldown / 同一資産 exclusive / 条件付き減額 をカバー。

## なぜ必要か (Why it matters)

日本の補助金・融資制度には、**同時応募すると失格になる** / **片方の前提条件を満たさないと応募できない** 組み合わせが存在する。例:

- 経営開始資金と雇用就農資金は同時受給不可 (MAFF 要綱)
- 認定新規就農者の資格が無いとスーパー L 資金の特例条件が適用されない

このような制約は各制度の要綱・Q&A に散在しており、**人力で全組み合わせを読み解くのは現実的に不可能**。誤って併用申請すると「発覚時に失格 + 既受給分の返還」というリスクが発生する。

AutonoMath は主要なルールを構造化データとして API で返すことで、この検証を **候補選定フェーズで自動化** する。

## ルールの種別 (Rule kinds)

### `mutex` — 相互排他

2 つ以上の制度を同時受給できない。両方を候補に含めた時点で `hit`。

```json
{
  "rule_id": "agri-001",
  "kind": "mutex",
  "severity": "absolute",
  "program_a": "keiei-kaishi-shikin",
  "program_b": "koyo-shuno-shikin",
  "description": "経営開始資金と雇用就農資金は同時受給不可",
  "source_urls": ["https://www.maff.go.jp/j/kobo/..."]
}
```

`severity` の値は `absolute` (例外なし) / `conditional` (条件付き) 等。

### `prerequisite` — 前提条件

A 制度を受けるためには B 制度 (または資格) が必要。`B` が候補に含まれず `A` だけ含まれる場合に triggered。

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

併用は可能だが、片方の受給額が減額される等。`hits` にレポートされるが severity で区別可能。

---

## API で使う (Using via API)

### 全ルール一覧

```bash
curl https://api.autonomath.ai/v1/exclusions/rules
```

[api-reference.md#exclusions](./api-reference.md#exclusions) 参照。

### 候補セット検証

```bash
curl -X POST https://api.autonomath.ai/v1/exclusions/check \
  -H "Content-Type: application/json" \
  -d '{
    "program_ids": [
      "keiei-kaishi-shikin",
      "koyo-shuno-shikin",
      "super-l-shikin"
    ]
  }'
```

返り値の `hits[]` が空なら併用安全、1 件以上あれば `description` と `source_urls` を確認して判断。

### MCP ツール

Claude Desktop 等からは `check_exclusions` / `list_exclusion_rules` ツールで同じ操作。[mcp-tools.md](./mcp-tools.md#check_exclusions) 参照。

---

## サンプル: agri-001 (経営開始資金 × 雇用就農資金)

```json
{
  "rule_id": "agri-001",
  "kind": "mutex",
  "severity": "absolute",
  "program_a": "keiei-kaishi-shikin",
  "program_b": "koyo-shuno-shikin",
  "description": "経営開始資金 (旧: 農業次世代人材投資資金) と雇用就農資金 (雇用型) は同一期間に受給できない。",
  "source_notes": "農林水産省「新規就農者育成総合対策 実施要綱」第3条第2項",
  "source_urls": [
    "https://www.maff.go.jp/j/kobo/..."
  ]
}
```

実際のルール内容は `/v1/exclusions/rules` で最新版を取得する (ここに書いた例は説明用フォーマットの引用)。

---

## 現行 181 件の範囲 (Scope: current 181 rules, 2026-04-24)

内訳 (`rule_id` prefix):

| カテゴリ | 件数 | 説明 |
|----------|------|------|
| hand-seeded (named) | 35 | 人手で 要綱 から読み取り構造化した中核ルール (agri 22 + non-agri 13) |
| primary-source auto-extracted (`excl-ext-*`) | 146 | 要綱 / 公募要領 PDF から一次資料パーサで抽出、人手レビュー済み |
| **合計** | **181** | — |

`kind` 内訳: `exclude` 125 / `prerequisite` 17 / `absolute` 15 / `combine_ok` 9 / `conditional_reduction` 6 / `same_asset_exclusive` 3 / `cross_tier_same_asset` 2 / `area_allocation` 1 / `cross_tier_loan_interest` 1 / `entity_scope_restriction` 1 / `mutex_certification` 1。

### agri 核心 22 件 (hand-seeded)

- 新規就農者育成総合対策: 経営開始資金 / 雇用就農資金 / 経営発展支援事業
- 青年等就農資金 (JFC)
- スーパー L 資金 (JFC)
- 認定新規就農者 / 認定農業者 資格との関係

### non-agri 主要制度 13 件 (hand-seeded)

- IT導入補助金 × IT導入補助金2024 セキュリティ枠 の cooldown / サイバーセキュリティお助け隊重複禁止
- 小規模事業者持続化補助金 (一般型通常枠) × (創業型) 相互排他 (双方向)
- キャリアアップ助成金 (正社員化) × 両立支援等助成金 (育児休業等)
- 両立支援等助成金 (出生時両立支援) × 育児休業等支援 併給調整
- 雇用調整助成金 × 産業雇用安定助成金 (産業連携) / キャリアアップ助成金 (正社員化)
- トライアル雇用助成金 × 特定求職者雇用開発助成金 時間差併用
- 中小企業経営強化税制 × 中小企業投資促進税制 同一資産重複不可
- 先端設備等導入計画 × 中小企業経営強化税制 併用条件
- 中小企業成長加速化補助金 × 事業再構築補助金 同一スコープ
- キャリアアップ助成金 (正社員化) × (障害者正社員化) 同一労働者併給不可

### 一次資料抽出 146 件 (`excl-ext-*`)

要綱 / 公募要領 PDF から primary-source パーサで抽出した 146 ルール。いずれも `source_url` (当該 要綱 原典) + `source_excerpt` 付。hand-seeded ルールより網羅範囲が広く、**地域創生推進交付金系 / 雇用助成金系 / 業種別補助金 (医療・介護・建設・造船 等)** の同一資産重複・交付期限重複・クーリング期間違反などを含む。個別ルールの全量は `list_exclusion_rules` または `GET /v1/exclusions/rules` で取得可能。

API ユーザーは `GET /v1/meta` の `exclusion_rules_count` で現在のルール数を確認し、自前の補完が必要かを判断してください。

## 制約 (Limitations)

1. **ルールは seed 済みのものだけ triggered する。** 181 件に含まれない組み合わせは `hits: []` が返っても「安全」を保証するものではない。
2. **個別判断は常に一次資料で確認すること。** `source_urls` にリンク済み。要綱改訂時は API 側で最新化するが timing lag があり得る。
3. **法的アドバイスではない。** AutonoMath は構造化情報の提供のみ。個別案件の可否判断は行政書士・税理士等の専門家、または担当窓口へ。

## 関連

- [api-reference.md#exclusions](./api-reference.md#exclusions) — `/v1/exclusions/rules`, `/v1/exclusions/check` の完全仕様
- [mcp-tools.md](./mcp-tools.md) — `list_exclusion_rules`, `check_exclusions` ツール
- [faq.md](./faq.md) — データの正確性について
