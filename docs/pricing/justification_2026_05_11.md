# jpcite ¥3/req 課金の根拠 — 実数 ROI による明文化

- snapshot_at: 2026-05-11
- 単価: ¥3 / billable unit (税込 ¥3.30)
- 匿名枠: 3 req/日/IP (JST 翌日 00:00 リセット)
- 課金方式: Stripe metered (使った分のみ・月額固定なし・最低利用期間なし・解約違約金なし)
- 想定読者: AI agent 経由で jpcite を呼び出すか否かを判断する最終利用者 (税理士・行政書士・中小企業診断士・M&A advisor・信用金庫渉外、およびそれら士業のクライアント企業のオペレータ)

このドキュメントは、jpcite が ¥3/req を請求する根拠を、対立する 3 つの代替案 (web search、無料 anonymous 枠、汎用 RAG API) との実数比較で示す。読み終えたとき、業務利用者が「払う方が圧倒的に安い」と判断できる材料を残すことが目的。

---

## A. 「公的情報の web search で済むのではないか?」への反論

### A-1. web search が業務に耐えない 3 つの構造欠陥

| 欠陥 | 具体的に何が起きるか | 業務上の損害 |
|---|---|---|
| 出典が不明 / 古い / aggregator 引用 | 検索上位は noukaweb / hojyokin-portal / biz.stayway 等のまとめサイトが占める。これらは省庁ページから孫引きで、しばしば締切・要件・対象業種を旧版のままミラーする。 | 締切過ぎの制度を顧問先に案内 → 案件単独で機会損失 ¥10-200 万、顧問契約に不信感が伝播 |
| 更新時刻が分からない | web search 結果の HTML には fetched_at が無い。「最終更新 2024-XX-XX」表記は当該サイトの自己申告で、ミラー元の更新と一致する保証は皆無。 | 「最新と思っていた要件が旧版」事故。判明するのは顧問先が申請して窓口で差し戻された時 |
| LLM が孫引きを正解扱いする | 一般 web search が aggregator を上位返却すると、LLM はそれを「複数ソースで一致 = 確からしい」と評価しがち。誤りが滝のように下流に伝わる。 | LLM 生成のチェックリスト・申請ストーリーが aggregator 由来の旧版要件を骨格に組まれる。修正コストが累積する |

### A-2. jpcite の構造が web search の 3 欠陥を解消する

- **`source_url` は省庁・自治体・公庫の一次資料に直リンク** (`noukaweb` / `hojyokin-portal` / `biz.stayway` 等の aggregator は `source_url` から ban、CLAUDE.md「データ衛生」セクションで制度化されている)
- **`source_fetched_at`** が全レスポンスに付与される。優先度の高い出典は再取得中央値 約 7 日。古ければ data-freshness ページで per-source 内訳を確認可能
- **`content_hash`** で「同じ URL を取り直したら本当に内容が変わったか」が判定可能。bulk 更新で sentinel になっていない (CLAUDE.md `source_fetched_at` 注記)
- **`known_gaps`** を Evidence Packet が明示。jpcite が「何を知らないか」を AI が読めるため、過剰主張が起きにくい
- **8 業法 fence** (税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47の2 / 司法書士法 §73 / 行政書士法 §19 / 社労士法 §27 / 中小企業診断士登録規則 / 弁理士法 §75) が出力に常時差し込まれる。「個別税務助言」「監査意見」「申請書面の代理作成」等は構造的に出さない設計

### A-3. 「1 制度取りこぼし = 顧問先損害」の数量化

業務 use case では、1 制度の取りこぼし損害は単発で次のオーダー (業界実勢) になる:

- **IT 導入補助金 (通常枠) を見落とした中小企業**: 補助金上限 ¥150 万を逃す。顧問先 1 件で年商比 1-3% の機会損失
- **省エネ補助金 / GX 投資補助 を見落とした製造業**: 設備投資 ¥3,000 万に対して補助率 1/2 適用なら ¥1,500 万を逃す
- **事業承継・引継ぎ補助金 (専門家活用枠) を見落とした M&A**: 補助上限 ¥600 万を逃す + 仲介手数料の自己負担拡大
- **研究開発税制 (試験研究費の総額型) を見落とした製造業**: 試験研究費 ¥5,000 万なら税額控除 ¥500 万級を逃す (移行措置・上乗せ込みで変動)

