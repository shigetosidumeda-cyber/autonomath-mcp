# EN coverage audit — site/en/

> 2026-04-29 / Auditor: Claude (read-only) / Scope: `site/en/`, `site/*.html`,
> `site/{programs,prefectures,industries,cross,qa,compare,integrations,docs,news,press,blog}/`,
> `site/{llms,sitemap*,robots,rss}.{txt,xml}`. No edits performed.
>
> Inputs: `CLAUDE.md` (canonical product = AutonoMath), `docs/_internal/i18n_strategy.md`
> (original 5-page plan, now superseded), `docs/i18n_style_guide.md` (program-name
> verbatim rule), `docs/english_v4_plan.md` (T+150d expansion plan).

---

## 1. Executive summary

- **Root-page parity** (top-level `site/*.html`): **28 of 30 JP pages have an EN equivalent**
  (93.3%). Missing pairs: `trial.html`, `upgrade.html` — both are transient
  authenticated landing stubs (`noindex`), so the gap is acceptable.
- **Audiences parity**: 6/6 (100%). Brand and translation quality on these pages
  is the strongest in the EN tree.
- **Section-level parity**: **0% for /programs, /prefectures, /industries, /cross,
  /qa, /compare/{vendor}, /integrations, /docs, /news, /press, /blog**. None of
  the JP content shards have an EN render. Total JP pages without EN equivalent:
  **~12,500** (10,952 programs + 470 cross + 1,048 industries + 48 prefectures +
  22 qa subdirs + 10 compare vendors + 4 integration vendor pages + ~32 mkdocs).
- **Brand inconsistency in EN root**: every non-legal EN root page leads with
  the Japanese-script brand "**税務会計AI**" in `<title>`, `og:title`, schema.org
  `name`, `<header>` brand-name span, and prose. Only `tos.html`, `privacy.html`,
  `tokushoho.html` use `AutonoMath` consistently. Audience subpages and `/widget/demo.html`
  also use `AutonoMath`. Conflict: `CLAUDE.md` declares the canonical product
  name **AutonoMath**.
- **EN SEO surfaces missing**: `site/en/llms-full.txt` does not exist (only the
  flat-root mirror `site/llms-full.en.txt` is present). `site/en/sitemap.xml`
  does not exist. `site/en/rss.xml` exists and is high-quality.
- **EN URLs in master sitemaps**: 86 in `sitemap.xml` + 18 in `sitemap-audiences.xml`
  = ~104 EN URLs indexed. The other 7 sitemap shards (programs, prefectures,
  industries, cross, qa, pages, structured) have **0 EN URLs**, mirroring the
  zero EN content in those sections.
- **hreflang link parity**: 28/30 JP root pages have hreflang; the 2 missing
  (`getting-started.html`, `trial.html`) are noindex stubs. 28/28 EN root pages
  have hreflang. Pair integrity is clean for everything that exists.

**Headline coverage number**: counting all crawlable JP HTML files (root + audiences +
programs + prefectures + industries + cross + qa + compare + integrations + news +
press + docs ≈ 12,580), EN equivalents exist for **34** (28 root + 6 audiences) =
**0.27% by page count**. Restricted to "marketing/landing surface" (root + audiences +
widget) the parity is **34/36 = 94.4%**. The gap is entirely in the long-tail
SEO content shards.

---

## 2. Coverage matrix

### 2.1 Root pages (`site/*.html` ↔ `site/en/*.html`)

