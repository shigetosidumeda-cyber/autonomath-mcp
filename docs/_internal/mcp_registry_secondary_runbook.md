---
prepared: 2026-04-25
status: F7 secondary submission runbook (operator-only)
target_launch: 2026-05-06
---

# AutonoMath — Secondary MCP Registry Submission Runbook

Operator-only manual instructions for the **7 secondary registries** below. Primary registries (Official MCP Registry, Smithery, Glama, DXT/Anthropic, MCP Server Finder, MCP Market, MCP Hunt) are covered by **F6** in
`/Users/shigetoumeda/jpintel-mcp/scripts/mcp_registries.md`.

This file documents what F7 cannot auto-submit — manual operator action only. Form-based submissions
are listed verbatim with the URL, required field list, and the canonical reply text to paste.

> **Constraint (per task brief).** Form-based registries are NOT auto-submitted by any agent. The
> only registry where automation is performed is `punkpeye/awesome-mcp-servers` via `gh pr create
> --draft`. Operator must review and mark the PR ready manually.

---

## Canonical paste-text (use everywhere)

| Field | Value |
|-------|-------|
| Display name | `AutonoMath` |
| Slug | `autonomath-mcp` |
| Tagline (≤200 chars) | `Japanese public-program MCP — 11,547 searchable / 13,578 total programs (補助金/融資/税制/認定) + 採択事例 + 融資三軸 + 行政処分 + 法令/税/インボイス, 181 exclusion rules. ¥3/req, 50/月 free.` |
| Long description (≤500) | See `/Users/shigetoumeda/jpintel-mcp/scripts/mcp_registries_submission.json` → `server.description_long` |
| Repo URL | `https://github.com/AutonoMath/autonomath-mcp` |
| Homepage | `https://autonomath.ai` |
| Docs URL | `https://autonomath.ai/docs/` |
| Install command | `uvx autonomath-mcp` |
| Alt install | `pip install autonomath-mcp && autonomath-mcp` |
| License | MIT |
| Language | Python ≥3.11 |
| Protocol | `2025-06-18` |
| Transport | stdio |
| Author | Bookyou株式会社 (T8010001213708) |
| Contact email | `info@bookyou.net` |
| Categories | `government, legal, finance` |
| Tags | `japan, japanese, government, subsidies, grants, loans, tax-incentives, certifications, enforcement, case-studies, exclusion-rules, mcp-server, stdio, python, 補助金, 助成金, 融資, 採択事例, 行政処分, jgrants, e-gov, invoice, mcp-2025-06-18` |
| Pricing | `50 req/月 per IP free (JST 月初 reset, no key) · ¥3/req tax-excl (¥3.30 incl) metered · no tier SKU · no seat fee` |

---

## 1. Cline MCP Marketplace  [GITHUB-PR — operator manual]

| Field | Value |
|-------|-------|
| Submission URL | `https://github.com/cline/mcp-marketplace` |
| Method | GitHub PR adding a JSON entry (operator-only — F7 does **not** auto-PR Cline) |
| Review | maintainer-gated, days |
| ToS link | `https://github.com/cline/mcp-marketplace/blob/main/LICENSE` (MIT — repo terms) |
| ToS notes | Free contribution; PR contributors retain copyright on their entry text. No exclusivity, no revenue share. |

### Operator steps

1. Fork `cline/mcp-marketplace` to your GitHub account.
2. Read `CONTRIBUTING.md` (top of repo) — Cline maintains a JSON index file (`servers.json` or similar). Confirm the schema before editing.
3. Add an entry with the canonical paste-text above.
4. Open a PR titled `Add AutonoMath: 72-tool Japanese gov-data MCP`.
5. PR body should include:
   - 1-2 sentence description (use tagline above)
   - Install command (`uvx autonomath-mcp`)
   - Repo URL
   - Note: "Listed alphabetically; please rebase if conflicts arise."
