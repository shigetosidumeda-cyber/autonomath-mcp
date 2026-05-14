# R01 — 顧問先別 補助金 weekly alert

税理士事務所が顧問先 N 社分の補助金保存検索を 1 cron で配信する。

- **Audience (cohort)**: C2 ZEI (税理士) primary / C5 HOJ (補助金 consultant) secondary
- **Use case**: 顧問先 50 社 × 週 1 回の補助金 watch を 1 jpcite アカウントで fan-out
- **Disclaimer**: §52 (税理士法) — 候補リストであり申告判定ではない
- **Cost**: ¥3/顧問先/週 (税込 ¥3.30)

## TL;DR

`saved_searches.profile_ids` カラム (mig 097) と `X-Client-Tag` header (mig 085 `usage_events.client_tag`) を組み合わせ、顧問先ごとの保存検索を 1 親 API key で fan-out。`run_saved_searches.py` cron が weekly に push。

## Sample (bash)

```bash
# 顧問先 client_42 用 saved_search を作成
curl -s -X POST https://api.jpcite.com/v1/me/saved-searches \
  -H "X-API-Key: $JPCITE_API_KEY" \
  -H "X-Client-Tag: client_42" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "設備投資 製造業",
    "prefecture": "埼玉県",
    "tier": ["S", "A"],
    "frequency": "weekly",
    "channel_format": "email",
    "channel_address": "tax-team+client42@example.com"
  }'
```

顧問先 50 社分は同じ呼び出しを `X-Client-Tag` を変えて 50 回繰り返す (初回登録のみ)。

## Expected output (excerpt)

```json
{
  "saved_search_id": "ss_3F8a...",
  "next_run_at": "2026-05-11T00:00:00+09:00",
  "frequency": "weekly",
  "client_tag": "client_42"
}
```

毎週月曜 09:00 JST に対象 hits を email で配信 (cron は `run_saved_searches.py`)。

## 代替手段 vs jpcite cost

| 手段 | 顧問先 50 社 / 月 4 週 | 備考 |
|---|---|---|
| スタッフが各補助金ポータルを巡回 | 30 min × 200 件 = 100h × ¥5,000/h = **¥500,000** | 漏れ + アグリゲータ一次資料担保が弱いリスク |
| 補助金 SaaS (例: J-Net21 RSS) | 0 円 (RSS) | 顧問先別フィルタなし、手動再振り分け必要 |
| jpcite saved_searches | 200 × ¥3 = **¥600** (税込 ¥660) | 顧問先別、weekly 自動配信、出典 URL 付き |

**約 800 倍の運用コスト削減**。alert に `unified_id` + `source_url` + `source_fetched_at` が含まれるため、税理士が顧問先に転送する際の証跡が同じ JSON に揃う。

## §52 disclaimer

```
本配信は公開資料に基づく制度候補リストです。具体的な申告
判定・申請可否の最終判断は、顧問税理士が一次資料を確認の上
行ってください。
```

email 本文 footer に `_disclaimer` envelope (jpcite が自動付与) をそのまま転記する。

## 関連

- [R02 税法改正 cliff-date weekly digest](r02-tax-cliff-digest.md)
- [API reference: /v1/me/saved-searches](../api-reference.md)
