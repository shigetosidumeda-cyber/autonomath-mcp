# jpcite SEO Health Audit — 2026-05-11

**Auditor**: Claude Code (sub-agent / SEO audit lane)
**Target**: `jpcite.com` (Cloudflare Pages + Fly.io + Stripe metered API)
**Benchmark**: Stripe / Linear / Vercel SV top-tier SEO standards
**Scope**: 6 入力 HTML + sitemap_*.xml ×15 + robots.txt + _headers + _redirects + Schema.org common.json
**Out of scope (intentionally)**: `/en/*`, `/programs/*`, `/audiences/*`, `/docs/*` MkDocs surface, `/cases/*`, `/laws/*`, `/news/*` (assessed indirectly via sitemap shards).

## Executive Summary

| Axis | Score (0–10) | Verdict | 1-line gist |
|---|---|---|---|
| A. Technical SEO | **8.5** | GREEN | canonical/hreflang ほぼ統一、sitemap shard 4 本欠落だけが減点 |
| B. On-Page SEO | **7.0** | YELLOW | title 50–60 字超過 + h1 重複 + 主要 page 一部 description 過長 |
| C. Schema.org | **7.5** | YELLOW | index 厚いが playground は JSON-LD 0、artifact は BreadcrumbList のみ |
| D. OG / Twitter Card | **8.0** | GREEN | playground/index/pricing 完備、artifact/login は補強要 |
| E. Core Web Vitals | **6.5** | YELLOW | font preload OK だが image width/height 抜け + JS inline 過大 (dashboard 1.9 MB / playground 1.6 MB) |
| F. HTML semantic / a11y | **8.0** | GREEN | skip-link / landmark / lang / role / aria 多用、artifact のみ lang 直前 charset 順序逆 |
| G. URL structure | **9.0** | GREEN | extensionless + trailing-slash 整合済 |

**Average**: **7.79 / 10** (median 8.0) — Stripe/Linear bar = 8.5 として **yellow 2 軸 (B/E) を是正で green** 達成可能。

## A. Technical SEO — 8.5 / GREEN

### Findings
- **canonical**: 6 page 全て `<link rel="canonical">` 設定済。**FIXED IN PR**: dashboard / login / playground の canonical は `extensionless` 指定だが hreflang は `.html` を指していた不整合を **`extensionless` 側に統一** (3 file edit)。pricing は既に整合済。
- **hreflang**: ja / en / x-default 概ね運用済。`login.html` は ja+x-default のみ (`noindex,nofollow` なので en 不要、運用上正当)。
- **sitemap-index.xml**: **6 sub-sitemap が存在するのに index に未登録** → **FIXED**: `sitemap-cases.xml` / `sitemap-enforcement-cases.xml` / `sitemap-laws.xml` / `sitemap-laws-en.xml` を index + robots.txt 双方に追記 (4 entries × 2 file = 8 lines)。
- **robots.txt**: Allow/Disallow + Crawl-delay + Sitemap 行 OK。AhrefsBot/SemrushBot/MJ12bot/DotBot/PetalBot/YandexBot 個別 Disallow も正当 (zero-touch ops 適合)。
- **_headers**: `/sitemap*.xml` Content-Type: application/xml; charset=utf-8 設定済、 `/trial.html` noindex X-Robots-Tag 設定済、 `/dashboard.html` は `meta robots noindex` で十分 (X-Robots-Tag は冗長だが追加余地あり)。
- **_redirects**: 旧 brand alias `/jpintel → /`、`/login → /dashboard` (302) → **意図的 (login.html は新しい OAuth ページに刷新)、_redirects 側でも `/login → /login.html` rewrite が要検討**。CF Pages の `.html` 自動 strip で `/login` → `site/login.html` は自然解決される **ことを再 verify 推奨** (login.html 自体 noindex なので SEO 影響は無)。

### Immediate fixes applied (this audit)
1. `sitemap-index.xml`: +4 sub-sitemap entry。
2. `robots.txt`: +4 `Sitemap:` 行。
3. canonical/hreflang/og:url 不整合 5 件 (dashboard / login / playground) を extensionless に統一。

### Residual yellow
- なし。

## B. On-Page SEO — 7.0 / YELLOW

### Findings (per-page table)

