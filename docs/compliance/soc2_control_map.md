---
search:
  exclude: true
---

# SOC 2 Type II Self-Attestation -- Control Map

**Service Organisation:** Bookyou株式会社 (T8010001213708)
**Service:** jpcite REST + MCP API for Japanese public-program evidence retrieval
**Reporting period:** Rolling 12 months ending on the first day of each quarter
**Auditor:** Self-attestation (solo operator -- no external CPA engagement)
**Document owner:** 梅田茂利 (info@bookyou.net)
**Last review:** 2026-05-11

This document maps jpcite's operating controls to the AICPA Trust Services
Criteria (TSC) used by SOC 2 Type II. Because jpcite is operated by a
single principal without external sales / CS / legal headcount, the
attestation is a **self-attestation**: every control is implemented in
code or in a public artefact whose path is listed below. Anyone running
the public repo at `HEAD` can re-derive each control's evidence from the
listed path without operator assistance.

The map is published deliberately. Customers can audit `HEAD` against the
list. If a path 404s or contradicts a control, file `info@bookyou.net`
within 90 days -- such reports are treated as the operating equivalent of
a "noted deficiency" in a formal SOC 2 report and are remediated under
the security policy 14-day window (`site/security/policy.md`).

The 5 trust principles below cover **Security**, **Availability**,
**Processing Integrity**, **Confidentiality**, and **Privacy**. Common
Criteria (CC) are listed first; principle-specific controls follow.

----

## Common Criteria (CC) -- Security baseline

### CC1 Control Environment

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC1.1** Integrity and ethical values | Bookyou株式会社 T8010001213708, representative 梅田茂利, Code of Conduct (Contributor Covenant v2.1) | `CODE_OF_CONDUCT.md` |
| **CC1.2** Board independence and oversight | Solo principal; quarterly transparency report serves as public oversight surface | `site/transparency.html` |
| **CC1.3** Organisational structure, reporting lines, responsibilities | Single principal owns all roles; documented in trust page | `site/trust.html` |
| **CC1.4** Commitment to competence | 梅田茂利 inventor profile, public CV, CONSTITUTION 13.2 anti-pattern register | `docs/_internal/CONSTITUTION.md` (when published) |
| **CC1.5** Accountability for internal control | All deploys gated on signed commits + GHA acceptance criteria CI | `.github/workflows/acceptance_criteria_ci.yml` |

### CC2 Communication and Information

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC2.1** Information quality and relevance | Audit log RSS broadcasts every schema / control change | `site/audit-log.rss` |
| **CC2.2** Internal communication of objectives, responsibilities, controls | All design decisions in markdown under `docs/`; no private wiki | `docs/_internal/` |
| **CC2.3** External communication with stakeholders | Public ToS, Privacy Policy, Tokushoho, ASVS, CAIQ all served from `/legal/` and `/security/` | `site/legal/`, `site/security/` |

### CC3 Risk Assessment

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC3.1** Objectives suitable for risk identification | Published service description on landing + ToS scope clause | `site/index.html`, `docs/compliance/terms_of_service.md` |
| **CC3.2** Risk identification (likelihood + impact) | Threat model + STRIDE table + chaos engineering scenarios | `docs/security/threat_model.md`, `tests/chaos/` |
| **CC3.3** Fraud risk consideration | `feedback_autonomath_fraud_risk` register; misleading-claim detector in copy lint | `scripts/ops/audit_runner_seo.py` (no-overpromise lint) |
| **CC3.4** Change identification | Amendment diff RSS + monthly deep audit catch upstream change | `site/audit-log.rss`, `.github/workflows/monthly-deep-audit.yml` |
| **CC3.5** Risk response (avoid / accept / share / reduce) | Documented per risk in threat model; control map (this file) is the residual register | `docs/compliance/soc2_control_map.md` |

### CC4 Monitoring Activities

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC4.1** Ongoing or separate evaluations | Weekly self-improve runner + monthly deep audit + audit regression gate | `.github/workflows/self-improve-weekly.yml`, `.github/workflows/monthly-deep-audit.yml`, `.github/workflows/audit-regression-gate.yml` |
| **CC4.2** Evaluation of deficiencies and communication | Audit regression gate blocks merge on regression; deficiency report goes to `analytics/` | `.github/workflows/audit-regression-gate.yml` |

