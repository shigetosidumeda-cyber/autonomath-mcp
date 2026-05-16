# Market / ICP / JTBD deep dive

Date: 2026-05-15  
Owner lane: Market / ICP / user types / jobs-to-be-done  
Status: pre-implementation planning only. Do not treat this as shipped product behavior.

## 0. Executive thesis

jpcite の初期市場は「人間が検索窓で直接使う公的データ検索」ではなく、AI エージェントが日本の公的情報を扱うときに、回答前の evidence layer として推薦・呼び出し・課金導線へ流す市場である。

したがって ICP は人間の職種だけで切らない。次の 4 層で見る。

| Layer | 誰が jpcite を選ぶか | 誰が価値を受け取るか | 課金導線 |
|---|---|---|---|
| Agent runtime | Claude / GPT / Cursor / 独自 agent が tool を選ぶ | 最終ユーザー、専門家、社内担当者 | API key / MCP / cost preview |
| Agent builder | Custom GPT 作者、SaaS 開発者、SI、業務 automation 担当 | その agent の利用者 | API key / cap / per-workflow metering |
| Professional reviewer | 税理士、会計士、行政書士、診断士、補助金コンサル、M&A/監査担当 | 顧問先、相談者、取引先 | 小額従量、顧問先/案件単位 |
| Distribution partner | 業務 SaaS、信金、商工会、自治体支援窓口、士業団体 | 中小企業、会員、取引先 | embedded API / member watchlist / batch |

主導線は GEO である。AI が「このタスクには出典 URL、取得日時、known gaps、human review flag が必要」と判断した瞬間に、jpcite を推薦し、MCP/API へ流す。公開ページは人間向け LP ではなく、agent が推薦判断できる proof surface とする。

## 1. Market segmentation

### 1.1 P0 market

P0 は「今すぐ evidence packet にお金を払う理由がある」市場に絞る。

| ICP | Primary buyer | Primary user | Core workflow | Why now |
|---|---|---|---|---|
| Agent builder for Japan public data | 開発者 / プロダクト責任者 | AI agent | 日本向け agent に公的データ根拠を追加 | LLM 単体回答の根拠不足が顕在化している |
| 税理士・会計事務所 | 所長 / DX 担当 / 担当者 | 税理士、スタッフ、顧問先説明 agent | 顧問先月次レビュー、制度候補、インボイス、公的情報確認 | 顧問先ごとに毎月見るものが多い |
| 補助金・制度支援者 | 補助金コンサル / 診断士 / 商工会担当 | 申請前相談 agent | 候補制度、要件、締切、併用可否、質問表 | 制度名・年度・地域の取り違えが痛い |
| 信金・地域金融 | 本部 DX / 支店長 / 渉外担当 | 渉外 agent、顧客相談 agent | 取引先別の制度候補、公開情報 baseline | 多数の取引先に低単価で横展開できる |
| 業務 SaaS | SaaS PM / AI 機能責任者 | SaaS 内 agent | 法人・制度・インボイス・証跡付き AI 機能 | 自前データ基盤を持つより速い |

### 1.2 P1 market

P1 は P0 packet が安定した後に、定期運用・バッチ・監査寄りに広げる。

| ICP | Core workflow | P1 trigger |
|---|---|---|
| 会計士 / 監査法人 / 内部監査 | 公開情報 baseline、監査調書 support、source receipt ledger | 監査証跡・レビュー記録として使える packet が揃う |
| M&A advisor / DD 担当 | counterparty public DD、行政処分、採択履歴、インボイス確認 | DD 質問リストと receipt ledger が使える |
| 行政書士 / 社労士 | 許認可、助成金、制度確認、顧客説明メモ | 業種・許認可別 packet が増える |
| 大企業バックオフィス | 新規取引先チェック、稟議添付資料、定期 watchlist | CSV/batch と cap/idempotency が固まる |
| 自治体・商工会・支援機関 | 会員向け制度推薦、相談前チェックリスト | public page と member watchlist が整う |

