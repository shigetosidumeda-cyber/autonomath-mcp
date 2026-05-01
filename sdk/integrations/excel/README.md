# jpcite Excel add-in

Operator: **Bookyou株式会社** (適格請求書発行事業者番号 **T8010001213708**) · brand: **jpcite** · API base: `https://api.jpcite.com` · cost: **¥3/req** (税込 ¥3.30)

Two install paths, same five user-defined functions:

| | XLAM (VBA) | Office Add-in (Office.js) |
|---|---|---|
| Files | `xlam/jpcite.bas`, `xlam/Settings.template.csv` | `office-addin/manifest.xml` + `office-addin/src/*` |
| Platforms | Excel for Windows (full); Mac partial — see notes | Excel for Windows / Mac / Web (full) |
| Distribution | Email a `.xlam` file | Office Add-in catalog (org) or AppSource |
| Install effort | 5 steps in VBE | 1 manifest sideload |
| Network stack | `MSXML2.XMLHTTP.6.0` | `fetch` |
| Suited to | Tax / accounting firms with locked-down PCs | Modern teams, browser Excel users |

Both implementations expose the same names so a worksheet built against XLAM keeps working when you migrate to the Office Add-in (and vice versa).

## The 5 functions

```excel
=JPCITE_HOUJIN("8010001213708")              -> "Bookyou株式会社 / 東京都文京区小日向2-22-1"
=JPCITE_HOUJIN_FULL("8010001213708")         -> "{\"houjin_bangou\":\"8010001213708\", ...}"
=JPCITE_PROGRAMS("東京都 設備投資", 5)        -> "中小企業設備投資補助金\nGX設備導入支援..."
=JPCITE_LAW("LAW-360AC0000000034")           -> "中小企業等経営強化法 / 1999-07-23"
=JPCITE_ENFORCEMENT("8010001213708")         -> "該当なし"  /  "該当あり (3 件)"
```

| Function | Endpoint | Returns |
|---|---|---|
| `JPCITE_HOUJIN(houjin_bangou)` | `GET /v1/houjin/{id}` | `name / address` (slash-joined string) |
| `JPCITE_HOUJIN_FULL(houjin_bangou)` | `GET /v1/houjin/{id}` | Raw JSON string (parse downstream) |
| `JPCITE_PROGRAMS(query, [limit])` | `GET /v1/programs/search` | Top-N program names, joined by `LF` |
| `JPCITE_LAW(law_id)` | `GET /v1/laws/{id}` | `title / effective_date` |
| `JPCITE_ENFORCEMENT(houjin_bangou)` | `GET /v1/am/enforcement?houjin_bangou=...` | `"該当なし"` or `"該当あり (N 件)"` |

Office Add-in callers use the namespaced form `=JPCITE.HOUJIN(...)` (see `manifest.xml` `<Namespace>`); XLAM callers use the flat form `=JPCITE_HOUJIN(...)`. Output values are identical.

## Install — XLAM (5 steps)

1. Open a fresh Excel workbook.
2. `Alt+F11` to open the VBE → File → **Import File…** → pick `xlam/jpcite.bas`.
3. In the workbook, add a sheet named `Settings`. Paste your API key in `B2` and define a name `APIKey` pointing at that cell. (`Settings.template.csv` shows the layout.)
4. Save the workbook as `Excel Add-in (.xlam)`. The default location is `%AppData%\Microsoft\AddIns\` (Windows) or `~/Library/Group Containers/UBF8T346G9.Office/User Content/Add-ins/` (Mac).
5. File → Options → Add-ins → Manage: Excel Add-ins → Go… → tick **`jpcite`** → OK.

The five UDFs are now available from any cell. Detailed notes in `xlam/INSTALL.md`.

## Install — Office Add-in (5 steps)

1. `cd sdk/integrations/excel/office-addin && npm install`.
2. `npm run build` — produces `dist/functions.js`.
3. Host `dist/functions.js`, `src/functions.json`, `src/taskpane.html`, `src/functions.html`, `src/runtime.html` somewhere HTTPS. The default URLs in `manifest.xml` point at `https://jpcite.com/excel-addin/*`. If you self-host, edit those URLs.
4. Sideload `manifest.xml`:
   - Excel for Web: **Insert → Add-ins → Upload My Add-in** → choose `manifest.xml`.
   - Excel for Windows/Mac: **Insert → My Add-ins → Manage My Add-ins → Upload My Add-in**.