これら 1 件の取りこぼしが顧問先で発生すると、顧問契約 (¥3-10 万/月) の解除に直結する事例が業界実勢として頻発する。顧問契約 1 件解除 = ¥36-120 万/年 のロス。

### A-4. ¥3/req は web search 代替として圧倒的に安い

| 方法 | 100 req で発生する直接コスト | 取りこぼし 1 件で発生する想定損害 | ROI 倍率 |
|---|---|---|---|
| 一般 web search + LLM | 一般 LLM 入力 token 単価分のみ (¥10-100 程度) だが、aggregator 由来のため取りこぼし確率が高い | 顧問契約 1 件解除 ¥36-120 万 | 一見安いがリスクで赤字 |
| jpcite ¥3/req × 100 = ¥330 | ¥330 (税込) | 取りこぼし確率を構造的に下げる (一次出典・8 業法 fence・aggregator ban) | ¥330 を払うことで ¥36-120 万級の解除リスクを 1 オーダー下げる = **約 1,000-3,600 倍** |

「払う方が圧倒的安い」結論は、顧問契約 1 件のロスを 1 回避けるだけで 100 顧問先 × 12 ヶ月分の jpcite 課金を上回ることから出る (詳細計算は §D に分解)。

---

## B. 「無料の anonymous 3 req/day で済むのではないか?」への反論

### B-1. anonymous 枠の正しい用途

匿名 3 req/日/IP は次の 3 用途に限られる:

1. **開発・統合の動作確認** (Evidence Packet の構造を見て自前パイプラインに組み込む試走)
2. **one-off 個人利用** (個人事業主が自分の 1 件の申請可否を確認する程度)
3. **業務利用の事前検証** (5 点チェックリスト = 出典 URL / fetched_at / known_gaps / packet tokens / break-even の確認、料金ページに記載)

### B-2. 業務利用に anonymous 枠は構造的に合わない

- **IP per day 3 req 制限**: 同一オフィス・同一 VPN 配下の同僚と quota を共有する。1 人が試走で消費すると他の人は 0 req
- **MCP server 経由のシステム利用は数百-数千 req/月が常識**: 税理士事務所で 100 顧問先を月次レビューすれば最低 100 req/月。anonymous では 1 日で枯渇
- **rate limit ブロックは業務 UX の致命傷**: AI agent が cron で走ったときに `429 Too Many Requests` が返ると、その日の自動化フローが落ちる。anonymous は意図的に「業務に耐えない設計」になっている

### B-3. ¥3/req は「rate limit を外す」コストとして見ても異常に安い

- 税理士 1 人で 100 顧問先を月次レビュー: 100 req × ¥3.30 = **¥330/月**
- 顧問契約 1 件あたり月額 ¥3-10 万。100 顧問先のうち 1 件で課金額の 100-300 倍を回収できる
- jpcite 課金は 100 顧問先全員のレビューにかかる **総和** で ¥330。1 顧問先あたり ¥3.30/月 (税込)、顧問契約の **0.003-0.01%**

---

## C. 「他の RAG API (Perplexity / Tavily / Exa 等) で済むのではないか?」への反論

### C-1. 汎用 RAG の構造的な限界

| 項目 | 汎用 RAG (Perplexity / Tavily / Exa) | jpcite |
|---|---|---|
| 主たる corpus | 英語 SEO bias の web 全体 | 日本公的制度・法令・行政処分・採択事例・適格事業者の curated DB |
| 日本公的情報のカバレッジ | 検索インデックス依存 — 自治体補助金・公庫融資・税制特例は穴だらけ | 11,601 検索可能 programs (S/A/B/C tier) + 6,493 法令本文 + 9,484 法令名解決 + 50 tax_rulesets + 2,065 判例 + 362 入札 + 13,801 適格事業者 |
| aggregator 混入 | 構造的に防げない (上位 SERP に aggregator が常駐) | `source_url` に aggregator ban を制度化 (CLAUDE.md データ衛生) |
| 業法フェンス | なし — 個別税務助言・契約書添削・申請書面作成も生成する | 8 業法 fence で出さない領域を構造的に明示 |
| 監査対応の出典記録 | URL のみ。fetched_at / content_hash / corpus_snapshot_id なし | URL + fetched_at + content_hash + corpus_snapshot_id + known_gaps |
| compatibility / 排他ルール | 横断的に持たない | `am_compat_matrix` (sourced 4,300 pair) + 181 exclusion / prerequisite rules |
| 制度 ID 化 | 文字列マッチでブレる | `search_programs` で resolve、program_id 体系で安定 |