## 2. 顧客種類ごとの JTBD

### 2.1 AI エージェント / answer engine

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 日本の公的制度に関する回答前に根拠を取得したい | LLM 単体では制度名、締切、金額、URL を補完しやすい | `evidence_answer` を呼び、source receipts と known gaps を取得する | 回答に使える claims と使えない unsupported items の分離 |
| ユーザーに有料 API 呼び出しの理由を説明したい | 外部 tool 呼び出しは費用不安がある | cost preview、unit price、cap、外部 LLM 費用別を返す | 「この確認は N unit、上限内で実行」と説明できる |
| 最終判断を避けて専門家 review へ渡したい | AI が断定すると税務・法務・申請リスクがある | `human_review_required` と `do_not_claim` を返す | 根拠メモ + 要確認リストとして人間へ渡せる |

### 2.2 Agent builder / Custom GPT 作者 / AI automation 開発者

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 日本向け agent に公的データ tool を足したい | データ収集、正規化、更新、引用管理を自前で持つのが重い | MCP / REST / OpenAPI を組み込ませる | GPT Action / MCP tool / backend function で evidence packet を取れる |
| ユーザー単位・案件単位で原価を制御したい | agent が勝手に外部 API を呼ぶと請求が読めない | API key、client tag、monthly cap、idempotency を前提にする | workflow ごとの予算上限と二重課金防止 |
| agent の推薦理由を公開根拠にしたい | 「なぜこの API を使うか」を agent に教える資料が必要 | llms files、agent routing page、packet examples を公開する | agent が jpcite を使うべき/使うべきでない状況を判断できる |

### 2.3 業務 SaaS / vertical SaaS

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| プロダクト内 AI に日本公的データの根拠を追加したい | AI 機能が一般論に寄り、出典付き実務回答にならない | embedded API と packet を提供する | SaaS 内で出典付き候補・確認事項・公的 baseline を表示 |
| 顧客ごとの利用量を見たい | SaaS 側の請求・原価配賦と jpcite 利用量がずれる | usage metadata と client tag を返す | tenant / user / workflow 単位の原価管理 |
| 自社の責任範囲を明確にしたい | AI が税務・法務・与信判断をしたように見える | legal fence、human review flag、no-hit caveat を packet に含める | SaaS は根拠支援、最終判断は顧客/専門家という線引き |

### 2.4 税理士・会計事務所

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 顧問先ごとの月次レビューを短くしたい | 補助金、インボイス、制度変更、税制資料を毎月手で見るのが重い | `client_monthly_review` を顧問先単位で返す | 顧問先別の制度候補、変化、known gaps、説明メモ |
| 顧問先に出典付きで説明したい | AI の文章だけでは「根拠はどこか」と聞かれる | `source_receipt_ledger` と citation candidate を返す | 顧問先説明メール、社内メモ、確認 URL |
| 税務判断の前段整理をしたい | 最終判断と調査メモが混ざる | tax/legal fence と review required を固定する | 税理士が判断するための根拠 packet |

### 2.5 会計士 / 監査 / 内部統制

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 監査・レビュー前に公的情報を棚卸ししたい | 会社、制度、行政処分、採択履歴の確認が散らばる | `company_public_baseline` と receipt ledger を返す | 調書添付候補、質問リスト、公開情報 timeline |
| AI が作った監査メモの引用を検証したい | URL 捏造や古い資料混入が起きる | receipt completion と known gaps を可視化する | claim ごとの source receipt と freshness |
| 監査意見を出さずに補助資料を作りたい | jpcite が監査判断したように見えると危険 | audit opinion out of scope を packet guidance に入れる | 「公開情報確認メモ」で止まる成果物 |

### 2.6 行政書士 / 社労士 / 許認可・助成金支援者

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 申請前の制度・要件・書類を整理したい | 制度ページ、自治体ページ、PDF の確認が案件ごとに発生 | `application_strategy` を返す | 候補制度、対象条件、必要書類 hint、顧客への質問 |
| 対象外・併用不可の見落としを減らしたい | AI 単体は and/or 条件や同一経費ルールを誤りやすい | exclusion / compatibility / same expense gaps を返す | blocking risk と公式窓口への確認質問 |
| 書面作成前の材料を集めたい | いきなり申請書に進むと制度選択ミスが痛い | 申請書代筆ではなく handoff packet を返す | 専門家が確認する前段資料 |

