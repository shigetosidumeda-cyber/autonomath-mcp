# jpcite Browser Extension (Manifest V3)

e-Gov / 国税庁 / 法務省 / 裁判所 / 国税不服審判所 のページに `jpcite で見る`
overlay ボタンを inject する browser 拡張。Chrome / Edge / Brave / Opera
ですぐ動き、Safari は Xcode で wrap して Web Extension として動作します。

`sdk/chrome-extension/` (法人番号 hover ハイライト) とは目的が別物で、
こちらは「特定の政府サイトでだけ overlay UI を出す」専用拡張です。

## 機能

| 操作 | 挙動 |
|---|---|
| e-Gov 法令ページを開く (例 `laws.e-gov.go.jp/law/415AC1000000086`) | 右下に **`jpcite で見る (法令 415AC1000000086)`** ボタンが出る |
| ボタンクリック | `GET https://api.jpcite.com/v1/laws/search?q=…` を実行し modal で表示 |
| modal の **Evidence Packet 化** ボタン | `GET /v1/evidence/packets/{kind}/{id}` を呼んで envelope を表示 (`subject_kind` ∈ `program` / `houjin`) |
| modal の **jpcite.com で開く** | `https://jpcite.com/?q=<id>` を新タブで |
| 国税庁 / 法務省 / 裁判所 / 国税不服審判所 ページ | URL or 本文から検出した **法令番号 / 事件番号 / 法人番号** を同じ overlay で照会 |
| 拡張アイコンの popup | 最近 30 件の照会履歴 + 残 quota |
| 右クリック「jpcite で照会」 | 任意ページの選択テキストを `https://jpcite.com/?q=…` で開く |

## 構成

```
sdk/browser-extension/
  manifest.json    # Manifest V3
  background.js    # service worker (fetch + storage + contextMenu)
  content.js       # 対象6サイトに inject (fab + modal)
  content.css      # overlay style (z-index 2147483647 / !important)
  popup.html       # toolbar アイコン clic 時の UI
  popup.js         # 履歴 + quota 表示
  options.html     # 設定画面 (API key 入力)
  options.js       # API key 保存 (chrome.storage.sync)
  icons/
    icon16.png  icon32.png  icon48.png  icon128.png
  README.md        # 本ファイル
```

## ターゲット URL

content script は以下のドメインでのみ動作します。

- `https://laws.e-gov.go.jp/*`
- `https://elaws.e-gov.go.jp/*`
- `https://www.nta.go.jp/*` (国税庁)
- `https://www.moj.go.jp/*` (法務省)
- `https://www.courts.go.jp/*` (裁判所)
- `https://www.kfs.go.jp/*` (国税不服審判所)

`api.jpcite.com` は host_permissions に含まれていますが content script は
inject されません (拡張 fetch 専用)。

## Chrome / Edge / Brave への load 手順

```text
1. Chrome を起動 → アドレスバーに `chrome://extensions/` を開く
   (Edge は edge://extensions/、Brave は brave://extensions/)
2. 右上の「デベロッパー モード」を ON にする
3. 「パッケージ化されていない拡張機能を読み込む」を押す
4. このディレクトリ (sdk/browser-extension/) を選択
5. 拡張アイコン (jp) が toolbar に出ていれば成功
6. 任意で「拡張機能の管理 → 詳細 → 拡張機能のオプション」から API key を設定
   (空のままなら匿名 3 req/日 で動作)
```

更新時は同 `chrome://extensions/` 画面で当該拡張カードの「リロード」ボタンを押す
だけで再ロードされます (manifest 変更も反映)。

## Safari への load 手順

Safari は `.crx` を直接ロードできないため、Xcode の **Safari Web Extension**
Converter を使います。

```bash
# 前提: Xcode 15+ (macOS 14+) と xcrun が利用可能。
# 拡張ディレクトリを Safari Web Extension に変換 → Xcode project が生成される。
xcrun safari-web-extension-converter \
  /Users/shigetoumeda/jpcite/sdk/browser-extension/ \
  --project-location /tmp/jpcite-safari \
  --bundle-identifier com.bookyou.jpcite \
  --app-name "jpcite" \
  --no-prompt --no-open

# 生成された Xcode project を build & run。
open /tmp/jpcite-safari/jpcite/jpcite.xcodeproj
# Xcode で ▶ を押すと「jpcite」app が起動 + Safari に拡張がインストールされる。
```

その後 Safari で:

```text
1. Safari メニュー → 設定 (⌘ + ,) → 拡張機能 タブ
2. 左カラムから「jpcite」を選択 → ON にチェック
3. 「Web サイトの権限」で「すべての Web サイト」または
   各 *.go.jp ドメインを「許可」に設定 (laws.e-gov.go.jp 等)
4. 開発中は Safari → 開発 → 「未署名の拡張機能を許可」も ON にする
   (App Store 配布時は不要)
```

オプション画面は Safari の拡張設定 → 「拡張機能の Web サイト」リンクから
開けます (`options_ui.open_in_tab: true` 設定済み)。

### Safari リリース署名

`xcrun safari-web-extension-converter` で生成された Xcode project は
- macOS app target
- Safari Extension target
の 2 つを持ちます。Mac App Store 配布する場合は通常の Apple Developer 署名と
App Store Connect でのレビューが必要です (本拡張は外形的に同等なので、
追加コードは不要)。

## API key と料金

- **匿名**: 3 req/日 (IP base、JST 翌日 00:00 リセット)。API key 不要。
- **API key**: 設定画面 (拡張アイコン右クリック → オプション、または popup
  の「設定」ボタン) で入力。`chrome.storage.sync` に保存され、Chrome アカウント
  間で同期されます。**jpcite サーバ以外には送信しません**。
- **課金**: 全件 ¥3/req (税込 ¥3.30)。発行・残量・支払いは
  <https://jpcite.com/pricing.html>。

## permissions の根拠

| permission | 用途 |
|---|---|
| `activeTab` | popup 開閉時に現在 tab の URL を読む (履歴用) |
| `storage` | API key / 履歴 / 残 quota を保存 (sync + local) |
| `scripting` | (将来用) 動的 inject の余地。現時点では未使用 |
| `contextMenus` | 右クリック「jpcite で照会」menu |
| `host_permissions` | 上記6サイト + `api.jpcite.com` (拡張 fetch 専用) |

LLM API は呼びません。サーバ側 (`api.jpcite.com`) でも LLM 推論は行いません
(jpcite 全体ポリシー)。

## 開発時の lint

```bash
# Mozilla web-ext (Chrome / Safari の Manifest V3 も lint できる)
npx web-ext lint --source-dir /Users/shigetoumeda/jpcite/sdk/browser-extension/
```

`manifest.json` は Manifest V3 に準拠 (service worker / host_permissions 分離 /
options_ui.open_in_tab)。`web-ext lint` の警告は host_permissions の
ワイルドカード (e.g. `https://www.nta.go.jp/*`) のみで、本拡張は対象サイトを
ピンポイント指定しているため意図通りです。

## 関連リンク

- `sdk/chrome-extension/` — 法人番号 hover ハイライト拡張 (別物・併用可)
- API ドキュメント: <https://jpcite.com/docs/>
- bookmarklet (拡張不要、即使える): `site/bookmarklet.html`
- 料金: <https://jpcite.com/pricing.html>
