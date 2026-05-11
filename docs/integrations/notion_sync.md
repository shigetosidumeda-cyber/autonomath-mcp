# Notion Sync (jpcite)

更新日: 2026-05-12 (Wave 26)

jpcite のプログラム / 法令 / インボイスを Notion DB に sync し、Notion 側で並べ替え / フィルタ / 進捗管理を行うための連携仕様。Wave 21 で起案、Wave 26 で双方向 (bi-directional) 化。

## 1. 概要

```
jpcite                    Notion DB
  │  POST search ───────► (jpcite → Notion: new rows)
  │
  │  jpcite saved_searches◄── (Notion → jpcite: 保存検索更新)
  ▼
[notion_sync_v2.py]
```

- **jpcite → Notion**: ニッチな自治体補助金や法令改正を Notion DB に作成。Notion side で「進捗」「担当」「期限」など顧客固有の列を増やしてもよい (jpcite は触らない)。
- **Notion → jpcite**: Notion DB の `saved_search` プロパティ (text) に検索クエリを書き、checkbox `sync_to_jpcite=true` を立てると、次回 sync 時に `POST /v1/me/saved_searches` でアカウントへ保存される。

実装スクリプト: [`tools/integrations/notion_sync_v2.py`](../../tools/integrations/notion_sync_v2.py)

## 2. 前提

| 項目 | 値 |
| --- | --- |
| Notion integration token | `secret_xxx` (Internal Integration 推奨) |
| Notion DB 列 | `name(title) / source_url(url) / kind(select) / amended_at(date) / saved_search(text) / sync_to_jpcite(checkbox)` |
| jpcite API key | paid metered key (anon 3/日では sync 不可) |
| sync 頻度 | 推奨 1 日 1 回。最短 5 分間隔 (anon cap と整合) |

token / API key は環境変数で渡す:

```
export NOTION_TOKEN=secret_xxx
export NOTION_DATABASE_ID=...
export JPCITE_API_KEY=jp_xxx
```

## 3. 実行

### 3.1 jpcite → Notion (一方向)

```bash
python tools/integrations/notion_sync_v2.py push \
  --dataset programs \
  --filter '{"kind":"subsidy","prefecture":"東京都"}' \
  --limit 100
```

push は jpcite の `/v1/programs` を呼び、 `program_id` を Notion 側の `external_id` プロパティに紐付けて upsert する。重複は `external_id` の一致で判定。

### 3.2 Notion → jpcite (saved_search 同期)

```bash
python tools/integrations/notion_sync_v2.py pull-saved-searches
```

Notion DB から `sync_to_jpcite=true` の row を取得し、 `saved_search` を `POST /v1/me/saved_searches` に登録する。`label` には Notion の `name` を使う。

### 3.3 bi-directional (推奨)

```bash
python tools/integrations/notion_sync_v2.py sync \
  --dataset programs --filter '{"kind":"subsidy"}'
```

`sync` mode は push → pull → push の順に 1 周する。push の冪等性 (external_id ベース) により余計な Notion API 呼び出しは発生しない。

## 4. 課金

| 動作 | 単位 | 課金 |
| --- | --- | --- |
| jpcite → Notion (1 dataset / 1 page) | 1 export = 5 unit (Wave 26 `/v1/export` 経由) | ¥15 |
| Notion → jpcite saved_search 登録 | 1 row = 1 unit (saved_searches.create) | ¥3 |
| Notion 側 API 呼び出し | 0 unit | jpcite 側課金なし (Notion 側課金は Notion 規約) |

`push` は内部で `POST /v1/export` を 1 回 + Notion `pages.create` を N 回。export 5 unit に集約することで N に依らず ¥15 で済む。

## 5. 失敗時

- Notion API が 429 → exponential backoff (最大 3 回、合計 30s)
- Notion DB の列が無い → スクリプトが自動追加 (`pages.update` で属性 inject)
- jpcite saved_search 登録上限 (1 key=200 件) → 古い `saved_search` を Notion 側で `sync_to_jpcite=false` に戻して空ける

## 6. 統制 / 制約

- `_disclaimer` フィールドを必ず 1 列 `note(rich_text)` に同期 (§52 を agent でも見えるように)。
- Notion 側で row を削除しても jpcite saved_searches は自動削除しない。意図しない削除事故防止。
- LLM API 呼び出しは無し。row のテキスト変換 / 要約は Notion AI 機能側に任せる (`feedback_no_operator_llm_api`)。
