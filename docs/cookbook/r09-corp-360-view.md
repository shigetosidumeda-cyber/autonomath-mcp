# R09 — 法人 360 view (1-call evidence packet)

法人番号 1 件で「採択履歴 + 行政処分 + 適格事業者 + 関連法令」を 1 リクエストで取得し、M&A pre-DD / 税理士 onboarding の出発点にする。

- **Audience (cohort)**: C1 MA (M&A pre-DD) primary / C2 ZEI (税理士) secondary
- **Use case**: M&A target または税理士 顧問先 onboarding の初日チェック
- **Disclaimer**: §72 (弁護士法 — DD checklist であり法律判断ではない) + §52 (税理士法)
- **Cost**: ¥3/legal entity (税込 ¥3.30) for evidence packet

## TL;DR

`/v1/evidence/packets/query` に法人番号を渡すと、`v_houjin_360` view (autonomath.db) が 採択 / enforcement / invoice / 関連法令 / source_url[] を 1 envelope に詰めて返す。`known_gaps` フィールドが正直に欠損領域を述べる。

## Sample (bash)

```bash
HB="8010001213708"

curl -s -X POST "https://api.jpcite.com/v1/evidence/packets/query" \
  -H "X-API-Key: $JPCITE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"subject_kind\":\"corp\",\"subject_id\":\"$HB\",\"include_facts\":true}" \
  | jq '.packet | {
      legal_id, name,
      adoption_count: (.adoptions | length),
      enforcement_count: (.enforcements | length),
      invoice_status: .invoice_registrant.registered,
      source_urls: (.sources | map(.url)),
      known_gaps,
      _disclaimer
    }'
```

個別 endpoint で同じ取得をする場合は 3-4 call に分かれる:

```bash
curl -s "https://api.jpcite.com/v1/case-studies/search?recipient_houjin_bangou=$HB" -H "X-API-Key: $JPCITE_API_KEY"
curl -s "https://api.jpcite.com/v1/enforcement-cases/search?recipient_houjin_bangou=$HB" -H "X-API-Key: $JPCITE_API_KEY"
curl -s "https://api.jpcite.com/v1/invoice_registrants/search?houjin_bangou=$HB" -H "X-API-Key: $JPCITE_API_KEY"
```

## Expected output (excerpt)

```json
{
  "legal_id": "8010001213708",
  "name": "Bookyou株式会社",
  "adoption_count": 0,
  "enforcement_count": 0,
  "invoice_status": true,
  "source_urls": [
    "https://www.houjin-bangou.nta.go.jp/...",
    "https://www.invoice-kohyo.nta.go.jp/..."
  ],
  "known_gaps": [
    "採択事例 DB は 2,286 件のみ (中企庁公表分)",
    "未公表処分は corpus に含まない"
  ],
  "_disclaimer": {
    "sec72": "本出力は DD checklist であり、法律判断ではありません。",
    "sec52": "税務判定は税理士にご相談ください。"
  }
}
```

## 代替手段 vs jpcite cost

| 手段 | target 1 社あたり | 備考 |
|---|---|---|
| M&A 仲介 staff の手動 DD (法人番号公表サイト + 採択事例 + 行政処分プレス + 適格事業者公表サイト) | 4-8h × ¥10,000/h = **¥40,000-80,000** | 漏れ + 出典版数管理が手作業 |
| 民間 DB (帝国データ等) | ¥5,000-30,000/件 | 公開制度との突き合わせ別途 |
| jpcite evidence packet | **¥3** (税込 ¥3.30) | 1 envelope, source_urls + known_gaps 付き |

**1,000-25,000 倍の取得コスト削減**。1 envelope に `corpus_snapshot_id` が入るため、1 ヶ月後に同じ snapshot を再取得して差分監査できる。

## §72 / §52 disclaimer

レスポンスの `_disclaimer` envelope をそのまま deal memo / 顧問契約 onboarding メモに転記する。jpcite は `_disclaimer` を自動付与し、税理士法 §52 と弁護士法 §72 の両方をカバーする。

## 関連

- [R03 月次申告 適格事業者 bulk verify](r03-monthly-invoice-verify.md)
- [R10 類似採択事例 検索](r10-case-studies-search.md)
- [R11 行政処分 watch](r11-enforcement-watch.md)
- [API reference: /v1/evidence/packets/query](../api-reference.md)
