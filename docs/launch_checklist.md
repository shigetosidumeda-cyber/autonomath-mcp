# AutonoMath — Launch Checklist (operator-only)

> **operator-only**: launch 直前 11 日 → launch 当日 → 30 日後までの daily checklist。`mkdocs.yml::exclude_docs` で公開除外。
>
> Launch day: **2026-05-06 (水) JST** · 起算日: **2026-04-25 (今日 = T-11d)**
>
> Owner (全 task): **梅田茂利** / info@bookyou.net / Bookyou株式会社 (T8010001213708)

最終更新: 2026-04-25 · 関連 doc: `launch_announcement_calendar.md` (告知 surface), `go_no_go_gate.md` (判定基準), `rollback_runbook.md` (障害時)

---

## 0. 全体方針

このドキュメントは「launch 当日に何が green でないと撃たないか」「撃った後 30 日間どこを毎日見るか」を operator 1 人で運用できる形に **時系列 + check 欄 + 中間確認** で並べた最短経路。

- **基準時刻**: JST。海外 surface (HN / r/LocalLLaMA 等) は ET / UTC を併記する。
- **rehearsal**: T-1d で **production と同一手順** をリハーサル → 本番は手順紙どおり進めるだけにする。
- **abort criteria**: T-1d までに `go_no_go_gate.md` の critical 項目 ≥ 3 件 fail なら **launch 延期**。連絡経路は本人 → 自分のみ (zero-touch、`feedback_zero_touch_solo`)。
- **中間確認**: 各日付の末尾 "中間確認" を満たさないと翌日に進まない。check 欄は `[ ]` → `[x]` に flip する。
- **記録**: 各 task の完了時刻 + 観察値 (例: smoke の P95 latency) を本ファイル末尾の **記録欄** に追記する (誇張禁止、`feedback_no_fake_data`)。

---

## 毎日の wake-up routine (T-11d 〜 T+30d 共通)

朝起きてから launch 関連 task に着手する前に必ず通すミニ smoke。

```bash
# 1. ヘルス
curl -sI https://api.autonomath.ai/healthz
curl -sI https://autonomath.ai/

# 2. ツール数 (production)
curl -s https://api.autonomath.ai/meta | jq '.total_programs, .build_sha, .last_ingest_at'

# 3. Sentry 新規 issue (web UI 30 秒チェック)
#    bookyou / autonomath-api project → Issues → new (last 24h)

# 4. Stripe ダッシュボード (web UI 30 秒チェック)
#    Subscriptions: active 件数 / past_due 件数 / dispute 件数

# 5. 直近 24h の usage 集計 (T-1d 以降のみ)
flyctl ssh console -a autonomath-api -C \
  'sqlite3 /data/jpintel.db "SELECT date(ts), COUNT(*), SUM(yen) FROM request_log WHERE ts > datetime(\"now\",\"-24 hours\");"'
```

**所要**: 5 分。これで赤が出たら今日の launch task は止めて `rollback_runbook.md` に飛ぶ。

---

## T-11d (2026-04-25 金) — 今日: gate 1 (ベースライン確定)

**目的**: 5 layer × 5 項目 baseline 計測。残り blocker を確定し、T-7d までの実装計画に落とす。

### Tasks

- [ ] `go_no_go_gate.md` を全項目読み、現時点の PASS/FAIL を埋める (operator 自身による self-assessment)
- [ ] `flyctl status --app autonomath-api` で staging machine 健全性確認
- [ ] `sqlite3 data/jpintel.db "PRAGMA integrity_check;"` → "ok"
- [ ] `sqlite3 autonomath.db "PRAGMA integrity_check;"` → "ok"
- [ ] `.venv/bin/python scripts/export_openapi.py > docs/openapi/v1.json` で OpenAPI 再 export
- [ ] `mkdocs build --strict` PASS
- [ ] `ruff check src/ tests/ scripts/` PASS
- [ ] `.venv/bin/pytest -q` PASS (full suite)
- [ ] T-7d までの残 blocker を本ファイル末尾「記録欄」に列挙

### 中間確認 (T-11d 締め)

`go_no_go_gate.md` 5 layer 25 項目のうち PASS が **15+ / 25** に到達。

---

## T-10d (2026-04-26 土) — Storage layer 仕上げ

**目的**: L0 Storage の green 化を完了し、以降は触らない (frozen)。

### Tasks

