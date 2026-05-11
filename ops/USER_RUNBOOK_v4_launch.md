# jpcite USER RUNBOOK v4 — launch 即時実行 (24 task)

> 2026-05-11 v4 / Bookyou株式会社 T8010001213708 / 代表 梅田茂利 / info@bookyou.net
> 本番 launch 直後の user 手動操作のみを、launch 即時実行 priority 順に再整理。
> Claude AUTO で fix-gate 済みの自動化部分は本文書に登場しない (V3_WAVE5_BACKLOG.md 参照)。

## RUNBOOK の使い方

- T01 から順に着手。各 task は **実行場所** (CLI/WEB) **手順** (5 step 以内) **完了確認** (curl or 画面) **失敗時 fallback** の 4 ブロックで自己完結。
- 上から落ちる前 task の `price_id` / `portal_config_id` 等は `.env.local` (chmod 600) を SOT として後段が参照。
- 24 task 全 done で `gh release create v1.0-GA` の auto-trigger を待つ状態に到達。

---

## Phase 0: deploy 完了 verify (T01-T03)

### T01: post_deploy_verify_v3.sh 実行
- 実行場所: CLI (local mac)
- 手順:
  1. `cd /Users/shigetoumeda/jpcite`
  2. `bash scripts/ops/post_deploy_verify_v3.sh` を実行 (script 不在なら次の T01-fallback)
  3. 出力末尾の `OVERALL: PASS` を確認
  4. `PASS` でなければ stdout を `/tmp/post_deploy_verify_$(date +%s).log` に保存し T02 に進まない
  5. PASS なら T02 へ
- 完了確認: stdout に `healthz=200`、`openapi paths=182`、`commit=b1de8b2` を含む `OVERALL: PASS` 行
- 失敗時 fallback (script 不在):
  - `curl -fsSL https://api.jpcite.com/healthz` で `{"status":"ok"}` を確認
  - `curl -fsSL https://api.jpcite.com/openapi.json | jq '.paths | length'` で `182` を確認
  - `curl -fsSL https://api.jpcite.com/openapi.json | jq -r '.info.version'` で現行 version を確認
  - すべて通れば T02 へ進む

### T02: Fly app machine 状態 verify
- 実行場所: CLI
- 手順:
  1. `flyctl status -a autonomath-api` 実行
  2. 全 machine が `state=started`、`health checks: passing` であることを確認
  3. `flyctl logs -a autonomath-api --no-tail | tail -200` で boot log を確認
  4. 末尾 200 行に `autonomath self-heal migrations: applied=N skipped=M` を確認
  5. 異常なら `flyctl deploy --remote-only --strategy rolling -a autonomath-api` で redeploy
- 完了確認: machine state=started + health passing + migration self-heal log 出現
- 失敗時 fallback: `flyctl machine restart <machine_id> -a autonomath-api`、それでも crash なら直前 commit に `git revert` して再 push

### T03: GHA 最新 deploy run verify
- 実行場所: CLI
- 手順:
  1. `gh run list --workflow=deploy.yml --limit 1 --repo shigetosidumeda-cyber/autonomath-mcp` で最新 run id 取得
  2. `gh run view <run_id> --repo shigetosidumeda-cyber/autonomath-mcp` で 14/14 step が全 success を確認
  3. failed step があれば `gh run view <run_id> --log-failed` で原因 log 取得
- 完了確認: `conclusion: success` + step `Smoke test post-deploy` が green
- 失敗時 fallback: failed step が `Smoke test post-deploy` のみなら edge cache propagation 起因の false negative の可能性。120s 待って `gh run rerun <run_id> --failed --repo shigetosidumeda-cyber/autonomath-mcp` で再走

---

## Phase 1: DNS + Fly secret 確認 (T04-T08)

