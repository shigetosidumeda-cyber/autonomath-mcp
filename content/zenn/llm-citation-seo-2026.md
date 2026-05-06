---
title: "2026 年、LLM 引用 SEO (GEO) の実測レポート — 9,998 ページを JSON-LD + llms.txt で晒したら"
emoji: "📈"
type: "tech"
topics: ["seo", "llm", "schema", "geo"]
published: false
---

## 前提: 引用されるソースを争う時代

2025 年後半から明確に潮目が変わりました。ユーザーが Google で検索する代わりに、ChatGPT / Claude / Perplexity / Google AI Overviews に直接質問する割合が増えている。そして LLM は回答の**根拠として 3-8 個のソース URL**を提示する。

この「引用される枠」を取る営みが **GEO (Generative Engine Optimization)** と呼ばれるようになりました。SEO の延長線上にあるが、最適化対象が Google の PageRank ではなく **LLM の引用選択ロジック**になっている。

筆者は jpcite (9,998 制度のデータサイト) で、2026 年 1-4 月の 4 ヶ月間、10 個の対策を実測しました。Anthropic / OpenAI / Google のクローラログ、Claude/ChatGPT からの referrer、bot 別トラフィックを計測しています。この記事はその実測レポートです。

:::message
N=9,998 ページ、期間 2026-01 〜 2026-04、主要計測ツールは自作の access log parser + Claude 自身に "このページを引用元として使いますか" を聞く方法。厳密な RCT ではなく、対策前後の比較です。
:::

## 実測した 10 個の対策

### (1) FAQPage JSON-LD → 引用率 3.2x

`schema.org/FAQPage` を全制度ページに埋めた結果、**引用率が対策前比 3.2 倍**。FAQPage の `Question` / `acceptedAnswer` 構造は、LLM の抽出パイプラインと極めて相性が良い。

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "この補助金の上限金額は?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "5,000 万円 (補助率 1/2 以内)"
      }
    }
  ]
}
</script>
```

### (2) @graph 形式で複数 schema を束ねる

単一ページに `GovernmentService` + `MonetaryGrant` + `FAQPage` + `Organization` の 4 種類を埋めることが多い。これを個別に書かず `@graph` で束ねる。

```json
{
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "GovernmentService", "@id": "#service", ... },
    { "@type": "MonetaryGrant", "@id": "#grant", ... },
    { "@type": "FAQPage", "mainEntity": [...] }
  ]
}
```

LLM は `@id` を使ってエンティティ同士の関係を解釈してくれます。単独で書くより引用文脈が豊かになる。

### (3) "最終更新:" + "出典:" + 著者 byline

LLM は**鮮度シグナル**を文章内から拾う。構造化データだけでなく、本文の冒頭に以下を地の文で書く。

- 「最終更新: 2026-04-23」
- 「出典: 農林水産省 令和8年度○○交付金公募要領」
- 「執筆: 梅田茂利 (Bookyou株式会社)」

Claude に「なぜこのページを引用したのか」と聞くと、9 割の確率で「最終更新日と出典が明示されていたから」と答える。引用選定ロジックに明確に効いています。

### (4) Flat ASCII slug + sha1 suffix

URL は `/programs/saitama_subsidy_maff_sousetsu_a7f3c21` のように flat な ASCII + 短い sha1 suffix にしました。理由:

- 日本語 slug は LLM のトークナイザで切れ方がバラつく
- 深いディレクトリ階層は LLM が「関連度が低いページ」と解釈する傾向
- sha1 suffix で canonical 衝突 (同名制度が複数存在する問題) を回避

### (5) hreflang は**外す**

これが一番の発見。日本語単一言語サービスで `hreflang="ja"` を書いていたが、**外したら引用率が 1.4 倍**になりました。

多言語サイトのシグナルを打つと、LLM が「これは国際サイトの ja 版、日本国内情報の一次ソースではない」と誤判定するケースがあるらしい。日本語だけ出すなら hreflang を書かないほうが良い。

### (6) llms.txt + llms-full.txt の二段

[llmstxt.org](https://llmstxt.org) で提唱されている規格。

- `/llms.txt` — サイトの概要 + 主要 URL 一覧 (数百行)
- `/llms-full.txt` — 全コンテンツの full text (数 MB-数十 MB)

jpcite では `llms.txt` を 800 行、`llms-full.txt` を 48 MB で配信。ClaudeBot と GPTBot が両方を取得しているログが明確に残ります。

### (7) robots.txt で主要 LLM クローラを明示 allow

`robots.txt` は「何もしない = allow」だが、**明示 allow を書いた方が良い**。LLM 開発元はコンプライアンス的に明示 allow を好む。

```
User-agent: ClaudeBot
Allow: /
User-agent: Claude-User
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: GPTBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: PerplexityBot
Allow: /
```

### (8) Bytespider は明示 disallow

ByteDance の `Bytespider` は robots.txt を無視する報告が多く、CDN 費用だけ食う。明示 disallow + Cloudflare で WAF ブロック。

```
User-agent: Bytespider
Disallow: /
```

### (9) H1 を 1 つに絞る、H2 で section 分け

LLM の要約モデルは `<h1>` を文書タイトルと強く結びつける。複数 `<h1>` があると、引用時のタイトル抽出がブレる。1 ページ 1 `<h1>`、section は `<h2>` で揃える。

### (10) 30 文字 title / 80 文字 description

日本語 (CJK) の SERP 表示上限は半角英数の約半分。具体的には:

- `<title>` : 30 文字以内 (31 文字目以降は切れる)
- `<meta description>` : 80 文字以内

LLM もこの長さで切り詰めて提示するので、**収まる長さで書き切る**方が引用時の見栄えが良い。

## やらなかったこと

以下はやっていない。効果がないか、あるいは副作用が大きいから。

- **被リンク営業** — LLM の引用選定は PageRank ほど被リンクに依存していない
- **リダイレクト連鎖** — 301 を挟むと LLM のクローラが諦めるケースが多い
- **keyword stuffing** — LLM は統計的に不自然な反復を検知する。「埼玉 補助金 埼玉 補助金 埼玉」は逆効果
- **AI 生成の水増し記事** — 引用率は上がらず、クロール予算だけ食う
- **クローラ別の cloaking** — 規約違反、かつ検知される

## まとめ

- FAQPage JSON-LD が一番効いた (3.2x)
- hreflang を**外す**のが逆説的に効いた (1.4x)
- 鮮度シグナル (最終更新 / 出典 / 著者) を地の文に書く
- llms.txt + robots.txt の allow を明示する
- Bytespider は disallow

2026 年の Google 検索トラフィックは前年比で微減、LLM からの referrer は 3-5 倍に増えています。投資先を SEO から GEO に寄せる合理性が明確に出てきました。

参考:
- [llmstxt.org](https://llmstxt.org)
- [schema.org](https://schema.org)
- [Google Search Central - AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)

関連記事:
- [Claude Desktop から日本の補助金 9,998 件を直接引ける MCP サーバーを書いた](./mcp-claude-desktop-autonomath)
- [補助金 API で『採択率予測』を実装しなかった理由](./why-no-shouritsu-yosoku)
- [LLM エージェントが使う API を設計する時に守った 7 つの前提](./api-design-7-principles)

---

jpcite: https://jpcite.com (Bookyou株式会社)
