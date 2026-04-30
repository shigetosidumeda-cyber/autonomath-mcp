# note.com — 長文 JP 記事

**タイトル候補**:
- `日本の制度データ 11,684 件を AI エージェントから叩ける API を作った話 (¥3/req)`
- `1 年かけて作った税務・補助金検索 API を本日公開しました — jpcite`

**ハッシュタグ**: `#API` `#AI` `#補助金` `#MCP` `#個人開発`

**カバー画像**: jpcite.com のスクリーンショット または ロゴ

---

## 本文

本日、jpcite (autonomath-mcp) を公開しました。

日本の制度公開情報 — 補助金 11,684 件 / 法令 9,484 件 / 判例 2,065 件 / 適格事業者 13,801 件 / 税制 50 件 / 採択事例 2,286 件 / 行政処分 1,185 件 — を REST API + MCP サーバーから検索できるサービスです。

各レコードに必ず一次資料 URL (各省庁・都道府県・日本政策金融公庫・国税庁) が付いており、noukaweb / hojyokin-portal 等の集約サイトーサイトは `source_url` から完全に排除しています。

## なぜ作ったか

既存の制度情報アクセスは正直ひどい状況です。

- 政府ポータルは PHP 時代の UI のままで、検索は keyword AND のみ
- URL は 18 ヶ月で半分が 404 になる (省庁の CMS リプレースで失効)
- 集約サイトーサイトが SEO を独占しているが、データは数ヶ月遅延 + 互いに引用し合っているだけで、一次資料を辿れない
- AI エージェントが日本の補助金を扱おうとすると、結局ハルシネーションするか壊れたスクレイピング結果を返す

「自分の事業 (Bookyou株式会社) で補助金を探したい」というところから始まり、最終的に AI エージェント向けのインフラとして提供することにしました。

## 何ができるか

### REST API

```bash
curl "https://api.jpcite.com/v1/programs/search?q=農業&prefecture=東京都"
```

これだけで、東京都の農業関連補助金が JSON で返ってきます。匿名で日 3 req まで無料、サインアップ不要。

### Claude Desktop / Claude Code に MCP として組み込む

`~/Library/Application Support/Claude/claude_desktop_config.json` に追加:

```json
{
  "mcpServers": {
    "autonomath": {
      "command": "uvx",
      "args": ["autonomath-mcp"]
    }
  }
}
```

Claude Desktop を再起動して「農業に使える東京都の補助金を教えて」と聞けば、Claude が `search_programs` ツールを呼び、一次資料 URL 付きで回答します。

### 提供している MCP ツール (72 個)

- 補助金・融資・税制・認定の検索 (`search_programs`, `search_loan_programs`, `search_tax_incentives` 等)
- 法令検索 + スナップショット時刻クエリ (`search_by_law`, `query_at_snapshot`)
- 採択事例検索 (「実際に何が採択されたか」のグラウンディング用)
- 適格事業者照会 (インボイス対応確認)
- 行政処分履歴照会 (取引先リスクチェック)
- プロベナンス検索 (各 fact がどの一次資料由来かを返す)

## 技術スタック

- SQLite 全文検索 (3-gram + unicode61 の二重インデックスで日本語の部分一致と分かち書きの両方をカバー)
- ベクトル検索 で hybrid lexical + semantic search
- FastAPI (REST) + FastMCP (stdio MCP)
- 単一の SQLite ファイル (8.29 GB) に統合 — 503,930 entities + 6.12M facts (EAV)
- Fly.io 東京リージョン + Cloudflare Pages + Stripe 従量課金

なぜ Postgres ではなく SQLite なのか — 読み取り中心のワークロード、シングルバイナリデプロイ、ローカル MCP インストール時に DB ごと配布できる、の 3 点です。

## 料金体系

**¥3/req 完全従量課金** (税込 ¥3.30)。

- 匿名 3 req/日 無料 (IP ベース、JST 翌日 00:00 リセット、サインアップ不要)
- API キー利用時も ¥3/req のみ。月額固定 / 年間最低額 / シート課金はすべてありません
- カードでいつでも開始 / 解除

なぜ Free / Pro / Enterprise の 3 階層 SaaS にしなかったか:

1. **個人運営 (zero-touch ops) を前提にしているから**。CS / 法務 / セールスチームは持たない。Enterprise SKU を売るには商談が必要だが、それを捌くリソースがない。
2. **AI エージェントのトラフィックは bursty**。階層型 SKU は steady な利用者を過剰請求し、burst 利用者を過小サービスする。完全従量制が実コスト構造に最も近い。
3. **解約摩擦をゼロにしたい**。年間契約は新規顧客が試す心理的障壁を上げる。100% organic 集客なので、摩擦を減らす方が LTV を捕まえるより重要。

## 正直に言っておくこと (免責)

これは情報検索ツールであって、税務相談ではありません。

- 税理士法 §52 — 個別の税務相談は税理士のみが行えます。私は税理士ではありません。
- 弁護士法 §72 — 法律事務は弁護士のみが行えます。
- 行政書士法 §1 — 行政書士業務は行政書士のみが行えます。

このサービスでできるのは「制度を見つけて一次資料 URL を取り出す」ところまでです。実際の事業判断や申請にあたっては、必ず資格を持つ専門家に確認してください。

## データ衛生について

過去 1 年で一番時間を使ったのが、データ衛生です。具体的には:

- 集約サイトー完全排除 — `source_url` は省庁・都道府県・公庫・国税庁のみ
- URL 死亡監視 — 毎晩 source_url を巡回し、404 を公開保留バケット (二次レビュー待ち) に隔離 (現在 2,788 件)
- 一次資料間矛盾の解決 — 例えば METI と SMRJ で締切が違うときは、省庁優先のヒエラルキーで正規化
- 月次スナップショット — リアルタイム法令更新は e-Gov 側が atomic でないので、月次差分に切り替えてから安定した

## 試してみてください

サインアップ不要で、ブラウザ / curl ですぐ試せます:

```bash
curl "https://api.jpcite.com/v1/programs/search?q=飲食&prefecture=東京都"
```

各種リンク:

- サイト: https://jpcite.com
- 料金: https://jpcite.com/docs/pricing/
- GitHub: https://github.com/shigetosidumeda-cyber/autonomath-mcp
- PyPI: https://pypi.org/project/autonomath-mcp/
- OpenAPI: https://api.jpcite.com/openapi.json

## 運営者

- Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
- 東京都文京区小日向 2-22-1
- 代表 梅田茂利
- info@bookyou.net

VC からの資金調達なし、社員なし、サポートチームなし。すべて自走運営です。

ご意見・バグ報告・データの提案は GitHub Issues か X (DM 開放) までどうぞ。
