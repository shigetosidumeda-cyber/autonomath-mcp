# jpcite — Google Sheets add-on (Apps Script custom functions)

> Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) · brand: jpcite ·
> API base: `https://api.jpcite.com` · cost: **¥3/req** metered (税込 ¥3.30)

A Google Apps Script project that adds five spreadsheet custom functions
backed by the jpcite REST API:

```text
=JPCITE_HOUJIN("8010001213708")              -> 法人名 / 住所
=JPCITE_HOUJIN_FULL("8010001213708")          -> 全項目 JSON 文字列
=JPCITE_PROGRAMS("東京都 設備投資", 5)         -> 上位 5 制度 (改行連結)
=JPCITE_LAW("LAW-360AC0000000034")            -> 法令名 / 効力日
=JPCITE_ENFORCEMENT("8010001213708")          -> "該当なし" or "該当あり (N 件)"
```

The function surface mirrors the Excel office-addin (`../excel/office-addin/`)
1:1, so consultants can reuse the same workbook formulas across Google
Sheets and Excel.

## Cost model

Each cell call = 1 jpcite request = ¥3 (税込 ¥3.30). Sheets recalcs cells
automatically on edit. **Sheet recalcs multiply this cost.** A 1,000-row
sheet × 4 recalcs/day = 4,000 calls/day = ¥12,000/day. Mitigations:

- Pin volatile inputs in a small range and paste-as-values once you have
  the answer.
- Use `IFERROR(JPCITE_HOUJIN(A2), "—")` to short-circuit re-fetch when
  Sheets re-evaluates after a column rename.
- Apps Script caches the result of a custom function within a single
  recalc pass; cross-pass it does not. Stripe metered billing is
  computed by the jpcite API gateway and is the source of truth.

## Deploy as a per-document container-bound script (5 steps)

> This deploy mode is **per-spreadsheet**, lightweight, and does not
> require Google Workspace Marketplace publication. Each customer
> repeats the steps once per sheet.

1. **Create / open the sheet.** New sheet → Rename it.

2. **Open the script editor.**
   Menu **拡張機能 → Apps Script**. A blank `Code.gs` opens.

3. **Paste the project.**
   - Replace `Code.gs` contents with `gsheets_addon/Code.gs` from this
     folder.
   - Click **+ → HTML** → name it `Sidebar` → replace contents with
     `gsheets_addon/Sidebar.html`.
   - In the script editor's left panel, click the **歯車 (Project Settings)**
     → check **「appsscript.json」マニフェスト ファイルをエディタで表示**.
   - Replace `appsscript.json` with `gsheets_addon/appsscript.json` from
     this folder.

4. **Authorize.**
   Click **保存 (💾)**. Run the function once: select `onOpen` → **実行**.
   Google will prompt for permissions: `spreadsheets.currentonly` (sheet
   access) and `script.external_request` (HTTPS calls to
   `api.jpcite.com`). Approve.

5. **Set the API key + use the functions.**
   Reload the spreadsheet. The new menu **「jpcite → 設定 (API キー)」**
   opens a sidebar. Paste your jpcite API key (issue one at
   https://jpcite.com/dashboard) → 保存.

   Then in any cell:

   ```
   =JPCITE_HOUJIN("8010001213708")
   ```

## Deploy as a Workspace add-on (operator side)

The Workspace add-on path requires Google's Marketplace review and a
Google Cloud project. We do not provide a published add-on yet; the
container-bound path above is the supported deploy mode. If you want
to publish your own internal add-on, see Google's
[Apps Script add-on docs](https://developers.google.com/apps-script/add-ons).

## Recalc storm protections

| Protection                              | Where                                |
| --------------------------------------- | ------------------------------------ |
| Hard cap `limit` to 20                  | `_coerceLimit()` in `Code.gs`        |
| Aggregator-only rows are dropped        | `JPCITE_PROGRAMS` filter             |
| `urlFetchWhitelist` constrains targets  | `appsscript.json`                    |
| API key in document scope, not script   | `PropertiesService.getDocumentProperties` |
| Apps Script per-script daily quota      | Google-managed (`URL Fetch` ~20k/day) |

The Apps Script daily URL Fetch quota is roughly 20,000 calls/day per
consumer Google account (≈ ¥60,000/day at ¥3/req). Workspace accounts
have a higher cap. Hitting the quota returns an Apps Script error in
the cell, not a billable jpcite call.

## What the add-on does *not* do

- **No LLM call.** The functions return deterministic REST output. To
  summarize results, pipe them into Sheets' built-in `=GOOGLEFINANCE`-
  style formulas or your own LLM script — outside this add-on.
- **No write-back.** The functions are pure; they do not modify
  ranges other than the cell that called them.
- **No DB.** The add-on is stateless; the only persisted state is the
  user's API key in document properties.

## License

MIT. See `LICENSE` in the repo root.

## 不具合報告

info@bookyou.net (Bookyou株式会社, 適格請求書発行事業者番号 T8010001213708)
