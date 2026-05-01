# jpcite-freee-plugin glue

A **stateless glue layer** that lets a freee アプリストア plugin pull jpcite
program recommendations using the freee 会計 OAuth2 access_token already held
by the host plugin.

```
                     ┌────────────────────────────────────────────────┐
                     │             freee アプリストア plugin            │
                     │   (個人 dev / agency が freee 認証を保持)        │
                     └────────────┬───────────────┬───────────────────┘
                                  │               │
                       freee OAuth2  jpcite API key
                       access_token   (caller-managed)
                                  │               │
                                  ▼               ▼
                          ┌───────────────────────────────┐
                          │  freee_to_autonomath.py       │
                          │  - fetch_company_context()    │
                          │  - call_autonomath_search()   │
                          │  - recommend()                │
                          │  *stateless / no logging*     │
                          └───┬──────────────────┬────────┘
                              │                  │
                              ▼                  ▼
                    api.freee.co.jp       api.jpcite.com
                    (company / 経理 API)    (¥3/req metered)
```

## なぜこの形か (design rationale)

- **jpcite は API/MCP only**: freee の UI に乗せるのが正解、自社 UI は持たない。
- **¥3/req fully metered**: glue 自体は OSS (MIT) で配布 free。課金は jpcite
  API 側で 1 req = ¥3 の従量で発生する。
- **Solo + zero-touch**: freee OAuth token と jpcite API key は **plugin
  実装者が管理** する。我々 (Bookyou) は触れない / 預からない。
- **No LLM API call**: glue は推論しない。Claude / ChatGPT 等を使う場合も
  呼び出しは利用者側の環境で完結する。

## install

```bash
pip install -r requirements.txt
# or, vendored into a freee plugin repo:
cp freee_to_autonomath.py path/to/plugin/
```

`freee_to_autonomath.py` と `autonomath_api_key` という名前は既存利用者向けの
後方互換名。新規利用でも値として渡すのは jpcite の API key で、LLM API key
ではない。

依存は `httpx` と `pydantic` のみ。Python 3.10+。

## minimal usage

```python
from freee_to_autonomath import recommend

results = recommend(
    freee_access_token=os.environ["FREEE_ACCESS_TOKEN"],   # caller-managed
    company_id=int(os.environ["FREEE_COMPANY_ID"]),
    autonomath_api_key=os.environ["JPCITE_API_KEY"],       # caller-managed
    limit=5,
)
for r in results:
    print(r.title, r.tier, r.source_url)
```

戻り値は最大 5 件、`source_url` を必ず持つ。`source_url` を持たない row は
glue 側で drop する (aggregator 経由の出典ロンダリング防止)。

## freee アプリストア 申請手順

1. **freee Developers** (https://developer.freee.co.jp/) で開発者登録 (無料)。
2. **アプリ新規作成** → "Public app (アプリストア公開)" を選択。
3. 必要 scope:
   - `read` (会社 / 取引先 / 取引一覧)
   - `companies:read` (基本情報 + 業種コード)
4. OAuth2 redirect URL を plugin host (例: `https://your-plugin.example.com/oauth/callback`) に設定。
5. ストア掲載情報:
   - 製品名: `jpcite 補助金レコメンド` 等 (任意。"freee" 商標は logo OK 取得後のみ)
   - カテゴリ: 「業務効率化 / AI アシスタント」
   - 料金: glue は無料。jpcite API 利用料 ¥3/req は別契約と明記。
6. レビュー提出 → 通常 1-2 週間で公開。

referral fee 還元 (¥3/req の 10%) は freee Partner Program 側で別途契約済。
詳細は `docs/partnerships/freee.md` を参照。

## jpcite API 接続

1. https://jpcite.com/ から API key を発行 (匿名 3 req/日 free, それ以降 ¥3/req)。
2. plugin の secret manager に `JPCITE_API_KEY` として登録。
3. 上記の `recommend(...)` を呼ぶ。リトライ / レート制限は jpcite MCP/SDK
   (`pip install autonomath-mcp`) を使う方が便利だが、本 glue は依存最小の
   ため httpx を直接呼んでいる。

## セキュリティ前提

- `freee_access_token` と `autonomath_api_key` は **caller-supplied**。
  `autonomath_api_key` は引数名の後方互換で、中身は jpcite の API key。
  glue は受け取って即 forward、終了時に破棄する。
- log には token を**出さない**。例外文も token を含まない (httpx 既定動作)。
- glue は state を持たない。DB / cache / disk 書き込み無し。
- 商用 redistribute / fork 自由 (MIT)。我々の moat は jpcite API 課金。

## test

```bash
cd sdk/freee-plugin
pip install -r requirements.txt pytest
python -m pytest tests/ -x --tb=short
```

mock 経路のみ (実 freee / 実 jpcite は叩かない)。
