<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "税務会計AI Pricing",
  "description": "Free (匿名 50 req/月、IP ベース、JST 月初リセット) + Paid (完全従量 ¥3/req 税別、税込 ¥3.30、無上限)。Starter / Pro / Enterprise tier は存在しない。契約・最低金額なし、いつでもカード登録/解除で開始/停止。",
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
    "@id": "https://zeimu-kaikei.ai/docs/pricing/"
  }
}
</script>

# Pricing

> **要約 (summary):** Free (匿名 50 req/月、IP ベース、JST 月初 00:00 リセット) + Paid (完全従量 ¥3/req 税別、無上限)。Starter / Pro / Enterprise といった tier プランは **存在しない** 。契約・最低金額なし、いつでもカード登録/解除で開始/停止。

## 価格 (Price)

| Plan | 単価 (税別) | Quota | 対象 |
|------|-------------|-------|------|
| **Free** | ¥0 | 50 req/月 (匿名、**IP ベース**、JST 月初 00:00 リセット) | 試用・個人検証・サンプル取得 |
| **Paid** | **¥3 / req** | 無制限 (metered、税込 ¥3.30) | 商用・業務系エージェント・RAG |

- **¥3/req metered とは:** API / MCP の 1 リクエスト (検索・取得・排他チェック・provenance 取得・validate 等、課金対象 endpoint への 1 call) ごとに ¥3 (税別) が計上される。`GET /healthz` と `GET /v1/meta` は課金対象外。
- 1,000 req/月 ≒ ¥3,000、1 万 req/月 ≒ ¥30,000、10 万 req/月 ≒ ¥300,000 (いずれも税別)。
- 消費税 10% は Stripe で自動計算・請求書に外税表示。1 リクエスト税込 ¥3.30。
- 請求は月次 (Stripe 使用量ベース)、クレジットカードのみ。
- **Starter / Pro / Enterprise / Team / Seat のような tier SKU は存在しない。** プランは Free と Paid の 2 種類だけで、Paid の単価は誰がどれだけ叩いても一律 ¥3/req。

## なぜ従量 1 本 (Why pure metered)

- Tier を分けないので「どのプランが自分に合うか」の選定コストがゼロ。
- 最低月額 / 契約 / 解約違約金がない — 1 ヶ月使わなければ請求は ¥0。
- 使った分だけ。スパイクが来てもエラーで止まらない、来月の料金だけ増える。
- OpenAI / Anthropic / Stripe 自身が採用する形と同じ。

## 始め方 (Getting started)

1. Free で試す (カード登録なし、IP ベースで 50 req/月)
2. 評価を終えて本格利用に入る段階で [Stripe Checkout](https://zeimu-kaikei.ai/pricing.html) でカード登録
3. 以降は `X-API-Key` を投げるだけ、月次メーター請求に切り替わる
4. カードを外せばその場で Free に戻る (Stripe Customer Portal、`POST /v1/billing/portal`)

## Rate limit の仕様

- **Free (匿名):** 1 IP あたり **50 req/月** 、**JST 月初 00:00** に bucket リセット。超過は `429 Too Many Requests` (`{"detail":"anon rate limit exceeded","limit":50,"resets_at":"<次月 JST 00:00>"}`)。API key を投げない call が Free 扱いになる
- **Paid (認証済み):** hard cap なし。呼んだ分だけ Stripe に usage_records として報告。メーター集計期間は UTC 0 時基準 (Stripe subscription anchor date)。翌 UTC 月に請求
- `GET /healthz` / `GET /v1/meta` はどちらの plan でも **課金・カウント対象外**

## 支払い・請求書 (Invoicing)

- 決済: Stripe のクレジットカード (Visa / MasterCard / JCB / AmEx)
- 請求書: 毎月、Stripe が 適格請求書 (インボイス制度対応、登録番号 T8010001213708) を自動発行して送付
- 消費税: 10% 外税、請求書に別記
- 領収書: Stripe の hosted invoice PDF をダウンロード可能

## 解約・返金 (Cancellation & refunds)

- **停止:** Stripe Customer Portal でカードを外すか、サブスクリプションを停止。以降の請求は発生しない
- **返金:** デジタル役務のため原則不可。ただし重大な障害 (SLA breach) が生じた場合は個別に返金対応

## 特定商取引法に基づく表記

[/tokushoho.html](https://zeimu-kaikei.ai/tokushoho.html) を参照。

## FAQ

- Q: 使わない月は請求される? → A: いいえ。Paid でも usage が 0 なら請求 ¥0。
- Q: 途中で Free に戻せる? → A: はい、カードを外すだけで即座に Free に戻る。
- Q: API key を複数発行できる? → A: 可能。Stripe Customer Portal から追加発行/revoke。
- Q: Free だけで商用運用できる? → A: Free は「サンプル」位置付け (50/月)。業務で使うなら Paid を推奨。
- Q: 大量に叩く予定、契約書は? → A: 完全セルフサーブ / 自動化方針。契約書・個別 SLA は現時点で用意していません。
