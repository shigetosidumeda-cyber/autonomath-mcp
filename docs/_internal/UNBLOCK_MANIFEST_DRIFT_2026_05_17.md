# UNBLOCK — 264 Distribution Manifest Drift → 0 (2026-05-17)

Lane: `lane:solo` (worktree-isolated)
Commit: `4e1cf0404`
Push: `7a8323f53..4e1cf0404 → origin/main` (fast-forward)

## TL;DR

The distribution-manifest drift checker reported **264 false-positive
`forbidden:¥3/req` hits** across `mcp-server.full.json` / `.core.json`
/ `.composition.json`, blocking every commit gated by the
`distribution-manifest-drift` pre-commit hook (FF1 SOT, FF2-FF4, GG1-GG10,
H6 roll-forward fix).

Root cause was a one-line exclude-list omission: the canonical-pricing
exclude in `scripts/distribution_manifest.yml` listed `server.json`
(whose substring covers `mcp-server.json` + `site/mcp-server.json` by
coincidence) but did not list the three audience-sliced derivatives
(`mcp-server.full.json`, `mcp-server.core.json`,
`mcp-server.composition.json`).

The fix adds those three entries to `forbidden_token_exclude_paths`.
Drift checker goes 264 → 0; full test suite for the checker passes.

## Drift categorize (264 hits)

| Surface                          | Hits | Category                                    |
| -------------------------------- | ---: | ------------------------------------------- |
| `mcp-server.full.json`           |  169 | A. Canonical "Cost-saving claim ... ¥3/req" |
| `mcp-server.composition.json`    |   57 | A. Canonical "Cost-saving claim ... ¥3/req" |
| `mcp-server.core.json`           |   38 | A. Canonical "Cost-saving claim ... ¥3/req" |
| **Total**                        |  264 |                                             |

All 264 are **Category A** (legitimate canonical pricing claim, identical
to the trailer also present in `server.json` line 4 / line 86 — which IS
excluded). The forbidden token `¥3/req` is registered to catch stale
*legacy* mentions outside canonical surfaces; it was never intended to
fire on the MCP registry split manifests.

Categories considered and rejected:

* **B. Schema-field price drift** — N/A. The price values themselves are
  consistent (¥3 ex-tax, ¥3.30 tax-included) across `pricing.amount_yen`
  fields. The drift checker's price regex (`PRICE_PATTERNS`) does NOT
  flag these — only the `forbidden_tokens` substring check did.
* **C. Stale registry artifacts** — N/A. Per-tool `Cost-saving claim`
  trailer is a current Wave 51 + V3 pricing rollout artifact, not legacy.
* **D. Forbidden-token policy mismatch (V3 multi-tier)** — partially
  applicable. V3 introduces ¥3 / ¥6 / ¥12 / ¥30 / ¥60 tiers. We did NOT
  add the higher tiers to `forbidden_tokens` (they are not currently
  surfacing as drift), and we did NOT change the `¥3/req` listing
  (it still correctly catches stale legacy strings like `¥3 / req`,
  `¥3/リクエスト`, `JPY 3/req` from older surfaces). The fix is purely
  scoped to the exclude-path list.

## Strategy adopted

**Strategy 1 (exclude-path extension)** — consistent with the YAML's
documented design intent (comment block at lines 264-270 of the
manifest YAML explicitly lists `server.json` + `webmcp_init.js` as
by-design canonical pricing surfaces). The split derivatives are direct
siblings of `server.json`:

* `mcp-server.full.json` — exhaustive (all 184 tools, full descriptions)
* `mcp-server.core.json`  — lean subset (39 tools, context-tight agents)
* `mcp-server.composition.json` — paid Stage-3 composition tools (58 tools)

Each per-tool description carries the canonical trailer:

> Cost-saving claim: Equivalent to ~3-turn Claude Opus 4.7 reasoning
> (~¥54). This tool returns the precomputed/structured answer for
> ¥3/req (tier A). Saving: 94.4% / ¥51/req vs raw Opus call.

This phrase IS the canonical surface for the price; suppressing it
would defeat the AX cost-saving transparency requirement.

**Strategy 2 (manifest regen) — NOT needed.** The manifests already
carry the V3-correct trailer; regenerating them would not change the
text (sync_mcp_public_manifests.py is the source of the trailer). The
drift was purely in the policy file, not the artifact files.

**Strategy 3 (drift-checker context refinement) — NOT needed.** The
checker's line-by-line substring policy is sound; the per-surface
exclude is the right escape hatch.

## Diff

`scripts/distribution_manifest.yml` (13-line append to
`forbidden_token_exclude_paths`):

```yaml
# MCP split manifests (full / core / composition) are direct siblings
# of server.json — same MCP registry SOT, just sliced by audience
# (full = exhaustive, core = lean, composition = paid Stage-3 tools).
# Each per-tool `description` carries the canonical "Cost-saving
# claim: ... ¥3/req (tier A)" trailer added in Wave 51 + V3 pricing
# rollout (2026-05-17). The substring exclude for `server.json`
# already covers `mcp-server.json` / `site/mcp-server.json`; the
# split derivatives need their own entries because their stems
# ("mcp-server.full.json" etc.) do not contain the bare "server.json"
# substring.
- mcp-server.full.json
- mcp-server.core.json
- mcp-server.composition.json
```

## Validation

```
$ python3 scripts/check_distribution_manifest_drift.py
[check_distribution_manifest_drift] OK - distribution manifest matches static surfaces.
exit 0

$ .venv/bin/python -m pytest tests/test_distribution_manifest.py -x -q --timeout=60
6 passed, 1 skipped in 2.05s

$ .venv/bin/python -m ruff check scripts/check_distribution_manifest_drift.py
All checks passed!

$ .venv/bin/python -m ruff format --check scripts/check_distribution_manifest_drift.py
1 file already formatted
```

(Mypy strict shows 2 pre-existing `PyYAML stubs missing` errors on the
unchanged import line; identical before and after the edit. Out of
scope for this UNBLOCK; tracked separately.)

## Post-commit effect

* FF1 SOT doc (Wave 51 V3 pricing) — commit immediately unblocked.
* FF2-FF4 + GG1-GG10 — all lanes with manifest-drift hook gating now
  pass.
* H6 `--no-verify` roll-forward — no longer needed; the manifest-drift
  hook accepts canonical-surface presence as designed.
