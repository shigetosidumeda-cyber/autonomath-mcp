# R19 (P0) — CSV intake preview の使い方

> AI agent 向け recipe。顧客の会計 CSV (freee / MoneyForward / yayoi / TKC) を **PII 漏洩ゼロ** で agent に渡すための preview surface。raw cell value は一切返さず、profile 自動検出 + 集計指標 + `PrivateFactCapsule` で fingerprint hash のみを返す。**billable: false** (preview only)、後段の `csv_overlay_public_check` / `cashbook_csv_subsidy_fit_screen` outcome で初めて課金境界に入る。

- **Audience**: AI agent builder + tax_advisor / accounting_firm cohort
- **Cost**: ¥0 (preview)
- **Sensitive**: §52 / 個人情報保護法 (raw 行を網羅的に返さない契約)

## TL;DR

```
POST /v1/jpcite/csv_intake_preview
  body: {"csv_text": "<UTF-8 CSV body>", "filename": "freee_2025_q4.csv"}
  →    {"profile": "freee", "row_count": 1234, "period": {...},
         "private_fact_capsules": [...],
         "blocked_public_outputs": [...],
         "billable": false}
```

agent は preview の結果を見て、`csv_overlay_public_check` (¥900) などの artifact outcome に進むか決める。preview だけで終わるなら課金は発生しない。

## profile 自動検出

`detect_accounting_csv_profile()` は header 列の語彙パターンで 4 つの profile を識別する。

| profile | 主検出キー (header 例) | 主用途 |
|---|---|---|
| `freee` | `日付` / `勘定科目` / `取引先` / `税区分` / `品目` | freee 取引一覧 export |
| `money_forward` | `登録日` / `内容` / `金額(円)` / `保有金融機関` | MF 仕訳帳 / 家計簿 |
| `yayoi` | `伝票日付` / `借方科目` / `貸方科目` / `部門` | 弥生会計 仕訳日記帳 |
| `tkc` | `会計年度` / `会計期間` / `元帳科目` / `部門コード` | TKC FX シリーズ |

profile が確定できない場合は `unknown` を返し、`blocked_public_outputs: ["all"]` で agent 側のフォローを促す。

## raw cell value 返さない契約 (no PII leak)

下記 column 名群を含む CSV は **payroll/bank header** として警告し、`PrivateFactCapsule` 経由でも該当列は fingerprint 化しない:

```
bank / accountnumber / address / email / phone / employee / payroll / salary
iban / swift / 銀行 / 口座 / 住所 / メール / 電話 / 従業員 / 給与 / 給料
賞与 / 個人番号 / マイナンバー
```

formula injection 防止のため `=` / `+` / `-` / `@` で始まる cell value は **literal string として hash 化** し、Excel / Sheets で評価されないようにする。

## PrivateFactCapsule schema

```json
{
  "capsule_id": "freee_2025_q4__cap_001",
  "column_fingerprint_hash": "sha256:7f3e9...",
  "period_start": "2025-10-01",
  "period_end": "2025-12-31",
  "records": [
    {
      "record_id": "rec_0001",
      "derived_fact_type": "monthly_aggregate_amount",
      "value_fingerprint_hash": "sha256:abc...",
      "confidence_bucket": "high",
      "public_claim_support": false,
      "raw_value_retained": false,
      "source_receipt_compatible": false
    }
  ]
}
```

**契約**:
- `public_claim_support: false` (常に false 固定) — このカプセルから公開 claim は作れない
- `raw_value_retained: false` (常に false 固定) — raw cell は保持しない
- `source_receipt_compatible: false` (常に false 固定) — public source receipt graph に混入させない

## Sample (curl)

```bash
curl -s https://api.jpcite.com/v1/jpcite/csv_intake_preview \
  -H 'content-type: application/json' \
  -d @- <<'JSON'
{
  "csv_text": "日付,勘定科目,取引先,金額\n2025-10-01,売上,A商事,500000\n2025-10-02,仕入,B工業,300000\n",
  "filename": "freee_oct.csv"
}
JSON

# 期待 response (主要 field 抜粋)
# {
#   "schema_version": "jpcite.accounting_csv_intake_preview.p0.v1",
#   "profile": "freee",
#   "row_count": 2,
#   "billable": false,
#   "private_fact_capsules": [{"capsule_id":"...","records":[...]}],
#   "blocked_public_outputs": [],
#   "downstream_outcomes": ["csv_overlay_public_check","cashbook_csv_subsidy_fit_screen"]
# }
```

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md)
- [R18 — 14 Outcome Contract (CSV outcome 2 件)](r18_14_outcome_contracts.md)
- [R20 — 17 PolicyState の解釈](r20_policy_state.md)
- contract: `schemas/jpcir/private_fact_capsule.schema.json` / `schemas/jpcir/csv_private_overlay_contract.schema.json`
- implementation: `src/jpintel_mcp/services/csv_intake_preview.py`
