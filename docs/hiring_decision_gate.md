# 税務会計AI — Hiring Decision Gate

Internal P5-quarterly decision document. Solo operator (梅田茂利, info@bookyou.net), Bookyou株式会社.

最終更新: 2026-04-25 · Reviewed: quarterly (Q1/Q2/Q3/Q4 初旬) alongside `docs/sla.md`

This document defines the four points in the product lifecycle where the operator must consciously decide: **stay solo, contract, or hire**. The defaults all favor staying solo (memory `feedback_zero_touch_solo`, `project_autonomath_business_model`). Each trigger overrides the default only if measured criteria are met.

---

## 0. Operating principles (immutable)

- **Default is solo.** Hiring is the exception, not the path. Every alternative (automation, outsourcing a single task, accepting slower iteration) is preferred to a permanent W-2 hire.
- **No commission-driven sales hires, ever.** Memory `feedback_organic_only_no_ads` rules out outbound sales. If MRR plateaus, the answer is content + product, not a salesperson.
- **No customer success hires, ever.** Memory `feedback_zero_touch_solo`. If support load grows, the answer is more in-product self-service (CS automation Tier 1-3 in `00_smart_merge_plan.md` §0.10), not a CS rep.
- **Equity grants only.** No cash-heavy comp. Bookyou KK is a single-shareholder Japanese 株式会社 — equity grants require board resolution + 株主総会 + 税理士 valuation. Range: 1-3% per first hire.
- **Runway test.** No hire that drops runway below 12 months at then-current burn.

---

## 1. The four triggers

| Trigger | Timing | Criterion (all must be true) | Default action | Override action |
|---|---|---|---|---|
| **T+180d** | 6 months post-launch | MRR > ¥1M sustained 60 d **AND** incident rate ≥ 2/week **AND** burnout signs (see §2) | Stay solo + automate | Hire 1 ops contractor |
| **T+365d** | Year 1 anniversary | MAU ≥ 10k **AND** MRR > ¥3M sustained 90 d | Stay solo + automate | Hire 1 ops (full-time) — required, not optional |
| **T+730d** | Year 2 — 2nd vertical entry decision | Y1 ARR > ¥150M **AND** vertical-1 cache hit > 75% **AND** vertical-2 demand evidenced (waitlist > 200 OR partner request) | Contractor (not hire) | Hire 1 vertical-2 specialist |
| **Y3** | Phase 4 transition | Y2 ARR > ¥450M **AND** 70+ h/month operator hours sustained | Hire 2nd ops | Hire 2 ops (one engineering, one bizops) |

Triggers are **and-gated**: missing any criterion → fall back to default. The operator may not unilaterally override the gate — quarterly review with 税理士 + (optional) advisor required.

---

## 2. Detection — how each trigger is measured

### 2.1 MRR / MAU

- **Source**: Stripe live dashboard → Billing → MRR widget. Cross-checked against `request_log` daily yen sum (1% tolerance, see `solo_ops_handoff.md` §10).
- **MAU definition**: distinct `customer_id` with ≥ 1 paid request in trailing 30 days. Anonymous IP-based traffic does NOT count.
- **Sustained**: rolling N-day window where the metric stays above threshold every day. Single-day spikes do not qualify.

### 2.2 Incident rate

- **Source**: `docs/_internal/dr_drill_log.md` + Sentry incident counts.
- **Definition**: customer-affecting events (Scenario 1 / 2 / 6 / 8 / 9 in `disaster_recovery.md`) only. Internal-only (Scenario 3 / 4 / 5) do not count.
- **Threshold**: 2/week sustained 4+ weeks = "incident rate increasing" trigger condition.

### 2.3 Burnout signs (T+180d gate only)

The operator self-assesses against the following — 3+ "yes" answers within a single quarter activates the burnout flag:

