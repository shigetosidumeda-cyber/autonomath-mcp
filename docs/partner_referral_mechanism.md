# Partner Referral Mechanism

> **要約 (summary):** jpcite の partnership は **referral_code 1 個** で trace。発生する metered 売上の **10%** を月末締め翌月末日に Stripe Connect Transfer で payout。discount は永久 NG (¥3/billable unit 固定)。referral 0 でも ¥0 払出。

## なぜ 1 つのメカニズムにまとめるか

5 つの partnership (freee / Money Forward / kintone / SmartHR / Anthropic) は配布形式は違うが、**売上計上と payout のロジックは同一**。

- 個別契約書 / 個別 payout schedule は **作らない** (memory `feedback_zero_touch_solo`)
- 全 partner に同じ referral mechanism が適用される
- **Anthropic だけ例外**: registry は referral partner でないため 0% (= 払出なし)

## referral_code の付与方法

| 経路 | 付与方法 |
|------|--------|
| **freee Marketplace** | freee OAuth callback で `referral_code=freee-{client_app_id}` を jpcite API key の `referral_code` カラムに保存 |
| **Money Forward** | MF API integration 時に `referral_code=mf-{tenant_id}` を保存 |
| **kintone Marketplace plugin** | plugin の query parameter `referral_code=kintone-{kintone_app_id}` を `/v1/programs/search` 等に毎 request 付与 |
| **SmartHR widget** | iframe URL に `?referral_code=smarthr-{tenant_id}` を埋込、内部で X-API-Key と紐付 |
| **Anthropic Directory** | registry ingestion はユーザー個別追跡 不可 → referral_code は **空** (= internal 計上) |

referral_code は API key 単位で **immutable**。後から変更できない (詐欺防止)。

## DB schema (planned)

```sql
-- src/jpintel_mcp/db/migrations/021_referral.sql (post-launch 追加予定)
ALTER TABLE api_keys ADD COLUMN referral_code TEXT NULL;
CREATE INDEX idx_api_keys_referral ON api_keys(referral_code) WHERE referral_code IS NOT NULL;

CREATE TABLE referral_partners (
  partner_code   TEXT PRIMARY KEY,            -- 'freee', 'mf', 'kintone', 'smarthr', 'anthropic'
  display_name   TEXT NOT NULL,
  share_percent  INTEGER NOT NULL,            -- 0-30, 通常は 10
  payout_method  TEXT CHECK (payout_method IN ('stripe_connect', 'bank_transfer')),
  stripe_account TEXT NULL,                   -- Stripe Connect ID, 振込のときは NULL
  bank_jp        TEXT NULL,                   -- 銀行名 / 支店 / 口座番号 (encrypted at rest)
  active         INTEGER NOT NULL DEFAULT 1,
  created_at     INTEGER NOT NULL,
  notes          TEXT NULL
);

CREATE TABLE referral_payouts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  partner_code   TEXT NOT NULL REFERENCES referral_partners(partner_code),
  period_start   TEXT NOT NULL,               -- ISO date (YYYY-MM-01)
  period_end     TEXT NOT NULL,
  request_count  INTEGER NOT NULL,
  charged_jpy    INTEGER NOT NULL,            -- ¥3 × request_count
  share_jpy      INTEGER NOT NULL,            -- charged_jpy × share_percent / 100
  payout_status  TEXT CHECK (payout_status IN ('pending','transferred','failed')),
  stripe_transfer_id TEXT NULL,
  paid_at        INTEGER NULL
);
```

## 計算式

`request_count` は **billable な request のみ** (=`X-API-Key` 経由 / `429` / `4xx` を除く successful 課金 request)。匿名 3 req/日 free は計上対象外。

```
charged_jpy   = request_count × ¥3
share_jpy     = floor(charged_jpy × share_percent / 100)
                # 端数は jpcite に残す (Bookyou 株式会社 計上)
```

例: freee 経由 user が月 20,000 req → `charged_jpy = ¥60,000` → `share_jpy = ¥6,000` を freee に払出。

## payout cycle

| step | timing | action |
|------|--------|--------|
| **calc** | 月末日 23:59 JST | `referral_payouts` row を作成 (`payout_status = 'pending'`) |
| **invoice** | 翌月 1 日 09:00 | partner 宛に **jpcite が** 適格請求書 (T8010001213708) を発行 (※受領側請求書ではなく、振込通知書として送付) |
| **transfer** | 翌月末日 17:00 | Stripe Connect Transfer or 銀行振込実行、`payout_status = 'transferred'` 更新 |
| **fail handling** | failed → 14 日 retry | retry 失敗時は info@bookyou.net 宛 Sentry alert |

最低金額なし: 1 ヶ月 0 req なら ¥0 払出 (transfer event 自体スキップ)。

## utm parameter との互換

- `referral_code` は jpcite internal 名
- 外部マーケ: `utm_source` / `utm_medium` / `utm_campaign` (Google Analytics 互換) も並行受付
- 優先順位: query parameter `referral_code` > X-API-Key の保存値 > `utm_source` (推測 fallback)

## 監査と透明性

- partner ダッシュボード (post-launch): `https://jpcite.com/partners/{partner_code}/dashboard`
- 月次 CSV export: 「日付 / API key 末尾 / req 数 / 課金 ¥」のみ (個人特定不可)
- jpcite 側のログは 90 日保持 (privacy policy 6.1)
- 払出明細の disputes は info@bookyou.net で受付、14 日以内回答

## NOT DO (永久禁止)

| 項目 | 理由 |
|------|------|
| 30% 超の share | LTV 圧迫、unit economics 破綻 |
| 個別 partner ごとに異なる share% | zero-touch ops 違反 (memory `feedback_zero_touch_solo`) |
| 期間限定 boost (例: 初年度 20%) | discount 同等の不健全インセンティブ |
| referral 経由 user に discount 適用 | ¥3/billable unit 完全均一 (memory `project_autonomath_business_model`) |
| 紙の覚書 / 押印契約 | 全 partner self-serve、Stripe 標準 ToS のみ |
| call / Zoom での price 交渉 | 営業活動 NG (memory `feedback_organic_only_no_ads`) |

## 参考リンク

- [partnerships/freee.md](partnerships/freee.md)
- [partnerships/money_forward.md](partnerships/money_forward.md)
- [partnerships/kintone.md](partnerships/kintone.md)
- [partnerships/smarthr.md](partnerships/smarthr.md)
- [partnerships/anthropic_directory.md](partnerships/anthropic_directory.md)
- Stripe Connect docs: https://stripe.com/docs/connect
- 適格請求書: https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice.htm
