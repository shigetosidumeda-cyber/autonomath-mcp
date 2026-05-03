# R11 — 行政処分 watch (clawback / 業種別 weekly)

業種 (JSIC) × `event_type=clawback` で同業の補助金返還命令 / 行政処分を抽出し、weekly cron でリスクパターンを把握する。

- **Audience (cohort)**: C1 MA (M&A pre-DD) primary / C8 IND (Industry packs) secondary
- **Use case**: M&A pre-DD の業界別リスク把握、業界 watch list 上の "同業 redflag" 自動配信
- **Disclaimer**: なし (公表処分の引用)。M&A 文脈で参照する場合は §72
- **Cost**: ¥3/req (税込 ¥3.30) per scan / weekly run

## TL;DR

`/v1/enforcement-cases/search?event_type=clawback&q=<industry>` で業種関連の返還命令を抽出。週次 cron で `event_date_after` を 7 日前に固定すれば差分配信になる。

## Sample (bash, 一回スキャン)

```bash
# 製造業に関連する clawback 50 件
curl -s "https://api.jpcite.com/v1/enforcement-cases/search?event_type=clawback&q=製造&limit=50" \
  -H "X-API-Key: $JPCITE_API_KEY" \
  | jq '.results[] | {case_id, program_name, ministry, amount_yen, event_date, source_url}'
```

## Sample (bash crontab, weekly digest)

```bash
# /etc/cron.weekly/jpcite_enforcement.sh
SINCE=$(date -v-7d +%Y-%m-%d)   # macOS; Linux は `date -d '-7 days' +%Y-%m-%d`
curl -s "https://api.jpcite.com/v1/enforcement-cases/search?event_type=clawback&event_date_after=$SINCE&limit=50" \
  -H "X-API-Key: $JPCITE_API_KEY" \
  | jq '.results[] | "- \(.event_date) \(.ministry) / \(.program_name) / \(.amount_yen // "額不明")"' \
  | mail -s "jpcite weekly enforcement digest" me@example.com
```

## Expected output (excerpt)

```
- 2026-04-25 経産省 / ものづくり補助金 / 4,500,000
- 2026-04-22 中企庁 / 持続化補助金 / 800,000
- 2026-04-19 環境省 / 脱炭素設備補助 / 額不明
```

## 代替手段 vs jpcite cost

| 手段 | コスト (1 週) | 備考 |
|---|---|---|
| 各官庁プレス subscribe + 手動 grep | 4h × ¥5,000/h = **¥20,000** | 漏れ大、event_type 分類なし |
| 民間 リスク DB | ¥10,000-100,000/月 | 補助金 clawback 領域は粒度荒い |
| jpcite enforcement-cases/search | **¥3/週** (税込 ¥3.30) | event_type 厳密、industry × clawback、出典 URL 一次のみ |

**約 6,000 倍のコスト削減**。M&A target が同業 clawback パターンを踏んでいないかの 1 次スクリーニングが、週 ¥3 で常時稼働する。

## Caveat (data shape)

- `amount_yen` は **約 30%** しか populated されていない (公表時に金額非開示の処分が多い)。「額」より「件数 / 比率」で評価。
- `event_type` の値は `clawback` (返還命令) / `subsidy_exclude` (指名停止) / `fine` (罰金) など複数。M&A pre-DD では `clawback` + `subsidy_exclude` の合算を見るのが定石。
- `recipient_houjin_bangou` を介して [R09 法人 360 view](r09-corp-360-view.md) と join すると、target 法人が直接 hit したかを 1 ステップで照合できる。

## §72 disclaimer (M&A 文脈)

M&A pre-DD で同業 redflag を参照する際は以下のような免責付与を推奨。

```
本一覧は各官庁公表の処分情報を構造化した参考情報であり、
対象法人の事業実態の確証ではありません。DD には別途登記 /
決算書 / 税務申告 / ヒアリングが必要です。
```

## 関連

- [R09 法人 360 view](r09-corp-360-view.md)
- [R10 類似採択事例 検索](r10-case-studies-search.md)
- [API reference: /v1/enforcement-cases/search](../api-reference.md)
