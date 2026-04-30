# Email Setup — Postmark 運用手順 (launch: 2026-05-06)

`docs/retention_digest.md` §1 で確定した Postmark を実際に動かすための
設定集。コード側の配線は既に入っている (`src/jpintel_mcp/email/postmark.py`,
`src/jpintel_mcp/api/email_webhook.py`)。残タスクは **アカウント作成 +
DNS 設定 + Postmark ダッシュボード操作** の 3 点のみ。

> **P2.6.6 SPF / DKIM / DMARC 検証 anchor**: 本文 §3-1 (SPF) / §3-2 (DKIM) /
> §3-4 (DMARC) で 4 record 定義済。operator は §3 全 record を Cloudflare
> DNS に投入後、§4 mail-tester で 9.5/10 を取得することで P2.6.6 完了とする。
> 実 DNS 操作は credential 必須のため Claude は触れない (solo + zero-touch
> 原則。1 度設定すれば DKIM rotation 以外は sustain 不要)。HSTS / CSP 等の
> HTTP 層ヘッダ (P2.6.5) は API middleware 側で実装済 — 詳細は
> `docs/_internal/autonomath_com_dns_runbook.md` §9 を参照。

---

## 1. サーバー tier と運用レベル

| 項目 | launch 設定 | スケール時 |
| --- | --- | --- |
| Plan | **Free 100 emails/month** で開始 | 月 600 通超えで $15/mo 10k に upgrade |
| Server 数 | 1 (`jpintel-prod`) | staging 用 2 台目は W6 に検討 |
| Message Streams | `outbound` (transactional), `broadcast` (digest) | 同一 |
| Token | API Token × 1 (sandbox Token は使わない) | Prod/Staging で分離 |

Launch 初週の予測送信数 = Welcome 10 + Receipt 10 + 運用通知数通 = **50
通未満**。Free tier で十分余裕がある。Digest (W7〜) が毎週 500+ になる
ので、W6 のうちに $15/mo へ切替予定。

---

## 2. Sender Signature と From/Reply-To

| 用途 | アドレス | Postmark 設定 |
| --- | --- | --- |
| From (all transactional) | `no-reply@jpcite.com` | Sender Signature を DKIM 込みで verify |
| Reply-To | `hello@jpcite.com` | 受信専用 — forward to `info@bookyou.net` inbox or Postmark Inbound |
| Bounce Return-Path | `pm-bounces.jpcite.com` | 下記 DNS §3-4 参照 |
| Digest footer support | `support@jpcite.com` | 受信のみ |

`no-reply@` を From にするのは返信抑制が主目的。**Reply-To** で人間に
届かせる設計にしないと 特商法 11 条の「連絡先」要件を満たさないので、
Postmark 側で `ReplyTo` ヘッダが必須 (コード側は `postmark_from_reply`
未設定なら送らない)。

---

## 3. DNS レコード (必須 4 種)

### 3-1. SPF

```
jpcite.com    TXT   "v=spf1 include:spf.mtasv.net ~all"
```

既存の SPF がある場合は `include:` をマージ。**`~all` (softfail) で開始**、
7 日間 bounce ゼロを確認してから `-all` (hardfail) に締め上げる。

### 3-2. DKIM (Postmark が 2 本払い出す)

```
20260506pm._domainkey.jpcite.com        CNAME  20260506pm.jpcite.com.dkim.mtasv.net
20260506pm-bounces._domainkey.jpcite.com CNAME  20260506pm-bounces.jpcite.com.dkim.mtasv.net
```

セレクタ名は Postmark の Sender Signature 画面で発行される日付形式。
**rotation に備えて前回分を 30 日残してから削除** — Gmail が過去 30 日
間のキーでも検証するため。

### 3-3. Return-Path / Bounce 処理

```
pm-bounces.jpcite.com   CNAME   pm.mtasv.net
```

VERP 経由の bounce 配送先。Postmark がここへ送り返した bounce を
webhook で拾って `/v1/email/webhook` → `subscribers.unsubscribed_at`
に反映する。

### 3-4. DMARC (段階運用)

```
_dmarc.jpcite.com   TXT   "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@jpcite.com; pct=100; adkim=r; aspf=r"
```

**`p=reject` ではなく `p=quarantine` で launch** (§2 と §3-1 が全ドメイン
で効いているか 14 日観測後に reject へ)。失敗すると launch 直後の全
トランザクションメールが迷惑箱行きになるリスクがあるので保守的に倒す。
`rua=` の集計レポート受信箱は Postmark Inbound か外部 (例: dmarcian)
どちらでも可。

---

## 4. Inbox Placement テスト

