# Retention Email Digest — 設計書

| 項目 | 値 |
| --- | --- |
| Go-live | W7 (2026-05-20 水) |
| First send | 2026-05-20 09:00 JST |
| Cadence | 週1回 (水 09:00 JST) |
| Vendor | Postmark (launch), SES (50K users 以降の再評価) |
| Target open | 25% / CTR 8% / Unsub < 2% / Spam < 0.1% |
| Migration | `004_digest.sql` |
| Cron | `.github/workflows/digest.yml` (`0 0 * * 3` UTC = 水 09:00 JST) |
| Script | `scripts/send_digest.py` |

既存の newsletter (`src/jpintel_mcp/api/subscribers.py`) はブロードキャストで、本 digest はパーソナライズ配信という別レール。Opt-in/opt-out・HMAC 解除トークンは newsletter と同じ方式を流用する。

---

## 1. Audience gating

### 1.1 対象ユーザー
| Tier | Default opt-in | Opt-out | Cap |
| --- | --- | --- | --- |
| Free (newsletter 経由のみ) | `digest_opted_in = 1` が必須 | footer link + `/v1/subscribers/unsubscribe` | 1/週 |
| Paid (starter/growth) | 自動 opt-in | footer link | 1/週 |

`subscribers` に email しか持たないユーザー (API key 未発行) も digest 対象。ただしパーソナライズ材料 (`usage_events`) が無いので「新規ユーザー fallback テンプレ」(§6B) に分岐。

### 1.2 Active-user suppression (don't spam the engaged)
過去7日で `metered=1` の `usage_events` が **10件以上** あるユーザーは既に product-active なのでスキップ。

```sql
-- 配信対象 key_hash の抽出 (paid 側)
WITH last7 AS (
  SELECT key_hash, COUNT(*) AS n
  FROM usage_events
  WHERE ts >= datetime('now', '-7 days')
    AND metered = 1
  GROUP BY key_hash
)
SELECT k.key_hash, k.customer_id, k.tier
FROM api_keys k
LEFT JOIN last7 u ON u.key_hash = k.key_hash
LEFT JOIN digest_state d ON d.key_hash = k.key_hash
WHERE k.revoked_at IS NULL
  AND k.tier IN ('starter','growth')
  AND COALESCE(u.n, 0) < 10
  AND COALESCE(d.opted_in, 1) = 1
  AND (d.last_sent_at IS NULL OR d.last_sent_at < datetime('now','-6 days'));
```

Free-tier (email-only) は `subscribers.digest_opted_in = 1 AND unsubscribed_at IS NULL` のみで引く。重複抑止のため email 単位でも `digest_state.last_sent_at` を持つ (key_hash NULL 可)。

### 1.3 データソース制約 — 重要

現状の `usage_events` は `(key_hash, endpoint, ts, status, metered)` のみで、**`q` / filter 引数は記録していない**。そのため §2 で「検索履歴」をパーソナライズ材料にするには:

- 追加カラム **`params_digest TEXT`** を `usage_events` に足す (migration `005_usage_params.sql`)。
- 値は `sha1("q=...|prefecture=...|target_types=...")` のような **ハッシュではなく正規化文字列** (後で集計するため)。平文 `q` を長期保存するのは個人検索履歴に近く、30日 TTL で自動パージ。
- PII を避けるため、`q` が email/phone 正規表現にマッチしたら拒否保存。

この追加 migration は digest 稼働の前提条件で、W6 (5/13) までに本番に適用する。

---

## 2. Content formula (per user)

| ブロック | 件数 | ロジック |
| --- | --- | --- |
| A. 「あなたの検索に合う制度」 | 3 | 過去7日の `params_digest` から prefecture / target_types / crop_categories / amount_band を頻度で集計し、マッチする programs を `coverage_score DESC, updated_at DESC` で上位3件 |
| B. 「先週以降に追加された制度」 | 最大2 | `source_fetched_at > last_sent_at` かつ A と同じフィルタで絞る。無ければブロックごと省略 |
| C. 「見落としがちな除外ルール」 | 1 | `exclusion_rules` からランダム1件 (`seed = hash(key_hash||week)` で週の中では決定的) |
| D. 使用量サマリ | 1 | 本人 tier の月間 quota と消化率 (`usage_events` で集計) |
| E. Footer | — | Unsubscribe (HMAC) / support@ / docs |

### 2.1 Top-3 抽出 SQL (A ブロック)

