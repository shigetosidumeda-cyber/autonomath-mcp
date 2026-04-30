# Cline MCP Marketplace — Submission Pack

**Submit to**: <https://github.com/cline/mcp-marketplace>
**Method**: GitHub PR (fork → edit index → open PR)
**Estimated review time**: 3–10 days (maintainer-gated)
**Status**: DRAFT — do NOT submit

---

## Pre-flight

- [ ] Public repo `github.com/shigetosidumeda-cyber/autonomath-mcp` is live
- [ ] PyPI package `autonomath-mcp` v0.3.2 is published
- [ ] README.md renders the pinned tool count (93 default / 4 gated off)
- [ ] Read `CONTRIBUTING.md` and the index schema in the marketplace repo before opening the PR

---

## Step 1 — Fork and clone

```bash
gh repo fork cline/mcp-marketplace --clone
cd mcp-marketplace
git checkout -b add/autonomath-mcp
```

## Step 2 — Add the JSON entry

Locate the marketplace index file (typically `mcps.json`, `servers.json`, or `index.json` at the repo root — confirm with the current `CONTRIBUTING.md` before editing). Add the entry below in alphabetical order under the `servers` array (or under the `Finance` / `Government` category, whichever the schema uses).

### Exact JSON to add

```json
{
  "name": "autonomath-mcp",
  "displayName": "AutonoMath — 日本の制度 MCP",
  "description": "Search Japanese institutional data: 10,790 subsidies + 154 laws full-text + 9,484 law catalog stubs + 2,065 court decisions + 35 tax rulesets + 13,801 invoice registrants + 2,286 adoption cases + 1,185 enforcement records. 93 MCP tools at default gates (4 additional tools gated off pending fix). Primary-source URLs on 99%+ rows.",
  "repository": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
  "homepage": "https://jpcite.com",
  "license": "MIT",
  "language": "Python",
  "runtime": "python>=3.11",
  "transport": "stdio",
  "protocol": "2025-06-18",
  "install": {
    "uvx": "uvx autonomath-mcp",
    "pip": "pip install autonomath-mcp"
  },
  "command": "uvx",
  "args": ["autonomath-mcp"],
  "categories": ["government", "legal", "finance"],
  "tags": [
    "japan",
    "japanese",
    "government",
    "subsidies",
    "grants",
    "loans",
    "tax",
    "laws",
    "court-decisions",
    "compliance",
    "due-diligence",
    "primary-source",
    "ja",
    "補助金",
    "助成金",
    "融資",
    "税制"
  ],
  "tools_count": 93,
  "pricing": "¥3/request tax-exclusive (¥3.30 tax-inclusive, fully metered) · first 3 requests/day per IP free (anonymous, JST next-day reset) · no tier SKUs, no seat fees, no annual minimums",
  "operator": {
    "name": "Bookyou株式会社",
    "invoice_registration_number": "T8010001213708",
    "contact": "info@bookyou.net"
  },
  "disclaimer": "情報検索サービスです。税理士法 §52 (税務代理) / 弁護士法 §72 (法律事務) / 行政書士法 §1 (申請代理) / 社労士法 (労務判断) のいずれにも該当しません。出力は一次資料 URL を必ずご確認ください。"
}
```

Note: schema field names (e.g. `tools_count` vs `toolsCount`, `displayName` vs `name`) MUST be re-verified against the live `CONTRIBUTING.md` immediately before opening the PR — the marketplace schema can change without notice.

## Step 3 — Validate locally

```bash
# JSON syntax
python -m json.tool < <index-file> > /dev/null && echo "OK"

# If the repo ships a JSON Schema:
npx ajv-cli validate -s schema.json -d <index-file>
```

## Step 4 — Commit

```bash
git add <index-file>
git commit -m "Add AutonoMath: 93-tool MCP for Japanese institutional data"
git push -u origin add/autonomath-mcp
```

## Step 5 — Open the PR

### PR title

```
Add AutonoMath: 93-tool MCP for Japanese institutional data (subsidies / laws / tax / court / invoice)
```

### PR body