5. Open the **jpcite** ribbon group → click **jpcite パネル** → paste API key in the task pane → 保存. Functions are immediately usable as `=JPCITE.HOUJIN(...)` etc.

## API key

Issue a key from your jpcite dashboard (https://jpcite.com → Settings → API keys).

- XLAM reads `Settings!APIKey` first, then falls back to env var `JPCITE_API_KEY` (Windows only).
- Office Add-in stores the key in `OfficeRuntime.storage` (per-machine, not synced).

The functions return sentinel strings on auth failure rather than `#VALUE!`, so a partly-broken sheet is still readable:

| Sentinel | Meaning |
|---|---|
| `#NEEDS_KEY` | API key not configured. |
| `#AUTH_ERROR (401\|403)` | Key is wrong, revoked, or out of credit. |
| `#RATE_LIMITED` | 429 from the server (anonymous tier 3 req/day, or rate-cap on your key). |
| `#NOT_FOUND` | The 法人番号 / 法令ID does not resolve. |
| `#NETWORK_ERROR` / `#HTTP_xxx` | Connectivity / unexpected server response. |

## Recalc storm — read this before deploying

Every cell call costs **¥3 (税込 ¥3.30)**.

Excel re-evaluates volatile formulas (and any formula whose precedents change) on every workbook recalc. The arithmetic is unforgiving:

> **monthly cost ≈ cell_count × recalcs_per_day × 22 working days × ¥3**

| Pattern | Cells | Recalcs/day | Monthly cost |
|---|---:|---:|---:|
| 100 法人 × 1 col, manual recalc | 100 | 1 | ¥6,600 |
| 1,000 法人 × 5 cols, auto recalc | 5,000 | 4 | ¥1.32M |
| 10,000 法人 × 5 cols, "always volatile" | 50,000 | 8 | ¥26.4M |

Mitigations the add-in supports out of the box:

- **Both UDFs are non-volatile** (`Application.Volatile False` in VBA; Office.js custom functions default to non-volatile). Inserting unrelated rows does not re-trigger them.
- **Sentinel returns are cheap**: errors return locally without a network call where possible.
- **`Application.Calculation = xlCalculationManual`** during bulk edits avoids cascade fires.
- **Paste-as-values once you have the answer** — convert the JPCITE column to static text the moment the lookup is final.
- **Pin inputs**: avoid wiring `JPCITE_*` cells to `NOW()`, `RAND()`, or any volatile precedent.

The five-target product is for one-shot enrichment, not real-time monitoring. Use the REST API + `houjin_watch` (cohort 1 webhook surface) for monitoring instead.

## Pricing

Single-tier ¥3/request metered (税込 ¥3.30). No tier SKUs, no seat fees, no annual minimums. Anonymous probes from the same IP get 3 req/day free, reset at JST 翌日 00:00 — but the Excel add-in always sends an API key, so anonymous quota is irrelevant here.

## Layout

```
sdk/integrations/excel/
├── README.md                                ← this file
├── xlam/
│   ├── jpcite.bas                           ← VBA module (drop into VBE)
│   ├── INSTALL.md                           ← XLAM-specific 5-step install
│   └── Settings.template.csv                ← Layout for the Settings sheet
└── office-addin/
    ├── manifest.xml                         ← Office Add-in manifest v1.1
    ├── package.json
    ├── tsconfig.json
    ├── webpack.config.js
    └── src/
        ├── functions.ts                     ← 5 custom functions
        ├── functions.json                   ← function metadata (registry)
        ├── functions.html                   ← runtime host page
        ├── runtime.html                     ← long-lived runtime container
        └── taskpane.html                    ← API key form + usage cheat sheet
```

## Constraints honoured

- No LLM imports anywhere (server-side rule applies to the SDK as well).
- No DB writes.
- `src/jpintel_mcp/` is untouched.
- Single ¥3/req tier, no Pro/Starter labels.
- All HTTPS calls are to `https://api.jpcite.com` with `X-API-Key`.
- jpcite brand only; the legacy AutonoMath / jpintel names do not appear in user-facing strings.

## Support

Issues: https://github.com/bookyou/jpcite/issues · Email: support@jpcite.com · Operator: Bookyou株式会社 (T8010001213708), 東京都文京区小日向2-22-1.
