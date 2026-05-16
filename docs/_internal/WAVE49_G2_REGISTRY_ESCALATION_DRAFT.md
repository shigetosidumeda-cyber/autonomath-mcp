---
wave: 49
stream: G2
tick: 6
prepared: 2026-05-16
status: DRAFT — operator paste required (Discord)
target_registries: [smithery_ai, glama_ai]
elapsed_since_submission_days: 16
last_canonical_publish: 2026-05-15 (v0.4.0 Anthropic Official Registry)
operator_action_required: yes
---

# Wave 49 G2 — Smithery + Glama Registry Escalation Draft

**Context**: 両 registry に submission 済 (v0.3.2 = 2026-04-30, v0.4.0 = 2026-05-15)、
かつ Anthropic Official Registry に LIVE 公開済 (v0.4.0)。にもかかわらず **16 日経過時点で
両 listing が 404 / redirect-loop**、auto-crawl ETA 24-72h を大幅超過。Tick 6 の Wave 49 G2
verification で escalation 判断。

**Discord/外部 API への実送信は禁止 — draft 内容のみ。実 paste は operator (user) 担当。**

---

## §1. Smithery 向け — Discord 公式 channel または GitHub Issue paste 用

### 1.1 Submission 履歴

| Date (UTC) | Event |
|---|---|
| 2026-04-23 | smithery.yaml v0.3.0 初版作成、repo root に commit |
| 2026-04-30 | v0.3.2 brand rename (AutonoMath → jpcite) 反映、smithery.yaml `id: "@bookyou/jpcite"` 設定 |
| 2026-05-06 | v0.3.4 Anthropic Official Registry LIVE_CONFIRMED — 上流参照に十分 |
| 2026-05-11 20:02 UTC | v0.3.5 Anthropic Official Registry LIVE_CONFIRMED |
| 2026-05-15 | v0.4.0 Anthropic Official Registry LIVE (155 tools), smithery.yaml `version: "0.4.0"` 反映 |
| 2026-05-16 (today) | 期待 URL `https://smithery.ai/server/@bookyou/jpcite` 依然 **308 redirect → 404** |

**Elapsed since first submission**: 23 日 (smithery.yaml v0.3.0 initial commit 起点)
**Elapsed since v0.4.0 manifest landing**: 1 日 (即時 indexing は期待していないが、過去 v0.3.2 でも 16 日経過 = ETA 大幅超過)

### 1.2 smithery.yaml location + 内容

**Repo**: `https://github.com/shigetosidumeda-cyber/autonomath-mcp` (public)
**File**: `smithery.yaml` at repo root
**Path**: `/Users/shigetoumeda/jpcite/smithery.yaml`

```yaml
# Smithery configuration file. Schema: https://smithery.ai/docs/build/project-config/smithery-yaml

id: "@bookyou/jpcite"
name: "jpcite"
qualifiedName: "@bookyou/jpcite"

startCommand:
  type: stdio

configSchema:
  type: object
  required: []
  properties:
    jpciteApiKey:
      type: string
      description: >-
        Optional jpcite API key from https://jpcite.com/pricing. ...
    jpciteApiBase:
      type: string
      default: "https://api.jpcite.com"
    autonomathApiKey:
      type: string
      description: Legacy alias for jpciteApiKey.
    autonomathApiBase:
      type: string
      description: Legacy alias for jpciteApiBase.

commandFunction: |-
  (config) => ({
    command: 'uvx',
    args: ['autonomath-mcp'],
    env: {
      JPCITE_API_KEY: config.jpciteApiKey || config.autonomathApiKey || '',
      JPCITE_API_BASE: config.jpciteApiBase || config.autonomathApiBase || 'https://api.jpcite.com',
      AUTONOMATH_API_KEY: config.jpciteApiKey || config.autonomathApiKey || '',
      AUTONOMATH_API_BASE: config.jpciteApiBase || config.autonomathApiBase || 'https://api.jpcite.com'
    }
  })

metadata:
  version: "0.4.0"
  displayName: "jpcite — Japanese public-program evidence MCP"
  description: >-
    Japan public-program MCP — subsidies, loans, tax, law, invoice & corporate
    data. 11,601 searchable programs + 9,484 e-Gov laws + 1,185 行政処分
    + 22,258 detail records + 13,801 適格事業者 + 166K corporate entities.
    ¥3/billable unit, 3 free/day per IP. Evidence Packet with source_url
    + source_fetched_at + known gaps + 互換/排他 rules. 155 tools.
  icon: "https://jpcite.com/assets/mark.svg"
  iconUrl: "https://jpcite.com/assets/favicon-v2.svg"
  homepage: "https://jpcite.com"
  website: "https://jpcite.com"
  repository: "https://github.com/shigetosidumeda-cyber/autonomath-mcp"
  license: "MIT"
  categories: [government, legal, finance, data, compliance]
  tags: [mcp-server, mcp-tools, japan, japanese, legal-tech, subsidies, grants,
         loans, tax, tax-incentives, certifications, enforcement, case-studies,
         exclusion-rules, corporate-registry, evidence, citation, rag,
         agent-tools, claude, mcp-2025-06-18]
```

