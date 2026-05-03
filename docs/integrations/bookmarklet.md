# ブックマークレット & Chrome 拡張

任意のページで法人番号 (13桁) や制度名を選択 → 1 click で jpcite に照会する
ブラウザツール 2 種。

このツールは回答を生成しません。選択した法人番号・制度名を jpcite API に渡し、一次資料 URL、取得時刻、provenance、制度名、対象地域、金額、締切などの構造化ファクトを取得します。ChatGPT / Claude / Cursor に貼る前の evidence pre-fetch と引用準備に向いています。

- **ブックマークレット** (server side 0、今すぐ使える、全ブラウザ対応)
- **Chrome 拡張** (manifest v3、右クリック menu + 13桁 hover ハイライト + popup form)

## ダウンロード / install

公開ページ: <https://jpcite.com/bookmarklet.html>

そちらに drag drop ボタン、ソースコード、Chrome 拡張 unpacked 読み込み手順を
まとめてあります。

## ルーティング仕様

| 入力 | 振り分け先 |
| --- | --- |
| 13桁数字 (T プレフィックス可) | `GET /v1/houjin/{digits}` |
| それ以外のテキスト | `GET /v1/programs/search?q=<encoded>` |

## 課金

- API キー利用時は従量課金対象単位ごとに ¥3 税抜 (税込 ¥3.30)。
- 匿名 3 req/日 無料 (IPベース、JST 翌日 00:00 リセット)。
- jpcite 側では外部 LLM API を呼びません。
- LLM のトークン量やモデル選択には連動しない固定 API 単価です。

## 実装

ブックマークレットはブラウザ内で選択文字列を読み取り、jpcite API に問い合わせます。Chrome 拡張は右クリックメニューと popup から同じ検索を実行できます。

## 想定ユーザー

- 税理士・会計士・行政書士 (13桁の法人番号から採択履歴を確認)
- 補助金 / 経営コンサル (制度名から類似制度・併用制限を確認)
- 記者・調査会社・M&A デューデリ (記事中の法人番号から行政処分などを確認)
- SMB 経営者 (商工会・信金メルマガから直接 jpcite)

## 関連

- [連携ガイド (Claude Desktop / Cursor / ChatGPT Custom GPT)](https://jpcite.com/integrations/)
- [REST API リファレンス](../api-reference.md)
- [料金](../pricing.md)
