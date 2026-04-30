# D-Day Execution Matrix — 2026-05-06 (Wed) JST

> **要約:** launch 当日 (2026-05-06 水) の分単位スケジュール + チャネル別 A/B コピー + 計測 + クライシス対応 + stretch 目標。`docs/launch_war_room.md` の運用面と `docs/launch_content.md` / `docs/ab_copy_variants.md` のコピー素材を 1 本に畳んだ実行表。ドメイン / ブランド名は rebrand pending (`project_jpintel_trademark_intel_risk`) のため `jpcite.com` / `[BRAND]` / `[HANDLE]` placeholder で固定する。実名の投入は launch 48h 前に replace-all。
>
> 原則: 単独オペレーション (梅田 1 名)。並列ボットなし。全ツイート・HN 投稿は自分の手で enter。

関連: `docs/launch_war_room.md` (ops) / `docs/launch_content.md` (long-form copy) / `docs/ab_copy_variants.md` (hero コピー) / `docs/fallback_plan.md` (fallback) / `docs/competitive_watch.md` (competitor watch) / `docs/customer_dev_w5.md` (interview pipeline) / `docs/conversion_funnel.md` (metrics).

---

## 0. Firing order summary (canonical timeline)

**1 表で全 channel の発射時刻 を統一管理する**。 個別 channel の draft (`docs/launch_assets/*.md`) や ops doc (`launch_war_room.md`) と齟齬が出た場合は本表が正本。conflict が見つかったら全 doc を本表に揃える。

| JST | UTC | ET (US East) | PT (US West) | チャネル | 備考 |
|-----|-----|--------------|--------------|---------|------|
| **09:00** | 00:00 | (前日) 20:00 | (前日) 17:00 | Zenn (publish) + LinkedIn (post) | scheduled publish。朝通勤帯 JP audience |
| **09:00** | 00:00 | (前日) 20:00 | (前日) 17:00 | X thread 1/8-8/8 | thread 連打、最終 tweet に Zenn URL + GitHub URL |
| **10:00** | 01:00 | (前日) 21:00 | (前日) 18:00 | Email (first 500 subscribers) | X 投稿 1h 後、購読者向け一斉送信 |
| **11:00** | 02:00 | (前日) 22:00 | (前日) 19:00 | (HN 不在 — JP 朝で X / Zenn / Email の手応えを観測) | metrics snapshot のみ |
| **15:00** | 06:00 | 02:00 | (前日) 23:00 | metrics rollup (午後 snapshot) | `research/metrics/2026-05-06_t15.json` 書き出し |
| **17:00** | 08:00 | 04:00 | 01:00 | Discord / Slack 告知 (3 箇所まで) | invite 確認後のみ |
| **19:00** | 10:00 | 06:00 | 03:00 | Reddit (`r/programming` 等) | LocalLLaMA は fit に応じて skip 可 |
| **22:30** | 13:30 | **09:30** | **06:30** | **HN "Show HN: ..." (LEAD)** | **(09:30 ET = HN morning peak window)** US East Coast morning coffee + West Coast wake-up |
| 22:45 | 13:45 | 09:45 | 06:45 | HN first comment (自分で body 補足 + Q&A) | 他者 Q&A 埋没防止 |
| 23:00-25:00 | 14:00-16:00 | 10:00-12:00 | 07:00-09:00 | HN comment monitoring (能動 reply) | HN 4h 壁判定 (28:30 JST = 翌 02:30 JST) |

**JST 22:30 を HN の sweet spot に決めた根拠**: HN traffic peaks 09:00-11:00 ET (US morning) — JST 22:00-24:00 帯。22:30 JST は (a) US Pacific 06:30 PT = 西海岸 wake-up、(b) US East 09:30 ET = 東海岸 morning coffee の中間で front-page 算法が最も新規 submission に有利な時間。逆に JST 11:00 = 前日 ET 21:00 = HN dead hour、JST 20:00 = ET 06:00 = 早すぎて深夜 lurker 帯のため front page bucket に滞留しない。

**Zenn / LinkedIn は既に publish 済 (D-Day 09:00 JST)** — HN まで 13.5h の organic runway を確保 (JP audience による Zenn いいね・X RT・LinkedIn impression が HN 投下時点での "social proof" になる)。

---

## 1. D-Day timeline (JST)

すべて JST、単独実施。前日 (5/5) 23:00 に全ドラフトを scheduler または local draft に積み、当日朝に差し替える。