### CC5 Control Activities

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC5.1** Selection and development of control activities | Controls are code, not policy text; every control maps to a CI workflow or runtime middleware | `.github/workflows/`, `src/jpintel_mcp/api/` |
| **CC5.2** Technology general controls | CodeQL static analysis weekly; SBOM monthly; dependabot weekly | `.github/workflows/codeql.yml`, `.github/workflows/sbom-publish-monthly.yml` |
| **CC5.3** Deployment via policy and procedure | All prod changes through GHA `deploy.yml`; flyctl secrets through documented runbook | `.github/workflows/deploy.yml`, `docs/_internal/USER_RUNBOOK.md` |

### CC6 Logical and Physical Access Controls

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC6.1** Logical access -- identification and authentication | `jc_` prefix API key + scoped + magic-link + GitHub/Google OAuth | `src/jpintel_mcp/api/me/`, `src/jpintel_mcp/api/auth_github.py`, `src/jpintel_mcp/api/auth_google.py` |
| **CC6.2** New user registration and provisioning | Magic-link only -- no admin provisioning path; rate-limited via `_advisory_lock` | `src/jpintel_mcp/api/me/login_request.py`, `src/jpintel_mcp/api/me/login_verify.py` |
| **CC6.3** User access removal | `DELETE /v1/me` revokes all keys + GDPR Art. 17 erasure | `src/jpintel_mcp/api/me.py` |
| **CC6.4** Physical access -- N/A (no own datacenter) | Fly Tokyo region datacenter, SOC 2 inherited from Fly.io | `https://fly.io/legal/security-and-compliance/` |
| **CC6.5** Logical and physical asset disposal | All persistence in Fly volumes + R2; disposal via flyctl volume destroy + R2 lifecycle 7-year | `fly.toml`, R2 lifecycle policy |
| **CC6.6** Logical access -- remote access (admin) | SSH disabled on production Fly machines; admin access only via `flyctl ssh` + 2FA Fly account | `fly.toml` (no `ssh` port exposed) |
| **CC6.7** Restriction of information assets in transit and at rest | TLS 1.2+ everywhere (CF + Fly enforce); AES-256 at rest (Fly volume + R2 default) | `fly.toml`, `cloudflare-rules.yaml` |
| **CC6.8** Prevention and detection of malicious software | Container base image from Distroless / Python slim, CodeQL scan, dependabot | `Dockerfile`, `.github/workflows/codeql.yml` |

### CC7 System Operations

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC7.1** Detection of new vulnerabilities and unusual activity | Monthly deep audit (audit_runner_seo / geo / html / per_record / ai_bot / ax_4pillars / agent_journey / ax_anti_patterns) + chaos engineering | `.github/workflows/monthly-deep-audit.yml`, `scripts/ops/audit_runner_*.py` |
| **CC7.2** Anomaly detection in system operations | CF AI Audit dump daily + RUM aggregator daily | `scripts/cron/cf_ai_audit_dump.py`, `scripts/ops/rum_aggregator.py` |
| **CC7.3** Evaluation and response to security events | Security policy 72h acknowledgement + 14-day fix window | `site/security/policy.md` |
| **CC7.4** Security incident response | Same policy + audit-log.rss broadcast + transparency report disclosure | `site/security/policy.md`, `site/transparency.html` |
| **CC7.5** System recovery | Daily R2 backup with SHA256 verification + monthly restore drill (RPO 24h / RTO 4h) | `scripts/cron/backup_autonomath.py`, `scripts/cron/backup_jpintel.py`, `scripts/cron/restore_drill_monthly.py`, `.github/workflows/restore-drill-monthly.yml` |

### CC8 Change Management

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC8.1** Change authorisation, design, development, configuration, documentation, testing, approval, implementation | Every change via PR + acceptance CI gate + ruff + pytest 36 file suite | `.github/workflows/acceptance_criteria_ci.yml`, `.github/workflows/test.yml` |

### CC9 Risk Mitigation

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **CC9.1** Risk mitigation for business disruption | RPO 24h / RTO 4h documented; monthly restore drill verifies; webhook dispatcher retry policy | `scripts/cron/restore_drill_monthly.py`, `scripts/cron/dispatch_webhooks.py` |
| **CC9.2** Sub-service / vendor management | 5 sub-processors listed at `site/legal/subprocessors.md`; 30-day objection window via audit-log.rss | `site/legal/subprocessors.md`, `site/audit-log.rss` |