6. **Do not auto-merge.** Wait for maintainer review.

### Status: NOT AUTO-SUBMITTED — operator manual

---

## 2. PulseMCP  [AUTO-INGEST + FALLBACK FORM]

| Field | Value |
|-------|-------|
| Submission URL | `https://www.pulsemcp.com/submit` |
| Listing URL (target) | `https://www.pulsemcp.com/servers/autonomath-mcp` |
| Method | Auto-ingest from Official MCP Registry; fallback web form if missing >7 days |
| Review | weekly batch, hand-reviewed by founder |
| ToS link | `https://www.pulsemcp.com/terms` |
| ToS notes | Free auto-ingest; no exclusivity. Hand-review for spam protection. |

### Operator steps

1. **First: do nothing.** Wait 7 days after Official MCP Registry publish (F6 step 1, 2026-05-06). PulseMCP ingests automatically.
2. If listing is still missing on 2026-05-13, submit the fallback web form.

### Fallback web form (only if listing missing > 7 days post-launch)

| Field name | Required value |
|-----------|----------------|
| Server name | `AutonoMath` |
| Repo URL | `https://github.com/AutonoMath/autonomath-mcp` |
| Description | Use tagline (≤200 chars) above |
| Category | `government` |
| Submitter email | `info@bookyou.net` |
| Notes (optional) | "Already published to Official MCP Registry under namespace io.github.AutonoMath/autonomath-mcp on 2026-05-06." |

### Status: WAIT 7 DAYS POST-LAUNCH; FALLBACK ONLY IF MISSING

---

## 3. mcp.so  [GITHUB ISSUE / WEB FORM — operator manual]

| Field | Value |
|-------|-------|
| Submission URL | `https://mcp.so/submit` |
| Method | Web form OR GitHub issue against the mcp.so directory repo |
| Review | manual or semi-auto, 2-5 days |
| ToS link | `https://mcp.so/terms` (verify before submission) |
| ToS notes | Free directory listing. Verify ToS does not require exclusivity or paid placement. If it does → skip per memory `feedback_no_cheapskate`. |

### Operator steps

1. Open `https://mcp.so/submit` in browser (do not curl-only verify — form may use JS).
2. Read ToS via the link in form footer; confirm:
   - No paid-placement requirement
   - No exclusivity clause
   - Re-licensing of submission text not required
3. Fill form:
   - Server name: `AutonoMath`
   - Repo URL: `https://github.com/AutonoMath/autonomath-mcp`
   - Description: paste tagline above
   - Category: `government` (or closest)
   - Tags: paste tag list above
   - Email: `info@bookyou.net`
4. Submit; record submission ID in this file under "Status".

### Status: NOT AUTO-SUBMITTED — operator manual

---

## 4. Awesome MCP Servers (`punkpeye/awesome-mcp-servers`)  [PR — F7 AUTO-SUBMITTED]

| Field | Value |
|-------|-------|
| Submission URL | `https://github.com/punkpeye/awesome-mcp-servers` |
| Method | GitHub PR adding 1 line under `### 💰 Finance & Fintech`, alphabetical order |
| Target file | `README.md` |
| Insertion point | Between `armorwallet/armor-crypto-mcp` cluster and `autonsol/sol-mcp` (case-insensitive alphabetical) |
| Review | maintainer-gated, 2-14 days |
| ToS link | repo `LICENSE` (CC0 1.0 Universal) |
| ToS notes | Public-domain dedication; PR contributions follow same. No exclusivity. |

### Entry text (committed to PR)

