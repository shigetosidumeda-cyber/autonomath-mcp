# R8 Fly Deploy Readiness Audit — 2026-05-07

> 内部仮説 framing: "deploy 直前の readiness check (fly.toml syntax / Dockerfile build / entrypoint.sh syntax / secret list 完備性) は production_deploy_go_gate 4/5 PASS とは別軸 verify 済か?" を 4 surface read-only audit で検証した結果。
>
> Scope: read-only (no rm/mv/edit). LLM 0. jpcite v0.3.4 文脈。
>
> Verdict (上位サマリ): **READY (deploy precondition green)**. fly.toml TOML / entrypoint.sh bash / Dockerfile multi-stage 構造 / SECRETS_REGISTRY §0.1 boot gate がすべて整合。観測された不整合は 4 件あるが いずれも **non-blocking** で historical drift か informational。

---

## 1. fly.toml audit

| Field | Expected | Actual | Verdict |
|---|---|---|---|
| `app` | `autonomath-api` | `autonomath-api` | OK |
| `primary_region` | `nrt` | `nrt` | OK |
| `http_service.internal_port` | `8080` | `8080` | OK |
| `[[vm]]` cpu_kind/cpus/memory_mb | shared / 2 / 4096 | shared / 2 / 4096 | OK (Wave-23 capacity audit と一致) |
| `[deploy] release_command` | commented out (期待通り) | コメントアウト (`# release_command = "python scripts/migrate.py"`) | OK |
| `[deploy] strategy` | `immediate` | `immediate` | OK |
| `[[mounts]]` | `/data` 40gb | source=`jpintel_data`, dest=`/data`, initial_size=`40gb` | OK |
| Health check | `/healthz` 30s/10s/60s | path=`/healthz`, interval=30s, timeout=10s, grace_period=`60s` | OK ※後述 §5 |
| `[metrics]` | `/metrics:9091` | port=9091, path=`/metrics` | OK |
| `[http_service.concurrency]` | requests soft=50/hard=100 | requests soft=50/hard=100 | OK |
| Auto-stop / min_machines | suspend / 1 | `suspend` / 1 | OK |
| `[env]` keys | 8 baseline | `JPINTEL_ENV=prod`, `JPINTEL_LOG_LEVEL=INFO`, `JPINTEL_LOG_FORMAT=json`, `JPINTEL_DB_PATH=/data/jpintel.db`, `AUTONOMATH_DB_PATH=/data/autonomath.db`, `AUTONOMATH_ENABLED=true`, `AUTONOMATH_APPI_ENABLED=0`, `SENTRY_ENVIRONMENT=production` | OK |

**TOML syntax**: `tomllib.load(open('fly.toml','rb'))` → no parse error. fields 完全 dump ☑。

**Observation 1.1 (informational)**: `[env] AUTONOMATH_APPI_ENABLED=0` は production boot gate (`main.py::_assert_production_secrets`) が `CLOUDFLARE_TURNSTILE_SECRET` を required から除外する条件を成立させる。この値で意図通り。

**Observation 1.2 (drift, non-blocking)**: Dockerfile 内コメントには "grace_period 120s covers R2 download on first boot" とあるが、fly.toml の実値は `60s` (Fly 側の sigsoft cap = 60s)。Drift は documentation 側のみ、TOML 値は spec 通り。「巨大 SQLite に boot 時 quick_check 禁止」memory が示す `grace 60s 制約` を踏襲しており entrypoint.sh も background bootstrap で一貫。

---

## 2. Dockerfile audit

| Field | Expected | Actual | Verdict |
|---|---|---|---|
| Base image | python 3.12 | `python:3.12-slim-bookworm` (builder + runtime, multi-stage) | OK |
| Platform pin | linux/amd64 | `--platform=linux/amd64` 両 stage | OK |
| WORKDIR | `/app` | `/app` (runtime) | OK |
| COPY ordering | system deps → python deps → model bake → app code | 観察通り (44-49→61-66→110-111) | OK |
| ENTRYPOINT / CMD | entrypoint.sh + uvicorn | `ENTRYPOINT ["/app/entrypoint.sh"]` + `CMD ["uvicorn", "jpintel_mcp.api.main:app", ...]` | OK |
| EXPOSE | 8080 | `EXPOSE 8080` (line 145) | OK |
| sqlite-vec native | `/opt/vec0.so` | builder stage extracts to `/opt/vec0.so`, runtime sets `AUTONOMATH_VEC0_PATH=/opt/vec0.so` | OK |
| baked seed | `/seed/jpintel.db` + `/seed/unified_registry.json` + `/seed/autonomath_static/` | 全 3 個 COPY、`DATA_SEED_VERSION=2026-04-26-v4` env | OK |
| HF offline lock | `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` | 設定済 (line 104-105) | OK |

