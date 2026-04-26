# AutonoMath starter template

Minimal scaffold to call the [AutonoMath](https://autonomath.ai) API
(Japanese government program / law / case-study / enforcement search) from
your own code in 30 seconds.

This repo is a **GitHub template**: click **"Use this template"** at the top
of <https://github.com/AutonoMath/autonomath-starter> to fork it into your
own account.

## What's inside

```
sdk/starter/
  README.md                  # this file
  claude_desktop_config.json # MCP server entry for Claude Desktop
  python_example.py          # 5 LOC raw-curl-style call
  langchain_tool.py          # LangChain Tool wrapper (~40 LOC)
  LICENSE                    # MIT
  .gitignore
```

## 30-second setup

1. **Clone or use template**:

   ```bash
   git clone https://github.com/<you>/autonomath-starter
   cd autonomath-starter
   ```

2. **Get an API key** at <https://autonomath.ai> (anonymous tier: 50
   req/month free per IP, no signup; authenticated: ¥3/req metered).
   Then export it:

   ```bash
   export AUTONOMATH_API_KEY=am_xxx   # optional for the anon tier
   ```

3. **Run the Python example**:

   ```bash
   python python_example.py
   ```

   You should see a JSON list of subsidies for 東京都.

4. **(Optional) Use with LangChain**:

   ```bash
   pip install langchain requests
   python -c "from langchain_tool import autonomath_tool; print(autonomath_tool.run('東京都の補助金'))"
   ```

5. **(Optional) Use with Claude Desktop / MCP**:

   Copy the contents of `claude_desktop_config.json` into your
   `~/Library/Application Support/Claude/claude_desktop_config.json`
   (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows),
   then restart Claude Desktop. The `autonomath` tool group will appear.

## Pricing

- **Anonymous**: 50 requests / month per IP, free, no signup. Resets
  JST 月初 00:00.
- **Authenticated**: ¥3/req (税込 ¥3.30), fully metered via Stripe.
  No tier SKUs, no seat fees, no annual minimums.

## Data scope

66 MCP tools / REST endpoints over a 8.29 GB primary-source-cited corpus:

- 11,547 補助金・融資・税制・認定 programs (tier S/A/B/C, excluded=0)
- 9,484 laws (e-Gov 法令データ)
- 2,286 採択事例 (real adoption case studies)
- 1,185 行政処分・不正受給 enforcement records
- 35 tax_rulesets, 2,065 court decisions, 362 bids
- 13,801 invoice_registrants

Every row cites a primary government source; aggregators are banned.

## License

This starter template is released under **MIT** (see `LICENSE`). You can
fork it, modify it, ship it inside commercial products. The
**AutonoMath dataset and API** carry their own terms — see
<https://autonomath.ai/terms> and the
[HuggingFace dataset card](https://huggingface.co/datasets/bookyou/autonomath-japan-public-programs)
for redistribution rules.

## Support

- Operator: Bookyou株式会社 (法人番号 T8010001213708)
- Email: <info@bookyou.net>
- Issues: <https://github.com/AutonoMath/autonomath-starter/issues>