- [ ] `programs` FK 違反 0 件確認: `sqlite3 data/jpintel.db "PRAGMA foreign_key_check;"`
- [ ] 3 indexes (`idx_programs_tier_excluded`, `idx_programs_source_url`, `idx_programs_updated_at`) `EXPLAIN QUERY PLAN` で利用確認
- [ ] cache schema (`response_cache` table) 存在確認 + TTL row 0 件
- [ ] autonomath.db `am_entities_fts` MATCH 動作確認 (任意キーワード 1 件で smoke)
- [ ] `cache_architecture.md` の数値が現状と一致 (drift 0)
- [ ] `data/jpintel.db.bak.*` `.wrangler/` `.venv/` が `.gitignore` に入っているか再確認

### 中間確認

L0 Storage 4 項目 (integrity / FK 0 / 3 indexes / cache schema) が **全て PASS**。以降 storage には触らない。

---

## T-9d (2026-04-27 日) — Tools layer + envelope v2

**目的**: L1+L2 (tools/list ≥ 66, /v1/am/* 16 endpoint, Stripe pass, envelope v2, 5 critical invariants core 5本) を green 化。

### Tasks

- [ ] `.venv/bin/autonomath-mcp` 起動 → `tools/list` で 72 tools 出力確認 (38 jpintel + 28 autonomath = 17 V1 + 4 V4 universal + 7 Phase A absorption)
- [ ] `/v1/am/*` 16 endpoint の OpenAPI export を確認 (まだ main.py で mount されていない場合は launch ブロッカーに昇格)
- [ ] envelope v2 (`token_estimate` + `confidence` + `source_attribution` + `cache_hint`) が全 tool に wired
- [ ] 5 critical invariants Tier 1 (INV-04 / INV-21 / INV-22 / INV-23 / INV-25) active 確認
- [ ] Stripe metered live mode の `STRIPE_PRICE_PER_REQUEST` 設定確認 (¥3 / req)
- [ ] `scripts/mcp_smoke.py` PASS

### 中間確認

L1+L2 5 項目が **全て PASS**。tools 数値が `mcp-tools.md` と drift 0。

---

## T-8d (2026-04-28 月) — Infra layer + DR formal

**目的**: Fly / R2 / Stripe e2e / SLO doc / DR 10 シナリオ formal 化。

### Tasks

- [ ] `flyctl status --app autonomath-api` healthy
- [ ] Fly volume 残容量 ≥ 20 GB (`flyctl volumes list --app autonomath-api`)
- [ ] `scripts/stripe_smoke_e2e.py` PASS (¥3 e2e charge → refund)
- [ ] R2 nightly snapshot SHA256 verify が直近 7 日分 green
- [ ] aggregator startup 検出 PASS (起動時に `noukaweb.jp` 等の banned source URL を `programs.source_url` に持つ row が 0 件)
- [ ] `docs/sla.md` (公開) と `observability.md` (内部) で SLO target が一致
- [ ] `disaster_recovery.md` の 10 シナリオ全てで RPO / RTO が埋まっていることを確認

### 中間確認

L0 Infra 7 項目が **全て PASS**。

---

## T-7d (2026-04-29 火) — Compliance layer + smoke test live

**目的**: docs.autonomath.ai/compliance/* / 特商法 / pepper / honesty + 10 keyword block / INV-21/22/23 wired。Production smoke 初回。

### Tasks

- [ ] `docs.autonomath.ai/compliance/` 配下 7 ページが live (privacy / ToS / disclaimer / governance / DSR / electronic_bookkeeping / INDEX)
- [ ] 特商法ページ (`site/tokushoho.html`) の 8 必須項目埋め済 + 法人番号 T8010001213708 表示
- [ ] `API_KEY_PEPPER` Fly secret 設定済 (`flyctl secrets list --app autonomath-api`)
- [ ] honesty + 10 keyword block (INV-22) regex が tax/medical/legal disclaimer 規制語をブロック
- [ ] INV-21 / INV-22 / INV-23 が `src/jpintel_mcp/api/middleware/` に wired
- [ ] **Production smoke 初回**: `BASE_URL=https://api.autonomath.ai ./scripts/smoke_test.sh` PASS

### 中間確認

Compliance 5 項目が全て PASS、production smoke が green。残 7 日で `go_no_go_gate.md` の **PASS が 22+ / 25** に到達。

---

## T-6d (2026-04-30 水) — Public surface

**目的**: 5 manifest 全 55 統一 / OpenAPI 70+ paths / 5 surface positioning / 12 registry / per-tool precision / pricing 月額 calculator / 数値 drift 0 / handoff doc deployed。

### Tasks

- [ ] `pyproject.toml` / `server.json` / `.well-known/mcp.json` / GitHub `topics` / PyPI `keywords` の 5 manifest で tools 数 = 55 統一
- [ ] OpenAPI export `docs/openapi/v1.json` の paths が 70+ (`jq '.paths | length' docs/openapi/v1.json`)
- [ ] 5 surface (developer / 税理士 / SMB / VC / GovTech) positioning copy が `docs/blog/2026-05-5_audience_pitch.md` に揃っている
- [ ] 12 distribution registry (smithery / glama / mcp.so / Anthropic / npm proxy / PyPI / GitHub / Cloudflare Pages / openapi.tools / mcp-registry / X / LinkedIn) submission 計画確認
- [ ] `per_tool_precision.md` table が 72 tool 全て埋まっている
- [ ] `pricing.md` の月額 calculator が 50 / 1k / 10k req の月額表示
- [ ] 数値 drift 0 (制度数 / tools 数 / FAQ 数値が `mcp-tools.md` / `pricing.md` / `index.md` / `press_kit.md` 全て一致)
- [ ] `solo_ops_handoff.md` が `docs/_internal/` 配下 + 1Password 経由のリンク指示が埋まっている

### 中間確認

Public 8 項目 + 数値 drift 0 を確認。`go_no_go_gate.md` PASS が **24+ / 25** に到達。

---

## T-5d (2026-05-01 木) — DR drill (Scenario 1 + 2)

**目的**: 障害シナリオ 1 (VM crash) + 2 (volume corruption) を staging で実走、RTO を SLO 内で確認。

### Tasks

- [ ] staging machine で `flyctl machine restart` を 3 回実行 → 30 秒以内復帰確認 (Scenario 1)
- [ ] staging volume を corrupt simulate (任意 row UPDATE で integrity_check fail) → R2 snapshot から復旧 (Scenario 2、target 30 分以内)
- [ ] 観察 RTO を `docs/_internal/dr_drill_log.md` に追記
- [ ] `rollback_runbook.md` の手順が drill と整合していることを確認

### 中間確認

Scenario 1 RTO ≤ 30s、Scenario 2 RTO ≤ 30 min。両方 PASS。

---

## T-4d (2026-05-02 金) — 数値 drift sweep + content lockdown

**目的**: 全公開 surface の数値を fact-sheet に最終整合させる。以降 launch 当日まで content freeze。

### Tasks

- [ ] `site/press/fact-sheet.md` の数値を最新値で fix (制度数 / 採択事例 / 融資 / 行政処分 / tools / OpenAPI paths / プレローンチ subscribers)
- [ ] `index.md` / `getting-started.md` / `faq.md` / `pricing.md` / `mcp-tools.md` の数値を fact-sheet と grep diff
- [ ] `README.md` (GitHub 用) の数値を fact-sheet と整合
- [ ] `press_kit.md` の数値を fact-sheet と整合
- [ ] **Content freeze 宣言**: 以降 T+0 まで上記 7 surface の数値変更を行わない

### 中間確認

7 surface の数値 grep diff = 0。content freeze 宣言を本ファイル「記録欄」に書く。

---

## T-3d (2026-05-03 土) — Zenn 草稿 publish + PyPI dry-run

**目的**: Zenn を 3 日先行で indexing 開始 + PyPI build を dry-run で確認 (実 upload は T-1d)。

### Tasks

- [ ] Zenn 草稿 publish (`launch_announcement_calendar.md::T-3d` 参照)
- [ ] `python -m build` で wheel + sdist 生成 → `dist/autonomath_mcp-0.2.0*.whl` `tar.gz` 確認
- [ ] `twine check dist/*` PASS (metadata validation)
- [ ] `pip install dist/autonomath_mcp-0.2.0-py3-none-any.whl` をクリーン venv で動作確認
- [ ] `autonomath-mcp` console script 起動確認
- [ ] **本 upload は T-1d まで保留**

### 中間確認

PyPI dry-run 全 PASS。Zenn URL を press kit に追加せず内部メモのみ (公式 launch は T+0)。

---

## T-2d (2026-05-04 日) — GitHub repo public + 1Password 棚卸し

**目的**: GitHub stars 収集起点 + AI registry crawler に detect される。Secret 棚卸しで T-1d リハーサルへ繋ぐ。

### Tasks

- [ ] `launch_announcement_calendar.md::T-2d` のチェックリスト全消化
- [ ] 1Password vault `bookyou-autonomath-prod` の 13 secret (`solo_ops_handoff.md::§15`) を全件確認
- [ ] Fly secrets と 1Password 値が一致していることを `flyctl secrets list` の expiry 列で確認
- [ ] GitHub release `v0.3.0` 作成 (PyPI tag 連動は T-1d)

### 中間確認

GitHub 公開 + 13 secret 全件揃い。

---

## T-1d (2026-05-05 月) — Full deploy rehearsal + PyPI publish

**目的**: production deploy を **本番と同一手順** で 1 回実行し、handoff 含む全フローを通す。

### Tasks (時系列、AM → PM)

- [ ] **AM**: `git checkout main && git pull && ruff && pytest && mypy` 全 PASS
- [ ] **AM**: `mkdocs build --strict` PASS
- [ ] **AM**: `flyctl deploy --app autonomath-api --strategy rolling` (staging tag 付き)
- [ ] **AM**: production smoke `BASE_URL=https://api.autonomath.ai ./scripts/smoke_test.sh` PASS
- [ ] **AM**: Stripe live ¥3 e2e (`scripts/stripe_smoke_e2e.py`) PASS
- [ ] **PM**: `python -m build && twine upload dist/*` (PYPI_TOKEN)
- [ ] **PM**: `pip install autonomath-mcp` をクリーン venv で動作確認
- [ ] **PM**: `mcp publish server.json` で Anthropic + 11 registry へ submission
- [ ] **PM**: Cloudflare Pages production deploy 確認 (autonomath.ai)
- [ ] **PM**: 翌日 launch 投稿の本文 (HN / X / LinkedIn / Zenn / 購読者 mail) を最終 review
- [ ] **PM**: `go_no_go_gate.md` 全 25 項目を最終 PASS/FAIL 判定 → **Go / No-Go 決定**

### 中間確認 (= go/no-go gate)

`go_no_go_gate.md` の 25 項目で:

- critical fail = 0 件 → **Go** (T+0 へ)
- critical fail 1-2 件 → **operator 判断 Go**
- critical fail ≥ 3 件 → **No-Go**、launch を T+7d 延期

判定結果と理由を本ファイル「記録欄」に書く。

---

## T+0 (2026-05-06 水) — Launch day

**目的**: 公式 launch、HN / X / 購読者へ一斉告知。`launch_announcement_calendar.md::T+0` の time slot に従う。

### Tasks (時系列)

- [ ] **08:00 JST**: 朝の wake-up routine (上述) 完走
- [ ] **08:30 JST**: production smoke + Stripe smoke 最終確認
- [ ] **09:00 JST**: X (Twitter) launch tweet
- [ ] **10:00 JST**: 購読者 email send
- [ ] **20:00 JST (= 07:00 ET)**: Hacker News Show HN 投稿 + first comment
- [ ] **22:00 JST**: LinkedIn post
- [ ] **00:00 JST (T+0d 終了直前)**: 当日のメトリクス snapshot を `docs/_internal/dr_drill_log.md` に追記

### 中間確認 (毎時)

毎時 30 分に `wake-up routine` の 5 ステップを再走 (12 回 / 24h)。Sentry / Fly / Stripe で赤が出たら即 `rollback_runbook.md`。

---

## T+1d (2026-05-07 木) — 5 audience pitch + 障害監視継続

**目的**: persona 別 deep-dive 公開 + launch 翌日 burst を捌く。

### Tasks

- [ ] `launch_announcement_calendar.md::T+1d` のチェックリスト全消化
- [ ] launch 24h 観測値を本ファイル「記録欄」に追記 (req 数 / unique IP / paid req / Sentry エラー数 / 5xx 比率)
- [ ] 24h で Sentry 新規 issue ≥ 5 件 / 5xx > 2% → `rollback_runbook.md` 起動
- [ ] 顧客問い合わせ (info@bookyou.net) を 4h 以内に 1st response

### 中間確認

5xx < 2% / Sentry 新規 issue < 20 件 / 24h。基準を超えたら post-mortem + 次 deploy で fix。

---

## T+7d (2026-05-13 水) — 1 週間 metrics blog + DR drill 振り返り

**目的**: launch 後 1 週間の数値を transparent に公開、organic trust 強化。

### Tasks

- [ ] `launch_announcement_calendar.md::T+7d` のチェックリスト全消化
- [ ] `site/stats.html` dashboard を 7 日間累計値で update
- [ ] 失敗・課題も併記 (memory `feedback_action_bias`)
- [ ] 7 日間で発生した incident を `disaster_recovery.md` のシナリオ番号にマッピング
- [ ] T-5d の DR drill log を読み返し、real incident の RTO と比較

### 中間確認

7 日間の SLO budget 21.6 min × 7/30 ≒ 5.04 min を消費していないこと。超えていれば quarterly review に格上げ。

---

## T+30d (2026-06-05 金) — Phase 1 振り返り + post-launch P5/P6 移行

**目的**: launch から 30 日のメトリクスをまとめ、P5 (cache populate / amendment webhook 等) + P6 (Healthcare V3 prep) に切替える。

### Tasks

- [ ] 30 日 metrics blog publish (req 数 / paid retained M2 / cache hit / TTFV / NPS)
- [ ] `disaster_recovery.md::§3.3` Q1 drill (Scenario 1 + 2) を実施し log
- [ ] T+0 → T+30d の post-mortem を 1 ファイルにまとめる (template §A 適用、`disaster_recovery.md::§4`)
- [ ] P5/P6 ロードマップ (`long_term_strategy.md`) を 30 日観測値で校正
- [ ] **Phase 0 → Phase 1 への solo ops 状態遷移宣言** (`solo_ops_handoff.md::§20`)

### 中間確認

T+30d 数値が `00_smart_merge_plan.md::§8` v8 plan の T+30d 列 (MAU 100-300 / paid 5-10 / ARR ¥1.5-3M/月 / 33 invariants 5/33) のレンジ内。レンジ外なら `improvement_loop.md` に従って次 30 日の target 再設定。

---

## 記録欄 (operator が手書きで埋める、launch 後の参照用)

```
# T-11d (2026-04-25)
- baseline: PASS __ / 25
- 残 blocker: <列挙>
- 完了時刻: __:__

# T-10d (2026-04-26)
- L0 Storage 4 項目 PASS: yes/no
- 観察値: <FK 違反件数 / index hit rate>

# T-9d (2026-04-27)
- L1+L2 5 項目 PASS: yes/no
- tools 数: __ (期待 55)

# T-8d (2026-04-28)
- L0 Infra 7 項目 PASS: yes/no
- Stripe ¥3 e2e: pass/fail
- Fly volume 残: __ GB

# T-7d (2026-04-29)
- Compliance 5 項目 PASS: yes/no
- production smoke: pass/fail
- gate progress: __ / 25

# T-6d (2026-04-30)
- Public 8 項目 PASS: yes/no
- 数値 drift: __ surface 不一致

# T-5d (2026-05-01)
- DR drill Scenario 1 RTO: __ s (target 30s)
- DR drill Scenario 2 RTO: __ min (target 30 min)

# T-4d (2026-05-02)
- 7 surface 数値 drift: __
- content freeze: yes/no

# T-3d (2026-05-03)
- Zenn URL: <url>
- PyPI dry-run: pass/fail

# T-2d (2026-05-04)
- GitHub public: yes/no
- 13 secret 揃い: yes/no

# T-1d (2026-05-05)
- production deploy 時刻: __:__
- PyPI upload: pass/fail
- go/no-go 判定: Go / No-Go
- 判定理由: <一行>

# T+0 (2026-05-06)
- 09:00 X tweet 時刻: __:__
- 10:00 mail send 時刻: __:__
- 20:00 HN 投稿 URL: <url>
- 24h req 数: __
- 24h unique IP: __
- 24h paid req: __
- 24h Sentry 新規 issue: __
- 24h 5xx 比率: __ %

# T+1d (2026-05-07)
- 5 audience pitch publish: yes/no
- incident 件数: __

# T+7d (2026-05-13)
- 7 日累計 req 数: __
- 7 日 paid req 数: __
- 7 日 SLO budget 消費: __ min (budget 5.04 min)
- 失敗・課題: <列挙>

# T+30d (2026-06-05)
- MAU: __ (target range 100-300)
- paid retained M2: __ (target range 5-10)
- ARR: ¥__ /月 (target range ¥1.5-3M/月)
- Phase 1 移行: yes/no
```

---

最終更新: 2026-04-25 / Bookyou株式会社 / info@bookyou.net
