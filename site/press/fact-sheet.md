# jpcite Fact Sheet

更新日: 2026-04-25 / Launch: 2026-05-06 / Bookyou株式会社

数値ファクトシート — 引用時は出典「jpcite / Bookyou株式会社, 2026-04-25 時点」を明記してください。

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
| ステータス | Launch 2026-05-06 |
| 提供形態 | REST API + MCP server (stdio) |
| MCP プロトコル | 2025-06-18 |
| MCP ツール総数 | 93 |
| REST API 経路 | `/v1/*` (FastAPI) |

## Coverage (2026-04-25 時点)

| データ | 件数 | 出典 |
|---|---:|---|
| 制度 (補助金・融資・税制・認定) | 11,684 検索可 / 14,472 登録総数 | METI, MAFF, 中小企業庁, 都道府県, 日本政策金融公庫 |
| 採択事例 | 2,286 | 各制度公式採択リスト |
| 融資 (三軸分解) | 108 | 日本政策金融公庫, 民間金融機関 |
| 行政処分 | 1,185 | 各官庁の公表行政処分 |
| 法令 (本文収録) | 154 | e-Gov 法令データ提供システム (CC-BY) — 全文検索対象 |
| 法令 (メタデータ stubs) | 9,484 | e-Gov 法令データ提供システム (CC-BY) — 法令名 resolver 用、本文ロード継続中 |
| 税務 ruleset | 35 | 国税庁 (インボイス + 電帳法) |
| 適格事業者 | 13,801 | 国税庁 (PDL v1.0) |
| entity-fact entities | 503,930 | 12 record_kinds |
| entity-fact facts | 6.12M | EAV schema |
| entity-fact relations | 23,805 | 14 canonical relation types |
| entity-fact aliases | 335,605 | 別名・略称 index |
| 法令条文 index | 28,048 | e-Gov 法令データ提供システム |
| 行政処分 詳細 records | 22,258 | 各官庁の公表行政処分 |
| 排他ルール | 181 | 公開要綱に基づき整理 |
| `source_url` 付与率 | 99% 以上 | 12 件は小規模自治体 CMS 不在のため URL 未取得 |

## Pricing

| 項目 | 値 |
|---|---|
| 課金モデル | 完全従量制 (no tier SKU, no seat fee, no annual minimum) |
| 単価 (税別) | ¥3 / request |
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
| MCP registry | mcp registry, smithery, glama, etc. |

## Launch milestones

| 日付 (JST) | イベント |
|---|---|
| T-3d (2026-05-03) | Zenn 草稿 publish |
| T-2d (2026-05-04) | GitHub repo public |
| T-1d (2026-05-05) | PyPI publish |
| T+0 (2026-05-06) | Launch tweet + HN Show + email subscribers |
| T+1d (2026-05-07) | 5 audience pitch detailed blog |
| T+3d (2026-05-09) | Case study collection start |
| T+7d (2026-05-13) | First metrics report (transparent dashboard) |

## Contact

- Press: [info@bookyou.net](mailto:info@bookyou.net)
- 件名 prefix: `[press]`
- SLA: 24h JST 営業日

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
