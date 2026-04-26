# Accessibility Audit — AutonoMath site

- 監査日: 2026-04-23
- 対象: `site/*.html` 全 8 ページ (`index`, `pricing`, `dashboard`, `success`, `privacy`, `tos`, `tokushoho`, `status`) + `site/styles.css`, `site/dashboard.js`, `site/assets/demo.svg`
- 対象外: `site/press/` (マーケ素材, 別経路で生成)
- 方式: 手動静的レビュー + Headless Chrome (1280×1600, `≤1880px` 制約準拠) で pre/post スクリーンショット差分確認 (`research/a11y_before_after/`)
- 前提: 2026-05-06 launch、2024-04 施行「障害者差別解消法」改正で民間事業者にも合理的配慮が法的義務化。B2B 開発者ツール (Claude Desktop / MCP directories / HN / Zenn 経由で screen reader / keyboard-only / high-contrast ユーザーが多数想定)

## 監査 12 項目 × pre/post サマリ

| # | 項目 | Pre 所見 | Post | 備考 |
| --- | --- | --- | --- | --- |
| 1 | Semantic HTML | 0 defect | ✓ | `<main>`/`<nav>`/`<header>`/`<footer>`/`<article>` 既に適切に使用。div-soup なし |
| 2 | Heading hierarchy (h1 1 個、skip 無し) | 0 defect | ✓ | 全ページ h1 唯一。success.html の error state は `<strong>` で明示 |
| 3 | `<html lang="ja">` | 0 defect | ✓ | 8 ページすべて設定済 |
| 4 | `<img>` alt | 0 defect | ✓ | 唯一の `<img>` (`assets/demo.svg`) は descriptive alt + `role="img"` + `<title>`/`<desc>` 付 |
| 5 | Form labels | 2 defect | ✓ | (a) `index.html` newsletter は `visually-hidden` label 済、(b) `dashboard.js` injected sign-in input は placeholder のみ → `<label for>` 追加 + `aria-labelledby`/`aria-describedby` 配線 |
| 6 | Link text ("click here" / 単独「詳細」 禁止) | 0 defect | ✓ | 「詳細と契約へ →」「Pricing に戻る」「既に契約済みの方は Dashboard」等すべて行先具体化。`→` は装飾文字、前に説明文あり |
| 7 | Keyboard navigation (focus visible, outline) | 0 defect | ✓ | `:focus-visible { outline: 2px solid var(--focus); }` グローバル設定あり。`outline: none` 無し |
| 8 | Color contrast (WCAG AA) | 0 text fail, 1 non-text note | ✓/⚠ | 主要 body text `#111/#fff` = 18.9:1 (AAA)、muted `#555/#fff` = 7.46:1 (AAA)、accent `#1e3a8a/#fff` = 10.36:1 (AAA)、danger/warn/ok/brown すべて AA ≥4.5:1。唯一 `.key-warning` の amber border `#f59e0b/#fff8e6` = 2.03:1 が UI 3:1 未満だが、当該 alert は本文色 6.69:1 + 背景色差で識別可能なため border は装飾扱いで残置 (下記 ⚠) |
| 9 | ARIA (aria-label, aria-live, role=status) | 0 defect | ✓ | icon-only button には aria-label 付、newsletter status / dashboard spinner / signin error に `role="status"`/`role="alert"` + `aria-live="polite"` 配線済。dashboard.js signin-err に追加 |
| 10 | Skip link | 8 page 不在 | ✓ | `site/styles.css` に `.skip-link` を追加し 8 ページすべて `<body>` 直下に「メインコンテンツへスキップ / Skip to main content」を挿入、全 `<main>` に `id="main"` |
| 11 | `prefers-reduced-motion` | 未対応 (2 animation + 2 spinner + 1 SVG) | ✓ | `site/styles.css` に `@media (prefers-reduced-motion: reduce)` で `animation/transition: 0.001ms` 一括停止。success.html inline style + `site/assets/demo.svg` 内の `<style>` にも同等 rule を追加 (SVG 内 style は外部 media クエリが届かないため) |
| 12 | Focus management (success.html state transition) | 未対応 | ✓ | `showOnly()` を拡張し、初回 loading 表示以外の state 切替時は新 state の heading/alert に `focus()` を移す。初回表示では focus を動かさないため mouse 経由到達時に余計な focus ring が出ない |

