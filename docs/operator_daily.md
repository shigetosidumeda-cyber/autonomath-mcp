# 税務会計AI — Operator Daily Runbook

**Audience**: 梅田茂利 (info@bookyou.net) — solo operator, 税務会計AI / Bookyou株式会社 (T8010001213708).
**Scope**: T+0 (launch 2026-05-06) 〜 T+90d operator routine. Replaces ad-hoc check-ins with a fixed cadence so the 6h/week cap (memory `feedback_zero_touch_solo`) is enforced without missing customer-affecting signals.
**Status**: operator-only. Excluded from `mkdocs build` (`exclude_docs` in `mkdocs.yml`). No secret values written here — only env var names.

Companion docs:

- `docs/_internal/operators_playbook.md` — full incident / refund / abuse procedures
- `docs/solo_ops_handoff.md` — Scenario-10 successor handoff (NOT for daily use)
- `docs/operator_dashboard_walkthrough.md` — dashboard / stats / testimonials / alerts UI walk
- `docs/hiring_decision_gate.md` — D1 references for the monthly hire-decision self-eval

---

## 0. Cadence at a glance

| Slot | Length | Frequency | Output |
|------|--------|-----------|--------|
| 朝 routine | 15 min | 平日毎朝 | pytest + Sentry triage + cap-reached scan |
| 昼 routine | 30 min | 平日昼 (任意) | testimonial moderation / hallucination guard 補修 / partner inquiry |
| 夕 routine | 15 min | 平日夕 | MAU / MRR / margin の今日値 確認 + 翌日 plan 1 行 |
| 週次 ritual | 60 min | 土曜 10:00 JST | gold expansion / weekly invariant / blog 1 本草稿 |
| 月次 ritual | 180 min | 月初 第1営業日 | hire decision gate / DR drill / refund・dispute 棚卸し |

合計目安: 平日 60 min × 5 + 土 60 min + 月次 180 min ÷ 4 = 6h/週 cap 内。

---

## 1. 朝 routine (15 min, 平日)

### 1.1 pytest scheduled health (3 min)

GitHub Actions `nightly-tests.yml` の前夜 build を確認:

```bash
gh run list --workflow=nightly-tests.yml --limit=1
gh run view --log-failed | head -40    # failed の場合のみ
```

- green: 何もしない、次へ
- red:  `Sentry / actions email` に reproduce instruction が来ているはず → triage 起票 (§1.3 と統合)

### 1.2 Sentry alert review (5 min)

1. Sentry dashboard (`SENTRY_DSN` env で参照、project = autonomath-prod) を開く
2. **Last 12h, Unresolved, level=error|fatal** filter
3. issue 0 件: 完了
4. issue ありの場合:
   - **fatal** → 即 `_internal/incident_runbook.md` で trigger と一致する scenario に jump
   - **error** で件数 < 5: メモのみ、昼 routine で見る
   - **error** で件数 ≥ 5 or 1 issue で >50 events: 即 triage、§3.2 (refund_helper) で影響 customer 特定

### 1.3 cap-reached customer chk (5 min)

`scripts/ops_quick_stats.py` を 1 発:

```bash
.venv/bin/python scripts/ops_quick_stats.py
```

`Cap usage:` 行の **cap-reached** が前日比 +1 以上なら:

1. 該当 customer に「cap reached email」(billing module 自動送信済) の delivery 確認
2. cap raise 希望の inbound が来ていたら、24h 以内に customer reply (§2.2 partner inquiry response の手順を流用)
3. operator 側からの先回り連絡は **しない** (zero-touch 原則)

### 1.4 朝 routine 完了条件

- [ ] pytest green
- [ ] Sentry critical 0 / 高優先 issue triage 起票済
- [ ] cap-reached delta 確認済
- [ ] 朝 stand-up note を `research/ops_log_<YYYY-MM>.md` に 1 行追記

未達があっても 15 min 経過で打ち切る。残課題は昼 routine の queue に push。

---

## 2. 昼 routine (30 min, 任意)

平日昼の任意 slot。inbound が無く朝 queue も空なら skip 可。

### 2.1 testimonial moderation (10 min)

`site/testimonials.html` 経由で submit された inbound (B8 module、メール `OPS_INBOX_EMAIL` env に届く):

1. `site/testimonials.html` の moderation queue (admin link、`OPS_ADMIN_TOKEN` env 必要) を開く
2. pending 件を読み、**虚偽 / 攻撃的 / 個人情報含む** ものを reject
3. approve は 1 日 max 5 件、それ以上は週次へ持ち越し (公平性確保)
4. approve 済は `research/testimonials_log.md` に hash + 日付 のみ記録

### 2.2 hallucination guard 補修 (10 min)

`docs/hallucination_guard_methodology.md` の方針に従い、`research/hallucination_audit/` 配下に蓄積された false-positive / false-negative samples を 1 件処理:

- 該当 program の `confidence_score` を re-evaluate (read-only)
- ruleset 修正案を `research/guard_proposals/<YYYY-MM-DD>.md` に書く
- 実装 (DB write / code change) は週次へ ; 当日は調査メモのみ

### 2.3 partner inquiry response (10 min)

`docs/partnerships/*.md` 由来の inbound (freee / MoneyForward / kintone / SmartHR / Anthropic Directory):

- 24h 以内に 1 次返信 (受領 + 回答期限) を返す
- 必ず `research/partner_inquiries_log.md` に 1 行追記 (相手 / 受信日時 / 1 次返信日時 / 回答期限)
- 案件成立は zero-touch 原則の例外なので慎重に — 営業電話・slack connect は受けない

