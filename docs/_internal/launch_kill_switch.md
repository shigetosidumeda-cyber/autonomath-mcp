# Launch Kill-Switch Runbook

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

> **要約:** 単一 Fly.io Tokyo box + SQLite (file lock) に対する RPS spike を 5-30s 以内に止める三段階 lever。
>
> 1. Cloudflare WAF custom rule (5s, IP-precise)
> 2. Fly.io secret `KILL_SWITCH_GLOBAL` (~30s, app-wide 503)
> 3. Fly.io app suspend (~10s, last resort: static fallback only)

関連: `docs/_internal/launch_dday_matrix.md` (D-Day timeline) / `docs/_internal/incident_runbook.md` (general) / `cloudflare-rules.yaml` (edge defenses) / `src/jpintel_mcp/api/middleware/kill_switch.py` (impl).

---

## 1. Trigger conditions (any one fires the playbook)

operator は以下のいずれかが満たされた瞬間に **§2 lever 1** を即時投下する。判断は P0 — 確認会議は incident 後の post-mortem で。

| 条件 | window | source |
|------|--------|--------|
| **sustained > 50 RPS global** | ≥ 60s | Fly metrics dashboard / Cloudflare Analytics 5min view |
| **single IP > 5 RPS** | ≥ 30s | Cloudflare Security Events / Fly logs grep `fly-client-ip` |
| **/v1/programs/search p95 > 2000ms** | ≥ 60s | Sentry performance / Fly metrics → endpoint p95 |
| **Fly health check fail rate > 50%** | ≥ 60s | Fly dashboard → machine health |

これらは *or* 関係。1 つでも当てはまればトリガー成立。50 RPS は単機 SQLite が file-lock 競合で kappa 503 を出し始める閾値 (loadtest a7388 で実測)。

---

## 2. Kill-switch levers (escalation order)

### Lever 1 — Cloudflare WAF custom rule (TTL ~5s, IP-precise)

**いつ使う**: 1-3 個の悪性 IP / IP range が判別できているとき。最小破壊。

**前提 (launch 前に実施)**:
- Cloudflare dashboard → Security → WAF → Custom rules で **`autonomath-emergency-deny`** という名前の空ルールを LOG action で pre-create する。条件は空 (`(false)`) で OK。
- これで incident 時に IP を追記して action を BLOCK に切替えるだけで即時に効く (新規 rule 作成は伝播 30-60s かかるため pre-create 必須)。

**手順 (incident 中)**:
1. https://dash.cloudflare.com → 該当 zone → Security → WAF → Custom rules → `autonomath-emergency-deny` → Edit。
2. Expression に `(ip.src eq 1.2.3.4) or (ip.src in {5.6.7.0/24})` の形で被疑 IP を追加。
3. Action を **Block** に切替えて Save。伝播 < 5s。
4. Cloudflare Security Events で BLOCK count を確認、p95 が落ちるまで観測 5-10 分。
5. Status page を `warn` に更新 (§4)。

**ロールバック**: Action を LOG に戻す。Expression は incident ノートのため残してよい。

### Lever 2 — Fly.io secret toggle `KILL_SWITCH_GLOBAL` (~30s, app-wide 503)

**いつ使う**: 攻撃 IP が散発 / botnet / Cloudflare WAF を擦り抜けた / Lever 1 が 5 分で効果無し。アプリ全体を 503 に倒す。

**手順**:
1. ターミナルから `flyctl secrets set KILL_SWITCH_GLOBAL=1 KILL_SWITCH_REASON='<one line>' -a autonomath-api` を実行。
   - 例: `flyctl secrets set KILL_SWITCH_GLOBAL=1 KILL_SWITCH_REASON='ddos 1000rps from 5.6.7.0/24 sentry-12345' -a autonomath-api`
2. Fly がマシンを replace (~30s)。新マシンの env に `KILL_SWITCH_GLOBAL=1` が乗る。
3. **アプリ挙動**:
   - 全エンドポイント → 503 + `error.code = "service_unavailable"` + `details.retry_after = "see_status_page"`
   - **allowlist** (常時 200): `/healthz`, `/readyz`, `/v1/am/health/deep`, `/status`, `/status/`, `/robots.txt`
   - 各 503 hit は `audit_log` テーブルに `event_type='kill_switch_block'` で記録 (post-incident 集計用)。
4. 確認: `curl -sS https://api.autonomath.ai/v1/programs/search | jq '.error.code'` → `"service_unavailable"`。
5. Status page を `down` に更新 (§4)。
6. `GET /v1/admin/kill_switch_status` (X-API-Key=ADMIN_API_KEY) で `enabled: true, since_iso: "...", reason: "..."` を確認。

**ロールバック**: `flyctl secrets unset KILL_SWITCH_GLOBAL KILL_SWITCH_REASON -a autonomath-api`。マシン replace ~30s。

