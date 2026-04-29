# 税務会計AI — Go / No-Go Gate (operator-only)

> **operator-only**: launch 直前 (T-1d) の Go / No-Go 判定 gate。`mkdocs.yml::exclude_docs` で公開除外。
>
> Launch day: **2026-05-06 (水) JST** · 判定実施日: **2026-05-05 (月) T-1d 21:00 JST 前後**
>
> Owner: **梅田茂利** / info@bookyou.net / Bookyou株式会社 (T8010001213708)

最終更新: 2026-04-25 · 関連 doc: `launch_checklist.md` (時系列), `rollback_runbook.md` (障害時), `analysis_wave18/audit_full/00_smart_merge_plan.md::§6` (5 layer × 5 項目 origin)

---

## 0. このドキュメントの使い方

T-1d (2026-05-05) の終わり頃に 5 layer × 5 項目 = **25 項目** を 1 つずつ手で `[x]` に flip する。
各項目は **PASS / FAIL** + **critical / non-critical** の 2 軸。判定基準は §7 abort criteria。

判定は紙 (or markdown) と `flyctl status` / `curl` / `sqlite3` 等の **客観出力** で行う。記憶や推測で PASS にしない (`feedback_validate_before_apply`)。

各項目 ≪ ≫ で囲んだ部分が **客観 verify コマンド** (or 該当ファイル / surface)。

---

## L0 Storage layer (4 項目)

> `data/jpintel.db` (188 MB) + `autonomath.db` (8.29 GB) の整合性。launch 直前に整合崩れ → 復旧不能リスク。

### 1. integrity (critical)

- [ ] PASS / [ ] FAIL
- ≪`sqlite3 data/jpintel.db "PRAGMA integrity_check;"` → "ok"≫
- ≪`sqlite3 autonomath.db "PRAGMA integrity_check;"` → "ok"≫
- 観察値: __

### 2. FK 0 (critical)

- [ ] PASS / [ ] FAIL
- ≪`sqlite3 data/jpintel.db "PRAGMA foreign_key_check;"` → 出力 0 行≫
- 観察値 (出力行数): __

### 3. 3 indexes (non-critical)

- [ ] PASS / [ ] FAIL
- ≪`idx_programs_tier_excluded` / `idx_programs_source_url` / `idx_programs_updated_at` 全て存在≫
- 確認: `sqlite3 data/jpintel.db ".indexes programs"` で 3 件確認

### 4. cache schema (non-critical)

- [ ] PASS / [ ] FAIL
- ≪`response_cache` table 存在 + 期限切れ row が cron で削除されている≫
- 確認: `sqlite3 data/jpintel.db ".schema response_cache"` で schema 表示

**L0 Storage 小計**: __ / 4

---

## L1+L2 Tools layer (5 項目)

> MCP tools + REST `/v1/am/*` + Stripe + envelope v2 + 5 critical invariants Tier 1。

### 5. tools/list ≥ 55 (critical)

- [ ] PASS / [ ] FAIL
- ≪`autonomath-mcp` 起動 → MCP `tools/list` で 89 tool 出力 (39 jpintel + 50 autonomath)≫
- 数値 drift 0 (`mcp-tools.md` / `pyproject.toml` / `server.json` 全部 89)
- 観察値: __

### 6. /v1/am/* 16 endpoint (critical)

- [ ] PASS / [ ] FAIL
- ≪`docs/openapi/v1.json` で `/v1/am/` prefix の path が 16 件≫
- ≪`autonomath.py` router が `main.py` で `app.include_router(...)` 済≫
- 確認: `jq '.paths | keys[] | select(startswith("/v1/am/"))' docs/openapi/v1.json | wc -l` → 16
- 観察値: __

### 7. Stripe pass (critical)

- [ ] PASS / [ ] FAIL
- ≪`scripts/stripe_smoke_e2e.py` PASS (live mode、¥3 charge → refund)≫
- ≪Stripe webhook endpoint が `Receiving events` 状態≫
- 観察値 (e2e 時間): __ s

