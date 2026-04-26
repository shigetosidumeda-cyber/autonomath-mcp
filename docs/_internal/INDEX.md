**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

# `docs/_internal/` INDEX

Operator-only runbook index. Excluded from mkdocs build (`exclude_docs: _internal/` in `mkdocs.yml`). Sole reader: 梅田茂利 (Bookyou株式会社).

Authoritative ground truth (defer to CLAUDE.md if drift):
- **Tool count**: 72 (39 jpintel + 33 autonomath, default gates) — verify via `len(mcp._tool_manager.list_tools())`. Legacy literals `55 / 59 / 66 / 67` may appear and are stale.
- **Manifest version**: v0.3.0 (`pyproject.toml` / `server.json` / `mcp-server.json` / `dxt/manifest.json` / `smithery.yaml`). v0.2.0 references in old logs are historical.
- **Programs**: 11,547 searchable (tier S/A/B/C) / 13,578 total rows (incl. tier X quarantine).
- **Pricing**: ¥3/req metered (税込 ¥3.30) + 無料 50/月 anonymous IP quota. **No "Free tier"/"Starter"/"Pro" SKUs exist** for AutonoMath. ("Free tier" mentions of Grafana Cloud / Cloudflare / Fly.io are about *vendor* tiers and remain valid.)
- **Operator**: Bookyou株式会社 (法人番号 T8010001213708), 代表 梅田茂利, info@bookyou.net.

---

## 1. Incident response (4)

| File | Purpose |
|---|---|
| `incident_runbook.md` | §(a)-(f) 障害対応 (outage / leak / DDoS / disk full / Stripe webhook / Fly.io 障害) |
| `launch_kill_switch.md` | 3-lever 緊急停止 (Cloudflare WAF / Fly secret / DNS flip) |
| `launch_war_room.md` | D-Day +24h SLA タイムライン / Slack post順 |
| `fallback_plan.md` | API 全停止時の Cloudflare Pages 静的バナー |

## 2. Operator continuity (3)

| File | Purpose |
|---|---|
| `operators_playbook.md` | 日次運用 (refunds / chargebacks / inquiries) |
| `operator_absence_runbook.md` | 1-14 日不在時 fallback (旅行・短期入院) |
| `operator_succession_runbook.md` | 死亡 / 長期不能 / 廃業時の successor 手順 |

## 3. Billing & legal (5)

| File | Purpose |
|---|---|
| `stripe_tax_setup.md` | Stripe Tax 自動課税の設定 |
| `stripe_webhook_rotation_runbook.md` | `STRIPE_WEBHOOK_SECRET` 定期 + emergency rotation |
| `tokushoho_maintenance_runbook.md` | 特商法 第32条 表示の 6ヶ月レビュー |
| `breach_notification_sop.md` | 個人情報漏えい時の PPC 通知 SOP (24h / 30 日 cycle) |
| `launch_compliance_checklist.md` | 全体 legal posture (特商法 / 景表法 / 個情法 / Stripe Tax) |

## 4. Data & DB (8)

| File | Purpose |
|---|---|
| `dr_backup_runbook.md` | R2 nightly backup + restore (Scenarios 1-3) |
| `data_integrity.md` | FTS5 / vec / programs row 整合性 SLO |
| `autonomath_db_sync_runbook.md` | autonomath.db 8.3 GB Fly volume sync |
| `autonomath_com_dns_runbook.md` | autonomath.com DNS / Cloudflare zone |
| `ingest_automation.md` | 47 都道府県 / e-Gov / 公庫 cron + manual ingest |
| `invoice_registrants_bulk_runbook.md` | NTA 適格事業者 bulk import (PDL v1.0) |
| `archive_inventory_2026-04-25.md` | DB backup file naming / retention |
| `saburoku_kyotei_gate_decision_2026-04-25.md` | 36協定 launch gate 判断記録 |

## 5. Deployment & release (12)

| File | Purpose |
|---|---|
| `deploy_staging.md` | Fly.io staging deploy 手順 |
| `deploy_gotchas.md` | Fly + Cloudflare 既知の罠 (TLS / DNS / build) |
| `dev_setup.md` | 初期 dev 環境構築 (.venv / playwright / pre-commit) |
| `env_setup_guide.md` | 環境変数一覧 + secret 配置 |
| `cloudflare_deploy_log.md` | Cloudflare Pages 履歴 |
| `npm_publish_runbook.md` / `npm_publish_log.md` | npm SDK 公開手順 + 履歴 |
| `pypi_publish_runbook.md` | PyPI `autonomath-mcp` 公開手順 (publish_log は未作成) |
| `hf_publish_runbook.md` / `hf_publish_log.md` | HuggingFace dataset 公開 |
| `sdk_release.md` | SDK (Python + TS) リリース cycle |
| `mcp_registry_runbook.md` | Official MCP Registry 提出 |
| `mcp_registry_secondary_runbook.md` | 7 secondary registries (Cline / Cursor / etc.) |
| `mcp_registry_submissions/` | 各 registry 個別提出 draft |

## 6. Observability (4)