### Lever 3 — Fly.io app suspend (~10s, last resort)

**いつ使う**: Lever 2 が効かない / SQLite データ破損疑い / 緊急停止が必要。アプリ自体を停止する。

**手順**:
1. `flyctl apps suspend autonomath-api`。Fly が全マシン停止 ~10s。
2. **アプリ挙動**:
   - api.autonomath.ai は Fly 502 / unreachable
   - autonomath.ai (Cloudflare Pages) は静的に動き続ける — ランディング、tos, privacy, /status, /docs (mkdocs static) は配信継続
   - DNS: `api.autonomath.ai` を Cloudflare Pages の fallback バナーへ flip するなら `docs/_internal/fallback_plan.md` 参照
3. Status page を `down (fallback mode)` に更新 (§4)。

**ロールバック**: `flyctl apps resume autonomath-api`。マシン boot ~30-60s。

---

## 3. Decision matrix (Symptom × Severity → Lever)

| Symptom | Severity | Lever |
|---------|----------|-------|
| 単一 IP / 小数 IP の burst (Cloudflare で識別可) | low | **Lever 1** WAF block |
| 100+ IP からの分散 burst | medium | **Lever 2** KILL_SWITCH_GLOBAL |
| Lever 2 後も Fly machine が flap | high | **Lever 3** apps suspend |
| /v1/programs/search のみ遅い (他 OK) | low | **Lever 1** + per-IP-endpoint cap (既に in-app) |
| SQLite WAL 異常 / disk full | critical | **Lever 3** + DR runbook (`dr_backup_runbook.md`) |
| Stripe webhook 1 IP burst | benign | 何もしない (whitelist 済み、`rate_limit.py` の `_WHITELIST_PATHS`) |

---

## 4. Status page coordination

- **Always announce on https://autonomath.ai/status/ before un-killing.** これは brand 5-pillar (透明・誠実) の運用面の核。
- 編集対象: `site/status.html` の `state ok|warn|down` クラス + `Last updated` の `<code>` 内。
- Cloudflare Pages 自動 redeploy < 30s。
- 文言テンプレ:
  - `warn` (lever 1): "一部 IP からの異常リクエストを遮断中。サービス継続中、p95 は通常範囲内。"
  - `down` (lever 2): "本日 HH:MM JST より一時的にサービスを停止中。原因確認後、復旧次第ここで通知します。"
  - `down (fallback)` (lever 3): "API は停止中。本ページは Cloudflare Pages の fallback で配信されています。"

---

## 5. Recovery (reverse order)

1. **Status page を更新** ("復旧作業開始" 文言 → `warn`)。
2. **Lever 3 reverse** (suspend 解除): `flyctl apps resume autonomath-api`。
3. /healthz が 200 を返すまで待機 (~30-60s)。
4. **Lever 2 reverse**: `flyctl secrets unset KILL_SWITCH_GLOBAL KILL_SWITCH_REASON -a autonomath-api`。
5. `GET /v1/admin/kill_switch_status` で `enabled: false` を確認。
6. **Lever 1 reverse**: Cloudflare WAF custom rule の Action を LOG に戻す (Expression は監査ノート用に残してよい)。
7. **Smoke test**: `BASE_URL=https://autonomath.ai ./scripts/smoke_test.sh` を流して全 probe green を確認。
8. **Status page を `ok` に更新** (`Last updated` を現在時刻に)。
9. Post-mortem を `research/incidents/<YYYY-MM-DD>-<short-id>.md` に記録 (timeline / root cause / lever sequence / detection time / recovery time)。

---

## 6. Contacts

- **Cloudflare**: 24x7 サポート (Pro plan 以上)。チャット → https://dash.cloudflare.com → Support。
- **Fly.io**: コミュニティサポート (https://community.fly.io)。emergency 専用回線なし — community post + メール `support@fly.io`。
- **operator on-call**: 梅田茂利 1 名のみ (`info@bookyou.net`)。代替なし — incident は寝かせるか自力で消化。

---

## 7. Operational notes

- **`KILL_SWITCH_GLOBAL=1` を入れるたびに `KILL_SWITCH_REASON` も入れる**: post-incident で原因を辿れない事故を 0 にする。
- **3 lever 全部試して効かないとき**: DNS で api.autonomath.ai を `autonomath.ai/status` に CNAME リダイレクト。これは緊急時のみ。
- **Lever 1 の Cloudflare WAF rule pre-create は launch 前必須** (`launch_dday_matrix.md` checklist 参照)。後付け作成は伝播 30-60s かかり、incident 中の最初の 1 分が遅れる。
- audit log query で blocked traffic を集計する: `SELECT path, COUNT(*) FROM audit_log WHERE event_type='kill_switch_block' AND ts >= '<since>' GROUP BY path ORDER BY 2 DESC`.