### T04: DNS 4 host 解決確認
- 実行場所: CLI
- 手順:
  1. `for H in jpcite.com www.jpcite.com api.jpcite.com mcp.jpcite.com status.jpcite.com jpcite.dev; do echo "$H: $(dig +short $H | head -1)"; done`
  2. 全 host で CF proxy IP (104.x / 172.x) が返却されることを確認
  3. 未設定 host があれば CF dashboard で CNAME 追加 (Type=CNAME / Target=jpcite.com / Proxied)
  4. `for H in jpcite.com api.jpcite.com mcp.jpcite.com status.jpcite.com; do echo "$H: $(curl -sI https://$H | head -1)"; done` で 200/3xx を確認
- 完了確認: 6 host 全て dig 解決 + 4 host で TLS 確立
- 失敗時 fallback: CF DNS で proxy 状態 (orange cloud) を再確認、`dig +trace` で 委譲確認

### T05: jpcite.dev → jpcite.com 301 redirect 確認
- 実行場所: CLI
- 手順:
  1. `curl -sI https://jpcite.dev/llms.txt | head -3` を実行
  2. `HTTP/2 301` + `location: https://jpcite.com/llms.txt` を確認
  3. 不在なら CF dashboard → jpcite.dev zone → Rules → Redirect Rules で `(http.host eq "jpcite.dev")` → `https://jpcite.com${http.request.uri.path}` Status=301
  4. Preserve query string=ON を確認
- 完了確認: 任意 path で `301` + `location` header が `jpcite.com` 配下
- 失敗時 fallback: CF Page Rule (legacy) でも代替可。SEO citation bridge marker 経由で旧 `zeimu-kaikei.ai` の 301 も残置 (前面表示はしない)

### T06: Fly secret inventory + 不足分追加
- 実行場所: CLI
- 手順:
  1. `flyctl secrets list -a autonomath-api > /tmp/fly_secrets_$(date +%s).txt` で現状取得
  2. `cut -f1 /tmp/fly_secrets_*.txt | sort -u` と `.env.local` の key を `diff` で差分確認
  3. 不足 key を `flyctl secrets set KEY=VALUE -a autonomath-api` で逐次追加 (まとめて set すると 1 回 deploy で済む)
  4. `STRIPE_PRICE_PER_REQUEST` と `STRIPE_BILLING_PORTAL_CONFIG_ID` は T11/T12 完了後に追記
  5. `flyctl secrets list -a autonomath-api | wc -l` で 25+ key を確認
- 完了確認: `.env.local` ⊆ Fly secret (Stripe 2 key を除く)
- 失敗時 fallback: deploy がトリガされて machine 再起動するので T01-T03 を再走

### T07: .env.local SOT 再構築 (chmod 600 維持)
- 実行場所: CLI
- 手順:
  1. `stat -f %A /Users/shigetoumeda/jpcite/.env.local` で `600` 確認 (異なれば `chmod 600 .env.local`)
  2. `flyctl secrets list -a autonomath-api` の全 key 名を取得 (値は flyctl では取得不可、各 dashboard から個別取得)
  3. 不足 KEY=VALUE を `.env.local` に append (Stripe / CF R2 / GitHub OAuth / Google OAuth / Sentry / GBizINFO / Postmark 等)
  4. `cut -d= -f1 .env.local | grep -v '^#' | grep -v '^$' | sort -u | wc -l` で Fly secret 件数 +α 以上を確認
  5. `git status .env.local` で untracked 状態を確認 (.gitignore 済)
- 完了確認: chmod 600 + key 件数 ≥ Fly secret 件数 + git untracked
- 失敗時 fallback: 値が分からない key は発行元 dashboard で rotate して新値を取得し直す