| 時刻 | ゲート | アクション | 成功判定 |
|------|-------|-----------|---------|
| **07:00** | smoke | `BASE_URL=https://jpcite.com ./scripts/smoke_test.sh` + `python tests/mcp_smoke.py` + `curl -s https://jpcite.com/meta \| jq .total_programs` | 全 probe green / `total_programs >= 6658` / Sentry 過去 12h で P0=0 |
| 07:10 | kill switch | Cloudflare WAF Custom rule **`autonomath-emergency-deny`** が Action=LOG / Expression=`(false)` で **pre-create 済み** であることを確認 (`docs/_internal/launch_kill_switch.md` §2 Lever 1)。`flyctl secrets list -a autonomath-api` で `KILL_SWITCH_GLOBAL` が未設定 (off) であることを確認 | rule 存在 + LOG mode / secret 未設定。incident 時に 1 click で BLOCK へ flip 可能な状態 |
| 07:20 | infra | Fly metrics / Sentry / Stripe webhooks / Cloudflare Analytics / UptimeRobot を 5 tab pin, 2nd screen へ | 全 dashboard リロードでエラーなし |
| 07:30 | status | `site/status.html` の `Last updated` を今朝にして commit | Pages redeploy < 30s |
| **08:00** | Zenn 公開 | 長文 (`docs/launch_content.md` Zenn 版) を **scheduled publish**。朝通勤タイミングに当てる | Zenn 記事 URL 確定、記事内 canonical は `jpcite.com/articles/launch-announce` |
| 08:45 | pre-X | X thread 1/8-8/8 の本文を `drafts/` から最終確認、タイポ検索 (「補助金」「排他」「一次資料」) | draft 8 本準備完 |
| **09:00** | X 投下 | thread 1/8 を post、以降 30-60 秒間隔で 2/8-8/8。最終 tweet に Zenn 記事 URL + GitHub URL | thread 成立、RT/いいね の初期 pulse を監視 |
| 09:15 | @mention | Thread 最終 tweet で 1 名だけ柔らかく @ (不特定多数への bomb ではなく、自然な紹介) | @ は最大 2 名まで (`tone check` §6) |
| **10:00** | LinkedIn | 日英 dual (JP primary, EN 追記) で 1 post。Zenn URL + 英語版 short description | Impressions 目標なし、名刺代わり |
| 10:30 | buffer | コーヒー休憩、返信はまだしない | 感情の pulse を強制的に落とす |
| 11:00 | check-in | X / Zenn / LinkedIn の初動 metrics snapshot。HN 投下 (22:30) までの runway 観測 | HN は **22:30 JST** に shift (§0 Firing order summary 参照、09:30 ET = HN morning peak window) |
| 12:00 | lunch | 本人は一度画面から離れる。30 min 離席 | F5 中毒の自己遮断 |
| 12:30 | triage | 返信キュー確認: X replies / HN comments / Zenn reactions を分類 (技術 / 要望 / 批判 / spam) | 件数ログ化、P0 question を 10 件まで抽出 |
| **14:00** | reply + outreach | X で最も engagement の高い 3 件に個別 reply。`docs/customer_dev_w5.md` §3 の warm list (Zenn 記事コメント / 勉強会 LT 登壇者) から 20 名へ interview 打診メール一斉送信 (per-recipient rendered、テンプレ bulk 禁止) | 20 send 完了、auto-response ≥ 3 |
| 15:00 | metrics rollup | 午後 snapshot。HN は **22:30** 投下のため 15:00 時点では未投下。X / Zenn / LinkedIn / Email の累計を `research/metrics/2026-05-06_t15.json` に書き出し | 数字確認のみ、HN preparation の draft 最終チェック |
| 16:00 | metrics | `docs/conversion_funnel.md` §2 の rollup を手動で叩き 30 分 snapshot。`/v1/admin/metrics` でキー発行数 / checkout 試行数を目視 | `research/metrics/2026-05-06_t16.json` に書き出し |
| **17:00** | Discord / Slack | MCP 系コミュニティに告知 (「要 invite 確認」マーク、§4 を参照)。一社一 post、クロスポスト禁止 | 3 箇所まで、全て明示的な self-promo 可否確認後に post |
| 18:00 | dinner + breath | 1h 強制離脱。端末閉じる | exhaustion によるテキスト事故防止 |
| **19:00** | Reddit | `r/programming` にタイトル + 1 段落 + GitHub link。LocalLLaMA は MCP の fit を投稿前に自問 (MCP は local-LLM より Claude Desktop 主体、無理筋なら skip) | 投稿 or 静かに skip、どちらも acceptable |
| 20:00 | HN pre-flight | HN draft 最終確認 (`docs/launch_assets/hn_show_post.md`)。title 80 chars 以下、URL `https://jpcite.com` 200、GitHub placeholder 置換済、first comment 800-1500 chars。`https://news.ycombinator.com/showhn.html` 再読 | 22:30 投下前の最終 sanity check |
| **21:00-22:00** | partial post-mortem | 数値を集計 (unique visitors / POST /v1/billing/checkout / keys issued / 5xx / 429 / p95) + 今日の surprise 3 本を `research/retro/d+0_pre_hn.md` に書く | HN 投下前の baseline retro。P0 があれば quick-fix |
| **22:30** | **HN 投下 (LEAD)** | "Show HN: AutonoMath – ..." を `https://news.ycombinator.com/submit` に投下。**(09:30 ET = HN morning peak window)** | HN item id を控える、score 3 以上で front page bucket に入ったと判定 |
| 22:45 | HN body | 自分で first comment を投下 (2 段落、ボディ補足 + 技術 Q&A 受付文)。X thread に reply で `Also on HN: [URL]` (1 回のみ) | 他者 Q&A を埋没防止 |
| 23:00-25:00 | HN monitoring | コメント・karma を 30 分刻みで snapshot。能動 reply は質問のみ (defense 型反論しない) | HN 4h 壁判定は 02:30 JST (翌 D+1)。深夜帯 monitoring は 90 分まで、それ以降は alert 任せ |