```sql
-- 入力: :key_hash, :week_start (ISO)
WITH recent AS (
  SELECT params_digest
  FROM usage_events
  WHERE key_hash = :key_hash
    AND ts >= :week_start
    AND endpoint LIKE '/v1/programs%'
    AND status = 200
),
-- params_digest は "pref=saitama|target=法人|crops=rice" 形式を想定
tokens AS (
  SELECT
    TRIM(REPLACE(SUBSTR(v, 1, INSTR(v, '=')-1), ' ', '')) AS k,
    TRIM(SUBSTR(v, INSTR(v, '=')+1)) AS val,
    COUNT(*) AS hits
  FROM (
    SELECT value AS v
    FROM recent, json_each('["' || REPLACE(params_digest, '|', '","') || '"]')
  )
  WHERE v <> '' AND INSTR(v, '=') > 0
  GROUP BY k, val
),
top_pref AS (
  SELECT val FROM tokens WHERE k='pref'   ORDER BY hits DESC LIMIT 3
),
top_target AS (
  SELECT val FROM tokens WHERE k='target' ORDER BY hits DESC LIMIT 3
),
top_crops AS (
  SELECT val FROM tokens WHERE k='crops'  ORDER BY hits DESC LIMIT 3
)
SELECT p.unified_id, p.primary_name, p.prefecture, p.authority_name,
       p.amount_max_man_yen, p.subsidy_rate, p.official_url, p.tier,
       p.coverage_score
FROM programs p
WHERE p.excluded = 0
  AND p.tier IN ('S','A','B')
  AND (
        p.prefecture IN (SELECT val FROM top_pref)
     OR EXISTS (
          SELECT 1 FROM json_each(COALESCE(p.target_types_json,'[]')) t
          WHERE t.value IN (SELECT val FROM top_target)
        )
     OR EXISTS (
          SELECT 1 FROM json_each(COALESCE(p.crop_categories_json,'[]')) c
          WHERE c.value IN (SELECT val FROM top_crops)
        )
      )
ORDER BY
  -- prefecture 一致を優先、次に tier、次に coverage
  (CASE WHEN p.prefecture IN (SELECT val FROM top_pref) THEN 0 ELSE 1 END),
  (CASE p.tier WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END),
  p.coverage_score DESC,
  p.updated_at DESC
LIMIT 3;
```

検索履歴が空 (new signup) の場合は fallback として `tier='S' AND excluded=0` から `amount_max_man_yen DESC` で上位5件を選ぶ。

### 2.2 Freshness (B ブロック)

```sql
SELECT unified_id, primary_name, prefecture, official_url, source_fetched_at
FROM programs
WHERE source_fetched_at > COALESCE(:last_sent_at, datetime('now','-7 days'))
  AND excluded = 0
  AND (prefecture IN (SELECT val FROM top_pref)
       OR EXISTS (SELECT 1 FROM json_each(target_types_json) t
                  WHERE t.value IN (SELECT val FROM top_target)))
ORDER BY source_fetched_at DESC
LIMIT 2;
```

### 2.3 Exclusion rule (C ブロック) — ランダム1件

```sql
SELECT rule_id, severity, description, program_a, program_b
FROM exclusion_rules
WHERE severity IN ('high','medium')
ORDER BY (abs(random()) % (SELECT COUNT(*) FROM exclusion_rules))
LIMIT 1;
```

---

## 3. Privacy posture

| 項目 | ポリシー |
| --- | --- |
| 検索ワードの保管 | `params_digest` 30日 TTL。`scripts/purge_params.py` を nightly で実行 |
| 本文の保管 | **しない**。`digest_log` には `(key_hash, sent_at, status, postmark_message_id, program_ids_json)` だけ。本文 HTML は送信後破棄 |
| Free-tier opt-in | `subscribers.digest_opted_in` = 1 必須 (UI チェックボックス default OFF) |
| Paid opt-out | footer link 1-click (HMAC token) |
| 外部共有 | Postmark にメール本文+メールアドレスを送る以外、第三者共有なし |
| `privacy.html` 更新 | 「検索トレンドに基づく digest 配信」「送信者: AutonoMath <noreply@zeimu-kaikei.ai>」「委託先: Postmark (米 Wildbit LLC)」を W6 までに追記 |
| APPI 越境移転 | Postmark = 米国。「越境移転の同意」条項を signup 画面と privacy に明示 |

---

## 4. Vendor choice — **Postmark**

| Vendor | 月額(10K) | Pros | Cons | 判定 |
| --- | --- | --- | --- | --- |
| **Postmark** | ~¥1,500 | 日本からのレピュ良好、Transactional 特化、DMARC ガイドが明確、低 bounce | price scale | **採用** |
| AWS SES | ~¥150 | 安い、AWS 統合 | warmup 必要、UI 弱い、dashboard 貧弱 | 50K 以降で再評価 |
| Fastmail / self-SMTP | 固定 ~¥500 | 学習にはなる | deliverability 地雷、IP 汚染で全滅リスク | 不採用 |

launch 時は **Postmark** 一択。reputation が安定したら SES hybrid (bulk = SES, high-value = Postmark) を検討。

---

## 5. Architecture

### 5.1 Migration `scripts/migrations/004_digest.sql`