### 8. envelope v2 wired (non-critical)

- [ ] PASS / [ ] FAIL
- ≪全 tool response が `{ data, meta: { token_estimate, confidence, source_attribution, cache_hint, request_id } }` 構造≫
- 確認: 任意 1 tool を curl で実行し `meta.token_estimate` 等 4 fields の存在を verify

### 9. 5 critical invariants Tier 1 active (critical)

- [ ] PASS / [ ] FAIL
- ≪INV-04 (¥3/req metering) / INV-21 (data hygiene aggregator block) / INV-22 (10 keyword honesty block) / INV-23 (claim_strength gating) / INV-25 (PII redaction) が middleware で active≫
- 確認: `src/jpintel_mcp/api/middleware/` の wiring を grep + INV-22 keyword で実 request → block 確認

**L1+L2 Tools 小計**: __ / 5

---

## L0 Infra layer (7 項目)

> Fly + R2 + Stripe + aggregator + SLO + DR.

### 10. flyctl healthy (critical)

- [ ] PASS / [ ] FAIL
- ≪`flyctl status --app autonomath-api` で全 machine が `started`≫
- ≪`flyctl checks list --app autonomath-api` で全 health check `passing`≫
- 観察値 (machine 数): __

### 11. 20GB 残容量 (non-critical)

- [ ] PASS / [ ] FAIL
- ≪`flyctl volumes list --app autonomath-api` で残 ≥ 20 GB≫
- ≪autonomath.db 8.29 GB + jpintel.db 188 MB + R2 backup queue ≤ 5 GB の余地≫
- 観察値: __ GB

### 12. Stripe ¥3 e2e (critical)

- [ ] PASS / [ ] FAIL
- ≪live mode で ¥3 charge → refund が 1 cycle 完走≫
- 確認: `scripts/stripe_smoke_e2e.py` 出力に `succeeded` 2 件 + `refunded` 1 件
- 観察値 (charge ID prefix): __

### 13. R2 SHA (critical)

- [ ] PASS / [ ] FAIL
- ≪直近 7 日間の R2 nightly snapshot SHA256 sidecar が verify pass≫
- 確認: `aws s3 ls s3://autonomath-backups/jpintel.db/` の最新 7 件 + `.sha256` 一致
- 観察値 (verify pass 件数): __ / 7

### 14. aggregator startup pass (critical)

- [ ] PASS / [ ] FAIL
- ≪起動時 health check で `programs.source_url` に `noukaweb.jp` `hojyokin-portal.jp` `biz.stayway.jp` 等 banned aggregator が 0 件≫
- 確認: `sqlite3 data/jpintel.db "SELECT COUNT(*) FROM programs WHERE source_url LIKE '%noukaweb%' OR source_url LIKE '%hojyokin-portal%' OR source_url LIKE '%biz.stayway%';"` → 0
- 観察値: __

### 15. SLO doc + Sentry rules + cost alert (non-critical)

- [ ] PASS / [ ] FAIL
- ≪`docs/sla.md` (公開 99.0%) + `docs/observability.md` (内部 99.5%) 整合≫
- ≪Sentry alert rules 4 件 (Severity 1/2/3/4) 設定済≫
- ≪`scripts/cron/stripe_cost_alert.py` で 80%/100%/150% 警告設定済≫

### 16. DR formal 10 scenarios documented (critical)

- [ ] PASS / [ ] FAIL
- ≪`docs/disaster_recovery.md` で 10 シナリオ全て RPO / RTO + 手順 + post-mortem template が埋まっている≫
- ≪`docs/_internal/incident_runbook.md` から各シナリオへの cross-link 健在≫

**L0 Infra 小計**: __ / 7

---

## Compliance layer (4 項目)

> 公開コンプライアンス doc + 特商法 + secret + 規制語 block + 3 invariants。

### 17. docs.zeimu-kaikei.ai/compliance/* (critical)

