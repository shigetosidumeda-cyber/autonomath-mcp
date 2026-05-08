# jpcite Fact Sheet

更新日: 2026-05-03 / Bookyou株式会社

数値ファクトシート — 引用時は出典「jpcite / Bookyou株式会社, 2026-05-03 時点」を明記してください。

---

## Company

| 項目 | 値 |
|---|---|
| 運営 | Bookyou株式会社 |
| 法務情報 | 特定商取引法ページに集約 |
| 問い合わせ | info@bookyou.net |

## Product

| 項目 | 値 |
|---|---|
| 製品名 | jpcite |
| MCP パッケージ | PyPI 互換パッケージとして提供 |
| ドメイン | https://jpcite.com |
| ステータス | 公開中 |
| 提供形態 | REST API + MCP server (stdio) |
| MCP プロトコル | 2025-06-18 |
| MCP ツール総数 | 139 |
| REST API 経路 | `/v1/*` (FastAPI) |

## Coverage (2026-05-03 時点)

| データ | 件数 | 出典 |
|---|---:|---|
| 制度 (補助金・融資・税制・認定) | 11,601 検索対象 | METI, MAFF, 中小企業庁, 都道府県, 日本政策金融公庫 |
| 採択事例 | 2,286 | 各制度公式採択リスト |
| 融資 (三軸分解) | 108 | 日本政策金融公庫, 民間金融機関 |
| 行政処分 | 1,185 | 各官庁の公表行政処分 |
| 法令本文 | 提供中 | e-Gov 法令データ提供システム (CC-BY) — 全文検索対象 |
| 法令 (メタデータ) | 9,484 | e-Gov 法令データ提供システム (CC-BY) — 法令名検索用 |
| 税務 ruleset | 50 | 国税庁 (インボイス + 電帳法) |
| 適格事業者 | 13,801 | 国税庁 (PDL v1.0) |
| entity-fact entities | 503,930 | 12 record_kinds |
| entity-fact facts | 6.12M | EAV schema |
| entity-fact relations | 378,342 | relation table |
| entity-fact aliases | 335,605 | 別名・略称 index |
| 法令条文 index | 28,048 | e-Gov 法令データ提供システム |
| 行政処分 cases | 1,185 | 各官庁の公表行政処分 |
| 排他ルール | 181 | 公開要綱に基づき整理 |
| `source_url` / 鮮度 | 主要な公開レコードに付与 | 鮮度・broken URL は Data Freshness で確認 |

## Pricing

| 項目 | 値 |
|---|---|
| 課金モデル | 完全従量制 (no tier SKU, no seat fee, no annual minimum) |
| 単価 (税別) | ¥3 / 課金単位 (per billable unit) |
| 単価 (税込) | ¥3.30 |
| 無料枠 | 匿名 3 req/日 per IP |
| 無料枠リセット | JST 翌日 00:00 |
| 認証 | API key (オプション、無料枠は匿名 IP base) |
| 請求 | 従量課金、国内請求書対応 |

## Infrastructure

| 項目 | 値 |
|---|---|
| API 提供地域 | 日本向け運用 |
| 静的サイト | 公開Webサイト |
| データベース | SQLite + 日本語の高速全文検索 |
| OpenAPI | https://api.jpcite.com/v1/openapi.json |
| MCP distribution | MCP client configuration, DXT bundle, public manifests |

## Release notes

Public release notes and data refresh notices are published on the website
and in the audit log feed.

## Contact

- Press: [info@bookyou.net](mailto:info@bookyou.net)
- 件名 prefix: `[press]`
- SLA: 24h JST 営業日

---

最終更新: 2026-05-03 / Bookyou株式会社 / info@bookyou.net