**Prerequisite (landed 2026-04-23):** `005_usage_params.sql` — adds `params_digest TEXT` + `idx_usage_events_key_params` to `usage_events`. Digest is a 16-char SHA-256 over canonical JSON of query params, computed at `api/deps.py::log_usage` time, whitelisted to `programs.search` / `programs.get` / `exclusions.check` / `exclusions.rules` / `meta` / `ping`. PII-heavy endpoints (`/v1/me/*`, `/v1/billing/*`, `/v1/feedback`, `/v1/subscribers`) stay `params_digest = NULL`. **TTL cron: still outstanding** — no nightly purge exists today; `params_digest` inherits retention from the parent `usage_events` row, whatever that ends up being. `scripts/purge_params.py` (§3) must be wired before W6 or raw query history accumulates past 30 days.

```sql
-- 004_digest.sql
ALTER TABLE subscribers ADD COLUMN digest_opted_in INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS digest_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT,                 -- paid users
    email TEXT,                    -- free users (email-only)
    opted_in INTEGER NOT NULL DEFAULT 1,
    preferred_day INTEGER DEFAULT 3,  -- 0=Sun..3=Wed..6=Sat
    last_sent_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(key_hash),
    UNIQUE(email)
);

CREATE INDEX IF NOT EXISTS idx_digest_state_last_sent ON digest_state(last_sent_at);

CREATE TABLE IF NOT EXISTS digest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT,
    email TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,          -- 'sent'|'deferred'|'failed'|'skipped'
    postmark_message_id TEXT,
    program_ids_json TEXT,         -- digest に含めた unified_id の配列
    error_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_digest_log_sent_at ON digest_log(sent_at);
CREATE INDEX IF NOT EXISTS idx_digest_log_key_hash ON digest_log(key_hash);
```

### 5.2 `.github/workflows/digest.yml`

```yaml
name: digest
on:
  schedule:
    - cron: "0 0 * * 3"   # Wed 00:00 UTC = Wed 09:00 JST
  workflow_dispatch: {}
concurrency:
  group: digest
  cancel-in-progress: false
jobs:
  send:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e '.[dev]'
      - name: Pull latest DB from Fly
        run: scripts/pull_db.sh
        env: { FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }} }
      - name: Send digests
        run: python scripts/send_digest.py --limit 5000 --rate 100
        env:
          POSTMARK_TOKEN: ${{ secrets.POSTMARK_TOKEN }}
          API_KEY_SALT:   ${{ secrets.API_KEY_SALT }}
          DIGEST_SENDER:  "AutonoMath <noreply@zeimu-kaikei.ai>"
```

`digest` は **DB read-only** で十分だが、`digest_state.last_sent_at` と `digest_log` への書き込みだけ push-back する設計 (別スクリプト or POST endpoint `/v1/internal/digest-log` を作る)。

### 5.3 `scripts/send_digest.py` の骨格

```python
# pseudo
for user in iter_eligible_users(conn):
    top3   = query_top3(conn, user)
    fresh  = query_fresh(conn, user.last_sent_at)
    rule   = random_exclusion_rule(conn, seed=user.key_hash)
    usage  = query_usage_summary(conn, user)
    if not top3 and not fresh:
        body = render_fallback(user, popular5)
    else:
        body = render_digest(user, top3, fresh, rule, usage)
    batch.append(body)
    if len(batch) == 100:
        postmark_send_batch(batch)        # 100/sec rate-limit
        time.sleep(1.0)
        batch.clear()
        flush_log(conn, results)
```

Postmark Batch API (`/email/batch`) は 500 件/call, 300 req/sec が上限。本件は 100/sec に自制して余裕を持たせる。失敗は `digest_log.status='failed'`、3回連続失敗した recipient は `digest_state.opted_in=0` に automatic opt-out。

### 5.4 Unsubscribe

Newsletter と同じ `make_unsubscribe_token(email)` + `/v1/subscribers/unsubscribe?email=&token=`。digest 専用 opt-out か newsletter ごと opt-out かは URL param `?scope=digest` で分岐 (UPDATE 先が `subscribers.digest_opted_in` か `subscribers.unsubscribed_at` か)。

---

## 6. Template draft

### 6A. メール本文 (Jinja, ~200 words)

