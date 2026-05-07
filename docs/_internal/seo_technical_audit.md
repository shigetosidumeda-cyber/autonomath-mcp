# SEO / AI Indexability Technical Audit

> 2026-04-23 初版 / Owner: 梅田茂利 / launch 2026-05-06 向け
> scope: `site/` のすべての HTML、`site/sitemap.xml`、`site/robots.txt`、`.well-known/`、JSON-LD。
> 目的: Google + AI indexer (ChatGPT / Claude / Perplexity / Gemini) の双方に正しく拾われる構造にする。
> placeholder: 本書および関連 file 内の `{{DOMAIN}}` は rebrand 決定後に置換 (`project_jpintel_trademark_intel_risk` 参照)。

---

## 1. 結論 (TL;DR)

- landing / pricing / status は crawlable で signal も揃っている。index.html に JSON-LD の `SoftwareApplication` が既にあり、1 本で Organization + WebSite 相当が足りていないのが唯一の穴。
- tos / privacy / tokushoho の 3 本は `<meta name="robots" content="noindex">` が付いていて公開 crawl から外れる。これは正しい選択だが、**サイトの中心コンテンツが実質 index + pricing + status の 3 本しかない**状態は AI indexer に薄く見える。
- robots.txt が `User-agent: *` 一行だけで AI crawler 区別が無い。Google-Extended / GPTBot / ClaudeBot / PerplexityBot / CCBot の 5 種を明示しておく必要あり。
- `llms.txt` 未配置。emerging spec に従い 1 本追加すべき。
- hreflang は日本語単一なので不要に見えるが、Google guideline は **x-default と hreflang=ja のセット**を推奨、単一言語でも追加コストがほぼゼロなので付ける。
- 個別制度 URL (`/programs/{unified_id}`) は未存在。本 audit では **option (a): SSG で ~5,100 件生成** を選択。理由は下段。

---

## 2. 現行ページの crawlability 監査 (snapshot 2026-04-23)

| ページ | `<title>` | `<meta description>` (JP 文字数 目安) | `<link rel=canonical>` | `<meta name=robots>` | `<html lang="ja">` | 判定 |
|--------|-----------|------|---------|----------|---------|------|
| `/` (`index.html`) | O | O (56 文字) | O | 未指定 (= `index,follow`) | O | OK |
| `/pricing.html` | O | O (28 文字) | O | 未指定 | O | OK (description 薄め) |
| `/tos.html` | O | O (15 文字) | O | `noindex` | O | 意図通り (法務) |
| `/privacy.html` | O | O (16 文字) | O | `noindex` | O | 意図通り |
| `/tokushoho.html` | O | O (23 文字) | O | `noindex` | O | 意図通り |
| `/status.html` | O | O (40 文字) | O (`/status`) | `noindex, follow` | O | OK (運用ページ) |
| `/dashboard.html` | O | O (31 文字) | O | `noindex,nofollow` | O | 意図通り (ログイン) |
| `/success.html` | O | O (20 文字) | O | `noindex,nofollow` | O | 意図通り (薄いコンテンツ) |

**所見**
- 日本語文字数は全て 120 JP 文字以内、Google SERP truncation line (~80-120 全角) 以内に収まっている。
- `pricing.html` の description は 28 文字と短く、AI 要約取込時に物足りない。`10,790 件の制度 API の料金。Free 50 req/月 (IP) + Paid ¥3/billable unit 従量、Stripe self-serve、MCP + REST 両対応。` のように具体化を推奨 (下段 quick wins に計上)。
- 全ページ `<html lang="ja">`、`<meta charset="UTF-8">`、viewport も正しい。

---

## 3. 日本語 SEO 固有チェック

