---
title: Cloudflare 301 Redirect Setup
updated: 2026-05-07
operator_only: true
category: brand
---

# Cloudflare 301 Redirect Setup (zeimu-kaikei.ai → jpcite.com)

zeimu-kaikei.ai 配下の全 URL を jpcite.com の同一パスへ 301 永続リダイレクトする。
SEO 認証 (PageRank / E-E-A-T) を移行するため status code は必ず `301`。

## 1. 必要な API Token

Cloudflare ダッシュボード → Profile → API Tokens で以下 scope の Custom Token を発行。

- **Zone.DNS:Edit** — DNS レコード確認用
- **Zone.Page Rules:Edit** — 本 script の対象操作

取得元: https://dash.cloudflare.com/profile/api-tokens

## 2. Zone ID 取得

1. Cloudflare ダッシュボード にログイン
2. `zeimu-kaikei.ai` zone を選択
3. 右下 **Overview** ペインの "Zone ID" をコピー

## 3. Secrets 配置

`~/.jpcite_secrets.env` に以下を追記 (権限 `chmod 600` 必須)。

```bash
export CLOUDFLARE_API_TOKEN="..."
export CLOUDFLARE_ZONE_ID_ZEIMU_KAIKEI="..."
```

## 4. 実行

```bash
bash scripts/ops/cloudflare_redirect.sh
```

成功時 stdout に Cloudflare API レスポンス JSON 2 件 + `[OK] 301 redirect rules created`。

## 5. 検証

```bash
curl -I https://zeimu-kaikei.ai/test
# 期待: HTTP/2 301
#       location: https://jpcite.com/test

curl -I https://www.zeimu-kaikei.ai/foo/bar
# 期待: HTTP/2 301
#       location: https://jpcite.com/foo/bar
```

`HTTP/2 301` + `location: https://jpcite.com/...` (パス保持) を確認できれば完了。

## 6. ロールバック

Cloudflare ダッシュボード → zeimu-kaikei.ai → Rules → Page Rules で
当該 2 ルールを **Disable** または **Delete**。即時反映 (≦ 30 秒)。

## 7. 注意

- Page Rules は free plan で 3 個上限。本 script 実行で 2 個消費する点に留意
- 既に同一 target の Page Rule があると API は 409 を返す → 先に dashboard で削除してから再実行
- `$2` は `*` wildcard キャプチャの 2 番目を指す (1 番目はホスト wildcard)
- DNS レコード (A/AAAA/CNAME) は別途 Cloudflare proxy 経由 (orange cloud) でないと Page Rule が機能しない
