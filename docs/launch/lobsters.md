# lobste.rs

**Title**: `Building a Japanese institutional-data API: SQLite 全文検索 + ベクトル検索, FastMCP, ¥3/req metered`

**Tags**: `api`, `databases`, `python`, `show`

---

## Body

Just shipped 税務会計AI — a REST + MCP search API over Japanese institutional public data (10,790 subsidies, 9,484 laws, 2,065 court decisions, 13,801 invoice registrants, 35 tax rulesets, 2,286 adoption cases). Posting here for the architecture-curious; the technical choices are unusual enough that I think they're worth a discussion.

## Architecture

Single SQLite file, no Postgres, no microservices. The DB is `autonomath.db` at 8.29 GB.

- **EAV schema**: 503,930 件の正規化レコード (12 record kinds) + 612 万件の structured 属性 + 17.7 万件の関係性 link + 別名・略称 index 335,605 行
- **Hybrid search**: SQLite 全文検索インデックスを 2 種類用意 — `_fts` (3-gram、CJK の部分一致に強い) と `_fts_uni` (unicode61、分かち書き済み日本語向け)
- **Vector layer**: ベクトル検索でセマンティック検索、5 段階の階層インデックス (1 つの巨大インデックスではなく) でクエリごとに適切な精度に振り分け
- **Cross-domain views**: `entity_id_map` (6,339 jpi↔am mappings), `v_program_full`, `v_houjin_360`, `v_readiness_input`

## Why SQLite over Postgres

Three reasons:

1. **Read-mostly workload.** Writes happen during nightly ingest, reads happen 24/7. SQLite 書込ログモードで自然に裁ける。
2. **Single-binary deploy.** Fly.io Tokyo + a volume mount, no managed-DB bill. The whole thing runs as one Python process talking to a local file.
3. **Local-mode customers can ship the DB.** Customers running the MCP server locally clone the repo and pull the DB tarball — `autonomath-mcp` then runs against the local SQLite with zero network calls. You can't do that with managed Postgres.

全文検索 + ベクトル検索 の組み合わせは、このワークロードでは Postgres + tsvector + pg_vector とほぼ互角 (中央値クエリ ~12ms on a Fly.io shared CPU)。SQLite で痛いのは ingest 時の並列書き込みだけで、夜間ジョブの直列化で回避している。

## MCP server

89 tools at default gates, MCP protocol `2025-06-18`, FastMCP over stdio. Drop into Claude Desktop config:

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

The PyPI wheel doesn't ship the 8.29 GB DB — it auto-detects empty local DB and HTTP-falls-back to `api.zeimu-kaikei.ai`. First 50 req/month per IP are free, no signup. After that, ¥3/req metered.

## Honest framing

Not tax advice (税理士法 §52). Information lookup with primary-source URLs only. Aggregator sites are banned from `source_url` — every record points to a ministry / prefecture / 公庫 / 国税庁 page.

## Try it

```bash
curl "https://api.zeimu-kaikei.ai/v1/programs/search?q=農業&prefecture=東京都"
```

- GitHub: https://github.com/shigetosidumeda-cyber/jpintel-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/
- Site: https://zeimu-kaikei.ai
- OpenAPI: https://api.zeimu-kaikei.ai/openapi.json

Solo built under Bookyou株式会社. Happy to dig into 全文検索 schema choices, the EAV trade-offs (yes, EAV has classic issues — I'll defend the choice in comments), or the data-ingest pipeline.
