---
title: "中小 M&A の公的 DD パック"
slug: "r03-sme-ma-public-dd"
audience: "M&A仲介"
intent: "due_diligence"
tools: ["get_corp_360", "list_adoptions", "get_enforcement"]
artifact_type: "dd_pack.zip"
billable_units_per_run: 28
seo_query: "中小 M&A DD 公的 補助金 行政処分 デューデリ"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 中小 M&A の公的 DD パック

## 想定 user
中小 M&A 支援機関 (M&A 仲介・FA・地銀 M&A 部門・事業承継・引継ぎ支援センター) の案件担当者で、買い手・売り手のいずれか (又は両方) に対して公的情報の DD (デューデリジェンス) を実施する。基本合意 (LOI) 直後 / 最終契約 (SPA) 前の 2 タイミングで、売り手の補助金返還義務 (財産処分制限期間) / 行政処分歴 / 適格事業者抹消歴 / 公共入札の指名停止有無を 5 分で把握し、後段の弁護士・会計士 DD のスコーピングと費用見積に直結させる。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- `X-Client-Tag` (案件別計上、契約書 / 請求書の通し番号と一致)
- 売り手 (target) 法人番号 + 買い手 (buyer) 法人番号
- (任意) M&A 支援機関登録番号 — artifact 脚注に記載すると顧客向け透明性が上がる

## 入力例
```json
{
  "target_corp": "7010001234567",
  "buyer_corp": "8010001234568",
  "lookback_years": 5,
  "client_tag": "ma-2026-0411",
  "include": ["adoption_clawback", "enforcement", "invoice_history", "bid_suspension", "houjin_amendment"],
  "language": "ja"
}
```
- `lookback_years`: 補助金財産処分制限の標準 5 年 + 設備の 8-15 年に合わせ 5-15 を指定
- `include`: 5 種類のうち選択、`bid_suspension` は公共入札の指名停止 (国 + 47 都道府県 + 政令市)
- `houjin_amendment`: 代表者 / 商号 / 住所 / 目的変更歴を遡及

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: ma-2026-0411" \
  "https://api.jpcite.com/v1/corp/7010001234567/360?include=adoption,enforcement,invoice_history,bid,amendment&lookback_years=5"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/corp/7010001234567/clawback_risk?lookback_years=5"
```
### Python
```python
import os, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"])
target = "7010001234567"
dd = c.get_corp_360(corp_number=target,
    include=["adoption", "enforcement", "invoice_history", "bid", "amendment"],
    lookback_years=5, client_tag="ma-2026-0411")
clawback = c.get_clawback_risk(target, lookback_years=5)
pack = {"target": target, "fetched_at": dd.fetched_at,
        "subsidy_clawback": clawback.obligations,
        "enforcement_history": dd.enforcement_history,
        "invoice_status": dd.invoice_status,
        "bid_suspension": dd.bid_suspension,
        "amendment_log": dd.amendment_log}
with open(f"dd_pack_{target}.json", "w") as f:
    json.dump(pack, f, ensure_ascii=False, indent=2)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const target = "7010001234567";
const dd = await jpcite.get_corp_360({
  corp_number: target,
  include: ["adoption", "enforcement", "invoice_history", "bid", "amendment"],
  lookback_years: 5, client_tag: "ma-2026-0411",
});
const clawback = await jpcite.get_clawback_risk({ corp_number: target, lookback_years: 5 });
fs.writeFileSync(`dd_pack_${target}.json`, JSON.stringify({ target, dd, clawback }, null, 2));
```

## 出力例 (artifact)
```json
{
  "target_corp": "7010001234567",
  "target_name": "サンプル製作所株式会社",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/v1/corp/7010001234567/360",
  "content_hash": "sha256:9e1d...3a7f",
  "subsidy_clawback_risk": [
    {"program": "meti-monozukuri-r4", "adopted_at": "2024-09-15", "amount_jpy": 12000000,
     "asset_useful_life_years": 5, "obligation_end": "2029-09-14", "remaining_months": 40,
     "source_url": "https://portal.monodukuri-hojo.jp/koubo/2024/r4/list.pdf"}
  ],
  "enforcement_history": [
    {"case_id": "mhlw-2023-0421", "agency": "厚生労働省", "law": "労働基準法", "action": "是正勧告",
     "issued_at": "2023-04-21", "source_url": "https://www.mhlw.go.jp/..."}
  ],
  "invoice_status": "active",
  "invoice_revocations": [],
  "bid_suspension": [],
  "amendment_log": [
    {"changed_at": "2023-06-01", "field": "representative", "from": "山田太郎", "to": "山田次郎"}
  ],
  "known_gaps": ["市町村補助金の財産処分制限期間 (耐用年数依存) は手動確認必要"],
  "recommended_followup": [
    "monozukuri r4 採択 1 件あり (残 40 ヶ月) — 譲渡時の財産処分承認申請が必要",
    "労基法 是正勧告 1 件あり (2023-04) — 弁護士 DD で改善状況の文書提出を要請"
  ]
}
```

## known gaps
- 市町村補助金の財産処分制限期間 (耐用年数依存 5-15 年)、市町村ごとに運用差あり、本 recipe は国 / 都道府県分のみ完全網羅
- 5 年超の古い案件は一次資料リンクで約 8% link rot、sentinel 化済
- 行政処分の都道府県分は 47 のうち独自 DB 提供 22 県、残り 25 県は四半期更新で 30-90 日 lag
- 公共入札 指名停止は中央省庁 + 47 都道府県 + 20 政令市まで、中核市以下は逐次拡大中
- 代表者氏名変更は法務局登記から 2 週間遡及

## 関連 tool
- `get_corp_360` (法人 6 source 統合 view)
- `list_adoptions` (採択履歴 5-15 年遡及)
- `get_enforcement` (行政処分 / 公表事案)
- `check_invoice_status` (適格事業者番号 + 抹消履歴)
- `get_clawback_risk` (補助金財産処分制限の残余月数算定)

## 関連 recipe
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/) — 監査法人 KYC、隣接領域
- [r13-shihoshoshi-registry-watch](../r13-shihoshoshi-registry-watch/) — 司法書士 registry watch
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 法人 6 source join、素材レイヤ

## billable_units 試算
- 1 DD 28 units × ¥3 = ¥84 / DD
- 月 10 案件 = ¥840 / 月、税込 ¥924
- 月 30 案件 = ¥2,520 / 月、税込 ¥2,772

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- DD レポート / IM への組込時は jpcite 出典明記
- 公開資料に基づく公知情報、NDA 対象外であることを明記推奨

## 業法 fence
- 弁護士法 §72 — 法的判断 (契約条項解釈 / 紛争予測 / 表明保証起案) は弁護士領域、本 recipe は事実列挙
- 公認会計士法 / 税理士法 §52 — 財務 DD / 税務 DD は資格者、本 recipe は公的データ提示まで
- 中小企業等経営強化法 / M&A 支援機関登録制度 — 登録 M&A 支援機関の業務範囲内
- 個人情報保護法 — 代表者氏名 / 住所等は artifact から削除可 (`include_pii=false`)
