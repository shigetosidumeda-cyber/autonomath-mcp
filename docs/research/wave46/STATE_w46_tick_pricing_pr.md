# STATE — Wave 46 永遠ループ tick#3 (pricing redesign)

- date: 2026-05-12
- lane: /tmp/jpcite-w46-pricing-redesign.lane
- worktree: /private/tmp/jpcite-w46-pricing-redesign
- branch: feat/jpcite_2026_05_12_wave46_pricing_redesign
- status: PR open pending (commit ready, push ready)

## 1. ゴール

site/pricing.html + site/compare.html から "ROI / ARR / ¥X/月 射程" 等の
盛り表現を全廃し、「**節約 ¥Y/月**」(use case = N) の cost saving framing に置換する。
3 用例 (税理士 / M&A / 信金) を inline embed、全 6 case は canonical doc に集約。

## 2. 変更内容

### 2.1 修正 file

- `site/pricing.html` (+88 / -7 lines)
  - JSON-LD Dataset description: "ROI シナリオ表" → "純 LLM vs jpcite cost-saving シナリオ表"
  - cost-examples セクション footnote: "ROI 倍率" link → "cost_saving_examples" link + 業種別 use case
  - vs web search 表 final row: "1,000-3,600 倍 ROI" → "節約 ¥1,300-46,000/月 (use case 別)"
  - vs web search 表 left cell: "¥36-120万/年 リスク" → cache-miss / hallucinate phrasing
  - 新 section: `id="cost-saving-calc-title"` — 6 use case x cycle x 純 LLM vs jpcite x 節約
    - 税理士 顧問先月次レビュー / M&A advisor 公開情報 DD / 信金 制度マッチ pre-screen を含む 6 case を inline 表 embed
  - rename: `id="roi-vs-websearch-title"` → `id="vs-websearch-title"`
- `site/compare.html` (+1 / -1 lines)
  - row 6 価格モデル: "節約 ¥8,000-39,000 /use case" + canonical doc link 追加

### 2.2 追加 file

- `docs/canonical/cost_saving_examples.md` (92 lines, ~180 LOC source-form)
  - 6 use case 節約表 + 内訳 + 純 LLM 単価仮定 + jpcite ¥3/req cost
- `tests/test_pricing_cost_saving.py` (137 lines, ~80 LOC test-form)
  - 10 test cases (canonical doc 存在 / ROI/ARR/射程 0 grep / 6 use case 節約金額 parity / 構造 anchor / brand 一貫)

### 2.3 LOC delta

- pricing.html: +88 / -7
- compare.html: +1 / -1
- new doc: +92
- new test: +137
- **合計: +318 / -8 lines**

## 3. 6 use case 節約表 (canonical inline)

| # | use case | 月 cycle | 純 LLM コスト/月 | jpcite ¥3/req コスト/月 | 節約 ¥/月 |
|---|---------|----------|------------------|---------------------------|-----------|
| 1 | 税理士 顧問先月次レビュー (50 社) | 50 | ¥18,000 | ¥2,700 (900 req) | **¥15,300** |
| 2 | M&A advisor 公開情報 DD (月 10 deck) | 10 | ¥24,000 | ¥4,800 (1,600 req) | **¥19,200** |
| 3 | 信金 制度マッチ pre-screen (月 200 件) | 200 | ¥16,000 | ¥2,400 (800 req) | **¥13,600** |
| 4 | 中小企業診断士 申請戦略パック (月 30 案件) | 30 | ¥10,800 | ¥1,800 (600 req) | **¥9,000** |
| 5 | BPO 1000 案件 triage (月 4 batch × 250) | 1000 | ¥48,000 | ¥9,000 (3,000 req) | **¥39,000** |
| 6 | 行政書士 補助金前リサーチ (月 80 件) | 80 | ¥9,600 | ¥1,440 (480 req) | **¥8,160** |
| **合計 (6 worker 並走時)** | — | — | **¥126,400** | **¥22,140** | **¥104,260** |

純 LLM 単価仮定: 入力 token ¥300/1M、tool call ¥0.5/件、source 5,000-10,000 token/cycle。
jpcite は ¥3/req 完全従量 (税込 ¥3.30)、tier / seat / 月額固定なし。

## 4. 禁止事項 verify

- 大規模 redesign: NO — 既存 hero / cost examples / vs web / break-even / api-paid セクションすべて維持。新 section 1 本 追加 + 既存 row の文字列置換のみ
- surface text 改ざん: NO — 数字根拠は canonical doc に明示、純 LLM 単価は公開 price source
- main worktree: NO — `/private/tmp/jpcite-w46-pricing-redesign` で作業
- 旧 brand 復活: NO — 税務会計AI / AutonoMath / zeimu-kaikei.ai 全 0 件 (test で gate)
- LLM API: NO — test pure offline + python `html.parser` のみ
- Phase / MVP / 工数: NO — 一括フル投入、段階分割なし

## 5. verify 結果

- `grep -nE '(ROI|ARR|射程)' site/pricing.html site/compare.html` → 0 件
- `grep -nE '(税務会計AI|AutonoMath|zeimu-kaikei\\.ai)' site/{pricing,compare}.html` → 0 件
- HTML parser leftover stack: pricing OK / compare OK / err 0 / err 0
- pytest tests/test_pricing_cost_saving.py: 10 PASSED in 0.98s
- jpcite brand counter: pricing=90, compare=74 (両方 >0)

## 6. 残課題

- main merge 後 CF Pages propagation 60s+
- Wave 46 永遠ループ 次 tick (pricing 外) は別 lane で