- [ ] PASS / [ ] FAIL
- ≪`/docs/compliance/INDEX.md` + privacy_policy / terms_of_service / landing_disclaimer / data_governance / data_subject_rights / electronic_bookkeeping 6 ページ live≫
- 確認: `curl -s https://zeimu-kaikei.ai/docs/compliance/ | grep -c "href=\"./"` で >= 6

### 18. tokushoho (critical)

- [ ] PASS / [ ] FAIL
- ≪`https://zeimu-kaikei.ai/tokushoho.html` (or `/legal/tokushoho`) で特商法 8 必須項目 + 法人番号 T8010001213708 表示≫
- 確認: 法人番号 / 代表者名 / 登記住所 / 役務内容 / 価格 / 支払時期 / 引渡時期 / 返金条件 8 項目 grep PASS

### 19. pepper (critical)

- [ ] PASS / [ ] FAIL
- ≪`flyctl secrets list --app autonomath-api` に `API_KEY_PEPPER` 設定済 + 値が 1Password と整合≫
- 確認: `flyctl secrets list` 出力で row 存在

### 20. honesty + claim_strength + 10 keyword block (critical)

- [ ] PASS / [ ] FAIL
- ≪response 内に `claim_strength` field + 10 規制語 (税理士相当 / 弁護士相当 / 必ず受給 / 100% / 確定 等) が `[REDACTED]` 化≫
- 確認: 任意 search query で `100%` を含むレコードを 1 件用意し、API response が `[REDACTED]` 出力されることを確認

### 21. INV-21/22/23 wired (critical)

- [ ] PASS / [ ] FAIL
- ≪`src/jpintel_mcp/api/middleware/invariants.py` (or 同等) で INV-21 (aggregator) + INV-22 (keyword) + INV-23 (claim) middleware が `app.add_middleware(...)` 済≫
- 確認: `grep -r "INV-21\|INV-22\|INV-23" src/jpintel_mcp/api/` で 3 件以上 hit

**Compliance 小計**: __ / 4

注: §4 の「INV-21/22/23 wired」が §21 に独立しているため Compliance layer は **5 項目相当 (17/18/19/20/21)** だが、project task 表上は 5 項目で集計する。本 doc では 21 までで Compliance 5 項目を構成。

---

## Public layer (5 項目)

> 5 manifest 統一 + OpenAPI 70+ paths + 5 surface positioning + 12 registry + per-tool precision + pricing 月額 calculator + 数値 drift 0 + handoff doc。

### 22. 5 manifest 全 55 統一 (non-critical)

- [ ] PASS / [ ] FAIL
- ≪`pyproject.toml` (keywords) + `server.json` (tools count) + `.well-known/mcp.json` + GitHub topics + PyPI metadata の 5 surface で tools 数 = 55 統一≫
- 確認: 5 surface を順に grep し全件 55 を verify

### 23. OpenAPI 70+ paths (non-critical)

- [ ] PASS / [ ] FAIL
- ≪`jq '.paths | length' docs/openapi/v1.json` ≥ 70≫
- 観察値: __

### 24. 5 surface positioning + GitHub public + 12 registry (non-critical)

- [ ] PASS / [ ] FAIL
- ≪Developer / 税理士 / SMB / VC / GovTech 5 cohort 別 positioning copy が `blog/2026-05-5_audience_pitch.md` で揃っている≫
- ≪GitHub repo public 状態 + `topics` 7 個設定済≫
- ≪12 distribution registry へ submission 計画 (smithery / glama / mcp.so / Anthropic / npm proxy / PyPI / GitHub / Cloudflare Pages / openapi.tools / mcp-registry / X / LinkedIn) が `registries.md` に列挙≫

### 25. per-tool precision + pricing 月額 calculator + 数値 drift 0 + handoff doc deployed (critical)

- [ ] PASS / [ ] FAIL
- ≪`per_tool_precision.md` table が 89 tool 全て埋まっている≫
- ≪`pricing.md` の月額 calculator が 50 / 1k / 10k req 表示 + ¥3/req 完全従量明示≫
- ≪7 surface (index / getting-started / faq / pricing / mcp-tools / README / press_kit) で数値 grep diff = 0≫
- ≪`solo_ops_handoff.md` が `_internal/` で deploy 済 + 1Password 経由のリンク指示が埋まっている≫

