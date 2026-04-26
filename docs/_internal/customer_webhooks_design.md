# 顧客向け Outbound Webhook 設計 (Customer Webhooks Design)

> **要約 (summary):** Pull 型 API に加えて **サーバから顧客エンドポイントに push する outbound webhook** を W5-W8 で実装する設計書。6 種の event type、HMAC-SHA256 署名 (Stripe 同方式)、at-least-once + 指数バックオフ、SSRF 防止 (https + RFC1918 遮断)、tier 別 gating (Free 不可 / Paid 全種) を定義する。実装は feature branch で W6、W7 beta 5 社、W8 GA。
>
> **Status:** 設計段階 (2026-04-23)。migration は `scripts/migrations/009_webhook_subscriptions.sql.draft` として起案のみ (未実行)。本書は `docs/POST_DEPLOY_PLAN_W5_W8.md` §4-5 の retention 施策を補完する。

---

## 1. Event type 仕様 (初期 6 種)

| # | event_type | trigger | tier 許容 | 推定 volume/顧客/月 |
|---|---|---|---|---|
| E1 | `program.created` | ingest で新規 program 追加 | Paid | 20-80 |
| E2 | `program.updated` | `source_checksum` 変更を検出 | Paid | 100-400 |
| E3 | `program.matching_filter` | 保存 filter にマッチする new program | Paid (※) | 5-30 |
| E4 | `adoption.published` | gBizINFO 採択データ追加 | Paid | 300-2,000 |
| E5 | `exclusion_rule.added` | 顧客の追跡中 program に関連する rule | Paid | 0-5 |
| E6 | `tier.quota.warning` | 1 日 quota 80% 到達 (meta) | Paid | 0-30 |

※ E3 は「保存 filter」機能 (本書 out of scope、W6 別 issue) に依存する。本書はその機能が入った瞬間配線できるよう envelope を先行確定させる。

**payload 共通エンベロープ (v1):**

```json
{
  "version": "v1",
  "event_id": "evt_01HX9Z2K7V3B4C5D6E7F8G9H0J",
  "event_type": "program.updated",
  "created_at": "2026-05-14T09:00:00+09:00",
  "subscription_id": "sub_01HX9Z...",
  "data": { /* 以下、event 別 */ }
}
```

**event 別 `data` shape:**

```json
// E1 program.created
{"unified_id":"UNI-...","primary_name":"...","authority_level":"prefecture","prefecture":"奈良県","amount_max_man_yen":300,"source_url":"https://..."}

// E2 program.updated
{"unified_id":"UNI-...","changed_fields":["amount_max_man_yen","application_window_json"],"previous_checksum":"abc123","current_checksum":"def456"}

// E3 program.matching_filter
{"unified_id":"UNI-...","filter_id":"flt_...","matched_fields":["prefecture","target_types"]}

// E4 adoption.published
{"adoption_id":"ADP-...","program_id":"UNI-...","year":2024,"count_added":42,"evidence_url":"https://info.gbiz.go.jp/..."}

// E5 exclusion_rule.added
{"rule_id":"ER-...","program_a":"UNI-A...","program_b":"UNI-B...","kind":"mutex","severity":"block"}

// E6 tier.quota.warning
{"customer_id":"cus_stripe","tier":"pro","usage_today":8120,"limit":10000,"resets_at":"2026-05-15T00:00:00+09:00"}
```

**匿名性:** E1-E5 は `customer_id` を含まない (program 情報は全顧客共通なので漏洩しない)。E6 のみ当該顧客の `customer_id` を含む (§11 プライバシーと対応)。

---

## 2. Subscription 管理 API

全エンドポイントは `X-API-Key` 認証必須 (Free は 403、`{"detail":"webhook subscriptions not available on free tier"}`)。

| Method & Path | 動作 |
|---|---|
| `POST /v1/webhooks/subscribe` | 新規 subscription 作成 |
| `GET  /v1/webhooks/subscriptions` | 呼び出し元の subscription 一覧 |
| `DELETE /v1/webhooks/subscriptions/{id}` | 削除 (soft delete: `disabled_at = now()`) |
| `POST /v1/webhooks/test/{id}` | 疎通確認 (test ping) |
| `POST /v1/webhooks/subscriptions/{id}/rotate-secret` | 署名 secret 再発行 (§6) |

