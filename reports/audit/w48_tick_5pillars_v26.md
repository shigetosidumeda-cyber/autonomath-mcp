# jpcite AX 5 Pillars Audit — 2026-05-12 (automated)

**Total**: 60.00 / 60
**Average**: 12.00 / 10 (GREEN)
**Framework**: Biilmann 4 (Access/Context/Tools/Orchestration) + Wave 43.3.x Resilience
**Cells**: 36

| Pillar | Score | Cells |
| --- | --- | --- |
| Access | 12.00 / 12 | 6 |
| Context | 12.00 / 12 | 6 |
| Tools | 12.00 / 12 | 6 |
| Orchestration | 12.00 / 12 | 6 |
| Resilience | 12.00 / 12 | 12 |

## Access — 12.00 / 12

### Evidence

- [OK] scoped_api_token: 37 file(s) reference X-API-Key/jc_ prefix
- [OK] oauth_github_google: auth_github.py + auth_google.py both present
- [OK] no_captcha_on_api: live probe captcha=no (reachable=True), repo grep hits=0
- [OK] rate_limit_headers: Retry-After + X-RateLimit-* both grep-hit in api/
- [OK] cors_allowlist: CORS wiring in main.py + cors_setup.md runbook present
- [OK] device_flow_polling_live: RFC 8628 §3.5 4 error cases + success wired, /poll_introspect + /poll_response_spec live, mounted in main.py

### Missing items

- (none)

## Context — 12.00 / 12

### Evidence

- [OK] llms_txt_4_files: all 4 present: ['llms.txt', 'llms.en.txt', 'llms-full.txt', 'llms-full.en.txt']
- [OK] schema_org_jsonld: JSON-LD on 4/4 key pages: ['index.html', 'pricing.html', 'about.html', 'facts.html']
- [OK] openapi_3layer: docs/openapi/v1.json + site/openapi.agent.json + site/openapi.agent.gpt30.json
- [OK] hosted_context_files: site/llms-meta.json + agents.json both present
- [OK] companion_md_6plus: 8 .html.md siblings: ['about.html.md', 'compare.html.md', 'data-licensing.html.md', 'facts.html.md', 'index.html.md', 'legal-fence.html.md', 'pricing.html.md', 'transparency.html.md']
- [OK] dataset_metadata_jsonld_live: 5/5 Dataset JSON-LD payloads in site/_data/, aggregate hasPart=4, ariaDescribedBy markers=5, emitter present

### Missing items

- (none)

## Tools — 12.00 / 12

### Evidence

- [OK] mcp_server_live: server.py present + manifest tool_count=139
- [OK] typed_error_envelope: _error_envelope.py present with code/message/docs_url
- [OK] idempotency_key: 20 file(s) reference Idempotency-Key / idempotency_cache
- [OK] mcp_resources_prompts: manifest resource_count=14 + prompt_count=15, modules present, /v1/meta/{resources,prompts} routes wired
- [OK] webmcp_preview: polyfill=True (size=8547B), registerTool=yes, tools=4 (lookup_houjin_360,search_enforcement_cases,search_invoice_registrants,search_jpcite_programs), script_tag_wired_on=2 site root(s)
- [OK] mcp_resource_polling_live: resource_subscriber.py present (size=8292B), 8/8 API surfaces present, notifications/resources/updated wired, get_registry singleton

### Missing items

- (none)

## Orchestration — 12.00 / 12

### Evidence

- [OK] webhook_event_driven: migration_088=True + dispatch_webhooks.py present
- [OK] long_task_async: _bg_task_queue.py present + async/BackgroundTasks usage
- [OK] interrupt_resume_session: mig_087 idempotency_cache + 3 session/state-token grep hits
- [OK] a2a_receiver: a2a.py present (router=/v1/a2a, 5/5 routes), state_token+HMAC 24h, mounted in main.py
- [OK] streamable_http: mcp-server.json _meta.transports=3 values, a2a agent_card advertises stdio+streamable_http, src/doc markers=1/23
- [OK] a2a_skill_negotiation_live: /v1/a2a/skills + /skills/{name} + /skills/negotiate wired, SKILL_CATALOG (9 skills) + tags + input/output schema present, A2ASkillNegotiation model wired

### Missing items

- (none)

## Resilience — 12.00 / 12

### Evidence

- [OK] 1_idempotency: src/scripts hits=25
- [OK] 2_retry_policy: retry/backoff anchors=11
- [OK] 3_circuit_breaker: circuit_breaker anchors=46
- [OK] 4_dlq: DLQ anchors=2
- [OK] 5_canary: canary/rolling anchors=9
- [OK] 6_degradation: degradation anchors=19
- [OK] 7_failover: failover/DR anchors=51
- [OK] 8_chaos: chaos anchors=5
- [OK] 9_postmortem_v2_base: docs/postmortem entries=3
- [OK] 10_sla_alert: scripts/cron/sla_breach_alert.py: 12 METRICS + Telegram + sidecar
- [OK] 11_postmortem_auto_v2: scripts/ops/postmortem_auto_v2.py: detect+render+PR open
- [OK] 12_backup_verify: scripts/cron/verify_backup_daily.py: r2 list + sha256 + sidecar

### Missing items

- (none)
