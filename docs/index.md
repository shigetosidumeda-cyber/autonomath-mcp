<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "税務会計AI Documentation",
  "description": "税務会計AI は、日本政府の公開制度データ (補助金・融資・税制・認定制度) 11,684 件 検索可能 (公開保留 2,788 件 別、合計 14,472 件) + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を一次資料 URL 付きで横断検索する REST API + MCP サーバー。Bookyou株式会社 (info@bookyou.net) が運営。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://zeimu-kaikei.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://zeimu-kaikei.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://zeimu-kaikei.ai/docs/"
  }
}
</script>

# 税務会計AI docs

> **要約 (summary):** 税務会計AI は、日本政府の公開制度データ (補助金・融資・税制・認定制度) 11,684 件 検索可能 (公開保留 2,788 件 別、合計 14,472 件) + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を一次資料 URL 付きで横断検索する REST API + MCP サーバー。検索・取得・排他ルール列挙を 1 API で叩ける (検索結果は一次資料で必ず確認)。

## 税務会計AI とは (What is AutonoMath)

日本の公的制度 (補助金・融資・税制・共済・認定制度) を、一次資料 URL 付きで横断検索できる **REST API + MCP サーバー** 。日本政府の公開データに対する検索インデックスを提供する。

- **11,684 プログラム 検索可能** (Tier S/A/B/C; 公開保留 2,788 件は別管理、合計 14,472 件) + **2,286 採択事例** + **108 融資 (担保・個人保証人・第三者保証人の三軸分解)** + **1,185 行政処分** を横断検索 (Tier ラベルは enrichment 充足度を表すもので、「正確性の保証」ではない)
- **181 件の排他ルール** (hand-seeded 35 = 農業 22 + 非農業 13 + 要綱 一次資料 auto-extracted 146) で「併用すると失格になる組み合わせ」を機械的に列挙。網羅性は保証しない (詳細は [exclusions.md](./exclusions.md))
- **MCP ネイティブ対応** — 89 ツール at default gates (39 jpintel: 制度 / 採択事例 / 融資 / 行政処分 + 拡張 [法令 / 判例 / 入札 / 税務ruleset / 適格事業者 + cross-dataset glue `trace_program_to_law` / `find_cases_by_law` / `combined_compliance_check` + one-shot 合成 `smb_starter_pack` / `subsidy_combo_finder` / `regulatory_prep_pack` / `subsidy_roadmap_3yr`] + 50 autonomath: entity-fact DB `503,930 entities / 6.12M facts / 23,805 relations` を `search_tax_incentives` / `reason_answer` / `search_by_law` 等で公開、加えてメタデータ tools 4 (`get_annotations` / `validate` / `get_provenance` / `get_provenance_for_fact`) と静的データセット tools (`list_static_resources_am` / `get_example_profile_am` 等) と **合成 tools + DD/監査支援 tools 計 10 本** [`apply_eligibility_chain_am` / `find_complementary_programs_am` / `simulate_application_am` / `track_amendment_lineage_am` / `program_active_periods_am` + `match_due_diligence_questions` / `prepare_kessan_briefing` / `forecast_program_renewal` / `cross_check_jurisdiction` / `bundle_application_kit`、各 tool 結果に `_next_calls` 連鎖ヒント + `corpus_snapshot_id` 監査再現 fields を埋め込み] と **業種特化 tools 3 本** [`pack_construction` / `pack_manufacturing` / `pack_real_estate` — 業種特化 cohort で top 10 補助金 + 5 saiketsu 引用 + 3 通達 を 1 req に集約])。Claude Desktop / Cursor / ChatGPT (Plus 以降) / Gemini から直接呼び出し、SDK 不要
- **一次資料 URL 付与** — 各行に `source_url` + `fetched_at` を付与。集約サイトは `source_url` から除外。検索結果は必ず一次資料 URL を開いて内容確認すること
- **全 self-serve** — サインアップ → Stripe → API key → 即利用。完全従量 ¥3/req 税別 (税込 ¥3.30)、匿名 50 req/月 無料 (JST 月初リセット、IP ベース)

## 誰のためか (Who is it for)

5 つの audience に合わせて、interface を選んで届ける。

- **税理士** — Claude に繋いで API を叩く。月数千円程度の従量課金。法改正は Email 通知。
- **行政書士** (建設業中心) — 案件の「使える補助金 + 融資 + 許認可」を 1 call で抽出。月 50 件まで無料で試す。
- **SMB 経営者** (本人 / 妻 / 経理) — LINE で「うちの業種の補助金ある?」と聞くだけ。月 10 件まで無料、超えても 1 質問 ¥3。
- **VC / M&A advisor** — 法人番号で行政処分歴 5 年 / 採択歴 10 年 / 適格請求書を 1 query で取得。due-diligence データ取込に組込み。¥3/req metered。
- **AI agent developer** — 89 MCP tools at default gates (39 jpintel + 50 autonomath; 合成 tools + DD/監査 tools + 業種特化 tools `pack_construction` / `pack_manufacturing` / `pack_real_estate` for 1-req cohort bundles)。¥3/req、50 req/月 free。Claude Desktop / Cursor 即動作。

詳しい利用者層別の使い方は [zeimu-kaikei.ai/#audiences](https://zeimu-kaikei.ai/#audiences) に。

## Jグランツ との違い (Position vs Jグランツ)

**Jグランツ** は経産省運営の公式 **申請ポータル** (補助金の申請・審査管理が目的)。**税務会計AI** は日本政府の公開データを横断検索する **API + MCP** で、11,684 件の制度 (検索可能、公開保留 2,788 件 別) + 2,286 採択事例 + 108 融資 + 1,185 行政処分を一次資料 URL 付きで返す — 目的とレイヤーが異なる。税務会計AI は申請を代行しない。

## 次のステップ (Next)

- [getting-started.md](./getting-started.md) — 5 分で最初のリクエスト
- [api-reference.md](./api-reference.md) — 全エンドポイント仕様
- [mcp-tools.md](./mcp-tools.md) — 89 の MCP ツール at default gates (39 jpintel + 50 autonomath; includes 合成 tools + DD/監査 tools + 業種特化 tools)
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [pricing.md](./pricing.md) — 料金プラン
- [faq.md](./faq.md) — よくある質問
