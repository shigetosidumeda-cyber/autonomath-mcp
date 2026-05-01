---
title: "日本の補助金・融資データ 14,472 件を 1 本の REST API にまとめた話"
description: "jpcite ローンチ記事 (Article 1 of 2) — 補助金・融資・税制・認定制度 14,472 件、採択事例 2,286 件、融資 108 件、排他ルール 181 本を 1 本の REST API で提供する設計背景。"
tags:
  - api
  - python
  - fastapi
  - llm
  - japan
published: false
---

# 日本の補助金・融資データ 14,472 件を 1 本の REST API にまとめた話

## 補助金を探すには「省庁ガチャ」を 10 回引かなければならない

「うちの会社で使える補助金、調べてくれますか」と言われたとき、
現実に何が起きるか。

農水省・経産省・中小企業庁・都道府県・市区町村の
各ポータルを個別に開き、PDFを開き、
該当しそうなものを10件見つけたら今度は「これと一緒に申請できないやつある?」
という「排他ルール」を要綱の脚注から掘り起こす。
これが現状です。

jpcite はそこに API 1 本を刺します。

- **14,472 件**の補助金・融資・税制・認定制度
- **2,286 件**の採択事例
- **108 件**の融資（担保・個人保証人・第三者保証人 三軸分解）
- **1,185 件**の行政処分事例
- **181 本**の排他・前提条件ルール
- `source_url` + `fetched_at` を 99%以上の行に付与 (12件は小規模自治体 CMS 不在のため URL 未取得)

一次資料（農水省・経産省・SMRJ・日本政策金融公庫等）だけを参照し、
集約サイトーは一切使いません。

---

## 3 分で動かす

### Step 1: 補助金を検索する

```bash
curl -s "https://api.jpcite.com/v1/programs/search?q=設備投資&prefecture=埼玉県&limit=3" \
  | python3 -m json.tool
```

```json
{
  "results": [
    {
      "unified_id": "saitama_subsidy_maff_sousetsu_a7f3c21",
      "title": "令和8年度 農業経営強化支援交付金",
      "authority": "農林水産省",
      "amount_max": 50000000,
      "amount_max_description": "5,000万円（補助率 1/2 以内）",
      "target_types": ["法人", "認定農業者"],
      "deadline": "2026-06-30",
      "source_url": "https://www.maff.go.jp/j/aid/hozyo/2026/...",
      "fetched_at": "2026-04-24T03:00:00+09:00"
    }
  ],
  "total": 47,
  "next_cursor": "eyJvZmZzZXQiOjN9",
  "has_more": true
}
```

### Step 2: 排他ルールを判定する

候補が揃ったら、複数制度の「同時申請不可」を一括チェックします。

```bash
curl -s -X POST "https://api.jpcite.com/v1/exclusions/check" \
  -H "Content-Type: application/json" \
  -d '{
    "unified_ids": [
      "saitama_subsidy_maff_sousetsu_a7f3c21",
      "national_loan_jfc_keiei_a1b2c3d"
    ],
    "applicant": {
      "applicant_type": "法人",
      "household_income": 12000000
    }
  }' \
  | python3 -m json.tool
```

```json
{
  "hits": [
    {
      "rule_id": "MAFF_INCOME_CAP_2025",
      "kind": "exclude",
      "description": "世帯所得 1,000 万円超の申請者は除外",
      "affected_ids": ["saitama_subsidy_maff_sousetsu_a7f3c21"],
      "source_url": "https://www.maff.go.jp/..."
    }
  ]
}
```

### Step 3: API キー付きで認証する

匿名では 3 req/日（JST 翌日 00:00 リセット）まで無料です。
それ以上は API キーを付けてください。

```bash
export AM_KEY="am_xxxxxxxxxxxxxxxx"

curl -s "https://api.jpcite.com/v1/programs/search?q=クラウド&limit=5" \
  -H "X-API-Key: $AM_KEY" \
  | python3 -m json.tool
```

料金は **¥3/リクエスト（税別）、税込 ¥3.30**。
Tier なし、座席課金なし、年次契約なし。

---

## なぜこれを作ったか

一言で言えば「LLM に信頼できる補助金データを渡したかったから」です。

Claude や GPT に「うちの会社で使える補助金は?」と聞くと、
廃止済みの制度名・桁違いの金額・404 の URL が返ってくる。
これは LLM の性能の問題ではなく、**信頼できるデータが LLM の外にないことの問題**です。

jpcite を運営しているのは、東京の小さなソフトウェア会社
Bookyou株式会社です。
ソロ運用・ゼロタッチ前提で設計しています。

---

## アーキテクチャ概要

```
FastAPI (REST /v1/*)
 └── SQLite 全文検索 (3-gram 分割)
      ├── programs         (14,472 件)
      ├── case_studies     (2,286 件)
      ├── loan_programs    (108 件, 三軸担保分解)
      ├── enforcement_cases (1,185 件)
      ├── exclusion_rules  (181 本)
      ├── laws             (6,850+ 件 e-Gov CC-BY — 継続ロード中)
      ├── tax_rulesets     (50 件 インボイス/電帳法 — live)
      └── court_decisions / bids / invoice_registrants (スキーマ構築済み、データロード準備中)
```

FastMCP stdio サーバーも同じ SQLite を読むので、
REST と MCP でビジネスロジックの重複は一切ありません。

---

## 設計上のこだわり 3 点

### 1. null / [] / "" を意味で分ける

`null` = 未確認、`[]` = 該当なし（確認済み）、`""` は使わない。

LLM は `null` を見て「別のツールで調べるべきか」と判断し、
`[]` を見て「これ以上探さなくてよい」と判断します。

### 2. エラーは日本語の自然言語で返す

```json
{
  "error": "prefecture には都道府県名（漢字）を指定してください。受け取った値: 'Tokyo'",
  "suggested_values": ["東京都", "神奈川県", "埼玉県"],
  "field": "prefecture"
}
```

LLM がエラーを読んで自己修正してリトライできます。

### 3. source_url は全件必須フィールド

99%以上の行に `source_url` と `fetched_at` が付いています。
`fetched_at` は「私たちが最後に取得した日時」であり、
「制度が最終更新された日時」ではありません（景表法・消費者契約法上の誠実さ）。

---

## レート制限の仕様

| | 上限 | リセット |
|---|---|---|
| 匿名（API キーなし） | 3 req/日 per IP | JST 翌日 00:00 |
| 認証済み（API キーあり） | 使った分だけ課金 | なし |

HTTP 429 のレスポンスには次のリセット日時が入ります。

```json
{
  "error": "レート制限に達しました。JST 翌日 00:00 にリセットされます。",
  "retry_after_seconds": 604800,
  "reset_at": "2026-05-01T00:00:00+09:00"
}
```

---

## 今後の展開

2026-04-24 拡張では法令 (e-Gov CC-BY, 6,850+ 件・継続ロード中) と税務ルールセット (インボイス+電帳法, 50 件)
をライブ追加しました。判例・入札・国税庁適格事業者はスキーマと取込インフラが完成しており、
データロードはローンチ後に追って公開します。

---

## まとめ

- 14,472 件の一次資料補助金データが `curl` 1 本で取れる
- 181 本の排他ルールを POST 1 本で機械判定できる
- ¥3/req 税別（税込 ¥3.30）、匿名 3 req/日 per IP 無料
- `source_url` + `fetched_at` を 99%以上の行に付与

**jpcite: https://jpcite.com**

---

*Bookyou株式会社 / info@bookyou.net*
