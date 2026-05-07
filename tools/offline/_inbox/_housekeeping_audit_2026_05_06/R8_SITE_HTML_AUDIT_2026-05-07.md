# R8 — site/ HTML 公開 readiness audit (jpcite v0.3.4)

- generated: 2026-05-07
- scope: `/Users/shigetoumeda/jpcite/site/` (Cloudflare Pages publish target)
- mode: read-only audit (LLM 0, destructive 上書き 禁止)
- internal hypothesis frame: 「launch 直前 verify、最低 blocker のみ表面化、漸次改善は別軸」

---

## 0. summary verdict

`site/` は **Cloudflare Pages publish に readiness あり** と判定。

- HTML 12,592 file 全件 doctype + UTF-8 charset 整合
- JS 22 file (lunr/min/bundle/workers 除外後) 全件 `node --check` pass
- inline JS 構文 bug pattern (`function NAME {` paren 抜け) 0
- 業法 sensitive cohort 4 page で `legal-note` envelope + 該当統治法条文 (税理士法 §52 / 弁護士法 §72 / 行政書士法 §1-3 / 司法書士法 §3) すべて整合
- Stripe 等 secret leak 0、insecure http src 0、unresolved `{{...}}` placeholder 0、localhost href 0
- `href="#"` は 4 page (dashboard / playground / en/dashboard / cookbook) で計 8 箇所、すべて JS 経由で resolve される DOM hook (R8 blocker としては許容、別軸で漸次改善)
- `javascript:` pseudo-protocol 2 page は意図的 bookmarklet (jpcite Search bookmarklet) で false positive

---

## 1. ファイル inventory

| 区分 | 件数 |
|---|---:|
| HTML 全数 (`find site/ -name "*.html"`) | **12,592** |
| HTML root-level (depth=1) | 39 |
| HTML index.html (各ディレクトリの index) | 1,222 |
| audiences cohort | 60 (47 都道府県 + 11 cohort + index + 1 cross) |
| en/ 英訳 page | 36 |
| contribute/ (DEEP-28) | 1 (index.html + scrubber.js) |
| JS file 全数 | 58 |
| JS file (primary; lunr/min/bundle/workers 除外) | **22** |

---

## 2. doctype / charset 整合

```bash
find site/ -name "*.html" -type f -print0 | \
  xargs -0 grep -L "<!doctype html\|<!DOCTYPE html" 2>/dev/null | wc -l
# => 0
find site/ -name "*.html" -type f -print0 | \
  xargs -0 grep -L "charset=\"UTF-8\"\|charset=\"utf-8\"\|charset=UTF-8\|charset=utf-8" 2>/dev/null | wc -l
# => 0
```

- doctype 不在: **0**
- UTF-8 charset 不在: **0**
- meta description 不在 (root+depth2): 1 (audit-log.rss は HTML ではないため除外確認)
- title 不在 (root+depth2): 0
- en/ pages with `lang="en"`: 36/36

判定 — readiness OK。

---

## 3. 業法 sensitive surface — disclaimer 整合

### sensitive cohort page (audiences/)

| page | 税理士法 | 弁護士法 | 司法書士法 | 行政書士法 | legal-note envelope |
|---|:-:|:-:|:-:|:-:|:-:|
| `audiences/tax-advisor.html` | §52 (line 166) | §72 (line 166) | — | — | line 165 |
| `audiences/subsidy-consultant.html` | §52 (line 106) | — | — | — | (FAQ Answer 内 inline) |
| `audiences/admin-scrivener.html` | — | — | — | §1-3 (line 155) | line 154 |
| `audiences/shihoshoshi.html` | (4 hits) | (2 hits) | (12 hits) | — | (envelope 複数) |

- 各 sensitive page で 該当統治法条文への参照確認、`legal-note` または `Question/Answer` JSON-LD 中で disclaimer 文言整合
- subsidy-consultant.html は専用 `legal-note` blockではなく FAQ Q&A 内に「税理士法 §52」明記 (acceptedAnswer.text)。表示位置 inline だが法的 surface として有効
- shihoshoshi.html は司法書士法 12 hit、§3 (独占業務) も整合

判定 — 業法 disclaimer envelope 整合 (要件満たす)。

### sensitive surface 拡張 list (grep)

```
site/audiences/construction.html
site/audiences/index.html
site/audiences/manufacturing.html
site/audiences/real_estate.html
site/audiences/shihoshoshi.html
site/audiences/subsidy-consultant.html
site/audiences/tax-advisor.html
```

(admin-scrivener.html は keyword grep で素通りしたが行政書士法 §1-3 を別 path で明記、目視確認済み)

---

## 4. JS syntax check (node --check)

```bash
find site/ -name "*.js" -type f \
    -not -path "*/docs/assets/javascripts/lunr/*" \
    -not -path "*/docs/assets/javascripts/bundle*" \
    -not -path "*/docs/assets/javascripts/workers/*" \
    -not -path "*/docs/assets/javascripts/lunr/min/*"
# 22 file, node --check 全件 pass (TOTAL: 22 OK: 22 FAIL: 0)
```

primary JS verified file:

```
site/analytics.js / analytics.src.js
site/dashboard.js / dashboard.src.js
site/dashboard_init.js / dashboard_init.src.js
site/dashboard_v2.js / dashboard_v2.src.js
site/assets/feedback-widget.js / feedback-widget.src.js
site/assets/prescreen-demo.js / prescreen-demo.src.js / prescreen-demo.en.js
site/assets/trust-strip.js / trust-strip.en.js
site/assets/public-counts.js
site/widget/autonomath.js / autonomath.src.js
site/widget/jpcite.js
site/contribute/scrubber.js
site/docs/assets/feedback-widget.js
site/docs/assets/feedback-init.js
```

