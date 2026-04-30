# Operators Playbook — AutonoMath

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

最終更新: 2026-04-26 / 対象: solo founder (梅田)。zero-touch 前提なので「最初の support 1 人」という想定は廃止。
Launch: 2026-05-06 / 想定 volume: W5-W8 = 10-50 paid / W12 = 100-500 paid

深夜 2 時に customer メールが来た時に開く本。読み飛ばして、動いて、検証する。

---

## §1 原則 (stance)

1. **24 時間以内に 1 次応答する (平日営業日基準)**。問題解決は後でよい。「受け取った / 調査する / 回答期限」を必ず返信する。土日祝は 48 時間。
2. **データのギャップは正直に言う**。「網羅率 100% ではない」「この制度は trust_level=B」など。盛らない。
3. **採択/受給の約束は絶対しない**。jpintel-mcp は制度 **情報** の提供であり、採択・受給の意思決定 は customer 責任。TOS §3 参照。
4. **書かずに動かない**。全 decision は log に残す (§3 `research/refund_decisions.log`、§6 APPI 対応は `research/data_deletion_log.md`)。後で監査・検索できる状態にする。
5. **法律・税務は自分で答えない**。§10 escalation 参照。
6. **一次資料主義**。customer が「制度の内容が違う」と言ってきたら、MAFF / 公庫 / e-Gov / 自治体 official site の URL を要求し、そこで確認してから反映する。`feedback_no_fake_data.md` 原則。

---

## §2 Stripe disputes / chargebacks

### 2.1 発生トリガー (よくあるパターン)

| パターン | 根本原因 | 防止策 |
|---------|---------|--------|
| 「身に覚えがない」(Unrecognized) | 明細 descriptor が曖昧 / 家族カード | Stripe Settings → Business settings → Public details で descriptor を `JPINTEL-MCP` に固定 |
| 「サービスが受け取れていない」(Product not received) | API key 到達失敗 / welcome mail 遅延 | `api_keys` に row があるか + welcome mail 送信済か確認 |
| 「商品説明と違う」(Product unacceptable) | pricing page の誤解 / 用語不統一 | `docs/pricing.md` と `site/pricing.html` の整合、rate limit 数値固定 |
| 「承認していない決済」(Fraudulent) | 実際に fraud / 盗難カード | Radar baseline rule 維持、3DS2 強制 |

### 2.2 対応 window

Stripe から dispute 通知が届いたら **20 日以内** に evidence を提出しないと自動敗訴。実運用は **通知から 5 営業日以内** に提出する目標で動く。

### 2.3 提出手順 (JP Merchant Evidence)

1. Stripe Dashboard → Payments → Disputes → 該当 dispute 選択
2. 「Submit evidence」クリック
3. 最低限の添付 4 点:
   - **Receipt / invoice**: Stripe が自動発行した PDF (Payments → 該当 payment → Invoice)
   - **Terms of service acceptance**: `tos.html` URL + Checkout で `consent_collection.terms_of_service = required` が ON の session ID スクショ。DB に明示的な accept timestamp は保存していないため、Stripe Checkout 側の consent record を証跡とする
   - **Product delivery evidence**: 該当 customer の `api_keys.created_at` + `api_keys.last_used_at` を sqlite から抜いたスクリーンショット (§5 の `support_stats.py` 出力 or 下記 query)
   - **Customer communication**: welcome mail 本文 + support スレッド全文
4. `Refund issued` は基本 No (§3 で事前 refund していれば Yes + 詳細記載)
5. 提出前に `research/disputes/<dispute_id>.md` にメモ (日付 / 金額 / 添付ファイル一覧 / 提出日時)

### 2.4 Product delivery evidence 取得 query

```bash
sqlite3 data/jpintel.db <<SQL
.headers on
.mode column
SELECT customer_id, tier, created_at, last_used_at, revoked_at,
       (SELECT COUNT(*) FROM usage_events ue WHERE ue.key_hash = ak.key_hash) AS call_count
  FROM api_keys ak
 WHERE customer_id = 'cus_XXXX';
SQL
```

本番は Fly 上:
```bash
flyctl ssh console -a jpintel-mcp -C \
  'sqlite3 /data/jpintel.db "SELECT customer_id,tier,created_at,last_used_at,revoked_at FROM api_keys WHERE customer_id=\"cus_XXXX\";"'
```

### 2.5 Post-dispute

