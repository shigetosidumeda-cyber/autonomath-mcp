# R10 — 類似採択事例 検索

採択事例 (case_studies) を業種 (JSIC) × 都道府県 × FTS キーワードで検索し、申請書類の類似事例参照に使う。

- **Audience (cohort)**: C5 HOJ (補助金 consultant) primary / C8 IND (Industry packs) secondary / C1 MA (M&A pre-DD)
- **Use case**: 「同業種・同地域・同テーマの過去採択先」をリスト化、申請書 / 事業計画の方向性検証
- **Disclaimer**: なし (公表採択事例の引用) ※ 金額利用は sentinel に注意
- **Cost**: ¥3/search (税込 ¥3.30)

## TL;DR

`/v1/case-studies/search?industry_jsic=E&prefecture=東京都&q=...` で業種大分類 (JSIC) × 都道府県 × 任意キーワードで採択事例を抽出。`recipient_name` 公開分のみ (個人事業主は名称非公開)。

## Sample (bash)

```bash
# 製造業 (JSIC E) × 東京都 × 「省エネ」関連の採択事例 20 件
curl -s "https://api.jpcite.com/v1/case-studies/search?industry_jsic=E&prefecture=東京都&q=省エネ&limit=20" \
  -H "X-API-Key: $JPCITE_API_KEY" \
  | jq '.results[] | {case_id, recipient_name, program_name, year, source_url}'
```

## Sample (python)

```python
import requests, os
r = requests.get(
    "https://api.jpcite.com/v1/case-studies/search",
    params={"industry_jsic": "E", "prefecture": "東京都", "q": "省エネ", "limit": 20},
    headers={"X-API-Key": os.environ["JPCITE_API_KEY"]},
)
for c in r.json().get("results", []):
    print(c["case_id"], c.get("recipient_name") or "(非公開)", c["program_name"], c.get("year"))
```

## Expected output (excerpt)

```
CASE-... ○○製作所 ものづくり補助金 2024
CASE-... △△工業 省エネ設備導入補助金 2025
CASE-... (非公開) 東京都 設備投資補助金 2024
```

## 代替手段 vs jpcite cost

| 手段 | コスト | 備考 |
|---|---|---|
| 中企庁 / 経産省 採択事例集 PDF を年次別 grep | 90 min × ¥5,000/h = **¥7,500** | OCR 漏れ、業種分類不統一 |
| 補助金 SaaS の事例検索 | ¥5,000-30,000/月 | アグリゲータ依存、`recipient_name` 取り扱い不透明 |
| jpcite case-studies/search | **¥3** (税込 ¥3.30) | JSIC 業種 + 都道府県 + FTS、`source_url` 一次のみ |

**約 2,500 倍のコスト削減**。consultant が新規顧客の業界研究を秒で完了。

## Caveat (sentinel)

- `total_subsidy_received_yen` は **< 1% しか populated されていない**。**金額 sort は誤読の元**、件数 sort + program_name 集約で評価する。
- `recipient_name` は中企庁公表分のみ。個人事業主 / 一部企業は伏せ字 / 不公開。
- データ件数は 2,286 件 (2026-04-29 時点)。網羅性ではなく「公開された代表例」として扱う。

## 関連

- [R09 法人 360 view](r09-corp-360-view.md)
- [R11 行政処分 watch](r11-enforcement-watch.md)
- [API reference: /v1/case-studies/search](../api-reference.md)
