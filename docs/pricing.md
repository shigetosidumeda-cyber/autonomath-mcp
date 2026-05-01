<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Pricing",
  "description": "Free (匿名 3 req/日、IP ベース、JST 翌日リセット) + Paid (完全従量 ¥3/req 税別、税込 ¥3.30)。Starter / Pro / Enterprise tier は存在しない。契約・最低金額なし、いつでもカード登録/解除で開始/停止。",
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
    "@id": "https://jpcite.com/docs/pricing/"
  }
}
</script>

# Pricing

完全従量。tier プラン無し、最低額無し、契約無し。必要に応じて利用側で月次上限を設定してください。

| Plan | 単価 (税別) | Quota |
|------|-------------|-------|
| **Free** | ¥0 | 3 req/日 (匿名、IP ベース、JST 翌日 00:00 リセット) |
| **Paid** | **¥3 / req** (税込 ¥3.30) | 従量課金 |

## ¥3/req とは

- API / MCP の 1 リクエスト (検索・取得・排他チェック・provenance 等) に ¥3 (税別)
- `GET /healthz` と `GET /v1/meta` は **課金対象外**
- 1,000 req/月 ≒ ¥3,000、1 万 req/月 ≒ ¥30,000、10 万 req/月 ≒ ¥300,000 (税別)
- 消費税 10% は Stripe が自動計算・外税表示
- 請求は月次 (Stripe usage 集計)、クレジットカードのみ
- **Starter / Pro / Enterprise / Team / Seat は存在しない**

## 始め方

1. Free で試す (カード登録なし、IP ベース 3 req/日)
2. [Stripe Checkout](https://jpcite.com/pricing.html) でカード登録
3. `X-API-Key` を投げるだけで Paid に切替
4. ダッシュボードから Customer Portal を開き、カード削除または停止が可能

## Rate limit 仕様

- **Free (匿名):** 1 IP あたり 3 req/日、**JST 翌日 00:00** リセット
  - 超過時: `429`、body `{"detail":"anon rate limit exceeded","limit":3,"resets_at":"<翌日 JST 00:00>"}`
  - API key を投げない call が Free 扱い
- **Paid:** 従量課金。利用量は請求期間ごとに集計

## 請求書 / 適格請求書

- 決済: Visa / MasterCard / JCB / AmEx
- Stripe が自動でインボイス制度対応の適格請求書を発行・送付
- 領収書: Stripe hosted invoice PDF をダウンロード可

## 解約・返金

- **停止:** Stripe Customer Portal でカード除去 or サブスクリプション停止 → 以降の請求 ¥0
- **返金:** 誤課金や障害が疑われる場合は、利用状況を確認して個別対応します ([sla.md](./sla.md))

## 特定商取引法に基づく表記

[/tokushoho.html](https://jpcite.com/tokushoho.html)。

## FAQ (短縮)

- 使わない月は請求 ¥0
- カードを外せば即 Free に戻る
- API key は複数発行可 (Customer Portal)
- 契約書 / 個別 SLA は提供せず (完全セルフサーブ方針)
- リクエスト単価は ¥3/req で固定
