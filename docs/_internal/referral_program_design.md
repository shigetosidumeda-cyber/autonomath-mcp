# 紹介プログラム設計 (Referral Program Design)

> **要約 (summary):** V3 "Credit-only" を launch 方式として採用。景表法/源泉徴収/資金決済法いずれのリスクも最小。V1/V2 は再評価枠として保留。W5 launch 後 W6 から 20 顧客に開放、W8 時点で viral coefficient k > 0.3 に届かなければ sunset。
>
> **Status:** 設計段階 (2026-04-23)。実装・DB migration は未着手。本書は `docs/POST_DEPLOY_PLAN_W5_W8.md` の補完である。

---

## 1. 3 方式の比較と選定

### V1 — "Give-Get" (招待者に 1 ヶ月無料、被招待者に 3 ヶ月 30% OFF)

- 仕組み: 被招待者が有料転換したとき、招待者の次回請求に 1 ヶ月分の Stripe credit (`Customer.balance` 負残高) を付与。被招待者は Stripe Coupon で初回 3 請求に 30% OFF。
- 利点: SaaS 定番、導線が単純、実装はほぼ Stripe Coupon + Customer.balance で済む。
- 欠点 (本プロダクト固有): **景表法 4 条で 1 ヶ月無料は取引価額の 100% = 違反リスク**。下記 §2 参照。pure metered では「1 ヶ月無料」の基準額が顧客ごとに異なり実装も難しい。

### V2 — "Affiliate with payout" (招待者に 15% MRR 手数料 / 12 ヶ月)

- 仕組み: ImpactRadius 等のアフィリエイトネットワーク経由で、referrer に 12 ヶ月分の 15% 現金支払い。
- 利点: 高レバレッジ、influencer 層に刺さる。
- 欠点: **個人宛 ¥1,000 以上の支払いは 10.21% 源泉徴収義務 (所得税法 204 条)**、1099 相当の書類発行、特商法でアフィリエイト表示必須、ImpactRadius の最低月額 ($500+) が launch 初期の ARR に対して重い。**B2B dev 読者層は 12 ヶ月 kickback を開示した瞬間「ステマ警戒」に傾く**ため、tone として `project_jpintel_trademark_intel_risk` と同じレベルでブランドリスク。

### V3 — "Credit-only, no cash" (被招待者に ¥2,000 API credit、招待者に有料転換時 ¥2,000 credit)

- 仕組み: 被招待者は metered 使用量 (¥3/req) に充当できる ¥2,000 API credit を signup 時に獲得 (約 666 req 相当)。被招待者が Paid 転換 (カード登録 → 最初の invoice paid) した瞬間、招待者の Stripe `Customer.balance` に ¥2,000 credit を付与 (今後の請求に自動充当)。cash 払い戻し不可、譲渡不可、12 ヶ月で失効。
- 利点: (a) 源泉徴収非該当 (現金給付でない)、(b) 資金決済法 3 条の前払式支払手段に該当させないため譲渡・払戻不可と明記、(c) ¥2,000 は 4,000 req 分 = pure metered のため「値引き」構成に自然に載る。月次使用量がそれ以下なら実質無料、それ以上なら差分のみ課金。弁護士確認前提だが、現金給付・景品給付と異なり metered 課金への credit 充当は Stripe 標準機能であり法的に清浄。
- 欠点: インセンティブが薄く k (viral coefficient) が稼ぎにくい可能性。下記 §7 で測定して評価する。

### 採用: **V3**

**理由 (2-3 文):** B2B dev 層は現金キックバック ("アフィリエイト") に倫理的抵抗があり、V2 は購読者信頼を毀損する。V1 は 1 ヶ月無料 = 100% discount が景表法の「取引価額 20% 以下」ラインを明確に超え、弁護士確認までの blocker が厚い。V3 は金額を ¥2,000 の credit (値引き構成) に固定し、pure metered モデルでは `Customer.balance` で自然に適用される。源泉徴収と資金決済法のリスクを構造的にゼロ化する — `feedback_autonomath_fraud_risk` 系の「法務が弱いまま営業する」アンチパターンを避けられる。

---

## 2. 日本法務チェック

### 2.1 景品表示法 (景表法) 4 条 / 景品類制限告示

