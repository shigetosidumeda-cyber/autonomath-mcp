# jpcite USER RUNBOOK (本番 launch 操作手順書)

> 2026-05-11 作成 / Claude AUTO 完了後の USER 必須操作 24 件。
> Bookyou株式会社 T8010001213708 / info@bookyou.net

## 概要

Claude (Wave 1-4 AUTO) が repo 内 file 変更 102 task を完了後、user が以下 24 件を手動実行することで本番 launch + 5min 接続可能化が完成する。

## Phase 1: 即時実行 (DNS / Fly secret) — 30 分

### USER-CLI-1: DNS jpcite.dev → jpcite.com 301 redirect
- 操作: Cloudflare dashboard → `jpcite.dev` zone → Page Rules または Worker で `*.jpcite.dev/*` を `https://jpcite.com/$1` に 301
- 確認: `curl -I https://jpcite.dev/llms.txt` → `301` + Location header に `jpcite.com`

### USER-CLI-2: mcp.jpcite.com CNAME
- 操作: Cloudflare DNS → `mcp` CNAME → `jpcite.com.` (Proxied)
- 確認: `dig +short mcp.jpcite.com`

### USER-CLI-3: status.jpcite.com CNAME
- 操作: Cloudflare DNS → `status` CNAME → `jpcite.com.`
- 確認: `dig +short status.jpcite.com`

### USER-CLI-4: Fly secret 不足分追加
- 操作:
  ```
  flyctl secrets set GBIZINFO_API_TOKEN=<value> -a autonomath-api
  flyctl secrets set POSTMARK_TOKEN=<value> POSTMARK_API_TOKEN=<value> POSTMARK_FROM_TX=info@bookyou.net POSTMARK_FROM_REPLY=info@bookyou.net -a autonomath-api
  flyctl secrets set SLACK_WEBHOOK_URL=<value> -a autonomath-api
  ```
- 確認: `flyctl secrets list -a autonomath-api | grep -E "GBIZINFO|POSTMARK|SLACK"`

### USER-CLI-5: .env.local SOT 再構築 (Fly 25 secret の本値 mirror)
- 操作: `/Users/shigetoumeda/jpcite/.env.local` に Fly secret 25 key の本値を手動 paste (chmod 600 維持、git-ignored)
- 確認: `cut -d= -f1 /Users/shigetoumeda/jpcite/.env.local | grep -v '^#' | wc -l` >= 25

### USER-CLI-6: GHA secret mirror (Stripe 等)
- 操作:
  ```
  gh secret set STRIPE_WEBHOOK_SECRET --body "$(grep ^STRIPE_WEBHOOK_SECRET .env.local | cut -d= -f2)" --repo shigetosidumeda-cyber/autonomath-mcp
  gh secret set STRIPE_SECRET_KEY --body "..." --repo ...
  ```
- 確認: `gh secret list --repo shigetosidumeda-cyber/autonomath-mcp | grep STRIPE`

## Phase 2: PyPI / npm publish — 15 分

### USER-CLI-7: PyPI publish (jpcite-mcp ブランド)
- 操作:
  ```
  cd /Users/shigetoumeda/jpcite
  uv build
  uv publish --token "$(grep ^PYPI_API_TOKEN .env.local | cut -d= -f2)"
  ```
- 確認: `pip install jpcite-mcp==0.3.4` 成功 (現状の autonomath-mcp は alias として維持)

### USER-CLI-8: npm publish (sdk-ts)
- 操作:
  ```
  cd /Users/shigetoumeda/jpcite/sdk-ts
  npm publish --access public
  ```
- 確認: `npm view @bookyou/jpcite` 200

### USER-CLI-9: GitHub repo rename (optional brand 統一)
- 操作: `gh repo rename jpcite-mcp -R shigetosidumeda-cyber/autonomath-mcp` (7 日間旧 URL から 301)
- 確認: `gh repo view shigetosidumeda-cyber/jpcite-mcp` 200

## Phase 3: 外部 submission (web 操作) — 60 分

### USER-WEB-10: Smithery submit
- URL: https://smithery.ai/new
- 操作: GitHub login → repo 選択 → smithery.yaml 認識 → publish
- 確認: smithery.ai/server/jpcite-mcp 200

### USER-WEB-11: awesome-mcp-servers PR
- URL: https://github.com/punkpeye/awesome-mcp-servers
- 操作: fork → README.md 編集 → `## Other / Government / Public Data` section に 1 行追加 → PR open
- snippet: `- [jpcite](https://github.com/shigetosidumeda-cyber/jpcite-mcp) — Japanese public-program evidence layer (subsidies / loans / licenses / enforcement / invoice registry / e-Gov laws). 139+ tools, uvx 1-line install, ¥3/billable unit, free 3 req/day per IP.`

### USER-WEB-12: modelcontextprotocol/servers Community PR
- URL: https://github.com/modelcontextprotocol/servers
- 操作: 同上、`Community Servers` section