### 2.4 昼 routine 終了条件

- [ ] testimonial pending 0 ≤ 5 以内に整理
- [ ] hallucination guard 1 件処理 or skip 理由を log
- [ ] partner inquiry 0 件 or 1 次返信完了

---

## 3. 夕 routine (15 min, 平日)

### 3.1 KPI 今日値 (10 min)

```bash
.venv/bin/python scripts/ops_quick_stats.py
```

`research/ops_log_<YYYY-MM>.md` に追記:

```
2026-05-XX (Wed)
  MAU=234 (anon=198, paid=36)
  MRR=¥47,250
  ¥/customer=¥1,313
  cap_set=12, cap_reached=3
  Sentry unresolved critical=0
  Stripe dispute pending=1 (¥3,510)
  Note: ...  # 1 行コメント
```

### 3.2 翌日 plan (5 min)

「翌日朝の最優先 1 件」をメモ:

- triage carry-over があるか
- 週次 / 月次 ritual の前倒しが必要か
- inbound が積もっていないか

3 行 max。長文 plan 禁止 (memory `feedback_slow_pace_pivot`).

---

## 4. 週次 ritual (60 min, 土曜 10:00 JST)

### 4.1 gold expansion (20 min)

`evals/gold/` の正解集を 5 件追加 / 5 件 review:

```bash
.venv/bin/python scripts/eval_runner.py --gold-only --since-last-week
```

failure があれば `_internal/data_integrity.md` の手順で fix。当週で fix 不能なら issue 化。

### 4.2 weekly invariant review (20 min)

```bash
.venv/bin/python scripts/run_invariants.py --tier 2
ls -la analysis_wave18/invariant_runs/$(date -u +%Y-%m-%d).json
```

`docs/invariant_runbook.md` §Weekly cron に従い、red invariant があれば即 fix。green でも 4 週連続で 0 違反なら invariant の cardinality を 1 段階上げる検討メモを `research/invariants_evolution.md` に書く。

### 4.3 blog 1 本草稿 (20 min)

`docs/blog/draft_<YYYY-MM-DD>.md` に 600-1200 字の draft を書く。published=false で commit。実 publish は別週 (review buffer 1 週間)。テーマ source:

- 当週で hit した実 customer 質問 (匿名化)
- 当週の制度更新 (法改正 / 新規 program)
- ¥3/req economics の透明性 post

### 4.4 週次 ritual 終了条件

- [ ] gold +5 / review 5
- [ ] invariant red=0 を確認
- [ ] blog draft 1 本コミット
- [ ] `research/ops_log_<YYYY-MM>.md` に週次サマリ 1 段落

---

## 5. 月次 ritual (180 min, 月初第1営業日)

### 5.1 hire decision gate self-eval (60 min)

`docs/hiring_decision_gate.md` の D1 references を順に評価:

1. trigger 1-4 のうち発火しているか (測定値ベース)
2. 当月の operator hours actual (`research/ops_log_*.md` 集計)
3. 6h/week cap 4 週連続超え → trigger 4 ON 候補
4. 結論を `research/hire_decision_<YYYY-MM>.md` に 1 ページ書く (NO の場合も「NO + 理由」を必ず書く)

### 5.2 DR drill 1 件 (60 min)

`docs/disaster_recovery.md` の Scenario 1-9 から 1 つ選択 (毎月 rotation、9 ヶ月で 1 周):

1. staging 環境で scenario を再現
2. RTO/RPO 実測
3. `research/dr_drills/<YYYY-MM>_scenario<N>.md` に結果記録
4. 想定 RTO/RPO を超えたら scenario 別の runbook を update

### 5.3 refund / dispute 棚卸し (60 min)

```bash
.venv/bin/python scripts/ops_quick_stats.py
```

の dispute / refund summary を起点に:

1. 当月の dispute 全件 status 確認 (Stripe Dashboard、`STRIPE_SECRET_KEY` env で API 直叩きはしない、operator 目視のみ)
2. unresolved dispute は §2.3 of operators_playbook の 20 日 window 内か検証
3. 当月 refund 件数 / 総額を `research/refund_decisions.log` に追記
4. refund 率が直近 3 ヶ月で増えていたら『商品説明の誤解』pattern を疑い、`docs/pricing.md` / `site/pricing.html` の wording 監査

### 5.4 月次 ritual 終了条件

- [ ] hire decision YES/NO を 1 ページで結論
- [ ] DR drill 1 件 完走 + 記録
- [ ] dispute / refund 全件 close 状態を確認
- [ ] 翌月の cap 改善 1 候補をメモ

---

## 6. 触ってはいけないこと (NG list)

- LIVE 自動操作 (refund / cap raise / key revoke) を script 化しない — operator 目視確認を残す
- DB write を script 経由で行わない — 全 mutation は migration / billing module 経由
- secret 値を log / docs にコピーしない — env var 名のみ参照
- hire decision を月次以外で前倒し / 後ろ倒ししない (memory `feedback_no_mvp_no_workhours` 派生)

---

## 7. 関連 file

- 朝 stats: `scripts/ops_quick_stats.py` (read-only)
- refund 助言: `scripts/ops_refund_helper.py` (read-only, advisory のみ)
- 旧 weekly stats: `scripts/support_stats.py` (Monday ritual で併用可)
- 詳細 incident: `docs/_internal/incident_runbook.md`
- DR scenarios: `docs/disaster_recovery.md`
- 後継 hand-off: `docs/solo_ops_handoff.md`