**POST /v1/webhooks/subscribe body:**

```json
{
  "url": "https://customer.example.com/hooks/jpintel",
  "events": ["program.created","program.updated"],
  "filter": {"prefecture":"奈良県","authority_level":"prefecture"}
}
```

**201 response (signing_secret は一度だけ返却):**

```json
{
  "subscription_id": "sub_01HX...",
  "signing_secret": "whsec_<64-char-hex>",
  "events": ["program.created","program.updated"],
  "filter": {"prefecture":"奈良県","authority_level":"prefecture"},
  "created_at": "2026-05-14T09:00:00+09:00",
  "secret_shown_once": true
}
```

**上限 (per customer):**

| Tier | max subscriptions |
|---|---|
| Free | 0 (403) |
| Paid | 20 |

超過時は `409 Conflict`、body `{"detail":"subscription limit N reached for tier=X"}` — 既存 API の error shape と一致。

---

## 3. 配信セマンティクス

- **At-least-once.** 顧客は `event_id` による idempotency を自前で実装する (envelope にそれを促す文言をドキュメント明記)。
- **Retry policy** (5 回、~15h 合計): `1m → 5m → 30m → 2h → 12h` の指数バックオフ + ±10% ジッタ。最終失敗は `dead_letter` ログへ。
- **署名:** `X-Jpintel-Signature: t=<unix>,v1=<hex>` の CSV 形式。`v1 = HMAC-SHA256(subscription.signing_secret, f"{t}.{raw_body}")`。timestamp は replay 防止目的で **±5 分** で reject 推奨 (顧客側指針)。Stripe webhook と同一方式で、既存の `src/jpintel_mcp/api/email_webhook.py::_verify_signature` の対称実装として書ける。
- **Envelope:** `{version:"v1", event_id, event_type, created_at, subscription_id, data}`。`version` 昇格時は `v2` を新 envelope として並走させ、既存 subscription は `v1` のまま配信し続ける。
- **Timeout:** 顧客エンドポイントへの request timeout **10 秒**。TCP connect 3s、read 7s。超過は 5xx 扱いで retry。
- **成功判定:** HTTP 2xx (200/201/202/204 等) のみ ack。body は無視する。
- **Content-Type:** `application/json; charset=utf-8`。

---

## 4. データモデル (DRAFT: `scripts/migrations/009_webhook_subscriptions.sql.draft`)

> **注:** `.draft` 拡張子は未実行 migration を示す運用ルール (既存の 001-007 と区別)。W6 実装時に `009_webhook_subscriptions.sql` に改名して `scripts/migrate.py` 対象化する。

```sql
-- 009_webhook_subscriptions.sql.draft
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    subscription_id TEXT PRIMARY KEY,               -- ULID, prefix "sub_"
    customer_id TEXT NOT NULL,                      -- Stripe customer_id
    url TEXT NOT NULL,                              -- https:// 必須
    events_json TEXT NOT NULL,                      -- ["program.created",...]
    filter_json TEXT,                               -- {"prefecture":"..."}
    signing_secret_hash TEXT NOT NULL,              -- HMAC-SHA256(secret, api_key_salt)
    failures_streak INTEGER NOT NULL DEFAULT 0,     -- 連続 4xx/5xx 数
    created_at TEXT NOT NULL,
    disabled_at TEXT,                               -- NULL = active
    disabled_reason TEXT                            -- "4xx_streak"/"410_gone"/"cost_cap"/"user"
);
CREATE INDEX idx_webhook_subs_customer ON webhook_subscriptions(customer_id);
CREATE INDEX idx_webhook_subs_active ON webhook_subscriptions(disabled_at);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,                           -- "pending"|"success"|"failed"|"dead_letter"
    attempt INTEGER NOT NULL DEFAULT 1,
    response_status INTEGER,
    response_body_truncated TEXT,                   -- 先頭 512B のみ
    duration_ms INTEGER,
    delivered_at TEXT,                              -- 最終試行時刻
    FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(subscription_id)
);
CREATE INDEX idx_webhook_deliv_sub_status ON webhook_deliveries(subscription_id, status);
CREATE INDEX idx_webhook_deliv_event ON webhook_deliveries(event_id);
```