### C-2. 汎用 RAG では達成できない jpcite 固有価値

- **複数 DB 統合**: 制度 × 法令 × 法人 × 行政処分 × 採択事例 を 1 unit (1 req) で結合返却
- **8 業法フェンス**: AI 出力が個別税務助言・監査意見・申請代理に滑り落ちないよう構造制約。汎用 RAG は同じ制約を後付けでもかけにくい
- **税制 chain / 事業承継 matcher / 災害特例 surface 等の cohort 横断 endpoint**: cohort 横断の 22 軸クエリは汎用 RAG が日本公的領域では構造的に届かない
- **PDL v1.0 ライセンスでの NTA 適格事業者 13,801 行 (delta) + 月次 4M 行 bulk 自動 ingest**: 適格事業者照合は汎用 RAG では再配布不可

「日本公的制度 × AI agent 業務利用」の交点では、jpcite の 11,601 programs + 8 業法 fence + 一次出典固定が構造的優位。汎用 RAG では情報の正しさを毎回人手で検算する必要が残り、業務利用には負荷が大きすぎる。

---

## D. 業界別 break-even calculator (実数)

下記は典型 use case における 1 ヶ月 / 1 案件あたりの jpcite 課金額と、当該業務の単価との比率。すべて税込 ¥3.30/unit ベース、業界実勢の単価帯で算定。

### D-1. 税理士 — 100 顧問先 月次制度レビュー

- 利用量: 100 req/月 (1 顧問先 1 req 月次)
- jpcite 課金: 100 × ¥3.30 = **¥330/月**
- 顧問契約: ¥3-10 万/月/顧問先
- 100 顧問先 顧問売上: ¥300-1,000 万/月
- jpcite 課金 / 顧問売上 = ¥330 / ¥3,000,000-10,000,000 = **0.003 - 0.011%**
- ROI 倍率: 9,000 - 30,000 倍 (1 件の制度取りこぼし回避で簡単に回収)

詳細 → `case_studies/tax_accountant_monthly_review.md`

### D-2. 行政書士 — 建設業許可 1 件 DD

- 利用量: 18 req/件 (1 社フォルダ作成パック相当、mcp.json cost_examples より)
- jpcite 課金: 18 × ¥3.30 = **¥59.40/件**
- 許可申請報酬: ¥10-30 万/件 (新規・更新で変動)
- jpcite 課金 / 報酬 = ¥59.40 / ¥100,000-300,000 = **0.020 - 0.059%**
- ROI 倍率: 1,700 - 5,000 倍

詳細 → `case_studies/admin_scrivener_construction_license.md`

### D-3. 中小企業診断士 — 経営診断 1 件

- 利用量: 47 req/件 (M&A DD 1 社相当、mcp.json cost_examples より)
- jpcite 課金: 47 × ¥3.30 = **¥155.10/件**
- 診断料: ¥10-30 万/件
- jpcite 課金 / 診断料 = ¥155.10 / ¥100,000-300,000 = **0.052 - 0.155%**
- ROI 倍率: 640 - 1,900 倍

詳細 → `case_studies/sme_diagnostician_consulting.md`

### D-4. M&A advisor — 1 案件 DD

- 利用量: 47 req/件 (M&A DD 1 社、mcp.json cost_examples より)
- jpcite 課金: 47 × ¥3.30 = **¥155.10/件**
- DD 料: ¥100-500 万/件 (ミドル M&A の業界実勢)
- jpcite 課金 / DD 料 = ¥155.10 / ¥1,000,000-5,000,000 = **0.003 - 0.016%**
- ROI 倍率: 6,400 - 32,000 倍

詳細 → `case_studies/ma_advisor_dd.md`

### D-5. 信用金庫渉外 — 1 顧客 watch (月次)

- 利用量: 12 req/月 (houjin_watch + amendment 監視 + 月次レビュー)
- jpcite 課金: 12 × ¥3.30 = **¥39.60/月/顧客**
- 渉外担当の 1 顧客 LTV: 業界実勢 数百万円 (融資 + 為替 + 投資信託の総合)
- jpcite 課金 / LTV: 0.001% 未満
- ROI 倍率: 数千倍以上 (信用毀損 1 件回避で巨額回収)

