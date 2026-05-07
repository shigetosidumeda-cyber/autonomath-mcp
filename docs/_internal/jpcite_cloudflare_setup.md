# jpcite.com Cloudflare Setup Runbook

**Status**: pending operator action (one-time, ~10 min)
**Owner**: operator (Cloudflare dash credential 必須)
**Goal**:
1. `jpcite.com` を本番ドメインとして既存 Cloudflare Pages project (`autonomath`) で配信する
2. `www.jpcite.com/*` を `jpcite.com/$1` に **301 でパス保持リダイレクト**する
3. `zeimu-kaikei.ai/*` を `jpcite.com/$1` に **301 でパス保持リダイレクト**する

---

## 前提

- `jpcite.com` は Cloudflare Registrar で取得済 (zone は Cloudflare に既に存在)
- 既存 Cloudflare Pages project 名: **`autonomath`**
- 既存 custom domain: `zeimu-kaikei.ai` (ここから jpcite.com に主力を移す)
- `site/_headers` / `site/_redirects` は **既に jpcite.com 前提で書かれている** ので変更不要 (CSP の `connect-src` は `https://api.jpcite.com` を許可済)
- `site/_redirects` は host 条件を持てないため、`www.jpcite.com` / `zeimu-kaikei.ai` の正規化は zone-level Redirect Rules で行う
- **Cloudflare Page Rules ではなく Redirect Rules (新システム) を使う** — 安価・高速・無料枠が広い (Page Rules は zone あたり 3 ルール上限の旧課金、Redirect Rules は無料 plan で 10 ルールまで)

---

## Step 1: wrangler 再認証 (operator手元のCLI)

```bash
wrangler login
```

ブラウザが開くので Cloudflare アカウントで承認 → token を保存。
※ wrangler は **デプロイには使わない**。Cloudflare dash のクリック操作で完結できる。repo の `scripts/ops/cloudflare_redirect.sh` から Redirect Rules を適用する場合は wrangler ではなく Cloudflare API token を使う。

---

## Step 2: 既存 Pages project に apex `jpcite.com` を custom domain として追加

1. https://dash.cloudflare.com/pages を開く
2. 一覧から project **`autonomath`** をクリック
3. 上部タブから **「Custom domains」** を選択
4. **「Set up a custom domain」** ボタンをクリック
5. ドメイン入力欄に `jpcite.com` と入力 → **「Continue」**
6. 確認画面で **「Activate domain」** をクリック
7. SSL 証明書プロビジョニング待ち (~1分)。状態が **「Active」** になれば完了
8. `www.jpcite.com` は canonical 配信ホストにしない。既に Custom domains に存在していても Step 3 の zone-level 301 が先に評価されれば可。

> 結果: `https://jpcite.com/` が既存 Pages project の最新 deploy を配信開始する。`zeimu-kaikei.ai` は **そのまま稼働を続ける** (Step 3 で 301 化する)。

---

## Step 3: `jpcite.com` zone に www → apex の 301 redirect rule を追加

> Pages `_redirects` は path-only なので、host canonicalization は Redirect Rules で行う。

1. https://dash.cloudflare.com/ を開く
2. 左 sidebar の **「Websites」** から zone **`jpcite.com`** を選択
3. 左ナビ **「Rules」** → **「Redirect Rules」** をクリック
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

> **Page Rules ではなく Redirect Rules を使う。** Page Rules は legacy で 3 ルール無料枠、Redirect Rules は新規・無料 10 ルール枠・edge eval が速い。

1. https://dash.cloudflare.com/ を開く
2. 左 sidebar の **「Websites」** から zone **`zeimu-kaikei.ai`** を選択
3. 左ナビ **「Rules」** → **「Redirect Rules」** をクリック
4. **「Create rule」** をクリック
5. 以下を入力:

   | フィールド | 値 |
   |---|---|
   | Rule name | `Redirect to jpcite.com` |
   | When incoming requests match... | **「All incoming requests」** を選択 |
   | Type | **Static** ではなく **Dynamic** を選ぶ (パス連結に式が必要なため) |
   | Expression (URL) | `concat("https://jpcite.com", http.request.uri.path)` |
   | Status code | **301** (Permanent Redirect) |
   | Preserve query string | **ON** (有効) |

   > **注**: タスク仕様の "Static" + `https://jpcite.com${request.uri.path}` 表記は擬似的な意図表現。Cloudflare dash の実 UI では:
   > - Static type は固定 URL のみで `${...}` 補間不可
   > - パス保持には **Dynamic type + `concat("https://jpcite.com", http.request.uri.path)` 式** を使う
   > - これが正しい "preserve path" 実装