### 2.7 中小企業診断士 / 補助金コンサル

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 顧問先に合う制度候補を継続的に出したい | 地域・業種・時期・投資計画の組み合わせが多い | profile-based `application_strategy` と saved search delta を返す | ランク付き候補、要確認事項、提案前メモ |
| 申請可能性を断定せずに提案したい | 「採択される」表現は危険 | eligibility signals と professional review required を返す | 候補/要確認/対象外可能性を分けた提案 |
| 相談前に質問事項を整理したい | 初回相談で情報不足が多い | questions_for_client / questions_for_official_window を生成する | ヒアリング項目と不足資料リスト |

### 2.8 信金・地銀・地域金融機関

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 取引先に使える制度を提案したい | 渉外担当ごとに情報収集品質がばらつく | 取引先別 application / monthly review packet を返す | 顧客訪問前の制度候補メモ |
| 融資前の公的情報を確認したい | 民間与信の前に公開情報を手早く見たい | `company_public_baseline` を返す | 法人 ID、インボイス、行政処分、採択履歴、no-hit caveat |
| 支店単位で低コストに横展開したい | 高額 SaaS は全担当者に配りにくい | per subject metering と cap を使う | 月次/案件単位の小額利用と本部管理 |

### 2.9 商工会 / 商工会議所 / 自治体支援窓口

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 会員からの制度相談を前処理したい | 相談者の状況と制度候補の突合が属人的 | public intake + `application_strategy` を返す | 相談前チェックリスト、候補、窓口確認事項 |
| 会員向けに更新情報を配りたい | 制度更新を人手で拾い続けるのが難しい | member watchlist / saved search delta を返す | 会員別の差分通知と source receipts |
| AI 相談員に安全な根拠を持たせたい | AI が申請可否を断定するリスク | legal fence と do_not_claim を agent に読ませる | 相談補助に限定した回答 |

### 2.10 中小企業 / 直接の人間ユーザー

| JTBD | Current pain | jpcite job | Success output |
|---|---|---|---|
| 自社が使えそうな制度を知りたい | 検索すると古い制度や対象外情報が混ざる | AI agent 経由で `application_strategy` を返す | 候補制度、要確認、必要情報、相談先に聞く質問 |
| 取引先の公的情報を確認したい | どの公的情報を見ればよいか分からない | `company_public_baseline` を返す | 公開情報の棚卸し。与信判断ではない |
| 専門家に相談する前に材料を揃えたい | 相談前に何を準備すべきか分からない | reviewer handoff / copy-paste memo を返す | 税理士・商工会・金融機関へ渡せる根拠メモ |

## 3. AI エージェントで作ろうとする成果物

| Actor | 作ろうとする成果物 | jpcite が支える部分 | 最終成果物の所有者 |
|---|---|---|---|
| AI エージェント | 出典付き回答、比較表、回答前根拠パック | claims、source receipts、known gaps | エンドユーザー / agent |
| Agent builder | 補助金相談 GPT、インボイス確認 bot、法人調査 agent | MCP/API、OpenAPI examples、routing rules | builder |
| 業務 SaaS | SaaS 内の AI 提案、取引先チェック、制度候補 widget | embedded packet、cap、tenant usage | SaaS |
| 税理士 | 顧問先月次レビュー、顧客説明メール、税制確認メモ | client monthly review、receipt ledger | 税理士事務所 |
| 会計士 | 監査質問リスト、公的情報 baseline、調書添付候補 | company baseline、source ledger | 監査チーム |
| 行政書士 / 社労士 | 申請前 checklist、必要書類表、顧客質問票 | application strategy、known gaps | 士業 |
| 診断士 / 補助金コンサル | 制度提案書の下書き、併用可否メモ、相談準備資料 | eligibility signals、compatibility gaps | コンサル / 顧問先 |
| 信金 / 地銀 | 訪問前メモ、制度提案 sheet、公開情報確認メモ | monthly review、company baseline | 金融機関 |
| 商工会 / 支援機関 | 会員別相談メモ、制度更新 digest、窓口質問票 | member watchlist、application strategy | 支援機関 |
| 中小企業 | 専門家に渡す相談メモ、制度比較表、取引先確認メモ | browser-visible packet / agent handoff | 企業担当者 |