## Post-fix で採用した修正 (file-level)

- `site/styles.css` — `.skip-link` (translateY で 100% 上に退避、focus 時に 0 へ復帰) と `@media (prefers-reduced-motion: reduce)` 追加
- `site/index.html` / `pricing.html` / `dashboard.html` / `success.html` / `privacy.html` / `tos.html` / `tokushoho.html` — skip link + `href="#"` → `https://github.com/AutonoMath` (公開準備中の旨 aria-label に明示) に置換
- `site/status.html` — inline `<style>` を使用のため skip link CSS + reduced-motion ルールも内部に追加、`<main>` に `id="main"` 付与
- `site/dashboard.html` — `dash-nav` 内プレースホルダ anchor に `aria-disabled` + `title`、Overview に `aria-current="page"`、API key / Billing ブロックに id 付与しフラグメント到達可能化
- `site/dashboard.js` — sign-in form に `<label for>` + `aria-labelledby` + `aria-describedby`、error msg に `role="alert"`/`aria-live="polite"`
- `site/success.html` — 各 state 容器に `tabindex="-1"` 追加、`showOnly()` を focus-move 対応、`[id^="state-"]:focus` で mouse 操作時の outline 抑止
- `site/assets/demo.svg` — 内部 `<style>` に `@media (prefers-reduced-motion: reduce)` を追加し、step fade / caret blink を停止

## 残課題 (⚠ deferred / ✗ out of scope)

| 項目 | 判定 | 理由 |
| --- | --- | --- |
| `.key-warning` amber border `#f59e0b` 2.03:1 | ⚠ deferred | alert box は text (6.69:1) + background fill で識別可、border は装飾。ブランド色差替えは design system 側の判断事項 |
| success.html 各 error state に `<h1>` 代替見出しが無い | ⚠ deferred | `role="alert"` + `<strong>` で announce される。`<h1>` 追加は hierarchy 設計変更になるため今回保留 |
| dashboard.html プレースホルダ nav 4 項目 ("API key", "Billing", "Invoices") のファンクション未実装 | ⚠ deferred | 本監査は a11y 範囲。実装は別 task、現状は `aria-disabled` + `title` + ページ内アンカーで keyboard user の混乱を最低限に抑制 |
| `site/press/*` | ✗ out of scope | タスク明示除外 |
| `site/programs/_samples/` | ✗ out of scope | 空ディレクトリ、ページ未生成 |

## WCAG 2.1 達成水準

- **Level A**: 全ページ達成
- **Level AA**: 全 8 ページで text contrast / keyboard accessible / skip link / motion prefs / form labels / status message (1.3.1, 1.4.3, 2.1.1, 2.4.1, 2.4.4, 2.4.7, 3.3.2, 4.1.2, 4.1.3) を満たす
- **Level AAA (部分達成)**: 主要 text contrast は 7:1 超 (1.4.6)、target 最小 44×44 に近い (2.5.5 relaxed)、reduced motion (2.3.3)
- **未達成 Level AAA**: section heading が全 state で存在 (2.4.10) ← success error state で一部欠落

## 障害者差別解消法 posture (1 行)

launch 時点で WCAG 2.1 AA を全ページで満たし、keyboard-only / screen reader / high-contrast ユーザーに対し skip link + focus ring + form label + motion prefs で合理的配慮の「事前的改善措置」要件を充足している。

## 事後検証

- 8 ページ Headless Chrome 1280×1600 スクリーンショット pre/post を `research/a11y_before_after/` に保存。全ページで pixel-level の視覚リグレッション無し (skip link は focus 時のみ顕在化、初期 paint 完全退避)
