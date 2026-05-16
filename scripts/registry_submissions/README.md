# Registry Submissions — Manual Pack

Drafted submission packets for the 7 MCP registries that require manual action (per the audit in `scripts/mcp_registries.md` / `scripts/mcp_registries_submission.json`). The other 6 registries (PyPI, npm, MCP Official Registry, DXT, Smithery, Glama) auto-publish or auto-index and are out of scope here.

**Status: DRAFT — do not submit until launch readiness clears (repo creation, PyPI publish, v0.3.2 cut).**

---

## Canonical facts (used in every submission)

| Field | Value |
|---|---|
| Product | jpcite |
| Version | 0.3.2 |
| PyPI package | `autonomath-mcp` |
| Repo (pending creation) | https://github.com/shigetosidumeda-cyber/autonomath-mcp |
| Homepage | https://jpcite.com |
| Docs | https://jpcite.com/docs/ |
| License | MIT |
| Language / runtime | Python >= 3.11 |
| MCP protocol | 2025-06-18 |
| Transport | stdio |
| Install | `uvx autonomath-mcp` (or `pip install autonomath-mcp`) |
| Tool count | **155 at default gates** (3 additional gated off pending fix; 2 further behind `AUTONOMATH_36_KYOTEI_ENABLED`) |
| Pricing | ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive, fully metered) · 3 req/day per IP free (anonymous, JST next-day reset) · no tier SKUs |
| Operator | Bookyou株式会社 (T8010001213708) — 代表 梅田茂利 — info@bookyou.net |

Value proposition note: Evidence Pre-fetch / precomputed intelligence means source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins are prepared for retrieval. Describe it as evidence packaging, not as model-cost savings.

### Honest data counts

- **Programs**: 11,601 searchable (tier S=114 / A=1,340 / B=4,186 / C=5,961). Full table incl. tier X quarantine = 14,472.
- **Adoption case studies**: 2,286
- **Loan products**: 108 (with 3-axis 担保 / 個人保証人 / 第三者保証人 decomposition)
- **Enforcement records (行政処分)**: 1,185
- **Laws**: 6,493 full-text indexed + 9,484 law metadata records (e-Gov CC-BY; name resolver covers all 9,484)
- **Court decisions**: 2,065
- **Bids**: 362
- **Tax rulesets**: 50
- **Invoice registrants (国税庁 PDL v1.0 delta)**: 13,801
- **Sourced compatibility pairs**: 4,300 (status='confirmed'). 44,515 heuristic inferences are flagged status='unknown' and never surfaced as truth — do **not** quote 48,815 as a sourced count.
- **Exclusion / prerequisite rules**: 181

### §52 disclaimer fence (must appear in every submission)