詳細 → `case_studies/shinkin_customer_watch.md`

---

## E. 「払って失敗したらどうするか?」への保証

### E-1. リスクを構造的に限定する 4 装置

| 装置 | 効果 |
|---|---|
| Stripe metered = 使った分のみ課金 | 月額固定 0 円。最低利用期間なし、解約違約金なし。1 回も呼ばなければ課金 0 円 |
| anonymous 3 req/日 で先行 trial | 構造・出典・known_gaps を課金前に 5 点チェックリストで確認可能 (料金ページに明示) |
| `X-Cost-Cap-JPY` header | request 単位で予算 hard cap。batch / fanout 時の暴走防止 |
| ダッシュボード月額上限設定 | 月内に予算到達したら API は `cap_reached` で停止、次月リセット |

### E-2. 出典 URL は全 response に含まれる

- 監査・DD・顧問先説明用に転記可能
- AI agent が出した答えを人間が verify する経路が常に開いている
- `corpus_snapshot_id` + `content_hash` で再現可能性が担保される

### E-3. 解約は Stripe Customer Portal から自己解約

- 当月末まで API アクセス可、当月利用分のみ ¥3.30/unit 請求、次月以降の課金停止
- 解約手数料・違約金なし
- 再契約も同じ Stripe Customer Portal から即時

---

## F. 「課金 user が伸びる仕掛け」 — repeat 業務向け endpoint 群

業務利用では同じ user が月数百-数万 req を継続する。jpcite はその repeat utilization を低リスクで設計するための endpoint 群を備える:

### F-1. `previewCost` (実行前見積もり)

- batch / export / fanout の予測 units と金額を実行前に確認
- 見積もり自体は匿名 3 req 枠を消費しない
- 「Run before broad runs」が mcp.json `recurring_agent_workflows.activation_rule` に明示

### F-2. `Idempotency-Key` (POST 再試行で二重課金しない)

- 同一 Idempotency-Key の POST は 1 unit のみ課金
- ネットワーク障害・client 側 retry での二重課金事故を構造的に防止
- 中身は migration 087 `idempotency_cache` table が backing

### F-3. `X-Client-Tag` (顧問先別 fan-out 課金)

- 税理士・行政書士・中小企業診断士の B2B2C 用途で必須
- 1 つの API key で 100 顧問先分の利用を呼んだとき、tag 別に集計可能
- 顧問先別の原価が見える → 顧問先別の付加価値費用としてそのまま顧問料に転嫁可能
- `client_profiles` (migration 096) + `saved_searches.profile_ids` (migration 097) + `run_saved_searches.py` cron でクライアント別 fan-out が cron 化可能

### F-4. `get_usage_status` (quota 自己観察)

- AI agent が batch 開始前に quota を自前で確認
- 月額上限到達 (`cap_reached`) を事前に検出して人間に escalation 可能
- mcp.json `first_hop_routing.mcp_equivalents.quota_before_batch` で AI agent に推奨

### F-5. parent/child API key (migration 086)

- 1 つの parent API key から子 key を発行
- 顧問先 / 案件単位で子 key を渡す B2B2C 構成
- 子 key 単位での停止・rotate が可能 (情報漏洩時の被害局所化)

---

## G. 「払う価値」をひとことで

> jpcite ¥3/req は、AI agent が日本公的制度を扱う際に「一次出典付き・8 業法フェンス入り・複数 DB 統合済み」のレコードを 1 unit で取得する料金。汎用 web search や RAG では構造的に再現できない。
>
> 業務利用の単価 (顧問契約 ¥3-10 万/月、許可申請 ¥10-30 万/件、診断料 ¥10-30 万/件、M&A DD ¥100-500 万/件) に対し、jpcite 課金は **0.003 - 0.16% のレンジ** に収まる。 1 件の制度取りこぼし回避で年単位の課金額を回収できる構造で、ROI 倍率は典型的に **600 倍 - 30,000 倍**。
>
> 払って失敗するリスクは、Stripe metered + X-Cost-Cap-JPY + ダッシュボード上限 + anonymous 先行 trial + 出典 URL verify 経路 + 自己解約により構造的に限定済み。

---

## 関連ドキュメント