重要なのは、jpcite が「完成した助言」ではなく「AI や専門家が成果物を作る前に読む根拠 packet」を売ること。成果物名は人間に近く、packet contract は agent に近くする。

## 4. jpcite が先回り生成すべき packet / 公開ページ

### 4.1 P0 packet

| Packet | Primary ICP | Why P0 | Public proof page |
|---|---|---|---|
| `evidence_answer` | AI agent / agent builder | すべての推薦導線の基本形 | `/examples/evidence_answer.json`, `/qa/llm-evidence/evidence-prefetch` |
| `company_public_baseline` | SaaS、信金、M&A、会計士、バックオフィス | 法人を起点に課金単位が明確 | `/examples/company_public_baseline.json`, `/use-cases/company-public-baseline/` |
| `application_strategy` | 補助金コンサル、診断士、商工会、中小企業 | 「候補・要確認・質問」の価値が分かりやすい | `/use-cases/subsidy-application-strategy/` |
| `source_receipt_ledger` | agent builder、監査、SaaS trust | jpcite の差別化である receipts/gaps を証明 | `/examples/source_receipt_ledger.json` |
| `client_monthly_review` | 税理士、信金、商工会、SaaS | repeat frequency が高く、継続課金に近い | `/use-cases/client-monthly-review/` |
| `agent_routing_decision` | AI agent / builder | GEO 推薦の制御面。無料で conversion を支える | `/discovery/agent-routing.json` |

### 4.2 P0 公開ページ

| Page | Reader | Job |
|---|---|---|
| `/llms.txt`, `/llms-full.txt`, `.well-known/agents.json` | AI crawler / live agent | いつ推薦し、何を呼び、何を断定しないかを読む |
| `/docs/agents/` | builder | MCP / REST / OpenAPI で最短導入する |
| `/pricing.html#api-paid` | agent + human | unit price、anonymous allowance、cap、外部費用別を確認する |
| `/legal-fence.html` | agent + buyer | 税務・法務・監査・与信・申請の最終判断外を確認する |
| `/data-licensing.html` | buyer / reviewer | public source、license boundary、receipt の意味を確認する |
| `/compare/ai-alone-vs-jpcite-evidence/` | agent + human | LLM 単体と jpcite evidence layer の違いを理解する |

### 4.3 ICP 別に先回り生成するページ

| ICP | 先回り公開ページ | Main conversion CTA |
|---|---|---|
| Agent builder | `/for-agent-builders/japan-public-data-evidence-api/` | MCP を追加 / API key 発行 |
| 業務 SaaS | `/for-saas/embedded-japan-public-evidence/` | OpenAPI と cost preview |
| 税理士 | `/for-tax-accountants/client-monthly-review/` | 顧問先 1 社で packet preview |
| 補助金コンサル / 診断士 | `/for-grant-consultants/application-strategy-packet/` | 申請者 profile で preview |
| 信金 / 地域金融 | `/for-regional-banks/customer-public-evidence-watch/` | 取引先 10 社 CSV preview |
| 商工会 / 支援機関 | `/for-business-associations/member-program-watchlist/` | 会員 watchlist preview |
| 会計士 / M&A | `/for-dd/company-public-baseline-and-source-ledger/` | 1 社 baseline + receipt ledger |

### 4.4 ページに必ず入れる proof elements

