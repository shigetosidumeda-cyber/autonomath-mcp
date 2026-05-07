# R8: M&A / 事業承継 制度 matcher (2026-05-07)

Status: shipped to source on 2026-05-07.

## Summary

The cohort revenue model's **M&A pillar** (cohort #1 in CLAUDE.md, paired
with `houjin_watch` migration 088) previously surfaced only via the
generic `search_programs` keyword path. Customers asking the canonical
question — 「後継者問題 / M&A consider する 中小企業 はどの制度を使
えるか?」 — had to manually compose 3+ search calls and stitch
事業承継税制 (法人版特例措置) + 経営承継円滑化法 + 事業承継・引継ぎ
補助金 + 政策金融公庫 事業承継・集約・活性化支援資金 themselves.

This packet promotes 事業承継 to a first-class scenario-tailored
matcher:

- **POST `/v1/succession/match`**
  Body
  `{scenario, current_revenue, employee_count, owner_age}`.
  Closed-vocab `scenario` (`child_inherit | m_and_a | employee_buy_out`).
  Response carries scenario-tailored 制度 chain:
  - `programs` (top 8 補助金 / 融資 from `programs` table)
  - `tax_levers` (curated 事業承継税制 法人版特例措置 + 個人版 + 相続時
    精算課税 / 経営資源集約化税制 / 登録免許税 軽減 / 経営強化税制 D類型)
  - `legal_support` (経営承継円滑化法 + 施行令 + 施行規則 + 相続税法 from
    `laws` table)
  - `next_steps` (advisory checklist; 70歳+ → cliff warn, 大企業 size →
    中小企業者該当性 warn)
  - `provenance` (program_corpus_size, law_corpus_size, primary_source_root)
- **GET `/v1/succession/playbook`**
  Standard 事業承継 playbook (7 step) — 現状把握 → 承継方針 → 経営承継
  円滑化法 認定 → M&A仲介 / 後継者選定 → 補助金申請 → 株式・資産移転 →
  PMI. Includes `advisor_chain` (税理士・公認会計士 + 弁護士 + 司法書士 +
  登録 M&A支援機関 + 都道府県 事業承継・引継ぎ支援センター) + `cliff_dates`
  (2026-03-31 特例承継計画 提出期限 / 2027-12-31 特例措置 適用期限) +
  `primary_sources` (中小企業庁 / 国税庁 / e-Gov / 事業承継・引継ぎ補助金
  公式サイト / M&A支援機関 登録制度).
- 2 MCP tools mirror the REST contract: `match_succession_am` and
  `succession_playbook_am`. Both are gated by
  `AUTONOMATH_SUCCESSION_ENABLED` (default ON).

NO LLM call inside any of the four entry points. Pure SQLite + Python +
curated tax-lever / playbook tables; ¥3 / call billing per the standard
metered surface contract. Anonymous tier shares the 3/日 per-IP cap.

## File map

| Path | Purpose |
| --- | --- |
| `src/jpintel_mcp/api/succession.py` | REST surface (router with both endpoints) + `_TAX_LEVERS_BY_SCENARIO` + `_PLAYBOOK_STEPS` + `_CLIFF_DATES` curated tables |
| `src/jpintel_mcp/mcp/autonomath_tools/succession_tools.py` | MCP impls + tool registration; reuses helpers from the REST module |
| `src/jpintel_mcp/api/main.py` | Router wiring just after `houjin_router` (M&A pillar neighbourhood) |
| `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` (`succession_tools`) | MCP package import + tool register |
| `tests/test_succession_endpoint.py` | 11 tests covering REST envelope shape, scenario branches, validation, paid-key usage logging, v2 envelope |
| `docs/openapi/v1.json` | regenerated; `+2` paths under the new `succession` tag |

## Scenario routing

Each scenario picks (a) different keyword fences over `programs.primary_name`
and (b) a different curated `tax_levers` slice:

| scenario | keyword fence | tax_levers |
| --- | --- | --- |
| `child_inherit` | 事業承継 / 承継 / 後継 | 事業承継税制 法人版特例措置, 個人版, 相続時精算課税 |
| `m_and_a` | M&A / 承継 / 引継ぎ / 事業譲渡 | 経営資源集約化税制, 登録免許税 軽減 (経営承継円滑化法) |
| `employee_buy_out` | 事業承継 / 承継 / MBO / EBO | 事業承継税制 (役員従業員適用), 経営強化税制 D類型 |

`primary_levers` is the human-readable summary of the same routing —
LLM relays render it as the cohort's "first 4 制度を一気に挙げて"
checklist.

## 中小企業者 coarse classifier