**Public 小計**: __ / 4

注: Public layer は task 表上は 5 項目だが、本 doc では 22-25 の 4 entry に集約 (entry 25 が複合 4-sub-item)。総項目数は **5 layer × 5 項目 = 25 sub-item** を維持。

---

## 6. 集計

| Layer | 項目数 | PASS 数 | critical fail |
|---|---|---|---|
| L0 Storage | 4 | __ | __ |
| L1+L2 Tools | 5 | __ | __ |
| L0 Infra | 7 | __ | __ |
| Compliance | 5 | __ | __ |
| Public | 4 | __ | __ |
| **合計** | **25** | __ | __ |

---

## 7. Abort criteria (Go / No-Go 判定)

```
critical fail = 0 件         → Go (確実 launch)
critical fail = 1-2 件       → operator 判断 Go (理由を記録欄に書く)
critical fail >= 3 件        → No-Go (launch 延期、T+7d リスケジュール)
```

`launch_checklist.md::T-1d` の中間確認 = 本 gate の判定結果と一致させる。

### Critical 項目 (16 件、§番号)

§1 (integrity) / §2 (FK 0) / §5 (tools/list ≥ 55) / §6 (/v1/am/* 16) / §7 (Stripe pass) / §9 (5 critical invariants) / §10 (flyctl healthy) / §12 (Stripe ¥3 e2e) / §13 (R2 SHA) / §14 (aggregator startup) / §16 (DR 10 scenarios) / §17 (compliance/* live) / §18 (tokushoho) / §19 (pepper) / §20 (10 keyword block) / §21 (INV-21/22/23 wired) / §25 (per-tool + pricing + drift + handoff)

= 17 critical entries (§1/§2/§5/§6/§7/§9/§10/§12/§13/§14/§16/§17/§18/§19/§20/§21/§25)。Public layer の §25 は複合 4-sub だが、4 sub のうち 2+ fail なら critical fail カウント +1 として扱う。

### Non-critical 項目 (8 件)

§3 (3 indexes) / §4 (cache schema) / §8 (envelope v2 wired) / §11 (20GB) / §15 (SLO doc + Sentry rules) / §22 (5 manifest 統一) / §23 (OpenAPI 70+) / §24 (5 surface positioning + GitHub + 12 registry)

非 critical は **fail 5 件以上で operator review** だが launch を止めない。

---

## 8. 判定記録欄 (T-1d 21:00 JST 前後で書く)

```
判定実施日時: 2026-05-05 (月) __:__ JST
判定者: 梅田茂利 (operator 単独)

L0 Storage      : PASS __ / 4   critical fail __ 件
L1+L2 Tools     : PASS __ / 5   critical fail __ 件
L0 Infra        : PASS __ / 7   critical fail __ 件
Compliance      : PASS __ / 5   critical fail __ 件
Public          : PASS __ / 4   critical fail __ 件
合計             : PASS __ / 25 critical fail __ 件

判定: Go / No-Go (operator 判断)
理由 (1-3 行):
__________________________________________________
__________________________________________________
__________________________________________________

T+0 投稿開始時刻: 09:00 JST (X)
T+0 中止条件 (T-1d → T+0 までに新規発生時): __________________________
```

---

## 9. 関連 doc

- `launch_checklist.md` — 11 日前から 30 日後までの時系列 task list
- `rollback_runbook.md` — launch 後 30 分の監視 + rollback 手順
- `disaster_recovery.md` — 10 scenarios formal RPO / RTO + post-mortem template
- `solo_ops_handoff.md` — Scenario 10 successor doc (本 gate と独立した 1-day 引継ぎ書)
- `analysis_wave18/audit_full/00_smart_merge_plan.md::§6` — 本 gate の 5 layer × 5 項目 定義 origin

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