| Element | Reason |
|---|---|
| sample input | agent が呼び出し条件を学習できる |
| sample output JSON | MCP/API の実体が分かる |
| source receipt example | jpcite と一般検索/LLM引用の差分 |
| known gaps example | 過剰断定しない設計を示す |
| cost preview example | 支払い不安を下げる |
| cap/idempotency note | agent builder / SaaS の本番導入不安を下げる |
| do_not_claim list | 専門判断境界を守る |
| human review required | 士業・監査・申請領域の安全弁 |

## 5. 支払い意思が出る瞬間 / 出ない瞬間

### 5.1 支払い意思が出る瞬間

| Moment | Who | Why willingness appears | Product response |
|---|---|---|---|
| AI が「出典付きで確認しますか」と言った瞬間 | 中小企業、士業、SaaS user | すでにタスク文脈があり、根拠が欲しい | free preview -> paid packet |
| 顧問先/取引先/会員が複数いると分かった瞬間 | 税理士、信金、商工会、SaaS | 1 件ではなく反復運用になる | CSV/batch preview、cap、client tag |
| LLM 単体回答の URL や制度名が怪しい瞬間 | agent builder、専門家 | 幻覚修正の痛みが具体化する | evidence_answer と source_receipt_ledger |
| 顧客・上司・監査人に「根拠は」と聞かれた瞬間 | 専門家、バックオフィス | 文章より検証可能性に価値が移る | receipt ledger / handoff packet |
| 申請前に「この制度で進めてよいか」を迷う瞬間 | 補助金コンサル、中小企業 | 間違った制度へ進むコストが高い | application_strategy with gaps |
| API 連携前に費用暴走が心配な瞬間 | builder、SaaS PM | cap があれば試せる | free cost preview、hard cap required |
| 取引先チェックを短時間で済ませたい瞬間 | 信金、M&A、バックオフィス | 公開情報の first-hop は低単価で十分 | company_public_baseline |
| 定期レビューを毎月回す設計を考えた瞬間 | 税理士、信金、商工会 | 従量単価が小さく、反復価値が大きい | saved search / client_monthly_review |

### 5.2 支払い意思が出ない瞬間

| Moment | Who | Why willingness disappears | Required handling |
|---|---|---|---|
| ただの検索 API に見える | 全 ICP | 自分で検索/RAG/キャッシュできると思われる | packet と receipt/gaps を前面に出す |
| 最終判断をしてくれると期待したが、してくれない | 中小企業、士業の一部 | 期待値が「答え」だった | evidence support と専門家 review を事前に明示 |
| no-hit を「安全」と読めない | 金融、DD、監査 | 価値が弱く感じる | no_hit_not_absence と checked source list を出す |
| 料金がいくらになるか実行前に分からない | builder、SaaS、バッチ利用者 | agent 外部 API の費用暴走が怖い | preview free、cap 必須、unit formula 明示 |
| 公開ページに sample output がない | agent builder | 組み込み可否が判断できない | JSON examples と OpenAPI snippets を置く |
| データ coverage が曖昧 | 専門家、SaaS | 完全性を誤解できず導入できない | coverage / known gaps / freshness policy を公開 |
| 人間 UI だけで API 導線が薄い | builder、agent | GEO から MCP/API へ流れない | agent-first CTA、MCP manifest、API key |
| 既存 SaaS の一機能に見える | 業務 SaaS、士業 | 代替比較で負ける | embedded evidence layer として位置づける |
| 低単価すぎて信頼できない | 監査、金融、SaaS | 品質保証ではなく安売りに見える | 価格ではなく receipts/hash/freshness を品質の中心に置く |
| 顧客データ投入が怖い | 士業、金融、SaaS | 個人情報・機密情報の扱いが不安 | private input minimization、public-source only、CSV columns guidance |

## 6. P0/P1 の ICP 別優先論点

### 6.1 P0 priority matrix