- 原則: 取引価額 ¥1,000 超は景品 20% 以下、¥1,000 以下は景品 ¥200 まで (一般懸賞)。総付景品は 20% / ¥200 ルール。
- 本設計での整理: 被招待者向け ¥2,000 credit は「月額使用料の値引き (取引条件の一部)」と解釈し、景品類に該当させない。根拠: **消費者庁 Q&A で「値引き」「付随サービス」は景品類から除外**されている (景品類等の指定の告示の運用基準 4 項)。
- 招待者向け ¥2,000 credit も同様に「将来の自社サービスの値引き」として扱う (現金化不可、他社サービスと交換不可を契約で明記)。
- **残リスク: 弁護士確認必須**。pure metered (¥3/req) に対する ¥2,000 credit は使用量に応じて消化される「値引き」として構成する。景品類認定を避けるため、契約規約側でも「使用料金の値引き」と明記する。→ §4 の DB schema で `reward_type = 'service_credit'` と明記。
- **要 弁護士 確認項目 (launch blocker):**
  1. ¥2,000 credit が「値引き」として整理可能か
  2. 招待者向け credit の「自社サービス限定」整理が値引き構成に合致するか
  3. LP で `紹介特典` と表示する場合の景表法上の表記義務

### 2.2 源泉徴収 (所得税法 204 条)

- 個人への報酬 ¥1,000 超 → 10.21% 源泉徴収義務、支払調書発行義務。
- V3 は現金報酬を一切出さないため **源泉徴収非該当**。Stripe `Customer.balance` への credit 付与は自社サービスの割引であり、所得税法 204 条の「報酬・料金の支払」に該当しない。
- V2 を将来検討する場合は、(a) 法人アフィリエイトのみ受付、(b) 個人は ¥1,000/年キャップ、のいずれかを選択しないと源泉徴収事務が発生する。

### 2.3 特定商取引法

- V3 は「アフィリエイト」という語を使わない (credit 型であって報酬型ではない)。LP での表示名は `紹介プログラム` / `紹介特典` に統一。
- 特商法表示は既存の `/legal/tokushoho` に「紹介特典: ¥2,000 credit、12 ヶ月有効、譲渡不可、払戻不可」の 3 行を追記。アフィリエイト表示義務は発生しない。

### 2.4 資金決済法 3 条 (前払式支払手段)

- 原則: 自家型前払式支払手段で未使用残高が基準日 (3/31, 9/30) に 1,000 万円超 → 届出義務。
- 本設計では credit に **(i) 現金払戻不可、(ii) 譲渡不可、(iii) 12 ヶ月で失効**を規約で明記。これにより「前払式」ではなく「販売促進目的の割引」として整理 (資金決済法 3 条 4 項のおまけ的性格の除外例に寄せる)。
- 2026 年内に未使用 credit 総額が 1,000 万円に到達する見込みはないが、launch 後 12 ヶ月ごとに監査。

### 2.5 Anti-gaming 要件 (launch blocker、実装必須)

1. **自己紹介禁止**: `referral_events.referred_customer_id == referral_codes.owner_customer_id` を DB CHECK で弾く。Stripe `customer_id` が一致する場合は invoice.paid webhook で reward 発行しない。
2. **new customer only**: 被招待者の `customer_id` が過去に 1 度でも active subscription を持っていたら無効 (`api_keys` を JOIN して判定)。
3. **家族割 abuse 対策**: 同一 `customer_id` 系列 (Stripe Customer の email hash が一致、または Stripe Test Clock 経由作成) を excluded list として DB に保持。
4. **組織関連検出 (nice-to-have、D-Day 非 blocker)**: 同一ドメインメール (@example.co.jp) の過剰自己紹介を検出するロジックは W7 以降。

---

## 3. データモデル追加 (DRAFT)

`scripts/migrations/008_referrals.sql.draft` として以下を下書き。**実行可能 migration は別 PR で確定**。

```sql
-- 008_referrals.sql.draft  (DRAFT — do not apply yet)
-- Referral codes + events. V3 credit-only scheme.
-- Idempotent via IF NOT EXISTS. Tracked in schema_migrations after apply.

CREATE TABLE IF NOT EXISTS referral_codes (
    code TEXT PRIMARY KEY,                       -- 8-12 char, URL-safe, unambiguous charset (exclude 0/O/1/l)
    owner_customer_id TEXT NOT NULL,             -- Stripe customer_id of referrer (paid tier only)
    created_at TEXT NOT NULL,
    revoked_at TEXT,                             -- set on fraud / opt-out
    max_uses INTEGER,                            -- NULL = unlimited; default 50 at app layer
    uses_count INTEGER NOT NULL DEFAULT 0,
    reward_type TEXT NOT NULL DEFAULT 'service_credit',  -- 'service_credit' only for V3
    reward_value_yen INTEGER NOT NULL DEFAULT 2000,
    FOREIGN KEY(owner_customer_id) REFERENCES api_keys(customer_id)
);

CREATE INDEX IF NOT EXISTS idx_referral_codes_owner ON referral_codes(owner_customer_id);

CREATE TABLE IF NOT EXISTS referral_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    referred_customer_id TEXT NOT NULL,          -- Stripe customer_id of invitee
    referred_subscription_id TEXT,               -- Stripe subscription_id after paid conversion
    signed_up_at TEXT NOT NULL,                  -- when /apply recorded the intent
    paid_at TEXT,                                -- when invoice.paid webhook fired
    reward_granted_at TEXT,                      -- when Customer.balance credit applied
    reward_amount_yen INTEGER,                   -- snapshot at time of grant
    void_reason TEXT,                            -- set if refund / chargeback voids reward
    FOREIGN KEY(code) REFERENCES referral_codes(code),
    CHECK (referred_customer_id <> (SELECT owner_customer_id FROM referral_codes WHERE referral_codes.code = referral_events.code))
);

CREATE INDEX IF NOT EXISTS idx_referral_events_code ON referral_events(code);
CREATE INDEX IF NOT EXISTS idx_referral_events_referred ON referral_events(referred_customer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_referral_events_referred_unique ON referral_events(referred_customer_id);
  -- A customer can only be referred once ever.
```

