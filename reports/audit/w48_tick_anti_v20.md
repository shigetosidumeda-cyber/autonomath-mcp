# jpcite AX Anti-Patterns Audit — 2026-05-12 (automated)

**Total violations**: 0 (target: 0)
**Verdict**: GREEN

| # | Anti-pattern | Violations | Status |
| --- | --- | --- | --- |
| 1 | separate_agent_site_path | 0 | PASS |
| 2 | aria_overuse | 0 | PASS |
| 3 | jsonld_html_divergence | 0 | PASS |
| 4 | captcha_on_api | 0 | PASS |
| 5 | vague_mcp_descriptions | 0 | PASS |
| 6 | browser_only_oauth | 0 | PASS |
| 7 | server_side_session_state | 0 | PASS |
| 8 | js_required_content | 0 | PASS |
| 9 | partially_humanized_ai | 0 | PASS |

## 1. separate_agent_site_path — PASS

_Avoid maintaining a parallel agent-only site (site/agent/, site/ai/ etc.). One canonical site benefits both humans and agents._

- (none)

## 2. aria_overuse — PASS

_role='button' on a non-<button> element when a native <button> would suffice (WebAIM: ARIA-heavy sites score worse on a11y)._

- (none)

## 3. jsonld_html_divergence — PASS

_Schema.org JSON-LD price/availability must match visible HTML body (search-engine penalty + agent-trust loss)._

- (none)

## 4. captcha_on_api — PASS

_API endpoints must not require CAPTCHA. Use scoped tokens + rate limits instead._

- (none)

## 5. vague_mcp_descriptions — PASS

_MCP tool-level description (function docstring of @mcp.tool / @server.tool) must be specific and >= 50 chars; vague placeholders like 'データを取得' are AX-hostile. Parameter Field descriptions are out of scope._

- (none)

## 6. browser_only_oauth — PASS

_Must offer at least one non-browser auth path (API token / device-code / client-credentials)._

- (none)

## 7. server_side_session_state — PASS

_Server-side session-ID cookie state is hard for agent HTTP clients. Prefer stateless token auth._

- (none)

## 8. js_required_content — PASS

_Initial HTML must carry main content; retrieval crawlers do not execute JS. Hydrate, do not bootstrap._

- (none)

## 9. partially_humanized_ai — PASS

_TOAST research: partially-humanized AI is least trusted. Be clearly AI, no mascot / persona / first-person voice._

- (none)