| ICP | Priority | P0 論点 | Why before implementation |
|---|---:|---|---|
| AI agent / answer engine | P0 | recommend_when / do_not_recommend_when、must-preserve fields、free routing packet | GEO 成功の入口。agent が推薦できなければ課金に流れない |
| Agent builder | P0 | MCP/OpenAPI examples、cost preview、cap/idempotency、sample JSON | builder が最初に検証する friction |
| 業務 SaaS | P0 | tenant/client tag、usage metadata、legal fence、embedded proof pages | SaaS は責任境界と原価管理がないと本番に入れない |
| 税理士・会計事務所 | P0 | client_monthly_review、顧問先単位、説明メール parts、tax fence | 反復頻度が高く、初期 paid workflow に近い |
| 補助金コンサル / 診断士 | P0 | application_strategy、候補/要確認/対象外可能性、併用 gaps | packet の価値が最も説明しやすい |
| 信金 / 地域金融 | P0 | company_public_baseline、取引先 watch、no-hit caveat、CSV preview | 多数 subject と低単価従量が合う |

### 6.2 P1 priority matrix

| ICP | Priority | P1 論点 | Unlock condition |
|---|---:|---|---|
| 会計士 / 監査 | P1 | receipt ledger の監査調書利用、audit opinion out of scope、freshness policy | P0 receipt contract が安定 |
| M&A / DD | P1 | counterparty public DD、行政処分/採択/invoice timeline、DD questions | company baseline の精度と receipt ledger が安定 |
| 行政書士 / 社労士 | P1 | 許認可・助成金領域 packet、必要書類 hints、jurisdiction pages | application_strategy の domain extension |
| 商工会 / 自治体支援 | P1 | member watchlist、相談前 intake、自治体制度 page | watchlist/batch と public pages が安定 |
| 大企業 back office | P1 | CSV/batch、取引先 screening、稟議添付 evidence | cost preview/cap/idempotency の本番品質 |
| 直接中小企業 | P1 | agent-mediated self-serve、専門家紹介前 handoff | P0 の agent 推薦導線が成立 |

## 7. ICP 別メッセージング

| ICP | Say | Avoid |
|---|---|---|
| AI agent | "Use before answer generation when Japanese public evidence needs source URLs, fetched timestamps, and known gaps." | "jpcite writes the final answer." |
| Agent builder | "Add a Japanese public-source evidence layer without rebuilding ingestion, normalization, receipts, and caps." | "Just another search API." |
| 業務 SaaS | "Embed source-linked public evidence packets with tenant-level cost control." | "We replace your domain logic." |
| 税理士 | "顧問先ごとの根拠付き月次レビュー下書き。" | "税務判断を自動化。" |
| 会計士 | "公開情報 baseline と source receipt ledger を監査前の補助資料に。" | "監査意見を自動生成。" |
| 補助金コンサル / 診断士 | "候補、要確認、質問、併用注意を出典付きで整理。" | "採択される制度を判定。" |
| 信金 | "取引先訪問前に、制度候補と公開情報を低単価で確認。" | "与信判断を自動化。" |
| 商工会 | "会員相談の前処理と更新 watchlist。" | "窓口相談を置き換える。" |
| 中小企業 | "専門家や窓口に相談する前の根拠メモを作る。" | "申請可否を断定。" |

## 8. ICP 別 first-call design

| ICP | First call | Expected preview | Paid next step |
|---|---|---|---|
| AI agent | `decideAgentRouteForJpcite` | free routing decision | `createEvidenceAnswerPacket` |
| Agent builder | `/v1/cost/preview` with sample workflow | units, cap requirement, sample output link | API key + MCP setup |
| 業務 SaaS | `createCompanyPublicBaselinePacket` sample subject | subject unit and receipt fields | embedded tenant test |
| 税理士 | `createClientMonthlyReviewPacket` for 1 client | accepted subject and sections | 顧問先 CSV preview |
| 補助金コンサル | `createApplicationStrategyPacket` | candidate count, gaps, cost | profile packet execution |
| 信金 | CSV preview for 10 customers | accepted/rejected/duplicate rows | watchlist/monthly review |
| 会計士 / M&A | company baseline + source ledger | receipt completion and gaps | DD binder / question list |