**禁止**: D+1 (翌日) の「もう一回だけ見る」。F5 は自己破壊。**HN 投下が 22:30 JST に shift したため、深夜 90 分は active monitoring 必須**だが、25:00 (翌 01:00 JST) 以降は能動行動を止め PagerDuty alert のみに任せる。sleep は最低 5h 死守。

---

## 2. Variant copy (A/B hypothesis 付)

フレームは `docs/ab_copy_variants.md` §4 と整合: v1 feature-first / v2 outcome-first / v3 trust-first。lead は 1 つ、他は backup としてキープ、負け筋が確定したら 48h 以内に入れ替え。

### 2.1 X thread — first tweet (≤280 chars JP)

- **v1 (feature-first):**
  「日本の制度 6,658 件を REST + MCP で直引きできる [BRAND] を launch しました。検索 / 詳細 / 排他チェック を 1 行 curl で、Claude Desktop からも呼べる。全件 source_url + fetched_at の一次資料リンク付き。[Zenn URL]」
- **v2 (outcome-first) — LEAD:**
  「『この補助金、あれと併用できる?』を AI エージェントが 1 発で答える。日本の制度 6,658 件を API 化した [BRAND] を今日 launch。REST でも MCP でも、Claude Desktop から直呼び OK。無料で叩けます。[Zenn URL]」
- **v3 (trust-first):**
  「制度データの幻覚を止めたくて作りました。6,658 件の日本の補助金 / 制度情報を、全件 公式 URL + 取得日付で API 化。Jグランツは申請 portal、[BRAND] は discovery + compatibility 層という棲み分け。[Zenn URL]」

**lead 採択理由 (v2):** X の JP dev コミュニティは「誰が何に使えるのか」の 1 行が最も刺さる。v1 は機能羅列で滑りやすい、v3 は真面目すぎて thread 全体のトーンで十分語れる (1/8 は引きに回す)。

### 2.2 HN — post title (≤80 chars, EN, HN convention)

- **v1 (feature-first):**
  `Show HN: 6,658 Japanese government programs as a REST + MCP API`  (73)
- **v2 (outcome-first):**
  `Show HN: Ask an agent "can I stack these two subsidies?" for any JP program`  (75)
- **v3 (trust-first) — LEAD:**
  `Show HN: A primary-source-linked API for Japan's 6,658 institutional programs`  (78)

**lead 採択理由 (v3):** HN audience は「source + structured」に反応が強い (cf. "data with citation" 系タイトルの historical uplift)。feature-first はジェネリック、outcome-first は colloquial すぎて Show HN の tone から浮く。

### 2.3 HN — body first 3 lines