| Page | JP exists | EN exists | EN brand | Notes |
|---|---|---|---|---|
| 404.html | yes | yes | 税務会計AI (only) | brand drift |
| about.html | yes | yes | 税務会計AI primary, AutonoMath ×2 | brand drift |
| advisors.html | yes | yes | 税務会計AI primary | brand drift |
| alerts-unsubscribe.html | yes | yes | 税務会計AI primary | brand drift |
| alerts.html | yes | yes | 税務会計AI primary | brand drift |
| changelog.html | yes | yes | 税務会計AI primary | brand drift; one stale "jpintel" string in body |
| compare.html | yes | yes | 税務会計AI primary | brand drift |
| confidence.html | yes | yes | 税務会計AI primary | brand drift |
| dashboard.html | yes | yes | 税務会計AI primary | brand drift |
| facts.html | yes | yes | 税務会計AI primary | brand drift |
| getting-started.html | yes (`noindex` redirect stub to `/docs/getting-started/`) | yes (full EN page) | 税務会計AI primary | JP is a noindex stub; EN is the actual content. JP→EN hreflang absent (fine for stub) |
| glossary.html | yes | yes | 税務会計AI primary (47×) | brand drift; 47 mentions is the highest count |
| go.html | yes | yes | 税務会計AI primary | brand drift |
| index.html | yes | yes | 税務会計AI primary (19×) | brand drift on the most-trafficked surface |
| line.html | yes | yes | 税務会計AI primary | brand drift |
| partners.html | yes | yes | 税務会計AI primary | brand drift |
| pricing.html | yes | yes | 税務会計AI primary | brand drift; schema.org Offer.name uses 税務会計AI |
| privacy.html | yes | yes | **AutonoMath** consistently | clean |
| products.html | yes | yes | 税務会計AI primary | brand drift |
| prompts.html | yes | yes | 税務会計AI primary | brand drift |
| sources.html | yes | yes | 税務会計AI primary | brand drift |
| stats.html | yes | yes | 税務会計AI primary | brand drift; one stale `laws_jpintel` table label |
| status.html | yes | yes | 税務会計AI primary | brand drift |
| success.html | yes | yes | 税務会計AI primary | brand drift; one "39 jpintel + 33 autonomath" string in body |
| testimonials.html | yes | yes | 税務会計AI primary | brand drift |
| tokushoho.html | yes | yes | **AutonoMath** consistently | clean (intentional 1-line legal pointer per i18n_strategy.md §3) |
| tos.html | yes | yes | **AutonoMath** consistently | clean |
| trial.html | yes (noindex) | **NO** | n/a | acceptable; transient magic-link landing |
| upgrade.html | yes (noindex) | **NO** | n/a | acceptable; auth-gated upgrade flow |
| widget.html | yes | yes | 税務会計AI primary | brand drift |

### 2.2 Audiences (`site/audiences/` ↔ `site/en/audiences/`)

| Page | JP | EN | Brand | Notes |
|---|---|---|---|---|
| index.html | yes | yes | **AutonoMath** consistent | clean |
| tax-advisor.html | yes | yes | **AutonoMath** consistent | clean |
| admin-scrivener.html | yes | yes | **AutonoMath** consistent | clean |
| smb.html | yes | yes | **AutonoMath** consistent | clean |
| vc.html | yes | yes | **AutonoMath** consistent | clean |
| dev.html | yes | yes | **AutonoMath** consistent | clean |

Audience pages are the gold standard: brand consistent, schema.org valid,
hreflang pairs complete, prose tonality is technical-restrained per
i18n_style_guide.md §6.

### 2.3 Section-level coverage (subdirectories)

