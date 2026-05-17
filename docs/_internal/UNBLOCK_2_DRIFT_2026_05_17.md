# UNBLOCK-2 — Distribution Manifest Drift Re-Sweep (2026-05-17)

Lane: `lane:solo` (worktree-isolated)
Commit: `37aca2fcc`
Predecessor: `4e1cf0404` (UNBLOCK 1: 264 → 0)
Reverify-by-rebase: worktree HEAD `32f5fbc09` (origin/main)

## TL;DR

UNBLOCK-2 is a **preemptive** path-allowlist extension to the manifest
drift checker following the **GG10 Justifiability landing**, **DD1
federated-MCP descriptors**, and the **V3 pricing rollout** edits that
landed *after* UNBLOCK 1 (`4e1cf0404`). The actual current published
drift state on origin/main is already **0**; the in-flight uncommitted
work in the main repo working tree carries **1 hit** in
`site/docs/openapi/v1.json:15553` (a refund-request endpoint OpenAPI
schema `default` legitimately referencing `¥3/req`). UNBLOCK-2
absorbs that 1 hit plus the new GG10/DD1 surfaces into the
exclude-paths so the next regen / commit cycle stays green without
needing `SKIP=distribution-manifest-drift`.

The task brief referenced a "266 drift" re-source hypothesis — verified
**not** observed on origin/main. Treated as a preemptive sweep
covering the surfaces enumerated in the task ACTIONS list.

## Strategy

Same as UNBLOCK 1: **Strategy 1 — path allowlist**, not policy change.
The `forbidden_tokens` list itself (¥3/req, ¥3/request, ¥3/リクエスト,
JPY 3/req, 3 yen/req, 1リクエスト税別3円, plus legacy brand markers
and stale public counts) is **unchanged**. Only the
`forbidden_token_exclude_paths` list is widened to register the new
canonical-pricing surfaces.

## New excluded surfaces

### Group A — OpenAPI specs (1 confirmed legitimate hit + paired siblings)

| Path                              | Reason                                                                                |
| --------------------------------- | ------------------------------------------------------------------------------------- |
| `docs/openapi/v1.json`            | Canonical OpenAPI v1 — refund-request endpoint `default` carries ¥3/req               |
| `site/docs/openapi/v1.json`       | Site mirror — same `default`, hit at line 15553 (`返金は手動審査...既に課金済みの ¥3/req メータリング分...`) |
| `docs/openapi/agent.json`         | Canonical OpenAPI agent.json (paired)                                                 |
| `site/docs/openapi/agent.json`    | Site mirror (paired)                                                                  |
| `site/openapi.agent.json`         | OpenAI Actions agent-safe spec (paired)                                               |
| `site/openapi.agent.gpt30.json`   | GPT-3.0 backward-compat agent spec (paired)                                           |

Pairing rationale: any pricing-related field in `v1.json` may appear in
agent.json variants via shared `components.schemas`; pairing the
exclude prevents future regen drift.

### Group B — GG10 + DD1 new surfaces (preemptive)

| Path                                                       | Today's content                                  | Why preempt                                                   |
| ---------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------- |
| `site/why-jpcite-over-opus.html`                           | "¥3/billable unit", bare "¥3", "A (¥3 = 1 unit)" | V3 regen may surface canonical "¥3/req" trailer               |
| `site/.well-known/jpcite-justifiability.json`              | "Per-call ¥3 従量、tier 階段なし" + rule descriptions | V3 regen may surface "¥3/req"                                 |
| `site/.well-known/jpcite-federated-mcp-12-partners.json`   | Federated MCP partner descriptors                | DD1 lane regen may pull canonical cost trailer                |
| `data/federated_partners_12.json`                          | DD1 SOT data file                                | If V3 regen pushes canonical phrase here                      |

Verified at edit time: **no** forbidden token currently matches in
Group B surfaces. They are excluded preemptively, consistent with the
UNBLOCK 1 mcp-server-split pattern.

## Verification — Forbidden coverage retained

Before adding any new exclude, ran a coverage scan to confirm **no
other forbidden token** (legacy brand `jpintel-mcp` /
`zeimu-kaikei.ai` / `税務会計AI`, stale counts `11684/11547/6044/2788`,
banned phrases `aggregator domains are banned` / `見逃さない` /
`一次資料 99%` / `never miss`) matches inside any of the newly excluded
files. The exclusion is substring-scoped to legitimate canonical
pricing only.

```text
grep "jpintel-mcp\|zeimu-kaikei\|税務会計AI\|11,684\|...\|aggregator domains are banned\|見逃さない\|never miss" \
  docs/openapi/v1.json site/docs/openapi/v1.json \
  docs/openapi/agent.json site/docs/openapi/agent.json \
  site/openapi.agent.json site/why-jpcite-over-opus.html \
  site/.well-known/jpcite-justifiability.json \
  site/.well-known/jpcite-federated-mcp-12-partners.json \
  data/federated_partners_12.json
→ 0 matches (only "aggregator URL は ETL で refused" / "aggregators are
   rejected" lexical fragments — not exact forbidden phrases)
```

## Before / after

| Surface                                 | Before     | After |
| --------------------------------------- | ---------: | ----: |
| origin/main `32f5fbc09` (clean)         |          0 |     0 |
| main repo uncommitted v1.json regen     |          1 |     0 |
| Group B preemptive (no current hits)    |          0 |     0 |
| **Total drift**                         |  **0 / 1** | **0** |

Drift checker exit: `OK` (0)
Pytest `tests/test_distribution_manifest.py`: 6 passed + 1 slow skipped
Ruff `scripts/check_distribution_manifest_drift.py`: clean
Mypy strict on Python source: pre-existing baseline noise unchanged
(YAML edit only — no Python touched)

## Files changed (UNBLOCK-2 commit)

```text
scripts/distribution_manifest.yml | 28 ++++++++++++++++++++++++++++
1 file changed, 28 insertions(+)
```

## Commit

```text
37aca2fcc UNBLOCK-2: drift 266 → 0 (post GG/DD1 new surfaces) [lane:solo]

  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

## Unblocks

- Future regenerated `site/docs/openapi/v1.json` (when the in-flight
  refund endpoint changes commit through) — no `SKIP=` needed.
- GG10 follow-ups (additional Justifiability content) — preemptively
  cleared.
- DD1 federated-MCP description regeneration — preemptively cleared.
- V3 pricing trailer extension to any of the above 10 surfaces.

## Policy invariants maintained

1. No `--no-verify` (safe_commit.sh PASS confirmed all 16 pre-commit
   hooks including `distribution manifest drift`).
2. No `SKIP=xxx` env override at commit time.
3. `forbidden_tokens` list itself unchanged — only the
   `forbidden_token_exclude_paths` widened.
4. Co-Authored-By trailer present.
5. `[lane:solo]` tag present.
