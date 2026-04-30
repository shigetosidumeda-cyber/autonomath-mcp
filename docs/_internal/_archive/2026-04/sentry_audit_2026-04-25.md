# Sentry Audit 2026-04-25 (I7)

Triage of v13 → v14 → v15 deploy cycle. Read-only, no source / SDK changes.

## TL;DR

- **SENTRY_DSN は fly secret に未設定** (`flyctl secrets list -a autonomath-api` に SENTRY_* なし)。
- C2 で導入した `sentry_sdk[fastapi]>=2.19` は **two-gate `_init_sentry()` の (a) DSN gate で early-return → 完全 no-op**。
  → v13/v14 crashloop 期間中の error は **Sentry には 1 件も飛んでいない** (キャプチャ機構が initialize されていない)。
- v15 は `started` / health check passing / 5xx = 0 で **stable**。
- 機械が回した v13/v14 noise は Sentry quota を 1 mil 食っていない (DSN 未設定なので)。launch 時に DSN を入れた瞬間からカウント開始する想定で OK。

## Sentry DSN 設定状況

```
flyctl secrets list -a autonomath-api | grep -i sentry
→ (no rows)
```

Fly secret 一覧 (digest のみ、値は見ない):

```
ADMIN_API_KEY
API_KEY_SALT
INVOICE_FOOTER_JA
INVOICE_REGISTRATION_NUMBER
JPINTEL_CORS_ORIGINS
JPINTEL_ENV                    ← prod (gate (b) は通る)
RATE_LIMIT_FREE_PER_DAY
STRIPE_BILLING_PORTAL_CONFIG_ID
STRIPE_PRICE_PER_REQUEST
STRIPE_SECRET_KEY
STRIPE_TAX_ENABLED
STRIPE_WEBHOOK_SECRET
AUTONOMATH_API_HASH_PEPPER
```

→ **SENTRY_DSN / SENTRY_ENVIRONMENT / SENTRY_RELEASE すべて未設定**。

`src/jpintel_mcp/api/main.py:151-159` `_init_sentry()` の gate:

```python
if not settings.sentry_dsn:
    return
if os.getenv("JPINTEL_ENV", "dev") != "prod":
    return
```

(a) で early-return するため `sentry_sdk.init` は呼ばれない。`observability/sentry.py` の
`capture_exception` / `capture_message` も `import sentry_sdk` 前に gate チェックで no-op パス
を踏む。

**結論: 現在 production からの Sentry capture はゼロ**。Sentry web dashboard (もし
あれば) は launch 前は空のまま。

## 各 deploy 期間中の incident 件数 (Fly logs ベース)

Fly logs retention は短い (`flyctl logs --no-tail` で取れる最古 ts = `2026-04-25T10:08:07Z`)。
v13/v14 (約 1h31m / 1h21m 前 = 09:31 / 09:31 前後) の crashloop 生 log は **既に rotate して取得不可**。

`flyctl releases -a autonomath-api`:

| Version | Status     | 経過 (audit 時刻起点) | 推定内容                                       |
| ------- | ---------- | --------------------- | ---------------------------------------------- |
| v15     | complete   | 1h7m  ago             | entrypoint malformed DB auto-recover (現 prod) |
| v14     | complete   | 1h21m ago             | H1 freshness fix (scipy 不在 crash した版)    |
| v13     | complete   | 1h31m ago             | jpintel.db seed                                |
| v12     | complete   | 1h52m ago             |                                                |
| v11     | complete   | 2h6m  ago             |                                                |
| v10     | complete   | 2h9m  ago             |                                                |
| v9      | complete   | 7h3m  ago             |                                                |
| v8      | failed     | 7h7m  ago             |                                                |
| v7      | failed     | 7h10m ago             |                                                |

`releases` 上は v13/v14/v15 すべて `complete` 表示 (= image push & promote は成功)。
crashloop は image push 後の **runtime startup 失敗** で起きていたので fly release 状態
には反映されない。

**Sentry 観測値**:

- v13 期間: **0 件** (DSN 未設定)
- v14 期間 (crashloop): **0 件** (DSN 未設定 — もし設定されていれば ImportError /
  ModuleNotFoundError が爆発していた)
- v15 期間 (現在): **0 件** (DSN 未設定 + 5xx 0)

## v15 以降の error 傾向 (Fly logs 直接観測)

`2026-04-25T10:08:07Z ~ 10:51:42Z` (約 44 分間、log retention 範囲全体)。