----

## Availability (A)

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **A1.1** Capacity planning and management | Fly autoscale configured (min 1 / max 3); usage_events table tracks billable units for forecasting | `fly.toml`, `src/jpintel_mcp/db/schema.sql` (usage_events) |
| **A1.2** Environmental protection, software, data backup, recovery | Fly Tokyo (no own datacenter); daily R2 backup; monthly restore drill verified | `.github/workflows/nightly-backup.yml`, `.github/workflows/weekly-backup-autonomath.yml`, `.github/workflows/restore-drill-monthly.yml` |
| **A1.3** Recovery testing | Monthly restore drill workflow + monthly health drill | `.github/workflows/restore-drill-monthly.yml`, `.github/workflows/health-drill-monthly.yml`, `scripts/cron/health_drill.py` |

----

## Processing Integrity (PI)

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **PI1.1** Data input quality and completeness | unified_registry Tier system grades input completeness; Tier S/A/B/C exposed | `project_unified_registry_tier` (memory), `src/jpintel_mcp/api/_field_filter.py` |
| **PI1.2** System processing -- correctness and timeliness | Cross-source check + amendment diff detect upstream drift in <24h | `scripts/cron/cross_source_check.py`, `scripts/cron/refresh_amendment_diff.py` |
| **PI1.3** System output -- accuracy and completeness | Audit seal (Merkle anchor) on each response envelope; client can verify | `src/jpintel_mcp/api/_audit_seal.py`, `scripts/cron/merkle_anchor_daily.py` |
| **PI1.4** Data storage -- integrity | SHA256 on every R2 backup; quarterly hash chain anchor publication | `scripts/cron/backup_autonomath.py`, `scripts/cron/merkle_anchor_daily.py` |
| **PI1.5** Modifications to production data -- authorised | Migrations append-only; production gate dashboard daily | `.github/workflows/production-gate-dashboard-daily.yml`, `src/jpintel_mcp/db/schema.sql` |

----

## Confidentiality (C)

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **C1.1** Identification and maintenance of confidential information | License gate per record; metered audit log includes data classification tag | `src/jpintel_mcp/api/_license_gate.py`, `src/jpintel_mcp/api/_audit_log.py` |
| **C1.2** Disposal of confidential information | Erasure endpoint `DELETE /v1/me` removes user records within 30 days; R2 backup retention 7 years for invoicing only | `src/jpintel_mcp/api/me.py`, `docs/compliance/privacy_policy.md` |

----

## Privacy (P)

| Control | Implementation evidence | Audit evidence path |
|---|---|---|
| **P1.1** Privacy notice | Published privacy policy + Tokushoho + landing disclaimer (JP + EN) | `docs/compliance/privacy_policy.md`, `docs/compliance/tokushoho.md`, `docs/compliance/landing_disclaimer.md` |
| **P2.1** Choice and consent | OAuth scope minimisation; email opt-in for webhooks only | `src/jpintel_mcp/api/auth_github.py`, `src/jpintel_mcp/api/auth_google.py` |
| **P3.1** Collection limited to disclosed purposes | usage_events stores timestamp / endpoint / status / billable units only; query body never persisted | `src/jpintel_mcp/db/schema.sql` (usage_events), DPA §3 |
| **P3.2** Personal info accuracy, consent, transparency | Data subject rights doc + DPA Art. 7 + DPA self-service issuance | `docs/compliance/data_subject_rights.md`, `site/legal/dpa_template.pdf`, `functions/dpa_issue.ts` |
| **P4.1** Use, retention, disposal limits | DPA Art. 10: 30-day deletion on termination, 7-year invoicing retention | `site/legal/dpa_template.pdf` (Art. 10) |
| **P5.1** Access to personal info | `GET /v1/me/usage` self-service export | `src/jpintel_mcp/api/me.py` |
| **P6.1** Disclosure to third parties limited | Sub-processor list maintained + 30-day objection window | `site/legal/subprocessors.md`, `site/audit-log.rss` |
| **P7.1** Quality of personal info | Self-service rectification via account portal | `src/jpintel_mcp/api/me.py` |
| **P8.1** Monitoring and enforcement | Audit evidence collector aggregates weekly; quarterly transparency report | `scripts/cron/audit_evidence_collector.py`, `site/transparency.html` |

