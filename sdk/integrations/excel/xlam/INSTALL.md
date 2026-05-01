# jpcite XLAM — 5-step install

> Operator: Bookyou株式会社 (T8010001213708) · brand: jpcite · API base: `https://api.jpcite.com` · cost: ¥3/req (税込 ¥3.30)

This XLAM ships VBA-only. No external dependencies. Works on **Excel for Windows** (full support) and **Excel for Mac** (XMLHTTP path uses a slightly different name — see step 5).

## 1. Open a fresh workbook

Save it once so the Visual Basic Editor (VBE) has a host.

## 2. Open the VBE and import `jpcite.bas`

- Windows: `Alt+F11` → File → Import File… → pick `jpcite.bas` from this folder.
- Mac: `Option+F11` → File → Import File… → pick `jpcite.bas`.

You should see a `JPCITE` module appear under "Modules" in the project tree.

## 3. Add a `Settings` sheet with a named cell `APIKey`

1. In the workbook, create a new sheet named `Settings`.
2. In `B2` paste your jpcite API key (issue one from your dashboard at https://jpcite.com).
3. Select `B2` → Formulas → Define Name → Name: `APIKey` → OK.

If you'd rather use an environment variable, skip this and set `JPCITE_API_KEY` in your OS env (Windows only — `Environ$()` is not reliable on macOS sandboxed Excel).

## 4. Save the workbook as `.xlam`

File → Save As → Format: **Excel Add-in (`.xlam`)**.

The default save location is `%AppData%\Microsoft\AddIns\` on Windows or `~/Library/Group Containers/UBF8T346G9.Office/User Content/Add-ins/` on Mac.

## 5. Enable the add-in

Excel → File → Options → Add-ins → Manage: Excel Add-ins → Go… → check **`jpcite`** → OK.

The five UDFs are now available in any open workbook:

```excel
=JPCITE_HOUJIN("8010001213708")
=JPCITE_HOUJIN_FULL("8010001213708")
=JPCITE_PROGRAMS("東京都 設備投資", 5)
=JPCITE_LAW("LAW-360AC0000000034")
=JPCITE_ENFORCEMENT("8010001213708")
```

### Mac note

VBA `CreateObject("MSXML2.XMLHTTP.6.0")` is Windows-only. On Mac, the XLAM falls back transparently in a future revision; today, **the XLAM is Windows-first**. Mac-first users should install the Office Add-in (`../office-addin/`) instead, which uses Office.js and is fully cross-platform.

### Recalc storm warning

Every cell call costs ¥3 (税込 ¥3.30). 1,000 rows × 5 columns × 4 recalcs/day = 20,000 req/day = ¥60,000/day. Pin volatile inputs to a small range, paste-as-values once you have the answer, or use `Calculation = xlCalculationManual`. See `../README.md` for the full mitigations table.
