# jpcite — Japan Compliance Reference (VS Code extension)

Hover-preview Japanese laws / regulations / subsidies in any source file.

When you hover an e-Gov law identifier (format `NNNAC0000000NNN`, e.g.
`322AC0000000049` for 労働基準法), the extension fetches the law title,
公布日, and 第一条 from the [jpcite](https://jpcite.com) API and renders it
inline as Markdown. A `▶ jpcite で見る` CodeLens appears above each line that
contains a law ID; clicking it opens the canonical jpcite page (which itself
links back to the e-Gov primary source).

Backed by the same corpus as the jpcite REST API:

- 9,484 法令 (e-Gov, CC-BY 4.0; 154 with full-text articles indexed)
- 50 税制 ruleset, 181 排他/前提 rules, 2,286 採択事例
- 11,684 searchable 補助金 / 助成金 / 認定制度

## Features

| Capability      | Detail                                                                 |
| --------------- | ---------------------------------------------------------------------- |
| HoverProvider   | e-Gov law ID regex `\b\d{3}AC\d{10}\b` → title + 第一条 + 出典 link    |
| CodeLensProvider| `▶ jpcite で見る` lens above every matched line, click → browser open  |
| In-memory cache | Default 1h TTL per ID, command `jpcite: Clear Hover Cache` to reset    |
| Anonymous tier  | Works with no API key (3 req/day per IP, JST 翌日 00:00 リセット)      |
| Languages       | python / typescript / javascript / markdown / yaml / json / go / rust / java / ruby / php / csharp / html / sql / plaintext |

## Configuration

Settings live under `jpcite.*` in `settings.json`:

```jsonc
{
  // Optional API key. Empty = anonymous tier. Get one at https://jpcite.com/dashboard
  "jpcite.apiKey": "",

  // Override only for local development
  "jpcite.apiBaseUrl": "https://api.jpcite.com",

  // Toggle providers without uninstalling
  "jpcite.enableHover": true,
  "jpcite.enableCodeLens": true,

  // Lookup cache (seconds)
  "jpcite.cacheTtlSeconds": 3600
}
```

## Usage

1. Install from VS Code Marketplace, or sideload a `.vsix` (see Build below).
2. Open any file containing an e-Gov law ID, e.g.

   ```python
   # Labor Standards Act, 昭和22年法律第49号
   LAW_ID = "322AC0000000049"
   ```

3. Hover the ID — a popup shows title, 公布日, 第一条 抜粋, and links to
   jpcite + e-Gov.
4. Click the `▶ jpcite で見る` lens above the line to open the canonical
   jpcite page in your browser.

Commands available in the Command Palette:

- `jpcite: Open Law in Browser`
- `jpcite: Clear Hover Cache`

## Build

```bash
cd sdk/vscode-extension
npm install
npm run build          # tsc -> dist/extension.js
npm run package        # vsce package -> jpcite-0.1.0.vsix
```

To test locally, press `F5` from inside this folder in VS Code to launch an
Extension Development Host.

## Publish to VS Code Marketplace

```bash
# 1) Create a publisher (one-time, https://marketplace.visualstudio.com/manage)
#    The publisher in package.json is "bookyou".

# 2) Get a Personal Access Token from Azure DevOps (Marketplace > Manage scope).
#    Store it in the keychain via vsce, or export VSCE_PAT.

# 3) Login (one-time per machine).
npx vsce login bookyou

# 4) Bump version in package.json, then publish.
npx vsce publish               # uses current package.json version
# or bump + publish in one go:
npx vsce publish patch         # 0.1.0 -> 0.1.1
```

Open VSX (Cursor / VSCodium / Theia) is supported via `ovsx`:

```bash
npx ovsx publish jpcite-0.1.0.vsix -p $OVSX_PAT
```

## License

MIT — see top-level [`LICENSE`](../../LICENSE).

Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) ·
contact: info@bookyou.net · web: https://jpcite.com