- [ ] Skipped 2+ scheduled days off in trailing 30 d
- [ ] Average sleep < 6 h on workdays in trailing 30 d
- [ ] Missed 2+ deadman check-ins in trailing 90 d
- [ ] Postponed 2+ post-mortems past D+30 deadline
- [ ] Customer email response time > 7 d in trailing 30 d (vs target 48 h)
- [ ] Stopped writing weekly retrospective (`_internal/weekly_retro.md`) for 4+ weeks
- [ ] Considered shutting down product without recurring incident driving it

Self-assessment is private to the operator. If 3+ check-marks: trigger fires regardless of MRR/incident counts.

### 2.4 Cache hit rate (T+730d gate)

- **Source**: `request_log.cache_hit` boolean column, weekly rollup.
- **Definition**: % of paid requests served from `pre_compute_cache` without a fresh primary 正規化レコード query. Target by Y2: > 75% (path to 80% Zipf ceiling).

### 2.5 Operator hours (Y3 gate)

Tracked via `_internal/weekly_retro.md` self-report. 70+ h/month sustained 3+ months = "burning all the slack".

---

## 3. Hire profile by trigger

### Trigger 1 — T+180d ops contractor

- **Role**: Part-time ops contractor (15-25 h/week, remote, 業務委託契約).
- **Profile**: Mid-level Python + SQLite + Fly.io ops. Comfortable with on-call rotation. Bilingual JP/EN preferred (English is bonus).
- **Scope**: incident triage Tier 1 (`_internal/incident_runbook.md` §a-e), nightly backup verification, customer email triage. NOT decision-making — operator retains all product/billing decisions.
- **Comp**: ¥3,000-5,000/h hourly cap. ¥150-300k/month at full utilization. NO equity at contractor stage.
- **Sourcing**: 個人事業主 referral via existing network. NOT 派遣 / NOT recruiter (commission destroys margin).

### Trigger 2 — T+365d full-time ops

- **Role**: Full-time ops engineer (40 h/week, 正社員 or full-time 業務委託).
- **Profile**: Senior Python / SRE / 1+ year SQLite-at-scale. Reads JP business correspondence (政府文書 + 法務メール). Independent — must be able to take a Sentry alert at 02:00 JST and ship a fix without supervision.
- **Scope**: Full ops responsibility. Operator transitions to product + ingest + roadmap.
- **Comp**: ¥800k-1.2M/month base + 1-2% equity (4-year vesting, 1-year cliff). Stripe-equivalent restricted stock via Bookyou KK 取締役会決議.
- **Sourcing**: 1 candidate from existing network → if no fit, post on YouTrust / Findy. NOT LinkedIn / NOT 大手 recruiter.

### Trigger 3 — T+730d vertical-2 specialist (default = contractor)

- **Role**: Domain expert (e.g. 医療法 + 介護保険法 lawyer / 不動産 取引士) on consulting retainer. Read `docs/_internal/GENERALIZATION_ROADMAP.md` for the V3-V5 roadmap.
- **Scope**: Vertical-2 data curation (法令 references, exclusion rules, hallucination_guard rows). NOT engineering.
- **Comp (contractor)**: ¥30-80k/month retainer + per-row review fee (¥500-1500/row). NO equity unless converted to full-time.
- **Comp (full-time override)**: ¥600-900k/month + 0.5-1% equity if scope expands to ownership of the vertical end-to-end.
- **Sourcing**: 弁護士会 / 司法書士会 referral. NOT a tech recruiter.

### Trigger 4 — Y3 second ops (engineering + bizops split)

- **Role 4a**: Senior engineering ops (replaces operator on infra). Same profile as T+365d hire but more senior — ARR is now ¥450M+, expectations rise.
- **Role 4b**: BizOps lead (NOT sales). Owns billing reconciliation, 法務 reviews, 税理士 interface, partnership formalities (memory `feedback_zero_touch_solo` still applies — no outbound sales). Comfortable with Stripe + e-Tax + 法人 admin.
- **Comp 4a**: ¥1.2-1.8M/month + 1-2% equity.
- **Comp 4b**: ¥800k-1.2M/month + 0.5-1% equity.
- **Operator transition**: Operator moves to roadmap + ingest + research; day-to-day ops handed to 4a, billing/legal handed to 4b.