`signing_secret_hash` は検証時には使わない (検証は顧客側)、**ローテーション時の同定**と **ログ監査**用。raw secret は DB 保存しない (`api_keys` の hash 戦略と同方針)。

---

## 5. 失敗ハンドリング

| 条件 | 動作 |
|---|---|
| HTTP 2xx | success、`failures_streak = 0` |
| HTTP 4xx (400-499) 連続 10 回 | auto-disable、`disabled_reason = "4xx_streak"`、顧客にメール通知 |
| HTTP 5xx | retry 継続、auto-disable **しない** (顧客サーバ障害、設定ミスではない) |
| HTTP 410 Gone | 即 permanent disable、`disabled_reason = "410_gone"` |
| TCP/TLS/timeout | 5xx と同等扱い (retry) |
| DNS fail | 1 回目だけ 5xx 扱い、以降連続 10 回で 4xx と同等扱い (設定ミス濃厚) |

**Dead-letter log:** `webhook_deliveries.status = "dead_letter"` の row を **30 日保持**、cron で delete。顧客は `GET /v1/webhooks/subscriptions/{id}/deliveries?status=dead_letter` で一覧取得可 (design 内、実装 W7)。

---

## 6. セキュリティ

- **URL validation:**
  - `https://` 必須 (http 拒否、`400 {"detail":"https required"}`)
  - `localhost`, `127.0.0.0/8`, `169.254.0.0/16` (link-local), RFC1918 (`10/8`, `172.16/12`, `192.168/16`), IPv6 ULA (`fc00::/7`), multicast を DNS resolve 後も拒否 (SSRF 防止)
  - **TOCTOU 対策:** 実配信時にも resolve 後 IP を再チェック (subscribe 時点の DNS 結果を信用しない)
  - 社内管理面ネットワーク (Fly.io 6PN の `fdaa::/16`) も明示ブロック
- **Signing secret:**
  - サーバで `secrets.token_hex(32)` 生成
  - Subscribe response に **一度だけ** 返却 (`api_keys` と同方針)
  - DB には `HMAC-SHA256(secret, api_key_salt)` の hash のみ保存
- **Rotation:** `POST /v1/webhooks/subscriptions/{id}/rotate-secret` は **新 secret** を返却し、**旧 secret は 1 時間 grace period** 有効 (顧客の deploy 時間を確保)。grace 中は `X-Jpintel-Signature` に `v1=<new>,v1=<old>` の 2 値を付けて配信。
- **環境変数:** `JPINTEL_WEBHOOK_DISPATCH_CONCURRENCY` (既存 `JPINTEL_*` スタイル)、`JPINTEL_WEBHOOK_GLOBAL_KILL_SWITCH` (緊急全停止)。
- **Rate limit per URL:** 同一顧客の同一 URL に対して **burst 上限 30 req/sec**。超過は内部 queue で平滑化。

---

## 7. 顧客側統合ガイド (doc 同梱)

### Python 例 (`httpx + stdlib hmac`)

```python
import hmac, hashlib, time, json, os
from fastapi import FastAPI, Header, HTTPException, Request

SECRET = os.environ["JPINTEL_WEBHOOK_SECRET"].encode()
app = FastAPI()

def verify(sig_header: str, body: bytes) -> bool:
    parts = dict(p.split("=",1) for p in sig_header.split(","))
    t, v1 = parts.get("t",""), parts.get("v1","")
    if abs(time.time() - int(t)) > 300: return False
    expected = hmac.new(SECRET, f"{t}.".encode()+body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)

_seen = set()  # 本番は Redis 等で 24h TTL
@app.post("/hooks/jpintel")
async def hook(req: Request, x_jpintel_signature: str = Header(...)):
    body = await req.body()
    if not verify(x_jpintel_signature, body):
        raise HTTPException(401)
    evt = json.loads(body)
    if evt["event_id"] in _seen: return {"ok": True}  # idempotent
    _seen.add(evt["event_id"])
    # handle evt["event_type"], evt["data"]
    return {"ok": True}
```

