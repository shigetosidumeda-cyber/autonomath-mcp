# jpcite USER RUNBOOK (本番 launch 操作手順書)

> 2026-05-11 作成 / Claude AUTO 完了後の USER 必須操作 24 件。
> Bookyou株式会社 T8010001213708 / info@bookyou.net

## 概要

Claude (Wave 1-4 AUTO) が repo 内 file 変更 102 task を完了後、user が以下 24 件を手動実行することで本番 launch + 5min 接続可能化が完成する。

## Phase 1: 即時実行 (DNS / Fly secret) — 30 分

### USER-CLI-1: DNS jpcite.dev → jpcite.com 301 redirect
- 操作: Cloudflare dashboard → `jpcite.dev` zone → Rules → Redirect Rules → Create Rule、 If `(http.host eq "jpcite.dev")` Then Static redirect to `https://jpcite.com${http.request.uri.path}` (Status=301、 Preserve query string=ON)
- 確認: `curl -I https://jpcite.dev/llms.txt` → `301` + `location: https://jpcite.com/llms.txt`
- rollback: 該当 Redirect Rule を Disable

### USER-CLI-2: mcp.jpcite.com CNAME
- 操作: Cloudflare DNS → Add record → Type=CNAME / Name=`mcp` / Target=`jpcite.com` / Proxy status=Proxied (orange cloud)
- 確認: `dig +short mcp.jpcite.com` で CF proxy IP 返却、 `curl -sI https://mcp.jpcite.com` で 200/3xx (CF Pages 配信側 USER-WEB-19 完了後)

### USER-CLI-3: status.jpcite.com CNAME
- 操作: Cloudflare DNS → Add record → Type=CNAME / Name=`status` / Target=`jpcite.com` / Proxy status=Proxied
- 確認: `dig +short status.jpcite.com` で CF proxy IP 返却

### USER-CLI-4: Fly secret 不足分追加
- 値の出所: `.env.local` の同名 key に既に paste 済 (USER-CLI-5 を先に実施した場合)。 未取得値は GBizINFO=https://info.gbiz.go.jp/api/, Postmark=https://account.postmarkapp.com/servers, Slack=https://api.slack.com/messaging/webhooks で発行
- 操作:
  ```
  flyctl secrets set GBIZINFO_API_TOKEN=<value> -a autonomath-api
  flyctl secrets set POSTMARK_TOKEN=<value> POSTMARK_API_TOKEN=<value> POSTMARK_FROM_TX=info@bookyou.net POSTMARK_FROM_REPLY=info@bookyou.net -a autonomath-api
  flyctl secrets set SLACK_WEBHOOK_URL=<value> -a autonomath-api
  ```
- 確認: `flyctl secrets list -a autonomath-api | grep -E "GBIZINFO|POSTMARK|SLACK"` で 5 key 出現
- rollback: `flyctl secrets unset GBIZINFO_API_TOKEN POSTMARK_TOKEN POSTMARK_API_TOKEN POSTMARK_FROM_TX POSTMARK_FROM_REPLY SLACK_WEBHOOK_URL -a autonomath-api`

### USER-CLI-5: .env.local SOT 再構築 (Fly secret 全件 mirror)
- 操作: `flyctl secrets list -a autonomath-api` で現在の secret 一覧取得 (現状 25+ key) → `/Users/shigetoumeda/jpcite/.env.local` に各 key の本値を `KEY=VALUE` 形式で paste (chmod 600 維持、git-ignored)。 本値は発行元 dashboard (Stripe / Cloudflare R2 / GitHub OAuth / Google OAuth / Sentry / GBizINFO / Postmark 等) から個別に取得
- 確認: `stat -f %A /Users/shigetoumeda/jpcite/.env.local` が `600`、 `cut -d= -f1 /Users/shigetoumeda/jpcite/.env.local | grep -v '^#' | grep -v '^$' | sort -u | wc -l` が `flyctl secrets list` 件数 +α 以上

### USER-CLI-6: GHA secret mirror (Stripe 等)
- 前提: USER-CLI-5 で `.env.local` に Stripe 4 key (STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET / STRIPE_PRICE_PER_REQUEST / STRIPE_BILLING_PORTAL_CONFIG_ID) が paste 済。 STRIPE_PRICE_*** と STRIPE_BILLING_PORTAL_** は USER-WEB-17/18 完了後に追記される
- 操作:
  ```
  cd /Users/shigetoumeda/jpcite
  for K in STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRICE_PER_REQUEST STRIPE_BILLING_PORTAL_CONFIG_ID; do
    V=$(grep "^${K}=" .env.local | head -1 | cut -d= -f2-)
    [ -n "$V" ] && gh secret set "$K" --body "$V" --repo shigetosidumeda-cyber/autonomath-mcp
  done
  ```
- 確認: `gh secret list --repo shigetosidumeda-cyber/autonomath-mcp | grep STRIPE` で 4 key 出現