### T08: GHA secret mirror (Stripe + CI 用)
- 実行場所: CLI
- 手順:
  1. `cd /Users/shigetoumeda/jpcite`
  2. 下記 loop を実行
     ```
     for K in STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRICE_PER_REQUEST STRIPE_BILLING_PORTAL_CONFIG_ID PYPI_API_TOKEN NPM_TOKEN; do
       V=$(grep "^${K}=" .env.local | head -1 | cut -d= -f2-)
       [ -n "$V" ] && gh secret set "$K" --body "$V" --repo shigetosidumeda-cyber/autonomath-mcp
     done
     ```
  3. `gh secret list --repo shigetosidumeda-cyber/autonomath-mcp` で 6 key 出現を確認
  4. STRIPE_PRICE_* は T11 完了後、STRIPE_BILLING_PORTAL_* は T12 完了後に再 mirror
- 完了確認: GHA secret に Stripe 4 key + PyPI/NPM token 出現
- 失敗時 fallback: `gh auth status` で repo scope を確認、未付与なら `gh auth refresh -s repo,workflow`

---

## Phase 2: Stripe product / pricing setup (T09-T12)

### T09: Stripe LIVE mode 切替確認
- 実行場所: WEB (https://dashboard.stripe.com/)
- 手順:
  1. ブラウザで login (Bookyou株式会社 account)
  2. 左下 toggle で **Live mode** に切り替え (Test mode で作成すると LIVE と完全分離されるため必ず確認)
  3. 右上 account name の隣に "Live mode" バッジを目視
  4. URL bar に `/test/` が含まれないことを確認
  5. Activate アカウント (Business profile 完成、Tax ID T8010001213708 入力済) を確認
- 完了確認: URL に `/test/` 含まれず + Live mode バッジ表示
- 失敗時 fallback: Activate 未完なら Business profile 入力 (Bookyou株式会社 / T8010001213708 / 文京区小日向2-22-1 / info@bookyou.net)

### T10: Stripe Tax 設定 (JP only, inc tax)
- 実行場所: WEB (https://dashboard.stripe.com/settings/tax)
- 手順:
  1. Settings → Tax → Tax registrations で `Japan / Active` を追加 (Tax ID T8010001213708)
  2. Default tax behavior を `Inclusive` に設定 (¥3 内税 = 税抜 ¥2.73 + 消費税 ¥0.27 ≒ 表示価格 ¥3.30 税込)
  3. Tax rate 自動計算を ON (Japan 標準税率 10%)
  4. 適用国を `Japan` のみに restrict (JP only origin)
- 完了確認: Tax registrations 一覧に Japan = Active + Default behavior=Inclusive
- 失敗時 fallback: 自動計算が走らない場合は手動で `Tax rate=10%` を Inclusive で product に明示適用

### T11: Stripe Product 作成 (jpcite metered req)
- 実行場所: WEB (https://dashboard.stripe.com/products)
- 手順:
  1. 右上 "Add product" → name=`jpcite-api`、Description=`Japanese public-program evidence layer — metered API`
  2. Pricing model=`Usage-based` / Currency=`JPY` / Per-unit=`3` / Tax behavior=`Inclusive` / Aggregation=`Sum of usage during period` / Billing period=`Monthly`
  3. Usage type=`Metered` (Free 3 req/day は API 側 rate limit で実装済、Stripe 側では設定不要)
  4. Save → 表示された `price_id` (例 `price_1Q...`) を copy
  5. `.env.local` の `STRIPE_PRICE_PER_REQUEST=` 行に paste して保存 → T06 に戻って Fly secret + T08 に戻って GHA secret に mirror
- 完了確認: `grep ^STRIPE_PRICE_PER_REQUEST /Users/shigetoumeda/jpcite/.env.local` が `price_` で始まる値、Fly + GHA secret に反映
- 失敗時 fallback: LIVE では削除不可、誤作成時は product を archive して新規作成

### T12: Stripe Customer Portal config (jpcite.com 復帰先)
- 実行場所: WEB (https://dashboard.stripe.com/settings/billing/portal)
- 手順:
  1. URL bar に `/test/` が含まれないこと (Live mode) を再確認
  2. Features → 解約 / 支払方法変更 / invoice DL / 顧客情報変更 を ON
  3. Business information → Privacy policy URL=`https://jpcite.com/privacy`、Terms of service URL=`https://jpcite.com/terms`
  4. Default return URL=`https://jpcite.com/dashboard.html`
  5. Save → `portal_config_id` (例 `bpc_...`) を `.env.local` の `STRIPE_BILLING_PORTAL_CONFIG_ID=` 行に追記 → T06 + T08 で mirror
- 完了確認: `grep ^STRIPE_BILLING_PORTAL_CONFIG_ID /Users/shigetoumeda/jpcite/.env.local` が `bpc_` で始まる値、Fly + GHA に反映
- 失敗時 fallback: Portal preview で 顧客 login flow を E2E 試走 (login → 解約取消 → invoice DL)

---

## Phase 3: AI surface submission 8 件 (T13-T20)

> 全 8 task は organic acquisition のみ (広告出稿しない)。旧 brand「税務会計AI」は前面に出さず、SEO citation bridge marker としてのみ最小表記。

### T13: PyPI publish (autonomath-mcp legacy 配布名)
- 実行場所: CLI
- 手順:
  1. `cd /Users/shigetoumeda/jpcite && uv build` で `dist/autonomath_mcp-0.3.4-*` 生成
  2. `uv publish --token "$(grep ^PYPI_API_TOKEN .env.local | cut -d= -f2-)"`
  3. `pip install autonomath-mcp==0.3.4 --upgrade` で install 確認
  4. `uvx autonomath-mcp --help` が exit 0
  5. PyPI page `https://pypi.org/project/autonomath-mcp/0.3.4/` を WEB で確認
- 完了確認: PyPI page で 0.3.4 公開 + `pip show autonomath-mcp | grep Version` が 0.3.4
- 失敗時 fallback: version 衝突なら `pyproject.toml` を 0.3.5 にして `gh secret set` 系を再 mirror せず `uv build && uv publish` のみ再走

### T14: Anthropic MCP registry submission (modelcontextprotocol/servers PR)
- 実行場所: WEB (https://github.com/modelcontextprotocol/servers)
- 手順:
  1. GitHub fork
  2. README.md の `### 🌎 Third-Party Servers` > `Community Servers` 章に alphabet 順 (`j` 位置) で 1 行追加
  3. snippet=`- [jpcite](https://github.com/shigetosidumeda-cyber/jpcite-mcp) — Japanese public-program evidence layer (subsidies / loans / licenses / enforcement / invoice registry / e-Gov laws). 139+ tools, uvx 1-line install, ¥3/billable unit metered, 3 req/day free per IP.`
  4. PR open (title=`Add jpcite to Community Servers`、body に PyPI link + tool count + cohort 説明)
  5. PR URL を `/tmp/pr_anthropic_mcp.txt` に記録
- 完了確認: PR URL 取得 + maintainer auto-label 付与待ち
- 失敗時 fallback: alphabet 順違反等の指摘は同 PR で push 修正 (close → 別 PR は不要)

### T15: Smithery submission (ChatGPT plugin store の代替路)
- 実行場所: WEB (https://smithery.ai/)
- 手順:
  1. 右上 "Add Server" or GitHub App connect (`/new` / `/servers/new` は 404)
  2. GitHub login → repo `shigetosidumeda-cyber/autonomath-mcp` 選択
  3. `smithery.yaml` 自動認識を確認 → publish
  4. 公開後の URL `https://smithery.ai/server/@shigetosidumeda-cyber/autonomath-mcp` を copy
- 完了確認: `curl -s -o /dev/null -w "%{http_code}" https://smithery.ai/server/@shigetosidumeda-cyber/autonomath-mcp` が 200
- 失敗時 fallback: smithery.yaml が認識されない場合は `dxt/manifest.json` を root に symlink して再 publish

### T16: Cursor MCP directory submission (awesome-mcp-servers PR)
- 実行場所: WEB (https://github.com/punkpeye/awesome-mcp-servers)
- 手順:
  1. fork → README.md 編集
  2. `<details><summary>...Government</summary>` または `Knowledge & Memory` ブロック内に T14 と同 snippet を追加
  3. PR open
  4. PR URL を `/tmp/pr_cursor_awesome.txt` に記録
- 完了確認: PR URL 取得 (Cursor / Cline は本 list を auto-discover するため別途 submission 不要)
- 失敗時 fallback: maintainer が closed conventional commit を要求するケースあり、その場合は `feat: add jpcite (japanese public-program evidence layer)` で再 commit

### T17: mcp-get.com submission
- 実行場所: WEB (https://mcp-get.com/)
- 手順:
  1. 右上 "Submit a Server" → GitHub login
  2. form: name=`jpcite-mcp`、PyPI=`autonomath-mcp` (legacy 配布名)、runtime=`uvx`、install_command=`uvx autonomath-mcp`、homepage=`https://jpcite.com/`
  3. submit
  4. 数分以内に `https://mcp-get.com/packages/jpcite-mcp` が 200 を返す
- 完了確認: `curl -s -o /dev/null -w "%{http_code}" https://mcp-get.com/packages/jpcite-mcp` が 200
- 失敗時 fallback: name 衝突なら `jpcite-evidence` で再 submit

### T18: LobeHub plugin manifest 提出
- 実行場所: WEB (https://lobehub.com/mcp/new)
- 手順:
  1. GitHub login
  2. ja / zh / en description (3 lang)、command=`uvx autonomath-mcp` (PyPI 配布名は legacy 維持)
  3. GitHub URL=`https://github.com/shigetosidumeda-cyber/jpcite-mcp` (T19 完了後の rename 後 URL)
  4. submit
- 完了確認: LobeHub 掲載 URL 取得
- 失敗時 fallback: rename 前なら URL は `autonomath-mcp` で submit、GitHub の 301 redirect が拾う

### T19: GitHub repo rename (jpcite-mcp 統一)
- 実行場所: CLI
- 手順:
  1. `gh repo view shigetosidumeda-cyber/autonomath-mcp --json name,url` で現状確認
  2. `gh repo rename jpcite-mcp -R shigetosidumeda-cyber/autonomath-mcp` 実行
  3. 旧 URL からの 301 redirect が GitHub side で自動付与される
  4. `gh repo view shigetosidumeda-cyber/jpcite-mcp` で `name: jpcite-mcp` 表示
  5. local clone は `git remote set-url origin https://github.com/shigetosidumeda-cyber/jpcite-mcp.git`
- 完了確認: 新 URL で repo view 成功 + 旧 URL でも 301 で同 repo に到達
- 失敗時 fallback: `gh repo rename autonomath-mcp -R shigetosidumeda-cyber/jpcite-mcp` で巻戻し可

### T20: OpenAI Custom GPT 公開 + Gemini Extension (Claude.ai の MCP 連携は T14 経由で完結)
- 実行場所: WEB (https://chatgpt.com/gpts/editor)
- 手順:
  1. ChatGPT Plus/Pro/Team login → Create a GPT → name=`jpcite`、description=`日本公的制度 evidence API (補助金/融資/税制/法令)`
  2. Configure → Actions → Import from URL=`https://jpcite.com/openapi.agent.gpt30.json`
  3. Authentication=API Key、Auth Type=Custom、Header=`X-API-Key`
  4. Test 機能で 1 制度 lookup を E2E (`search_programs?q=ものづくり`) → 200 + 結果配列
  5. Publish (Visibility=Everyone)、Gemini Extension は Gemini Extensions store の "Submit" form (https://gemini.google.com/extensions) に GPT3.0 OpenAPI を同様に submit
- 完了確認: GPT Store 公開 URL 取得 + Test 1 件 evidence 引用、Gemini Extension は submission queued
- 失敗時 fallback: OpenAPI import が schema validate に失敗なら `site/openapi.agent.json` (v3.1) を試す、`X-API-Key` header の Custom 設定が UI から消える既知バグはブラウザ再 load で再表示

---

## Phase 4: organic article publish 8 本 (T21-T22)

> 8 本は実在の生成済み markdown を使用 (docs/announce/ 配下)。広告出稿しない、organic のみ。

### T21: Zenn / note / PRTIMES 3 本 publish (一次 publish channel)
- 実行場所: WEB
- 手順:
  1. **Zenn** (https://zenn.dev/new/article): `docs/announce/zenn_jpcite_mcp.md` を本文 textarea に貼付、トピック=`mcp` `claude` `python` `api` `subsidy`、canonical URL=`https://jpcite.com/announce/zenn`、publish。記事 URL を `/tmp/article_zenn.txt` に記録
  2. **note** (https://note.com/notes/new): `docs/announce/note_jpcite_mcp.md` を貼付、ハッシュタグ=#補助金 #AI #MCP #日本 #API、publish。記事 URL を `/tmp/article_note.txt` に記録
  3. **PRTIMES** (https://prtimes.jp/ → Bookyou株式会社 法人 login): 新規リリース作成 → `docs/announce/prtimes_jpcite_release.md` 貼付 → 配信日時=即時、申請。審査後の掲載 URL を `/tmp/article_prtimes.txt` に記録
- 完了確認: 3 article URL 取得 + 各記事内に `https://jpcite.com/` link が 1+ 件含まれる
- 失敗時 fallback: PRTIMES 審査落ちは「商品サービス情報の客観性」が原因の場合あり、disclaimer (`§52 / §72 / 行政書士法 §1 一次 URL only`) を本文に追記して再 submit

### T22: 業界紙 5 本 organic 寄稿 (税理士新聞 / 行政会報 / TKC会報 / M&A Online / 診断士会報)
- 実行場所: WEB (各誌 contact form / 寄稿受付)
- 手順:
  1. **税理士新聞**: `docs/announce/zeirishi_shimbun_jpcite.md` を contact form / 寄稿メール (info@zeirishi-shimbun.example) に送付。Bookyou株式会社 T8010001213708 を署名に明記
  2. **行政会報**: `docs/announce/gyosei_kaiho_jpcite.md` を行政書士会連合会 広報窓口に送付
  3. **TKC 会報**: `docs/announce/tkc_journal_jpcite.md` を TKC 寄稿窓口に送付
  4. **M&A Online**: `docs/announce/ma_online_jpcite.md` を編集部 contact form から送付 (houjin_watch + DD pack の M&A pillar cohort 訴求)
  5. **診断士会報**: `docs/announce/shindanshi_kaiho_jpcite.md` を中小企業診断協会 会報窓口に送付
- 完了確認: 5 通の送信完了 (掲載は審査後、organic 通常 1-2 週)。送信ログを `/tmp/articles_industry.txt` に記録
- 失敗時 fallback: 連絡先不明な誌は誌面奥付の「読者投稿/寄稿/取材依頼」窓口を確認、organic 範囲なので push 営業はしない (feedback_zero_touch_solo)

---

## Phase 5: 24h monitor + GEO bench week 1 (T23-T24)

### T23: 24h post-launch monitor (Slack + Sentry + Fly)
- 実行場所: CLI + WEB
- 手順:
  1. `flyctl logs -a autonomath-api -f` を別 terminal で常時 tail (5xx / OOM / migration error を目視監視)
  2. Sentry dashboard (https://sentry.io/) で `autonomath-api` project の Issues タブを open、新規 error が 0 を確認
  3. Slack #jpcite-alerts channel で `SLACK_WEBHOOK_URL` 経由の dispatch 通知を確認
  4. `for i in $(seq 1 24); do echo "[$(date)] healthz=$(curl -s -o /dev/null -w '%{http_code}' https://api.jpcite.com/healthz)"; sleep 3600; done > /tmp/healthz_24h.log &` で 24h 連続 probe (1h 間隔)
  5. 24h 経過後 `grep -v 200 /tmp/healthz_24h.log` で異常時刻だけ抽出
- 完了確認: 24h で 5xx Sentry issue=0 + healthz 200 持続率 ≥ 99%
- 失敗時 fallback: 5xx 発生時は `flyctl logs --no-tail | grep ERROR | tail -50` で context 取得、必要なら直前 commit に `git revert` して再 deploy

### T24: GEO bench week 1 baseline (Claude/ChatGPT/Gemini/Perplexity)
- 実行場所: WEB (各 LLM frontend) + CLI
- 手順:
  1. `data/geo_questions.json` (100 問、ja 70 + en 30) のうち先頭 10 問を baseline ピック
  2. Claude.ai / ChatGPT / Gemini / Perplexity の 4 surface で各 10 問を手動投入、`jpcite.com` 引用の有無を `data/geo_bench_w1.csv` に記録 (columns: surface, q_id, cited, citation_url, response_excerpt)
  3. `python scripts/geo_bench/score.py --input data/geo_bench_w1.csv` で平均 score を算出 (W1 baseline、target W4 平均 ≥ 1.2)
  4. 結果を `docs/_internal/geo_bench_w1_baseline.md` に記録
  5. 次週以降は `tests/geo/bench_harness.py` の Playwright 自動化に移行 (V3_WAVE5_BACKLOG H)
- 完了確認: `data/geo_bench_w1.csv` に 40 row (4 surface × 10 q) + baseline score docs に保存
- 失敗時 fallback: 一部 LLM が `jpcite.com` を全く引用しない場合、site/llms.txt + sitemap-index.xml の indexed 状態を GSC で再確認 (USER_RUNBOOK.md USER-WEB-15 sitemap submission の完了が前提)

---

## 完了確認 chart

| Phase | task 数 | 完了条件 |
|---|---|---|
| 0 deploy verify | 3 (T01-T03) | post_deploy_verify_v3 PASS + Fly machine started + GHA 14/14 |
| 1 DNS + Fly secret | 5 (T04-T08) | 6 host 解決 + Fly 25+ key + .env.local SOT + GHA mirror |
| 2 Stripe setup | 4 (T09-T12) | LIVE mode + JP tax + price_id + portal_config_id |
| 3 AI surface | 8 (T13-T20) | PyPI + 7 registry/store submission |
| 4 organic article | 2 task / 8 article (T21-T22) | Zenn + note + PRTIMES publish + 業界紙 5 本送付 |
| 5 monitor + GEO | 2 (T23-T24) | 24h healthz ≥99% + GEO W1 baseline 40 row |
| **計** | **24 task** | 全 done で v1.0-GA tag auto-trigger 待ち |

## ロールバック早見

- DNS: CF dashboard で旧 record 復活、Redirect Rule disable
- Fly secret: `flyctl secrets unset KEY -a autonomath-api`
- Stripe LIVE product: archive (削除不可)、`.env.local` の price_id を空に戻して T08 で再 mirror
- PyPI: `twine yank autonomath-mcp==0.3.4` (yank は install 防止のみ、削除ではない)
- gh repo rename: `gh repo rename autonomath-mcp -R shigetosidumeda-cyber/jpcite-mcp` で巻戻し
- 寄稿: 各誌に削除依頼可、ただし GEO 引用 cache は数週間残留

## 参照

- `USER_RUNBOOK.md` (v1, 193 行) — 旧 24 task の詳細 / 本 v4 で priority 再整理
- `V3_WAVE5_BACKLOG.md` — Claude AUTO 側の Wave 5 backlog (10 項目、本 RUNBOOK 範囲外)
- `CLAUDE.md` — production state SOT (146 runtime tools / 219 openapi paths / 11,601 programs 等)
- `docs/_internal/CURRENT_SOT_2026-05-06.md` — 直近 SOT note
- `docs/announce/*.md` — Phase 4 で publish する 8 本の本文 (Zenn / note / PRTIMES / 業界紙 5 誌)