- 敗訴 (lost): loss amount + ¥1,500 前後の chargeback fee。`api_keys.revoked_at` を `UPDATE` で打つ (§5 参照)。`research/disputes/<id>.md` に "lost" 追記。
- 勝訴 (won): evidence が accepted、資金戻る。customer には追加 contact しない (再燃リスク)。

---

## §3 Refund requests

### 3.1 判断フロー

```
customer refund 希望
   |
   v
[1] 決済から 7 日以内 & 使用量低 (call_count < 100)?
   |- Yes -> 全額 refund + key revoke (§5 手順) -> refund_full.md 返信
   |- No -> [2]
   |
[2] 使用は中程度 & サイクル半ば?
   |- Yes -> 日割り refund + 次サイクル解約 -> refund_prorated.md 返信
   |- No -> [3]
   |
[3] 濫用 (低 tier で high volume / scraping) ?
   |- Yes -> refund 拒否 + ToS §6.3 引用 -> refund_denied.md 返信
           + §5 abuse handling
   |- No -> [4]
   |
[4] 判断迷う -> 24h 保留、customer に「3 営業日以内に回答」と返信
         -> §10 escalation 検討
```

### 3.2 実行手順

1. **事実確認**: `api_keys.created_at` / `last_used_at` / `usage_events` で call_count 確認 (§2.4 query 再利用)
2. **decision 記録**: `research/refund_decisions.log` に 1 行追記
   ```
   2026-05-10T14:30+09:00 | cus_XXX | plus | full | call_count=23 since 2026-05-03 | ticket_id=SP-0012 | operator=umeda
   ```
3. **Stripe 操作**: Dashboard → Payments → 該当 payment → Refund ボタン
   - 全額: `Refund full amount`
   - 日割り: 「Partial refund」に円金額入力 (`月額 * (残日数 / 30)` を手計算)
4. **Key revoke** (§5 `scripts/revoke_key.sh` 参照、全額 refund の場合は即時 revoke、日割りの場合は次サイクル末で revoke)
5. **返信**: `docs/_internal/templates/refund_*.md` をコピーしプレースホルダ置換

### 3.3 消契法 8 / 8-2 ガードレール

- `tos.html` §8 は「消費者 (消契法 2 条 1 項) の場合は 8 条・8 条の 2 に反する限度で適用しない」と明記済。
- つまり **「一切 refund しない」というブランケット拒否は無効**。重過失・故意があれば責任限定できない。
- 濫用ケースで refund 拒否する場合も「ToS § 6.3 に基づき」と根拠条項を明示し、最終判断は lawyer escalation を念頭に置く。

---

## §4 Data correction requests

「制度 X の上限は 500 万じゃなく 300 万」「この subsidy_rate は 1/2 ではなく 2/3」などの指摘対応。

### 4.1 検証フロー

1. **ticket open**: 24h 以内に 1 次応答 (受領 + 調査開始の通知、テンプレ `data_correction_acknowledged.md`)
2. **ソース要求**: customer の指摘に URL + 具体箇所 (ページ番号 / 段落) が無ければ `data_correction_source_needed.md` で再送依頼
3. **primary source 確認** (一次資料のみ):
   - 国の制度: MAFF (`www.maff.go.jp`) / 公庫 (`www.jfc.go.jp`) / e-Gov (`elaws.e-gov.go.jp`) / 総務省 (`www.soumu.go.jp`)
   - 自治体: 該当自治体 official site (noukaweb 等 2 次 aggregator は裏取り用のみ)
   - 告示/交付要綱: PDF を `research/source_cache/<unified_id>/` に保存
4. **判定**:
   - customer 正しい → §4.2 パッチ手順
   - customer 誤り → `data_correction_rejected.md` で 一次資料 URL 添えて返信、こちらの値の根拠を示す
   - 判定不能 (資料が曖昧) → 発行元に電話/メールで確認、結論出るまで ticket open

### 4.2 パッチ手順 (customer が正しい場合)

1. `data/fix_<unified_id>.md` を起票 (差分 / 証拠 URL / 担当 / 期限)
2. Autonomath 側 `unified_registry` の該当 row を修正 → `scripts/ingest_tier.py` (dry-run → 本番) で DB 再投入
3. 7 日以内に反映、PR URL を取得
4. customer へ返信 (PR URL + 反映予定日時)、`data_correction_acknowledged.md` の follow-up 形式で
5. `research/data_fixes.log` に 1 行追記 (日付 / unified_id / 修正内容 / ticket / source_url)