## Phase 2: PyPI / npm publish — 15 分

### USER-CLI-7: PyPI publish (autonomath-mcp legacy 配布名)
- 注: CLAUDE.md SOT に従い PyPI 配布名は `autonomath-mcp` を維持 (user-facing ブランドだけ jpcite)。`jpcite-mcp` への rename は別 release で alias 配布枠を取ってから
- 操作:
  ```
  cd /Users/shigetoumeda/jpcite
  uv build      # dist/autonomath_mcp-0.3.4-* を再生成 (既に dist/ 配下に存在すれば skip 可)
  uv publish --token "$(grep ^PYPI_API_TOKEN .env.local | cut -d= -f2-)"
  ```
- 確認: `pip install autonomath-mcp==0.3.4` 成功 + `pip show autonomath-mcp | grep Version` で `0.3.4`

### USER-CLI-8: npm publish (sdk-ts) ※ blocked / sdk-ts 未実装
- 状態: 現状 repo に `sdk-ts/` ディレクトリ無し (Option B post-launch SDK republish 待ち)。 本 task は launch 前 skip 可。 sdk-ts 構築完了後に再度実施
- 操作 (sdk-ts 構築後):
  ```
  cd /Users/shigetoumeda/jpcite/sdk-ts
  npm publish --access public
  ```
- 確認: `npm view @bookyou/jpcite` で `version` 取得

### USER-CLI-9: GitHub repo rename (optional brand 統一)
- 操作: `gh repo rename jpcite-mcp -R shigetosidumeda-cyber/autonomath-mcp` (旧 URL は GitHub が自動 301 で恒久 redirect)
- 確認: `gh repo view shigetosidumeda-cyber/jpcite-mcp` で `name: jpcite-mcp` 表示
- rollback: `gh repo rename autonomath-mcp -R shigetosidumeda-cyber/jpcite-mcp`

## Phase 3: 外部 submission (web 操作) — 60 分

### USER-WEB-10: Smithery submit
- URL: https://smithery.ai/ (右上 "Add Server" or GitHub App connect; `/new` と `/servers/new` は 404 で利用不可)
- 操作: GitHub login → "Add Server" → repo `shigetosidumeda-cyber/autonomath-mcp` 選択 → `smithery.yaml` 自動認識 → publish
- 確認: `curl -s https://smithery.ai/server/@shigetosidumeda-cyber/autonomath-mcp -o /dev/null -w "%{http_code}"` が 200

### USER-WEB-11: awesome-mcp-servers PR
- URL: https://github.com/punkpeye/awesome-mcp-servers
- 操作: fork → README.md 編集 → 既存 section の中で最も近い `<details><summary>...Government</summary>` または `Knowledge & Memory` ブロック内に 1 行追加 → PR open
- snippet: `- [jpcite](https://github.com/shigetosidumeda-cyber/jpcite-mcp) — Japanese public-program evidence layer (subsidies / loans / licenses / enforcement / invoice registry / e-Gov laws). 139+ tools, uvx 1-line install, ¥3/billable unit, free 3 req/day per IP.`
- 確認: PR URL 取得 + maintainer auto-label 付与
- 注: USER-CLI-9 (repo rename) 完了後の URL `jpcite-mcp` を使用

### USER-WEB-12: modelcontextprotocol/servers Community PR
- URL: https://github.com/modelcontextprotocol/servers
- 操作: fork → README.md の `### 🌎 Third-Party Servers` > `Community Servers` 章にアルファベット順に 1 行追加 → PR open
- snippet: USER-WEB-11 と同一 snippet (alphabet 順なので `j` 位置に挿入)
- 確認: PR URL 取得

### USER-WEB-13: mcp-get.com submit
- URL: https://mcp-get.com/ (右上 "Submit a Server")
- 操作: GitHub login → form 入力 (name=jpcite-mcp / PyPI=autonomath-mcp / runtime=uvx / install_command=`uvx autonomath-mcp`) → submit
- 確認: `curl -s https://mcp-get.com/packages/jpcite-mcp -o /dev/null -w "%{http_code}"` が 200

### USER-WEB-14: LobeHub plugin manifest 提出
- URL: https://lobehub.com/mcp/new (Submit MCP server form)
- 操作: jp/zh/en description + command `uvx autonomath-mcp` (PyPI 配布名は legacy 維持)、 GitHub URL=`https://github.com/shigetosidumeda-cyber/jpcite-mcp` (rename 後)
- 確認: LobeHub 掲載 URL 取得

### USER-WEB-15: GSC verification + sitemap submit
- URL: https://search.google.com/search-console
- 操作: jpcite.com property 追加 → DNS TXT or meta tag → Sitemaps → `sitemap-index.xml` 提出
- 確認: ownership verified + Sitemap status=Success