| Section | JP page count | EN page count | EN coverage | Notes |
|---|---|---|---|---|
| programs/ | 10,952 | 0 | 0% | per-program SEO pages, all JP. JSON-LD per row is language-agnostic schema.org. |
| prefectures/ | 48 | 0 | 0% | hub pages keyed on prefecture name |
| industries/ | 1,048 | 0 | 0% | JSIC industry × subsidy crosses |
| cross/ | 470 | 0 | 0% | (industry × prefecture × program) cross pages |
| qa/ | 22 subdirs (76 pages per index claim) + 1 root | 0 | 0% | i.e. /qa/invoice, /qa/dencho, /qa/it-subsidy ... |
| compare/ | 10 vendor compare pages (tdb, tsr, gbizinfo, jgrants, mirasapo, moneyforward, freee, navit, nta-invoice, diy-scraping) | 0 | 0% | top-level `compare.html` exists in EN; per-vendor does not |
| integrations/ | 5 (claude-desktop, cursor, cline, openai-custom-gpt, index) | 0 | 0% | this is the **highest-leverage** EN gap for AI dev cohort |
| docs/ (mkdocs) | ~32 sections | 0 | 0% | mkdocs is JP-only; the 5-min quickstart is mirrored at `site/en/getting-started.html` |
| news/ | 1 (index, no posts yet) | 0 | 0% | `am_amendment_diff` cron will populate; structurally no EN renderer |
| press/ | 1 (index, plus .md kit) | 0 | 0% | press kit assets are language-agnostic; index page is JP |
| blog/ | 0 (only .md drafts) | 0 | n/a | not yet rendered |
| widget/ | 1 (demo.html) | 1 (demo.html) | 100% | clean, brand correct |

### 2.4 Infrastructure surfaces

| Surface | JP path | EN path | Status |
|---|---|---|---|
| llms.txt | site/llms.txt (129 lines) | site/en/llms.txt (68 lines) | both exist; EN points to flat-root `llms-full.en.txt`; clean |
| llms-full.txt | site/llms-full.txt (13,806 lines) | **NO `site/en/llms-full.txt`** | EN agents that crawl `/en/llms-full.txt` 404. Flat-root `site/llms-full.en.txt` (22,659 lines) exists and serves the same role. Either move/copy or document the convention. |
| llms.en.txt (flat mirror) | n/a | site/llms.en.txt (67 lines) | exists |
| llms-full.en.txt (flat mirror) | n/a | site/llms-full.en.txt (22,659 lines) | exists, longer than JP edition (probably stale numbers) |
| sitemap.xml | site/sitemap.xml (74 locs, 86 EN URLs) | **NO** | EN URLs live inside the JP sitemap shards via `xhtml:link rel="alternate" hreflang="en"`. Acceptable per Google's hreflang spec; not a defect, just confirm. |
| sitemap-audiences.xml | yes (12 locs, 18 EN refs) | n/a | EN URLs included as alternates |
| rss.xml | site/rss.xml (54 lines, JP) | site/en/rss.xml (54 lines, EN) | clean parity |
| robots.txt | yes | n/a | `Allow: /en/` explicit; no EN-only Disallow rules |

---

## 3. Brand canonical recommendation

### 3.1 Findings

`CLAUDE.md` is unambiguous:

> **Product**: AutonoMath (PyPI package: `autonomath-mcp`)
> **Operator**: Bookyou株式会社

But every EN root page (except the 3 legal ones) uses **税務会計AI** as the
visible brand in `<title>`, `og:title`, `<header>` and most prose. The
audiences/, widget/, and legal pages use **AutonoMath**. Net result: a
visitor landing on `/en/index.html` reads "税務会計AI" (Japanese kanji),
clicks through to `/en/audiences/dev.html` and reads "AutonoMath", clicks
to `/en/tos.html` and reads "AutonoMath" again. Three brand identities
on the same English visit.

`docs/i18n_style_guide.md` §4.something says "Never invent an English brand"
for **program names** ("Manufacturing Subsidy 2026" wrong, ものづくり補助金
right). That rule applies to subsidy/law/program identifiers — not to the
product brand itself. The product is `AutonoMath` per `CLAUDE.md`,
`pyproject.toml` (`name = "autonomath-mcp"`), `server.json`, `dxt/manifest.json`,
and the PyPI package.

### 3.2 Recommendation: **AutonoMath as the single English-side brand**

- All EN `<title>`, `og:title`, `twitter:title`, `<header>` `brand-name`
  span, schema.org `name`, and prose body switch from `税務会計AI` to
  `AutonoMath` (no romanization "Zeimu Kaikei AI" — that's neither the
  PyPI name nor the trademark-aware name and would invent a third brand).