| File | Purpose |
|---|---|
| `observability_dashboard.md` | Grafana Cloud 12-panel layout (Sentry / Fly / Cloudflare 集約) |
| `health_monitoring_runbook.md` | UptimeRobot / `/v1/am/health/deep` |
| `slo.md` | SLO 4 本 (S1 availability / S2 P95 / S3 webhook / S4 freshness) |
| `sentry_audit_2026-04-25.md` | Sentry release 紐付け監査 |

## 7. Performance & capacity (3)

| File | Purpose |
|---|---|
| `perf_baseline_2026-04-25.md` | E2 launch-1w baseline (httpx 1000-req sweep) |
| `perf_baseline_v15_2026-04-25.md` | v15 release ベースライン |
| `capacity_plan.md` | Fly machine sizing + Cloudflare 帯域試算 |

## 8. Growth & customer (8)

| File | Purpose |
|---|---|
| `customer_dev_w5.md` | W5 customer interview script |
| `customer_webhooks_design.md` | 顧客向け webhook 設計 (post-launch) |
| `referral_program_design.md` | リファラル program 設計 (post-launch) |
| `retention_digest.md` | 月次 retention digest メール |
| `content_flywheel.md` | SEO content 拡張サイクル |
| `seo_technical_audit.md` | site/ 技術 SEO 監査 |
| `json_ld_strategy.md` | JSON-LD 構造化データ戦略 |
| `competitive_watch.md` | 競合 / 関連プロダクト監視 |

## 9. Launch (May-2026) coordination (10)

| File | Purpose |
|---|---|
| `launch_dday_matrix.md` | D-Day 時刻表 (07:00-23:00 JST) |
| `launch_followon.md` | D+1 〜 D+14 follow-on 計画 |
| `launch_partner_outreach.md` | パートナー / 紹介ルート |
| `launch_compliance_checklist.md` | 法務 gate (cross-listed in §3) |
| `COORDINATION_2026-04-25.md` | T-11d coordination signaling |
| `PHASE_A_HANDOFF_2026-04-25.md` | Phase A 完了 handoff |
| `PHASE_A_AUDIT_BY_LAUNCH_CLI_2026-04-25.md` | Phase A audit |
| `POST_DEPLOY_PLAN_W5_W8.md` | W5-W8 post-deploy 計画 |
| `GENERALIZATION_ROADMAP.md` | agri niche → 汎用 ロードマップ |
| `templates/` | 顧客対応テンプレ (refund / outage / data correction) |

## 10. UX & site (4)

| File | Purpose |
|---|---|
| `accessibility_audit.md` | a11y 監査 (WCAG AA) |
| `ab_copy_variants.md` | hero / CTA copy A/B variant |
| `conversion_funnel.md` | landing → checkout 導線 |
| `i18n_strategy.md` | EN ページ展開 |
| `email_setup.md` | Postmark transactional email |
| `admin_api.md` | `/v1/admin/*` operator-only endpoints |
| `preview_endpoints.md` | デモ key 不要のプレビュー endpoint |

---

## Stale-claim watch list (top 5 worst)

正本=CLAUDE.md。以下は launch 前に更新済 / もしくは historical marker として残置:

| File | Stale claim | Should be | Status |
|---|---|---|---|
| `perf_baseline_2026-04-25.md` L75-77 | "Tools advertised: 55" / "55-tool manifest" | 72 tools (historical baseline; ベンチ実施時は 55 が事実なので注記済) | annotated |
| `mcp_registry_secondary_runbook.md` L61 | "66-tool Japanese gov-data MCP" | 72-tool | fixed |
| `PHASE_A_HANDOFF_2026-04-25.md` L213-218 | `66 tools` (target row of edits) | 72 tools (post-2026-04-26 audit) | annotated |
| `COORDINATION_2026-04-25.md` L207, L351 | `55→59 tools` migration table | historical, retained | annotated |
| `health_monitoring_runbook.md` L50 | "Free plan limit" (UptimeRobot vendor tier) | OK — *vendor* free tier is valid | no-op |

## Broken cross-reference list (4)

| Source | Target | Status |
|---|---|---|
| `slo.md` L185 | `docs/_internal/slo_log.md` | TBD (launch+30d で作成、現状 missing 想定) |
| `breach_notification_sop.md` L375 | `docs/_internal/legal_contacts.md` | placeholder (operator action item) |
| `npm_publish_runbook.md` L152 / `pypi_publish_runbook.md` L110 | `pypi_publish_log.md` | missing (publish 完了時に作成) |
| `stripe_tax_setup.md` L8 / L168, `deploy_staging.md` L107 / L202 | `docs/launch_compliance_checklist.md`, `docs/fallback_plan.md`, `docs/incident_runbook.md` | パス誤り — 実体は `docs/_internal/` 配下。launch 前に link 修正推奨 |

---

## Conventions

- **Header stamp**: 各 runbook 冒頭に `**Owner**: 梅田茂利 (info@bookyou.net)` + `**Last reviewed**: YYYY-MM-DD` を置く (2026-04-26 INDEX 作成時に主要 runbook へ追加)。
- **No team steps**: solo + zero-touch 前提なので「チーム招集」「on-call ローテ」「DPA 交渉」を含む step は禁止 (memory `feedback_zero_touch_solo`).
- **Re-review**: 3 ヶ月以上 `Last reviewed` が古い runbook は launch 後の月次 audit で再 stamp。