### USER-WEB-13: mcp-get.com submit
- URL: https://mcp-get.com/
- 操作: publish manifest (PyPI runtime hint = uvx)

### USER-WEB-14: LobeHub plugin manifest 提出
- URL: https://lobehub.com/mcp (market form)
- 操作: jp/zh/en description + command `uvx jpcite-mcp`

### USER-WEB-15: GSC verification + sitemap submit
- URL: https://search.google.com/search-console
- 操作: jpcite.com property 追加 → DNS TXT or meta tag → Sitemaps → `sitemap-index.xml` 提出
- 確認: ownership verified + Sitemap status=Success

### USER-WEB-16: Bing Webmaster import + IndexNow key
- URL: https://www.bing.com/webmasters/
- 操作: GSC からの 1-click import → IndexNow key 生成 → `site/{key}.txt` 公開

### USER-WEB-17: Stripe product + price 作成 (LIVE mode)
- URL: https://dashboard.stripe.com/products
- 操作: product `jpcite-api`、price `¥3/req metered` + `Free 3 req/day` 配置、price_id を `.env.local` STRIPE_PRICE_PER_REQUEST に追記
- 確認: Stripe test mode → live mode 切替確認

### USER-WEB-18: Stripe Customer Portal config
- URL: https://dashboard.stripe.com/test/settings/billing/portal
- 操作: 解約・支払方法・invoice DL 有効化、return_url=https://jpcite.com/dashboard.html
- 確認: portal_config_id を `.env.local` STRIPE_BILLING_PORTAL_CONFIG_ID に追記

### USER-WEB-19: CF Pages custom domain proof
- URL: https://dash.cloudflare.com → Pages → autonomath-mcp project → Custom domains
- 操作: jpcite.com / jpcite.dev (将来) / mcp.jpcite.com / status.jpcite.com の domain proof
- 確認: 全 host で SSL Active

### USER-WEB-20: Zenn 公開
- URL: https://zenn.dev/new/article
- 操作: Claude 起草 md (`docs/announce/zenn_jpcite_mcp.md`、Wave 4 で生成予定) を貼付 → publish
- 確認: canonical jpcite.com link 含む、Zenn URL 取得

### USER-WEB-21: note 公開
- URL: https://note.com/notes/new
- 操作: Claude 起草 md 貼付 → publish

### USER-WEB-22: PRTIMES 無料枠
- URL: https://prtimes.jp/ (Bookyou 法人アカウント)
- 操作: jpcite β 公開 release プレス投稿
- 確認: 掲載 URL 取得 (1 営業日後)

### USER-WEB-23: OpenAI Custom GPT 公開
- URL: https://chatgpt.com/gpts/editor
- 操作: name=jpcite、description=日本公的制度 evidence API、Action import URL=https://jpcite.com/openapi.agent.gpt30.json、Auth=Bearer (X-API-Key)
- 確認: GPT Store 公開、URL 取得

### USER-WEB-24: Anthropic / Cursor / Cline 直接 submission
- URL: https://anthropic.com/contact (developers@) + Cursor docs PR
- 操作: cold email + repo URL 提示

## Phase 4: launch 後 TIME-WAIT (待ち時間)

| # | 待ち項目 | 目安 |
|---|---|---|
| W1 | GSC sitemap indexed 95% | 1-2 週間 |
| W2 | Bing sitemap indexed 95% | 数日 |
| W3 | GEO crawler (Claude/GPT) 反映 | 数週間 |
| W4 | awesome-mcp PR merge | 数日-数週 |
| W5 | k6 7日連続 p95<500ms | 1 週間 |
| W6 | restore drill 3 ヶ月連続 | 3 ヶ月 (acceptance H5 緩和済) |

## Phase 5: 完了確認

- [ ] DNS 3 host 解決
- [ ] Fly secret 25+ 件 mirror
- [ ] GHA secret mirror 完了
- [ ] PyPI jpcite-mcp publish 成功
- [ ] npm publish 成功
- [ ] Smithery listed
- [ ] awesome-mcp PR open
- [ ] GSC verified + sitemap submitted
- [ ] Bing imported + IndexNow key 公開
- [ ] Stripe live product 作成 + Portal config
- [ ] CF Pages custom domain SSL Active (4 host)
- [ ] Zenn / note / PRTIMES / OpenAI GPT 公開
- [ ] 24 USER task 全 done → v1.0-GA tag 自動 trigger 待ち

## ロールバック

- DNS: CF dashboard で旧 record 復活
- Fly secret: `flyctl secrets unset KEY -a autonomath-api`
- PyPI: `twine yank jpcite-mcp==0.3.4`
- gh repo rename: `gh repo rename autonomath-mcp -R shigetosidumeda-cyber/jpcite-mcp` 巻戻し
- Stripe live product: archive (削除不可)
- 寄稿: 削除可、ただし GEO 引用は残留