----

## 個情法 (令和5年改正) coverage matrix

| APPI 条文 | Requirement | SOC 2 control mapping |
|---|---|---|
| 第15条 | 利用目的の特定 | P3.1 |
| 第17条 | 利用目的による制限 | P4.1 |
| 第20条 | 安全管理措置 | CC6.1 -- CC6.8, CC7.x |
| 第21条 | 委託先の監督 | CC9.2 |
| 第22条 | 漏えい等報告 (個情委) | CC7.4, DPA §8 |
| 第23条 | 第三者提供の制限 | P6.1 |
| 第27条 | 越境移転規制 | DPA §9 (All compute + storage in Japan) |
| 第32-39条 | 開示・訂正・利用停止請求 | P5.1, P7.1, CC6.3 |
| 第40条 | 苦情処理 | `site/security/policy.md` 72h ack |

----

## GDPR (EU 2016/679) coverage matrix

| GDPR Article | Requirement | SOC 2 control mapping |
|---|---|---|
| Art. 5 | Lawfulness, fairness, transparency | P1.1, P3.1 |
| Art. 6 | Lawful basis (contract performance for B2B API) | DPA §1, ToS |
| Art. 9 | Special categories -- explicitly excluded | DPA §4 |
| Art. 13-14 | Information to data subjects | P1.1 (privacy policy) |
| Art. 15-22 | Data subject rights (access, rectification, erasure, portability, object) | P5.1, P7.1, CC6.3, `docs/compliance/data_subject_rights.md` |
| Art. 28 | Processor obligations | DPA (self-service `/dpa/issue`) |
| Art. 30 | Records of processing activities | usage_events table + audit-log.rss |
| Art. 32 | Security of processing | CC6.x, CC7.x, A1.x |
| Art. 33-34 | Breach notification | CC7.4, DPA §8 |
| Art. 35 | DPIA (only when high risk -- none currently) | Threat model documents the analysis |
| Art. 44-49 | International transfers | DPA §9 -- no transfers outside Japan required |

----

## Audit evidence collection cadence

| Cadence | Source | Output |
|---|---|---|
| Daily | RUM aggregator, CF AI audit, KPI digest | `analytics/rum_*.jsonl`, `analytics/cf_ai_audit_*.jsonl` |
| Weekly | Audit evidence collector | `analytics/audit_evidence_{ISO_week}.jsonl` |
| Monthly | Deep audit, restore drill, health drill, SBOM | `analytics/audit_baseline_*.json`, GHA artefacts |
| Quarterly | Transparency report publication | `site/transparency.html` |
| Annual | Control map self-review (this document) | `docs/compliance/soc2_control_map.md` (this file) |

----

## Self-attestation limits and honesty caveat

This is a **self-attestation**, not a formal SOC 2 Type II report
issued by an external CPA firm. The differences a buyer should
understand:

1. **No independent CPA review.** Anyone running the public repo at
   `HEAD` can re-derive the evidence, but no external auditor has
   signed an opinion letter. Buyers who require a signed AICPA report
   should not procure jpcite at the current stage.
2. **Solo operator.** Separation-of-duties controls that depend on
   multiple humans (e.g., maker / checker workflows) are implemented
   by CI gates, not by a second human. This is a known limitation; CI
   gate evidence is documented in CC5.x and CC8.1.
3. **Period of operation.** SOC 2 Type II conventionally covers 6-12
   months. jpcite's reporting period rolls forward each quarter; the
   audit-log.rss feed gives buyers a continuous evidence stream rather
   than a discrete annual report.

If a buyer needs a stronger assurance level (e.g., ISMAP or a formal
SOC 2 from a Big-4 CPA firm), email `info@bookyou.net`. We will not
overpromise: an external engagement requires resources we do not
currently allocate, so the answer is most likely a polite decline.

----

## Change log

| Date | Change | By |
|---|---|---|
| 2026-05-11 | Initial control map published (Wave 18 E4) | 梅田茂利 |