### Node.js 例 (`crypto + express`)

```js
const express = require("express"), crypto = require("crypto");
const app = express();
app.post("/hooks/jpintel", express.raw({type:"application/json"}), (req,res) => {
  const sig = Object.fromEntries((req.header("X-Jpintel-Signature")||"").split(",").map(p=>p.split("=")));
  if (Math.abs(Date.now()/1000 - Number(sig.t)) > 300) return res.status(401).end();
  const expected = crypto.createHmac("sha256", process.env.JPINTEL_WEBHOOK_SECRET)
                         .update(sig.t+"."+req.body).digest("hex");
  if (!crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig.v1||""))) return res.status(401).end();
  const evt = JSON.parse(req.body.toString());
  // idempotency on evt.event_id
  res.json({ok:true});
});
```

### Claude Desktop / MCP との関係

**重要:** webhook は **MCP server とは別経路**。MCP server は stdio で Claude Desktop が spawn するローカルプロセス、webhook は顧客が運営する HTTPS エンドポイントへの push。MCP を使いながら webhook を受けたい場合は、**顧客側の HTTP サーバ** (独自) を別途立て、そこで受けた event を Claude Desktop に push するか、MCP 側から file/DB を読みに行く構成にする。webhook 配信経路は MCP を一切経由しない。

---

## 8. コストモデル + 暴走ガード

- **通常コスト:** 1 配信あたり outbound egress + CPU 数 ms。Fly.io nrt の outbound は 160 GB/月無料枠内で 10K 配信/日 × 1KB ≈ 10 MB/日 = 余裕。
- **retry 嵐リスク:** 顧客エンドポイント死亡時、queue が肥大する。
- **ガード:**
  - **Per-customer cap: 10,000 配信試行 / 日**。超過した subscription は自動 disable、`disabled_reason = "cost_cap"`。
  - 個別拡張は提供しない (完全セルフサーブ・個別契約なし方針)。
  - **Global kill switch:** `JPINTEL_WEBHOOK_GLOBAL_KILL_SWITCH=1` で全配信停止 (incident 用)。
- **Dead-letter overflow:** 1 subscription あたり dead-letter 100 件を超えたら強制 disable。

---

## 9. Observability

各配信で 1 行の structlog event を emit:

```json
{"event":"webhook_delivered","subscription_id":"sub_...","event_type":"program.created","customer_id_hash":"a8b9...","status":202,"attempt":1,"duration_ms":183,"ok":true}
```

`customer_id` は raw で出さず `HMAC-SHA256(customer_id, api_key_salt)` の先頭 8 文字 hex (`feedback.ip_hash` と同方針)。Grafana free tier で panel を 1 枚追加:

- `webhook_delivery_success_rate` (rolling 1h)
- `webhook_retry_depth` (attempts ≥ 2 の比率)
- `webhook_4xx_streak_top_5` (disable 予兆の subscription を可視化)

`docs/observability_dashboard.md` の "Infra signals" セクションに `I6` として追加予定。Alert (P2): success rate < 95% @ 1h。

---

## 10. Rollout phase

| 週 | 状態 |
|---|---|
| W5 (5/06-5/13) | 本設計書確定、API spec freeze、migration draft PR レビュー |
| W6 (5/13-5/20) | feature branch `feat/outbound-webhooks` 実装、test 40 本、staging で合成負荷テスト |
| W7 (5/20-5/27) | **beta**: 手選 5 顧客 (Paid 枠)、`webhook_subscriptions.disabled_at` のデフォルトは `"beta-opted-in: 2026-05-20T..."` (sentinel 文字列で beta 参加者を弁別) |
| W8 (5/27-6/03) | **GA**: Paid 全顧客開放。E1-E6 すべて配信可 |

beta 判定基準: delivery success rate ≥ 97% / p95 配信遅延 ≤ 3s / dead-letter 累計 ≤ 10。

