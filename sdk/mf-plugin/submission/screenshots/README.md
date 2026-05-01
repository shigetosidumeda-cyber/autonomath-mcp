# screenshots/ — 提出用画像

## 現状

すべて placeholder (単色 PNG) です。実 logo と実 MF 連携状態の screenshot は
**user による差し替えが必要** です。

| ファイル | サイズ | 内容 |
|---|---|---|
| `icon-512x512.png` | 512×512 | アプリアイコン (placeholder = MF 系の青 #0f6dd1 単色) |
| `01-subsidy-search.png` | 1200×630 | 補助金検索タブ |
| `02-tax-incentive.png` | 1200×630 | 税制優遇検索タブ |
| `03-invoice-check.png` | 1200×630 | インボイス番号確認タブ |
| `04-laws.png` | 1200×630 | 法令検索タブ |
| `05-court.png` | 1200×630 | 判例検索タブ |

## 差し替え手順 (user 作業)

1. Bookyou 株式会社が用意する公式 logo を `icon-512x512.png` に上書き保存。
2. MF アプリポータル登録後、実プラグインを `https://mf-plugin.jpcite.com`
   にデプロイし、demo MF 事業者でログイン。
3. 各タブで実検索を行い、screenshot を 1200×630 で取得。背景色は MF の
   ブランドガイドラインに合わせて白基調を推奨。
4. `01-..` 〜 `05-..` を上書き保存。
5. submission/manifest.json の highlight_images description は変更不要。

## 注意

- 実 MF 利用者の事業者名・仕訳データ・口座情報が画面に映り込まないようにマスキング。
- スクリーンショット内に **税理士法 §52 免責 footer** が含まれていることを確認 (常時表示要件)。
- 1200×630 を超えるサイズは MF アプリポータル側で自動圧縮される可能性があるため、
  指定サイズ厳守。