- Keep `税務会計AI` as a parenthetical descriptor on the EN about page
  ("AutonoMath (税務会計AI in Japanese)") so JP-aware visitors recognize
  continuity.
- Domain `zeimu-kaikei.ai` does not need a rename — the domain ≠ brand.
- Schema.org `Organization.alternateName` can carry "税務会計AI" so
  bilingual structured data still surfaces both for crawler disambiguation.
- JP side stays `税務会計AI` as primary (already correct).

This keeps:
- one English brand (AutonoMath) — searchable, pronounceable, trademark-aware
  per the jpintel/Intel collision memory;
- one Japanese brand (税務会計AI) — already aligned with Stripe product,
  invoicing, and existing JP-language SEO;
- legal pages keep AutonoMath (already correct, no change);
- audiences/widget keep AutonoMath (already correct, no change);
- only the EN root pages and EN llms.txt structured-data blocks need to flip.

### 3.3 Why not "Zeimu Kaikei AI"

Three independent reasons:
1. Not the PyPI package name. Package = `autonomath-mcp`, console scripts =
   `autonomath-api`, `autonomath-mcp`. Romanizing the JP brand creates a
   third identity nobody can `pip install`.
2. Hepburn romanization of "税務会計" varies (zeimu-kaikei vs. zeimukaikei),
   creating ambiguity in citations.
3. Memory `feedback_no_trademark_registration.md` says "trademark conflicts
   are resolved via rename, not registration". `AutonoMath` is the rename
   already made; reverting to a romanized JP brand re-opens the door.

---

## 4. Top 5 EN content gaps (P0)

Ranked by SEO + LLM-citation impact. Numbered tasks, no time estimates per
memory `feedback_no_priority_question`.

### Gap 1: `/en/integrations/` (5 pages)

- **What's missing**: EN renders of `/integrations/{claude-desktop,cursor,cline,openai-custom-gpt,index}.html`.
- **Why P0**: AI-dev cohort is the highest-LTV segment per `audiences/dev.html`
  framing. Claude Desktop / Cursor / Cline / Custom GPT users predominantly
  English-default. JP-only integration pages forfeit citation in English
  dev-tool docs and forum threads. These pages are also the canonical
  "how to add AutonoMath to {tool}" surfaces — first impressions of MCP
  integration land here.
- **Effort**: 1 agent task (5 pages, structurally clones of JP, terminology
  is mostly already English in JP source — Claude Desktop, MCP, etc.).

### Gap 2: `site/en/llms-full.txt`

- **What's missing**: A copy/symlink of `site/llms-full.en.txt` at
  `site/en/llms-full.txt` so that crawlers walking `/en/` find both
  `llms.txt` and `llms-full.txt` co-located, matching the JP root pattern.
- **Why P0**: the EN `llms.txt` references the flat-root mirror
  (`https://zeimu-kaikei.ai/llms-full.en.txt`), but LLM agents that
  blindly walk `<base>/llms-full.txt` (a common heuristic per llmstxt.org
  emerging convention) will 404 inside `/en/`.
- **Effort**: 1 agent task (single-file copy, plus updating `site/en/llms.txt`
  line 9 to point at the new co-located path).

### Gap 3: `/en/compare/{vendor}/` (10 pages)

