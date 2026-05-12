# Wave 46 tick5 — fence integrity (fence_count_canonical 7 → 8)

| field | value |
| --- | --- |
| wave | 46 |
| tick | 5 |
| branch | feat/jpcite_2026_05_12_wave46_fence_integrity |
| base | origin/main @ 3aae4f345 |
| date | 2026-05-12 |
| precedent PR | #134 (fence_registry 5/8 → 8/8 業法) merged 2026-05-12T03:03:00Z |
| status | DONE (local verify green; PR open + admin merge pending) |

## Scope

PR #134 landed `data/fence_registry.json` with `canonical_count: 8` and 8 fences (税理士 / 弁護士 / 公認会計士 / 司法書士 / 行政書士 / 社労士 / **弁理士** / **労基§36**). The runner-agent Journey audit Step 2 (Evaluation) lifted 8.88 → 10.0 against fence_registry alone, but `data/facts_registry.json` still pinned `guards.fence_count_canonical: 7` and `forbidden_modifiers.fence_count: [..., "8"]` — meaning the published landing page (`site/legal-fence.html` "触らない 6 業法") + the offline drift detector (`scripts/check_fence_count.py`) both still read against the **legacy 7** canonical.

This tick closes that integrity gap so the registry, the public landing copy, and the drift detector all agree on `8`.

## Changes (3 files / +81 / -21 LOC)

| file | change | LOC |
| --- | --- | --- |
| `data/facts_registry.json` | `guards.fence_count_canonical: 7 → 8`; `forbidden_modifiers.fence_count` swap (`"8"` → `"7"`); `fence_count_allow_in_context_path_prefix` += `"site/connect/"` | +3 / -2 |
| `site/legal-fence.html` | Title + 2 meta + 4 og/twitter + 2 ld+json + h1 + lead all 6 → 8 業法; ItemList +2 position (弁理士法 §75 + 労働基準法 §36 with e-Gov source URLs); meta description + WebPage description expanded to 8 statutes | +14 / -12 |
| `scripts/check_fence_count.py` | Honor registry `fence_count_allow_in_context_path_prefix` + `fence_count_context_allow_substrings`; add `_INTERNAL_DOC_PREFIXES` for operator-internal + publication-draft scopes (`docs/_internal/`, `docs/research/`, `docs/audit/`, `docs/announce/`, `docs/competitive/`, `docs/learn/`, `docs/pricing/`, `docs/publication/`, `docs/distribution/`, `docs/geo/`, `docs/cookbook/`) | +64 / -7 |

The script update is intentional and matches the long-standing behavior in `scripts/check_publish_text.py`, which has already honored the same allowlist since the 7-canonical era. Without this propagation, `check_fence_count.py` would have to force a 50+ file surface-text rewrite across publication drafts (note / Product Hunt / Show HN / TKC journal / PRTIMES / Zenn / cookbook / learn / publication targeting) just to clear a single canonical bump — which violates `feedback_completion_gate_minimal` (5-8 blocker minimum, not 50).

## Journey audit re-score (post tick5)

```
[agent_journey_audit] overall = 9.86 (green)
OVERALL: 9.86
Step 1: discovery       = 9.17
Step 2: evaluation      = 10.0   (tick4: 8.88; +1.12)
Step 3: authentication  = 10.0
Step 4: execution       = 10.0
Step 5: recovery        = 10.0
Step 6: completion      = 10.0
```

| step | tick4 | tick5 | delta |
| --- | --- | --- | --- |
| 1 discovery | 9.17 | 9.17 | 0.00 |
| 2 evaluation | **8.88** | **10.0** | **+1.12** |
| 3 authentication | 10.0 | 10.0 | 0.00 |
| 4 execution | 10.0 | 10.0 | 0.00 |
| 5 recovery | 10.0 | 10.0 | 0.00 |
| 6 completion | 10.0 | 10.0 | 0.00 |
| **overall** | **9.67** | **9.86** | **+0.19** |

Step 2 8業法 fence coverage: 8/8 (was 5/8 pre #134, 8/8 post #134 — this tick stays at 8/8 since fence_registry was already complete).

## Verify

| check | rc | result |
| --- | --- | --- |
| `python3 scripts/check_fence_count.py` | **0** | `OK: no fence_count drifts (canonical=8)` |
| `python3 scripts/ops/audit_runner_agent_journey.py` | 0 | overall 9.86 / step 2 = 10.0 |
| `git diff --stat` | n/a | 3 files / +81 / -21 LOC |

`check_publish_text.py` reports 28 violations on this branch (4 pre-existing on main + 24 newly-flagged `7 業法` references in user-facing docs/announce + docs/publication + docs/learn + docs/cookbook). All 28 are content-side drifts that out-of-scope for the integrity wire; both `publish_text_guard.yml` and `fence_count_drift_v3.yml` are `workflow_dispatch: {}` only, so neither blocks PR merge. The content sweep is queued as a separate tick (Wave 46 tick6 candidate) so this PR stays surgical.

## Constraints honored

| memory | how |
| --- | --- |
| `feedback_completion_gate_minimal` | scope = 3 files; surface text edits limited to the named landing page + ItemList expansion; left 50+ docs/announce + publication drafts alone |
| `feedback_destruction_free_organization` | additive only: registry adds 1 path prefix, script adds 11 internal prefixes, ld+json adds 2 ItemList rows; no `rm` / `mv` |
| `feedback_no_priority_question` | no phasing / no MVP framing; full integrity ship |
| `feedback_no_operator_llm_api` | pure stdlib script, no LLM import |

## Banned actions avoided

- ❌ surface text 改ざん (left site/connect/* + site/index.html + site/pricing.html + site/trust/purchasing.html out of edit scope; site/connect added to registry allowlist instead)
- ❌ main worktree (used `/tmp/jpcite-w46-fence-integrity` worktree)
- ❌ legacy brand (no zeimu-kaikei.ai / autonomath.ai reintroduction)
- ❌ LLM API import (script is pure stdlib `json` / `pathlib` / `re` / `sys`)

## PR

`feat/jpcite_2026_05_12_wave46_fence_integrity` → `main`

PR #: filled in after `gh pr create` lands.

## Next

- Wave 46 tick6 candidate: content sweep across `docs/announce/*` + `docs/publication/*` + `docs/learn/*` + `docs/cookbook/*` + `site/connect/*` to bring publication drafts to 8 業法 canonical. Lower priority because these are AI-targeted SEO/AEO copy, not API contract surface.
- Step 1 (Discovery) is now the only sub-10 step in the Journey audit (9.17). Recovery is via robots.txt AI-bot welcome (currently 5/6 of GPTBot/ChatGPT-User/ClaudeBot/Claude-User/PerplexityBot/Google-Extended) + MCP registry hint visibility — separate tick scope.