6. **「Save and deploy」** をクリック
7. 2~3 秒で edge に反映

---

## Step 5: `jpcite.com` の DNS 確認

Custom domain 追加 (Step 2) を行うと Cloudflare Pages が **自動で CNAME を打つ** が、念のため確認:

1. Cloudflare dash → **「Websites」** → `jpcite.com` を選択
2. 左ナビ **「DNS」** → **「Records」**
3. 以下が存在することを確認:

   | Type | Name | Content | Proxy |
   |---|---|---|---|
   | CNAME | `@` (apex / jpcite.com) | `autonomath.pages.dev` | Proxied (orange cloud) |
   | CNAME | `www` | `autonomath.pages.dev` | Proxied (orange cloud, redirect source only) |

4. もし無ければ **「Add record」** で手動追加 (Type=CNAME, TTL=Auto, Proxy=ON)

> Cloudflare は CNAME flattening を apex に対しても自動適用するので `@` への CNAME は安全。

---

## Step 6: 動作検証

Step 2-5 完了後、以下が成功すること:

```bash
# (a) jpcite.com が site を配信している
curl -I https://jpcite.com/
# → HTTP/2 200, server: cloudflare, content-type: text/html

# (b) www.jpcite.com が apex へ 301 している
curl -I https://www.jpcite.com/
# → HTTP/2 301
# → location: https://jpcite.com/

# (c) zeimu-kaikei.ai が 301 を返している
curl -I https://zeimu-kaikei.ai/
# → HTTP/2 301
# → location: https://jpcite.com/

# (d) パス保持で実際に追従できる
curl -L -I https://zeimu-kaikei.ai/pricing
# → 1段目: 301, location: https://jpcite.com/pricing
# → 2段目: 200 (jpcite.com/pricing が site/pricing.html を配信)

# (e) クエリ文字列も保持される
curl -I "https://zeimu-kaikei.ai/dashboard?utm_source=test"
# → location: https://jpcite.com/dashboard?utm_source=test
```

すべて期待通りなら完了。

---

## 想定 FAQ

**Q. `site/_redirects` に www / zeimu-kaikei.ai → jpcite.com の rule を入れるべきか?**
A. **入れない。** Cloudflare Pages の `_redirects` source は path-only で domain-level redirects 非対応。zone レベルの Redirect Rules (Step 3/4) が正しい手段。

**Q. `site/_headers` の CSP は変更不要か?**
A. **不要。** 既に `connect-src` は `https://api.jpcite.com` を許可している。`zeimu-kaikei.ai` は 301 で抜けるだけなのでブラウザは新ドメインで再評価する。

**Q. www.jpcite.com も同じ Page から配信したい**
A. 配信しない。canonical / sitemap / JSON-LD は apex `https://jpcite.com` 寄せなので、`www.jpcite.com` は 301 redirect source としてだけ維持する。

**Q. `zeimu-kaikei.ai` の zone を消すべきか?**
A. **消さない。** 301 redirect rule を稼働させ続けるために zone は維持必須。古い被リンクの SEO equity を jpcite.com に渡す役目もある。期限は最低 12 ヶ月 (Google が canonical 移行を完全に再評価するまで)。

**Q. `api.jpcite.com` の DNS は?**
A. このドキュメントの範囲外。Fly.io への CNAME は別途 `docs/_internal/autonomath_com_dns_runbook.md` 参照。今回の作業は Pages (静的サイト) のみ。

---

## ロールバック手順

万一 jpcite.com で配信に問題が出た場合:

1. Cloudflare dash → 対象 zone (`jpcite.com` または `zeimu-kaikei.ai`) → Rules → Redirect Rules
2. 対象 rule を **「Disable」** トグル OFF
3. 問題を切り分け後、再度 ON に戻す

custom domain `jpcite.com` を Pages から外す手順は dash → Pages → autonomath → Custom domains → `jpcite.com` 行の `...` → Remove。
