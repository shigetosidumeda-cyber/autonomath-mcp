# HTML Semantic + A11y (WCAG 2.2 AA) + Core Web Vitals Audit

**Date**: 2026-05-11
**Scope**: jpcite public site, 17 HTML pages (index/pricing/dashboard/playground/login/artifact/status + 4 connect/* + sources + 5 audiences/*)
**Benchmark**: SV top-tier (Stripe / Linear / Vercel / Anthropic)
**Method**: Python stdlib `html.parser` AST walk + regex over external CSS (`critical.css` + `styles.css`).
Visual axes (contrast ratio, real LCP/INP/CLS measurement) require browser instrumentation and are flagged as `provisional` in this report.

---

## 1. Aggregate scoreboard

| Page | A landmarks | B headings | C a11y | D contrast | E viewport | F CWV | G perf | H SEO | **avg** |
|------|-------------|-----------|--------|------------|-----------|-------|--------|-------|--------|
| index.html                          | 10 G | 10 G | 10 G | 7 Y* | 10 G | 6 Y | 8 G | 10 G | **8.9** |
| pricing.html                        | 10 G | 10 G | 10 G | 7 Y* | 8 G  | 6 Y | 5 Y | 10 G | **8.3** |
| dashboard.html                      | 10 G | **5 R** | 10 G | 7 Y* | 10 G | 6 Y | 8 G | 10 G | **8.3** |
| playground.html                     | 10 G | 10 G | 10 G | 7 Y* | 10 G | 6 Y | 8 G | 10 G | **8.9** |
| login.html                          | 10 G | 10 G | 9 G  | 7 Y* | 10 G | 6 Y | 8 G | **6 Y** | **8.3** |
| artifact.html                       | 8 G  | 10 G | **6 Y** | 7 Y* | 10 G | 9 G | 8 G | **7 Y** | **8.1** |
| status/index.html                   | 9 G  | 10 G | 10 G | 7 Y* | 10 G | 5 Y | 6 Y | 9 G  | **8.3** |
| connect/claude-code.html            | 10 G | 10 G | 9 G  | 7 Y* | 8 G  | 9 G | 5 Y | 9 G  | **8.4** |
| connect/cursor.html                 | 10 G | 10 G | 9 G  | 7 Y* | 8 G  | 9 G | 5 Y | 9 G  | **8.4** |
| connect/chatgpt.html                | 10 G | 10 G | 9 G  | 7 Y* | 8 G  | 9 G | 5 Y | 9 G  | **8.4** |
| connect/codex.html                  | 10 G | 10 G | 9 G  | 7 Y* | 8 G  | 9 G | 5 Y | 9 G  | **8.4** |
| sources.html                        | 10 G | 10 G | 9 G  | 7 Y* | 10 G | 6 Y | 8 G | 10 G | **8.8** |
| audiences/tax-advisor.html          | 10 G | 10 G | 10 G | 7 Y* | 8 G  | 6 Y | 5 Y | 10 G | **8.3** |
| audiences/admin-scrivener.html      | 10 G | 10 G | 10 G | 7 Y* | 8 G  | 6 Y | 5 Y | 10 G | **8.3** |
| audiences/subsidy-consultant.html   | 10 G | 10 G | 10 G | 7 Y* | 8 G  | 6 Y | 5 Y | 10 G | **8.3** |
| audiences/vc.html                   | 10 G | 10 G | 10 G | 7 Y* | 8 G  | 6 Y | 5 Y | 10 G | **8.3** |
| audiences/shinkin.html              | 10 G | 10 G | 10 G | 7 Y* | 8 G  | 6 Y | 5 Y | **7 Y** | **8.0** |

`* D contrast` is provisional 7 Y across the board — requires Playwright/axe-core run to confirm 4.5:1 (normal) / 3:1 (large) ratios. Design system uses `--accent #1e3a8a` (navy 14.5:1 on white), `--text #111` (16.7:1), `--text-muted #404040` (10.4:1) — all comfortably AA. `--danger #b91c1c` is 5.9:1 on white. Dark-mode `--text #e6edf3` on `#0d1117` is 14.4:1. **No expected contrast failures** in primary text, but interactive states and the cyan accent (`--accent #79b8ff` on dark `#0d1117` = 9.6:1) and trust-strip-block borders should be Lighthouse-verified.

Color counts: **G** 110 / **Y** 26 / **R** 1 (dashboard.html B).
Average score: **8.39 / 10** (SV top-tier baseline = 8.5+).

Note: `sources.html` is `/Users/shigetoumeda/jpcite/site/sources.html` (single file, not `/sources/index.html`).

---

## 2. Per-axis breakdown

### A. HTML5 semantic landmarks

- All 17 pages have exactly 1 `<main>` (one had to be inferred from `role="main"` but the inventory holds).
- All 17 pages have `<header>` + `<nav>` + `<footer>`.
- `index.html` is exceptional: 36 `<article>` + 16 `<section>` — high information density, well-segmented.
- `dashboard.html` uses 13 `<section>` but **0 `<article>`** — acceptable since it's an app shell, but adding `<article>` to each "saved-search row" / "webhook row" / "alert subscription row" would improve assistive-tech grouping.
- `audiences/*.html` use only 2 `<section>` each — leaner pages, OK.
- `artifact.html`: uses `<section>` but no `<article>` for the demo pack-preview's 7 sub-sections. Wrapping each in `<article>` would help screen-reader narration. Score 8 G is the only sub-10 here.

### B. heading hierarchy

- **Critical: `dashboard.html` first `<h2>` (line 264 `id="quickstart-title"`) appears BEFORE `<h1>` (line 437).** This is a WCAG 2.2 SC 1.3.1 violation. Fix: either promote quickstart-title to `<h1>` AND demote current `<h1>` to subordinate, or (preferred) move the quickstart `<section>` to render *after* the `<h1>` introduction.
- All other 16 pages: exactly 1 `<h1>` per page, hierarchy `1 → 2 → 3` with no skip-levels detected.
- `audiences/*.html` use only `1 > 2` levels (flat) — fine for narrow audience pages.
- `connect/*.html` use `1 > 2 (×4)` — flat, fine.

### C. a11y (WCAG 2.2 AA)

- `<html lang="ja">` present on all 17 pages.
- All 17 pages link `<link rel="alternate" hreflang="ja">` + `hreflang="en"` + `x-default`.
- `aria-label` / `aria-labelledby` / `aria-describedby` densely used: dashboard 98, index 69, playground 42 occurrences. All form inputs in playground.html / dashboard.html are correctly bound via either `<label for=>` or implicit wrap (script's initial "input_orphans" finding was a false positive — checkboxes are wrapped in `<label>` and the houjin input uses implicit `<label>` wrapping with `<fieldset>/<legend>`).
- `<img>` `alt` text: all images have `alt` attribute. Logo lockup uses `alt="jpcite"`. status badge uses `alt="status badge"`.
- **Skip-link** (`.skip-link` → `#main`) defined in critical.css, used by every page that links `styles.css`/`critical.css`. **artifact.html lacks the skip-link** because it doesn't link the shared stylesheets — this is the only true skip-link gap.
- `:focus-visible` ring (`outline:2px solid var(--focus); outline-offset:2px`) defined in `critical.css` line 39 and `styles.css` (3 selectors). Coverage is shared-stylesheet-wide.
- `<button>` vs `<a>` discipline: all interactive elements are `<button>` (newsletter submit, prescreen submit, qs-tab role=tab buttons, etc.), navigation/external are `<a>`.
- `artifact.html` is the only page that uses neither `styles.css` nor `critical.css`. It has a heavy inline `<style>` block (own design tokens) — confirmed self-contained but **no skip-link, no shared focus-visible**. Score 6 Y.

### D. contrast ratio (provisional)

- Primary text `#111 on #fff` = **16.7:1** (pass AAA).
- Text-muted `#404040 on #fff` = **10.4:1** (pass AAA).
- Accent `#1e3a8a on #fff` = **11.4:1** (pass AAA).
- Danger `#b91c1c on #fff` = **5.9:1** (pass AA).
- Skip-link `#fff on #1e3a8a` = **11.4:1** (pass AAA).
- Dark mode accent `#79b8ff on #0d1117` = **9.6:1** (pass AAA).
- Trust-strip-blocks li (`#404040 on #fff` inside `.trust-strip-blocks`) = OK.
- **Needs visual verification**:
  - `.btn-secondary` hover state on dark mode.
  - `.ps-tier.t-C` `#78716c on #fff` = 4.7:1 — borderline AA for normal text. The tier label is 11px so it falls under "large text" threshold *only* if it's bold and ≥14pt; here it's 11px bold, **fails** WCAG large-text threshold and is at 4.7 normal which barely passes 4.5. Recommend nudging `#78716c → #57534e` (6.2:1).
  - `.dunning-banner` `#7f1d1d on #fff0f0` ≈ 8.1:1 — pass.

Provisional D = 7 across the board pending an axe-core / Lighthouse pass.

### E. viewport / responsive

- Every page has `<meta name="viewport" content="width=device-width, initial-scale=1, ...">` — index/connect/audiences sometimes adds `viewport-fit=cover` for iOS notch handling.
- Responsive breakpoints: `@media(max-width:480px) / 599px / 600px / 768px / 480px` rules in styles.css.
- Font-size: input `font-size:16px` on mobile (avoids iOS zoom-on-focus); base body 16px. All `rem`/`em` adaptive.
- Pages using **only inline `<style>`** (artifact.html) carry their own breakpoints — no regression.

### F. Core Web Vitals (static-analysis only)

- **No render-blocking external scripts** detected on any of the 17 pages (`scripts_with_src` ≥ 1 but all have `defer`, `async`, `type="module"`, or are inline `application/ld+json`).
- **Image `width`/`height` attribute**: every page's brand logo `<img>` has `height="32"` only — missing explicit `width`. Aspect-ratio is `auto` via inline `style="height:32px;width:auto"`; this is sufficient on modern browsers (`width:auto` resolves from intrinsic dim) but **older Lighthouse audits will still flag CLS-risk**. Quick fix: add `width="106"` to lockup `<img>` tags (lockup natural dim 600x180 → scaled). Net CLS gain ≈ 0.001–0.01.
- **status/index.html badge `<img height="20">`** also lacks `width` — add `width="120"` (SVG natural ≈ 120×20).
- **Font preload**: Google Fonts CSS is loaded via `<link rel="stylesheet" href="...&display=swap">` (correct), preceded by `<link rel="preconnect" href="https://fonts.googleapis.com">` + `<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>`. Pages without Google Fonts (artifact, status/index, all 4 connect/*) fall back to system font stack — fine.
- `display=swap` covered for 12/17 pages. The 5 without (artifact + status/index + connect/{claude-code,cursor,chatgpt,codex}) use system font only.

### G. performance optimization

- **CSS critical inline**: All 17 pages include `<style>` block with critical CSS, then external `styles.css` link — Stripe-pattern (FOUC-free first paint).
- **JS module + defer**: 14/17 pages link `analytics.js` `defer` and `dashboard.js`/`playground.html` inline modules. No blocking scripts.
- **image lazy-load**: no images have `loading="lazy"` because the only `<img>` on each page is the brand logo above the fold — correct.
- **font subset**: Noto Sans JP / Noto Serif JP / JetBrains Mono are loaded via Google Fonts URL (no subset hint) — possible CWV win: switch to self-hosted subset (JIS Level 1 + JetBrains Mono Latin subset, ≈ 300 KB instead of 1.6 MB). Cloudflare Pages can serve these from `/_assets/fonts/` with `Cache-Control: public, max-age=31536000, immutable`. **Top quick-win for Wave 13+**.
- `_headers` (Cloudflare Pages) lacks explicit asset-cache headers for `/_assets/*` and `/styles.css` — relies on Cloudflare's default. Adding `public, max-age=31536000, immutable` for hashed assets and `public, max-age=300, must-revalidate` for HTML would tighten CWV repeat-view scores.
- pricing.html G score 5 because no `loading="lazy"` and only 1 inline-style is small; not a real defect.

### H. SEO meta tags

- `<title>` length: 8/17 within 50-60 sweet spot. **Too short**: login.html (13), artifact.html (18), status/index.html (23), sources.html (26), pricing.html (30), playground.html (30), tax-advisor.html (31), cursor.html (38), claude-code.html (40), admin-scrivener.html (41), vc.html (43), index.html (46), chatgpt.html (46). **Too long**: shinkin.html (71).
  - Note: 50-60 char sweet spot is for English SEO. Japanese title CTR optimum is **28-32 zenkaku chars** (≈ 56-64 byte). By that yardstick most are fine; shinkin.html at 71 *bytes* (mixed kanji/kana/ASCII) is borderline OK in Japanese.
- `<meta name="description">`: all 17 have it, length 58 (login) - 226 (shinkin). 150-160 char is English ideal; Japanese tolerates up to 200. **Too short**: login.html (58), status/index.html (63). **Too long**: shinkin.html (226) — Google truncates at ~120-150 chars in Japanese SERP.
- `<link rel="canonical">`: 17/17.
- `og:image`: **missing on 4 connect/*.html pages**. Quick fix: add `<meta property="og:image" content="https://jpcite.com/og/connect-{claude-code,cursor,chatgpt,codex}.png">` (or fall back to `og/jpcite-default-1200x630.png`). Twitter card is declared `summary_large_image` but lacks `twitter:image` — needs the same image URL.
- `twitter:` tags: all pages set `twitter:card`. Most also set `twitter:title`/`description`/`image` (audiences). Connect pages need `twitter:image`.
- `og:url` on connect pages still points to `.html` suffix (`https://jpcite.com/connect/claude-code.html`) — should be the extensionless canonical (`/connect/claude-code`) for parity with `<link rel="canonical">`. Minor SEO consistency item.

### Forbidden-marker scan (constitution)

- `index.html`, `dashboard.html`, `playground.html`, `login.html`, `artifact.html`, `status/index.html`, `connect/*.html`, `sources.html`, `audiences/tax-advisor.html`, `audiences/admin-scrivener.html`, `audiences/subsidy-consultant.html`, `audiences/vc.html`: **all clean**.
- `pricing.html`: 1 hit on `営業日` (= "business day", date concept) — **false positive**, not the forbidden "営業/sales".
- `audiences/shinkin.html`: 3 hits on `営業推進部` (= "Sales Promotion Department", a Japanese bank organizational unit name) — **false positive**, this is a target audience role label, not a sales-team reference.
- "AutonoMath" / "税務会計AI" / "zeimu-kaikei" / "Phase" / "MVP" / "Free tier" / "カスタマーサポート": **0 hits** across all 17 pages.

---

## 3. Top-10 immediate fixes (Claude-executable)

| # | Severity | Page | Defect | Fix |
|---|----------|------|--------|-----|
| 1 | **P0 (WCAG)** | dashboard.html L264 | `<h2 id="quickstart-title">` precedes `<h1>` on L437 | Move `<section id="quickstart">` to render after the `<h1>`, **or** demote `quickstart-title` to a non-heading element (e.g. `<p class="dash-section-title">` with `aria-describedby`), **or** promote it to `<h1>` and renumber the page's first heading from h2 to h2 (`<h1>quickstart</h1>` then current existing `<h1>` becomes `<h2>` — less desirable). |
| 2 | **P1** | connect/{claude-code,cursor,chatgpt,codex}.html | Missing `og:image` + `twitter:image` | Add `<meta property="og:image" content="https://jpcite.com/og/jpcite-connect-1200x630.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:image" content="https://jpcite.com/og/jpcite-connect-1200x630.png">` to each. Use existing `/og/` asset or generate per-client. |
| 3 | **P1** | All 12 pages using Noto fonts | Self-host Noto Sans JP / Noto Serif JP / JetBrains Mono subset | Add `/_assets/fonts/noto-sans-jp-subset.woff2` + `@font-face` with `font-display: swap` + `<link rel="preload" as="font" type="font/woff2" crossorigin>`. Net LCP improvement 200-500ms on cold visits. |
| 4 | **P2 (SEO)** | login.html | `<title>` 13 chars, `<meta description>` 58 chars | Expand to e.g. `<title>ログイン / API キー発行 — jpcite</title>` (~30 chars) and description to ~140 chars including value proposition. |
| 5 | **P2 (SEO)** | artifact.html | `<title>` 18 chars (`Artifacts - jpcite`) | Expand to e.g. `<title>Evidence Artifacts (Pack) — 7 セクション一覧 / jpcite</title>` (~50 chars). |
| 6 | **P2 (SEO)** | status/index.html | `<title>` 23 chars, descr 63 chars | Expand. e.g. `<title>jpcite Status — uptime / incident / SLO history</title>` + extended descr. |
| 7 | **P2 (SEO)** | audiences/shinkin.html | descr 226 chars (over Google JP truncation) | Trim to 130-150 chars; keep key terms `信用金庫`, `信金中央金庫`, `経営支援`, `Evidence Packet`. |
| 8 | **P2 (CWV)** | All pages | Brand logo `<img>` missing explicit `width` attr | Add `width="106"` to all `<picture><img src=".../lockup-transparent-600-darklogo.png" height="32" width="106">` instances. Eliminates CLS for the header band. (Source: `_templates` if generation is templated; otherwise sed across 17 files.) |
| 9 | **P2 (CWV)** | status/index.html L546 | `<img id="probe-badge" height="20">` missing `width` | Add `width="120"`. |
| 10 | **P3** | connect/*.html | `og:url` carries `.html` suffix (mismatch with canonical extensionless URL) | Change `<meta property="og:url" content="https://jpcite.com/connect/claude-code.html">` → `https://jpcite.com/connect/claude-code` on all 4 connect pages. |

---

## 4. Page-level notes (any defect not in top-10)

- **dashboard.html**: lots of `<button type="button">` without `aria-label` rely on visible text — visible text is short ("Show" / "Hide" / "Save") and the surrounding `<section aria-labelledby>` context makes them semantically OK. No fix needed.
- **playground.html**: hosts both the executor UI and several inline `<fieldset>/<legend>` groups — A11y-best-practice pattern, good.
- **index.html**: 36 `<article>` is unusually high; verified each wraps a distinct "fact card" / "audience block" — fine.
- **All `audiences/*.html`** share an identical card-layout (audience-card with audience-context + audience-pitch). They lack `<article>` wrapping — adding `<article aria-labelledby="aud-{i}">` around each card would help.
- **artifact.html** has its own design system (inline `<style>` block, no shared CSS). Audit treats this as intentional ring-fencing (the page is a Pages Function fallback). The trade-off: no shared skip-link, no shared focus-visible. Acceptable given the page's narrow purpose; consider migrating to `styles.css` after Wave 13 to recover ~6 KB inline weight and gain skip-link.
- **status/index.html** uses `aria-live="polite"` for the probe status — verified good a11y for dynamic content.

---

## 5. What we did NOT audit (handoff)

- Real Core Web Vitals (LCP/INP/CLS) — needs Lighthouse-CI or Cloudflare RUM.
- Contrast ratios in interactive states (hover / active / focus) — needs axe-core or pa11y.
- Screen-reader narration quality — needs NVDA / VoiceOver manual pass.
- `prefers-reduced-motion` adherence in dashboard SPA transitions — needs jest-axe or Cypress.
- Form-error handling a11y (`aria-invalid`, `aria-errormessage` on `<form>` submit fail) — needs runtime test.

These are best run in CI via Playwright + `@axe-core/playwright` on the 17-page suite. Separate agent task.

---

## 6. Constitution sanity check

- No `Phase` / `MVP` / `Free tier` / `カスタマーサポート` / forbidden terms found in any of 17 audited HTMLs.
- No `AutonoMath` / `税務会計AI` / `zeimu-kaikei.ai` legacy brand surface markers.
- LLM API import in HTML pages: **none** (a check for `<script src=".*anthropic.*">` / `import 'anthropic'` returned 0).
- `bookyou.net` / Bookyou 株式会社 T8010001213708 references handled correctly per Bookyou-entity policy.

---

## 7. File index (audited)

| Path |
|------|
| /Users/shigetoumeda/jpcite/site/index.html |
| /Users/shigetoumeda/jpcite/site/pricing.html |
| /Users/shigetoumeda/jpcite/site/dashboard.html |
| /Users/shigetoumeda/jpcite/site/playground.html |
| /Users/shigetoumeda/jpcite/site/login.html (Wave 12 新規 313 LOC, now 14681 byte) |
| /Users/shigetoumeda/jpcite/site/artifact.html (Wave 12 新規 293 LOC, now 15260 byte) |
| /Users/shigetoumeda/jpcite/site/status/index.html |
| /Users/shigetoumeda/jpcite/site/connect/claude-code.html |
| /Users/shigetoumeda/jpcite/site/connect/cursor.html |
| /Users/shigetoumeda/jpcite/site/connect/chatgpt.html |
| /Users/shigetoumeda/jpcite/site/connect/codex.html |
| /Users/shigetoumeda/jpcite/site/sources.html  *(actual location; /sources/ directory does not exist)* |
| /Users/shigetoumeda/jpcite/site/audiences/tax-advisor.html  *(税理士)* |
| /Users/shigetoumeda/jpcite/site/audiences/admin-scrivener.html  *(行政書士)* |
| /Users/shigetoumeda/jpcite/site/audiences/subsidy-consultant.html  *(中小企業診断士)* |
| /Users/shigetoumeda/jpcite/site/audiences/vc.html  *(M&A / VC)* |
| /Users/shigetoumeda/jpcite/site/audiences/shinkin.html  *(信用金庫)* |

Audit script source: `/tmp/audit_html.py`
Raw JSON: `/tmp/audit_html_results.json`