- **What's missing**: EN renders of `/compare/{tdb,tsr,gbizinfo,jgrants,
  mirasapo,moneyforward,freee,navit,nta-invoice,diy-scraping}/`. The
  top-level `/en/compare.html` exists, but the per-vendor deep pages do not.
- **Why P0**: comparative-search queries from EN-language M&A / VC / DD
  tooling buyers ("AutonoMath vs gBizINFO", "Japanese SMB API vs jGrants")
  land here. These are also the highest-intent SEO terms — buyer is past
  awareness, in evaluation. Without EN versions, English-language
  comparative search ranks JP page or competitor.
- **Effort**: 1 agent task (10 pages, well-structured templates already exist).

### Gap 4: `/en/qa/` (22 hub pages + index)

- **What's missing**: EN renders of QA hub pages by topic (invoice, dencho,
  it-subsidy, monozukuri-subsidy, jizokuka-subsidy, restructuring-subsidy,
  jfc, hojin-tax, shotoku-tax-tax-related, kakushin-plan, keieikyoka-tax,
  keieiryoku-plan, sentan-plan, shouhi-tax, shoukei, toushi-tax, chinage-tax,
  rd-tax, gx, law, bcp-plan, nintei-shien). Plus 76 sub-pages per the JP
  index meta-description.
- **Why P0**: Q&A pages are the **single highest LLM-citation surface**
  for English-language agents answering "what is the Japanese invoice
  system?", "how does e-bookkeeping law work?", "what is monozukuri subsidy?"
  These are exactly the queries agents serve to non-Japanese-speaking users
  who need the answer in English. Currently zero coverage.
- **Effort**: 1 agent task per ~5-7 hub pages = ~4 agent tasks for the
  full set. Could be parallelized.

### Gap 5: Brand reconciliation across 25 EN root pages

- **What's missing**: 25 EN root pages still lead with `税務会計AI` instead
  of `AutonoMath` in `<title>`, `og:title`, `<header>`, schema.org `name`,
  and prose. (Pages already correct: privacy, tos, tokushoho, plus all
  audiences/ and widget/.)
- **Why P0**: brand inconsistency directly hurts:
  - **English SEO**: Google sees three different brand mentions and splits
    authority across "税務会計AI", "AutonoMath", and the bare domain.
  - **LLM citation**: when an agent cites the source, it picks one brand
    string semi-randomly. Inconsistent citations weaken brand recall.
  - **Trademark posture**: per `project_jpintel_trademark_intel_risk` memory,
    the rename to AutonoMath was the resolution. Reverting half the surface
    to a Japanese-script brand undermines the rename.
  - **Pricing/Stripe alignment**: schema.org Offer.name uses `税務会計AI` on
    EN pricing.html — buyers reading EN content but seeing JP brand on the
    Offer get a coherence break at the moment of conversion intent.
- **Effort**: 1 agent task (mechanical sed-style replacement across 25
  files; requires care with the 3 legal pages already correct, plus
  preserving JP-language quoted strings inside the schema.org `description`
  fields where 税務会計AI appears as part of a JP product description).

---

## 5. Other findings (not P0, but worth tracking)

- **Stale "jpintel" strings inside EN body text** (5 files): `success.html`,
  `changelog.html`, `getting-started.html`, `about.html`, `stats.html`. Most
  are factual ("39 jpintel + 33 autonomath" tool group naming, which IS the
  internal bucket name and arguably correct). The two definite drifts are
  `stats.html` line 167 + 235 (`laws_jpintel` label / array element — refers
  to a DB table that internal code calls `laws`, never `laws_jpintel`) and
  `changelog.html` line 206 (a self-referential note about removing a
  "leftover jpintel string"). These are technical, not user-blocker.
- **EN `getting-started.html` uses tool-count numbers (72 tools) that
  match prod, but `/en/about.html` line 136 still says `66 (38 jpintel +
  28 autonomath)`** — drift between EN pages on tool count. Reconcile to
  68 (default-gate count per CLAUDE.md) or 72 (counting broken-tool gates
  flipped).
- **`docs/_internal/i18n_strategy.md` §1 says "EN surface = 5 pages"** but
  reality is 28 + 6 + 1 = 35 EN pages. The strategy doc has been overtaken
  by events. Either update the doc or accept the doc as historical.
- **`og:image` for EN pages is the same `/assets/og.png` as JP**. If that
  image has Japanese text, EN social shares show JP text. Did not open
  the PNG; flagged as worth a visual check.
- **`<html lang="en">` is correctly set on all 28 EN root pages** and on
  audiences/. Good.
- **No `/en/` dedicated sitemap** (`site/en/sitemap.xml` does not exist).
  Per Google's spec, hreflang alternates inside the JP sitemap shards
  is sufficient and correctly implemented. Not a defect; just confirming
  the design choice.
- **No EN render of `/news/` or `/press/`**. News is cron-generated and
  empty; press is mostly assets. Low priority but a future expansion would
  want EN news for English-language amendment alerts.
- **EN privacy/tos/tokushoho do not link to JP equivalents in the prose**
  (only via hreflang). For a visitor who arrives at `/en/tokushoho.html` and
  sees the 1-line "see JP version" stub, the link path is fine. For
  `/en/tos.html` and `/en/privacy.html` (which are full English documents),
  consider whether to add a "Japanese version is the controlling document"
  clause — this is a legal-review item, not a translation gap.

---

## 6. Coverage % summary (for the dashboard)

| Bucket | JP | EN | EN/JP % |
|---|---|---|---|
| Root pages (`site/*.html`) | 30 | 28 | 93.3% |
| Audiences | 6 | 6 | 100% |
| Widget | 1 | 1 | 100% |
| **Marketing surface (above 3 buckets)** | **37** | **35** | **94.6%** |
| Programs (per-program SEO) | 10,952 | 0 | 0% |
| Prefectures hubs | 48 | 0 | 0% |
| Industries hubs | 1,048 | 0 | 0% |
| Cross hubs (industry × pref × program) | 470 | 0 | 0% |
| QA hubs + sub-pages | ~76 (claim) | 0 | 0% |
| Compare per-vendor | 10 | 0 | 0% |
| Integrations | 5 | 0 | 0% |
| Mkdocs (`site/docs/`) | ~32 sections | 0 | 0% |
| News / Press | ~2 | 0 | 0% |
| **Whole site** | **~12,650** | **35** | **0.28%** |

Two reasonable framings of the headline number:

- **Marketing parity: 94.6%.** Every page a human visitor would normally
  click through has an EN equivalent. The remaining 2 missing pages are
  noindex auth-flow stubs.
- **Total content parity: 0.28%.** The long-tail SEO content (programs,
  industries, cross, qa) is JP-monolingual.

The launch posture per `i18n_strategy.md` was deliberately "marketing
surface only, defer long-tail to post-launch". That posture has held.
The English V4 plan (`docs/english_v4_plan.md`) targets T+150d (2026-10-03)
for the long-tail expansion via `am_alias.language` migration.

---

## 7. Top 5 P0 actionable batch (next agent invocation)

In priority order (already explained in §4):

1. **Translate `/integrations/` to `/en/integrations/`** — 5 pages, AI-dev
   cohort first impression, single agent task.
2. **Place `site/en/llms-full.txt`** — single-file copy of
   `site/llms-full.en.txt`, plus update `site/en/llms.txt` line 9 to point
   to the co-located URL.
3. **Translate `/compare/{vendor}/` to `/en/compare/{vendor}/`** — 10 pages,
   high buyer intent, single agent task.
4. **Translate `/qa/` hubs to `/en/qa/`** — start with 4 highest-volume
   hubs (invoice, dencho, monozukuri-subsidy, jizokuka-subsidy), then expand.
5. **Brand reconciliation across 25 EN root pages** — flip
   `税務会計AI` → `AutonoMath` in `<title>`, `og:title`, `<header>` brand-name,
   schema.org `name`, and body prose. Keep `Bookyou株式会社` and `T8010001213708`
   verbatim (legal entity names per i18n_style_guide.md §4.something).

Each of the above is one agent task. Brand reconciliation (#5) can be done
in parallel with any of #1-#4 because they don't touch the same files.

End of audit.