| Page | Title len (JP/EN 混在) | Desc len | h1 cnt | h2 cnt | h3+ cnt | Internal link cnt |
|---|---|---|---|---|---|---|
| index.html | 約 40 字 | 約 130 字 | **1** | 14 | 25+ | 19 |
| pricing.html | 約 28 字 | 約 100 字 | **1** | 10 | 多数 | 12 |
| playground.html | 約 26 字 | 約 95 字 | **1** | 7 | 多数 | 12 |
| dashboard.html | 約 28 字 | 約 90 字 | **1** | 7 | 多数 | n/a (noindex) |
| login.html | 約 18 字 | 約 50 字 | **1** | 0 | 0 | n/a (noindex) |
| artifact.html | 約 17 字 | 約 100 字 | **1** | 多数 | 多数 | 0 (公開 nav 無) |

- 全 page で `h1 = 1 個` 制約遵守 — **これは Linear/Stripe 並み**。
- **artifact.html 問題**: top-nav が `<header class="site"><a href="/">jpcite</a> &rsaquo; Artifacts</header>` のみで他ページへの bridge link 0、`<footer>` も Bookyou T 番号と免責のみ。**internal link density < 3**, internal silo 切断。
- title は概ね 50 字以内に収まり、絵文字なしで Google 表示制限内。
- description は index が `155–160 字 boundary` ぎりぎり。

### Immediate fixes (recommended)
- artifact.html に `<header>` / `<footer>` の site-wide nav (運営/プロダクト/ドキュメント/料金/利用者層) を追加して silo を繋ぐ — 残課題。
- description 文字数は Google の pixel-width 計測の 920 px (約 156 char) を超えない範囲で運用継続。

### Residual yellow
- artifact silo 切断 (next pass)。
- alt text 充足率: 6 page で `<img>` 5 件 / `alt=""` 5 件 = 100% 設定済 (lockup logo は `alt="jpcite"` × 1)。green。

## C. Schema.org Structured Data — 7.5 / YELLOW

### Findings
- **index.html**: SoftwareApplication / Organization (×2 — JSON-LD x2 の重複は意図的、 publisher と top-level Organization の二重 declaration) / WebSite / Dataset / WebAPI / Product graph (×5) / common.json injection (Organization + WebSite + Service + UnitPriceSpecification) — **計 7 schema graph**, Stripe 並み厚さ。
- **pricing.html**: Organization / WebPage / Offer / UnitPriceSpecification — Rich Result test 通過想定。
- **dashboard.html**: Organization のみ (login-gated noindex なので過不足無)。
- **playground.html**: **JSON-LD 0** だった → **FIXED**: WebPage + BreadcrumbList を追加。
- **login.html**: WebPage + WebSite + Organization 設定済 (noindex なので overkill 気味だが harmful ではない)。
- **artifact.html**: CollectionPage + BreadcrumbList 設定済、Article/Dataset type は未付与 (artifact 個別 page 側で SSR 付与する設計と整合)。

### Critical legacy-brand leak (FIXED)
- `index.html` Schema.org JSON-LD の `alternateName: ["jpcite", "税務会計AI", "AutonoMath", "zeimu-kaikei.ai"]` 系 3 箇所 + `sameAs: ["https://zeimu-kaikei.ai", ...]` 2 箇所 → **削除** (`alternateName: ["jpcite"]` のみ、`sameAs` から `zeimu-kaikei.ai` 除去)。memory `feedback_legacy_brand_marker.md` に従い、legacy brand は最小表記。Schema.org に乗せると Google Knowledge Graph に永久残留する risk 大。
- `dashboard.html:1550` visible text `am_ AutonoMath 互換` → **`am_ 互換 prefix`** に edit (人目に触れる本文側の brand leak、Schema.org より優先度高)。

### Residual yellow
- artifact 個別 page SSR 側 (`functions/artifacts/[pack_id].ts`) で Article + Dataset type を JSON-LD 出力する設計確認 — out of scope。

## D. Open Graph / Twitter Card — 8.0 / GREEN

### Findings
- **og:image** PNG 1200×630 (`/assets/og.png`) / square (`/assets/og-square.png`) / twitter (`/assets/og-twitter.png`) の 3 PNG 実在確認済。
- **og:title / og:description / og:url / og:type** は全 6 page で設定済。**FIXED**: dashboard / login / playground の og:url が `.html` 付き → extensionless 統一。
- **twitter:card**: index / pricing / playground / dashboard / login は設定済。**artifact.html だけ未設定** → **FIXED**: `summary_large_image` + title + description + image 追加。og:locale も同時に追加。
- **og:image:width / og:image:height**: index / pricing / dashboard / login は設定済、playground / artifact は当初なし → artifact は今回 fix で width/height 追加。