`_classify_chusho(revenue, employee_count)` is intentionally simple — it
flips to `False` only when revenue ≥ ¥50億 OR employees ≥ 300名. Real
中小企業基本法 §2 has a 業種別 table (製造業 300名/¥3億, 卸売業 100名
/¥1億, 小売業 50名/¥5千万, サービス 100名/¥5千万). We surface the coarse
boolean as `is_chusho_kigyo` and the `next_steps` array warns the caller
to re-validate against the industry-specific cap. We do NOT block
non-中小企業 inputs — large-cap 同族会社 occasionally apply 事業承継
税制 via 認定要件 carve-outs and the matcher must remain useful.

## Cliff dates

Two cliffs surface in both `match` and `playbook` responses:

- **2026-03-31** — 特例承継計画 提出期限. After this date, callers must
  rely on the standard (non-特例) 事業承継税制 path — 80% 評価額 猶予
  になる substantial regression.
- **2027-12-31** — 特例措置 適用期限 itself (相続・贈与 must complete by
  this date). Subject to 国会審議 延長 — primary source must be checked
  for the latest 中小企業庁 告示.

The 70歳 cliff threshold (`_OWNER_AGE_HIGH_RISK`) is a soft advisory
trigger rather than a hard cliff; it surfaces both cliff dates in the
`next_steps` for any caller who passes `owner_age ≥ 70`.

## §52 / §72 disclaimer envelope

`_disclaimer` is mandatory on every 2xx body. Copy includes:

> 本情報は事業承継に関する一般的な制度紹介であり、個別具体的な税務助言・
> 法的助言ではありません (税理士法 §52 / 弁護士法 §72)。…

Reasoning: 相続税 / 贈与税 申告, 経営承継円滑化法 認定申請, M&A契約
締結 are individually reserved acts. The matcher returns checklist
material — a customer-side 税理士 / 弁護士 / 認定経営革新等支援機関 must
own the final filing.

## DB usage

- jpintel.db `programs` (LIKE 部分一致 over `primary_name`, tier S/A/B/C,
  excluded=0). The query auto-detects whether `audit_quarantined` column
  is present (production schema; migration 167) and adds the filter
  conditionally — keeps tests against pre-167 fixtures green.
- jpintel.db `laws` (4 fixed `law_title` lookups: 中小企業における経営の
  承継の円滑化に関する法律 + 施行令 + 施行規則 + 相続税法).
- NO autonomath.db read — this surface is fully resolvable from
  jpintel.db, which keeps it cheap and fast. The cohort revenue model's
  `houjin_watch` (mig 088) and 採択履歴 axes remain in their dedicated
  endpoints (`/v1/houjin/...`, `/v1/cases/cohort_match`).

## Tests

`tests/test_succession_endpoint.py` (11 tests, all passing on the seeded
jpintel fixture):

1. `test_match_returns_expected_envelope_for_child_inherit`
2. `test_match_m_and_a_returns_m_and_a_levers`
3. `test_match_employee_buy_out_returns_ebo_levers`
4. `test_match_invalid_scenario_returns_422`
5. `test_match_negative_revenue_returns_422`
6. `test_match_owner_age_too_low_returns_422`
7. `test_match_large_enterprise_flag_flips_chusho_false`
8. `test_playbook_returns_seven_steps`
9. `test_playbook_paid_key_logs_usage`
10. `test_match_paid_key_logs_usage`
11. `test_match_v2_envelope`

## Manifests

- `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` /
  `mcp-server.json` `tool_count_default_gates` is intentionally **not**
  bumped — the 2 MCP tools sit on the existing post-manifest float
  alongside DEEP-* / R8 holdovers per the launch CLI plan. Manifest bump
  policy still says "Do not bump tool_count without intentional release."
- `docs/openapi/v1.json` regenerated; +2 paths
  (`/v1/succession/match`, `/v1/succession/playbook`).
- `scripts/distribution_manifest.yml`'s `openapi_path_count` realigns with
  current disk truth as part of this commit so the drift checker remains
  green for downstream lanes.

## Out of scope (future work)

- Per-prefecture variant of `succession.match` — currently the matcher
  surfaces nationwide rows ordered by tier; a `prefecture` filter would
  let 都道府県融資 (兵庫県 事業承継支援貸付 等) bubble up over national
  rows when the caller specifies their HQ.
- Deeper 事業承継税制 法人版 特例措置 calculation — actual 納税猶予額
  estimation requires 評価額 + 持株比率 + 後継者数 inputs which are
  closer to 税理士 territory than DB retrieval. Out of scope per §52
  fence.
- Direct integration with `houjin_watch` (mig 088): a future
  `succession.match_for_houjin/{bangou}` could pull `gBizINFO` corp
  facts to pre-fill `current_revenue` / `employee_count` / `owner_age`
  (the latter requires owner identification we don't currently store).
