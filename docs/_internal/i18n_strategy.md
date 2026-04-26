# 多言語対応戦略 (i18n strategy)

> 2026-04-23 初版 / Owner: 梅田茂利 / launch 2026-05-06 向け
> scope: `site/` HTML の日英並列運用、MkDocs 側 (`docs/`) は JP 単一のまま。
> 関連: `docs/seo_technical_audit.md` (hreflang)、`project_jpintel_trademark_intel_risk` ({{DOMAIN}} placeholder)。

---

## 1. 結論 (TL;DR)

- **JP primary / EN surface minimum** の 2 層。
- 英語は `site/en/` 配下に 5 本 (index / pricing / getting-started / about / tokushoho) のみ。
- フレームワーク不使用、静的 HTML の手動翻訳。ビルド時生成でも i18next でもない。
- `tokushoho.html` は英訳しない (特商法は JP consumer 保護を目的とする法定文書、多言語並列は契約解釈を混乱させる)。
- 自動翻訳 / Weblate / Crowdin は当面導入しない (ROI < コスト)。

## 2. なぜフル i18n を選ばなかったか

| 比較軸 | フル i18n (i18next / Next.js intl) | 現在採用 (static EN 5 pages) |
|---|---|---|
| 初期工数 | 2-3 人日 (key extract + JSON + build 配線) | 0.5 日 (HTML 複製 + 翻訳) |
| 運用コスト | key drift 監視、翻訳 CI、fallback バグ | 手動 diff、5 ファイル限定 |
| 訪問者価値 (D-Day) | 10/10 (全ページ EN) | 8/10 (landing + pricing + quick-start + about でほぼカバー) |
| 拡張性 | 新言語追加 O(1) | 新言語は O(pages) で再コピー |
| launch までの時間 | 1 週間消費 | 半日 |
| 典型失敗 | key 取りこぼし → mixed-language page | なし (静的で明示) |

**判定**: W0 (launch 前) に投下するなら現行方式。EN 訪問者が週次 100 UV / 1% signup を恒常的に超えたら i18next へ移行検討 (§7)。

## 3. 何を英訳しないか

以下は**明示的に** JP-only で据える:

- **特定商取引法 (tokushoho.html)**: 根拠法が JP 消費者保護。英訳すると「どちらが契約 controlling か」を問われた時に JP 必勝条項を無効化するリスクがある。EN 側は 1 行ポインタのみ (`en/tokushoho.html`) で JP 原文にリンク。
- **利用規約 (tos.html) / プライバシーポリシー (privacy.html)**: 同上。英訳は将来的に弁護士監修の下で行う (W5-W8 roadmap に組み込み済み: `launch_compliance_checklist.md`)。現状は `noindex` で SEO 漏れもない。
- **MkDocs 配下の `docs/` 全体**: 技術 reference は JP 開発者が 1 次読者。EN 開発者への受けは `en/getting-started.html` 1 本に集約し、深掘りしたい者には JP docs + DeepL / ChatGPT を使ってもらう (docs 翻訳コスト vs. 流入: 8,000 語 × 10 本 = 80,000 語 の翻訳・校正は 1-2 週間消費、対して EN 深掘り訪問者は初月 < 50 UV 見込み → 後回し)。

## 4. 方式 (implementation)

```
site/
  index.html           JP 原本
  pricing.html         JP 原本
  tokushoho.html       JP 原本 (法定、英訳せず)
  tos.html / privacy.html  JP 原本 (noindex)
  en/
    index.html         EN 手動翻訳
    pricing.html       EN 手動翻訳
    getting-started.html  EN 手動翻訳 (docs/getting-started.md の要約)
    about.html         EN 手動翻訳 (press/about.md の英語段落を基に拡張)
    tokushoho.html     EN 1 行ポインタ (JP 版へリンク)
  styles.css           共有 (fork 禁止、`.lang-switch` も本体に追加済)
```

### 4.1 Language switcher

- top-right 固定、plain `<a href>` のみ。JS 不要。
- `aria-label="Language / 言語"` + `aria-current="page"` で SR 読み上げ。
- Tab で到達可能 (`tabindex` 操作不要、デフォルトで順序に入る)。
- スタイルは `styles.css` の `.lang-switch` で一元管理。

### 4.2 hreflang

