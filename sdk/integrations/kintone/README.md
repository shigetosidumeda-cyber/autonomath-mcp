# jpcite — kintone plug-in

> Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) · brand: jpcite ·
> API base: `https://api.jpcite.com` · cost: **¥3/req** metered (税込 ¥3.30)

A minimal kintone customization plug-in. On the record-detail screen it
detects a configured "法人番号" field and injects a **「jpcite で見る」** button
in the header menu. Clicking the button issues a single
`GET /v1/houjin/{bangou}` request and renders the response (法人 360) in a
modal — 法人名 / 住所 / 適格事業者 / 行政処分件数 / 採択履歴件数.

The plug-in calls jpcite **directly from the customer's browser**. The API
key is stored only in the customer's kintone plug-in storage. Bookyou never
proxies traffic and never holds the customer's key.

## Cost model

Each modal open = 1 request = ¥3 (税込 ¥3.30). The plug-in does not retry
or pre-fetch; opening the modal repeatedly for the same record will charge
once per open. Stripe metered usage is computed by the jpcite API gateway,
not by this plug-in. See https://jpcite.com/pricing.

## 5-step install

> **Prerequisite (operator side)**: A cybozu.com developer account with
> the kintone Plug-in feature enabled (有償プラン). The customer also needs
> a jpcite API key issued from https://jpcite.com (separate from the
> kintone account).

1. **Build the `.zip`**.
   This folder is the plug-in source. Pack it into a kintone-compliant
   `.zip` with the official packer:

   ```bash
   npm install -g @kintone/plugin-packer
   kintone-plugin-packer ./
   # -> plugin.zip
   ```

2. **Sign and upload**.
   On https://{your-subdomain}.cybozu.com → kintone システム管理 → プラグ
   イン → **「読み込む」** → select `plugin.zip` → 確認 → 追加.

3. **Configure**.
   Open any app → 設定 → プラグイン → **「jpcite — 法人番号 360 ルックアップ」**
   → **「設定」**. Fill in:

   - **API key** : your jpcite API key (X-API-Key)
   - **法人番号 field code** : the kintone field code holding the 13-digit
     number (e.g. `houjin_bangou`)

   保存 → アプリを更新.

4. **Verify**.
   Open any record where the configured field has a 13-digit value. A
   **「jpcite で見る」** button appears in the header. Click it; a modal
   should render the 法人 360 within ~1s.

5. **Production note**.
   The plug-in does **not** prefetch. If you want a record-list view, hand
   the same field codes to the official Excel / Google Sheets integration
   (`../excel/` / `../google-sheets/`) — those run in batch and are cheaper
   when applied to dozens of rows at once.

## Configuration shape

`config.html` collects two strings; persistence is via
`kintone.plugin.app.setConfig` (kintone-managed, encrypted at rest by
cybozu).

```json
{
  "apiKey": "jpcite_sk_...",
  "houjinFieldCode": "houjin_bangou"
}
```

## Limits / caveats

- **Field type**: only single-line text is supported. Number fields work
  too but kintone returns a comma-formatted string for display; the plug-in
  strips non-digits before calling the API.
- **Mobile**: the same `index.js` is loaded on `kintone.events.on(['mobile.app.record.detail.show'])`; the modal CSS uses `position: fixed` so it
  works inside the cybozu mobile webview.
- **CORS**: `https://*.cybozu.com` is on the jpcite CORS allowlist
  (`OriginEnforcementMiddleware`). If you serve kintone from a custom
  domain, request an allowlist add via info@bookyou.net.
- **No DB writes**: the plug-in only issues `GET` requests. It does not
  write back to kintone. (Writing the looked-up data into a record is
  customer's responsibility — kintone REST API + the customer's app token,
  outside this plug-in's surface.)

## License

MIT. See `LICENSE` in the repo root.

## 不具合報告

info@bookyou.net (Bookyou株式会社, 適格請求書発行事業者番号 T8010001213708)