**Syntax verify**: hadolint / docker linter 不在 (`which hadolint` → not found)。`# syntax=docker/dockerfile:1.6` directive は 正しく header に存在。multi-stage `FROM ... AS builder` / `FROM ... AS runtime` 構造、`COPY --from=builder` 参照, `LABEL` / `ENV` / `RUN` 全て standard syntax。手動 grep で構文崩れなし。

**Observation 2.1 (informational)**: `LABEL org.opencontainers.image.source` は `github.com/shigetosidumeda-cyber/jpintel-mcp` を指している (TODO コメントで AutonoMath org 取得後に切替予告)。jpcite rename 完了 (2026-04-30) と整合させて将来 update 候補だが build には影響しない。

---

## 3. entrypoint.sh audit (起動 logic)

| Stage | Expected | Actual | Verdict |
|---|---|---|---|
| `set -euo pipefail` | 必須 | line 11 | OK |
| §1 /data dir ensure | `mkdir -p /data` + Fly mount check | line 22-26 | OK |
| §1.5 seed sync | jpintel.db / unified_registry.json `DATA_SEED_VERSION` gate | live healthy DB は preserve (line 56-78), 健康 NG なら force overwrite (line 80-119) | OK |
| §1.6 autonomath_static seed | MANIFEST.md absent → copy | line 140-149 | OK |
| §2 R2 bootstrap (autonomath.db) | missing or SHA mismatch → background download | `AUTONOMATH_BOOTSTRAP_MODE=background` default、 missing 時 fork (line 324-335) で /v1/am/* は 503 fallback | OK ※ grace 60s と整合 |
| §3 jpintel.db migrate.py | idempotent `python scripts/migrate.py` | line 348-361 (autonomath は **対象外**) | OK |
| §4 autonomath self-heal migrations | manifest mode default、 `target_db: autonomath` filter, `_rollback.sql` 除外, `boot_time: manual` 除外, schema_migrations bookkeeping | line 433-574, manifest が空ならゼロ apply | OK |
| §4 autonomath schema_guard | `--drop-empty-cross-pollution` 付き、 `AUTONOMATH_ENABLED=true` 時 fail-on-bad | line 575-587 | OK |
| §5 exec CMD | `exec "$@"` | line 598 | OK |

**Syntax verify**: `bash -n /Users/shigetoumeda/jpcite/entrypoint.sh` → exit 0 (`syntax OK`). shellcheck 不在 (`which shellcheck` → not found)。

**quick_check skip 確認 (memory: "巨大 SQLite に boot 時 quick_check 禁止")**:
- 9.3 GB autonomath.db については §4 で integrity check は走るが **trusted_stamp_matches (or sha_stamp_matches) で skip path あり** (line 375-381)。fresh boot 以外で 15+ 分 hang を回避できる。
- `release_command` は fly.toml で commented out (Fly grace 60s 超過防止)。fly.toml のコメントブロック (line 19-31) に経緯記載済。
- Health check は `/healthz` のみ (autonomath deep check は外している、fly.toml line 65-67 に明記)。

**Observation 3.1 (informational)**: `AUTONOMATH_BOOT_MIGRATION_MODE` default = `manifest`、 `autonomath_boot_manifest.txt` は **空** (header コメントのみ)。これにより boot 時 autonomath migration は **0 件 apply**。drift と捉えるかは方針次第だが、CLAUDE.md§"Common gotchas" は "auto-discover" 表現を使っており **微小な doc drift** が認められる (manifest mode に切替された経緯はリポジトリ内に記録あり)。実装側が安全側に倒した形で deploy 中に新規 migration を勝手に走らせない。**Audit 上は安全方向、historical doc 側だけ更新候補。**

---

## 4. Secret list 完備性 (SECRETS_REGISTRY §0.1)

production boot gate (`_assert_production_secrets`) で **必須** 判定される secret:

| Secret | Required when | Fly snapshot (2026-05-05) | Verdict |
|---|---|---|---|
| `API_KEY_SALT` | production 常時 (32+ chars, placeholder NG) | Deployed | OK |
| `AUDIT_SEAL_SECRET` または `JPINTEL_AUDIT_SEAL_KEYS` | production 常時 (どちらか 1 つ) | `AUDIT_SEAL_SECRET` Deployed (legacy single-key fallback) | OK |
| `STRIPE_SECRET_KEY` | production 常時 | Deployed | OK |
| `STRIPE_WEBHOOK_SECRET` | production 常時 | Deployed | OK |
| `CLOUDFLARE_TURNSTILE_SECRET` | `AUTONOMATH_APPI_ENABLED ≠ 0/false/False` 時 必須 | **未投入** だが fly.toml で `AUTONOMATH_APPI_ENABLED=0` → 除外条件成立 | OK (条件付 PASS) |

**追加 (deploy precondition ではないが site 起動に必要):**

| Secret | Status | 備考 |
|---|---|---|
| `STRIPE_BILLING_PORTAL_CONFIG_ID` / `STRIPE_PRICE_PER_REQUEST` / `STRIPE_TAX_ENABLED` | Deployed | 課金 |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT` / `R2_BUCKET` | Deployed | DB bootstrap |
| `AUTONOMATH_DB_URL` / `AUTONOMATH_DB_SHA256` / `AUTONOMATH_API_HASH_PEPPER` | Deployed | autonomath snapshot |
| `JPINTEL_CORS_ORIGINS` | Deployed | "Common gotchas" — apex+www 含む allowlist 要 |
| `JPINTEL_ENV` | Deployed | =production |
| `ADMIN_API_KEY` / `RATE_LIMIT_FREE_PER_DAY` / `INVOICE_FOOTER_JA` / `INVOICE_REGISTRATION_NUMBER` | Deployed | ops |

**conditional / live-only:**

| Secret | Status | 備考 |
|---|---|---|
| `GBIZINFO_API_TOKEN` | core deploy precondition では **ない** (live gBiz ingest 有効時のみ) | OK to defer |
| `SENDGRID_API_KEY` (or POSTMARK_API_TOKEN) | optional unless saved_searches/KPI digest を有効化 | non-blocking |
| `JPINTEL_AUDIT_SEAL_KEYS` | rotation list (legacy fallback で boot gate は満たす) | optional today |
| Sentry DSN / Telegram bot / IndexNow / CF analytics | optional (workflow fail-open 設計) | non-blocking |

**Observation 4.1**: `fly secrets list -a autonomath-api` snapshot は 2026-05-05 時点 20 個 Deployed。本 audit では **gh / fly コマンド未実行** (read-only filesystem audit)。secret rotation 直後に再確認したい場合は `bash scripts/ops/discover_secrets.sh` 推奨 (registry §5)。

---

## 5. 不整合 (4 件、 すべて non-blocking)

| # | Severity | 観測 | 影響 | 推奨 |
|---|---|---|---|---|
| 1 | informational | Dockerfile コメント "grace_period 120s" vs fly.toml `grace_period=60s` の **doc drift** | build / boot に影響なし、Fly 側の cap = 60s | Dockerfile コメント update (将来)|
| 2 | informational | LABEL `image.source` が `shigetosidumeda-cyber/jpintel-mcp` (TODO 既出) | container metadata のみ | jpcite org 取得後に switch (既知 TODO)|
| 3 | informational | CLAUDE.md "Common gotchas" は autonomath migration を "auto-discover" と表現するが、 entrypoint.sh は `MODE=manifest` default で **manifest 空** = boot 時 migration 0 件 apply。安全側 | 仕様変更ではなく defense-in-depth | doc 微更新候補|
| 4 | conditional | `CLOUDFLARE_TURNSTILE_SECRET` 未投入 (registry §1 snapshot) | `AUTONOMATH_APPI_ENABLED=0` (fly.toml) の限り boot gate 対象外 | APPI intake 有効化時に Fly secret 投入が必要|

deploy 阻害は **0 件**。すべて documentation drift か conditional secret。

---

## 6. Final readiness verdict

- fly.toml: TOML parse OK, app/region/port/vm/release_command/health/mounts 期待値一致 → **READY**
- Dockerfile: multi-stage, python 3.12, COPY ordering 正、 entrypoint+CMD 正 → **READY**
- entrypoint.sh: `bash -n` PASS、 background R2 bootstrap、 quick_check skip path、 manifest-mode autonomath migration → **READY**
- secret list: production boot gate 5 必須 (API_KEY_SALT / AUDIT_SEAL_SECRET / STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET / CLOUDFLARE_TURNSTILE_SECRET-conditional) すべて充足条件成立 → **READY**

**Conclusion**: production_deploy_go_gate の 残 1 (operator interactive sign) と独立した readiness 軸 4/4 PASS。本 audit 単体で `fly deploy` を阻害する factor は検出されず。

---

*Generated by R8 Fly Deploy Readiness Audit, 2026-05-07. read-only, no destructive action. LLM 0.*