- **Katakana-only phrasing の過多**: index.html `hero-sub` 「Exclusion-aware. MCP-native.」は dev 向け英語がそのまま。Google JP は Katakana-only 回避と漢字混合を好むが、ここは dev 向け ICP (ターゲットが日本の API 開発者) なので英語残存は許容。**JA 読み手が混乱する katakana 冗長表現は検出されず**。
- **description の前置き語**: 全ページ「AutonoMath の …」で始まっており、重複前置きが SERP で同じ "AutonoMath" 連呼になる。launch 時には冒頭を主語 (制度 API 6,658件…) に寄せたい。
- **h1 の重複なし**: 全ページ h1 1 本、重複や欠落なし (schema.org 非準拠の ambiguous heading も無し)。
- **alt 属性**: `assets/demo.svg` に alt 付き。`<img>` 全件確認、欠落なし。
- **Japanese font stack**: status.html inline CSS に Hiragino/Meiryo/Yu Gothic 指定あり。styles.css は未確認だが landing は正しく日本語表示。

---

## 4. Core Web Vitals 推定

静的 HTML + 単一 stylesheet + defer JS 1 本 (`analytics.js`) のみ。bundler 無し。

- **LCP**: 最大要素は index hero 内の `assets/demo.svg` (6.1 KB) または og hero なし → text LCP ~0.5-0.8s を見込む (Cloudflare Pages edge cache 前提)。**Good 閾値 2.5s 内に余裕**。
- **CLS**: hero / card / pricing table 全て固定サイズ。`<img>` の width/height 属性は `style="width:100%;max-width:720px"` で reserved。**< 0.05 を期待**。
- **INP**: JS が newsletter form の 1 handler のみ、body 50 行。**< 50ms**。

**画像サイズ audit** (>100KB のもの):
- `og.png` 33.9 KB / `og-twitter.png` 33.2 KB / `og-square.png` 48.4 KB → **いずれも 100 KB 未満、WebP 変換のコスパ低**。
- ただし **OG image は PNG が広く互換**、X / Slack / Facebook / LinkedIn で確実に render する。AVIF/WebP に変換すると LinkedIn 等で失敗するため **PNG のままを推奨**。landing 内で使用する `demo.svg` は既に SVG (text).

---

## 5. Schema.org (JSON-LD) 監査

### 5.1 現状
- `index.html` に `SoftwareApplication` JSON-LD 1 本あり、offers / featureList 記載済。
- `pricing.html` には JSON-LD 無し。
- `docs/json_ld_strategy.md` は **個別制度 `/structured/{id}.jsonld`** を 6,772 本静的配信する計画 (W5-W8)。本 audit と競合せず、SSG `/programs/{id}.html` の内部に **同じ JSON-LD を `<script type="application/ld+json">` で embed** する形で再利用する。

### 5.2 追加すべき block (index.html)
SoftwareApplication の横に `Organization` + `WebSite` + `BreadcrumbList` 相当を追加:

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "AutonoMath",
  "url": "https://{{DOMAIN}}/",
  "logo": "https://{{DOMAIN}}/assets/logo.svg",
  "sameAs": ["https://github.com/{{GH_ORG}}/AutonoMath"],
  "contactPoint": {
    "@type": "ContactPoint",
    "email": "hello@{{DOMAIN}}",
    "contactType": "customer support"
  }
}
```

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "AutonoMath",
  "url": "https://{{DOMAIN}}/",
  "inLanguage": "ja",
  "potentialAction": {
    "@type": "SearchAction",
    "target": "https://{{DOMAIN}}/dashboard.html?q={search_term_string}",
    "query-input": "required name=search_term_string"
  }
}
```

これで Google Knowledge Graph と AI crawler の両方に `Organization` シグナルが入る。SearchAction は Google sitelinks searchbox の入り口になりうるが、表示されなくても機能としては無害。

### 5.3 個別制度ページ (SSG) の JSON-LD
`docs/json_ld_strategy.md` §4 の mapping をそのまま再利用。HTML 埋め込みと `/structured/{id}.jsonld` 静的ファイル両方に同内容を書く (AI crawler は HTML 内 JSON-LD を好むため両立が最適)。

---

## 6. AI crawler 対応

### 6.1 ボット別方針

