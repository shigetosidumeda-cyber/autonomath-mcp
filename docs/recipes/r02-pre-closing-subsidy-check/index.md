---
title: "決算 30 日前の補助金最終チェック"
slug: "r02-pre-closing-subsidy-check"
audience: "税理士"
intent: "pre_closing"
tools: ["search_programs", "get_corp_360", "list_deadlines"]
artifact_type: "pre_closing_check.pdf"
billable_units_per_run: 12
seo_query: "決算前 補助金 助成金 締切 確認"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 決算 30 日前の補助金最終チェック

## 想定 user
3 月決算法人の 2 月時点で、未申請の補助金・税額控除を漏れなく洗い出して当期計上 (or 翌期繰越判断) を確定する税理士。顧問先 30-300 社規模、月次巡回が定着しており、決算月の 30 日前を「最終チェック窓」として固定運用する事務所が想定読者。所長税理士 1 人 + スタッフ 2-5 人体制で、各顧問先につき 3-5 分以内にスキャン完了することがビジネス採算の前提となる。期末処理 (賃上げ促進税制 / 中小企業投資促進税制 / IT 導入補助金 / DX 投資促進税制) の漏れは決算後の修正申告 = 顧問先信頼失墜に直結するため、決算前の網羅性が ROI を決める。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` ヘッダー (顧問先別の billable 計上)
- 決算月 + 法人番号 (国税庁 13 桁)
- 顧問先の業種 (JSIC 大分類) + 従業員数 — fit_score 算出 input
- 過去 3 年の採択履歴 (重複申請禁止条項のチェック用)

## 入力例
```json
{
  "corp_number": "7010001234567",
  "closing_month": 3,
  "fy_year": 2026,
  "jsic_major": "E",
  "headcount": 45,
  "past_adoptions": ["meti-it-2025-r3", "meti-mono-2024-r2"],
  "include_municipal": true
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
# 1. 未申請補助金を deadline 順
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: client-001" \
  "https://api.jpcite.com/v1/programs/search?corp=7010001234567&deadline_before=2026-03-31&exclude_applied=true&sort=deadline_asc"

# 2. 適用可能税額控除
curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/am/tax_rules/applicable?corp=7010001234567&fy=2026"

# 3. 締切カレンダー
curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/programs/deadlines?within_days=60"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="client-001")
programs = c.search_programs(corp_number="7010001234567", deadline_before="2026-03-31",
                              exclude_applied=True, sort="deadline_asc")
tax_rules = c.get_applicable_tax_rules(corp_number="7010001234567", fy=2026)
top5 = sorted(programs, key=lambda p: p.fit_score, reverse=True)[:5]
artifact = c.bundle_pre_closing_check(corp_number="7010001234567", picks=top5, tax_rules=tax_rules)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const programs = await jpcite.search_programs({
  corp_number: "7010001234567",
  deadline_before: "2026-03-31",
  exclude_applied: true,
  sort: "deadline_asc",
});
const taxRules = await jpcite.get_applicable_tax_rules({ corp_number: "7010001234567", fy: 2026 });
const top5 = programs.sort((a, b) => b.fit_score - a.fit_score).slice(0, 5);
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "fy_year": 2026,
  "closing_month": 3,
  "source_url": "https://www.chusho.meti.go.jp/koukai/kobo/index.html",
  "matched_programs": [
    {"program_id": "meti-it-2026-r5", "name": "IT 導入補助金 2026 通常枠", "deadline": "2026-03-15", "max_amount_jpy": 4500000, "fit_score": 0.82, "tier": "S"},
    {"program_id": "meti-mono-2026-r3", "name": "ものづくり補助金 2026 一般枠", "deadline": "2026-03-22", "max_amount_jpy": 12500000, "fit_score": 0.74, "tier": "S"}
  ],
  "applicable_tax_rules": [
    {"rule_id": "meas-42-4", "name": "研究開発税制 一般型", "max_credit_jpy": 8000000, "fy_applicable": true}
  ],
  "estimated_total_jpy": 25000000,
  "known_gaps": ["municipal lag 7-14d", "past_adoptions の自己申告に依存"]
}
```

## known gaps
- 市町村独自補助金は ingest 周期で 7-14 日遅延 (S/A tier は当日反映、B/C tier は週次)
- 締切後の繰越 / 再公募有無は一次資料での確認必須 (programs.next_round_hint は heuristic)
- 過去採択履歴は顧問先自己申告ベース、jPubs API では完全捕捉できないケースあり
- 税額控除の租特法読替は措置法 42-4 等の主要条項のみ、地方税の特例は範囲外
- ¥3/req の billable_units は jpcite 側のみ、e-Tax 送信費用や顧問先実費は別建て

## 関連 tool
- `search_programs` (deadline / 業種 / 規模で絞り込み)
- `get_corp_360` (法人 360 度ビュー)
- `list_deadlines` (60 日以内の締切カレンダー)
- `check_eligibility` (申請要件の自動チェック)
- `list_adoptions` (過去採択履歴の参照)

## 関連 recipe
- [r01-tax-firm-monthly-review](../r01-tax-firm-monthly-review/) — 月次レビュー、決算月以外の標準フロー
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/) — 診断士伴走、申請支援への引き継ぎ
- [r25-adoption-bulk-export](../r25-adoption-bulk-export/) — 採択 bulk export、類似事例の根拠資料

## billable_units 試算
- 1 法人 1 回 = 12 units × ¥3 = ¥36 / 法人 / 決算期
- 顧問先 100 社、3 月決算が 60 社想定 = 60 × ¥36 = ¥2,160 / 期
- 月次レビュー (r01) と組み合わせて年 13 回稼働 = ¥3,600 / 法人 / 年
- 節約 (純 LLM vs jpcite ¥3/req): 決算前 60 社チェック 1 期で、純 LLM は約 ¥7,200/期 (1 社 cycle ¥120 = source 6,000 + tool 8 + repeat fetch) に対し jpcite は ¥2,160/期 (720 req × ¥3) → 節約 約 ¥5,040/期 / 1 社あたり ¥84 (cf. `docs/canonical/cost_saving_examples.md` case 1 / case 6 同系)

## 商業利用条件
- 出力 artifact は PDL v1.0 + CC-BY-4.0 で再配布可、顧問先報告書への組込・印刷頒布 OK
- 出典 (`source_url`) 明記必須、jpcite 由来データの編集注記を artifact に保持
- 顧問先別 X-Client-Tag を付与した呼出は事務所内利用扱い、第三者配信は別途要相談

## 業法 fence
- 税理士法 §52 (税務代理 / 税務書類作成 / 税務相談は税理士独占) — 資料整備に留め、税務判断は税理士
- 中小企業診断士登録規則 — 経営助言 / 補助金申請伴走は診断士領域
- 行政書士法 §1 — 申請書面作成は行政書士、本 recipe は scaffold + 一次 URL まで
- 景表法 §5 — fit_score / max_amount_jpy は推定値、保証ではない旨を artifact PDF 末尾に注記
- 消費者契約法 §4 — 顧問先への提案資料に組み込む場合、不確実性を明示
