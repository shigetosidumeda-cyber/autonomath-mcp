# R02 — 税法改正 cliff-date weekly digest

14 日以内に effective_until (適用期限) を迎える tax_rulesets を抽出し、税理士事務所内で週次配信する。

- **Audience (cohort)**: C2 ZEI (税理士) primary / C3 KAI (会計士) secondary
- **Use case**: 期限切れ間近の特例措置 (例: 措置法 各種) の見落とし防止
- **Disclaimer**: §52 (税理士法) — 適用判定は税理士確認
- **Cost**: ¥3/週 (税込 ¥3.30) / digest

## TL;DR

`/v1/tax_rulesets/search?effective_until_before=<date>` で 14 日先の cliff-date filter を効かせ、上位 50 件を pull。週次 cron で digest 化。

## Sample (python)

```python
import requests, datetime, os

horizon = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
r = requests.get(
    "https://api.jpcite.com/v1/tax_rulesets/search",
    params={"effective_until_before": horizon, "limit": 50},
    headers={"X-API-Key": os.environ["JPCITE_API_KEY"]},
)

print(f"# 税法改正 cliff-date digest ({horizon} まで適用期限)\n")
for ts in r.json().get("results", []):
    print(f"- {ts['unified_id']} {ts['primary_name']}")
    print(f"  effective_until: {ts.get('effective_until')}")
    print(f"  source: {ts.get('source_url')}")
```

## Expected output (excerpt)

```
# 税法改正 cliff-date digest (2026-05-18 まで適用期限)

- TAX-S20-... 電帳法 経過措置
  effective_until: 2026-05-15
  source: https://www.nta.go.jp/...
- TAX-S21-... 賃上げ促進税制 (中小)
  effective_until: 2026-05-17
  source: https://www.chusho.meti.go.jp/...
```

## 代替手段 vs jpcite cost

| 手段 | コスト (月 4 回) | 備考 |
|---|---|---|
| 国税庁 / 中企庁 / 経産省 の改正 page を週次手動巡回 | 60 min × 4 = 4h × ¥5,000/h = **¥20,000** | 適用期限 column が page により異なる |
| 税務 SaaS (例: 改正解説サブスク) | ¥5,000-30,000/月 | 横断検索なし、cliff-date filter なし |
| jpcite tax_rulesets/search | 4 × ¥3 = **¥12** (税込 ¥13.20) | 全 50 件 effective_until ベースで filter |

**約 1,500 倍のコスト削減**。digest を顧問先別 fan-out (R01 と組み合わせ) すれば weekly KPI として運用可能。

## §52 disclaimer

```
本一覧は公開資料に基づく cliff-date 抽出です。各措置の適用
要件・経過措置・継続適用判定は、税理士が最終確認の上ご対応
ください。
```

`tax_rulesets` レスポンスに `_disclaimer` envelope が乗る (税法改正は §52 領域として常時付与)。

## 関連

- [R01 顧問先別 補助金 weekly alert](r01-weekly-alert-per-client.md)
- [法令改正の確認](../api-reference.md)
- [API reference: /v1/tax_rulesets/search](../api-reference.md)
