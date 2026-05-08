# GEO / AI agent 基盤 100,000 units/day 成長計画

作成日: 2026-05-08

目的: jpcite を「AI が日本企業・制度・公的根拠を調べる前に最初に叩く公共情報レイヤー」に寄せ、100,000 billable units/day を到達KPIとして管理できる状態にする。100,000 units/day は税抜 ¥300,000/day、30日換算で税抜約 ¥9,000,000/month。

重要な前提: 100,000 units/day は自然発生する手動検索需要ではない。AI agent / BPO / 士業システム / 監査・DD・営業支援の自動ワークフローに組み込まれ、会社・顧問先・案件単位で反復実行される場合にだけ現実味がある。したがって価格を先に上げるより、`first paid call` から継続 workflow までの導線、予算上限、顧客別原価管理、成果物の価値を強くする。

## 現状判断

- 発見面は強い。`llms.txt`, `.well-known/mcp.json`, `server.json`, `mcp-server.json`, `openapi.agent.json`, robots, sitemap が揃っている。
- ただし実売上KPIは HTTP request 数ではなく `usage_events.quantity` の合計で見る必要がある。batch / compatibility / export 系では 1 request が複数 billable units になり得る。
- 現時点の最大課題は「AI が jpcite を見つけること」ではなく、「見つけた後に first paid call を迷わず実行し、匿名枠後に API key 付きで同じワークフローを継続すること」。
- 100,000/day は単発検索だけではなく、BPO、士業、M&A、監査、営業、金融、AI agent の反復ワークフローで作る。
- `¥3/unit` は据え置きが最も合理的。値上げは、AI が「回答前にまず jpcite を叩く」行動を弱める可能性がある。高単価化は base unit ではなく、audit/DD pack、watch digest、bulk workflow、hosted connector、private ingest、SLA など成果物・運用価値側で行う。
- 需要検証前に「10万/day需要がある」と断定しない。観測すべきは HTTP request 数ではなく、paid key ごとの `daily_billable_units`, `7d retention`, `first_billable`, `client_tag別units`, `scheduled job / webhook / batch` の継続率。

## 需要仮説の補正

100,000 billable units/day は、SEO 流入、LLM discovery、単発検索の自然増だけで到達する数値ではない。これは「AI agent / BPO / 士業 / SaaS 組込の反復 workflow に入った場合の運用目標」であり、自然需要予測ではない。

単発検索の延長では、仮に 1,000 paid keys が毎日 30 units 使っても 30,000 units/day に留まる。100,000/day には、少なくとも次のいずれかが必要。

- 50 組織が 2,000 units/day 使う BPO / 士業 / 金融 / DD 型
- 10 組込先が 10,000 units/day 使う SaaS / OEM / agent platform 型
- 顧問先・取引先・会社フォルダ・saved search・watch digest が日次 / 週次で自動再実行される workflow 型
- batch / CSV / export / compatibility / audit pack のように、1 request が複数 billable units になる高密度処理型

したがって、100,000/day の主KPIは「訪問数」や「検索回数」ではなく、反復 workflow に入った証拠で見る。

## 深掘りループ 1: GEO / AI agent 導線

狙い: ChatGPT / Claude / Cursor / MCP client が「一般Web検索より先に jpcite」と判断する。

実装方針:
- company work は `createCompanyPublicBaseline` を first paid call に固定する。
- broad public program work は `prefetchIntelligence` または `queryEvidencePacket` に固定する。
- `previewCost` は広いfanout前の無料preflightとして位置づけるが、回答生成の本体は paid evidence endpoint と明記する。
- `.well-known/mcp.json`, `server.json`, `llms.txt`, `openapi.agent.json` の route policy を一致させる。

主要KPI:
- agent manifest hit から `openapi.agent.json` import への率
- `previewCost` から paid evidence call への率
- anonymous 3/day 超過後の API key リトライ率

## 深掘りループ 2: 高頻度実務ワークフロー

狙い: ユーザーが「1回の検索」ではなく「会社・顧問先・案件ごとの毎回処理」として使う。

ワークフロー:
- 会社フォルダ作成: `previewCost` -> `company_public_baseline` -> `company_folder_brief` -> `evidence/packets/query`
- 月次顧問先レビュー: `previewCost` -> `evidence/packets/query` -> `prescreenPrograms` -> `application_strategy_pack`
- 取引先DD / 監査準備: `previewCost` -> `company_public_baseline` -> `company_public_audit_pack` -> `advisors/match`
- AI回答前の根拠取得: `getUsageStatus` -> `previewCost` -> `evidence/packets/query` -> `citations/verify`

### workflow 化後の unit 係数

下記の units は「ユーザーがその業務を毎回 jpcite 経由にした場合」の係数であり、自然需要ではない。実際の需要は、会社名 / 法人番号を入れる習慣、保存・batch・watch への導線、client_tag による顧客別原価説明、法務レビュー、初回利用後の反復率で大きく変わる。