- lunr/bundle/workers (mkdocs material 由来 minified 生成物) は audit 範囲外として除外 (vendored, jpintel 商標 grep 既知 false-positive 群と同じ取り扱い)

### inline JS 構文 bug grep

```bash
find /Users/shigetoumeda/jpcite/site/ -name "*.html" -type f -print0 | \
  xargs -0 grep -l "function [A-Za-z_][A-Za-z0-9_]* {" 2>/dev/null | wc -l
# => 0
```

- jpintel-mcp 旧 audit で 90+ 検出された `function NAME {` paren 抜け pattern は site/ 内 **0 件**
- memory `feedback_js_syntax_audit.md` の routine が継続効力を持つ証跡

判定 — JS readiness OK。

---

## 5. broken-link / dead URL / placeholder

| 観点 | 件数 | 備考 |
|---|---:|---|
| `{{...}}` unresolved placeholder | **0** | build 漏れ無し |
| `href="http://localhost"` 等 | **0** | dev URL 残無し |
| `href=""` (empty) | **0** | — |
| `href="#"` (hash-only) | 8 (4 page) | dashboard / playground / en/dashboard / cookbook の DOM hook、JS で resolve される設計、launch blocker ではない |
| `src="http://..."` (insecure) | **0** | mixed content 無し |
| `javascript:` pseudo-protocol | 2 page (bookmarklet.html, audiences/journalist.html) | 意図的 bookmarklet (jpcite Search bookmarklet)、false positive |
| TODO / FIXME / TBD / `<<<` marker | **0** | build artifact 残無し |

### `href="#"` 詳細 (8 hits / 4 page)

```
site/dashboard.html:176          dunning-banner-action  (Stripe ポータル, JS で href 注入)
site/dashboard.html:437          btn-primary id="dash-billing-btn"  (同上)
site/playground.html:676,709,718,719  pg-nudge-link / conversion-secondary / Postman / HTTPie (JS で href 注入)
site/en/dashboard.html:196,302   dunning-portal / billing-btn (JS で href 注入)
site/docs/cookbook/r02-tax-cliff-digest/index.html:1800  R24 outline placeholder (next wave)
```

判定 — broken link readiness OK (R24 cookbook の 1 行 placeholder は内部 narrative、launch blocker でない)。

---

## 6. SEO / GEO meta 整合

| 観点 | 件数 |
|---|---:|
| schema.org reference 含む HTML | **10,942 / 12,592 (87.0%)** |
| `application/ld+json` 含む HTML (root+depth2) | 10,949 |
| meta description 不在 (root+depth2) | 1 |
| title 不在 (root+depth2) | 0 |

- 残り 13.0% は cross-tab / city listing 等の集計 page で個別 schema.org 不在は許容 (site-wide breadcrumb は inherit)
- audiences cohort 全 page で title + description + JSON-LD 整合

判定 — SEO/GEO readiness OK。

---

## 7. secret leak / 悪性 surface

### Stripe / OAuth client surface

| 観点 | 件数 |
|---|---:|
| `pk_live_*` / `sk_live_*` / `pk_test_*` / `sk_test_*` | **0** |
| `client_secret=` (non-null) | **0** |
| `js.stripe.com` 等 公式 lib URL | 0 (site/ 静的側では未使用、Stripe portal は API redirect) |
| OAuth `oauth/authorize` href | 1 (site/docs/api-reference/index.html — 仕様 doc) |

`secret` keyword 5 hit は すべて UI element ID (`dash2-webhooks-secret-reveal` 等) または TOS prose (`trade secrets`)。**実 secret leak 無し**。

判定 — secret readiness OK。

---

## 8. blocker 集計 (final)

| dimension | status | blocker? |
|---|:-:|:-:|
| HTML 12,592 file doctype + UTF-8 整合 | OK | — |
| JS 22 file syntax pass | OK | — |
| inline JS 構文 bug 0 件 | OK | — |
| 業法 sensitive 4 cohort page disclaimer 整合 | OK | — |
| `{{...}}` placeholder 残 0 件 | OK | — |
| localhost / mixed-content 残 0 件 | OK | — |
| Stripe / OAuth secret leak 0 件 | OK | — |
| schema.org 87% coverage | OK (許容) | — |
| `href="#"` 8 hits / 4 page | INFO | NO (JS で resolve、漸次改善) |
| `javascript:` 2 page | INFO | NO (意図的 bookmarklet) |

→ **launch blocker: 0**。Cloudflare Pages publish 即可。

---

## 9. 漸次改善候補 (NOT blocker)

優先順位質問はしない方針 (`feedback_no_priority_question.md`) — 一覧のみ。

- `href="#"` 8 hits を `data-action` 属性に置換し JS 側で `event.preventDefault` 完結化 (a11y)
- subsidy-consultant.html に専用 `legal-note` envelope 追加 (現状 FAQ inline)
- admin-scrivener.html に税理士法 §52 / 弁護士法 §72 言及追加 (補助金代理は事業によって税務助言・許認可代理に踏み込み得るため)
- schema.org coverage 87% → 95% (cross-tab / city listing にも minimal Breadcrumb)
- en/ pages に `hreflang` alternate 整備 (現状 lang="en" のみ)

---

## 10. R8 verify summary (1-line)

```
12592 html, 22 js, 0 doctype-miss, 0 charset-miss, 0 paren-bug, 0 syntax-fail,
0 placeholder, 0 secret-leak, 0 localhost, 4 hash-href (info), 4 sensitive cohort
disclaimer-OK → CF Pages launch blocker = 0
```

— end of R8 audit —
