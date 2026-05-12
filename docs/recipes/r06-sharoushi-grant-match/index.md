---
title: "社労士の助成金マッチ"
slug: "r06-sharoushi-grant-match"
audience: "社労士"
intent: "grant_match"
tools: ["search_programs", "get_corp_360", "list_deadlines"]
artifact_type: "grant_list.json"
billable_units_per_run: 10
seo_query: "社労士 雇用 助成金 キャリアアップ 育児休業 高年齢"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 社労士の助成金マッチ

## 想定 user
社労士事務所 (1-15 人体制、顧問先 30-300 社) で、顧問先の従業員規模 (5-1,000 人) + 業種 + 賃金制度 + 育児・介護制度 + キャリアアップ制度 から雇用関連助成金 (キャリアアップ助成金 / 人材開発支援助成金 / 両立支援等助成金 / 65 歳超雇用推進助成金 / 業務改善助成金 / 雇用調整助成金 等) の候補を 5 分でリスト化する。月次レポート + 提案資料の素材を所員 1 名が作成し、所長社労士が approve する運用が想定読者。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` (顧問先別計上)
- 顧問先の従業員数 + 業種 (JSIC 中分類) + 賃金体系 (時給 / 月給) + 平均年齢
- (推奨) 過去 3 年の助成金受給履歴 (重複申請禁止 / 同一年度別事業上限の確認)

## 入力例
```json
{
  "corp_number": "7010001234567",
  "headcount": 35,
  "industry_jsic_major": "P",
  "wage_system": "monthly",
  "avg_age": 41,
  "include": ["careerup", "ikuji_kaigo", "65over", "kaizen", "chosei"],
  "deadline_within_days": 60,
  "client_tag": "sharoushi-2026"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: sharoushi-2026" \
  "https://api.jpcite.com/v1/programs/search?ministry=mhlw&audience=employer&corp=7010001234567&deadline_within_days=60"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="sharoushi-2026")
programs = c.search_programs(
    ministry="mhlw", audience="employer",
    corp_number="7010001234567", deadline_within_days=60,
    include=["careerup", "ikuji_kaigo", "65over", "kaizen", "chosei"],
)
for p in sorted(programs, key=lambda x: x.fit_score, reverse=True)[:5]:
    print(p.program_id, p.fit_score, p.max_amount_jpy, p.source_url)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const programs = await jpcite.search_programs({
  ministry: "mhlw", audience: "employer",
  corp_number: "7010001234567", deadline_within_days: 60,
  client_tag: "sharoushi-2026",
});
console.log(programs.slice(0, 5));
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000060119.html",
  "matched_programs": [
    {"program_id": "mhlw-careerup-2026-r5", "name": "キャリアアップ助成金 正社員化コース",
     "fit_score": 0.85, "max_amount_jpy": 800000, "deadline": "2026-06-30", "tier": "S"},
    {"program_id": "mhlw-jinzai-2026-r3", "name": "人材開発支援助成金 人材育成支援コース",
     "fit_score": 0.72, "max_amount_jpy": 1500000, "deadline": "2026-07-31", "tier": "A"}
  ],
  "applicable_combos": [
    {"combo": ["careerup_seisha", "ikuji_kaigo_otoko"], "note": "正社員化 + 男性育休併用可"}
  ],
  "client_tag": "sharoushi-2026",
  "known_gaps": ["地方独自助成金は別途", "業務改善助成金は申請枠数上限あり"]
}
```

## known gaps
- 47 都道府県独自の雇用関連助成金 (例: 東京都 中小企業従業員 退職金共済等掛金補助) は逐次対応中
- 業務改善助成金は申請枠数上限 (年度予算依存)、`fit_score` 高でも先着順で締切前断られる可能性
- キャリアアップ助成金の「賃金規定改定加算」「賃金規定共通化加算」等の加算項目は本 recipe 対象外
- 雇用調整助成金の 産業雇用安定助成金 / 緊急雇用安定助成金 は災害 / 感染症の臨時特例、平時は通常コースのみ

## 関連 tool
- `search_programs` (ministry=mhlw, audience=employer で雇用助成金絞込)
- `get_corp_360` (法人 360 度ビュー、過去受給履歴)
- `list_deadlines` (60 日以内の締切カレンダー)
- `check_exclusions` (重複申請禁止チェック)
- `apply_eligibility_chain_am` (排他ルール、Wave 21)

## 関連 recipe
- [r01-tax-firm-monthly-review](../r01-tax-firm-monthly-review/) — 税理士月次、給与所得控除との連動
- [r05-gyosei-licensing-eligibility](../r05-gyosei-licensing-eligibility/) — 行政書士許可
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/) — 診断士月次伴走

## billable_units 試算
- 1 顧問先 10 units × ¥3 = ¥30 / 顧問先 / 月
- 顧問先 100 社 = ¥3,000 / 月、税込 ¥3,300
- 顧問先 300 社 (大手) = ¥9,000 / 月、税込 ¥9,900
- 節約 (純 LLM vs jpcite ¥3/req): 顧問先 100 社 × 月 1 cycle で、純 LLM は約 ¥10,000/月 (1 cycle ¥100 = source 6,000 + 助成金検索 5 call) に対し jpcite は ¥3,000/月 (1,000 req × ¥3) → 節約 約 ¥7,000/月 / 顧問先あたり ¥70 (cf. `docs/canonical/cost_saving_examples.md` case 1 / case 6 同系)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 月次レポート / 顧問先伴走資料への組込 OK、jpcite + 厚労省出典の両明記
- 顧問先別 X-Client-Tag を付与で事務所内利用扱い、第三者配信は別途要相談

## 業法 fence
- 社労士法 §2 (1 号 / 2 号業務は社労士独占)
- 社労士法 §27 (他人の求めに応じ報酬を得て、労働社会保険諸法令の代理 / 申請書 / 帳簿書類作成は社労士独占)
- 行政書士法 §1 — 申請書面の作成のうち労働社会保険諸法令分は社労士、それ以外は行政書士
- 弁護士法 §72 — 労働紛争 / あっせん代理は社労士特定社労士、本 recipe は scaffold まで
- 景表法 §5 — `fit_score` は推定値、最終判断は社労士