> AutonoMath is information retrieval over published Japanese primary sources. It does not provide tax advice or filing representation (税理士法 §52), legal advice (弁護士法 §72), application representation (行政書士法 §1の2), or labour determinations (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## The 7 submissions

| # | Registry | Submit URL | Method | File | Estimated review |
|---|---|---|---|---|---|
| 1 | Cline mcp-marketplace | <https://github.com/cline/mcp-marketplace> | GitHub PR (fork → edit JSON index → PR) | [`cline_pr.md`](./cline_pr.md) | 3–10 days |
| 2 | Anthropic External Plugin Directory | <https://clau.de/plugin-directory-submission> | Web form | [`anthropic_directory_submission.md`](./anthropic_directory_submission.md) | 1–3 weeks |
| 3 | PulseMCP | <https://www.pulsemcp.com/submit> | Web form (auto-ingests Official Registry; form for corrections / expedited) | [`pulsemcp_submission.md`](./pulsemcp_submission.md) | up to 7 days |
| 4 | mcp.so | <https://mcp.so/submit> | Web form or GitHub issue | [`mcp_so_submission.md`](./mcp_so_submission.md) | 1–7 days |
| 5 | Cursor Marketplace | <https://cursor.com/marketplace> | Web form | [`cursor_submission.md`](./cursor_submission.md) | 7–14 days |
| 6 | MCP Hunt | <https://mcphunt.com> (companion auto-crawler at `mcp-hunt.com` — no submit) | Web form + community upvote | [`mcp_hunt_submission.md`](./mcp_hunt_submission.md) | 1–3 days |
| 7 | MCP Server Finder | mailto:`info@mcpserverfinder.com` | Plain-text email | [`mcp_server_finder_email.md`](./mcp_server_finder_email.md) | 3–14 days |

---

## Time-to-submit-all (operator wall-clock, single sitting)

| # | Registry | Operator wall-clock |
|---|---|---|
| 1 | Cline mcp-marketplace (PR) | 20 min (fork, edit, push, open PR, validate JSON) |
| 2 | Anthropic Directory (form) | 15 min (paste long fields, attach logo) |
| 3 | PulseMCP (form) | 10 min |
| 4 | mcp.so (form) | 10 min |
| 5 | Cursor Marketplace (form, screenshots) | 20 min (3 screenshots required) |
| 6 | MCP Hunt (form + upvote nudge) | 15 min |
| 7 | MCP Server Finder (email) | 5 min |
| **Total** | | **≈ 95 minutes (~1 h 35 m)** |

Add ~10 min buffer for context switches and re-reading each registry's current submission rules immediately before submitting (forms drift without notice). Round to **~1 h 45 m end-to-end**.

After submit, watch wall-clock for review responses runs from 1 day (MCP Hunt) to 3 weeks (Anthropic). The longest tail dominates — plan to monitor for **3 weeks total** before chasing.

---

## Pre-submit gating (do all of these before submitting any of the 7)

1. **Repo public**: `gh repo view shigetosidumeda-cyber/autonomath-mcp --json visibility -q .visibility` returns `PUBLIC`. (Per launch readiness, repo creation is currently pending — every entry points at this URL.)
2. **PyPI package live**: `pip install autonomath-mcp==0.3.2` succeeds.
3. **MCP Official Registry entry live**: `mcp publish server.json` completed; PulseMCP / Glama auto-ingest will start propagating within ~24 h.
4. **README.md authoritative numbers**: matches the canonical facts above (155 tools, 6,493 laws full-text indexed, 9,484 law metadata records, 4,300 sourced compat pairs, ¥3/billable unit tax-exclusive (¥3.30 tax-inclusive) metered).
5. **Disclaimer text matches the fence above** in README, /tos, /privacy, /tokushoho, /legal.
6. **DXT bundle live**: `https://jpcite.com/downloads/autonomath-mcp.mcpb` returns 200.
7. **Logos exist**:
   - `site/static/icons/autonomath-icon-512.png` (square 512)
   - `site/static/og/autonomath-og-1200x630.png` (OG card)

Each per-registry file lists its own pre-flight at the top.

---

## After-submit follow-up template

When a submission is sent, append a row to a tracking table at the bottom of this README:

| Date | Registry | Submission ID / URL / Email msg-id | Status | Notes |
|---|---|---|---|---|

Example:
```
| 2026-05-06 | Cline | https://github.com/cline/mcp-marketplace/pull/1234 | merged 2026-05-09 | requested logo path fix in review, applied |
```

---

## What is NOT in this pack (out of scope)

- **PyPI** — `python -m build && twine upload dist/*` (auto-publish; not manual)
- **npm** — `@autonomath/sdk` will publish via `npm publish` (auto)
- **MCP Official Registry** — `mcp publish server.json` (auto via CLI; see `scripts/mcp_registries.md`)
- **DXT / Claude Desktop Extension** — `.mcpb` is self-distributing from `jpcite.com/downloads/`
- **Smithery** — auto-indexes the public repo via `smithery.yaml`
- **Glama** — auto-indexes the public repo (no submit form)
- **Awesome MCP Servers (punkpeye)** — handled separately as a one-line PR (`scripts/mcp_registries.md` § 8); not in this pack to keep this scope to "manual web/email submissions only"
- **MCP Market (mcpmarket.com)** — also a manual web form; `scripts/mcp_registries.md` already drafts the entry. Not duplicated here.
- **mcpservers.org** — auto-mirrors `punkpeye/awesome-mcp-servers`; covered by the punkpeye PR.

If any of those 6 auto-publish surfaces fail to propagate within a week of launch, a manual fallback may be needed — file a fresh draft under `scripts/registry_submissions/` at that point.

---

## Source documents (don't drift from these)

- `CLAUDE.md` — authoritative tool / data counts
- `pyproject.toml` — version + package metadata
- `server.json` — MCP Official Registry manifest
- `README.md` — public marketing text
- `scripts/mcp_registries.md` — full registry runbook (auto + manual combined)
- `scripts/mcp_registries_submission.json` — machine-readable manifest of all registries

When any of those change (version bump, tool count change, pricing change), every file in this directory must be re-checked against the canonical facts above.
