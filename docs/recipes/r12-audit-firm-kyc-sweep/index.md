---
title: "監査法人の KYC スイープ"
slug: "r12-audit-firm-kyc-sweep"
audience: "監査法人"
intent: "kyc_sweep"
tools: ["get_corp_360", "get_enforcement", "check_invoice_status", "list_adoptions", "search_edinet"]
artifact_type: "kyc_pack.zip"
billable_units_per_run: 32
seo_query: "監査法人 KYC 反社 行政処分 適格事業者"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 監査法人の KYC スイープ

## 想定 user
監査法人 (Big4 / 中堅 / 中小) が新規クライアント受嘱の独立性チェック・受嘱可否判定のために、対象会社の行政処分歴・補助金不正受給歴・適格事業者抹消歴・EDINET 重要事実・関連法人ネットワークを 5 分で一括把握する。受嘱判断委員会への提出資料 (kyc_pack.zip) を自動生成し、品質管理本部の継続監査でも同一フォーマットを再利用する用途。継続クライアントの年次更新時 (期初 1 週間で 200-500 社を一括) にも同一ジョブを流す運用が一般的。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` ヘッダー (クライアント別の billable 計上)
- 法人番号 (13 桁) + (任意) EDINET コード
- 遡及期間 (デフォルト 7 年、独立性チェックでは 5 年が一般)
- 取締役・主要株主の名簿 (任意、関連法人ネットワーク展開のため)

## 入力例
```json
{
  "corp_number": "7010001234567",
  "edinet_code": "E12345",
  "lookback_years": 7,
  "include_related_entities": true,
  "related_entities": ["8020005678901"],
  "axes": ["enforcement", "subsidy_fraud", "invoice", "edinet_material", "officer_history"]
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: client-axxx" \
  "https://api.jpcite.com/v1/corp/7010001234567/kyc?lookback=7&include_related=true"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/corp/7010001234567/related?hops=1"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/edinet/E12345/material_facts?lookback=7"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="client-axxx")
res = c.kyc_sweep(
    corp_number="7010001234567", lookback_years=7,
    axes=["enforcement", "subsidy_fraud", "invoice", "edinet_material", "officer_history"],
    include_related=True,
)
pack = c.build_kyc_pack(corp_number="7010001234567", result=res, format="zip")
with open("kyc_pack_7010001234567.zip", "wb") as f:
    f.write(pack)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const res = await jpcite.kyc_sweep({
  corp_number: "7010001234567", lookback_years: 7,
  axes: ["enforcement", "subsidy_fraud", "invoice", "edinet_material", "officer_history"],
  include_related: true,
});
const pack = await jpcite.build_kyc_pack({
  corp_number: "7010001234567", result: res, format: "zip",
});
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "lookback_years": 7,
  "source_urls": [
    "https://www.fsa.go.jp/.../enforcement.html",
    "https://www.invoice-kohyo.nta.go.jp/.../detail",
    "https://disclosure.edinet-fsa.go.jp/.../"
  ],
  "enforcement_7y": [],
  "subsidy_fraud_history": [],
  "invoice_status": {"current": "active", "events": [{"kind": "register", "at": "2023-10-01"}]},
  "edinet_material_facts": [],
  "officer_history": [{"role": "代表取締役", "name_hash": "...", "appointed": "2018-04-01"}],
  "related_entities": [{"corp_number": "8020005678901", "relation": "subsidiary"}],
  "risk_score": 0.12,
  "known_gaps": ["反社 DB は別契約必須", "個人代表者の処分歴は公開 DB 対象外"]
}
```

## known gaps
- 反社会的勢力 DB は別途専門業者 (帝国データバンク・東京商工リサーチ・MTSI 等) との契約必須、本 recipe では対象外
- 個人代表者の処分歴・破産歴は公開 DB の対象外、官報スクレイピングは別系統
- 海外子会社・関連法人 (Cayman / BVI 等) は EDINET 開示外の場合は捕捉不能
- 7 年遡及は処分公表期間 (5-10 年で各規制法により異なる) との突合が必要、本 recipe では遡及年数のみで打ち切り
- 取締役の同名異人判定 (no_match_explain) は別 API、本 recipe は氏名ハッシュのみ提供

## 関連 tool
- `get_corp_360` (法人 360 度ビューの単発取得)
- `get_enforcement` (行政処分の詳細)
- `check_invoice_status` (適格事業者状況、月次 4M 行 bulk 反映)
- `list_adoptions` (採択履歴、不正受給疑義の起点)
- `search_edinet` (EDINET 開示書類検索、重要事実の取得)

## 関連 recipe
- [r03-sme-ma-public-dd](../r03-sme-ma-public-dd/) — M&A DD、買収側の事前調査
- [r04-shinkin-borrower-watch](../r04-shinkin-borrower-watch/) — 信金 watch、与信側の継続監査
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 6 source join、KYC モデルの素材レイヤ

## billable_units 試算
- 1 法人 1 回 = 32 units × ¥3 = ¥96 / 受嘱
- 月 30 件 (Big4 中堅事務所平均) = ¥2,880 / 月
- 年次更新 200-500 社の bulk = 500 × ¥96 = ¥48,000 / 期初週
- 比較: 帝国データバンク KYC レポート ¥3,000-5,000 / 件、jpcite + 反社 DB 併用で半額〜2/3 まで圧縮可
- 節約 (純 LLM vs jpcite ¥3/req): 月 30 件 KYC で、純 LLM は約 ¥9,600/月 (1 受嘱 cycle ¥320 = 反社 DB + 法人 6 source + source 8,000 + tool 5) に対し jpcite は ¥2,880/月 (960 req × ¥3) → 節約 約 ¥6,720/月 / 受嘱あたり ¥224 (cf. `docs/canonical/cost_saving_examples.md` case 2)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0 (出典明記必須)
- kyc_pack.zip は監査法人内部の受嘱判断・品質管理利用のみ、対象会社への提供・外部公開は不可
- 委員会議事録への引用は出典明示で可、第三者監査人 (他法人) への共有は別途要相談

## 業法 fence
- 公認会計士法 (監査業務・独立性判断は会計士独占)
- 監査基準 (受嘱可否は法人内品質管理本部の決議、本 recipe は素材提供)
- 反社会的勢力チェックは別の専門業者領域 (反社 DB ベンダーとの契約必須)
- 個人情報保護法 (取締役氏名・住所等は個人情報、本 recipe は氏名ハッシュのみ provide)
- 金融商品取引法 (EDINET 重要事実の取扱は社内ルール準拠)
- 弁護士法 §72 (法的判断は弁護士、本 recipe は事実通知層に留める)