---

## 4. Interview process (any trigger)

Compressed because solo + zero-touch — we cannot run a 5-round panel.

### Round 1 — Async take-home (paid, ¥30-50k)

- 4 hours of work, paid hourly regardless of outcome. Examples:
  - Trigger 1/2: "Given this Sentry breadcrumb (real, redacted), write the runbook entry."
  - Trigger 3: "Review these 50 hallucination_guard rows. Which 5 are factually wrong, and what is the primary source?"
  - Trigger 4a: "Profile this query (`tests/perf/<file>.py`). What's the bottleneck? Propose 2 fixes with trade-offs."
- Submission graded against rubric in `_internal/hiring_rubric.md` (drafted at trigger fire-time).

### Round 2 — Live pairing (90 min, paid)

- Operator pairs with candidate on a real (low-risk) ticket. Observation, not interrogation.
- Pass criterion: candidate ships the ticket, asks 2-3 substantive questions, makes 1 disagreement explicit.

### Round 3 — Reference check + offer

- 2 references (managers, not peers). 30-min call each.
- Verify: did they ship independently? did they handle on-call? did they communicate clearly in writing?
- Offer extended within 5 business days of Round 3 pass.

Total cycle time: 3-4 weeks max. Two rounds of "no decision" → reject (decision fatigue is a hire risk signal).

---

## 5. Equity grant mechanics (Bookyou KK)

- 株式会社 single-shareholder structure. Equity grants require:
  1. 取締役会決議 (or 株主総会決議 for material grants > 5%)
  2. 税理士 valuation (FMV at grant date) — required for 給与所得 / 譲渡所得 separation
  3. 種類株式 vs 普通株式 decision (default: 普通株式 with vesting via shareholder agreement)
  4. 4-year vesting / 1-year cliff via 株主間契約 (separate from 雇用契約)
- Tax: equity grant is 給与所得 at FMV at grant; vesting events are not taxable until liquidity. Capital gains at exit. Confirm with 税理士 — rules change.
- Cap table impact: 1-3% Trigger 2 + 1-2% Trigger 4a + 0.5-1% Trigger 4b = up to 5.5% diluted by Y3. Operator retains 94.5%+ for Series A optionality.

---

## 6. Runway impact analysis

| Trigger | Monthly burn add | Runway at trigger fire (assumed cash) | Pass criterion |
|---|---|---|---|
| 1 | +¥150-300k (contractor) | ¥6M cash → -1 month per trigger fire = OK | MRR > ¥1M cushions |
| 2 | +¥800k-1.2M (FT + 法定福利) | ¥10M+ cash required | MRR > ¥3M cushions |
| 3 (contractor) | +¥30-80k (retainer only) | Negligible | Y1 ARR ¥150M = ¥12.5M MRR cushions |
| 3 (FT override) | +¥600-900k | ¥15M+ cash required | Same |
| 4 | +¥2-3M (combined 4a + 4b + 法定福利) | ¥30M+ cash required | Y2 ARR ¥450M = ¥37.5M MRR cushions |

Runway test: at any trigger, post-hire monthly burn must leave ≥ 12 months of cash at then-current MRR. Quarterly recompute alongside this doc review.

---

## 7. What this document does NOT cover

- **Investor decisions** (Series A timing, cap table for VCs): see `docs/_internal/long_term_strategy.md` (Y2-Y5 scenarios).
- **Acquisition / acqui-hire decisions**: see Scenario 10 in `solo_ops_handoff.md` §20.
- **Specific candidate evaluations**: each trigger fire spawns its own private `_internal/hire_<trigger>_<date>.md` file; do not recycle this template for personal info.

---

## 8. Review log

| Date | Reviewer | Triggers active | Decision |
|---|---|---|---|
| 2026-04-25 | 梅田 (drafted) | none (T-11d to launch) | initial draft |

Append a new row each quarterly review. Keep history.