| ツール | 何を見る | 合格ライン |
| --- | --- | --- |
| [mail-tester.com](https://www.mail-tester.com/) | SPF/DKIM/DMARC/SpamAssassin score | **9.5/10 以上** |
| [GlockApps](https://glockapps.com/) | Gmail/Yahoo/Outlook/iCloud の Inbox vs Promo vs Spam | Inbox ratio ≥ 85% |
| 自社 Gmail / Yahoo / au 実アカ宛 smoke | 実際の Inbox 着弾と文字化け | 全箱 primary 着弾 |

launch 前日の 5/5 までに 3 本とも pass させる。どれか落ちたら §3 の
セレクタ設定を疑って再確認 → 72 時間待ってから再テスト (DNS 伝播猶予)。

---

## 5. Suppression list の同期

Postmark 側の bounce / spam complaint は **webhook で受けて自分の DB に
反映** する (外部 suppression list を真の source-of-truth にしない。
ベンダー移行時に Postmark の unsubscribe list を引き継げなくなるため)。

### 5-1. Webhook 設定

Postmark ダッシュボード → Servers → jpintel-prod → **Webhooks** で:

```
URL:     https://api.jpcite.com/v1/email/webhook
Events:  Bounce, SpamComplaint, SubscriptionChange
HTTP Basic Auth: 未使用 (HMAC に移行)
Include message ID: ON
```

HMAC verification は `POSTMARK_WEBHOOK_SECRET` を `flyctl secrets set` で
本番に投入。コード側 (`api/email_webhook.py`) が `X-Postmark-Signature`
ヘッダ (= base64(HMAC-SHA256(body, secret))) を constant-time 比較する。

### 5-2. 既存テーブルの再利用

`subscribers` テーブル (migration 002) の `unsubscribed_at` カラムを
そのまま流用 (task brief は `unsubscribed` 専用テーブルを想定していたが、
実コードは `subscribers.unsubscribed_at` に INSERT/UPDATE する)。
`source` カラムに `suppress:bounce` / `suppress:spam-complaint` /
`suppress:list-unsubscribe` が入るので audit 時に識別可能。

---

## 6. Template Alias 一覧

Postmark UI → Templates でテンプレートを作る。コードは TemplateAlias で
fire するだけなので **HTML は Postmark 側で自由に編集可能 (デプロイ不要)**。

### 6-1. `welcome` (transactional, D+0)

- 件名: `jpintel-mcp API キーを発行しました`
- TemplateModel: `{ key_last4, tier }`
- Body 骨格:
  ```
  ご登録ありがとうございます。{{ tier }} プランの API キーを発行しました。

  キーの末尾 4 文字 (照合用): ****{{ key_last4 }}
  キー本体は決済完了画面に 1 度だけ表示されています。紛失した場合は
  ダッシュボードから rotate-key してください。

  Getting started: https://jpcite.com/docs/
  Support:        support@jpcite.com
  ```
- Tag: `welcome`、Stream: `outbound`
- 特商法除外: 取引関連なので opt-out 不要 (ただし footer に support 連絡先)

### 6-2. `weekly-digest` (broadcast, W7〜)

- 件名: `今週の補助金 3 件` (件名 A/B は `retention_digest.md` §7)
- TemplateModel: `{ programs: [...3], unsub_token, email }`
- Body 骨格:
  ```
  今週の検索傾向に合う制度を 3 件お届けします。

  1. {{programs.0.name}} ({{programs.0.amount_max}}万円) {{programs.0.url}}
  2. ...
  3. ...

  配信停止: https://jpcite.com/v1/subscribers/unsubscribe?scope=digest&email={{email}}&token={{unsub_token}}
  ```
- Tag: `digest`、Stream: `broadcast`
- 特商法 11 条: **unsubscribe link 必須** (本 template のみ)

### 6-3. `receipt` (transactional, on-demand)

- 件名: `領収書 #{{invoice_number}}`
- TemplateModel: `{ invoice_url }` (+ Postmark 側で `invoice_number` を
  variable として展開するか、invoice_url の末尾から切り出す)
- Body: Stripe hosted invoice URL へ誘導。**自分で PDF 生成しない** (JCT
  適格請求書は Stripe Tax が生成する — `research/stripe_jct_setup.md`)。
- Tag: `receipt`、Stream: `outbound`

### 6-4. `password-reset` (future placeholder)

- dashboard passwordless login 実装時 (W8 以降) に追加。
- 現時点 alias だけ Postmark に予約しておく (`password-reset`, 空 body)。

---

## 7. プライバシー / 法務の追記 1 行

`site/privacy.html` 第 4 条の 2 (APPI 28 条 越境移転) のリストに
**1 行追記** する (全文書き換えではない):

```html
<li>米国: Wildbit, LLC (Postmark / 取引メール配信)</li>
```

追記だけで法務レビュー通過可能 — 他の委託先 (Stripe/Fly/Sentry) と
同じフォーマットに揃えること。

---

## 8. 運用チェックリスト (launch 前日 5/5)

- [ ] Postmark アカウント作成、Sender Signature verify 完了
- [ ] DNS 4 本投入、`dig` で伝播確認
- [ ] DMARC = `p=quarantine` で 14 日観測タイマー開始
- [ ] `POSTMARK_API_TOKEN` / `POSTMARK_WEBHOOK_SECRET` を `flyctl secrets set`
- [ ] `POSTMARK_FROM_TRANSACTIONAL=no-reply@jpcite.com` 投入
- [ ] `POSTMARK_FROM_REPLY=hello@jpcite.com` 投入
- [ ] `JPINTEL_ENV=prod` に切替 (dev → prod で test-mode gate が解除)
- [ ] Template Alias 4 件作成 (welcome / weekly-digest / receipt /
      password-reset placeholder)
- [ ] Webhook URL 登録 + HMAC secret 同期
- [ ] mail-tester 9.5/10 取得
- [ ] 自分宛に welcome smoke 送信 (rotate-key 経由)
- [ ] `site/privacy.html` に Postmark 1 行追記

---

## 9. 外部参照

- Postmark DNS guide: https://postmarkapp.com/support/article/1002-spf-dkim-and-dmarc
- Postmark webhook signatures: https://postmarkapp.com/developer/webhooks/webhooks-overview
- DMARC 段階運用: https://dmarc.org/overview/
- 特商法 11 条 (電子メール広告): 消費者庁 2023 年改正対応条文
