---
title: "行政書士の建設業許可 prerequisite 検査"
slug: "r05-gyosei-licensing-eligibility"
audience: "行政書士"
intent: "licensing_eligibility"
tools: ["evidence_packets_query", "get_corp_360", "search_certifications"]
artifact_type: "licensing_checklist.json"
billable_units_per_run: 6
seo_query: "行政書士 建設業 許可 必要書類 排他ルール"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 行政書士の建設業許可 prerequisite 検査

## 想定 user
許認可業務 (建設業 / 産廃 / 在留資格 / 古物商 / 飲食店 / 風営) を月 5-30 件回す行政書士。法人番号 1 件入力で「必要書類リスト + 過去 5 年行政処分 history + 業法 fence + 関連補助金候補」を 1 envelope で 5 分以内に取得する。事前リサーチを 1 案件 3-6 時間 → 30 分 に短縮し、案件受任後の手戻り (許可取得後に「補助金を知らなかった」発覚 / 業者の過去処分見落とし) を防ぐ。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` (案件別計上、契約番号と連動)
- 法人番号 (13 桁) or 個人事業主の T + 13 桁
- 許認可種別 (`license_construction` / `license_waste` / `visa_engineer` / etc.)
- (任意) 申請担当者・経営業務管理責任者の連絡先

## 入力例
```json
{
  "subject_kind": "corp",
  "subject_id": "8010001213708",
  "scope": ["license_construction", "enforcement", "invoice", "subsidy_match"],
  "include_facts": true,
  "client_tag": "case-construction-001"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: case-construction-001" \
  -H "Content-Type: application/json" \
  -d '{"subject_kind":"corp","subject_id":"8010001213708","include_facts":true,"scope":["license_construction","enforcement","invoice"]}' \
  "https://api.jpcite.com/v1/evidence/packets/query"
```
### Python
```python
import os, requests, json
HB = "8010001213708"
r = requests.post("https://api.jpcite.com/v1/evidence/packets/query",
    headers={"X-API-Key": os.environ["JPCITE_API_KEY"], "X-Client-Tag": HB},
    json={"subject_kind": "corp", "subject_id": HB, "include_facts": True,
          "scope": ["license_construction", "enforcement", "invoice"]})
print(json.dumps(r.json()["packet"], ensure_ascii=False, indent=2))
```
### TypeScript
```ts
const r = await fetch("https://api.jpcite.com/v1/evidence/packets/query", {
  method: "POST",
  headers: { "X-API-Key": process.env.JPCITE_API_KEY!, "Content-Type": "application/json" },
  body: JSON.stringify({
    subject_kind: "corp", subject_id: "8010001213708", include_facts: true,
    scope: ["license_construction", "enforcement", "invoice"]
  })
});
const d = await r.json();
console.log(d.packet);
```

## 出力例 (artifact)
```json
{
  "legal_id": "8010001213708",
  "name": "サンプル建設株式会社",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.mlit.go.jp/totikensangyo/const/...",
  "license_construction": {
    "required_docs": [
      "登記事項証明書",
      "納税証明書 (その1 + その3)",
      "健康保険等加入証明",
      "技術者証明 (経営業務管理責任者 + 専任技術者)",
      "財産的基礎要件証明"
    ],
    "prereq_met": ["invoice_registered", "tax_paid"],
    "prereq_unknown": ["technical_competence", "financial_base"]
  },
  "enforcements_5y": [],
  "invoice_registrant": {"registered": true, "registered_date": "2023-10-01"},
  "subsidy_matches_top3": [
    {"program_id": "mlit-zero-energy-2026", "fit_score": 0.74, "deadline": "2026-08-15"}
  ],
  "known_gaps": ["過去 5 年超の業務停止は corpus 未収録"],
  "_disclaimer": {"sec1": "本出力は提出書類チェックリストであり、許可可否判定ではありません (行政書士法 §1)。"}
}
```

## known gaps
- 過去 5 年超の業務停止 / 監督処分は corpus 未収録、別途国交省 portal 確認
- 技術者証明 (経管 / 専技) の保有資格判定は本 recipe 対象外、申請者ヒアリングで補完
- 財産的基礎要件 (自己資本 ¥500 万以上 / 直前 5 年間建設業継続) は申請者財務 DD で別途確認
- 47 都道府県の建設業許可 (一般 / 特定) と国土交通大臣許可の管轄判定は申請地域 + 営業所所在地で行政書士判断
- 排他ルール (`check_exclusions`) は重複申請禁止条項のみ、業法上の併願制限は別途確認

## 関連 tool
- `evidence_packets_query` (本 recipe 中核、4 source 一括取得)
- `search_certifications` (経営事項審査 / 監理技術者 等)
- `get_corp_360` (法人 360 度ビュー)
- `check_exclusions` (排他ルール 181 件チェック)
- `pack_construction` (Wave 23、建設業 industry pack)

## 関連 recipe
- [r06-sharoushi-grant-match](../r06-sharoushi-grant-match/) — 社労士助成金マッチ
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/) — 診断士月次伴走
- [r13-shihoshoshi-registry-watch](../r13-shihoshoshi-registry-watch/) — 司法書士 registry watch

## billable_units 試算
- 1 案件 6 units × ¥3 = ¥18 / 案件
- 月 25 案件 = ¥450 / 月、税込 ¥495
- 月 50 案件 (大手事務所) = ¥900 / 月、税込 ¥990
- ROI: 懲戒 1 回回避 (¥80 万) で 1,777 倍、紹介喪失 1 件回避 (¥50 万 LTV) で 1,111 倍

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 受任面談資料 / 申請書類事前 DD への組込可、jpcite + 国交省 / 厚労省出典の両明記
- 顧客 (依頼者) への提供は事実通知に留め、法的判断は別途行政書士

## 業法 fence
- 行政書士法 §1 — 申請書面作成は行政書士独占、本 recipe は scaffold + 一次 URL まで
- 行政書士法 §13 / §14 — 懲戒対象を回避するため過去処分歴の見落とし防止を支援
- 弁護士法 §72 — 法的紛争予測は弁護士、本 recipe は事実列挙
- 司法書士法 §3 — 登記関連は司法書士、本 recipe は登記簿補完情報まで
- 景表法 §5 — `fit_score` / `prereq_met` は推定値、申請可否判定ではない

## canonical_source_walkthrough

> 一次資料 / canonical source への walk-through。Wave 21 C6 で全 30 recipes に追加。

### 使う tool
- **MCP tool**: `rule_engine_check + apply_eligibility_chain_am`
- **REST endpoint**: `/v1/am/rule_check + /v1/am/eligibility_chain`
- **jpcite.com docs**: <https://jpcite.com/recipes/r05-gyosei-licensing-eligibility/>

### expected output
- JSON: passed/failed predicates list + exclusion_rule_id + 法令条文 url
- 全 response に `fetched_at` (UTC ISO 8601) + `source_url` (一次資料 URL) 必須
- `_disclaimer` envelope (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3 / 弁護士法 §72 等の業法 fence 該当時)

### 失敗時 recovery
- **404 Not Found**: exclusion_rules に該当 license type 無し — issue で報告
- **429 Too Many Requests**: checklist bulk は X-Client-Tag client-{id} で fan-out
- **5xx / timeout**: 60s wait、jpcite.com/status で復旧確認

### canonical source (一次資料)
- 国税庁 適格事業者公表サイト: <https://www.invoice-kohyo.nta.go.jp/>
- 中小企業庁 補助金一覧: <https://www.chusho.meti.go.jp/>
- e-Gov 法令検索: <https://laws.e-gov.go.jp/>
- 国立国会図書館 NDL: <https://www.ndl.go.jp/>
- jpcite 一次資料 license 表: <https://jpcite.com/legal/licenses>
