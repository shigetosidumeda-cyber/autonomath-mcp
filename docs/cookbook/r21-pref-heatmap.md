# R21 — 47 都道府県 補助金 heatmap

47 都道府県をループして tier=S/A の制度件数を集計し、SVG / Plotly の choropleth heatmap を作る。

- **Audience (cohort)**: C7 SKK (信金 / 商工会 organic) primary / C5 HOJ (補助金 consultant) secondary
- **Use case**: 信金 / 商工会の地域 SEO 配信、補助金 consultant の地域別マーケット視覚化
- **Disclaimer**: なし (集計は公開検索結果のみ; tier=X quarantine は除外済)
- **Cost**: 47 × ¥3 = ¥141 (税込 ¥155) / build

## TL;DR

`/v1/programs/search?prefecture={pref}&tier=S,A&limit=1` を 47 回叩いて `total` のみ受け取り、47 件の (prefecture, count) を Plotly choropleth に渡す。`limit=1` なので response payload は最小、料金は req 数 (47) で決まる。

## Sample (python)

```python
import requests, os

PREF = [
    "北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県",
    "茨城県","栃木県","群馬県","埼玉県","千葉県","東京都","神奈川県",
    "新潟県","富山県","石川県","福井県","山梨県","長野県","岐阜県",
    "静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県",
    "奈良県","和歌山県","鳥取県","島根県","岡山県","広島県","山口県",
    "徳島県","香川県","愛媛県","高知県","福岡県","佐賀県","長崎県",
    "熊本県","大分県","宮崎県","鹿児島県","沖縄県",
]
HEADERS = {"X-API-Key": os.environ["JPCITE_API_KEY"]}

counts = {}
for p in PREF:
    r = requests.get("https://api.jpcite.com/v1/programs/search",
        params={"prefecture": p, "tier": ["S", "A"], "limit": 1}, headers=HEADERS)
    counts[p] = r.json().get("total", 0)

# Plotly choropleth (folium + 日本 GeoJSON でも可)
import plotly.express as px
import pandas as pd
df = pd.DataFrame({"pref": list(counts), "count": list(counts.values())})
fig = px.choropleth(df, locations="pref", color="count", scope="asia",
                    title="都道府県別 tier=S/A 補助金件数 (jpcite)")
fig.write_html("subsidy_heatmap.html")
```

## Expected output (excerpt)

```python
{'東京都': 1872, '大阪府': 1041, '愛知県': 712, ..., '沖縄県': 89, '全国': 4188}
```

47 行 + 「全国」(prefecture 指定なしの一括件数を 別 req で取得すれば 48 req / ¥144 で全国対比できる)。

## 代替手段 vs jpcite cost

| 手段 | コスト (1 build) | 備考 |
|---|---|---|
| 各都道府県 site + 中企庁ポータル巡回 | 8-12h × ¥5,000/h = **¥40,000-60,000** | tier 概念がなく主観集計、再現困難 |
| 補助金 SaaS の地域 dashboard | ¥10,000-50,000/月 | カテゴリ粒度が荒く、tier=S/A 相当指標なし |
| jpcite 47 req | **¥141** (税込 ¥155) | tier 厳密集計、再ビルドも自由 |

**約 280-400 倍のコスト削減**。週次 cron で 7 日 × 47 req = ¥1,000/月の継続更新も可能。

## Caveat (tier filter)

- `tier=X` は **quarantine** カラムで、データ品質が一定基準に達していない制度。`generate_program_pages.py` でも除外しており、heatmap でも常に除外する。
- `tier=B` / `tier=C` を含めるかは目的次第。SEO の信頼度シグナルとしては S/A のみが推奨。

## 関連

- [R10 類似採択事例 検索](r10-case-studies-search.md)
- [API reference: /v1/programs/search](../api-reference.md)
