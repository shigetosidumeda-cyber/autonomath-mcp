<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "AutonoMath Documentation",
  "description": "AutonoMath は、日本の制度データ (補助金・融資・税制・認定制度) 10,790 件 検索可能 (tier X 1,923 件 quarantine 別、合計 13,578 件) + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を REST API と MCP サーバーで提供する開発者向けプラットフォーム。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://autonomath.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://autonomath.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://autonomath.ai/docs/"
  }
}
</script>

# AutonoMath docs

> **要約 (summary):** AutonoMath は、日本の制度データ (補助金・融資・税制・認定制度) 10,790 件 検索可能 (tier X 1,923 件 quarantine 別、合計 13,578 件) + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を REST API と MCP サーバーで提供する開発者向けプラットフォーム。発見・互換性判定・排他チェック・実績確認を 1 API で叩ける。

## AutonoMath とは (What is AutonoMath)

日本の公的制度 (補助金・融資・税制・共済・認定制度) を、**AI アプリ開発者と企業内 RAG が叩ける REST API + MCP サーバー** で提供する開発者プラットフォーム。

- **10,790 プログラム 検索可能** (Tier S/A/B/C; tier X 1,923 件は quarantine、合計 13,578 件) + **2,286 採択事例** + **108 融資 (担保・個人保証人・第三者保証人の三軸分解)** + **1,185 行政処分** を横断検索 (Tier S/A/B/C/X 品質ラベル付き)
- **181 件の排他ルール** (hand-seeded 35 = 農業 22 + 非農業 13 + 要綱 一次資料 auto-extracted 146) で「併用すると失格になる組み合わせ」を事前検出
- **MCP ネイティブ対応** — 72 ツール at default gates (39 jpintel: 制度 / 採択事例 / 融資 / 行政処分 + 拡張 [法令 / 判例 / 入札 / 税務ruleset / 適格事業者 + cross-dataset glue `trace_program_to_law` / `find_cases_by_law` / `combined_compliance_check` + one-shot 合成 `smb_starter_pack` / `subsidy_combo_finder` / `regulatory_prep_pack` / `subsidy_roadmap_3yr`] + 33 autonomath: entity-fact DB `503,930 entities / 6.12M facts / 23,805 relations` を `search_tax_incentives` / `reason_answer` / `search_by_law` 等で公開、加えて V4 universal 4 (`get_annotations` / `validate` / `get_provenance` / `get_provenance_for_fact`) と Phase A absorption (`list_static_resources_am` / `get_example_profile_am` 等))。Claude Desktop / Cursor / ChatGPT (Plus 以降) / Gemini から直接呼び出し、SDK 不要
- **全件一次資料リンク** — `source_url` + `fetched_at` を全行に付与、アグリゲータ排除済み
- **全 self-serve** — サインアップ → Stripe → API key → 即利用。完全従量 ¥3/req 税別 (税込 ¥3.30)、匿名 50 req/月 無料 (JST 月初リセット)

## 誰のためか (Who is it for)

5 つの audience に合わせて、interface を選んで届ける。

- **税理士** (5 名事務所・SMB 顧客 80 社) — Claude に繋いで API を叩く。月 ¥1,000 前後の従量。法改正は Email 通知。
- **行政書士** (建設業中心) — 案件の「使える補助金 + 融資 + 許認可」を 1 call で抽出。月 50 件まで無料で試す。
- **SMB 経営者** (本人 / 妻 / 経理) — LINE で「うちの業種の補助金ある?」と聞くだけ。月 10 件まで無料、超えても 1 質問 ¥3。
- **VC / M&A advisor** — 法人番号で行政処分歴 5 年 / 採択歴 10 年 / 適格請求書を 1 query で取得。due-diligence パイプラインに組込み。¥3/req metered。
- **AI agent developer** — 72 MCP tools at default gates (39 jpintel + 33 autonomath)。¥3/req、50 req/月 free。Claude Desktop / Cursor 即動作。

詳しい audience 別ピッチは [autonomath.ai/#audiences](https://autonomath.ai/#audiences) に。

## Jグランツ との違い (Position vs Jグランツ)

**Jグランツ** は経産省運営の公式 **申請ポータル** (補助金の申請・審査管理が目的)。**AutonoMath** は **発見・互換性・排他チェック・実績確認の API** で、10,790 件の制度 (検索可能、tier X 1,923 件 quarantine 別) + 2,286 採択事例 + 108 融資 + 1,185 行政処分を横断し、MCP ネイティブ統合を提供する — 目的とレイヤーが異なる。

## 次のステップ (Next)

- [getting-started.md](./getting-started.md) — 5 分で最初のリクエスト
- [api-reference.md](./api-reference.md) — 全エンドポイント仕様
- [mcp-tools.md](./mcp-tools.md) — 72 の MCP ツール at default gates (39 jpintel + 33 autonomath)
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [pricing.md](./pricing.md) — 料金プラン
- [faq.md](./faq.md) — よくある質問
