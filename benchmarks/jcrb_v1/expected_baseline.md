# JCRB-v1 — Expected baseline (pre-registered)

This document is **pre-registered** before any model run lands. We
publish the predicted scores so the gap between prediction and observed
result is visible — both to detect over-claims by jpcite and to detect
data contamination in any submitted model.

## Headline hypothesis

> The same frontier LLM scores **30-50 percentage points higher on
> exact_match** when given jpcite primary-source context than when run
> closed-book on JCRB-v1.

## Predicted scores (per condition × model class)

| Model class | `without_jpcite` exact_match | `with_jpcite` exact_match | Predicted lift |
| --- | --- | --- | --- |
| Frontier LLM (closed-book, no retrieval) | **0.15 – 0.25** | n/a | n/a |
| Frontier LLM + jpcite top-5 context | n/a | **0.55 – 0.70** | **+30 – +50pp** |
| Generic web-search RAG (no jpcite) | 0.30 – 0.45 | n/a | n/a |
| Domain-tuned RAG over MAFF/METI/NTA | 0.50 – 0.65 | n/a | n/a |

The seed leaderboard (`site/benchmark/results.json`) currently lists
estimates of ~0.18 (without) → ~0.62 (with), implying ~+44pp lift.
These are seeds, not validated runs — they will be replaced by the
first real customer submission.

## Per-domain prediction (closed-book, frontier LLM, ja-JP)

| Domain | Predicted closed-book exact_match | Why this number |
| --- | --- | --- |
| `subsidy_eligibility` | 0.10 – 0.20 | Eligibility text rarely appears verbatim in training data; aggregator pollution is highest here. |
| `tax_application` | 0.20 – 0.30 | NTA Q&A is widely scraped, but 経過措置 dates flip annually. |
| `law_citation` | 0.25 – 0.35 | e-Gov 条文番号 is stable; LLMs memorize famous articles (労基法 §36, 独禁法 §19) but miss obscure ones. |
| `adoption_statistics` | 0.10 – 0.20 | 採択率 / 採択数 changes per round; prior-round numbers are often confidently wrong. |
| `enforcement_risk` | 0.10 – 0.20 | 会計検査院 / 公取委 / 国税庁 enforcement disclosures are rarely in training corpora. |

## Per-domain prediction (with jpcite context)

| Domain | Predicted exact_match | Why |
| --- | --- | --- |
| `subsidy_eligibility` | 0.50 – 0.65 | jpcite `programs` table covers both eligibility narrative and `source_url`. |
| `tax_application` | 0.70 – 0.85 | jpcite `tax_rulesets` (50 rows) directly contains `effective_until` cliff dates. |
| `law_citation` | 0.75 – 0.85 | jpcite `laws` (9,484 catalog stubs) returns e-Gov permalink with article count. |
| `adoption_statistics` | 0.40 – 0.55 | Public統計 are sparse in jpcite corpus today; ceiling lower than tax/law. |
| `enforcement_risk` | 0.50 – 0.65 | jpcite `enforcement_cases` (1,185 rows) covers 会計検査院 disclosures. |

## What the lift actually measures

The lift is NOT a measure of jpcite's "raw IQ" — the question texts are
already constructed so the answer is uniquely determined by a single
公開 government URL. The lift measures **how much of the model's
hallucination is closed by feeding it the right primary URL up front**.

Equivalently:

- Lift ≈ 0pp ⇒ either jpcite returned the wrong context, OR the model
  ignored the context, OR the question is too easy (closed-book already
  near 100%).
- Lift > 50pp ⇒ either jpcite is the only path to that fact (non-public
  corpus), OR the closed-book baseline was unusually weak. Both are
  flagged for investigation.

## Failure modes the benchmark deliberately surfaces

1. **Hallucinated URLs**: closed-book models often invent
   `https://www.maff.go.jp/...` paths that 404. `citation_ok` is host-
   match (registrable domain), so a hallucinated path on the right host
   still scores — but a wrong host (e.g. `aggregator.example.com`) does
   not. We accept this leniency because deeper URL liveness verification
   would add a network dep we deliberately avoid in the scorer.
2. **Stale 経過措置 dates**: 5 of the 100 questions hit dates that
   change per fiscal year (2割特例 終了, 80% 控除 終了, 50% 控除 終了,
   etc). Models trained before April 2026 routinely miss these.
3. **Confused 上位法 vs 通達**: closed-book models commonly cite the
   通達番号 instead of the 法律 article. The `expected_value` field
   distinguishes which level we want.

## When to bump to v2

- When the leaderboard has ≥ 5 distinct frontier models with both
  conditions populated.
- When the predicted lift is contradicted (observed lift < 15pp on the
  median frontier model). That would indicate either questions are too
  hard for jpcite to help, or jpcite retrieval quality regressed.
- When `subsidy_eligibility` ceiling exceeds 0.70 even without jpcite —
  that signals contamination of training data with our questions.