```
件名: 今週の 3 制度 — {{prefecture_label}} の方におすすめ

{{customer_name or "こんにちは"}} さん、

AutonoMath からの週次ダイジェスト (現在のプラン: {{user_tier}}) です。
過去 7 日の検索傾向から、あなたに合いそうな制度を 3 件お届けします。

―――――――――――――――
■ おすすめ制度
1. {{program_1_name}} ({{program_1_authority}})
   上限 {{program_1_amount}} 万円 / 補助率 {{program_1_rate}}
   {{program_1_url}}

2. {{program_2_name}} ({{program_2_authority}})
   上限 {{program_2_amount}} 万円 / 補助率 {{program_2_rate}}
   {{program_2_url}}

3. {{program_3_name}} ({{program_3_authority}})
   上限 {{program_3_amount}} 万円 / 補助率 {{program_3_rate}}
   {{program_3_url}}

■ 先週以降に追加された制度 ({{fresh_count}} 件)
{% for f in fresh %}- {{f.name}} — {{f.url}}{% endfor %}

■ 見落としがちな併用ルール
{{rule_description}}
(rule_id: {{rule_id}})

■ 今月の利用状況
{{usage_calls}} / {{quota}} calls ({{usage_pct}}%)

―――――――――――――――
・配信停止: {{unsubscribe_url}}
・質問: support@zeimu-kaikei.ai
・ドキュメント: https://zeimu-kaikei.ai/docs/
```

### 6B. Fallback (検索履歴なし)

> 件名: AutonoMath へようこそ — 今週の注目制度 5 件

本文は Top-5 popular (`tier='S'` の amount 順) + quickstart link + support。

---

## 7. A/B tests (W8)

| # | 軸 | A | B | 指標 |
| --- | --- | --- | --- | --- |
| 1 | 件名 | 「今週の 3 制度」 | 「{{prefecture}} で使える新しい補助金が見つかりました」 | 開封率 |
| 2 | 送信時刻 | 水 09:00 | 火 18:00 | 開封率 + 朝 vs 退勤後 CTR |
| 3 | カード件数 | 3 件 | 5 件 | CTR / スクロール到達 (UTM の深さ) |

各テストは **1 セグメント = 1 軸のみ** を 50/50 で 2 週。結果は `digest_log.program_ids_json` と UTM (`utm_source=digest&utm_campaign=wXX&utm_variant=A`) で突合。

---

## 8. Metrics & alert thresholds

| 指標 | 目標 | 警戒 | 再設計 trigger |
| --- | --- | --- | --- |
| Open rate | ≥ 25% | < 20% 2 回連続 | < 15% 4 回連続 → content 刷新 |
| CTR | ≥ 8% | < 5% | < 3% → card UI 見直し |
| Unsubscribe / send | < 2% | 2-5% | > 5% → 頻度を隔週へ |
| Spam complaints | < 0.1% | 0.1-0.3% | > 0.3% → 即送信停止 & vendor 相談 |
| Upgrade from digest click | > 0.3% / 送信 | — | tracking だけ、目標は低め |

計測は **Postmark webhook** (`delivery`, `open`, `click`, `bounce`, `spamComplaint`) を `/v1/internal/postmark/webhook` で受けて `digest_log` に UPDATE。

---

## 9. Failure modes & runbook

| 症状 | 原因候補 | 対応 |
| --- | --- | --- |
| Bounce rate > 5% | 古い email / typo | 該当 recipient を `opted_in=0`, 連続2週で auto-purge |
| Spam complaint > 0.3% | 件名 clickbait / 頻度過多 | 即 pause → 隔週へ。件名テンプレ見直し |
| Postmark 429 | burst 過多 | Batch size 100 → 50, sleep 1s → 2s。send_digest.py の `--rate` 引数で調整 |
| Postmark reputation 失墜 | bounce 蓄積 | sender domain rotation (noreply → hello@) → それでも駄目なら SES + warmup |
| 検索履歴ゼロユーザー多発 | new signup flood | §6B fallback でカバー、パフォーマンス上は問題なし |
| DB snapshot 取得失敗 | Fly sftp flaky | Postmark API は叩かず exit 1。翌週に倍送りしない (`last_sent_at` 据え置き) |

---

## 10. Rollout timeline

- **W6 (5/13)**: `004_digest.sql` + `005_usage_params.sql` を本番適用。signup UI に opt-in checkbox (default OFF for free)。`privacy.html` 更新。
- **W7 月-火 (5/18-19)**: 社内 5 アドレスへ smoke send。Postmark webhook 設定、DMARC/SPF/DKIM を本番ドメインで verify。
- **W7 水 09:00 (5/20)**: 初回配信。送信上限 `--limit 500` で始める。
- **W7 木-金**: 数値レビュー、open < 20% なら件名再考。
- **W8**: 全量配信 + A/B テスト開始。
- **W10**: 4 回配信後のレビュー。open < 15% なら content formula 刷新 (§2.1 の scoring 重み変更)。

---

## 11. Out of scope (今回やらない)

- 日次配信・時間指定パーソナライズ (W12 以降で検討)
- SMS / LINE 通知
- AI 生成本文 (hallucination リスク — program_name 以外の文は全て固定テンプレ)
- 個社向け「担当者宛コメント」機能

本 digest は **既存 programs / exclusion_rules / usage_events の aggregate 再配信** であり、新たな知識生成は行わない。