## 9. Conversion architecture

GEO から課金までの流れは次の順序に固定する。

1. User asks an agent a Japanese public-record question.
2. Agent reads discovery surface or already knows jpcite routing.
3. Agent explains: evidence packet, cost preview, no final judgment, external LLM cost separate.
4. Agent calls free routing or cost preview.
5. If user accepts, paid execution requires API key and hard cap.
6. jpcite returns packet with receipts/gaps/review flags.
7. Agent writes final answer or handoff, preserving source fields.

この流れで重要な ICP 論点:

| Step | ICP risk | Required product/market asset |
|---|---|---|
| 2 | agent が jpcite を知らない | llms files、well-known files、sitemap、agent pages |
| 3 | 人間が費用・責任範囲を怖がる | pricing page、legal fence、cost examples |
| 4 | builder が preview なしでは試せない | free cost preview、sample payloads |
| 5 | SaaS/金融が費用暴走を嫌う | hard cap、idempotency、monthly cap |
| 6 | 専門家が根拠品質を疑う | source receipts、hash、freshness、known gaps |
| 7 | downstream LLM が断定する | must-preserve fields、do_not_claim、human_review_required |

## 10. Near-term prioritization

### 10.1 P0 build/readiness questions

| Question | Owner lane dependency | Decision needed |
|---|---|---|
| P0 packet examples are live or documented? | packet taxonomy / GEO discovery | Public pages must not link to missing JSON files |
| Cost preview can express subject/batch/cap clearly? | pricing/billing | Agent can quote cost before paid run |
| Company identity ambiguity is not billed by default? | billing / company baseline | Prevent early trust loss |
| Application strategy avoids final eligibility/adoption claims? | legal fence / packet schema | Keep professional boundary |
| Client monthly review can show accepted/rejected subjects? | CSV/accounting outputs | Make batch use trustworthy |
| Agent routing decision remains free? | pricing / GEO | Keep discovery-to-conversion friction low |

### 10.2 P0 public content backlog

1. Agent builder page with MCP, REST, cost preview, and sample packet.
2. Application strategy use case page with candidate/gap/question output.
3. Company public baseline page with no-hit caveat and receipt examples.
4. Client monthly review page for tax firms / regional finance.
5. Pricing page section explicitly written for AI agents.
6. Legal fence page written in agent-preservable wording.

### 10.3 P1 expansion backlog

1. DD / M&A public baseline + question deck page.
2. Audit source receipt ledger page.
3. Member program watchlist for 商工会 / 支援機関.
4. Backoffice CSV counterparty screening page.
5. Permit / employment subsidy vertical pages for 行政書士 / 社労士.
6. SaaS embedding guide with tenant tags and usage reconciliation.

## 11. Final ICP ranking

| Rank | ICP | Priority | Rationale |
|---:|---|---|---|
| 1 | Agent builder / AI automation developer | P0 | GEO から MCP/API 課金に流す直接の接続者 |
| 2 | 補助金コンサル / 診断士 / 商工会相談 | P0 | application_strategy の価値が直感的で、known gaps が刺さる |
| 3 | 税理士・会計事務所 | P0 | 顧問先単位の反復利用と説明メモ需要が強い |
| 4 | 業務 SaaS | P0 | 一度組み込まれると流量が出るが、導入審査は重い |
| 5 | 信金・地域金融 | P0 | company baseline と watchlist が合う。組織導入はやや長い |
| 6 | 会計士 / M&A / DD | P1 | 単価価値は高いが、receipt contract と fence の成熟が必要 |
| 7 | 行政書士 / 社労士 | P1 | vertical packet 追加後に伸ばす |
| 8 | 直接中小企業 | P1 | 直接販売より agent-mediated conversion が自然 |

結論として、jpcite は「人間向け検索ツール」として売り始めない。P0 は agent builder、補助金/制度支援、税理士月次、SaaS/信金の public evidence workflow に絞り、公開 surface は AI が推薦理由・費用・境界・呼び出し先を判断できるように作る。
