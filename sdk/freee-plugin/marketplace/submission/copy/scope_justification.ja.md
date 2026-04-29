# freee アプリ申請 — scope (権限) 取得理由

申請する scope: `read` のみ。書込み権限 (write) は一切要求しません。

## 利用 API エンドポイントと取得理由

| API エンドポイント | 取得情報 | 利用目的 |
|---|---|---|
| `GET /api/1/companies` | 利用者がアクセス可能な事業所一覧 | OAuth 後にどの事業所コンテキストで検索を実行するか確定するため (1 回のみ・セッション中はキャッシュ) |
| `GET /api/1/companies/{id}` | 事業所名・所在地 (都道府県)・法人番号 (取得可能な場合) | 補助金検索の都道府県フィルタ・法人番号スコープに利用 |

## 取得しない情報

- 取引データ (`/api/1/deals`) — 一切アクセスしません
- 仕訳データ (`/api/1/journals`) — 一切アクセスしません  
- 取引先データ (`/api/1/partners`) — 一切アクセスしません
- 給与・人事データ (HR API) — 申請対象外
- 請求書・売上データ — アクセスしません

利用者の会計データそのものを参照する設計にはなっていません。検索クエリのスコープを「東京都の法人」「中小企業 (法人番号あり)」程度に絞り込むメタ情報としてのみ事業所情報を利用します。

## データ保持

freee から取得した事業所情報は、利用者の Express セッション (HttpOnly Cookie / 6 時間で自動失効) のみに保持し、Bookyou のデータベースには **永続化しません**。セッション失効後は自動破棄されます。

## アクセストークンの取扱い

- freee の access_token (TTL 6 時間) は session 内のみで保管。ログ・DB に出力しません。
- refresh_token (TTL 90 日) は session に保持し、access_token の更新時のみ使用。
- ログアウト時はセッションを完全削除し、cookie も無効化します。

## CSRF / state 検証

OAuth 認可リクエストには毎回ランダムな `state` (24 byte / Base64URL) を付与し、コールバック時に session 内の値と一致しない場合は 400 でリジェクトします。

## redirect_uri 固定

production: `https://freee-plugin.zeimu-kaikei.ai/oauth/callback` のみ登録。
ローカル開発時は freee 側で別 client_id を発行する運用とし、production の client_id では urn:ietf:wg:oauth:2.0:oob は使用しません。