---

## 4. API エンドポイント (skeleton)

すべて `X-API-Key` 必須。rate limit は既存 authed endpoint と同じ (tier 依存、現 `api/deps.py`)。**Free tier は referral code 発行不可** (spam 防止、§6 Rollout)。

### GET `/v1/referrals/my-code`
- 初回 call で自動生成 (paid tier のみ)。
- Response: `{"code": "abc12def", "share_url": "<site>/invite/abc12def", "max_uses": 50, "uses_count": 3}`
- 409 if Free tier.

### GET `/v1/referrals/stats`
- Response: `{"total_applies": 12, "converted": 4, "rewards_earned_yen": 8000, "pending_rewards_yen": 2000}`

### POST `/v1/referrals/apply`
- Body: `{"code": "abc12def"}`
- **Called during checkout**, before `POST /v1/billing/checkout`. Records intent in `referral_events` with `signed_up_at` set. Actual reward issuance happens in the `invoice.paid` webhook handler (§5).
- 422 if code revoked / max_uses 到達 / self-referral.

### Rate limits
- 既存 authed endpoint と同一 (Free: 100/day, Paid: metered hard cap なし)。/my-code と /stats はほとんどキャッシュ可。

---

## 5. Stripe 統合

### 被招待者側 (Checkout での値引き適用)
- 初回生成時に自動で Stripe Coupon を 1 つだけ作成 (`duration=once`, `amount_off=2000`, `currency=jpy`, `name=Referral Credit ¥2,000`)。全被招待者で同じ coupon を使い回す (coupon 単位ではなく referral_events で追跡)。
- Checkout Session 作成時に `discounts=[{coupon: JPINTEL_REFERRAL_V3}]` を付与。ただし `allow_promotion_codes=True` と併用不可の可能性があるため `allow_promotion_codes=False` に切り替え、promotion code path は `/v1/referrals/apply` 経由に一本化する。

### 招待者側 (credit 付与)
- `invoice.paid` webhook で被招待者の first paid invoice を検出 → `referral_events.paid_at` 更新。
- 招待者の Stripe `Customer.balance` を `-2000` (負 = credit) だけ減らす (Stripe の仕様: 負の balance は次回請求に自動充当)。
- 同 webhook handler 内でトランザクションにし、**Stripe 失敗時はイベントを pending 状態で残して retry queue に入れる** (webhook は Stripe 側が最大 72h retry するので、handler 側は 5xx を返せば自動再試行)。

### Refund 時の取り消し
- `charge.refunded` / `invoice.voided` webhook で該当 `referred_subscription_id` を検索 → `referral_events.void_reason = 'refund'` を立て、招待者の `Customer.balance` を `+2000` で巻き戻す。wash-referral (意図的 refund 経由でのポイント稼ぎ) 対策。

---

## 6. UI / dashboard 変更

### `site/dashboard.html` に "招待" タブ追加
- 表示項目: 自分のコード、発行済みシェア URL (コピーボタン)、累積 apply 数、converted 数、獲得 credit (yen)。
- Free tier 閲覧時は「Paid (¥3/req) で有効化」バナーのみ。

### `site/success.html` (checkout 成功後)
- 「招待コードを取得」 CTA。クリックで `/v1/referrals/my-code` を叩き、share URL を pre-fill してコピー。
- tone: 「同僚に MCP 連携を共有してみませんか」程度のライトな導線。`参加者拡散ゲーム` 的な gamification (leaderboard, 連鎖ボーナス等) は **作らない**。

### Opt-in
- dashboard 上で `紹介プログラムに参加する` checkbox (APPI 明示同意)。未チェックでは `/my-code` を呼んでも 403。初回 checkout ではデフォルトオフ。