### 4.3 多発した指摘への対応

同じ制度系統で 3 回以上同種 correction が来たら、 ingest 側の pipeline bug の可能性。`project_registry_vocab_drift.md` / `project_enrichment_done_criterion.md` 原則に戻り、matcher / enrichment 側を疑う。

---

## §5 Abuse reports

### 5.1 検出シグナル

| シグナル | 示唆 | 確認 query |
|---------|------|-----------|
| 同 key の IP 分散 (5+ /24) | key sharing | `scripts/support_stats.py` の outlier 節 |
| call_count が tier limit の 3x 超 | limit 回避 / bug 悪用 | 同上 |
| 同 IP /24 から multiple anon 枠消費 | anon rate-limit 回避 | `anon_rate_limit` (migration 007 適用後のみ) |
| endpoint 偏り (ほぼ 1 endpoint) | scraping | `usage_events GROUP BY endpoint` |

### 5.2 Revoke 手順

`scripts/revoke_key.sh` は **まだ存在しない**。下記 inline 手順で revoke する。将来 script 化 (TODO owner=umeda)。

```bash
# 1. 対象 key を特定 (customer_id 起点 or key_hash 起点)
sqlite3 data/jpintel.db <<SQL
SELECT key_hash, customer_id, tier, stripe_subscription_id, created_at, last_used_at
  FROM api_keys
 WHERE customer_id = 'cus_XXXX' AND revoked_at IS NULL;
SQL

# 2. Revoke (single key)
flyctl ssh console -a jpintel-mcp -C \
  'sqlite3 /data/jpintel.db "UPDATE api_keys SET revoked_at = datetime(\"now\") WHERE key_hash = \"<HASH>\";"'

# 3. Stripe subscription も止める (必要時)
# Dashboard → Customers → 該当 → Subscriptions → Cancel subscription
# (webhook 経由で revoke_subscription() が走り残 key も revoke される)
```

`src/jpintel_mcp/billing/keys.py` の `revoke_key()` / `revoke_subscription()` が API 経由の revoke ロジック。管理画面 `/v1/admin/*` に revoke endpoint があるかは `api/admin.py` 未確認 (TODO: admin UI 経由化)。

### 5.3 通知

- 濫用: `abuse_key_revoked.md` テンプレで revoke 理由 + ToS 該当条項 + (必要なら) 再発行条件を記載
- 決済継続中の customer (legitimate な誤用) は必ず事前 1 回 warning → 改善無ければ revoke。Stripe subscription は別途。

---

## §6 GDPR / APPI data deletion requests

### 6.1 当社が保持する個人情報

| table | column | 内容 |
|-------|--------|------|
| `subscribers` | `email` | newsletter 購読メール |
| `api_keys` | `customer_id`, `stripe_subscription_id` | Stripe 紐付け ID (メール本体は Stripe 側) |
| `feedback` | `customer_id`, `ip_hash`, `message` | feedback 投稿 |
| `usage_events` | `key_hash` (indirectly linked to customer_id) | API 呼び出しログ |
| (将来) `anon_rate_limit` | `ip_hash` | 匿名 IP ハッシュ (migration 007 後) |

Email 本体は `subscribers` のみ。`api_keys` に raw key は保存しない (SHA256-HMAC hash のみ)。

### 6.2 本人確認

- 登録 email から送信 & その email を subject line と一致させる → match すれば「stored email match」として受理
- Stripe 決済経由の customer は `customer_id` + Stripe 側の登録 email が一致するかを Stripe Dashboard で目視

### 6.3 削除手順

本番 Fly 上で実行する。

```bash
# target: email = "user@example.com"
# target: customer_id = "cus_XXXX"  (Stripe Dashboard で確認)

flyctl ssh console -a jpintel-mcp
sqlite3 /data/jpintel.db <<SQL
BEGIN;
-- 1) subscribers の email 削除
DELETE FROM subscribers WHERE email = 'user@example.com';

-- 2) api_keys は削除せず revoke (支払い履歴との紐付け監査のため)
--    customer_id を NULL 化 + stripe_subscription_id 削除で linkage 断つ
UPDATE api_keys
   SET revoked_at = COALESCE(revoked_at, datetime('now')),
       customer_id = NULL,
       stripe_subscription_id = NULL
 WHERE customer_id = 'cus_XXXX';

-- 3) feedback の PII null 化
UPDATE feedback
   SET customer_id = NULL, ip_hash = NULL, message = '[deleted on user request]'
 WHERE customer_id = 'cus_XXXX';

-- 4) usage_events は key_hash のみで PII 薄。該当 key_hash は残す (billing reconciliation 用)
--    PII としての削除要求範囲外と判断。監査ログ扱い。

COMMIT;
SQL
```

