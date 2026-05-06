# jpcite

Brand alias for [`autonomath-mcp`](https://pypi.org/project/autonomath-mcp/).

```
pip install jpcite
```

This meta-package installs `autonomath-mcp`, the real distribution that
provides the MCP server and REST client for jpcite — the Evidence-first
context layer for Japanese public-program data (補助金 / 融資 / 税制 /
認定 / 採択事例 / 行政処分 / 法令 / 判例 / 入札 / 適格請求書事業者).

## Why two names?

The user-facing brand was renamed from **AutonoMath** to **jpcite** on
2026-04-30. The PyPI distribution name `autonomath-mcp` is retained for
backward compatibility (renaming a published package would break every
existing `pip install autonomath-mcp` line in customer code, CI, and
Dockerfiles). New users land on [jpcite.com](https://jpcite.com) and
expect `pip install jpcite` to work — this meta-package bridges the two.

After install the entry points are still:

- `autonomath-api` — FastAPI REST app (legacy script name)
- `autonomath-mcp` — MCP stdio server (legacy script name)

These names will not be renamed; doing so would break `claude_desktop_config.json`
and `mcp.json` files in the wild.

## Operator

Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
代表 梅田茂利 / info@bookyou.net

## License

Apache-2.0 (matches autonomath-mcp).
