# 信用金庫渉外 — 1 顧客 watch (月次)

- snapshot_at: 2026-05-11
- 単価: ¥3 / billable unit (税込 ¥3.30)
- 想定読者: 信用金庫・地方銀行・商工会の渉外担当、ないしそれら金融機関で AI agent (Claude / GPT / Cursor 等) を運用するオペレータ

## 業務シナリオ

渉外担当 1 人が 50-200 取引先を抱え、月次で各取引先について「次月の融資・補助金・税制特例・行政処分動向」を一行ダイジェストで把握しておく。営業訪問の事前準備・口座解約防止・追加融資提案の初動として運用する。

- houjin_watch (migration 088) で取引先ごとに watch 登録
- 月次で `houjin_360` (3-axis scoring) を refresh
- am_amendment_diff (12,116 行 cron-live) で商号 / 所在地 / 役員変遷を時系列追跡
- enforcement_cases (1,185 行) + am_enforcement_detail (22,258 行 — 6,455 with houjin_bangou) で行政処分の新着検出
- 取引先業種に compatibility のある補助金 / 融資制度の新着 (saved_searches + run_saved_searches.py cron)
- 適格事業者の登録状況変更検出 (NTA invoice 月次 4M 行 bulk)
- 採択補助金の monitoring (program_post_award_calendar、migration 098)

## 利用量と課金 (実数)

| 項目 | 値 |
|---|---|
| 1 顧客 月次 req 数 | 12 (houjin_watch refresh 1 req + houjin_360 1 req + amendment diff 2 req + enforcement 照合 1 req + 業種制度 saved_search 3 req + 適格事業者 1 req + 採択 monitoring 2 req + 余裕 1 req) |
| 単価 | ¥3.30/unit (税込) |
| **1 顧客 月次 jpcite 課金** | **¥39.60/月/顧客** |
| 100 顧客 月次合計 | ¥3,960/月 |
| 100 顧客 年間 | ¥47,520/年 |

`saved_searches.profile_ids` (migration 097) + `run_saved_searches.py` cron で 100 顧客分を 1 ジョブで fan-out 可能。

## 業務単価との比較

| 項目 | 値 |
|---|---|
| 営業訪問 1 回の自社コスト (人件費 + 移動 + 機会費用) | ¥10,000-30,000/回 |
| 渉外担当 1 人の月給 | ¥30-60 万/月 (賞与・福利込みで実質コスト ¥50-100 万/月) |
| jpcite 課金 / 営業訪問 1 回コスト | **0.13 - 0.40%/月/顧客** |

## 費用対効果の前提 — 取りこぼし 1 件で何が起きるか

信用金庫渉外で「公開情報の見落とし」が起こす典型損害:

- **取引先の行政処分発覚を遅らせて与信判断を誤る** — 不良債権化・回収不能につながる可能性
- **取引先が新設補助金で設備投資資金を満たし他行へ流出** — 営業機会の喪失
- **適格事業者番号取消し検出遅れによる仕入税額控除事故** — 取引先からの信用毀損 + 別の取引先への波及
- **取引先採択補助金の交付決定取消 (grant_refund 1,498 行 amount_yen 持ち) を見落とし** — 返還義務承継リスクに気付かず追加融資、不良債権化
- **商号変更・本店移転・役員変遷の見落とし** — 反社チェック基準データの陳腐化、コンプラ違反リスク

¥39.60/月/顧客、年間 ¥475.20/顧客。100 顧客なら年間 **¥47,520** で、月次の公開情報 watch を同じ条件で回せる。

明示的な前提では、100 顧客 × 12 req/月 = 1,200 req/月。web search の手作業を 1 顧客 30 分と置くと 50 時間/月の調査作業になるため、jpcite はその調査準備を request-count ベースの固定費に置き換える。

## なぜ web search や anonymous 枠で代替できないか

- **web search**: 行政処分公示 (省庁 + 自治体) を 100 顧客分手作業で毎月当たる工数は破綻 (1 顧客 30 分 × 100 = 50 時間/月、渉外 1 人の月稼働の 1/3 が消える)
- **anonymous 3 req/日**: 100 顧客 × 12 req = 1,200 req/月。anonymous では 400 日かかる計算で物理的に不能
- **一般 AI / 長文資料投入**: 商号変遷 / 役員変遷 / 適格事業者番号 / 補助金交付決定取消 の curated DB は jpcite 固有。houjin_watch + webhook によるリアルタイム検出も長文資料を毎回 AI に渡す運用では構造的に不可

## jpcite を使った場合の構造的優位

- `houjin_watch` (migration 088) でリアルタイム法人改正 webhook
- `dispatch_webhooks.py` cron で 100 顧客分の watch を 1 ジョブで配信
- `houjin_360` 3-axis scoring で総合的な信用評価補助
- `am_amendment_diff` (cron-live 2026-05-02) で 商号 / 所在地 / 役員変遷を時系列追跡
- `am_enforcement_detail` (22,258 行 — 6,455 houjin_bangou 紐付き、amount_yen 持ち grant_refund 1,498 / subsidy_exclude 476) で行政処分の影響額を直接照会
- `cross_check_jurisdiction` (Wave 22) で 登記 / 適格事業者 / 採択地域の不一致を検出
- 個別与信判断・個別融資判断は出さない (`do_not_provide.credit_judgment` per facts_registry; TDB / TSR / 商工リサーチに handoff)
- 信用判断は出さず、公開情報の事前 awareness を高める補助線として運用

## 反論への先回り

- 「信用情報法・名誉毀損リスクがあるのでは?」 → jpcite は与信判断・破産確率・反社確実性 を構造的に出さない (`facts_registry.json:do_not_provide`)。jpcite は公開情報の集約のみ、信用判断は TDB / TSR / 商工リサーチに handoff する設計。信用金庫の渉外担当が「公開情報の事前 awareness」を高めるための tool であって、与信判断 tool ではない
- 「12 req/月/顧客は少なすぎないか?」 → 月次の routine monitoring としては典型的な配分。事件発生時 (行政処分・商号変更・採択取消等) に追加 req を呼んでも 1 件 5-20 req 程度で済む。年間でも 150-300 req/顧客 を超えることはまれ
- 「saved_search で 100 顧客一括 fan-out した時の単価表示は?」 → `X-Client-Tag` per 顧客 + `usage_events.client_tag` (migration 085) でクライアント別に集計。月次 invoice はクライアント別の内訳付き

## 関連 endpoint / 設定

- `houjin_watch` — リアルタイム法人改正 watch (migration 088)
- `dispatch_webhooks.py` cron — webhook 配信
- `houjin_360` — 法人 3-axis scoring (R8)
- `am_amendment_diff` — 改正履歴 cron-live
- `am_enforcement_detail` — 行政処分詳細 (22,258 行)
- `cross_check_jurisdiction` — 不一致検出 (Wave 22)
- `saved_searches` + `saved_searches.profile_ids` (migration 097) — 顧客別 saved search
- `run_saved_searches.py` cron — 100 顧客 fan-out 実行
- `X-Client-Tag` — 顧客別課金集計
- `previewCost` — 実行前見積もり

## まとめ

信用金庫渉外 1 顧客 watch、月額 ¥39.60 (税込)。年間 ¥475.20/顧客、100 顧客でも年間 ¥47,520。信用情報法 fence により与信判断領域は犯さず、渉外担当の事前 awareness を高める補助線として使う。専門判断・与信判断の代替ではなく、公開情報の確認下地としてレビューしてください。
