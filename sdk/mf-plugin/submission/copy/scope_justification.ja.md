# scope 取得理由 — `mfc/ac/data.read` のみ

## 要求する scope

| scope | 用途 | 必要性 |
|---|---|---|
| `mfc/ac/data.read` | MF クラウド会計の事業者表示名と tenant_uid を 1 回読み取る | 必須 |

## 取得する情報 (実取得項目)

- 事業者の **表示名** (UI ヘッダに「事業者: ◯◯◯」として表示するため)
- **tenant_uid** (Bookyou 側 billing と MF 側 API 呼び出しの整合に使用)
- 既定都道府県 (もし API で取得できれば検索クエリのデフォルト値に。取得できなければ手入力)

## 取得しない情報 (明示)

- 仕訳・元帳・取引明細・残高 (たとえ `mfc/ac/data.read` の射程内でも本アプリは読まない)
- 取引先マスタ・顧客リスト
- 口座連携情報 / API 連携先 / 銀行残高
- 従業員情報・マイナンバー
- 給与・賞与・経費精算データ
- 個人ユーザーの操作ログ

## 書込み権限について

- `mfc/ac/data.write` を含む書込み系 scope は **一切要求しません**。
- MF クラウドへ書き戻す処理 (仕訳・請求書発行 等) は本アプリでは行いません。

## トークンの扱い

- 取得した access_token / refresh_token は **server-side session (Fly.io HND, HttpOnly + Secure + SameSite=None クッキー、itsdangerous 署名)** にのみ保存します。
- ブラウザの localStorage / sessionStorage / クライアント JS 側に token を**一切露出しません**。
- 30 日経過した session は自動破棄します。明示的なログアウト時は MF 側の revoke endpoint も呼び出します。
- token をログ出力する箇所はゼロ。例外メッセージにも token は含まれません (httpx 既定動作 + 明示 redaction)。

## 既存 scope との比較

freee 版アプリは `read` scope を要求していますが、freee は scope 体系が粗いため
"会社・取引先・取引一覧" のうち本アプリで読むのは会社情報のみという「使わない権限を持つ」
状態でした。MF 版では scope 体系が `mfc/{product}/data.{read,write}` と細分化されている
ため、`mfc/ac/data.read` という最小単位を選択し、原理的に読み取り対象を会計プロダクト
内の read 操作に限定しています。

## 将来の拡張可能性 (現時点では未要求)

- 請求書プロダクトでのインボイス番号自動検証を MF 内で完結させる場合は、追加で
  `mfc/invoice/data.read` を取得する可能性があります。実装時には改めてユーザー同意を取得
  する設計とし、本リリース時点では `mfc/ac/data.read` のみとします。
