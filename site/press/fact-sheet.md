# AutonoMath Fact Sheet

更新日: 2026-04-25 / Launch: 2026-05-06 / Bookyou株式会社 (T8010001213708)

数値ファクトシート — 引用時は出典「AutonoMath / Bookyou株式会社, 2026-04-25 時点」を明記してください。

---

## Company

| 項目 | 値 |
|---|---|
| 商号 | Bookyou株式会社 (Bookyou K.K.) |
| 法人番号 | T8010001213708 |
| 適格請求書登録 | 2025-05-12 (令和7年5月12日登録) |
| 所在地 | 東京都文京区小日向2-22-1 |
| 代表者 | 梅田茂利 (Shigetoshi Umeda) |
| 資本金 | 非公開 (solo bootstrapped) |
| 従業員数 | 1 名 (代表のみ) |
| 設立形態 | Solo + zero-touch ops |
| 取得チャネル | 100% organic (no ads, no sales calls) |

## Product

| 項目 | 値 |
|---|---|
| 製品名 | AutonoMath |
| PyPI パッケージ | `autonomath-mcp` |
| ドメイン | https://jpcite.com |
| ステータス | Launch 2026-05-06 |
| 提供形態 | REST API + MCP server (stdio) |
| MCP プロトコル | 2025-06-18 |
| MCP ツール総数 | 69  + 30 autonomath, `list_tax_sunset_alerts` 含む at default gates; 3 broken-tool gates off pending fix) |
| REST API 経路 | `/v1/*` (FastAPI) |

## Coverage (2026-04-25 時点)

| データ | 件数 | 出典 |
|---|---:|---|
| 制度 (補助金・融資・税制・認定) | 10,790 検索可 / 13,578 登録総数 | METI, MAFF, 中小企業庁, 都道府県, 日本政策金融公庫 |
| 採択事例 | 2,286 | 各制度公式採択リスト |
| 融資 (三軸分解) | 108 | 日本政策金融公庫, 民間金融機関 |
| 行政処分 | 1,185 | 各官庁の公表行政処分 |
| 法令 (本文収録) | 154 | e-Gov 法令データ提供システム (CC-BY) — 全文検索対象 |
| 法令 (メタデータ stubs) | 9,484 | e-Gov 法令データ提供システム (CC-BY) — 法令名 resolver 用、本文ロード継続中 |
| 税務 ruleset | 35 | 国税庁 (インボイス + 電帳法) |
| 適格事業者 | 13,801 (delta-only) | 国税庁 (PDL v1.0) |
| entity-fact entities | 503,930 | 12 record_kinds |
| entity-fact facts | 6.12M | EAV schema |
| entity-fact relations | 23,805 | 14 canonical relation types |
| entity-fact aliases | 335,605 | 別名・略称 index |
| 法令条文 index | 28,048 | autonomath.db |
| 行政処分 詳細 records | 22,258 | autonomath.db |
| 排他ルール | 181 | 35 hand-seeded + 146 一次資料 auto-extracted |
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
| 課金プロセッサ | Stripe Metered + Stripe Tax |
| 国内インボイス対応 | 適格請求書発行事業者 (T8010001213708) |

## Infrastructure

| 項目 | 値 |
|---|---|
| API ホスティング | Fly.io Tokyo (nrt) リージョン |
| 静的サイト | Cloudflare Pages |
| データベース | SQLite + 日本語の高速全文検索 (jpintel.db 188 MB + autonomath.db 7.36 GB) |
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