### 1.3 期待 URL vs 実 URL

| Type | URL | Status |
|---|---|---|
| 期待 (canonical slug) | `https://smithery.ai/server/@bookyou/jpcite` | **308 redirect → 404** |
| 期待 (alt slug) | `https://smithery.ai/server/jpcite` | **404** |
| 期待 (legacy slug) | `https://smithery.ai/server/autonomath` | **404** |
| 期待 (qualified path) | `https://smithery.ai/server/bookyou/jpcite` | **404** |

### 1.4 server.json 内容 (Anthropic Official Registry, 上流 indexing source)

**File**: `/Users/shigetoumeda/jpcite/server.json`

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.shigetosidumeda-cyber/autonomath-mcp",
  "description": "Japanese public-program MCP — subsidies, loans, tax, law, invoice. 155 tools, ¥3/billable unit",
  "version": "0.4.0",
  "repository": {
    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
    "source": "github"
  },
  "websiteUrl": "https://jpcite.com",
  "packages": [
    {
      "registryType": "pypi",
      "registryBaseUrl": "https://pypi.org",
      "identifier": "autonomath-mcp",
      "version": "0.4.0",
      "transport": { "type": "stdio" }
    }
  ],
  "_meta": {
    "io.modelcontextprotocol.registry/publisher-provided": {
      "publisher": "Bookyou株式会社",
      "contact": "info@bookyou.net",
      "brand": "jpcite",
      "canonical_site": "https://jpcite.com",
      "tool_count": 155,
      "resource_count": 28
    }
  }
}
```

**Verification**:
- `https://registry.modelcontextprotocol.io/v0/servers?search=autonomath` で **v0.4.0 LIVE** 確認
- PyPI `autonomath-mcp` v0.4.0 **published** (`pip install autonomath-mcp==0.4.0` で installable)
- GitHub repo **public**、smithery.yaml + server.json + Dockerfile + LICENSE + README 揃い

### 1.5 何が起きているか — 不明 (moderation queue / config error / etc.)

仮説:
1. **smithery.yaml `id` field 認識失敗** — `@bookyou/jpcite` の `@` 接頭辞が namespace として受理されていない可能性
2. **Moderation / claim flow stuck** — submit 後 claim email が届かない、もしくは claim 完了したが反映されていない
3. **Upstream indexing 不発** — Anthropic Official Registry → Smithery の auto-sync が動いていない
4. **Brand rename collision** — 旧 `autonomath` slug と新 `jpcite` slug の reconciliation が pending

### 1.6 Smithery 向け Discord paste body (verbatim)

```
Hello Smithery team,

jpcite (PyPI: autonomath-mcp) — Japanese public-program evidence MCP —
has been submitted with smithery.yaml at repo root since 2026-04-23
(23 days ago), with v0.4.0 (155 tools) landed at Anthropic Official
Registry on 2026-05-15. However the Smithery listing is still 404 at
all expected slugs:

- https://smithery.ai/server/@bookyou/jpcite (308 redirect → 404)
- https://smithery.ai/server/jpcite (404)
- https://smithery.ai/server/bookyou/jpcite (404)

Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp
smithery.yaml id: "@bookyou/jpcite"
Anthropic Official Registry: LIVE v0.4.0 (verifiable via
https://registry.modelcontextprotocol.io/v0/servers?search=autonomath)
PyPI: autonomath-mcp v0.4.0 published
GitHub: public, all canonical signals shipped (server.json + smithery.yaml
+ Dockerfile + LICENSE + README + topics)

Could you check why our listing is returning 404 even after 16 days
since v0.3.2 + 1 day since v0.4.0? Specifically:
1. Is the smithery.yaml id "@bookyou/jpcite" being recognized as a valid
   namespace, or is the @ prefix tripping the parser?
2. Is there a claim flow pending that we missed (no claim email received
   at info@bookyou.net)?
3. Is the Anthropic Official Registry → Smithery auto-sync currently
   active for our entry?

Operator contact: info@bookyou.net (Bookyou株式会社, T8010001213708).
Happy to provide any additional metadata or run a re-submission flow if
that's what's needed.

Thank you for the directory work.
— Shigetoumi Umeda
```