Stripe 側の削除は Dashboard → Customers → 該当 customer → **Actions → Delete customer**。ただし過去 invoice の法定保管 7 年 (法人税法・所得税法) が優先されるので、削除前に lawyer escalation が無難。

### 6.4 anon_rate_limit IP hash null 化

Migration 007 未適用 (2026-04-23 時点、live DB に table 無し) のため N/A。適用後は `UPDATE anon_rate_limit SET ip_hash = '[deleted]' WHERE ip_hash = ?`。

### 6.5 SLA

APPI 35 条: 請求から 2 週間以内に要応答 (遅延時は理由開示)。実運用は **7 日以内に完了 + 応答**、遅くとも **30 日以内**。完了後 `research/data_deletion_log.md` に記録 (日付 / customer_id / 削除範囲 / operator / 備考)。

---

## §7 Outage response

### 7.1 判定

- `flyctl status -a jpintel-mcp` で machine が `stopped` / health check 連続 fail
- `curl -sS -o /dev/null -w '%{http_code}\n' https://jpcite.com/healthz` が 5xx or timeout
- UptimeRobot / Sentry spike

詳細 diagnose は `docs/incident_runbook.md` §(a)(c)(d)。

### 7.2 CNAME flip (Fly 完全ダウン時)

`docs/_internal/fallback_plan.md` に詳細。要約:

1. Cloudflare Dashboard → `jpcite.com` → DNS → Records
2. `@` (apex) A/AAAA を削除、CNAME `jpintel-mcp-fallback.pages.dev` (proxied, TTL 300) に変更
3. `site/status.html` の `active` class を `.state.ok` → `.state.down` に移動、commit + push (Pages は 30s で redeploy)
4. 同時進行で §7.3 communication

### 7.3 Customer communication

- **0-30 min**: `site/status.html` 更新 + X / HN に 1 post
- **30-60 min**: paying customer 全員に `outage_update.md` テンプレで 1 次通知 (Postmark broadcast)
- **復旧後**: 同テンプレの「復旧」版で 2 次通知
- **72h 以内**: postmortem を `docs/_internal/postmortems/YYYY-MM-DD-<slug>.md` に投稿 (既存 dir 無ければ mkdir、ファイル形式: 要約 / timeline / root cause / 再発防止 / 補償方針)

### 7.4 復旧

1. `flyctl status` machine が `started` + health check 連続 pass
2. DNS を Fly A/AAAA に戻す (§7.2 の逆)
3. `status.html` を `ok` に戻す
4. smoke: `BASE_URL=https://jpcite.com ./scripts/smoke_test.sh`

---

## §8 Critical path numbers

全て `TODO owner-fills` を **launch 前 (2026-05-06)** に埋める。

| 先 | 用途 | 連絡先 |
|----|------|--------|
| Fly Status | infra outage 確認 | https://status.fly.io/ |
| Fly dashboard | app monitoring | https://fly.io/apps/jpintel-mcp/monitoring |
| Stripe Support (JP) | dispute / payout 問題 | +81-3-4530-9047 (2026 時点公開 / launch 前再確認) / `TODO owner-fills 最終電話番号` |
| Stripe status | payment downstream | https://status.stripe.com/ |
| Postmark status | mail delivery | https://status.postmarkapp.com/ |
| Cloudflare status | DNS / Pages | https://www.cloudflarestatus.com/ |
| Sentry dashboard | error tracking | `TODO owner-fills Sentry org URL` |
| UptimeRobot | external health | `TODO owner-fills dashboard URL` |
| 弁護士 | 法的 demand 対応 | `TODO owner-fills 事務所名 / 電話 / メール` |
| 税理士 | インボイス / 消費税 / 所得税 | `TODO owner-fills 同上` |
| 司法書士 | 登記 / 定款 | `TODO owner-fills 同上` |
| 弁理士 | 商標 (Intel 衝突 — `project_jpintel_trademark_intel_risk.md`) | `TODO owner-fills 同上` |