- `case_studies/tax_accountant_monthly_review.md` — 税理士 100 顧問先 月次レビュー
- `case_studies/admin_scrivener_construction_license.md` — 行政書士 建設業許可 1 件 DD
- `case_studies/sme_diagnostician_consulting.md` — 中小企業診断士 経営診断 1 件
- `case_studies/ma_advisor_dd.md` — M&A advisor 1 案件 DD
- `case_studies/shinkin_customer_watch.md` — 信用金庫 渉外 1 顧客 watch
- `/pricing.html` — 公開料金ページ
- `/data-freshness.html` — 再取得中央値 + per-source freshness 内訳
- `/sources.html` — 出典カタログ
- `/trust.html` — 信頼センター
- `/.well-known/mcp.json` — AI agent 向け discovery (auth / pricing / cost_examples / recurring_agent_workflows)
- `data/facts_registry.json` — 公開数値 SOT (snapshot_at 2026-05-11、price_per_req_jpy_inc_tax=3.30)
- `data/fence_registry.json` — 8 業法 fence canonical
- `CLAUDE.md` — 8 cohort revenue model + データ衛生原則

---

## ADDENDUM Cost saving 新表現 (2026-05-12 user 指示反映)

旧 ROI 倍率表現 (§A-4 約 1,000-3,600 倍、§D-1 9,000-30,000 倍、§D-2 1,700-5,000 倍、§D-3 640-1,900 倍、§D-4 6,400-32,000 倍、§D-5 数千倍以上、§G 600-30,000 倍) は historical reference として §A-G 本文に保持。本 ADDENDUM では **1 案件 (1 req) 単位の純 LLM token cost 直接差分** で再表現する。

基準: 純 LLM (Claude Opus 4.7 入出力混合 ≈ 10K token in + 4K out @ $15/$75 per 1M token + 引用 reasoning 5x) ≈ **¥300/req**、jpcite 実料金 = **¥3/req fixed**。節約率は全業種一定で **99.00% off** (¥3 / ¥300 = 0.01)。本表は §A-G の ROI 倍率算定とは独立し、「同等出力を純 LLM token で出させた場合との単価差」のみを示す。quality / recall / latency / citation traceability / 8 業法 fence の構造的優位は §A-C 本文側で保持。

### 業界別 realistic frequency × cost saving table

| 業界 (§D 対応) | 代表 freq (req) | 純 LLM cost @¥300/req | jpcite @¥3/req | 節約 ¥ | 節約率 |
|---|---|---|---|---|---|
| 税理士 100 顧問先 月次 (§D-1) | 100 req/月 | ¥30,000 | ¥330 | **¥29,700** | 99.00% |
| 行政書士 1 件 建設業 DD (§D-2) | 18 req/件 | ¥5,400 | ¥59 | **¥5,341** | 99.00% |
| 中小企業診断士 1 件 経営診断 (§D-3) | 47 req/件 | ¥14,100 | ¥155 | **¥13,945** | 99.00% |
| M&A advisor 1 件 DD (§D-4) | 47 req/件 | ¥14,100 | ¥155 | **¥13,945** | 99.00% |
| 信用金庫 1 顧客 月次 watch (§D-5) | 12 req/月 | ¥3,600 | ¥40 | **¥3,560** | 99.00% |
| 会計士 監査 1 社 1 期 (追加) | 30 req/期 | ¥9,000 | ¥99 | **¥8,901** | 99.00% |
| 弁護士 法令 chain 1 query (追加) | 5 req/案件 | ¥1,500 | ¥17 | **¥1,483** | 99.00% |
| 社労士 1 顧問先 月次 (追加) | 8 req/月 | ¥2,400 | ¥26 | **¥2,374** | 99.00% |
| 司法書士 1 件 相続登記 (追加) | 6 req/件 | ¥1,800 | ¥20 | **¥1,780** | 99.00% |

範囲: ¥1,483/案件 (弁護士 5 req) 〜 ¥29,700/月 (税理士 100 顧問先)、9 業界平均 ≈ ¥8,900。節約率 99.00% 一定。本表の節約は §A-3 の取りこぼし回避 ¥10-200 万 とは別軸 (token cost 差分のみ) であり、§A-G の 8 業法 fence / 一次出典固定 / 複数 DB 統合等の構造的優位は別途保持。

**ADDENDUM Cost saving end** — Wave 46 tick5 cost saving SOT migration 2026-05-12
