---
title: "法令改正 → 補助金リンク"
slug: "r27-law-amendment-program-link"
audience: "横串 (法改正トラッキング)"
intent: "law_program_link"
tools: ["search_laws", "search_programs", "get_program_detail"]
artifact_type: "law_link_report.md"
billable_units_per_run: 5
seo_query: "法令改正 補助金 連動 トラッキング"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 法令改正 → 補助金リンク

## 想定 user
中小企業政策・税制大綱・労働関連法改正・環境関連法改正・DX 推進政策の発表に紐付けて、新規創設 / 拡充 / 終了予定の補助金リスト + 関連通達 + 国税不服審判所 裁決を 5 分でまとめるリサーチャー / 記者 / 業界団体スタッフ / シンクタンク研究員 / 大学院生・研究者・士業事務所の最新情報 watch 担当。法改正速報 (税務通信 / 戦略経営者通信 / TKC 戦略経営者通信 / 月刊 / 週刊 ベース) と jpcite の構造化データを突合させ、見落とし防止 + 顧客向け解説資料の素材作成を目標とする。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- 法令名 (e-Gov 法令検索の正式名称) or 法令 ID or 公布日
- e-Gov 法令検索の URL (一次資料リンク)
- (任意) 関連通達番号 (国税庁 法令解釈通達 / 厚労省 業務取扱要領 等)
- (任意) 監視業種フィルタ (JSIC 中分類)

## 入力例
```json
{
  "law_id": "ho15a-r6",
  "law_name": "中小企業基本法",
  "publication_date": "2026-04-01",
  "include": ["related_programs", "tax_rulesets", "notification", "saiketsu"],
  "tier_min": "B",
  "client_tag": "researcher-2026"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/laws/ho15a-r6/related_programs?tier_min=B"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/laws/ho15a-r6?include_diff=true"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/laws/ho15a-r6/notifications"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="researcher-2026")
law = c.get_law_with_related(
    law_id="ho15a-r6",
    include=["related_programs", "tax_rulesets", "notification", "saiketsu"],
    tier_min="B",
)
md = f"# {law.name} (公布: {law.publication_date})\n\n出典: {law.source_url}\n\n## 関連補助金\n"
for p in law.related_programs:
    md += f"- {p.program_id}: {p.name} (tier={p.tier}, 出典: {p.source_url})\n"
md += "\n## 関連通達\n"
for t in law.notifications:
    md += f"- {t.id}: {t.title} ({t.issued_at})\n"
with open("law_link_report.md", "w") as f:
    f.write(md)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const law = await jpcite.get_law_with_related({
  law_id: "ho15a-r6",
  include: ["related_programs", "tax_rulesets", "notification"],
  tier_min: "B", client_tag: "researcher-2026",
});
console.log(`関連補助金: ${law.related_programs.length} 件`);
```

## 出力例 (artifact)
```json
{
  "law_id": "ho15a-r6",
  "law_name": "中小企業基本法",
  "publication_date": "2026-04-01",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://elaws.e-gov.go.jp/document?lawid=338AC0000000154",
  "related_programs": [
    {"program_id": "meti-mono-2026-r5", "name": "ものづくり補助金 第18次",
     "linkage": "中小ものづくり技術強化", "tier": "S",
     "source_url": "https://portal.monodukuri-hojo.jp/..."}
  ],
  "tax_rulesets": [
    {"rule_id": "meas-42-12-5", "name": "賃上げ促進税制", "linkage": "中小企業基本法 §3 賃上げ促進"}
  ],
  "notifications": [
    {"id": "nta-2026-0401", "title": "中小企業基本法改正に伴う消費税の取扱い", "issued_at": "2026-04-01"}
  ],
  "saiketsu_recent": [],
  "client_tag": "researcher-2026",
  "known_gaps": ["施行から 30 日以内は紐付け遅延", "改正附則の解釈は専門家確認推奨"]
}
```

## known gaps
- 法改正から 30 日は手動レビュー要 (jpcite の法令→補助金リンク作成は専門家チェック付き、初動は手動)
- 改正附則の解釈は専門家確認推奨、本 recipe は条文 + 関連補助金の機械的紐付けまで
- 通達 (国税庁 法令解釈通達 / 厚労省 業務取扱要領) のうち jpcite 収録は 3,221 件、地方厚生局 ローカル通達は欠損あり
- 国税不服審判所 裁決 は 137 件のみ、業種薄い
- 法令名の表記揺れ (略称 / 正式名称 / 通称) — `law_name` ヒットしない場合は `law_id` で直接指定

## 関連 tool
- `search_laws` (法令名 / 番号 / 公布日 で検索)
- `search_programs` (キーワード + 関連法令 ID で絞り込み)
- `get_program_detail` (補助金原文取得)
- `get_law_with_related` (法令 → 関連 4 source 一括取得、本 recipe の中核)

## 関連 recipe
- [r22-n8n-zapier-webhook](../r22-n8n-zapier-webhook/) — n8n / Zapier、法改正速報 + 通知自動化
- [r28-edinet-program-trigger](../r28-edinet-program-trigger/) — EDINET 連動、上場会社の改正対応 trigger
- [r29-municipal-grant-monitor](../r29-municipal-grant-monitor/) — 市町村独自補助金、改正連動部分の差分

## billable_units 試算
- 1 件 5 units × ¥3 = ¥15
- 法改正 10 件 / 月 = ¥150 / 月、税込 ¥165
- 法改正 50 件 / 月 (大手シンクタンク level) = ¥750 / 月、税込 ¥825
- 節約 (純 LLM vs jpcite 標準従量料金): 月 10 件法改正 link で、純 LLM は約 ¥500/月 (1 件 cycle ¥50 = 法令本文 + 補助金 + 通達 cross-ref + tool 6) に対し jpcite は ¥150/月 (50 req × ¥3) → 節約 約 ¥350/月 / 件あたり ¥35 (cf. `docs/canonical/cost_saving_examples.md` case 6 同系)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 法令本文は e-Gov 出典明記、補助金 / 通達は所管省庁出典明記
- リサーチャーレポート / 業界誌記事 / シンクタンクレポートへの組込可、jpcite + 一次資料の両出典明記
- 公開資料に基づく公知情報、NDA 対象外

## 業法 fence
- 法的解釈は弁護士領域、本 recipe は情報整理のみ (弁護士法 §72)
- 税務判断は税理士領域、関連税制 / 通達紐付けは scaffold まで (税理士法 §52)
- 改正附則の細部は専門家確認必須、本 recipe は条文 + 補助金紐付けまで
- 景表法 §5 — `linkage` は機械的紐付け結果、保証ではない旨を レポート末尾に注記推奨
