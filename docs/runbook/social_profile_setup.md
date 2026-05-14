---
title: Social profile setup runbook (LinkedIn / X / GitHub Org)
updated: 2026-05-07
operator_only: true
category: brand
---

# Social profile setup runbook (LinkedIn / X / GitHub Org)

Trust-by-search work depends on the canonical Bookyou株式会社
Organization JSON-LD (https://jpcite.com/#publisher) listing the
operator's social profiles in `sameAs`. As of 2026-04-29 those URLs are
placeholders — this runbook walks the user through 5–10 minutes of
setup to make Knowledge Graph entity-binding strong.

**No content marketing required.** The accounts only need to exist with
a consistent description, link back to https://jpcite.com/, and
list 適格請求書発行事業者番号 T8010001213708 once. Knowledge Graph care about
**reciprocal cross-links** more than activity volume.

After completing each step, swap the placeholder URL in
`site/index.html`, `site/about.html`, `site/pricing.html`,
`site/audit-log.html`, `site/dashboard.html`, `site/integrations/*.html`,
and `site/compare/*/index.html` (search the repo for
`shigetosidumeda-cyber` to find every callsite) with the real URL.

---

## 1. LinkedIn Company Page (~3 min)

**Why first:** highest weight for B2B Knowledge Graph entity-binding.
LinkedIn Company Pages are crawled by Google in real-time and weighted
heavily for `Organization` schema verification.

**Steps:**
1. Sign into LinkedIn with `info@bookyou.net` (create the account if
   needed — use the operator email so transfer/handover is impossible
   for an attacker without inbox access).
2. Go to https://www.linkedin.com/company/setup/new/.
3. Pick **Small business** (1–10 employees).
4. Page identity:
   - **Name**: `Bookyou株式会社`
   - **LinkedIn public URL**: prefer `bookyou` (matches the .net domain).
     Fallback: `bookyou-inc`.
   - **Website**: `https://jpcite.com/`
   - **Industry**: `Software Development`
   - **Company size**: `1-10 employees`
   - **Company type**: `Privately Held`
   - **Logo**: upload `site/assets/logo.svg` (LinkedIn requires PNG —
     export at 400×400 from `assets/og.png` if the SVG isn't accepted).
5. **Tagline (120 chars max)**:
   > 日本の補助金・融資・税制・認定制度の API + MCP。¥3/billable unit。一次資料ベース。
6. **About / Description (2,000 chars max)**:
   > jpcite (, 適格請求書発行事業者番号 T8010001213708) は、日本の補助金・融資・税制・認定制度を REST API + MCP server で提供するサービスです。14,472 制度 + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を一次資料ベース で正規化、集約サイト不採用、AI agent が士業・経営者の確認作業を支援し、一次資料付きの照合結果を提示できるよう設計しました。料金は ¥3/billable unit 完全従量 (税込 ¥3.30)、匿名 3 req/日 per IP は登録不要で無料。本サービスは情報検索であり、税理士法 §52 / 弁護士法 §72 に基づく個別具体的な税務助言・法律相談ではありません。
7. **Specialties (tags, up to 20)**:
   - `Public program search`
   - `MCP server`
   - `Japanese tax`
   - `補助金`
   - `日本政策金融公庫`
   - `Schema.org`
   - `Tier S/A/B/C`
   - `全文検索インデックス (3-gram)`
8. **Location**: 東京都文京区小日向 (do not include 番地 — operator
   address policy keeps the street omitted from non-government surfaces).
9. Confirm checkbox + **Create page**.
10. After creation: get the canonical URL (e.g.
    `https://www.linkedin.com/company/bookyou/`) and swap it into the
    `sameAs` array in every site file (search repo for
    `https://www.linkedin.com/company/bookyou/` — it's already a
    placeholder in `audit-log.html` JSON-LD).

---

## 2. X (Twitter) account (~2 min)

**Why second:** weighted lower than LinkedIn for B2B but cheap to
maintain. Cross-link is the real value.

**Steps:**
1. Go to https://twitter.com/i/flow/signup.
2. Use `info@bookyou.net`.
3. **Username (handle)**: prefer `@zeimukaikei_ai` (matches the brand).
   Fallback: `@bookyou_inc`.
4. **Display name**: `jpcite (Bookyou株式会社)`
5. **Bio (160 chars max)**:
   > 日本の公的制度を AI が呼べる API + MCP に。¥3/billable unit 完全従量。一次資料ベース、集約サイト不採用。(T8010001213708)。
6. **Location**: `東京都`
7. **Website**: `https://jpcite.com/`
8. **Profile photo**: same logo as LinkedIn.
9. **Header (banner) image (1500×500 px)**: optional. If you skip,
   X uses the default — that's fine for entity-binding purposes.
10. **Pinned tweet** (one-time):
    > jpcite を公開しました。日本の補助金・融資・税制・認定 14,472 制度 + 採択事例 2,286 + 融資 108 + 行政処分 1,185 を一次資料ベース で API + MCP 化。¥3/billable unit 完全従量、匿名 3 req/日 per IP 無料。https://jpcite.com/
11. After setup: confirm the canonical URL is
    `https://twitter.com/zeimukaikei_ai` (or your fallback handle) and
    swap into the `sameAs` arrays.

---

## 3. GitHub Organization (~3 min)

**Why third:** developer-audience trust signal. The current repo is
under the operator's personal account (`shigetosidumeda-cyber`). An
org-claimed account moves the same ownership signal to a clearly
business-named entity.

**Steps:**
1. Go to https://github.com/organizations/new.
2. **Organization name**: `jpcite`. (If taken: `BookyouInc` or
   `bookyou-jp`. Confirm by visiting `https://github.com/shigetosidumeda-cyber/autonomath-mcp`
   first.)
3. **Contact email**: `info@bookyou.net`.
4. **This organization belongs to**: `My personal account`.
5. **Plan**: Free.
6. After creation, on the org settings page:
   - **Display name**: `Bookyou株式会社 (jpcite)`
   - **Description**:
     > Operator of jpcite (https://jpcite.com). Japanese public-program API + MCP server. 適格請求書発行事業者番号 T8010001213708.
   - **URL**: `https://jpcite.com/`
   - **Location**: `Tokyo, Japan`
   - **Twitter username**: `zeimukaikei_ai` (after step 2 above)
   - **Avatar**: same logo as LinkedIn.
7. Transfer the `autonomath-mcp` repo into the new org:
   - On the personal-account repo: **Settings** → **Transfer
     ownership** → enter the new org name.
   - This rewrites public clone URLs to `github.com/shigetosidumeda-cyber/autonomath-mcp/...`,
     but GitHub keeps the old URLs as redirects so existing
     consumers don't break.
8. After transfer: swap `https://github.com/shigetosidumeda-cyber/autonomath-mcp` →
   `https://github.com/shigetosidumeda-cyber/autonomath-mcp` in every `sameAs` array.

---

## 4. Optional: Wikidata entity claim

Skip unless the prior 3 are done first. Wikidata accepts an Organization
claim only if you can cite at least 2 independent reliable sources
(LinkedIn + the official site count).

Steps if you choose to:
1. https://www.wikidata.org/wiki/Special:CreateAccount
2. https://www.wikidata.org/wiki/Special:NewItem with:
   - **Label**: `Bookyou株式会社` / `Bookyou Inc.`
   - **Description (en)**: `Japanese software company, operator of jpcite`
   - **Description (ja)**: `jpcite を運営する日本のソフトウェア企業`
3. Add statements:
   - `instance of (P31)` → `business (Q4830453)` (or
     `private company (Q663529)`)
   - `country (P17)` → `Japan (Q17)`
   - `headquarters location (P159)` → `Tokyo (Q1490)`
   - `official website (P856)` → `https://jpcite.com/`
   - `Japanese Corporate Number (P3225)` → `8010001213708`
     (Wikidata uses 13-digit form **without** the `T` prefix)
4. Add reference to each statement: cite the canonical URL
   (`https://jpcite.com/about.html`) and the LinkedIn page.
5. Once the Wikidata item is approved (manual review by another editor,
   typically 24–48h), grab the QID (e.g. `Q12345678`) and add
   `https://www.wikidata.org/wiki/Q12345678` to `sameAs`.

---

## After all profiles exist — backfill the placeholders

Run this `grep` to find every callsite that needs the real URL:

```bash
# LinkedIn placeholder
grep -rln "https://www.linkedin.com/company/bookyou/" site/ docs/

# Twitter placeholder
grep -rln "https://twitter.com/zeimukaikei_ai" site/ docs/

# Personal GitHub (currently set to shigetosidumeda-cyber)
grep -rln "https://github.com/shigetosidumeda-cyber/autonomath-mcp" site/ docs/
```

Replace each placeholder with the real canonical URL. The canonical
Organization block lives in `<script type="application/ld+json">` near
the top of every standalone page (search for
`https://jpcite.com/#publisher` to locate them).

---

## Knowledge Graph entity-binding strength estimate

Treat this as ordinal, not absolute — Google does not publish the weight
function.

| State                                   | Estimated strength |
|-----------------------------------------|--------------------|
| Pre-2026-04-29 (no @id, no sameAs)      | 1/5 (logo + ToS only) |
| Post-Task B (@id consolidated, 2 sameAs)| 2/5 (sites cross-link, no third-party) |
| + LinkedIn page live                    | 3/5 (LinkedIn is the strongest single signal) |
| + X profile live                        | 3.5/5 |
| + GitHub Org claim + repo transfer      | 4/5 |
| + Wikidata item (optional)              | 4.5/5 |

**Solo-ops note:** maintaining 4/5 requires zero ongoing work.
Maintaining 4.5/5 (Wikidata) needs one ~20 min review cycle every
12 months. Skip Wikidata until 月商 ¥100k — the time is better spent
elsewhere until then.

---

## Verify

After landing each profile, smoke the cross-link in a clean browser
session (signed-out, fresh DNS resolve so cached redirects do not
mislead):

```bash
# LinkedIn — Company Page must list jpcite.com under "Website"
curl -sL "https://www.linkedin.com/company/<slug>/" | grep -E "jpcite\.com"

# X — bio link in profile JSON
curl -sL "https://twitter.com/<handle>" | grep -E "jpcite\.com"

# GitHub Org — public profile sidebar
curl -sL "https://api.github.com/orgs/<org>" | grep -E "blog.*jpcite"

# Site-side sameAs — apex Organization JSON-LD must list each profile
curl -sL https://jpcite.com/ | grep -oE 'sameAs"[^]]*' | head -1
```

Each must show the canonical jpcite.com URL on the social side and the
real social URL on the site side; placeholder strings (e.g. literal
`shigetosidumeda-cyber`) indicate a missed callsite.

## Rollback

If a social profile must come down (handle squatted, account
compromised, brand-conflict claim from another party), reverse the
cross-links so the Knowledge Graph does not keep advertising a dead
identity.

1. Mark the profile private / take it down on the social platform.
2. Replace the dead URL in `site/index.html`, `site/about.html`,
   `site/pricing.html`, `site/audit-log.html`, `site/dashboard.html`,
   `site/integrations/*.html`, `site/compare/*/index.html` with the
   previous placeholder (search for the dead URL to find every
   callsite).
3. Re-deploy Cloudflare Pages (auto on `main` push). Knowledge Graph
   re-crawl latency is ~1-2 weeks.
4. If LinkedIn or X is the affected profile, the entity-binding strength
   drops by ~1 ordinal step (see table above) until a replacement
   profile lands. No site-side error state — the Organization JSON-LD
   simply lists fewer `sameAs` entries.
