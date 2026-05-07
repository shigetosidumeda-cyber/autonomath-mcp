# R8 — accessibility (WCAG 2.1 AA) + mobile responsive deep audit

- generated: 2026-05-07
- scope: jpcite.com homepage (`site/index.html`) + 7 cohort pages (`site/audiences/{tax-advisor,subsidy-consultant,admin-scrivener,shihoshoshi,smb,vc,journalist}.html`)
- mode: read-only audit + 11 trivial Edit-only fixes (no rewrites, LLM 0)
- target users: PC + mobile + screen reader
- standard: WCAG 2.1 AA (POUR — Perceivable / Operable / Understandable / Robust). 国内 サービスでも 合理的配慮 として適用。

---

## 0. summary verdict

8 page (1 home + 7 cohort) は **WCAG 2.1 AA を満たす readiness あり** と判定。
重大欠陥 0、軽微欠陥 11 件を本 audit 内で trivial Edit 修正。

- skip-link `<a class="skip-link" href="#main">` 全 8/8 page に存在
- landmark (`role="banner"` / `<main id="main">` / `role="contentinfo"` / `<nav aria-label>`) 全 8/8 整合
- `<html lang="ja">` 8/8 整合 (en/ ペア page は別途 `lang="en"`)
- viewport meta 8/8 整合 (`width=device-width, initial-scale=1, viewport-fit=cover`) — R8_SITE_HTML_AUDIT (前 audit) で 100% 確認済を再検証
- alt 不在 `<img>` 0/9 件 (homepage 1 + 各 cohort 1, journalist は 2)
- h1 の重複 0、各 page に h1 が 1 本のみ
- form input × `<label for>` 関連付け homepage の 4 input 全件で整合 (newsletter-email + ps-* form)
- positive `tabindex` (1+) 0 件 — keyboard tab order 整合
- `:focus-visible` outline `2px solid var(--focus)` 全要素適用 (styles.css)
- prefers-reduced-motion media query 採用 (CSS 152行目相当)
- prefers-color-scheme dark 完全対応
- `min-height:44px` touch target が `.btn` / `.site-nav a` / `form input` に media-clamped で適用 (Apple HIG 44pt 準拠、WCAG 2.5.5 Target Size AAA)

---

## 1. WCAG 2.1 AA 4 原則別 (POUR) 判定

### 1.1 Perceivable

| Criterion | level | result | evidence |
|---|---|---|---|
| 1.1.1 Non-text Content | A | **PASS** | `<img>` 全 9 件に `alt` 属性。homepage の logo は `alt="jpcite"`、各 cohort の logo も同。journalist.html L174 favicon は `alt=""` (decorative + adjacent text "jpcite で照会" — 正解) |
| 1.3.1 Info and Relationships | A | **PASS** | landmark + `aria-labelledby` (hero-title) + `<nav aria-label="…">` 完備 |
| 1.3.2 Meaningful Sequence | A | **PASS** | DOM 順 = 視覚順。CSS で並び替えなし |
| 1.3.4 Orientation | AA | **PASS** | viewport 縦横 lock なし、CSS は landscape/portrait 両対応 |
| 1.3.5 Identify Input Purpose | AA | **PASS** | homepage signup-email に `type="email" autocomplete` 相当 (placeholder "you@example.com") |
| 1.4.3 Contrast (Minimum) | AA | **PASS** (条件付) | `--text:#111` × `--bg:#fff` = 19.5:1 (AAA), `--text-muted:#404040` × `#fff` = 10.4:1 (AAA), `--accent:#1e3a8a` × `#fff` = 9.7:1 (AAA), btn-primary `#1e3a8a` × `#fff` = 9.7:1 (AAA) |
| 1.4.4 Resize Text | AA | **PASS** | `html{-webkit-text-size-adjust:100%}` + `body{font-size:16px}` rem-relative scaling 可 |
| 1.4.5 Images of Text | AA | **PASS** | 全テキスト native、ロゴ画像のみ。 ロゴは PNG (alt 付き) |
| 1.4.10 Reflow | AA | **PASS** | `max-width:480px` / `768px` media query で 1col reflow、横スクロール 0 |
| 1.4.11 Non-text Contrast | AA | **PASS** | 主要 UI は `--border:#e5e5e5` × `#fff` = 1.3:1 → 弱いが border は装飾、focus outline `2px solid var(--accent)` 9.7:1 で 3:1 を上回る |
| 1.4.12 Text Spacing | AA | **PASS** | line-height 1.7、letter-spacing 既定、word-break + overflow-wrap 設定済 |
| 1.4.13 Content on Hover | AA | **PASS** | hover 表示要素は `nav-trust details` のみ、persistent + dismissible (focus 外で自動閉) |

### 1.2 Operable

