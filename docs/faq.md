<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite FAQ",
  "description": "jpcite についてよく聞かれる質問。更新頻度・データソース・法律相談/申請代行の対象外・SLA・解約・rate limit リセット等。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-29",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com/"
  },
  "publisher": {
    "@type": "Organization",
    "name": "jpcite",
    "logo": {
      "@type": "ImageObject",
      "url": "https://jpcite.com/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/faq/"
  }
}
</script>

# FAQ

## Q1. 更新頻度

canonical データは **月次再 ingest** が基本。日次差分は順次導入。最新タイムスタンプは `GET /v1/meta` の `last_ingested_at` / `data_as_of` で確認。

## Q2. データソース

主要な公開レコードは **日本政府・自治体・公的機関の一次資料** から取得しています (集約サイトは出典として使いません)。出典が接続済みのレコードでは `source_mentions` (URL + fetched_at) を返し、未接続の根拠は `quality.known_gaps[]` や `/v1/source_manifest/{program_id}` で確認できます。

- 農林水産省 / 経済産業省 / 中小企業庁
- 日本政策金融公庫 (JFC)
- 各都道府県・市区町村 公式サイト
- e-Gov 法令検索
- 環境省 / 厚生労働省 etc.

## Q3. 法的・税務アドバイスか?

**いいえ**。jpcite は検索 API です。法律相談、税務代理、行政書士業務、申請代行は提供しません。詳細: [honest_capabilities.md](./honest_capabilities.md)。

## Q4. 解約方法

`POST /v1/billing/portal` で Stripe Customer Portal URL を取得 → ブラウザで解約。当期末まで API key 有効、次期から revoke。詳細: [pricing.md](./pricing.md)。

## Q5. データ正確性は保証されるか?

API は出典 URL の付与と検索を提供します。一次資料の内容そのものについて再配布元としての正確性保証は行いません。主要公開レコードでは、出典の追跡可能性のために `source_url` + `fetched_at` を付与しています。tier ラベルは enrichment 充足度を表す指標です:

- **Tier S (114):** 主要次元ほぼ全て enriched
- **Tier A (1,340):** 主要次元 enriched、一部 null
- **Tier B (4,186):** 部分 enriched、対応範囲は中程度
- **Tier C (5,961):** sparse、基本情報のみ

重要判断では、各レコードで利用可能な `source_url` の一次資料と `/v1/source_manifest/{program_id}` を確認してください。誤りを見つけた場合は、特商法ページの連絡先からご連絡ください。

## Q6. 日本語 / 英語

API response / MCP tool description は **日本語 primary**。制度名・要綱は日本語のまま返却。field 名は英語 snake_case。

## Q7. 法人 / エンタープライズ契約

完全セルフサーブのため、個別契約・個別見積・請求書払い・専用 SLA は提供しない。Free + Paid (¥3/billable unit) のみ。

## Q8. SLA

[sla.md](./sla.md) — 月次 99.0% の稼働目標と計測方法。公開状況: `https://jpcite.com/status.html`。

## Q9. オフライン / self-host

`pip install autonomath-mcp` で **MCP server はローカル起動**できますが、PyPI wheel には本番 SQLite DB は同梱されません。ローカル DB 未設定時は `api.jpcite.com` への HTTP fallback を使います。

## Q10. Rate limit リセット

- **匿名 (Free):** JST 翌日 00:00、IP 単位、日次
- **Paid (認証済み):** 従量課金。予算上限や保護レート制限が適用される場合があります。Stripe メーター集計は UTC 0 時基準です。

匿名超過時: `429`、body `{"detail":"anon rate limit exceeded","limit":3,"resets_at":"<翌日 JST 00:00>"}`

## Q11. API key の revoke / rotate

- **自動 revoke:** サブスクリプション解約時に webhook (`customer.subscription.deleted`) で `revoked_at` セット
- **手動 rotate:** Customer Portal で解約 → 再契約で新 key 発行
- **即時 revoke (漏洩時):** 特商法ページの連絡先へ連絡

## Q12. MCP クライアント対応

- Claude Desktop / Cursor / Cline などの MCP クライアントで利用できます
- ChatGPT Custom GPT では OpenAPI Actions 経由で同等の REST endpoint を呼び出します
- 共通で stdio 転送、設定例は [getting-started.md](./getting-started.md)

## Q13. 排他ルール網羅性

181 件の登録済みルールを確認します。`hits: []` でも「併用安全」を保証しません。詳細: [exclusions.md](./exclusions.md)。

## Q14. 日本語 FTS 挙動

- 3 文字以上: 全文検索インデックス (3-gram)
- 2 文字以下: substring 一致 (`primary_name` / `aliases_json`)

3 文字以上推奨。

## Q15. 商用利用 / 再配布

- **API 内利用:** 自社プロダクト内での参照・表示は OK (Free / Paid 両方)
- **bulk 再配布:** 元データのライセンスは出典ごと異なる (e-Gov 法令 = CC-BY 4.0、国税庁 適格事業者 = PDL v1.0、JST = proprietary 等)。再配布前に各 record の `source_url` ライセンス条件を確認
- **出典明記:** 必須 (`official_url` / `source_urls` をユーザーに提示、集約サイト経由ではなく一次資料 URL を表示)

## サポート

- GitHub issues: <https://github.com/shigetosidumeda-cyber/autonomath-mcp/issues>
- 連絡先: [特定商取引法に基づく表記](./compliance/tokushoho.md)

## 関連

- [index.md](./index.md) — 概要
- [getting-started.md](./getting-started.md) — 導入
- [api-reference.md](./api-reference.md) — REST API
- [mcp-tools.md](./mcp-tools.md) — MCP ツール
- [pricing.md](./pricing.md) — 料金
- [exclusions.md](./exclusions.md) — 排他ルール
