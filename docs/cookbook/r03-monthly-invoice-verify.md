# R03 — 月次申告チェック (適格事業者番号 bulk verify)

仕入帳簿 N 件の T 番号 (適格請求書発行事業者番号) を一括検証し、失効・未登録を仕入税額控除リスクとして flag する。

- **Audience (cohort)**: C2 ZEI (税理士) primary / C8 IND (Industry packs) secondary
- **Use case**: 月次決算前の仕入請求書 100-1,000 件の T 番号バリデーション
- **Disclaimer**: PDL v1.0 attribution required (出典: 国税庁 法人番号公表サイト)
- **Cost**: ¥3/req (税込 ¥3.30) per T-番号 lookup

## TL;DR

国税庁 適格請求書発行事業者公表サイト (https://www.invoice-kohyo.nta.go.jp/) のバルク照合を、jpcite の `/v1/invoice_registrants/search` で 1 req/件で実行。レスポンスに `corpus_snapshot_id` + `source_fetched_at` が乗るため監査証跡として保管できる。

## Sample (bash)

```bash
# 仕入帳簿の T 番号 list を bulk verify
TNUMS=(T8010001213708 T1234567890123 T9876543210987)
for tnum in "${TNUMS[@]}"; do
  curl -s "https://api.jpcite.com/v1/invoice_registrants/search?invoice_registration_number=$tnum" \
    -H "X-API-Key: $JPCITE_API_KEY" \
    | jq -r ".results[0] | [.invoice_registration_number, .registered, .registered_on, .name] | @csv"
done
```

## Expected output (excerpt)

```csv
"T8010001213708",true,"2025-05-12","Bookyou株式会社"
"T1234567890123",false,,
"T9876543210987",true,"2024-09-01","..."
```

`registered:false` または結果 0 件の行は仕入税額控除のリスク候補として人手レビューに回す。

## 代替手段 vs jpcite cost

| 手段 | コスト (1,000 件) | 備考 |
|---|---|---|
| 国税庁公表サイト 1 件ずつ手動 | 30 sec/件 × 1,000 = 8h × ¥5,000/h = **¥40,000** | 人件費換算 |
| 国税庁 web-API 直接 (無料) | 0円 + 開発 + バルク token 管理 | レスポンスに provenance metadata なし |
| jpcite `/v1/invoice_registrants/search` | 1,000 × ¥3 = **¥3,000** (税込 ¥3,300) | `_attribution` + `corpus_snapshot_id` 付き、自動 |

**約 12 倍の労務コスト削減** + 監査証跡 (snapshot id) を 1 リクエストで確保。

## Attribution (PDL v1.0)

レスポンスに付帯する `_attribution` フィールドをそのまま証憑に転記する。

```
出典: 国税庁 法人番号公表サイト (PDL v1.0) / 編集: jpcite
取得時刻: <source_fetched_at>
スナップショット: <corpus_snapshot_id>
```

## 関連

- [R09 法人 360 view](r09-corp-360-view.md) (法人番号からの一括 evidence packet)
- [API reference: invoice_registrants/search](../api-reference.md)