- **v1 (feature-first):**
  1. I built an API that exposes 6,658 Japanese government subsidy / loan / tax programs as structured JSON, plus a MCP server so Claude / Cursor can call it directly.
  2. Who for: devs building JP-facing agents, RAG stacks that need Japanese regulatory context, and teams evaluating subsidy eligibility programmatically.
  3. What's different: every record links back to the primary source URL with a fetched-at timestamp, exclusion rules are first-class, and the MCP surface mirrors the REST one.

- **v2 (outcome-first):**
  1. "Can I combine this subsidy with that loan?" is a question that currently takes a Japanese consultant ~2h; our API answers it in one call.
  2. Who for: anyone whose LLM-powered product needs to reason about Japanese government programs (subsidies, tax incentives, policy loans, accounting rules).
  3. What's different: we don't just return a list, we ship 35+ exclusion rules (mutex / condition tags), lineage to primary sources, and first-class MCP tools.

- **v3 (trust-first) — LEAD:**
  1. Japanese institutional data is mostly PDF + prefectural HTML, which is why subsidy-related LLM answers hallucinate constantly. This API fixes the data layer.
  2. Who for: RAG / agent builders targeting Japanese SMBs, farmers, or any regulated domain, where "wrong amount" or "wrong deadline" is a legal hazard.
  3. What's different: all 6,658 programs carry a `source_url` + `fetched_at`; exclusion rules are encoded (35+ today, growing weekly); both REST and MCP surfaces are first-class (not an afterthought wrapper).

**lead 採択理由 (v3):** HN コメンター は「なぜ作ったか」「どの failure mode を解消するか」に reward を与える傾向。trust-first はその対話の出発点をそのまま与える。

### 2.4 LinkedIn — opener (≤3 sentences, JP primary)

- **v1 (feature-first):**
  「日本の制度データ 6,658 件を REST + MCP API で公開しました。補助金・税・政策融資・会計・法令のクロスリファレンスをクエリ 1 発で引けます。Claude Desktop などの AI エージェントから直接呼べる設計です。」
- **v2 (outcome-first) — LEAD:**
  「『この補助金は他と併用できるか』— この判定を AI エージェントが数秒で返せるようにしたくて、[BRAND] を作りました。日本の制度 6,658 件を API 化、併用可否ルール 35+ 本、一次資料 URL 全件付き。今日 self-serve で公開です。」
- **v3 (trust-first):**
  「Japan の制度データはまだ PDF と都道府県 HTML の海で、RAG の幻覚の温床です。6,658 件を一次資料 URL 付きで構造化し、REST + MCP API として公開しました。dev-first, self-serve, 法令遵守を前提の設計です。」

**lead 採択理由 (v2):** LinkedIn JP は B2B 意思決定者と mid-career engineer の mix。「何が解けるか」から入って技術詳細は 2-3 行目で補うのが滞留時間が伸びる。

---

## 3. Metrics to watch during launch window

計測レイヤーは `docs/conversion_funnel.md` §2 を流用。当日は **30 分刻みで snapshot**、自分で Slack DM (or local file) に書き溜める。dashboards を眺めるだけではなく、**数字をスプレッドシート (`research/metrics/2026-05-06_halfhourly.csv`)** に手入力。

| 区分 | 指標 | ソース | 30min スナップ | 当日目標 | 赤信号 |
|------|------|--------|----------------|---------|--------|
| traffic | **Cloudflare unique visitors** (landing) | Cloudflare Web Analytics `zone > analytics > traffic` | `unique_visitors_30m` | 累計 800-2,000 | 1 時間連続 0 visitors (beacon 死亡疑い) |
| traffic | **Top referrer** | 同上 | referrer top 3 | HN / Zenn / X が上位 | reddit spike で bot の可能性 |
| intent | **`POST /v1/billing/checkout` count** | `/v1/admin/metrics` (stripe event `checkout.session.created`) | `checkout_start_30m` | 累計 10-40 | 累計 100 超で abuse / bot 疑い |
| conversion | **API key issued count** | `api_keys` 新規挿入 count | `keys_issued_30m` | 累計 20-80 | 累計 0 → signup UX 破損 |
| health | **Error rate (5xx)** | Fly logs + Sentry | `5xx_per_min` | < 0.2% | > 2% 5 分連続 = rollback gate (war room) |
| health | **p95 latency** `/v1/programs/search` | Fly metrics | `p95_ms` | < 400ms | > 1,000ms 持続で cache / DB 診断 |
| abuse | **429 count** | Fly logs | `429_per_min` | < 5/min | > 50/min で DDoS 疑い、自己限の場合は free tier burst 上限見直し |
| abuse | **401 ratio** | Fly logs | `401_pct` | 初日 20-40% 許容 (未認証 curl 試行) | 80% 超で docs 誘導ミス |

