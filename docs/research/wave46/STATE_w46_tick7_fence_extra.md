# Wave 46 tick7#6 — fence_count 8 法令対応表 + API docs propagation + 残 drift 0 verify

| field | value |
| --- | --- |
| wave | 46 |
| tick | 7#6 |
| branch | feat/jpcite_2026_05_12_wave46_fence_extra_drift |
| base | origin/main @ 40b4ddda0 |
| date | 2026-05-12 |
| precedent | tick5 (fence_registry 8/8 + facts_registry guard) / tick6 (site/ surface 0 drift PR #143) |
| status | DONE (local verify green; PR pending push) |

## Scope

Wave 46 tick6 (PR #143) cleared **site/** surface drift to 0 via `tests/test_fence_site_count.py`. This tick closes the residual non-site drift on three surfaces that the prior tick intentionally left out of scope:

1. **`docs/schemas/client_company_folder_v1_response.schema.json`** — API contract for the client-company folder paid artifact (paid artifact §8.10 minimum). 2 lines pinned a stale `7 業法` boundary while `data/fence_registry.json` advertised `canonical_count: 8`. AI agents consuming this schema would see contradictory guidance (8 fences in registry, 7 enumerated in handoff routing).
2. **`site/connect/*.html`** (4 files: chatgpt / claude-code / codex / cursor) — each connector page surfaced "8 業法 fence" only inside a `<details>` summary with no enumeration. AI agents arriving from claude.ai / chatgpt / cursor.directory / codex had to follow `/legal-fence.html` to discover the law list — Layer 1 (Context) gap.
3. **`scripts/check_publish_text.py`** — fence-count gate comment block still hard-coded `canonical 7 業法` narrative even though the registry-driven `fence_canon` variable has been 8 since tick5. Stale comment risks confusing future operators.

## Drift inventory (task-brief grep, pre-fix)

```text
docs/schemas/client_company_folder_v1_response.schema.json:170 — "7 業法 boundary を踏まえた…"
docs/schemas/client_company_folder_v1_response.schema.json:196 — "7 業法 combined disclaimer envelope。"
scripts/check_fence_count.py:16,37,86 — narrative (intentional, descriptive of 5/6/7 evolution; not enforced)
scripts/check_publish_text.py:173,177  — stale "canonical 7 業法" comment + "historical 6 業法 floor" narrative
```

Non-narrative drift = **2** (schema lines 170 + 196). After fix = **0**.

The `check_*.py` narrative references that survived are the slash-separated `5/6/7 業法` evolution history phrases inside comments — those describe how the detector handles the legacy counts and do not match the enforced `(5\s*\+\s*1|[5-8])\s*業法` regex (slash-separated digits are not `5+1` and not bare `5/6/7/8`). Detector remains drift-free.

A bonus accuracy fix: `site/connect/chatgpt.html` line 185 Custom GPT instructions cited wrong articles (司法書士法§3 / 行政書士法§1の2 / 弁理士法§4 / 宅建業法§12). Updated to the fence_registry canonical articles (§73 / §19 / §75 / 労基§36).

## Changes (6 files / +11 / -10 LOC)

| file | change | LOC |
| --- | --- | --- |
| `docs/schemas/client_company_folder_v1_response.schema.json` | `06_professional_review_handoff.description`: `7 業法` → `8 業法` + `労基§36 (社労士隣接)` enumeration; `_disclaimer.description`: `7 業法 combined disclaimer` → `8 業法 combined disclaimer` | +2 / -2 |
| `site/connect/chatgpt.html` | Custom GPT Instructions L185 fence enumeration corrected to canonical 8 法令 (§52/§72/§73/§19/§27/§47条の2/§75/§36); FAQ `<details>` L207 expanded to enumerate all 8 統一 | +2 / -2 |
| `site/connect/claude-code.html` | FAQ `<details>` L210 expanded to enumerate all 8 法令 | +1 / -1 |
| `site/connect/codex.html` | FAQ `<details>` L166 expanded to enumerate all 8 法令 | +1 / -1 |
| `site/connect/cursor.html` | FAQ `<details>` L211 expanded to enumerate all 8 法令 | +1 / -1 |
| `scripts/check_publish_text.py` | Fence-count gate comment block rewritten: stale `canonical 7 業法` + `historical 6 業法 floor` → `currently 8 業法 post Wave 46 tick5` + `historical 5/6/7 業法 evolution alongside the current canonical` | +4 / -3 |
| `tests/test_fence_count_extra.py` (NEW) | 6 invariants: schema drift 0 / schema 8 業法 declared / connect 8-law enumeration / publish_text comment freshness / fence_registry canonical=8 / facts_registry guard=8 | +146 / 0 |

Total: **7 files / +157 / -10 LOC** (incl. new test file).

## Verify

| check | rc | result |
| --- | --- | --- |
| `python3 scripts/check_fence_count.py` | **0** | `OK: no fence_count drifts (canonical=8)` |
| `pytest tests/test_fence_count_extra.py -v` | **0** | **6/6 PASS** |
| `pytest tests/test_fence_site_count.py tests/test_fence_registry_8_complete.py tests/test_fence_count_extra.py` | 0 | **20/20 PASS** |
| `grep -rn "5 業法\|6 業法\|7 業法" docs/ scripts/ site/companion/ openapi.json` (excluding exempt internal prefixes) | n/a | **4 lines** = 3 narrative refs in `scripts/check_fence_count.py` + 1 narrative ref in `scripts/check_publish_text.py`, all slash-separated `5/6/7 業法` evolution phrases that **do not** match the enforced regex |
| Non-narrative drift count | n/a | **0** |

## PR

`feat/jpcite_2026_05_12_wave46_fence_extra_drift` → `main`

PR #: filled in after `gh pr create` lands.

## Constraints honored

| memory | how |
| --- | --- |
| `feedback_destruction_free_organization` | additive only — schema description expanded with 労基§36; connect `<details>` expanded with full law list; no `rm` / `mv` |
| `feedback_completion_gate_minimal` | scope = 6 files (no 50-doc sweep); narrative comments in `scripts/check_*.py` left as historical context (not enforced); the prior tick5 internal-prefix allowlist remains the boundary |
| `feedback_no_priority_question` | no phasing / no MVP framing; full integrity ship |
| `feedback_no_operator_llm_api` | pure stdlib test (`json` / `re` / `pathlib`), no LLM import |

## Banned actions avoided

- surface text 改ざん: site/connect/* `<details>` content was **expanded** (additional law enumeration), not replaced; `chatgpt.html` line 185 fix corrected wrong-article citations (司法書士法§3 → §73 etc) to match fence_registry — an accuracy fix, not a brand/positioning rewrite
- main worktree: used `/tmp/jpcite-w46-fence-extra` worktree
- 旧 brand: no `zeimu-kaikei.ai` / `autonomath.ai` / `jpintel` revival
- LLM API import: 0 (new test uses only stdlib `json` / `re` / `pathlib`)

## Next

- Wave 46 tick8 candidate (lower priority): mkdocs site mirror under `site/docs/learn/` carries `7 業法` text imported from `docs/learn/ai_layer_education_2026_05_11.md` (internal-exempt source). If a future tick wants to bring the published mirror to 8 業法 too, options are (a) add `site/docs/` to `fence_count_allow_in_context_path_prefix` (additive registry change), or (b) regenerate the mkdocs output after editing the source `.md`. Neither blocks Wave 46 sign-off because the detector already passes (`OK: no fence_count drifts`).
- Step 1 (Discovery) Journey audit remains the only sub-10 step at 9.17 (robots.txt AI-bot welcome + MCP registry hint visibility) — out of scope for this tick.
