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

jpcite は Evidence prefetch layer です。長い PDF・複数の官公庁ページ・検索結果を LLM へ渡す前に、出典 URL・取得時刻・known gaps・互換/排他ルール付きの小さい Evidence Packet を返します。caller supplied baseline がある場合だけ、入力文脈量の削減見込みと break-even を返します。外部 LLM の請求額削減は保証しません。

完全従量。tier プラン無し、最低額無し、契約無し。必要に応じて利用側で月次上限を設定してください。

| Plan | 単価 (税別) | Quota |
|------|-------------|-------|
| **Free** | ¥0 | 3 req/日 (匿名、IP ベース、JST 翌日 00:00 リセット) |
| **Paid** | **¥3 / req** (税込 ¥3.30) | 従量課金 |

## ¥3/req とは

- API / MCP の 1 リクエスト (検索・取得・排他チェック・provenance 等) に ¥3 (税別)
- ヘルスチェックなど、課金対象外の運用 endpoint があります。従量対象は API reference とレスポンスヘッダーで確認できます。
- 1,000 req/月 ≒ ¥3,000、1 万 req/月 ≒ ¥30,000、10 万 req/月 ≒ ¥300,000 (税別)
- 消費税 10% は Stripe が自動計算・外税表示
- 請求は月次 (Stripe usage 集計)、クレジットカードのみ
- **Starter / Pro / Enterprise / Team / Seat は存在しない**

## 無料 3 回で確認すること

匿名 3 req/日 (IP 単位、JST 翌日 00:00 リセット) の代表的な検証フローで、課金前に下の 5 点を確認できます。

1. **出典 URL がある** — 主要な公開検索 / Evidence response の `source_url` がまとめサイトでなく省庁・自治体・公庫の一次資料
2. **`source_fetched_at` がある** — jpcite が出典を最後に取得した時刻 (最終更新ではない)。中央値 7 日
3. **Evidence Packet で `quality.known_gaps` を確認できる** — 未接続 / 未取得 / 未抽出 を黙って隠さない
4. **packet tokens vs baseline 比較が返る** — `GET /v1/intelligence/precomputed/query` に `source_tokens_basis=pdf_pages` + `source_pdf_pages` + `input_token_price_jpy_per_1m` を渡すと `compression.packet_tokens_estimate` / `source_tokens_estimate` / `input_context_reduction_rate` が返る
5. **`agent_recommendation.recommend_for_cost_savings` が true になる条件** — caller baseline と入力 token 単価が揃い、`break_even_met=true` の時のみ true。baseline なしなら必ず false で `cost_savings_decision=needs_caller_baseline`

## `break_even_met` の正しい読み方

`compression.cost_savings_estimate.break_even_met` は **入力文脈量だけの参考比較** です。

- `true` の意味: caller が渡した baseline (`source_pdf_pages` または `source_token_count`) と `input_token_price_jpy_per_1m` を使ったとき、`avoided_tokens × 単価 / 1,000,000 ≥ ¥3` (jpcite 1 req 単価) を満たしたという推定値
- `false` の意味: 上の式を満たさない、または caller baseline が未指定 (`needs_caller_baseline`)
- **含まないもの**: 出力 tokens、reasoning tokens、cache、provider tool / search 料金、為替、外部 LLM 側の請求仕様
- **保証しないもの**: 外部 LLM の請求額が必ず ¥3 安くなること、月額 LLM 費用が必ず下がること

レスポンス側でも `compression.savings_claim="estimate_not_guarantee"` と `compression.provider_billing_not_guaranteed=true` が常に付きます。AI が引用するときも「caller baseline 条件下の入力文脈削減見込み」 として扱ってください。

数式と用語は API リファレンスの「Context Compression」を参照。

## 始め方

1. **匿名 curl で動作確認** (`curl "https://api.jpcite.com/v1/programs/search?q=IT導入&limit=3"` — カード登録なし、IP ベース 3 req/日)
2. **Playground で残り 2 回を Evidence Packet に使う** (<https://jpcite.com/playground.html?flow=evidence3>) — `break_even_met` まで一通り確認
3. **MCP / OpenAPI で取り込む** ([Getting Started](./getting-started.md)) — 反復利用は MCP server か OpenAPI client から
4. **API キー発行** ([Stripe Checkout](https://jpcite.com/pricing.html)) で Paid に切替、`X-API-Key` を投げるだけ
5. ダッシュボードから Customer Portal を開き、カード削除または停止が可能

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

- **停止:** Stripe Customer Portal でカード除去 or サブスクリプション停止。停止後の新規従量課金は発生しません。停止前の利用分は請求対象です。
- **返金:** 誤課金や障害が疑われる場合は、利用状況を確認して個別対応します ([sla.md](./sla.md))

## 特定商取引法に基づく表記

[/tokushoho.html](https://jpcite.com/tokushoho.html)。

## FAQ (短縮)

- 使わない月は請求 ¥0
- カードを外せば即 Free に戻る
- API key は複数発行可 (Customer Portal)
- 契約書 / 個別 SLA は提供せず (完全セルフサーブ方針)
- 公開料金と匿名枠はこのページに掲載