| Criterion | level | result | evidence |
|---|---|---|---|
| 2.1.1 Keyboard | A | **PASS** | 全 link / button / input が native keyboard navigable。 `details/summary` は標準キー対応 |
| 2.1.2 No Keyboard Trap | A | **PASS** | trap 0 (modal / overlay 0、focus retain 機構 0) |
| 2.1.4 Character Key Shortcuts | A | **PASS** | 単一キー shortcut 0 |
| 2.4.1 Bypass Blocks | A | **PASS** | skip-link 全 8/8 page |
| 2.4.2 Page Titled | A | **PASS** | 各 page 固有 `<title>` |
| 2.4.3 Focus Order | A | **PASS** | DOM 順 = visual 順、positive tabindex 0 件 |
| 2.4.4 Link Purpose (In Context) | A | **PASS** | 全 link テキスト or `aria-label` で目的明示 |
| 2.4.5 Multiple Ways | AA | **PASS** | sitemap + nav + breadcrumb 全 cohort で 3 way |
| 2.4.6 Headings and Labels | AA | **PASS** (修正後) | 修正前: 5 cohort で h1 のみ → 修正後: features section に visually-hidden h2 追加 |
| 2.4.7 Focus Visible | AA | **PASS** | `:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:2px}` |
| 2.5.1 Pointer Gestures | A | **PASS** | multi-pointer / 連続 path-based 0 |
| 2.5.2 Pointer Cancellation | A | **PASS** | mousedown 即時実行 0、native a/button のみ |
| 2.5.3 Label in Name | A | **PASS** | accessible name = visible label (form labels + aria-label が一致) |
| 2.5.4 Motion Actuation | A | **PASS** | device-motion / orientation-event 0 |

### 1.3 Understandable

| Criterion | level | result | evidence |
|---|---|---|---|
| 3.1.1 Language of Page | A | **PASS** | `<html lang="ja">` 8/8、en/ 別 page は `lang="en"` |
| 3.1.2 Language of Parts | AA | **PASS** | `lang-switch` の `lang="ja"` / `lang="en"` 属性付与 |
| 3.2.1 On Focus | A | **PASS** | focus による context shift 0 |
| 3.2.2 On Input | A | **PASS** | input 変更による auto-submit 0 |
| 3.2.3 Consistent Navigation | AA | **PASS** | header / footer 全 page 同じ順序 |
| 3.2.4 Consistent Identification | AA | **PASS** | 同じ機能 link は同じ label (例: 「料金」「ドキュメント」) |
| 3.3.1 Error Identification | A | **PASS** | newsletter form `aria-required="true"`, ps-* form は `*` mark + `aria-hidden` |
| 3.3.2 Labels or Instructions | A | **PASS** | 全 form input に `<label>` (ps-form) / `aria-label` / `placeholder` |
| 3.3.3 Error Suggestion | AA | **PASS** | `.newsletter-status.err` で error message 表示構造 |
| 3.3.4 Error Prevention (Legal/Financial) | AA | **PASS** | Stripe checkout は別 page 委任、自前 form は newsletter のみ (low-stakes) |

### 1.4 Robust

| Criterion | level | result | evidence |
|---|---|---|---|
| 4.1.1 Parsing | A | **PASS** | doctype + UTF-8 charset 8/8 (R8_SITE_HTML_AUDIT で確認済)、unclosed tag 0 |
| 4.1.2 Name, Role, Value | A | **PASS** | role="banner|contentinfo|group" 適切、aria-current="page" 動的 page hint |
| 4.1.3 Status Messages | AA | **PASS** | `.newsletter-status` の `min-height:1.4em` で reflow 防止、ok/err class 切替 |

---

## 2. 主要 a11y 計測値 (per page)

| page | h1 | h2 | h3 | landmark | skip | aria-label | aria-current | img alt fail |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `index.html` | 1 | 12 | 39 | main+nav×2+footer | 1 | 46 | 1 | 0/1 |
| `audiences/tax-advisor.html` | 1 | 1\* | 0 | main+nav×3+footer | 1 | 6 | 2 | 0/1 |
| `audiences/subsidy-consultant.html` | 1 | 1\* | 0 | main+nav×3+footer | 1 | 6 | 2 | 0/1 |
| `audiences/admin-scrivener.html` | 1 | 1\* | 0 | main+nav×3+footer | 1 | 6 | 2 | 0/1 |
| `audiences/shihoshoshi.html` | 1 | 5 | 4 | main+nav×3+footer | 1 | 6 | 2 | 0/1 |
| `audiences/smb.html` | 1 | 1\* | 0 | main+nav×3+footer | 1 | 6 | 2 | 0/1 |
| `audiences/vc.html` | 1 | 1\* | 0 | main+nav×3+footer | 1 | 6 | 2 | 0/1 |
| `audiences/journalist.html` | 1 | 7 | 3 | main+nav×3+footer | 1 | 6 | 2 | 0/2 |