```
- [AutonoMath/autonomath-mcp](https://github.com/AutonoMath/autonomath-mcp) 🐍 ☁️ 🍎 🪟 🐧 - AutonoMath: 72-tool MCP (39 core + 33 autonomath entity-fact DB = V1 + 4 V4 universal + 5 Phase A + lifecycle/abstract/prerequisite/graph_traverse/snapshot/rule_engine) over Japanese primary-gov data — 11,547 searchable / 13,578 total programs (補助金/融資/税制/認定) + 2,286 採択事例 + 108 融資 (担保/個人保証人/第三者保証人 三軸分解) + 1,185 行政処分 + 503,930 entities + 6.12M facts + laws (e-Gov CC-BY) + tax rulesets (インボイス/電帳法) + 国税庁 invoice registrants. 181 exclusion/prerequisite rules, primary-source lineage, no aggregators. ¥3/req metered (¥3.30 incl. tax); 50 req/月 free per IP. `uvx autonomath-mcp`.
```

### F7 status: DRAFT PR RAISED 2026-04-25

- Fork: `https://github.com/shigetosidumeda-cyber/awesome-mcp-servers`
- Branch: `add-autonomath-mcp`
- PR URL: `https://github.com/punkpeye/awesome-mcp-servers/pull/5371`
- Mode: **draft** (operator must mark ready)

### Operator steps

1. Visit PR: `https://github.com/punkpeye/awesome-mcp-servers/pull/5371`.
2. Verify the entry (line, alphabetical position, emoji legend, all 5 platform emojis).
3. **If repo `AutonoMath/autonomath-mcp` is publicly available with README + LICENSE on 2026-05-06:** click "Ready for review" to lift draft mode.
4. **If repo not public yet:** keep PR in draft until launch day.
5. Respond to maintainer review comments within 24h.

### Status: PR RAISED (draft); operator marks ready post-launch

---

## 5. Cursor Marketplace  [WEB FORM — operator manual]

| Field | Value |
|-------|-------|
| Submission URL | `https://cursor.com/marketplace` (or `https://cursor.directory/plugins`) |
| Method | Web form (plugin submission) |
| Review | manual, 3-10 days |
| ToS link | `https://cursor.com/terms` |
| ToS notes | Cursor Directory/Marketplace listing is free; `cursor.directory` may auto-mirror via Cursor IDE plugin pipeline. Verify no exclusivity clause before submission. |

### Operator steps

1. Open `https://cursor.com/marketplace` and locate the "Submit" or "Plugin Submission" button (path may change between Cursor releases — confirm in IDE settings → Extensions if web is unclear).
2. Fill form using canonical paste-text above. Specifically:
   - Plugin name: `AutonoMath`
   - Slug: `autonomath-mcp`
   - Tagline (<200): use tagline above
   - Category: pick the **two** closest from Cursor's enum (typically `Data` + `Productivity` or `Developer Tools`)
   - Icon (256×256 PNG): `https://autonomath.ai/assets/mcp_preview_1.png` (already 1200×630 — note any resize requirement)
   - Tile (1200×630): `https://autonomath.ai/assets/mcp_preview_1.png`
   - Repo URL: `https://github.com/AutonoMath/autonomath-mcp`
   - Homepage: `https://autonomath.ai`
   - Author: `Bookyou株式会社`
   - Contact: `info@bookyou.net`
   - License: `MIT`
   - Install command: `uvx autonomath-mcp`
   - Pricing: `Free 50 req/month per IP (JST first-of-month reset); ¥3/req tax-exclusive (¥3.30 tax-inclusive) metered. No tier SKUs, no seat fees.`
   - Tags: paste tag list above
3. Provide the `.cursor/mcp.json` snippet (Cursor users copy this into project root):

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

4. Submit; capture screenshot of confirmation; record submission ID below.

### Status: NOT AUTO-SUBMITTED — operator manual

---

## 6. mcpservers.org  [WEB FORM — operator manual]

| Field | Value |
|-------|-------|
| Submission URL | `https://mcpservers.org/submit` |
| Method | Web form (5 fields); Awesome MCP web mirror |
| Review | 3-7 days (free tier) |
| ToS link | `https://mcpservers.org/terms` |
| ToS notes | Free tier listing — **do not buy $39 premium** (memory `feedback_no_cheapskate`: paid placement is a noisy signal, organic only). Verify no exclusivity. |

