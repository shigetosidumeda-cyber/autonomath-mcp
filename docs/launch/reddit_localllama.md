# r/LocalLLaMA

**Title**: `MCP server for Japanese tax/subsidy/law data — works with any local agent (Claude Desktop, Cline, custom), 155 tools, ¥3/billable unit`

---

## Body

If you're building agents that need to reason about Japanese institutional data (subsidies, laws, court decisions, tax rulesets), you can now plug in jpcite as an MCP server.

**Coverage** (public rows include primary-source URLs where available — aggregator-only sources are excluded from public sourcing):

- 11,601 subsidy programs across 47 prefectures
- 9,484 laws (e-Gov, CC-BY)
- 2,065 court decisions
- 50 tax rulesets
- 13,801 適格事業者 (invoice registry)
- 2,286 historical adoption cases for grounding "what actually got funded"
- 1,185 enforcement records (so you can flag risky 業者)

**MCP integration**:

- 184 tools at default gates, protocol `2025-06-18`, FastMCP over stdio
- Tested with Claude Desktop, Cline, and custom Python MCP clients
- Tools cover search, get-by-ID, lifecycle, prerequisite chains, rule-engine checks, snapshot-time queries, and provenance lookup

**Claude Desktop config (30-second setup)**:

```json
{
  "mcpServers": {
    "jpcite": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

When you `uvx autonomath-mcp`, the wheel doesn't ship the 8.29 GB DB — it auto-detects and falls back to HTTP against `api.jpcite.com`. The first 3 req/day per IP are free anonymous, no signup. Past that it's ¥3/billable unit metered. If you want full local DB performance, clone the repo.

**Local-only path**: clone the repo, pull the DB tarball, run `autonomath-mcp` against the local SQLite. No network calls. The README has the steps.

**Honest caveat**: this is information lookup, not tax/legal advice. 税理士法 §52 — verify primary sources before any business decision. The agents do the search; humans still own the judgment call.

**Stack** (relevant to local-LLM folks): SQLite 全文検索 (3-gram + unicode61 二重インデックスで CJK 対応) + ベクトル検索 で hybrid lexical+semantic。EAV schema, 503,930 entities + 6.12M facts. Single SQLite file, no external deps for local mode.

Quick smoke-test from a terminal:

```bash
curl "https://api.jpcite.com/v1/programs/search?q=AI&prefecture=東京都"
```

- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/
- Site: https://jpcite.com

Solo built (Bookyou株式会社). No VC, no team. Self-service. Happy to answer MCP-integration questions or help debug a local setup in this thread.
