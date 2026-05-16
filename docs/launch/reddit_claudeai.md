# r/ClaudeAI

**Title**: `Custom MCP server for Japanese tax/subsidy data — drop-in for Claude Desktop & Claude Code, here's a 30-second setup tutorial`

---

## Body

Built and launched jpcite — a custom MCP server giving Claude direct access to Japanese institutional data: 11,601 subsidy programs, 9,484 laws, 2,065 court decisions, 13,801 invoice registrants, 50 tax rulesets, and historical adoption cases. Returned public rows are designed to include a primary-source URL.

**Why this is useful for Claude users**: Claude is great at reasoning over Japanese text but it doesn't have grounded access to the live institutional dataset. Without a tool layer, you get plausible-sounding subsidy names that don't exist or hallucinated tax rulings. The MCP server gives Claude actual rows from primary sources so it can cite e-Gov / METI / 公庫 URLs directly.

## Claude Desktop integration (30 seconds)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop. Then ask:

> 「農業に使える東京都の補助金を教えて。」

Claude calls `search_programs`, gets primary-source URLs back, and cites them in its answer.

## Claude Code integration

Add to `.claude/mcp.json` in your project root:

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

Now Claude Code can pull subsidy / law / court-decision data while you're coding regtech / govtech features.

## What's exposed

155 tools at default gates (MCP protocol 2025-06-18), grouped:

- **Programs** — `search_programs`, `get_program`, `program_lifecycle`, `program_abstract_structured`
- **Laws** — `search_by_law`, `get_law_article_am`, `query_at_snapshot` (time-travel)
- **Case studies / adoptions** — `search_case_studies`, `search_acceptance_stats_am`
- **Loans** — `search_loan_programs`, `search_loans_am`
- **Tax** — `search_tax_incentives`, `get_am_tax_rule`
- **Enforcement** — `search_enforcement_cases`, `check_enforcement_am` (flag 業者 with bad history)
- **Provenance** — `get_provenance`, `get_provenance_for_fact` (every fact has a source ID)
- **Rule engine** — `rule_engine_check`, `prerequisite_chain` (eligibility logic)

When you `uvx autonomath-mcp`, the wheel doesn't ship the 8.29 GB DB — it auto-detects and falls back to HTTP against `api.jpcite.com`. First 3 req/day per IP are free anonymous. No signup.

## Pricing

¥3/billable unit metered, 税込 ¥3.30. 3/day free anonymously. No tiers, no minimums. Solo founder + zero-touch ops — has to be self-service.

## Honest disclaimer

This is information lookup, not tax / legal advice (税理士法 §52, 弁護士法 §72). Use it to find programs and primary-source URLs; verify with a licensed professional before any business decision.

## Try it

```bash
curl "https://api.jpcite.com/v1/programs/search?q=AI&prefecture=東京都"
```

- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/
- Site: https://jpcite.com

Solo project (Bookyou株式会社). Happy to help debug a Claude Desktop / Claude Code setup in the thread.