### USER-WEB-16: Bing Webmaster import + IndexNow key
- URL: https://www.bing.com/webmasters/
- 操作: GSC からの 1-click import → IndexNow key 生成 → `site/{key}.txt` を作成 (中身は key と同じ文字列) → `git add site/{key}.txt && git push` で CF Pages に配信
- 確認: `curl -s https://jpcite.com/{key}.txt` で key 返却 + Bing Webmaster の IndexNow status=Active

### USER-WEB-17: Stripe product + price 作成 (LIVE mode)
- URL: https://dashboard.stripe.com/products (右上 toggle で **Live mode** 確認、Test mode で作るのは禁止)
- 操作: product `jpcite-api` → Add price → Pricing model=`Usage-based` / Currency=JPY / Per-unit=¥3 / Aggregation=`Sum of usage during period` / Billing period=Monthly → save → 表示された `price_id` (例 `price_1Q...`) を `.env.local` の `STRIPE_PRICE_PER_REQUEST=` 行に追記 (Free 3 req/day は API 側の rate limit で実装済、Stripe price 側では設定不要)
- 確認: `grep ^STRIPE_PRICE_PER_REQUEST .env.local` で `price_` から始まる値、 USER-CLI-4 → CLI-5 → CLI-6 順で Fly + GHA に mirror
- rollback: Stripe product を archive (LIVE 削除不可) + `.env.local` の値を空に

### USER-WEB-18: Stripe Customer Portal config
- URL: https://dashboard.stripe.com/settings/billing/portal (LIVE mode、 `/test/` URL は test mode なので使わない)
- 操作: Features → 解約 / 支払方法変更 / invoice DL を全て ON、 return_url=`https://jpcite.com/dashboard.html`、 保存後の `portal_config_id` (例 `bpc_...`) を `.env.local` の `STRIPE_BILLING_PORTAL_CONFIG_ID=` 行に追記
- 確認: `grep ^STRIPE_BILLING_PORTAL_CONFIG_ID .env.local` で `bpc_` から始まる値、 USER-CLI-4/5/6 で Fly + GHA に mirror

### USER-WEB-19: CF Pages custom domain proof
- URL: https://dash.cloudflare.com → Pages → autonomath-mcp project → Custom domains → "Set up a custom domain"
- 操作: 4 host (jpcite.com / jpcite.dev / mcp.jpcite.com / status.jpcite.com) を順に追加。 CF Registrar で取得済の zone は自動で proof 通る
- 確認: `for H in jpcite.com jpcite.dev mcp.jpcite.com status.jpcite.com; do echo "$H: $(curl -sI https://$H | head -1)"; done` で全て 200/3xx

### USER-WEB-20: Zenn 公開
- URL: https://zenn.dev/new/article
- 操作: `docs/announce/zenn_jpcite_mcp.md` (Wave 4 生成済) を本文 textarea に貼付 → 公開設定で canonical URL を `https://jpcite.com/announce/zenn` に固定 → publish
- 確認: Zenn 記事 URL 取得 + 記事内に `https://jpcite.com/` link が 1+ 件含まれる

### USER-WEB-21: note 公開
- URL: https://note.com/notes/new
- 操作: `docs/announce/note_jpcite_mcp.md` を貼付 → publish
- 確認: note 記事 URL 取得

### USER-WEB-22: PRTIMES 無料枠
- URL: https://prtimes.jp/main/action.php?run=html&page=releaseguide_login (Bookyou 法人アカウント login)
- 操作: 新規リリース作成 → `docs/announce/prtimes_jpcite_release.md` 貼付 → 配信日時設定 → 申請
- 確認: 配信後の掲載 URL 取得 (PRTIMES 審査 1 営業日)

### USER-WEB-23: OpenAI Custom GPT 公開
- URL: https://chatgpt.com/gpts/editor (ChatGPT Plus/Pro/Team login 必須)
- 操作: name=jpcite、description=日本公的制度 evidence API、Configure → Actions → Import from URL=`https://jpcite.com/openapi.agent.gpt30.json` (site/openapi.agent.gpt30.json で配信中) → Authentication=API Key、Auth Type=Custom、Header=`X-API-Key`
- 確認: GPT Store 公開後の URL 取得 + Test 機能で 1 制度 lookup が動作

### USER-WEB-24: Anthropic / Cursor / Cline 直接 submission ※ organic 原則と要整合
- 注意: CLAUDE.md「100% organic acquisition / 営業/cold outreach 禁止」原則と衝突するため、 本 task は実施前に再判断。 実施しない場合は launch gate からも除外
- 代替案 (organic 範囲): Cursor / Cline は `awesome-mcp-servers` 経由で自動的に拾われる。 Anthropic は MCP registry (USER-WEB-13) 経由
- 仮に実施する場合: https://github.com/cursor-ai/cursor の Discussion に技術投稿 (cold email でなく community 投稿)

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
