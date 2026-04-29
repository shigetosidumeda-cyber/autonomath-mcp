# i18n Style Guide (P6-E, English V4)

Hand-curation rules for the English half of the 税務会計AI message
catalog (`src/jpintel_mcp/i18n/__init__.py`). Every English string in
the codebase MUST follow this guide. Tests in `tests/test_i18n.py`
enforce the mechanical rules; the prose rules below are reviewed by a
human at PR time.

> **TL;DR**: Stripe / GitHub register. Keep Japanese names for legal
> entities and laws, append the official English in parens at first
> reference. No aggressive translation — the goal is "readable for a
> Japan-based foreign-born founder who already deals with bilingual
> contracts," not "fluent for a US-only audience."

## 1. Tone

- **Professional but friendly.** Match the Stripe / GitHub developer-doc
  register: declarative, direct, free of marketing adjectives.
- **No emoji.** Memory `feedback_no_emoji_in_files` applies.
- **No exclamation marks** in error / status messages. Save them for
  onboarding tips and only when truly warranted.
- **Active voice.** "Verify the source URL" — not "The source URL should
  be verified by the caller."
- **Second person where natural.** "Please retry after a short interval"
  is fine; "The user should retry" is not.

## 2. Capitalisation

- **Sentence case** for all messages.
  - Yes: "No matching programs found."
  - No: "No Matching Programs Found."
- **Tool names stay snake_case** (e.g. `search_tax_incentives`) — they
  are referenced as identifiers, not English nouns.
- **Acronyms are uppercased**: NTA, METI, MHLW, FSA, JFC, SMRJ,
  MCP, REST, API. Never "Nta" or "metI".

## 3. Punctuation

- **ASCII punctuation only.** No 、 。 「 」 ・ in English strings.
  The test `test_english_no_zenkaku_punctuation` enforces this.
- **Period at end of sentences.** Even short ones: "Multiple candidates."
- **Slashes for "and/or" lists** are fine: "ja / en / kana / romaji".
- **Em-dashes (—) ok** but use sparingly — they read as casual.

## 4. Bilingual conventions (the load-bearing part)

### 4.1 Law names

Format: **Japanese name, English transliteration in parens at first
reference**.

- First reference: "中小企業等経営強化法 (SME Management Enhancement Act)"
- Subsequent references in the same response: "中小企業等経営強化法" alone is fine.
- If the response is short enough that the user never sees the first
  reference (e.g. a 1-line empty-state message), repeat the parens form.

Source of truth for English law names: e-Gov 法令検索 English titles
where they exist; otherwise the official ministry transliteration.
Never invent — if no official English exists, keep the Japanese name
only and add a footnote reference to the e-Gov URL.

### 4.2 Public agency names

Format: **Japanese name, official English in parens at first reference**,
then **acronym only** afterwards.

| Japanese | First reference | Subsequent |
|---|---|---|
| 経済産業省 | METI (Ministry of Economy, Trade and Industry) | METI |
| 厚生労働省 | MHLW (Ministry of Health, Labour and Welfare) | MHLW |
| 金融庁 | FSA (Financial Services Agency) | FSA |
| 国税庁 | NTA (National Tax Agency) | NTA |
| 中小企業庁 | SME Agency | SME Agency |
| 日本政策金融公庫 | JFC (Japan Finance Corporation) | JFC |
| 中小機構 | SMRJ (Organization for SME and Regional Innovation, Japan) | SMRJ |
| 環境省 | MOE (Ministry of the Environment) | MOE |
| 国土交通省 | MLIT (Ministry of Land, Infrastructure, Transport and Tourism) | MLIT |
| 農林水産省 | MAFF (Ministry of Agriculture, Forestry and Fisheries) | MAFF |

### 4.3 Program names

- **Do not translate program names.** They are legal entity names.
- Use the Japanese name verbatim. Append a parenthetical descriptor
  only when the response budget allows: "ものづくり補助金 (manufacturing subsidy)".
- Never invent an English brand: "Manufacturing Subsidy 2026" is wrong;
  the actual canonical name is the Japanese one.

### 4.4 Date / time

- **ISO-8601** for machine-readable fields: `2026-04-25`.
- **Spelled-out** for human-facing prose: "April 25, 2026" or
  "25 April 2026" (consistent within a single response).
- **Timezone** is JST or UTC explicitly: "JST month-start (00:00)".
  Never imply timezone from context.

### 4.5 Currency

- **Yen sign + ASCII digits**: "¥3 per request", "¥3.30 tax-included".
- **Comma thousands separator**: "13,578 programs".
- Never use the kanji 円 in English strings.

### 4.6 URL conventions

- Keep host names verbatim: "e-Gov", "j-net21", "mirasapo-plus".
- Lowercase URL paths: "/v1/programs/search", not "/V1/PROGRAMS/SEARCH".
- Inline URLs without anchor text are fine in error messages:
  "See https://zeimu-kaikei.ai/docs/api-reference/."

## 5. Length budget

