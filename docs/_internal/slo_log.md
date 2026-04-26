# SLO Monthly Log — AutonoMath

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26
**Source of definitions**: [`slo.md`](./slo.md) §2 (S1-S4)

> Append-only monthly record of the 4 SLOs defined in `slo.md`. Solo +
> zero-touch ops: this log replaces a team retrospective. Each month
> entry is filled at JST 月初 + 3 営業日 (the cron `scripts/cron/anon_quota_audit.py`
> + UptimeRobot monthly report + Stripe Events API export drive the numbers).

---

## Logging convention

- **Append-only**: never edit a closed month row. Errata go in a `## Errata` section at the bottom with the reason and the corrected value.
- **Source citation**: every number must cite its source (UptimeRobot URL, structlog query, Stripe Events API range, SQL query). 「TBD」 と 「N/A (未launch)」 を区別する。
- **Solo retro**: each month adds a `### Notes / one-liner retro` paragraph with what to fix next month (no team distribution, just operator memo).
- **Stale-claim watch**: if a number contradicts CLAUDE.md or `slo.md`, fix the upstream doc first, then back-fill the row reference.

---

## 2026-04 (initial baseline, pre-launch)

**Status**: pre-launch. All numbers are **N/A (未launch)** unless explicitly noted.

| SLO | Target | Actual | Source | Status |
|---|---|---|---|---|
| S1 availability | 99.5%/月 | N/A (未launch) | — | baseline only |
| S2 prescreen p95 | < 500 ms | 247 ms (synthetic, 1000-req sweep, NRT region) | `perf_baseline_v15_2026-04-25.md` Table 2 | within budget |
| S3 webhook 成功率 | ≥ 99.9% | N/A (未launch) | — | baseline only |
| S4 anon limit ±5% | 47-53/IP | N/A (未launch) | — | baseline only |

### Notes / one-liner retro

- pre-launch baseline 確立。S2 のみ実測値あり (Wave 17 perf sweep)。launch 後 1 週間で S1/S3/S4 の最初の実測値を埋める。
- `scripts/cron/anon_quota_audit.py` 未着手 → launch +1 週で書く (`slo.md` §5)。

---

## 2026-05 (launch month)

**Status**: 進行中 (launch 2026-05-06)。月末締め後 (2026-06-03 目処) に確定。

| SLO | Target | Actual | Source | Status |
|---|---|---|---|---|
| S1 availability | 99.5%/月 | TBD post-launch | UptimeRobot monthly report URL | TBD |
| S2 prescreen p95 | < 500 ms | TBD post-launch | structlog `latency_ms` p95 (1h sliding × 月集計) | TBD |
| S3 webhook 成功率 | ≥ 99.9% | TBD post-launch | Stripe Events API delivery_attempt 集計 | TBD |
| S4 anon limit ±5% | 47-53/IP | TBD post-launch | `anon_rate_limit` 月初 SQL audit | TBD |

### Pre-fill checklist (operator, 2026-06-03)

- [ ] UptimeRobot monthly report DL → S1 入力
- [ ] `scripts/cron/anon_quota_audit.py` 出力 → S4 入力
- [ ] Stripe Events API range query → S3 入力
- [ ] structlog p95 SQL (`analytics/` 配下) → S2 入力
- [ ] error budget burn rate を `slo.md` §3 の式で計算、warn/alarm/pager 発火回数を併記
- [ ] one-liner retro 書く (次月への持ち越し課題)

---

## 2026-06 〜 (template)

以降の月は下記テンプレを copy して使う。launch 後 12 ヶ月で年次レビュー (`slo.md` §7)。

```markdown
## YYYY-MM

| SLO | Target | Actual | Source | Status |
|---|---|---|---|---|
| S1 availability | 99.5%/月 | XX.XX% | UptimeRobot URL | within / warn / alarm |
| S2 prescreen p95 | < 500 ms | XXX ms | structlog query | within / warn / alarm |
| S3 webhook 成功率 | ≥ 99.9% | XX.XX% (X/Y) | Stripe Events API | within / warn / alarm |
| S4 anon limit ±5% | 47-53/IP | XX-XX/IP | anon_quota_audit.py | within / warn / alarm |

### Incidents this month
- (none) または `incident_runbook.md` の incident_id 一覧

### Error budget burn
- S1: X.X min consumed / 21.6 min budget (XX%)
- S2: XX breaches / 1000 calls (within 5% allowance?)
- S3: X failures / Y webhooks
- S4: X% of unique IPs in breach

### Notes / one-liner retro
- (next-month action items, solo memo)
```

---

## Errata

(空 — closed 月の数値修正はここに reason 付きで記録)

---

## 関連 doc

- [`slo.md`](./slo.md) — SLO 定義 + error budget 計算式
- [`incident_runbook.md`](./incident_runbook.md) — incident 発生時の SLO への inject
- [`launch_war_room.md`](./launch_war_room.md) — launch +24h の SLO realtime 監視
- `docs/sla.md` (mkdocs 公開) — 公開 SLA 99.0% (この log は内部 99.5% target)
