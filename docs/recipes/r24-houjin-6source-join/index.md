---
title: "法人 6 source join (素材レイヤ)"
slug: "r24-houjin-6source-join"
audience: "AI agent dev / SaaS"
intent: "houjin_6source_join"
tools: ["get_corp_360", "list_adoptions", "get_enforcement", "check_invoice_status", "search_edinet", "get_bid_history"]
artifact_type: "houjin_join.parquet"
billable_units_per_run: 50
seo_query: "法人 6 source join 採択 行政処分 適格事業者 EDINET 入札"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 法人 6 source join (素材レイヤ)

## 想定 user
SaaS 開発者 / agent dev / リサーチャー / 大学院生で、法人番号 1 件から 6 つの公的 source (1) 採択履歴、(2) 行政処分、(3) 適格事業者状況、(4) EDINET 重要事実、(5) 公共入札落札、(6) 商号 / 住所 / 代表者変更 を 1 envelope で join した parquet / JSON を取得し、自社 SaaS の DB に取り込む素材レイヤとして使う。本 recipe は最も汎用的な素材 endpoint で、他の recipe (r03 M&A DD / r09 BPO トリアージ / r12 監査 KYC / r15 SaaS enrich) の下流に位置する。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` (用途別計上)
- 法人番号 (13 桁、国税庁付番)
- (推奨) Idempotency-Key (大量 batch の冪等性確保)

## 入力例
```json
{
  "corp_number": "7010001234567",
  "sources": ["adoption", "enforcement", "invoice", "edinet", "bid", "amendment"],
  "lookback_years": 7,
  "include_facts": true,
  "include_provenance": true,
  "client_tag": "saas-6source-2026"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: saas-6source-2026" \
  "https://api.jpcite.com/v1/corp/7010001234567/360?sources=adoption,enforcement,invoice,edinet,bid,amendment&lookback_years=7&include_facts=true&include_provenance=true"

curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "Content-Type: application/json" \
  -d '{"subject_kind":"corp","subject_id":"7010001234567","scope":["adoption","enforcement","invoice","edinet","bid","amendment"]}' \
  "https://api.jpcite.com/v1/evidence/packets/query"
```
### Python
```python
import os, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="saas-6source-2026")
snap = c.get_corp_360(
    corp_number="7010001234567",
    sources=["adoption", "enforcement", "invoice", "edinet", "bid", "amendment"],
    lookback_years=7, include_facts=True, include_provenance=True,
)
with open("houjin_join.json", "w") as f:
    json.dump(snap.__dict__, f, ensure_ascii=False, indent=2)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const snap = await jpcite.get_corp_360({
  corp_number: "7010001234567",
  sources: ["adoption", "enforcement", "invoice", "edinet", "bid", "amendment"],
  lookback_years: 7, include_facts: true, include_provenance: true,
  client_tag: "saas-6source-2026",
});
fs.writeFileSync("houjin_join.json", JSON.stringify(snap, null, 2));
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "corpus_snapshot_id": "2026-05-07",
  "content_hash": "sha256:8c91...a3f4",
  "source_urls": [
    "https://www.chusho.meti.go.jp/...",
    "https://www.mlit.go.jp/.../enforcement",
    "https://www.invoice-kohyo.nta.go.jp/.../detail",
    "https://disclosure.edinet-fsa.go.jp/...",
    "https://www.kkj.go.jp/.../bid",
    "https://www.houjin-bangou.nta.go.jp/..."
  ],
  "adoptions_7y": [{"program": "meti-mono-2024-r2", "amount_jpy": 8000000}],
  "enforcements_7y": [],
  "invoice_status": "active",
  "edinet_material_facts": [],
  "bid_history_3y": [{"bid_id": "kkj-2024-001", "issuer": "総務省", "amount_jpy": 15000000}],
  "amendment_log": [{"changed_at": "2024-06-15", "field": "representative"}],
  "client_tag": "saas-6source-2026",
  "known_gaps": ["EDINET 開示は上場会社のみ", "公共入札は中央 + 都道府県 + 政令市のみ"]
}
```

## known gaps
- EDINET 開示は上場会社 + 大量開示書類提出者のみ、非上場中小は対象外
- 公共入札は中央省庁 + 47 都道府県 + 20 政令市まで、中核市以下は逐次拡大中
- 反社 DB は別契約必須、本 recipe は公示行政処分のみ
- 海外子会社・関連法人は EDINET 開示外の場合は捕捉不能
- 7 年遡及は処分公表期間と突合が必要、本 recipe は遡及年数のみで打ち切り

## 関連 tool
- `get_corp_360` (本 recipe 中核、6 source 一括)
- `list_adoptions` (採択履歴)
- `get_enforcement` (行政処分)
- `check_invoice_status` (適格事業者状況)
- `search_edinet` (EDINET 重要事実)
- `get_bid_history` (公共入札落札)

## 関連 recipe
- [r03-sme-ma-public-dd](../r03-sme-ma-public-dd/) — M&A DD、本 recipe の上流ユースケース
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/) — 監査法人 KYC
- [r15-grant-saas-internal-enrich](../r15-grant-saas-internal-enrich/) — SaaS 内部 enrich、本 recipe の bulk 版

## billable_units 試算
- 1 法人 50 units × ¥3 = ¥150 / 法人
- 月 100 法人 = ¥15,000 / 月、税込 ¥16,500
- 月 1,000 法人 = ¥150,000 / 月、税込 ¥165,000
- 節約 (純 LLM vs jpcite ¥3/req): 月 100 法人 join で、純 LLM は約 ¥21,000/月 (1 法人 cycle ¥210 = 6 source × 35 = 6 別 fetch + reasoning) に対し jpcite は ¥15,000/月 (5,000 req × ¥3, join 済 envelope は 50 req/法人) → 節約 約 ¥6,000/月 / 法人あたり ¥60 (cf. `docs/canonical/cost_saving_examples.md` case 1 / case 2 同系、別途 SaaS 開発工数 50-80% 圧縮は ADDENDUM)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- SaaS 内部の素材レイヤ利用 OK、最終出力に jpcite 出典明記
- 二次卸 (他 SaaS への ETL 出力) は別途要相談
- 法人番号は公開情報、個社名特定可

## 業法 fence
- 弁護士法 §72 — 法的判断は弁護士、本 recipe は事実通知層まで
- 公認会計士法 / 税理士法 §52 — 監査 / 税務判断は資格者
- 個人情報保護法 — 代表者氏名 / 住所等は個人情報、`include_pii=false` で削除可
- 景表法 §5 — 統計推定値含む、保証ではない旨を SaaS UI に明示