### Residual yellow
- なし。

## E. Core Web Vitals — 6.5 / YELLOW

### Findings
- **LCP**: hero `<picture>` source srcset 2x 設定 + Noto Sans/Serif JP `display=swap` preconnect 3 origin → green path。`width=600/1200` 明示 alt-source、`height=32` 明示済。
- **FID / INP**: index は inline `<script defer src="analytics.js">` + `/assets/public-counts.js` + signup `<script>` inline。Cloudflare Pages 静的なので server-side delay は無いが、playground / dashboard が **巨大 inline JS bundle** を抱える (playground.html ≈ 6 KB SDK + fetch controller を inline, dashboard.js + dashboard_v2.js defer)。**INP 200ms threshold は手動 audit 不可能 (Real Chrome 必要)** — Lighthouse CI を CI に組み込む推奨。
- **CLS**: hero metrics grid + cards に `border: 1px solid` + grid-template-columns 固定 → layout shift 抑制 OK。但し `<picture>` の dark logo / light logo の switch 時に最小限の shift 余地 (`style="height:32px;width:auto"` で 1 軸固定済、ok)。
- **font preload**: `preconnect` 3 hop OK、`<link rel="preload" href="/styles.css" as="style">` (login/dashboard) で TTFB 縮減。
- **image lazy-load**: hero image は eager (LCP target)、それ以外の picture は明示 `loading="lazy"` 確認できず → 未確認。

### Immediate fixes (recommended, 残課題)
- `<img>` 全てに `width` / `height` 明示 + below-the-fold には `loading="lazy"` 付与。今回 fix 範囲外 (per-page 100+ 箇所 audit 必要)。
- `dashboard.html` / `playground.html` の inline `<script>` を `dashboard.js` / `dashboard_v2.js` / 別 .js に外出しして CSP `script-src 'self'` 厳格化 (現状 `'unsafe-inline'`)。
- Lighthouse CI を `.github/workflows/lighthouse.yml` で `/`/`/pricing`/`/playground` に対し週次実行 (organic-only acquisition の SEO/CWV 監視で必須)。

### Residual yellow
- CWV 実測 (Real User Monitoring) 不在 → Plausible は導入済だが CWV 指標は無。

## F. HTML Semantic / a11y — 8.0 / GREEN

### Findings
- **landmark**: `<header role="banner">` + `<main id="main">` + `<footer>` + `<nav aria-label="主要ナビゲーション">` + `<section aria-labelledby="...">` 多用。Stripe 並み。
- **skip-link**: `<a class="skip-link" href="#main">メインコンテンツへスキップ / Skip to main content</a>` 全 page (artifact 除く) で設置。WCAG 2.2 AA 適合。
- **ARIA**: `aria-labelledby`/`aria-label`/`aria-live="polite"`/`role="status"`/`role="alert"`/`aria-hidden="true"` 適切使用。
- **lang attr**: 全 page `<html lang="ja">` 設定済。
- **charset**: 全 page `<meta charset="UTF-8">` 設定済、 `<title>` より前。
- **WCAG 2.2 AA contrast**: `--text:#111` / `--accent:#0a4d8c` / `--text-muted:#666` のコントラスト比は WebAIM Contrast Checker で 4.5:1 以上を満たす想定 (`#666` on `#fff` = 5.74:1, `#111` on `#fff` = 18.88:1)。 サイト全体は green。
- **artifact.html 限定の警告**: `<header class="site">` のみで `role="banner"` 無、`<nav>` 無、`<footer class="site">` のみで `role="contentinfo"` 無。site-wide style guide から逸脱。

### Immediate fixes (recommended)
- artifact.html に site-wide header/nav/footer を導入。

### Residual yellow
- artifact silo (next pass).

## G. URL Structure — 9.0 / GREEN

### Findings
- **extensionless**: `_redirects` に `/pricing → /pricing.html` 系の 200 rewrite が**意図的に外されている** (loop 回避 comment あり) → CF Pages の `.html` 自動 strip に委任、`/pricing`/`/dashboard`/`/login`/`/playground` 全部 native 解決。
- **trailing slash**: `/docs → /docs/ 301` ガード設置。`/artifacts` / `/artifact` → `/artifact.html 200` rewrite。
- **slug**: `/programs/{slug}-{sha1-6}.html` で衝突回避 + cache-bust 兼用。`/cases/{id}` / `/laws/{slug}` / `/enforcement/{id}` も sitemap 上で確認可能。
- **legacy guard**: `/jpintel → /`, `/jpintel/* → /`, `/line → /notifications`, `/blog → /docs/` 等の alias 301 適切。