- **Envelope explanations**: 80-180 chars. Long enough to be useful,
  short enough not to dominate the response.
- **Suggestion strings**: 60-120 chars. They appear in lists.
- **Error user_messages**: 60-120 chars. Must include a recovery hint.
- **Onboarding tips**: 100-200 chars. They are read once.
- **Empty-state messages**: 80-180 chars, MUST point to a primary source.

## 6. Forbidden patterns

- **No "Sorry" / "We apologize"** — apologetic phrasing is service-y;
  Stripe / GitHub register avoids it.
- **No "please contact support"** — there is no support channel.
- **No "free trial" / "upgrade to Pro"** — there is no tier model.
  Memory `project_autonomath_business_model` applies.
- **No machine-translated program content** in the catalog. If a string
  references a specific program, keep the program name in Japanese.
- **No "Japan's first" / "the only" / "best-in-class"** marketing claims.
- **No "official partner" / "endorsed by"** language re. ministries —
  税務会計AI is not endorsed by any ministry.

## 7. Patterns to copy

The scaffolded entries in `src/jpintel_mcp/i18n/__init__.py` are the
canonical examples. When in doubt, mimic them:

```text
ja: "税制特例が十分件数見つかりました。適用期限と対象を確認して引用してください。"
en: "Sufficient tax incentives found. Verify the sunset date (適用期限) and eligible scope before citing."
```

Notice:
- Drops the polite "してください" → imperative "Verify ... before citing."
- Keeps 適用期限 in parens for bilingual readers (Japanese accountants
  reading the English version recognise the term).
- "before citing" carries the hallucination-guard intent without using
  the word "hallucination" (developer jargon, not user copy).

```text
ja: "該当認定は少数のみでした。認定名の正式名称で再検索すると精度が上がります。"
en: "Few certifications matched. Re-querying with the official Japanese name will improve precision."
```

Notice:
- "Few" not "Only a few of them" (Stripe-style economy).
- "the official Japanese name" — explicit that the input must be in JP,
  to head off the failure mode where an English-speaking caller types
  "management innovation plan" and gets zero matches because the
  canonical alias is 経営革新計画.

## 8. Review checklist for new English strings

Before adding an English string to `MESSAGES`:

- [ ] Sentence case, no Title Case
- [ ] No emoji, no zenkaku punctuation
- [ ] Acronyms uppercased (NTA, METI, ...)
- [ ] Law names: JP + English in parens at first reference
- [ ] Agency names: JP + official English + acronym pattern
- [ ] Program names: JP only
- [ ] Currency: ¥ + ASCII digits + comma thousands separator
- [ ] No "sorry", no "support", no "upgrade", no "best-in-class"
- [ ] Length within the budget for that surface
- [ ] Test `test_english_no_zenkaku_punctuation` passes

## 9. References

- Stripe API error reference for tone anchoring.
- GitHub REST API reference for noun-phrase economy.
- e-Gov 法令検索 for official English law titles.
- Memory: `feedback_autonomath_fraud_risk` — translation accuracy is a
  fraud-risk vector, not a polish item.
- Memory: `feedback_no_fake_data` — never invent English entity names
  that do not exist in primary sources.

## 10. llms-full.en.txt generation policy (D6)

The English LLM crawler dump at `site/llms-full.en.txt` is generated by
`scripts/regen_llms_full_en.py` and follows the bilingual conventions in
this guide. Specifically:

- **Structural prose is English.** Header, About, Pricing, Audiences,
  Coverage, and Footer are written in English (~150 lines total). They
  are templated; do not edit the generated file by hand — edit the
  builder functions in the script.
- **Data rows stay Japanese.** `primary_name` (programs), `law_title`
  (laws), `case_title` and `industry_name` (case_studies) are emitted
  verbatim. Translating them mechanically would violate §4.3 (Program
  names) and §6 (Forbidden patterns: "No machine-translated program
  content").
- **Compact pipe-delimited rows.** Same format family as `llms-full.txt`
  but extended with separate `## All Laws` and `## All Case Studies`
  sections. Each row sanitises embedded `|` / CR / LF / TAB so the file
  remains parseable by a one-line splitter.
- **Sibling files.**
  - `site/llms.en.txt` (short index, ~40 lines) points at
    `https://zeimu-kaikei.ai/llms-full.en.txt` as the canonical full dump.
  - `site/llms.txt` and `site/llms-full.txt` remain the Japanese siblings
    and are NOT touched by the en regenerator.
- **robots.txt.** The default policy `User-agent: *` `Allow: /` plus the
  per-bot `Allow: /` for GPTBot / ClaudeBot / PerplexityBot /
  Google-Extended / OAI-SearchBot / CCBot / Applebot / Amazonbot already
  permits crawling of `/llms-full.en.txt`. No bot-specific change needed.
- **No machine translation pipeline.** This script never calls Anthropic
  / OpenAI / any LLM (memory `feedback_autonomath_no_api_use`). The
  English structural sections are hand-written templates that read live
  counts from SQLite and slot them in.