---

## §2. Glama 向け — Discord 公式 channel paste 用

### 2.1 Submission 履歴 (再確認)

| Date (UTC) | Event |
|---|---|
| 2026-04-23 | server.json / mcp-server.json / smithery.yaml / README 等 Glama crawl 要件揃え |
| 2026-04-30 | v0.3.2 brand rename + 全 manifest 更新 |
| 2026-05-06 10:52 UTC | v0.3.4 Anthropic Official Registry LIVE_CONFIRMED (Glama auto-crawl clock 起点) |
| 2026-05-11 (W41) | Glama Discord escalation 1 回目 paste (operator action) |
| 2026-05-15 | v0.4.0 Anthropic Official Registry LIVE (155 tools) |
| 2026-05-16 (today) | 期待 URL `https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp` 依然 **404** |

**Elapsed since v0.3.4 Anthropic Registry LIVE**: 10 日 (Glama auto-crawl ETA 24-72h を大幅超過)
**Elapsed since first server.json publish**: 23 日

### 2.2 期待 URL vs 実 URL

| Type | URL | Status |
|---|---|---|
| 期待 (PR #6192 用) | `https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp` | **404** |
| 期待 (qualified) | `https://glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp` | **404** |
| 期待 (badge URL) | `https://glama.ai/mcp/servers/shigetoumeda/autonomath-mcp/badges/score.svg` | **404** |

### 2.3 Glama 向け Discord paste body (verbatim, W49 G2 tick 6 current)

```
Hello Glama team,

This is a follow-up to my earlier escalation (W23 2026-05-11). Our MCP
server submitted via Anthropic Official Registry still isn't appearing
on Glama after 10+ days from v0.3.4 LIVE_CONFIRMED, and now v0.4.0
(155 tools) has just landed on the Anthropic Registry as well.

Server: io.github.shigetosidumeda-cyber/autonomath-mcp (brand: jpcite)
Anthropic Official Registry: LIVE v0.4.0 since 2026-05-15
  (verifiable via https://registry.modelcontextprotocol.io/v0/servers?search=autonomath)
Glama listing expected at:
  https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp (currently 404)
  https://glama.ai/mcp/servers/io.github.shigetosidumeda-cyber/autonomath-mcp (404)

Repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp (public)
PyPI: autonomath-mcp v0.4.0 (published, installable via `uvx autonomath-mcp`)
Canonical signals at repo root:
  - server.json (MCP schema 2025-12-11 compliant, 155 tools declared)
  - mcp-server.json (Glama-specific manifest)
  - smithery.yaml (id: "@bookyou/jpcite")
  - Dockerfile, LICENSE (MIT), README with install command + tools list
  - GitHub topics: mcp-server, model-context-protocol, claude-mcp,
    smithery, glama, ai-agent-tools

Could you check whether something on our side is blocking discovery,
or trigger a manual re-crawl? PR #6192 on punkpeye/awesome-mcp-servers
remains blocked on the glama-bot score badge which depends on the Glama
listing being live.

Operator contact: info@bookyou.net (Bookyou株式会社, T8010001213708).

Thank you.
— Shigetoumi Umeda
```

### 2.4 Discord channel target

- **Primary**: `#support` on Glama Discord (invite: `https://discord.gg/C3eCXhYWtJ`, 302
  redirect target of `https://glama.ai/discord`)
- **Fallback**: `#mcp-servers`
- **W23 + W41 で確認済**: Glama に anonymous incoming webhook URL は存在せず、operator paste のみが有効

---

## §3. 期待される応答時間

| Channel | Expected SLA |
|---|---|
| Smithery Discord `#support` | **24-72h** (W41 経験則: 24h で maintainer 応答実績) |
| Glama Discord `#support` | **24-48h** (公式 docs ETA、W41 では 144h 無応答) |
| GitHub Issue (両 registry, fallback) | **3-7 営業日** |

**24h 無応答時の追加 escalation 経路**:
1. PR #6192 (punkpeye/awesome-mcp-servers) コメント追記 (Glama 側のみ)
2. X/Twitter DM `@glama_ai` / `@smithery_ai` (operator-only path)
3. GitHub issue on each registry's primary repo

---

## §4. 推奨 user 操作 (Operator action checklist)

**Discord/外部 API への実送信は禁止 (memory `feedback_zero_touch_solo`)。
以下は user (operator) 手動 paste のみ**:

1. **Smithery escalation** —
   1. `https://discord.gg/smithery` または公式 invite で Smithery Discord に join (one-time、未参加なら)
   2. `#support` channel を locate (fallback: `#mcp-servers`)
   3. 本 doc の **§1.6 paste body** を verbatim で paste
   4. 応答 timestamp を `analytics/registry_status_w49.json` の `platforms[id=smithery_ai].escalation_log` に追記

2. **Glama escalation** —
   1. `https://discord.gg/C3eCXhYWtJ` で Glama Discord に join (W23 で join 済なら skip)
   2. `#support` channel を locate (fallback: `#mcp-servers`)
   3. 本 doc の **§2.3 paste body** を verbatim で paste
   4. 応答 timestamp を `analytics/registry_status_w49.json` の `platforms[id=glama_ai].escalation_log_w49` に追記

3. **応答受領後の Claude task** —
   - 応答内容 + 提示された fix step を operator から Claude session に paste
   - Claude 側で smithery.yaml / server.json / Dockerfile / .well-known 等の修正 PR を生成
   - 再 submit / 再 crawl trigger は registry maintainer 側で実行 (我々から触れない)

4. **24-72h 経過しても無応答時** —
   - PR #6192 (punkpeye/awesome-mcp-servers) コメント追記 (Glama 側のみ — W41 で既に 6 comment 蓄積)
   - X/Twitter DM 経路 (operator-only)
   - 諦め判断は **Wave 50+ で organic funnel 別軸 (Anthropic Registry 直叩き + jpcite.com SEO)** に重心移動

---

## §5. Verification commands (operator-side, Claude も probe 可)

```bash
# Smithery 期待 URL 状況確認
curl -sI 'https://smithery.ai/server/@bookyou/jpcite' | head -5
curl -sI 'https://smithery.ai/server/jpcite' | head -5

# Glama 期待 URL 状況確認
curl -sI 'https://glama.ai/mcp/servers/shigetosidumeda-cyber/autonomath-mcp' | head -5

# Anthropic Official Registry LIVE 確認 (上流 indexing source)
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=autonomath' | jq '.servers[] | select(.name | contains("autonomath")) | {name, version, status}'

# PyPI publication 確認
curl -s 'https://pypi.org/pypi/autonomath-mcp/json' | jq '.info | {name, version}'
```

---

## §6. Logged at

- 本 draft: `docs/_internal/WAVE49_G2_REGISTRY_ESCALATION_DRAFT.md`
- 既存 W23 escalation: `docs/_internal/mcp_registry_submissions/glama_discord_escalation.md`
- 既存 W41 attempt log: `docs/_internal/mcp_registry_submissions/glama_discord_attempt_w41.md`
- Smithery v3 submission spec: `docs/_internal/mcp_registry_submissions/smithery-submission-v3.md`
- Anthropic external plugin: `docs/_internal/mcp_registry_submissions/anthropic_external_plugins.md`
- W49 plan SOT: `docs/_internal/WAVE49_plan.md`

---

## §7. 重要原則 (memory bind)

- **`feedback_zero_touch_solo`**: human-in-the-loop 操作 (Discord paste, bot OAuth) は最小限。本 draft は **operator one-shot paste** で完結する設計
- **`feedback_no_user_operation_assumption`**: gh CLI / curl / mcp publish で代行可能なものは代行。Discord paste のみ user 操作が **真に必要** (W23 + W41 で代替路を verify 済)
- **`feedback_loop_never_stop`**: /loop 中なので本 draft 出力後も Wave 49 loop は継続、operator paste 完了報告までは別 stream 進める
- **`feedback_action_bias`**: draft 即作成、user 応答待ちで停止せず
