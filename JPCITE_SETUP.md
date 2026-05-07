# jpcite.com 本番化 セットアップ手順

> **状態**: operator が手動で 1 回だけ実行する。所要 ~10 分。
> 詳細版: `docs/_internal/jpcite_cloudflare_setup.md` (このファイルと同内容)

## ゴール
1. `jpcite.com` を本番ドメインとして既存 Cloudflare Pages project (`autonomath`) で配信
2. `www.jpcite.com/*` → `jpcite.com/$1` に **301 でパス保持リダイレクト**
3. `zeimu-kaikei.ai/*` → `jpcite.com/$1` に **301 でパス保持リダイレクト**

---

## 前提

- `jpcite.com` は Cloudflare Registrar 取得済 (zone が既に Cloudflare 上に存在)
- 既存 Pages project 名: **`autonomath`** / 既存 custom domain: `zeimu-kaikei.ai`
- `site/_headers` / `site/_redirects` は **既に jpcite.com 前提** で記述済 → 変更不要
  - `_headers` の CSP `connect-src` は `https://api.jpcite.com` を許可済
  - `_redirects` には `www.jpcite.com` / `zeimu-kaikei.ai` の host redirect を入れない (Pages の `_redirects` source は path-only。zone 側 Redirect Rules が正しい層)
- **Cloudflare Page Rules ではなく Redirect Rules (新システム) を使う** — Page Rules は zone あたり 3 件無料の旧課金、Redirect Rules は無料 plan で 10 ルールまで・edge eval が速い

---

## Step 1: wrangler 再認証

```bash
wrangler login
```

ブラウザで承認 → token 保存。
※ 以降の Step は Cloudflare web dash 上のクリック操作で完結できる。repo の `scripts/ops/cloudflare_redirect.sh` から Redirect Rules を適用する場合は wrangler ではなく Cloudflare API token を使う。

---

## Step 2: Pages project に apex `jpcite.com` を custom domain として追加

1. https://dash.cloudflare.com/pages を開く
2. project **`autonomath`** をクリック
3. タブ **「Custom domains」** を選択
4. **「Set up a custom domain」** をクリック
5. ドメイン欄に `jpcite.com` → **「Continue」**
6. 確認画面で **「Activate domain」**
7. SSL プロビジョニング完了 (~1 分) を待つ → 状態が **「Active」** になれば OK
8. `www.jpcite.com` は canonical 配信ホストにしない。既に Custom domains に存在していても Step 3 の zone-level 301 が先に評価されれば可。

---

## Step 3: `jpcite.com` zone に www → apex の 301 redirect rule を追加

1. https://dash.cloudflare.com/ を開く
2. **「Websites」** から zone **`jpcite.com`** を選択
3. 左ナビ **「Rules」** → **「Redirect Rules」**
4. **「Create rule」** をクリック
5. 以下を入力:

   | フィールド | 値 |
   |---|---|
   | Rule name | `Canonicalize www.jpcite.com to apex` |
   | When incoming requests match... | Custom filter expression: `http.host eq "www.jpcite.com"` |
   | Type | **Dynamic** |
   | Expression (URL) | `concat("https://jpcite.com", http.request.uri.path)` |
   | Status code | **301** |
   | Preserve query string | **ON** |

6. **「Save and deploy」**

CLI 適用する場合は repo の source of truth から反映する:

```bash
bash scripts/ops/cloudflare_redirect.sh --dry-run
bash scripts/ops/cloudflare_redirect.sh
```

---

## Step 4: `zeimu-kaikei.ai` に 301 redirect rule を追加

1. https://dash.cloudflare.com/ を開く
2. **「Websites」** から zone **`zeimu-kaikei.ai`** を選択
3. 左ナビ **「Rules」** → **「Redirect Rules」**
4. **「Create rule」** をクリック
5. 以下を入力:

   | フィールド | 値 |
   |---|---|
   | Rule name | `Redirect to jpcite.com` |
   | When incoming requests match... | **「All incoming requests」** |
   | Type | **Dynamic** (パス連結に式が必要) |
   | Expression (URL) | `concat("https://jpcite.com", http.request.uri.path)` |
   | Status code | **301** |
   | Preserve query string | **ON** |

   > **補足**: パス保持を実現するため Static ではなく Dynamic を選ぶ。Static type は固定 URL のみで `${...}` 補間不可。Dynamic + `concat(...)` 式が正しい "preserve path" 実装。

6. **「Save and deploy」**
7. 2-3 秒で edge 反映

---

## Step 5: `jpcite.com` の DNS 確認

Step 2 を実行すると Cloudflare Pages が CNAME を自動で打つが念のため確認:

1. dash → **「Websites」** → `jpcite.com`
2. **「DNS」** → **「Records」**
3. 以下を確認 (無ければ「Add record」で手動追加):

   | Type | Name | Content | Proxy |
   |---|---|---|---|
   | CNAME | `@` | `autonomath.pages.dev` | Proxied (orange) |
   | CNAME | `www` | `autonomath.pages.dev` | Proxied (orange, redirect source only) |

> apex への CNAME は Cloudflare の CNAME flattening で安全に動く。

---

## Step 6: 動作検証

```bash
# (a) jpcite.com が配信中
curl -I https://jpcite.com/
# → HTTP/2 200, server: cloudflare

# (b) www.jpcite.com が apex へ 301
curl -I https://www.jpcite.com/
# → HTTP/2 301
# → location: https://jpcite.com/

# (c) zeimu-kaikei.ai が 301
curl -I https://zeimu-kaikei.ai/
# → HTTP/2 301
# → location: https://jpcite.com/

# (d) パス保持で実追従
curl -L -I https://zeimu-kaikei.ai/pricing
# → 1段目: 301 → location: https://jpcite.com/pricing
# → 2段目: 200

# (e) クエリ保持
curl -I "https://zeimu-kaikei.ai/dashboard?utm_source=test"
# → location: https://jpcite.com/dashboard?utm_source=test
```

すべて期待通りなら完了。

---

## ロールバック

万一問題発生時:
1. dash → `zeimu-kaikei.ai` zone → Rules → Redirect Rules
2. `Redirect to jpcite.com` を **Disable** (トグル OFF)
3. 即座に zeimu-kaikei.ai が再度 site を配信する (custom domain は削除していないので生きている)

---

## 注意事項

- `zeimu-kaikei.ai` の zone は **削除しない**。301 を稼働させ続けるため最低 12 ヶ月維持 (Google が canonical 移行を再評価するまで)
- `api.jpcite.com` (Fly.io 向け) は本ドキュメントの範囲外 → `docs/_internal/autonomath_com_dns_runbook.md` 参照
- `site/_redirects` に host redirect を **書き加えない** (Cloudflare Pages の `_redirects` source は path-only。`www` / legacy host の正規化は zone 側 Redirect Rules)