| Bot UA | 運営 | 用途 | 方針 |
|--------|------|-----|------|
| `Googlebot` | Google Search | 検索 index | **Allow** |
| `Googlebot-Image` | Google Images | 画像検索 | **Allow** |
| `Google-Extended` | Google | Bard/Gemini 訓練 | **Allow** (公的情報の再配布であり moat) |
| `Bingbot` | Microsoft | 検索 index (Perplexity の根っこでもある) | **Allow** |
| `GPTBot` | OpenAI | ChatGPT 訓練 / 回答参照 | **Allow** |
| `ChatGPT-User` | OpenAI | ChatGPT browse | **Allow** |
| `OAI-SearchBot` | OpenAI | SearchGPT index | **Allow** |
| `ClaudeBot` | Anthropic | Claude 訓練 / 回答参照 | **Allow** |
| `anthropic-ai` (旧 UA) | Anthropic | legacy | **Allow** |
| `PerplexityBot` | Perplexity | 回答参照 | **Allow** |
| `CCBot` | Common Crawl | 一般クロール (LLM 訓練データ源) | **Allow** |
| `Bytespider` | ByteDance | 訓練 (aggressive 報告多) | **Block** |
| `AhrefsBot` | Ahrefs | 競合 SEO tool | **Block** |
| `SemrushBot` | Semrush | 同上 | **Block** |
| `MJ12bot` | Majestic | 同上 | **Block** |
| `DotBot` | Moz | 同上 | **Block** |

方針の柱は **「一次情報を AI 訓練コーパスに載せることが moat」** (`docs/json_ld_strategy.md` §1 とも整合)。

### 6.2 `llms.txt` (emerging spec, `/llms.txt`)

`llms.txt` は `robots.txt` の LLM 版で、LLM が**人間向け HTML ではなく plain text docs にジャンプする導線**を提供する初期 spec。roots: `https://llmstxt.org/`。記法は markdown + absolute URL list。

内容はシンプルに 1 行概要 + key docs の URL 列挙にとどめる (spec 準拠、詐欺や宣伝は NG)。

### 6.3 Plaintext doc mirrors

`docs/*.md` はそのままでも AI crawler がパースできるが、markdown codeblock が AI summary 時に破損しやすい。以下を `site/llms/` にコピー (純テキスト、frontmatter なし):
- `index.md` → `site/llms/index.txt`
- `getting-started.md` → `site/llms/getting-started.txt`
- `api-reference.md` → `site/llms/api-reference.txt`
- `mcp-tools.md` → `site/llms/mcp-tools.txt`
- `faq.md` → `site/llms/faq.txt`

これはまず llms.txt 側で参照できる URL を揃えるための低コスト手段。本 audit では一覧化のみで、実コピーは launch 直前 cron で自動化する (別タスク)。

---

## 7. hreflang / i18n

現状 JP 単一。Google guideline は **単一言語でも x-default と自身を明示**することで "hreflang 未設定 → multi-locale 不明" の状態を回避できる。各 HTML `<head>` に:

```html
<link rel="alternate" hreflang="ja" href="https://{{DOMAIN}}/" />
<link rel="alternate" hreflang="x-default" href="https://{{DOMAIN}}/" />
```

を追加。pricing / legal も同様 (URL を page 別に置換)。将来英語版ができたら `hreflang="en"` 行を追加するだけ。

---

## 8. 個別制度ページ生成 (option picked: **a**)

3 option の比較:

| option | 概要 | 問題点 | AI index 効果 |
|--------|------|-------|-------------|
| **a** | SSG で 5,100 HTML を生成 (tier X / noukaweb / source_url 空を除外) | ストレージ数百 MB、Cloudflare Pages 限界内。programmatic 薄 HTML = Panda risk | HTML + JSON-LD 両刀で最大 |
| b | 当面 HTML 無し、JSON-LD だけ配信 | 人間 crawler とブラウザに露出しない | 弱 |
| c | dashboard 検索に hash fragment で誘導 | fragment は Google に index されない | 無効 |