```markdown
## What this PR adds

A single-server entry for **AutonoMath** (`autonomath-mcp` on PyPI), an MCP server that indexes Japanese institutional public data with primary-source URL lineage on every row.

## Coverage

| Dataset | Count |
|---|---|
| Searchable subsidy/loan/tax/certification programs | 10,790 |
| Adoption case studies (採択事例) | 2,286 |
| Loan products (3-axis 担保 / 個人保証人 / 第三者保証人 decomposition) | 108 |
| Enforcement records (行政処分) | 1,185 |
| Court decisions | 2,065 |
| Bids (GEPS + 47 都道府県) | 362 |
| Laws — full text indexed | 154 |
| Law catalog stubs (name resolver only, full-text load incremental) | 9,484 |
| Tax rulesets (インボイス + 電帳法) | 35 |
| Qualified-invoice issuer registrants (国税庁 PDL v1.0 delta) | 13,801 |
| Sourced compatibility pairs (am_compat_matrix status='confirmed') | 4,300 |
| Exclusion / prerequisite rules | 181 |

## Tools

- **93 tools at default gates** (`tools/list` runtime count, AUTONOMATH_ENABLED=1)
  - 39 core tools (programs / case studies / loans / enforcement / laws / court / bids / tax / invoice + 7 one-shot discovery + cross-dataset glue)
  - 50 autonomath tools at runtime (V1 + 4 V4 universal annotation/validation/provenance + Phase A static/example/health + lifecycle/abstract/prerequisite/graph_traverse/rule_engine)
- **4 additional tools are intentionally gated OFF** pending fix (smoke test 2026-04-29 found them broken):
  - `query_at_snapshot` (`AUTONOMATH_SNAPSHOT_ENABLED`, migration 067 missing)
  - `intent_of` + `reason_answer` (`AUTONOMATH_REASONING_ENABLED`, reasoning package missing)
  - `related_programs` (`AUTONOMATH_GRAPH_ENABLED`, am_node table missing)
- Two further tools (`render_36_kyotei_am` + `get_36_kyotei_metadata_am`) are held behind `AUTONOMATH_36_KYOTEI_ENABLED` due to 労基法 §36 / 社労士法 review requirements.
- Protocol: `2025-06-18`. Transport: `stdio`. Runtime hint: `uvx`.

Evidence Pre-fetch / precomputed intelligence means source URLs, fetched timestamps, exclusion-rule checks, and cross-dataset joins are prepared for retrieval. Describe it as evidence packaging, not as model-cost savings.

## Install

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

## Pricing

- **¥3 per request** (税込 ¥3.30) — fully metered via Stripe
- **First 3 requests/day free** per IP (anonymous, JST 翌日リセット)
- **No tier SKUs**, no seat fees, no annual minimums, no signup required

## Disclaimer (税理士法 §52 fence)

AutonoMath is an information-retrieval service over published primary sources. It does **not** provide:

- Legal advice (弁護士法 §72)
- Tax advice or filing representation (税理士法 §52)
- Application representation (行政書士法 §1)
- Labour determinations (社労士法)

Search results are extracted at the time of fetch; rates / sunset dates / authorities reflect the published values and may change. Verify primary-source URLs and consult a licensed professional for individual cases.

## Operator

- **Bookyou株式会社** (適格請求書発行事業者番号 T8010001213708)
- 代表 梅田茂利
- info@bookyou.net
- 適格請求書発行事業者 (qualified invoice issuer)

## Repo

- Source: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/
- Homepage: https://jpcite.com

## Checklist

- [ ] Entry added in alphabetical order
- [ ] JSON validates locally (`python -m json.tool` clean)
- [ ] License is MIT (OSI-approved)
- [ ] Public repo with README, LICENSE, and PyPI install path
- [ ] No paid-only / closed-source components in the install path
```

---

## Disclaimer fence (must appear in README and in the entry's `description` if schema permits)

> AutonoMath is information retrieval, not advice. It does not perform 税務代理 (税理士法 §52), 法律事務 (弁護士法 §72), 申請代理 (行政書士法 §1), or 労務判断 (社労士法). Verify primary-source URLs and consult licensed professionals for individual cases.

---

## After-merge follow-up

- [ ] Confirm the entry appears in the next Cline release (release cadence varies; check the marketplace tag).
- [ ] Update `scripts/registry_submissions/README.md` with the merged PR URL and merge date.