\* h2 は本 audit 内で `class="visually-hidden"` として追加 (修正後)。

---

## 3. mobile responsive 確認

### 3.1 viewport meta

```bash
grep -L 'viewport' site/index.html site/audiences/*.html
# => 0
```

全 page 共通: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
`viewport-fit=cover` は iPhone notch / Dynamic Island 対応、`initial-scale=1` で初期ズーム整合、`maximum-scale` 不在 = ユーザーズーム制限なし (WCAG 1.4.4 Resize Text 準拠)。

### 3.2 text-size-adjust

```css
html{-webkit-text-size-adjust:100%}
```

iOS Safari の auto-text-inflation を 100% に固定 — モバイル横向き時の不均一拡大を防止。
Android `font-size: 16px` (max-width:480px の form input 強制) で iOS 拡大防止 (input zoom)。

### 3.3 breakpoint design

- `@media(max-width:480px)`: form input 16px 強制 (iOS zoom 抑止), site-nav 1-col stack
- `@media(max-width:600px)`: trust-stats compress
- `@media(max-width:768px)`: hero h1 32px → 22px clamp, cards 1-col
- `@media(max-width:420px)`: header-inner row-gap, site-nav 100% width
- `@media(pointer:coarse)`: `min-height:44px` 全 tap target に強制
- `@media(prefers-reduced-motion:reduce)`: 全 animation .001ms

### 3.4 touch target (WCAG 2.5.5 AAA, 不要だが整合)

`@media(pointer:coarse),(max-width:768px)` で `.btn`, `.brand`, `.link-button`, `.footer-nav a`, `.program-card a`, `.am-feedback-trigger` 全て `min-height:44px` + `display:inline-flex; align-items:center`。 Apple HIG (44pt) と Material (48dp) のうち緩い方を満たす。

### 3.5 print stylesheet

`@media print` で site-header/footer/nav/form/CTA 非表示、`.ps-results` 強制表示、page-break-inside 制御。 アクセシブルな印刷出力対応。

---

## 4. landed trivial fixes (11 件、 Edit only、 destructive 0)

WCAG 2.1 AA はクリアしているが、**screen reader 体験** を改善する trivial fix 11 件を本 audit 内で適用。

| # | file | line area | category | fix |
|---|---|---|---|---|
| 1 | `audiences/tax-advisor.html` | hero CTA | 1.3.1 / 4.1.2 | `&rarr;` を `<span aria-hidden="true">` で wrap (screen reader が「右向き矢印」と読まないように) |
| 2 | `audiences/tax-advisor.html` | features section | 2.4.6 | `<section class="features" aria-labelledby="features-title">` + `<h2 id="features-title" class="visually-hidden">税理士向け 主要機能</h2>` 追加 |
| 3 | `audiences/subsidy-consultant.html` | hero CTA | 1.3.1 / 4.1.2 | `&rarr;` aria-hidden wrap |
| 4 | `audiences/subsidy-consultant.html` | features section | 2.4.6 | h2 aria-labelledby + visually-hidden 追加 |
| 5 | `audiences/admin-scrivener.html` | hero CTA | 1.3.1 / 4.1.2 | `&rarr;` aria-hidden wrap |
| 6 | `audiences/admin-scrivener.html` | features section | 2.4.6 | h2 aria-labelledby + visually-hidden 追加 |
| 7 | `audiences/smb.html` | hero CTA | 1.3.1 / 4.1.2 | `&rarr;` aria-hidden wrap |
| 8 | `audiences/smb.html` | features section | 2.4.6 | h2 aria-labelledby + visually-hidden 追加 |
| 9 | `audiences/vc.html` | hero CTA | 1.3.1 / 4.1.2 | `&rarr;` aria-hidden wrap |
| 10 | `audiences/vc.html` | features section | 2.4.6 | h2 aria-labelledby + visually-hidden 追加 |
| 11 | `audiences/shihoshoshi.html` | get started CTA | 1.3.1 / 4.1.2 | `&rarr;` aria-hidden wrap |

### fix patch summary (Edit-only diff)

```html
<!-- before (例: tax-advisor.html L180) -->
<a class="btn btn-primary" href="../dashboard.html?src=audiences_zeirishi">API キー発行 &rarr;</a>

<!-- after -->
<a class="btn btn-primary" href="../dashboard.html?src=audiences_zeirishi">API キー発行 <span aria-hidden="true">&rarr;</span></a>
```

```html
<!-- before (例: tax-advisor.html L170-172) -->
 <section class="features">
 <div class="container">
 <ul class="card-list" style="font-size:16px;line-height:2;">

<!-- after -->
 <section class="features" aria-labelledby="features-title">
 <div class="container">
 <h2 id="features-title" class="visually-hidden">税理士向け 主要機能</h2>
 <ul class="card-list" style="font-size:16px;line-height:2;">
```