---

## §9 Legal support response

### 9.1 特商法 32 条 — 消費者相談対応

- 消費生活センター (国民生活センター or 地方自治体) から照会が来たら **3 営業日以内に書面で応答**
- `site/tokushoho.html` の記載 8 項目 (事業者名 / 住所 / 電話 / 販売価格 / 支払方法 / 引渡時期 / 返品特約 / 連絡先メール) と矛盾しない回答
- 記録: `research/consumer_inquiries/<date>_<case_id>.md` に全文保存
- 迷ったら即 §10 lawyer escalation

### 9.2 インボイス T-号 未登録 reply (launch 後もまだ未登録の場合)

B2B customer から「適格請求書発行事業者登録番号を教えてほしい」と来る。`data_correction_acknowledged.md` ベースでなく専用短文:

```
ご連絡ありがとうございます。
弊サービスは現在、適格請求書発行事業者登録 (T-号) を申請中です。
発行までのリードタイムは 2-3 週間を見込んでおり、完了次第ご連絡いたします。
経過措置 (2026-09 まで仕入税額 80% 控除、2029-09 まで 50% 控除) 期間中となりますため、
御社での税額控除に影響がある場合は別途ご相談ください。
```

登録完了後は `docs/_internal/email_setup.md` / `site/tokushoho.html` / Stripe `invoice_settings.default_account_tax_ids` を **同じ日に全部更新**。

---

## §10 Escalation decisions

### 10.1 自分で処理 (= operator hat)

- §2 dispute evidence 提出 (定型添付 4 点で済むもの)
- §3 refund (full / prorated、判断明快なもの)
- §4 data correction (一次資料で判定可能なもの)
- §5 abuse revoke (明白な key share / scraping)
- §6 APPI deletion (身元確認 OK のもの)
- §7 outage 一次対応 & postmortem 執筆

### 10.2 即 escalation

| 状況 | escalate 先 |
|------|-------------|
| 内容証明 / 訴状 / 弁護士名義の書面 | 弁護士 |
| 刑事関連 (詐欺告訴 / 個人情報流出 疑い) | 弁護士 (優先)、警察は弁護士経由 |
| 税務署からの問合せ (10 分以上で回答できないもの) | 税理士 |
| Stripe payout hold / account review > 3 日 | Stripe Support 電話 + 弁護士 standby |
| 消費者庁 / 消費生活センター 照会 (書面) | 弁護士 quick review → 自分で返答 |
| メディア取材 (TV / 全国紙) | 広報 (TBD、`TODO owner-fills`) / 当面は「24 時間以内に書面で」と保留 |
| `project_jpintel_trademark_intel_risk.md` 関連の商標クレーム | 弁理士 + 弁護士 |
| データ破損で customer data loss の可能性 | 弁護士 + §7 outage フル起動 |

### 10.3 Escalation ログ

`research/escalations.log` に 1 行追記:
```
2026-05-10T10:00+09:00 | legal-demand | cus_XXX / ticket=SP-0099 | sent-to=lawyer-xxx | status=pending
```

---

## Appendix A. 毎週の ritual

| 曜日 | 作業 | 所要 |
|------|------|------|
| 月 AM | `scripts/support_stats.py` 実行、outlier 確認 | 10 分 |
| 月 AM | 先週の `refund_decisions.log` + `data_fixes.log` 追記漏れ確認 | 5 分 |
| 金 PM | dispute queue を Stripe Dashboard で目視 (20 日期限過ぎ防止) | 5 分 |
| 金 PM | postmortem draft があれば publish | 15-60 分 |

## Appendix B. TODO (未実装)

- [ ] `scripts/revoke_key.sh` 整備 (§5.2 の inline 手順を script 化)
- [ ] `anon_rate_limit` migration 007 を本番 DB に適用 (§6.4 が有効化される)
- [ ] `docs/_internal/postmortems/` dir 作成 (`.gitkeep` か template ファイル)
- [ ] `research/refund_decisions.log` / `data_fixes.log` / `data_deletion_log.md` / `escalations.log` / `consumer_inquiries/` の空ファイル起き
- [ ] §8 `TODO owner-fills` を launch 前に全部埋める
- [ ] `api/admin.py` に revoke endpoint があるか確認、無ければ追加検討
- [ ] `usage_events.params_digest` column は schema.sql にあるが live DB に無い。追加 migration 要否判定
