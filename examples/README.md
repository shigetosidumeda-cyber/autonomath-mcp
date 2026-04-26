<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "AutonoMath Examples (8 runnable files)",
  "description": "AutonoMath で 5 分以内に動かせる 8 つの runnable コード例 (Python 4 + TypeScript 4)。各ファイル 50-150 LOC、standalone 実行、出力例を冒頭コメントに明記。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://autonomath.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://autonomath.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://autonomath.ai/docs/examples/"
  }
}
</script>

# AutonoMath examples

Eight runnable files — 4 Python, 4 TypeScript — showing what you can build on
AutonoMath in under 5 minutes. Each file is 50-150 LOC, runs standalone, and
its top comment quotes the exact output.

## 3-step run

1. **Point at an API** (default is a local stub):

   ```bash
   export AUTONOMATH_API_BASE=http://localhost:8080
   export AUTONOMATH_API_KEY=am_xxxx    # optional; anonymous 50 req/month without
   ```

2. **Install deps**:

   - Python: `pip install -r requirements.txt`
   - TypeScript: `npm install`

3. **Run one**:

   - `python python/01_search_subsidies_by_prefecture.py`
   - `npx tsx typescript/01_search_subsidies_by_prefecture.ts`

Unreachable `AUTONOMATH_API_BASE` prints a clear error and exits with code 2 —
safe for CI smoke tests.

## Gallery

| # | file | what it shows |
|---|------|---------------|
| P1 | `python/01_search_subsidies_by_prefecture.py` | Top-10 青森県 S/A programs as a markdown table |
| P2 | `python/02_check_exclusions.py` | 4 program IDs -> which pairs conflict and why |
| P3 | `python/03_full_program_detail.py` | One tier-S program with full A-J enriched dimensions |
| P4 | `python/04_pandas_export_csv.py` | Paginate 370 中小企業 records -> DataFrame -> CSV |
| T1 | `typescript/01_search_subsidies_by_prefecture.ts` | Same as P1, idiomatic Node 20 fetch |
| T2 | `typescript/02_check_exclusions.ts` | Same as P2 |
| T3 | `typescript/03_mcp_claude_cli_example.ts` | Spawn MCP over stdio and call `search_programs` — no Claude Desktop |
| T4 | `typescript/04_nextjs_page.tsx` | Next.js 14 server component; API key stays server-side |

## Notes

- **SDK**: every TS example has a comment showing the 1-line swap to
  `@autonomath/sdk` once the SDK ships; the raw-`fetch` fallback is self-contained.
- **Auth**: all files read `AUTONOMATH_API_KEY` from env; never hard-coded.
- **Errors**: each file handles 401 / 429 / 5xx explicitly and respects
  `Retry-After` on 429.
- **Endpoints**: only `/v1/*` customer-facing routes. No admin endpoints.

## Troubleshooting

| symptom | fix |
|---------|-----|
| `transport: ECONNREFUSED` | start the server or point `AUTONOMATH_API_BASE` at prod |
| `401` | set `AUTONOMATH_API_KEY` or unset for anonymous access (50 req/月 per IP) |
| `429` with `Retry-After: <N>` | wait `N` s; anonymous quota exhausted |
| `ModuleNotFoundError: pandas` | P4 only — `pip install pandas` |
| `command not found: autonomath-mcp` | T3 — `pip install autonomath-mcp` |

## Which examples convert best

W5 interviews said the top blocker is "I don't see what I'd build with this."
**P2** (exclusion check) and **T3** (MCP-over-stdio) draw the loudest "oh,
THAT's what this does" reaction — start there.