---

## 11. Monetization + 顧客保護

**Tier 別 event アクセス:**

| Tier | 許容 events | 備考 |
|---|---|---|
| Free | ー | webhook 機能自体 off (SSRF リスクに対して revenue なし) |
| Paid | E1-E6 全種 | 使った分 (配信試行数 × ¥3 が pull req と同じく metered 課金対象となる将来拡張は別 issue) |

**顧客保護:**

- **Opt-out:** `site/dashboard.html` に "webhook 全停止" トグル。ON → `UPDATE webhook_subscriptions SET disabled_at = now(), disabled_reason = 'user_opt_out' WHERE customer_id = ?`。
- **プライバシー:** program event (E1-E5) は `customer_id` を payload に含めない。quota event (E6) のみ当該顧客の `customer_id` を含むが、それは当該顧客自身宛なので自己情報。
- **APPI 28 条 (越境移転):** webhook 配信先 URL は顧客管理 (AWS us-east 等海外可)。この時点で **顧客がデータ管理者**になる — ToS に下記を明記:
  - 「顧客が指定した URL は顧客の管理下にあり、配信後のデータ取扱責任は顧客に帰属する」
  - 「海外リージョンに配信先を置く場合、APPI 28 条に基づく第三国移転の告知義務は顧客が負う」
- **データ最小化:** payload は必要最小フィールドのみ、個人識別可能な enriched_json の下位 key は含めない。

---

## 12. 非対応事項 (やらないこと)

- **暗号化 payload:** HMAC 署名のみ、payload は平文 JSON。顧客がエンドツーエンド暗号化したければ独自に層を被せる。
- **順序保証:** `program.created` → `program.updated` の順に届く保証なし (at-least-once + 非同期 queue)。顧客は `created_at` と `current_checksum` で並べ替える。
- **金銭・決済通知 push:** 「補助金採択金額が確定した」「支払日が来た」等の **金融ルーティング系通知は実装しない** — 資金決済法/前払式支払手段/為替取引業に触れる可能性。採択データは「情報配信」として扱い、金額推移の予測や支払スケジュール通知は出さない。

---

## 13. 実装リスクレビュー

設計段階で列挙した blocker 級:

- **SSRF 防御の TOCTOU:** subscribe 時の DNS 検証と実配信時 IP が乖離するケース。実配信側で必ず resolve 後 IP を socket-level で再検証する (urllib3 の `socket_options` フックか httpx の custom transport を使う)。この防御が漏れると **内部 6PN (`fdaa::/16`) への私的攻撃経路**になる。
- **Retry storm 乗算:** 10K 顧客が死んだエンドポイントを登録すると 10K × 5 retry = 50K attempt/event。global cap と per-customer cap で抑える。
- **Queue 耐障害性:** 現 Fly.io 単機 single-writer SQLite + in-process worker。プロセス再起動で in-flight delivery が pending に戻る必要あり → `webhook_deliveries.status = "pending"` で再起動時に pickup。重複送信は顧客の idempotency で吸収。

---

## 14. 既存規約との整合

- **HMAC 方式** は Stripe webhook 形式 (`t=...,v1=...`) に合わせた (`src/jpintel_mcp/api/billing.py` が受け側、本書は送り側で同方式を鏡像化)。
- **error body shape** は `{"detail": "..."}` で統一 (`api/programs.py::raise HTTPException` と同じ)。
- **ENV var 命名** は `JPINTEL_*` / `STRIPE_*` 既存スタイル。
- **DB migration 命名** は `NNN_<topic>.sql` (001-007 の連番続き、008 は予約済と仮定し 009)。
- **Tier 名称** は `free` / `paid` の canonical (`pricing.md` と一致)。

---

*本書は仕様書である。実装は `feat/outbound-webhooks` ブランチで行い、merge には (a) test coverage ≥ 80% on `src/jpintel_mcp/api/webhooks*`、(b) `scripts/ssrf_probe.py` による 20 件の attack case pass、(c) `docs/api-reference.md#webhooks` 追記、の 3 条件を要求する。*
