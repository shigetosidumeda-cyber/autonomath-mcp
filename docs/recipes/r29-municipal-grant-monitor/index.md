---
title: "市町村独自補助金モニター"
slug: "r29-municipal-grant-monitor"
audience: "横串 (自治体施策 watch)"
intent: "municipal_monitor"
tools: ["list_municipal", "search_programs", "get_municipality"]
artifact_type: "municipal_diff.json"
billable_units_per_run: 47
seo_query: "市町村 独自 補助金 モニター 自治体"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 市町村独自補助金モニター

## 想定 user
47 都道府県 + 1,741 市町村 + 23 特別区 + 20 政令市の独自補助金 / 助成金 / 認証 / 認定制度を毎週差分配信で受け取り、特定地域 (例: 関東圏 / 関西圏 / 北海道 / 九州) または特定業種 (例: IT / 製造 / 農林水産 / 飲食) をターゲットにする商工会連合会 / 商工会議所 / 信用金庫 / 中小企業診断士 / 補助金 SaaS / 自治体施策コンサル / 大学院政策研究室 等の watch 担当者。週次差分で新規公示 + 募集終了 + 要綱改訂を縦覧し、自治体ごとの独自施策動向を四半期レポート化する用途も含む。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- 47 都道府県コード (01-47) or 市区町村コード (5 桁、総務省 LGCode)
- 週次 cron 環境 (n8n / GitHub Actions / Fly cron / Cloud Functions / Lambda 等)
- (任意) 業種フィルタ (JSIC 中分類)
- (任意) 補助金額レンジ (例: ¥100K-¥10M)

## 入力例
```json
{
  "prefecture_codes": ["01", "02", "13", "14", "27"],
  "since": "2026-05-04",
  "include_municipal": true,
  "industry_filter": ["it", "manufacturing"],
  "tier_min": "B",
  "client_tag": "municipal-watch-2026"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: municipal-watch-2026" \
  "https://api.jpcite.com/v1/programs/municipal/diff?since=2026-05-04&pref=11,12,13,14&include_municipal=true"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/municipalities/13104/programs?status=open"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/programs/municipal/diff?since=2026-05-04&pref=all"
```
### Python
```python
import os, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="municipal-watch-2026")
diff = c.municipal_diff(
    prefecture_codes=["all"], since="2026-05-04",
    include_municipal=True, industry_filter=["it", "manufacturing"],
)
out = {"fetched_at": diff.fetched_at,
       "added_programs": diff.added_programs,
       "removed_programs": diff.removed_programs,
       "modified_programs": diff.modified_programs}
with open(f"municipal_diff_{diff.fetched_at[:10]}.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const diff = await jpcite.municipal_diff({
  prefecture_codes: ["13", "14"], since: "2026-05-04",
  include_municipal: true, client_tag: "municipal-watch-2026",
});
console.log(`新規 ${diff.added_programs.length} 件、削除 ${diff.removed_programs.length} 件`);
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.city.shinjuku.lg.jp/...",
  "since": "2026-05-04",
  "scanned_prefectures": 47,
  "scanned_municipalities": 1741,
  "added_programs": [
    {"program_id": "shinjuku-it-2026", "name": "新宿区 IT 導入補助金",
     "issuer": "新宿区産業振興課", "max_amount_jpy": 500000, "subsidy_rate": "2/3",
     "deadline": "2026-09-30", "tier": "B",
     "primary_source": "https://www.city.shinjuku.lg.jp/sangyo/it_dounyu_2026.html"}
  ],
  "removed_programs": [],
  "modified_programs": [],
  "client_tag": "municipal-watch-2026",
  "known_gaps": ["municipal page redesign 検知遅延", "公示 → 取込 7-14 日"]
}
```

## known gaps
- 自治体サイト改修で URL 変動による検知遅延 (URL 変更後 1-3 週間 lag)
- 公示 → jpcite 取込 7-14 日 (週次 ETL バッチ)
- 1,741 市町村のうち RSS / API 提供は 280、残り 1,461 はスクレイピング週次バッチで 7-14 日 lag
- 政令市 (20) + 中核市 (62) + 一般市 + 町村のうち、政令市 + 中核市は逐次対応、一般市以下は申請ベース対応
- 自治体独自の認定 (例: SDGs 認証 / 子育てしやすい街認定) は補助金とは別系統 (`certifications` table)
- 自治体合併 / 名称変更は施行翌週から反映

## 関連 tool
- `list_municipal` (本 recipe 中核、都道府県 + 市町村の補助金一覧)
- `search_programs` (キーワード + 業種 + tier で全国横串)
- `get_municipality` (個別自治体の制度一覧 + 担当窓口)
- `municipal_diff` (差分取得、cron 用)

## 関連 recipe
- [r10-cci-municipal-screen](../r10-cci-municipal-screen/index.md) — 商工会議所 市町村 sweep、会員企業との突合
- [r22-n8n-zapier-webhook](../r22-n8n-zapier-webhook/index.md) — n8n / Zapier、差分配信自動化

## billable_units 試算
- 1 batch 47 units × ¥3 = ¥141 / 週
- 月 4 週 = ¥564 / 月、税込 ¥620
- 1,741 市町村全件 = 1 batch 1,741 units × ¥3 = ¥5,223 / 週、月 ¥20,892、税込 ¥22,981
- API fee delta: 47 自治体 × 月 4 週で、外部 model/search API fee は約 ¥1,880/月 (1 batch cycle ¥470 = 47 自治体 diff fetch + filter) に対し jpcite は ¥564/月 (188 req × ¥3) → API fee delta 約 ¥1,316/月 / 自治体あたり ¥28 (cf. `docs/canonical/cost_saving_examples.md` case 6 同系)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 自治体出典明記 (例: `https://www.city.shinjuku.lg.jp/...`)
- 週次レポート / 商工会報 / 会員企業向け fan-out OK、jpcite + 自治体出典の両明記
- 公開資料に基づく公知情報、NDA 対象外

## 業法 fence
- 公開情報、再配布は出典明記で OK
- 申請助言は資格者 (中小企業診断士 / 行政書士 / 認定支援機関)
- 業法 fence (税理士法 §52 / 行政書士法 §1) — 配信は scaffold + 一次 URL まで、申請書面作成は資格者
- 景表法 §5 — `tier` / `subsidy_rate` は公示値、保証ではない旨を配信末尾に注記推奨