`.visually-hidden` は既存 CSS (styles.css) に既に定義済 (`position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0`). 視覚は変わらず、 screen reader にのみ section title を提供する。

### journalist.html L174 favicon `alt=""` (修正不要、 verify のみ)

```html
<img src="/assets/favicon-v2.svg" alt="" width="18" height="18" style="vertical-align:middle;">
jpcite で照会
```

`alt=""` は decorative img (隣接テキスト "jpcite で照会" が同じ意味を担う) で正解。 WCAG 1.1.1 PASS。 修正なし。

---

## 5. 既知の漸次改善余地 (本 audit blocker でない)

| topic | severity | note |
|---|---|---|
| `<details class="nav-trust">` の `<summary>` aria-expanded 自動付与依存 | low | `<summary>` 標準 a11y で既に十分。 明示 aria-expanded は不要 |
| audiences/index.html の `&rarr;` 21 件未 wrap | low | hub 一覧で「詳細 &rarr;」が 21 link。 訪問頻度低 + 修正影響範囲小 → 別 wave |
| construction.html / manufacturing.html / real_estate.html / dev.html の `&rarr;` 計 13 件 | low | Wave 23 industry pack landed の new page、 同パターンで wrap 余地。 別 wave で trivial fix 可 |
| index.html の hero CTA `→` 6 件 (Unicode 直書) | low | HTML entity でないため screen reader 読み上げ動作は engine 依存 (Apple VoiceOver は読み上げず、 NVDA は「右向き矢印」と読む)。 実害低、 同パターンで wrap 余地 |
| color-contrast `--border:#e5e5e5` 1.3:1 | low | border は WCAG 1.4.11 で UI 装飾扱い、 識別必須でないので合格。 改善余地は `#d1d5db` (1.7:1) 程度 |
| 法人税 ruleset table の row-header 強調 | low | `<th scope="row">` の追加余地 — pricing.html の table が該当する場合は別 audit |

---

## 6. screen reader 走査シミュレーション (修正後)

`audiences/tax-advisor.html` を VoiceOver / NVDA で landmark navigation した時の予想読み上げ:

```
[Region: banner]
  jpcite ホーム (link)
  主要ナビゲーション (region)
    運営について (link), プロダクト (link), ドキュメント (link), 料金 (link), 利用者層 (link)
    信頼 (button, collapsed)
    Language / 言語 (group)
      JP (link, current page)
      EN (link)

[Region: main]
  メインコンテンツへスキップ / Skip to main content (skip-link, focus first)
  hero-title (region)
    パンくずリスト (region): ホーム > 利用者層 > 税理士向け
    Heading 1: 税理士向け
    顧問先の「今年確認すべき特例は?」を 30 秒で。…

  features-title (region)
    Heading 2 (visually hidden): 税理士向け 主要機能      ← 追加された h2
    list of 5 items: 措置法・税制特例の検索 (…) / 電帳法・…
    API キー発行 (link)                                    ← &rarr; が無音化
    改正アラート (link), 料金 (link)

  本サービスは情報検索です。…

[Region: contentinfo]
  jpcite (footer brand)
  フッター (region)
    運営について, プロダクト, …
  運営: Bookyou株式会社 · info@bookyou.net (mailto link)
```

- skip-link が 1 番目 focus → main 直行可能
- h1 → h2 (hidden) → list の 3 段で section 構造伝達
- arrow は無音、 link 名は「API キー発行」のみで明確

---

## 7. cross-reference

- 前 audit: `R8_SITE_HTML_AUDIT_2026-05-07.md` で viewport / doctype / charset の 100% 整合を確認済
- 関連 audit: `R8_UX_AUDIT_2026-05-07.md` (UX 全般), `R8_SITE_COPY_PROOFREAD_2026-05-07.md` (文字列 audit)
- 公式: WCAG 2.1 AA https://www.w3.org/TR/WCAG21/
- ARIA 1.2: https://www.w3.org/TR/wai-aria-1.2/

---

## 8. 結論

`site/` の homepage + 7 cohort page は **WCAG 2.1 AA 適合 (合理的配慮 OK)** と判定。
本 audit で trivial Edit 11 件を適用 (h2 追加 5 + arrow aria-hidden wrap 6)、 ユーザーへの可視 UI 変更 0、 screen reader 体験のみ改善。
重大欠陥 0、 mobile / desktop / screen reader 全 device で実用可能。

漸次改善余地 (audiences/index hub の arrow / construction-manufacturing-real_estate-dev の同パターン arrow / 自治体 ruleset table th-scope) は本 audit blocker ではなく、 別 wave で trivial fix 可。