- BPO / 士業が 1社フォルダを作るたびに 2-4 units
- 月次レビューで 1顧問先 3-8 units
- DD / 監査準備で 1対象 3-6 units
- AI answer grounding で 1質問 1-3 units

## 深掘りループ 3: 計測と売上予測

狙い: 100,000/day への進捗を毎日正しく見る。

必須集計:
- `daily_billable_units = SUM(quantity) WHERE metered=1 AND status<400`
- `daily_revenue_yen_ex_tax = daily_billable_units * 3`
- `active_paid_keys`, `new_paid_keys`, `first_billable_unit_keys`
- `stripe_unsynced_units`
- `units_by_endpoint`, `units_by_client_tag`, `top_customer_share`

値上げ判断前に最低 30 日見る指標:

| 指標 | 見る理由 |
|---|---|
| `anon_to_paid_retry_rate` | 匿名3回後に同じ workflow を API key 付きで継続したか |
| `first_billable_unit_rate` | key 発行後、実際に課金 call まで到達したか |
| `d7_repeat_paid_key_rate` / `d30_repeat_paid_key_rate` | 単発試用ではなく反復利用になったか |
| `units_per_active_paid_key_day` | 10万/day に必要な密度が出ているか |
| `artifact_units_share` | 単なる検索ではなく完成物 API が使われているか |
| `client_tag_usage_rate` | BPO / 士業 / 顧客別運用に入ったか |
| `avg_client_tags_per_key` | 1 組織が複数顧客・案件へ展開しているか |
| `batch_or_csv_units_share` | 人手検索ではなく業務処理に入ったか |
| `saved_search_or_watch_attach_rate` | 継続理由が作れているか |
| `cap_set_rate` / `median_monthly_cap_yen` | 従量課金への不安と許容予算 |
| `cost_preview_to_paid_call_rate` | 見積もりが課金実行に変わっているか |
| `refund_or_support_per_1k_units` | 価格・期待値・法務表現の摩擦 |
| `top_customer_share` | 10万/day が少数顧客依存になっていないか |
| `stripe_unsynced_units` | 売上認識・請求同期がスケールに耐えているか |

注意:
- Cloudflare request / visit は発見・SEO・bot状況の指標であり、売上KPIではない。
- Codex/Claude/curl/内部audit traffic は成長指標から分離する。
- referer は host 単位で集計し、AI discovery / search / direct / internal を分ける。

## 深掘りループ 4: 課金されるアウトプット

狙い: ユーザーが「¥3なら安い」と感じる単位を増やす。

強いアウトプット:
- 公的会社baseline: identity, invoice, enforcement, adoption, procurement, known gaps
- company folder brief: CRM / 顧問先メモに貼れる公開情報サマリ
- public audit pack: evidence ledger, mismatch flags, risk/gap register, review controls
- application strategy pack: 候補制度、条件、未確認軸、質問、期限・金額文脈
- evidence-to-expert handoff: 専門家へ渡す前の evidence brief

弱いアウトプット:
- 単なる検索結果リスト
- 出典のない要約
- 最終判断のように見える断定
- 内部進捗や収録作業中の数字を公開文面に出すこと

## 実装・テストループ

1. Agent OpenAPI に recurring workflow policy を追加し、AIが first paid call を迷わないようにする。
2. static `docs/openapi/agent.json`, `site/openapi.agent.json`, `site/docs/openapi/agent.json` を生成同期する。
3. `llms.txt`, `llms.en.txt`, `site/en/llms.txt`, `.well-known/mcp.json`, `server.json` に同じ recurring workflow を反映する。
4. GEO readiness guard で recurring workflow の欠落を検出する。
5. Cloudflare analytics export の UA分類を internal / AI crawler / bot に分け、成長指標から内部検証trafficを外せるようにする。
6. Cloudflare referer 集計を `refererHost` 依存から `clientRequestReferer` の host正規化に変え、GraphQL dimension drift と host分散を防ぐ。
7. unit tests, py_compile, OpenAPI export consistency, GEO readiness, JSON validation, diff check を通す。

## 次に残る実装候補

- `/v1/admin/funnel` または `stats_funnel` に `billable_units`, `revenue_yen`, `stripe_unsynced_units`, `first_metered_keys` を追加する。
- billing checkout / webhook / key issue 成功時に server-side funnel event を残す。
- playground の `data-cta` と `data-cta-variant` の計測差分を潰し、first billable unit へのクリック漏れをなくす。
- dashboard に `last_24h_units`, `7d_avg_units`, `projected_month_end_units`, `daily_goal_progress` を出す。
- `X-Client-Tag` を docs / SDK / examples で強め、BPO / 士業が顧客別に原価と利用量を説明できるようにする。