### Operator steps

1. Open `https://mcpservers.org/submit`.
2. Fill the 5 fields:
   - Name: `AutonoMath`
   - Repo URL: `https://github.com/AutonoMath/autonomath-mcp`
   - Description (paste tagline)
   - Category: `government` or closest
   - Email: `info@bookyou.net`
3. **Do not opt into the $39 premium placement.** Free-tier only.
4. Submit; record submission ID below.

### Status: NOT AUTO-SUBMITTED — operator manual

### Auto-mirror note

mcpservers.org may auto-sync from `punkpeye/awesome-mcp-servers`. If the punkpeye PR (#4 above) merges first, this listing may appear without a manual form submission. Check `https://mcpservers.org/server/autonomath-mcp` 48h after the punkpeye PR merges.

---

## 7. Cursor / Continue / Goose / Zed  [SKIPPED]

Per task brief: **Continue.dev / Goose / Zed: B10 で "not eligible" 確認済**.

| Tool | Reason for skip |
|------|----------------|
| Continue.dev (`hub.continue.dev`) | Public submission path unclear / not eligible per B10 |
| Goose | No public registry / not eligible per B10 |
| Zed | No public MCP registry / not eligible per B10 |

These do **not** require runbook entries. Cursor (registry #5 above) **is** in scope and is covered separately.

---

## Summary — registry status at F7 completion (2026-04-25)

| # | Registry | Method | F7 action | Status |
|---|----------|--------|-----------|--------|
| 1 | Cline MCP Marketplace | GitHub PR | Runbook only — operator manual | **NOT AUTO-SUBMITTED** |
| 2 | PulseMCP | Auto-ingest + fallback form | Runbook only — wait for ingest | **WAIT POST-LAUNCH** |
| 3 | mcp.so | Web form / GitHub issue | Runbook only — operator manual | **NOT AUTO-SUBMITTED** |
| 4 | Awesome MCP Servers | GitHub PR (draft) | **PR raised** | **DRAFT PR #5371** |
| 5 | Cursor Marketplace | Web form | Runbook only — operator manual | **NOT AUTO-SUBMITTED** |
| 6 | mcpservers.org | Web form | Runbook only — operator manual | **NOT AUTO-SUBMITTED** |
| 7 | Continue / Goose / Zed | n/a | n/a (B10 not eligible) | **SKIP** |

---

## Daily check (post-launch verification)

After 2026-05-06 launch, run nightly to confirm listings exist:

```bash
.venv/bin/python scripts/check_registry_listings.py
```

The script (see `scripts/check_registry_listings.py`) curls each registry's listing URL, parses HTTP status + presence of `autonomath-mcp` substring, and emits a JSONL report at `data/registry_status_$(date -I).jsonl`. Use crontab daily at 08:30 JST.

---

## Related files

- `/Users/shigetoumeda/jpintel-mcp/scripts/mcp_registries_submission.json` — canonical structured registry data (F6 source of truth)
- `/Users/shigetoumeda/jpintel-mcp/scripts/mcp_registries.md` — F6 launch-day publish runbook (primary registries)
- `/Users/shigetoumeda/jpintel-mcp/docs/_internal/mcp_registry_submissions/README.md` — F6 internal submission map
- `/Users/shigetoumeda/jpintel-mcp/scripts/check_registry_listings.py` — daily listing-presence checker (created by F7)
- `/Users/shigetoumeda/jpintel-mcp/server.json` — MCP registry manifest (canonical version + description)

---

## Changelog

- 2026-04-25: F7 initial draft. PR #5371 raised (draft) for `punkpeye/awesome-mcp-servers`. 6 form-based / PR-based registries documented with URL + required fields + canonical paste-text + ToS link. Continue/Goose/Zed marked not-eligible per B10.