**option a を採用**。Panda risk は以下で緩和:
- 各ページ 400-800 字の本文 (認可主体名、対象者、金額レンジ、窓口 URL、申請ガイド一般論、注意事項)
- `isBasedOn` で一次 URL 明示
- `canonical` を自ページに固定
- description は制度 summary を truncate (120 JP 文字以内)
- 1 制度 1 URL、alias は alternate に寄せず本ページ内に `alternateName` として登場 (重複 URL は発生させない)

生成対象 row 条件 (SQLite):
```sql
SELECT COUNT(*) FROM programs
WHERE excluded = 0
  AND tier IN ('S','A','B','C')
  AND source_url IS NOT NULL AND source_url <> ''
  AND authority_name NOT LIKE '%noukaweb%';
-- → 5,221 (2026-04-23 スナップショット時点)
```

SSG 出力: `site/programs/{unified_id}.html` (5,221 本) + index list `site/programs/index.html` (任意、ヒューマン用)。

---

## 9. sitemap 方針

- `site/sitemap.xml` — 静的 HTML の entry (index, pricing, dashboard は公開可なら、legal は noindex のため除外)。**dashboard は /dashboard が会員用のため noindex、sitemap にも含めない**。
- `site/sitemap-programs.xml` — 個別制度 HTML 5,221 URL。priority 0.4、changefreq monthly、lastmod は `programs.updated_at`。
- Sitemap index `site/sitemap-index.xml` を top に置き両者を参照。launch 後の GSC / Bing submit は index のみ。

50,000 URL / 50 MB 上限は余裕。将来 JSON-LD sitemap (json_ld_strategy §3) も sitemap index に追加する前提。

---

## 10. robots.txt 新設

現行は 3 行のみ。AI crawler 細分化 + 低価値 disallow + sitemap 2 本を明示する新版に差し替え (§3 別 file)。

---

## 11. 競合比較 (反面教師)

`docs/competitive_watch.md` ベースで観測した **やってはいけない例**:
- hojokin.ai: 補助金一覧ページで同一 title variant (都道府県名だけ挿し替え) 数百本 → doorway page risk。**本プロジェクトでは unified_id 単位の unique page に留め、都道府県 combination の組み合わせ爆発は作らない**。
- 補助金ポータル系: hidden keyword stuffing (白地白文字) が一部観察。**禁止事項、コード側で machinery 的に防ぐ**。
- 補助金クラウド: 個別制度ページが JS 描画依存 → AI crawler が拾えない。**本プロジェクトは SSG 前提、crawler が JS 無しで content を読める**。

---

## 12. 成果物一覧 (本 audit と同時 commit)

| file | 役割 |
|------|------|
| `docs/seo_technical_audit.md` | 本書 |
| `site/sitemap.xml` | 静的 HTML sitemap (差替) |
| `site/sitemap-programs.xml` | 個別制度 sitemap (placeholder 1 URL、生成後に拡張) |
| `site/sitemap-index.xml` | 上 2 つを parent 参照 |
| `site/robots.txt` | AI crawler 明示 + 低価値 block (差替) |
| `site/llms.txt` | LLM indexer 用 index |
| `site/_templates/program.html` | 個別制度の Jinja2 template |
| `scripts/generate_program_pages.py` | SSG generator |
| `site/programs/_samples/*.html` | 3 サンプル生成済 |

---

## 13. 今後の運用 (launch 後)

- ingest cron (毎月) 後に `scripts/generate_program_pages.py` を GHA で回す
- `sitemap-programs.xml` は SSG 時に同時生成
- GSC / Bing にサイトマップ提出 (domain 決定後)
- AI mention probe (`docs/json_ld_strategy.md` §8) と同じ cadence で週次集計
- 画像サイズ超過 (>100 KB) や CLS 悪化は Lighthouse CI で監視 (後日 `.github/workflows/lighthouse.yml` を追加予定)

---

最終更新: 2026-04-23 初版