**追加計測**: HN karma / score / position は 22:30 (投下直後) / 23:00 / 23:30 / 24:00 / 翌 01:00 の 5 点で目視ログ (HN は 22:30 JST 投下に shift、§0 参照)。Zenn のいいね・コメント数は 10:00 / 12:00 / 14:00 / 17:00 / 22:00 の 5 点。X engagement は impressions > 1,000 の thread post のみ追跡。

---

## 4. Crisis playbook

### 4.1 Fly machine crash → DNS flip to Cloudflare Pages

判定: `flyctl status -a AutonoMath` で machine が `stopped` / `crashed` 連続 5 min、もしくは `/healthz` が 3 min 以上 5xx。

手順 (所要 4-7 min):

1. **確認** — ローカル DNS 問題を除外 (`dig jpcite.com @1.1.1.1` 他 resolver)
2. **DNS flip** — Cloudflare dashboard → `jpcite.com` → DNS → apex レコードを CNAME `[BRAND]-fallback.pages.dev` に編集 (proxied, TTL 300)
3. **status.html 更新** — `site/status.html` の `active` class を `.state.ok` → `.state.down` に移す、commit + push → Pages auto-deploy
4. **HN / X thread に 1 行状態告知** — 「temporary fallback, API endpoints are 503, landing is static」
5. **復旧** — Fly `status=started + health passing` を確認後、DNS を Fly A/AAAA に戻し、status.html を `.ok` に戻す

**ボタンを押すのは**: 梅田本人 (単独)。代理なし。`docs/fallback_plan.md` の手順書を 1 画面で開いておく。

### 4.2 HN / Reddit が spam フラグ

パターン:
- HN: 新規 submission が `[flagged]` で front page 外に消える
- Reddit: AutoModerator で auto-remove

応手:
1. **削除しない** (削除履歴が残るとアカウントに対する将来的 penalty を招く)
2. HN ならメール `hn@ycombinator.com` に 1 段落で事実関係を送る (「Show HN として自分のプロジェクトを投下した、spam ではない、再検討お願い」)。煽らず、短く。
3. Reddit は mod mail で「read the sub rules, re-flair if needed」。削除ではなく修正を提案。
4. コメント欄には出没し、真摯に回答を続ける (上書きで埋没させるのではなく、質の高い対話を 2-3 本)

**やってはいけない**: アカウント作り直し / sock puppet / upvote 依頼 (`docs/launch_war_room.md` §tone check)。

### 4.3 Negative technical review 対応 (例: "just a wrapper around MAFF scraping")

想定批判と prepared response の draft:

> **批判**: "This is just a wrapper around MAFF / Jグランツ. Why pay for it?"
>
> **response draft (HN / X で使える 150 words):**
>
> Fair point — let me separate the layers.
>
> 1. **Source coverage**: Jグランツ covers application / portal flow for ~300 central programs. [BRAND] aggregates 6,658 programs across central ministries, 47 prefectures, municipal programs, JFC (policy loans), and subset of tax / legal / accounting references. Jグランツ is the application layer; we are the discovery + compatibility layer.
>
> 2. **Lineage**: every record carries `source_url` + `fetched_at`. You can verify any field against the primary source in 1 click. That's not what a scraper does — that's what an audited data pipeline does.
>
> 3. **MCP-first design**: the MCP surface is not a retrofit, it was designed alongside the REST surface so agents can use both interchangeably.
>
> 4. **Exclusion rules**: 35+ mutex / condition-tag rules encoded as first-class data. This is the answer to "can I combine these two?" which scraping cannot produce.
>
> The data is public. Our claim is not "exclusive data" — it is "structured, lineaged, MCP-ready, cross-indexed." Happy to show a 30-line RAG eval that makes this concrete.

トーンは **防御せず、層を分ける**。反論ではなく地図の提示。`docs/competitive_watch.md` §1 の Jグランツ section の差別化軸をそのまま流用。

---

## 5. Stretch goals (1 つでも当たれば儀式完了)

### 5.1 Inbound from JP tech media

**目標**: D-Day に 1 社から DM / 連絡。