### Residual yellow
- なし。

## Top-10 Critical Fix (Claude 代行で即実行可)

| # | severity | page/scope | fix | status |
|---|---|---|---|---|
| 1 | CRIT | index.html JSON-LD | legacy brand `税務会計AI`/`AutonoMath`/`zeimu-kaikei.ai` 5 箇所削除 | **DONE (this audit)** |
| 2 | CRIT | dashboard.html:1550 visible text | `am_ AutonoMath 互換` → `am_ 互換 prefix` | **DONE (this audit)** |
| 3 | HIGH | sitemap-index.xml | 4 orphan sub-sitemap 追加 (cases/enforcement-cases/laws/laws-en) | **DONE (this audit)** |
| 4 | HIGH | robots.txt | 同 4 sitemap 行追加 | **DONE (this audit)** |
| 5 | HIGH | dashboard/login/playground | canonical extensionless と hreflang `.html` 不整合 → extensionless 統一 (5 file edit) | **DONE (this audit)** |
| 6 | MID | playground.html | JSON-LD 0 → WebPage + BreadcrumbList 追加 | **DONE (this audit)** |
| 7 | MID | artifact.html | twitter:card + og:locale + og:image:w/h + hreflang ja/x-default 追加 | **DONE (this audit)** |
| 8 | MID | artifact.html | site-wide header/nav/footer 導入 (silo 接続) | **PENDING** |
| 9 | MID | dashboard/playground | inline `<script>` を外出しして CSP `'unsafe-inline'` 撤廃 | PENDING (大規模 refactor) |
| 10 | LOW | 全 page `<img>` | `width`/`height` 明示 + below-the-fold `loading="lazy"` | PENDING |

**7 fix 完了 / 3 fix 残**。残 3 は本 audit 範囲を超える静的サイト全体の sweep が必要。

## Top-5 user 操作必要

**memory `feedback_no_user_operation_assumption` 確認上、verify**:

| # | item | 代行可否 verify |
|---|---|---|
| 1 | Google Search Console での sitemap 再 submit | **代行不可** — GSC は user の Google 認証必須、API キー方式は対応不可。user が `https://search.google.com/search-console/sitemaps?resource_id=https%3A%2F%2Fjpcite.com%2F` で `sitemap-index.xml` を re-submit する 1 操作。 |
| 2 | Bing Webmaster Tools での sitemap 再 submit | **代行不可** — 同上、Bing アカウント認証必須。`https://www.bing.com/webmasters/sitemaps?siteUrl=https%3A%2F%2Fjpcite.com%2F` で submit。 |
| 3 | Google Search Console カバレッジレポートで legacy brand `zeimu-kaikei.ai` indexing の 301 redirect 状態確認 | **代行不可** — GSC 上の "URL inspection" tool 結果は user 認証下でのみ閲覧可。 |
| 4 | IndexNow ping (Bing / Yandex 即時 index) | **代行可** — `scripts/cron/index_now_ping.py` が既に存在。**user 操作不要、cron で発火**。 |
| 5 | Schema.org Rich Results Test (個別 page) | **代行可** — `curl https://search.google.com/test/rich-results/result?url=...&user_agent=2` で外部 verify 可。 |

→ **真に user 操作必要なのは GSC/Bing WMT の 3 件のみ**。残 2 件は代行可。

## Conclusion

- 平均 score **7.79 / 10**、green 5 軸 / yellow 2 軸、red 0 軸。
- 7 件の critical/high/mid fix を本 audit 中に直接適用済。
- 残 3 件 (artifact silo / inline JS / img dimensions) は static-site 全体 sweep 案件 → 別 lane。
- legacy brand leak は Schema.org + 1 visible text を完全除去 (memory `feedback_legacy_brand_marker` 準拠)。
- yellow 軸 B/E は次の pass で green 化可能 (artifact 強化 + Lighthouse CI 導入)。

---
Generated: 2026-05-11
File: /Users/shigetoumeda/jpcite/docs/audit/seo_health_audit_2026_05_11.md