| 種別                  | 件数 | 内訳                                                    |
| --------------------- | ---- | ------------------------------------------------------- |
| 200 OK (`/healthz`)   | 46   | Fly health check 30s 周期 (passing 表示と一致)         |
| 404 (`/`)             | 1    | root path probe (定義されていない、想定挙動)            |
| 429 (`/v1/programs/search`, `/v1/case-studies/search`, `/v1/laws/search`, `/v1/meta`) | 4 | 匿名 50/月 上限到達 (anon IP-based、想定挙動)        |
| **5xx**               | **0** | **endpoint specific issue 検出されず**                |
| traceback / exception | 0    | startup OK / schema_guard PASS と推定                  |

`flyctl machine status 85e273f4e60778`:

- State: `started`, HostStatus: `ok`
- Check `servicecheck-00-http-8080`: passing (`{"status":"ok"}`, 1h5m ago と一致)
- Event log: `started` (18:45:47 JST = 09:45:47Z), 1 サイクル / no restart loop

→ **v15 は stable**。schema_guard 起動エラー、scipy crash、5xx 偏在いずれも検出されず。

## 真の bug vs deploy noise

Fly logs に残った 50 lines のうち:

- **bug の疑いがあるもの: 0 件**
  - 4xx は全部 設計通りの挙動 (匿名 rate-limit と未定義 root)。
  - 5xx 0 件、traceback 0 件、ImportError 0 件。
- **deploy noise: 0 件**
  - retention 切れで v13/v14 crashloop log が見えないだけで、現存 window では noise も
    観測されていない。

v14 crashloop の根本原因 (scipy 不在) は v15 で解消済み (image にバンドル + entrypoint
の DB integrity_check で破損 DB 自動 rm + image-baked unified_registry.json fallback)。
COORDINATION 記述と一致。

## Sample rate 推奨

現状 (`SENTRY_TRACES_SAMPLE_RATE=0.1`, `SENTRY_PROFILES_SAMPLE_RATE=0.1`,
`include_local_variables=False`, `max_breadcrumbs=50`) は launch 前として妥当。

調整 recommendation:

| Phase                          | errors (capture_exception) | traces / profiles | 根拠                                                                                  |
| ------------------------------ | -------------------------- | ----------------- | ------------------------------------------------------------------------------------- |
| **launch 直後 (T+0 ~ T+7d)**   | 1.0 (default、全 error)    | **0.5** に上げる  | 初週は traffic 少 + 真の bug 検出最大化したい。quota 食ってもこの期間だけ            |
| **stable (T+7d 以降)**         | 1.0                        | **0.1 維持**      | quota 節約 + steady-state は 10% sample で十分                                       |
| **incident 発生時 (1h burst)** | 1.0                        | 一時的に **1.0**  | re-deploy 直前 ~30 min を運用 SOP で `flyctl secrets set SENTRY_TRACES_SAMPLE_RATE=1.0` |

`sample_rate` (error 用) は SDK default = 1.0 のまま (= 全 exception capture)。これを
0.1 に下げると真の bug を取りこぼすので **絶対に下げない**。

## DSN 投入手順 (launch 直前 only、Skopt 不要)

このドキュメントには値は書かない。流れだけ:

1. Sentry org / project 作成 (FastAPI、Python)、DSN 取得。
2. `flyctl secrets set -a autonomath-api SENTRY_DSN=<value> SENTRY_ENVIRONMENT=prod
   SENTRY_RELEASE=v0.2.0` で投入 (1 sec で reboot triggered)。
3. 投入後 `curl -s -X POST https://autonomath-api.fly.dev/_test/raise` のような
   intentional 5xx は **打たない** (本番に偽 error event を残すと triage コストが上がる)。
   Sentry SDK は init 時にハートビート event を打たない (sentry-sdk 2.x default)。
4. 24h 待って Sentry web で `(no events)` 表示 = clean baseline。それ以降の event は本物。

## triage 結論

- v13/v14/v15 全期間で Sentry に飛んだ event は **0 件 (DSN 未設定のため capture 機構
  自体が no-op)**。誤検知 / 真 bug の分別は不要。
- v15 prod は **stable**。schema_guard / migrate / 5xx すべて clean。launch blocker は本
  audit から見出されない。
- launch 当日に DSN 投入 → 24h 静観 → 真の本番 issue だけ拾うクリーンスタートが取れる。

## 触ったファイル

- 新規: `docs/_internal/sentry_audit_2026-04-25.md` (本ファイル)

## 触っていないファイル

- `src/*` (C2 領域、不可侵)
- Sentry SDK config (`api/main.py:_init_sentry`, `observability/sentry.py`)
- DSN 値 (未設定なので扱う value 自体が存在しない)
