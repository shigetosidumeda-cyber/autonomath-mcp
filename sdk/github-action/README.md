# jpcite-action

GitHub Action for querying the [jpcite](https://jpcite.com) API from CI workflows. Search Japanese public programs (補助金 / 融資 / 税制 / 認定), laws, corporate registry, and enforcement actions inline with your build.

Composite action — no Docker, no Node bundle. Just `curl` under the hood.

## 5-step usage

1. Get an API key at <https://jpcite.com> (anonymous tier = 3 req/day per IP, no key required for that path).
2. Add the key as a repository secret named `JPCITE_API_KEY`.
3. Reference the action in any workflow:

   ```yaml
   - uses: bookyou/jpcite-action@v1
     id: subsidy-check
     with:
       api_key: ${{ secrets.JPCITE_API_KEY }}
       query: "東京都 設備投資"
   ```

4. Use the JSON output downstream:

   ```yaml
   - run: echo "Found ${{ steps.subsidy-check.outputs.count }} programs"
   - run: echo '${{ steps.subsidy-check.outputs.result }}' | jq '.results[0]'
   ```

5. Pricing: ¥3/request fully metered (anonymous fallback gives 3 req/day per IP).

## Inputs

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `api_key` | no | `''` | jpcite API key. Empty string falls back to anon tier. |
| `query` | yes | — | Search keyword (Japanese or romaji). |
| `endpoint` | no | `programs/search` | API endpoint path under `/v1/`. |
| `base_url` | no | `https://api.jpcite.com` | Override base URL. |
| `fail_on_empty` | no | `false` | Fail step when zero results returned (compliance gate). |

## Outputs

| Name | Description |
| --- | --- |
| `result` | Raw JSON response. |
| `count` | Parsed result count. |
| `http_status` | HTTP status returned. |

## Endpoints commonly used

- `programs/search` — 補助金・融資・税制・認定 unified search
- `laws/search` — e-Gov full-text law lookup
- `invoice_registrants/search` — 法人 registry / 適格請求書発行事業者
- `enforcement-cases/search` — 行政処分 lookup

## Example — compliance gate

See [`example/.github/workflows/check-subsidies.yml`](example/.github/workflows/check-subsidies.yml).

```yaml
- uses: bookyou/jpcite-action@v1
  with:
    api_key: ${{ secrets.JPCITE_API_KEY }}
    query: "省エネ 補助金"
    fail_on_empty: 'true'
```

## License

MIT. See [LICENSE](LICENSE).

Operator: Bookyou株式会社 (T8010001213708) — info@bookyou.net
