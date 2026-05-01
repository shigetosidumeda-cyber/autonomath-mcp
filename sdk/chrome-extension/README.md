# jpcite Chrome 拡張 (manifest v3)

任意のページで法人番号 (13桁) や制度名を選択 → 右クリック「jpcite で照会」
で `https://api.jpcite.com/v1/*` を新タブで開く拡張。

## 構成

```
sdk/chrome-extension/
  manifest.json        # manifest v3、contextMenus + <all_urls> content script
  background.js        # service worker — context menu + open ハンドラ
  content_script.js    # 全ページ注入、13桁数字を hover ハイライト
  content_script.css   # ハイライト style (jpcite ブランド色 #3B82F6)
  popup.html           # 拡張アイコンクリック時の自由クエリフォーム
  popup.js             # popup → background メッセージング
  icons/
    icon16.png   icon48.png   icon128.png    # site/assets/favicon-* を流用
```

## 開発・読み込み

```bash
# Chrome > chrome://extensions/ > デベロッパーモード ON
# > 「パッケージ化されていない拡張機能を読み込む」 > sdk/chrome-extension/
```

## 仕様

- **ルーティング**: 13桁数字 (T プレフィックス可) → `/v1/houjin/{digits}` /
  それ以外 → `/v1/programs/search?q=<encoded>`
- **課金**: 全件 ¥3/req (税込 ¥3.30)。匿名 3 req/日 無料 (IP・JST 翌日リセット)。
- **権限**: `contextMenus` と `<all_urls>` content script。content script は
  13 桁数字の hover ハイライトだけを行い、外部送信はしない。検索時はブラウザに
  `api.jpcite.com` のタブを開かせるだけ。
- **LLM 不使用**: 拡張内・サーバ側ともに LLM 推論は呼ばない。

## Chrome Web Store 公開

Chrome Web Store 公開前は、開発者向けに unpacked load で確認できます。
公開後は Store から追加するだけで利用できます。

## 関連

- bookmarklet (server side 0、即使える): `site/bookmarklet.html`
- API ドキュメント: <https://jpcite.com/docs/>
- 料金: <https://jpcite.com/pricing.html>
