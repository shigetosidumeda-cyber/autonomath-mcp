# jpcite AX 4 Pillars Audit — 2026-05-11 (automated)

**Total**: 40.00 / 40  
**Average**: 10.00 / 10 (GREEN)  
**Framework**: Biilmann Access/Context/Tools/Orchestration  

| Pillar | Score |
| --- | --- |
| Access | 10.00 / 10 |
| Context | 10.00 / 10 |
| Tools | 10.00 / 10 |
| Orchestration | 10.00 / 10 |

## Access — 10.00 / 10

### Evidence

- [OK] scoped_api_token: 35 file(s) reference X-API-Key/jc_ prefix
- [OK] oauth_github_google: auth_github.py + auth_google.py both present
- [OK] no_captcha_on_api: live probe captcha=no (reachable=False), repo grep hits=0
- [OK] rate_limit_headers: Retry-After + X-RateLimit-* both grep-hit in api/
- [OK] cors_allowlist: CORS wiring in main.py + cors_setup.md runbook present

### Missing items

- (none)

## Context — 10.00 / 10

### Evidence

- [OK] llms_txt_4_files: all 4 present: ['llms.txt', 'llms.en.txt', 'llms-full.txt', 'llms-full.en.txt']
- [OK] schema_org_jsonld: JSON-LD on 4/4 key pages: ['index.html', 'pricing.html', 'about.html', 'facts.html']
- [OK] openapi_3layer: docs/openapi/v1.json + site/openapi.agent.json + site/openapi.agent.gpt30.json
- [OK] hosted_context_files: site/llms-meta.json + agents.json both present
- [OK] companion_md_6plus: 8 .html.md siblings: ['about.html.md', 'compare.html.md', 'data-licensing.html.md', 'facts.html.md', 'index.html.md', 'legal-fence.html.md', 'pricing.html.md', 'transparency.html.md']

### Missing items

- (none)

## Tools — 10.00 / 10

### Evidence

- [OK] mcp_server_live: server.py present + manifest tool_count=139
- [OK] typed_error_envelope: _error_envelope.py present with code/message/docs_url
- [OK] idempotency_key: 19 file(s) reference Idempotency-Key / idempotency_cache
- [OK] mcp_resources_prompts: manifest resource_count=42 + prompt_count=15, modules present, /v1/meta/{resources,prompts} routes wired
- [OK] webmcp_preview: polyfill=True (size=8547B), registerTool=yes, tools=4 (lookup_houjin_360,search_enforcement_cases,search_invoice_registrants,search_jpcite_programs), script_tag_wired_on=2 site root(s)

### Missing items

- (none)

## Orchestration — 10.00 / 10

### Evidence

- [OK] webhook_event_driven: migration_088=True + dispatch_webhooks.py present
- [OK] long_task_async: _bg_task_queue.py present + async/BackgroundTasks usage
- [OK] interrupt_resume_session: mig_087 idempotency_cache + 2 session/state-token grep hits
- [OK] a2a_receiver: a2a.py present (router=/v1/a2a, 5/5 routes), state_token+HMAC 24h, mounted in main.py
- [OK] streamable_http: mcp-server.json _meta.transports=3 values, a2a agent_card advertises stdio+streamable_http, src/doc markers=0/3

### Missing items

- (none)