---

## 7. 計測指標

| 指標 | 定義 | 計測場所 |
|------|------|---------|
| Referral link clicks | `share_url` の `?ref=CODE` 付き着信数 | GA / `site/analytics.js` |
| Code applies | `referral_events` 行数 | DB |
| Converted % | `referral_events.paid_at IS NOT NULL` 比率 | DB |
| Viral coefficient k | `avg referrals per paid customer × avg conversion %` | DB + Stripe customer count |
| Pending reward yen | `paid_at IS NOT NULL AND reward_granted_at IS NULL` の合計 | DB |

### Go/No-Go 基準
- **k > 0.3 by W8** → 継続、チューニング (credit 額、LP 訴求)
- **k < 0.1 by W6** → sunset (flag off、スキーマは残し tombstone 扱い)
- 中間 (0.1 ≤ k ≤ 0.3) → W8 まで追加観察、W9 に final 判定

---

## 8. Anti-patterns (no-go 明示)

1. **pro-rata rebate の自動付与禁止**: 既存有料顧客を勝手に紹介プログラムに登録して rebate を付けない (surprise billing は信頼を壊す)。
2. **feature unlock と紹介の紐付け禁止**: 「友達を紹介すると Paid の特定機能が解放される」は景表法ゼロ円景品の「取引に付随しない」要件を脱落させ、違反確定。
3. **家族割 abuse 禁止**: 同一 Stripe Customer email hash が referrer と referred の両方に現れた場合は reward 無効。
4. **opt-in なしで紹介メール送信禁止**: APPI 上、紹介プログラム案内メールは個別 opt-in を取得したユーザーにのみ送る (既存 `subscribers` テーブルの purpose とは別)。
5. **leaderboard / ランキング機能を作らない**: B2B dev 層は拡散ゲーム化を嫌う。tone として `紹介制` に留める。

---

## 9. ロールアウト

| 週 | 行動 |
|----|------|
| W5 (launch 週) | flag off。内部 5 codes を pre-seed して自己テスト。webhook 手動で invoice.paid を叩いて credit 付与経路を検証。 |
| W6 | flag on for 最初の 20 paid 顧客 (customer_id allow list)。UI は dashboard のみ、success.html CTA はまだ出さない。 |
| W7 | 全 paid 顧客に開放。success.html CTA 有効化。LP には出さない (ambassador 的に閉じる)。 |
| W8 | k 測定、§7 の Go/No-Go。 |
| Never | **Free tier は referral code 発行不可** (spam 抑制、`max_uses` 50 cap、code revoke API の用意)。 |

---

## 10. 顧客保護

- **解約が常に容易**: 紹介プログラムに参加しても Stripe Customer Portal からの解約手順は変わらない。lock-in は作らない。
- **credit 失効: 12 ヶ月**。LP と dashboard の両方で明示。`referral_events.reward_granted_at + 12 months` で自動失効 (cron)。
- **refund voids pending reward**: §5 参照、wash-referral 対策。
- **opt-out**: dashboard の同 checkbox を外すと既発行 code は revoke、pending event は `void_reason='opt_out'`。

---

## 報告 (レポート)

- **Chosen variant**: **V3 "Credit-only"**。理由は景表法/源泉徴収/資金決済法の 3 本すべてで blocker を最小化できる唯一の方式だから。
- **Biggest legal risk**: **¥2,000 credit が景表法上の「景品」でなく「値引き」として整理できるか**。pure metered (¥3/req) では ¥2,000 ≒ 666 req 分の「使用料金前倒し値引き」として自然に整理できる。**緩和策**: (a) 規約で `紹介特典` を一貫して「使用料金の値引き」と定義、(b) cash 化・譲渡・他社サービス交換を全て禁止、(c) launch 前に弁護士 1 回レビューで "値引き" 整理を書面で確定させる (launch blocker)。
- **実装で事故る 3 箇所**:
  1. **Webhook 冪等性**: `invoice.paid` の Stripe retry で同一 `referral_event` に対し二重 credit を付ける事故。`reward_granted_at IS NULL` で guard + `referred_subscription_id` UNIQUE を厳守。
  2. **Self-referral の抜け道**: Stripe Customer を 2 つ作って同一カードで決済する手口。email hash + payment method fingerprint の両方で判定しないと一方だけでは弾けない。
  3. **credit 失効 cron の抜け**: 12 ヶ月失効を LP で宣言しておきながら cron が停止していると「規約と実装の齟齬」= 景表法の不当表示 (有利誤認) に転化する。launch 前に失効 cron の死活監視を incident_runbook に記載。