- **候補媒体 (ジャンル / URL)**: TECHPLAY (イベント・技術記事連携), ITmedia (政府 DX / SaaS 取材), 日経 xTECH (regtech / 公共 DX), Publickey (インフラ/SaaS 個人運営, dev 層リーチ), ThinkIT (国内 SaaS 紹介)
- **reporter 名**: **要調査 / 要 実名確認**。launch 週より前に `research/press_contacts.md` を作成して「政府 DX」「補助金」「regtech」「MCP」のビート担当を特定する。本 doc 時点では実名ハルシネーションを避けるため空欄。

**アプローチ禁止**: cold DM でリプライ乞食。**やること**は、Zenn 記事末尾と GitHub README 下部に「取材・寄稿歓迎、hello@jpcite.com」を 1 行、それだけ。

### 5.2 Partnership DM from "not competitor" side

`docs/competitive_watch.md` §1 table の 1-10 のうち、**partnership 可能性のある側**:

- (1) Jグランツ / デジタル庁 → 非競合。discovery API として上流互換のオファーあり得る (open data カタログ相互リンク)
- (7) 補助金ポータル系 media → 記事内 API 引用のオファー可能
- 公庫 / JFC 等 **非競合** 側からの DM は launch 後 72h までは普通に発生し得る

DM が来たら:
1. 1 時間以内に「確認しました、24h 以内に返信します」の短答
2. 具体提案は翌日以降。当日 adrenaline 下で署名入り文書を出さない
3. `research/partner_inbound.csv` に一行で記録

---

## 6. Tone check (self-audit before each post)

1. @-mention は 1 投稿に **最大 2 名まで**。それ以上は spray 扱いなのでやらない。
2. HN post と Reddit post は **本文を変える**。identical cross-post は両サイトで evidence が残り、将来的な penalty を招く。
3. **Upvote 依頼・bot 購入・sock puppet 全面禁止** (`docs/competitive_watch.md` §7 non-goals と整合)。
4. ネガ競合比較は `docs/ab_copy_variants.md` §5 の anti-pattern に従う (Jグランツ 名指し disrespect 禁止、棲み分け トーン)。
5. 「残り X 時間限定」「今だけ」の scarcity framing 禁止 (`launch_compliance_checklist.md` §4 / 景表法)。
6. launch 当日の 4 回以上の「buy now」CTA 禁止 (1 posting 1 CTA、それ以上は incumbents でも disrespected)。

---

## 7. Channel priority (weighted attention)

下記の weight で「反応を見るべき窓」を決める (同時に全部は見られない)。

| チャネル | 初速 weight | 理由 |
|---------|-------------|------|
| HN | **40%** | dev reach + international + long-tail SEO |
| Zenn | 30% | JP dev コア読者層、コメントが depth ある |
| X | 15% | 瞬発・引用・インフルエンサーの pickup |
| LinkedIn | 5% | B2B 意思決定者の目に触れる (ただし当日の conversion 影響は低) |
| Reddit | 5% | ハマれば bonus、滑ってもノーダメ |
| Discord / Slack | 5% | invite 制、community fit 前提 |

合計 = 100%。2 chan 以上のイベントが同時に来たら HN を最優先、次に Zenn。

---

## Report

- **D-Day で最も traffic を連れてくるチャネル**: **Zenn**。JP dev 読者層の来訪 pace は HN より遅いが、launch 時刻 08:00 publish からの朝通勤帯がピッタリ重なり、HN が front page 外に落ちた後も残る。HN は峯値が鋭く短時間で燃え尽きる可能性。
- **再シェアで 10x する連絡先 3 カテゴリ** (実名を避け category で固定):
  1. **JP AI / MCP エコシステムの個人ビルダー** (Anthropic Japan community で活動する個人) — 要調査、名前確定前に DM しない
  2. **Jグランツ / デジタル庁 dev community 運営側の中の人** — 公式アカウント or 公開資料にハンドルが載っている人のみ @、実名ハルシネーション厳禁
  3. **農業・regtech vertical の著名 indie dev / founder** — `research/competitive_landscape.md` に記載のある人でも、直接 @-pitch は不適切。公開 thread に純粋な technical comment で立ち寄る程度に留める
- **Ethical/tone で削った tactic 1 本**: 「HN 投稿の直後に別アカウント 2 つ以上を friend に頼んで初速 upvote 3-5 ポイント入れてもらう」案。short-term には効くが、HN shadow ban 履歴に残り将来の submission 全部が flagged 予備軍になる。正攻法 (時刻選び + タイトル実名 + first comment 充実) だけで勝負する。