各ページの `<head>` に 3 行:

```html
<link rel="alternate" hreflang="ja" href="https://{{DOMAIN}}/foo.html">
<link rel="alternate" hreflang="en" href="https://{{DOMAIN}}/en/foo.html">
<link rel="alternate" hreflang="x-default" href="https://{{DOMAIN}}/foo.html">
```

`x-default` は JP に寄せる (primary)。

### 4.3 価格のローカライズ

- 金額は JPY 固定 (¥2,980 / ¥9,800 / ¥29,800)。
- EN 側に `(approx $20 / $65 / $200 USD at ¥150/$)` を parenthetical で添える (参考値であって約束ではない)。
- "Billing in JPY; card network handles FX" を pricing page に明記 (Stripe の自動 FX に依拠、当社は為替責任を負わない)。

## 5. 新規 EN ページ追加手順 (how-to)

1. `site/foo.html` (JP 原本) を開いて構造を確認。
2. `cp site/foo.html site/en/foo.html`。
3. `<html lang="ja">` → `<html lang="en">`。
4. `<link rel="stylesheet" href="styles.css">` → `href="../styles.css"`。同じく `analytics.js` も `../`。
5. `<link rel="canonical">` を `/en/foo.html` に書き換え。
6. hreflang 3 行 を追加 (§4.2)。
7. 本文を英訳。**trans tone は技術・抑制的**。grow-hack 語彙 (revolutionary / AI-powered / next-gen) 禁止。
8. フッター / nav / lang-switch の相対パス (`../` を付ける) を確認。
9. JP 原本側にも `hreflang="en"` を追加、`.lang-switch` の EN リンクを付与。
10. `sitemap.xml` に `https://{{DOMAIN}}/en/foo.html` を追加。
11. 手動で両ページを browser で開いて、switcher が往復するか確認 (screenshot 推奨)。

**翻訳できない語**: そのまま JP を残し `<span lang="ja">` で wrap、もしくはコメントに `<!-- 要 EN 校正 -->` を挿入して次パスで弁護士 / native reviewer に回す。

## 6. SEO / 検索面

- Google は hreflang + canonical で JP/EN を別ページとして index する。canonical は自己参照 (`/en/foo.html` の canonical は `/en/foo.html`)。
- `robots.txt` は `/en/` を明示 allow (default の `Allow: /` で既にカバーされているが、`sitemap-en.xml` を将来分割する際は追加)。
- `llms.txt` は当面 JP のみ。EN 版は EN ページが 20 本を超えたら分割検討。

## 7. スケール判断 (when to upgrade)

以下のいずれかを満たしたら、手動 static → ビルド時 i18n へ移行検討:

- EN ページが 15 本超 (手動 diff のコストが CI 化コストを超える)
- EN 訪問者が週次 500 UV を 4 週連続
- EN signup 率が 3% を超える (LTV から翻訳投資が合理化される)
- 第二言語 (zh-CN / ko) の要望が顧客からきた (同一仕組みで複数言語を扱うなら i18n framework 必須)

候補フレームワーク (推奨順):
1. `eleventy-plugin-i18n` — 静的 HTML に近い、学習コスト低
2. `astro` i18n — 既存 HTML のまま Page として import できる
3. `next-intl` — SaaS 側を Next.js 化した場合に限り
4. `i18next` — SPA 化した場合のみ (overkill)

## 8. rollout (launch 当日)

- D-Day (2026-05-06) 朝: HN post は JP landing (`{{DOMAIN}}/`) と EN landing (`{{DOMAIN}}/en/`) を両方貼る。最初の comment で "EN mirror for non-JP readers: /en/" と誘導。
- D+1 〜 D+7: EN ページの bounce rate / scroll depth / conversion を Plausible で比較。EN bounce > 80% なら hero copy を 1 回 A/B。
- D+14: EN signup が JP の 10% を超えていれば **getting-started 拡張** (Python SDK / Node SDK の full example、MCP 設定の Windows/Linux 補足) に 1 日投下。超えなければ触らない。
- D+30: 上記 §7 条件を満たしていれば i18n framework の PoC を 1 日で作って比較。

## 9. 変更履歴

- 2026-04-23: 初版。5 EN pages + language switcher + hreflang + この戦略ドキュメント。
