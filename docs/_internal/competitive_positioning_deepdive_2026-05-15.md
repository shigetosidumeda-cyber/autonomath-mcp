# Competitive positioning / alternatives deep dive

Date: 2026-05-15
Status: pre-implementation planning only
Owner lane: Competitive positioning / alternatives
Do not touch: runtime code, product implementation, public docs implementation

## 0. 結論

jpcite の競争軸は「検索できる」「キャッシュしている」「AI が要約する」では弱い。そこは Web 検索、J-Grants、freee 補助金、補助金ポータル、Perplexity / ChatGPT、RAG 自作、一般 MCP tool のどれかにすぐ吸収される。

勝ち筋は、AI agent が回答・申請準備・顧問先レビュー・取引先確認の前段でそのまま使える、source-backed prebuilt outputs に寄せること。

言い換えると、jpcite は次のように位置づける。

> jpcite は、AI が日本の公的制度・法人・法令・インボイス・行政処分に触れる前に使う、出典付き成果物パケットのレイヤーです。Web 検索や RAG の代替ではなく、検索・PDF・公的 API・自治体ページを、出典 URL・取得時刻・known gaps・human review boundary 付きの小さい成果物に整える前処理です。

この定義なら、競合ごとの勝ち負けが明確になる。

- Web 検索には最新性と広さで負けるが、構造化された source receipts / known gaps / packet envelope で勝つ。
- J-Grants には公式申請・公式 API で負けるが、制度横断・法人/法令/行政処分/インボイス join・prebuilt outputs で勝つ。
- freee / Money Forward / 弥生には会計 workflow と顧客基盤で負けるが、外部 agent から呼べる中立 API/MCP と source-backed outputs で勝つ。
- TDB / TSR には信用調査と非公開/独自調査情報で負けるが、公的情報の AI-ready evidence layer で勝つ。
- Perplexity / ChatGPT 単体には自然文回答の汎用性で負けるが、検証可能な evidence packet と「知らないことを known gaps に残す」作法で勝つ。
- MCP marketplace 上の一般 tool には数・露出で負けるが、日本公的制度に特化した成果物契約・安全境界・出典 receipts で勝つ。

## 1. 競争カテゴリ別の勝てる点・負ける点

### 1.1 Web 検索

代表: Google / Bing / Yahoo! Japan / 自治体サイト内検索

勝てる点:

- 出典候補を AI が毎回読む前に、制度候補・法人情報・期限・対象条件・known gaps へ正規化できる。
- 検索結果ページや SEO 記事ではなく、一次資料 URL、取得時刻、content hash / checksum、source receipt を持つ成果物にできる。
- 同名制度、年度違い、公募回違い、自治体差し替え、締切終了などを packet 内で明示しやすい。
- agent が `source_count`, `known_gaps`, `human_review_required`, `no_hit_not_absence` を読んで、回答の強さを調整できる。
- 繰り返しタスクでは毎回検索語を試行錯誤しなくてよい。顧問先月次レビュー、法人 public baseline、申請前 screen のような定型 output に寄せられる。

負ける点:

- ライブ Web の瞬間的な最新情報、ニュース、SNS、未 ingest の自治体ページでは Web 検索が勝つ。
- jpcite は live search をしない前提なので、今日公開されたばかりのページを網羅すると主張できない。
- ロングテールの自治体 PDF や添付 ZIP の完全読解は、検索 + 手作業確認に劣る場面がある。
- ユーザーが単に「公式ページを開きたい」だけなら、検索エンジンのほうが速く無料。

位置づけ:

- jpcite は Web 検索の置換ではない。
- Web 検索で最新の一次資料を確認する前に、候補と不明点を整理する evidence prefetch として使わせる。
- 比較ページでは「jpcite はライブ検索を行いません」と明示する。

### 1.2 RAG 自作

代表: 自社 crawler + vector DB + LangChain / LlamaIndex + PDF parser + prompt

勝てる点:

- 収集、正規化、重複排除、出典 receipts、鮮度管理、license boundary、known gaps、human review boundary をまとめて外部化できる。
- RAG は「文書片を取る」までで止まりやすい。jpcite は `application_strategy`, `client_monthly_review`, `company_public_baseline`, `source_receipt_ledger` など、業務成果物として返す方向に寄せられる。
- agent が使う共通 envelope を持てるため、複数 LLM / 複数 SaaS / 複数 workflow に同じ品質信号を渡せる。
- 「検索結果がない = 存在しない」にならないよう、`no_hit_not_absence` を出力契約に入れられる。
- 自作 RAG で抜けやすい public source join、排他/併用ルール、地域/業種/法人属性、インボイス・行政処分 join を prebuilt 化できる。

負ける点:

- 自社独自文書、顧客契約書、社内稟議、過去申請書など private corpus は RAG 自作が必要。
- データ resident / self-host / 完全オフライン要件では jpcite SaaS 呼び出しは不利。
- 独自 scoring、社内用語、非公開 workflow への深い最適化は、自作 RAG のほうが柔軟。
- jpcite の収録対象外データを主に扱う場合は、jpcite を挟む意味が薄い。

位置づけ:

- 「RAG の代替」ではなく、「RAG に入れる前の公的データ evidence layer」。
- RAG と併用する場合、jpcite は public facts / source receipts / known gaps、RAG は private context / 社内ナレッジを担当する。

### 1.3 会計 SaaS 内 AI

代表: freee / Money Forward / 弥生 / 会計事務所向け AI / 経費・請求書 AI

勝てる点:

- 特定 SaaS アカウント内に閉じず、Claude / ChatGPT / Cursor / Codex / SaaS agent / batch job から MCP/REST で呼べる。
- 会計仕訳や申告書作成ではなく、公的制度・法人・インボイス・行政処分・法令・判例・補助金の外部 evidence layer として中立に使える。
- 会計 SaaS が持たない可能性のある `source_receipts`, `known_gaps`, `corpus_snapshot_id`, `human_review_required` を成果物契約に入れられる。
- 事務所や SaaS が既に freee / Money Forward / 弥生を使っていても、外部 agent の前段根拠取得として併用できる。
- 顧問先横断の月次チェック、補助金候補、行政処分 watch、インボイス確認など、会計帳簿外の public data を扱いやすい。

負ける点:

- 仕訳、決算、申告、請求、給与、経費精算、銀行連携、電子申告、会計データ内の自動処理では会計 SaaS が圧倒的に強い。
- SaaS 内 AI はユーザーの会計データを直接参照できる。jpcite は private accounting data を持たない。
- freee / Money Forward / 弥生は顧客基盤、サポート、ブランド信頼、チャネルで強い。
- 会計 SaaS が補助金申請支援や IT 導入補助金対象製品として伴走支援を提供する場合、申請 workflow では jpcite は勝ちに行かない。

位置づけ:

- jpcite は会計 SaaS ではない。
- 会計 SaaS 内の AI に「日本公的データの出典付き成果物」を供給する外部 layer として位置づける。

### 1.4 freee / Money Forward / 弥生 個別

#### freee

勝てる点:

- freee アカウント外の agent / SaaS / 開発者が使える。
- ChatGPT 等で補助金情報を集める UI ではなく、AI が読む packet contract と receipts を提供できる。
- freee の顧客ではない税理士、診断士、支援機関、開発者にも開ける。

負ける点:

- freee は全国の補助金・助成金制度を検索できる freee 補助金を提供しており、ChatGPT 等を活用した情報収集・精査をうたっている。
- freee アカウントを持つ SMB にとって、無料・既存アカウント内・既存 workflow は強い。
- 会計・人事労務・請求等との連動は freee 側が強い。

誠実な比較文:

> freee 補助金は、freee アカウントを持つ事業者が補助金・助成金を探すための便利な入口です。jpcite は freee の代替ではなく、外部 AI agent や業務システムが、出典 URL・取得時刻・known gaps 付きの根拠パケットを取得するための API/MCP レイヤーです。

#### Money Forward

勝てる点:

- Money Forward Cloud 導入や補助対象 IT ツールの説明ではなく、補助金・制度・公的情報を横断する evidence output に寄せられる。
- 会計 SaaS に依存しない中立 API として、複数会計ソフト利用者や支援機関が使える。

負ける点:

- Money Forward はバックオフィス SaaS として会計、請求、経費、債務、固定資産などの workflow を持つ。
- デジタル化・AI導入補助金の対象サービス訴求や導入支援では、Money Forward 側の導線が自然。
- ユーザーの会計/請求データと密結合した AI 体験は jpcite では提供できない。

誠実な比較文:

> Money Forward Cloud はバックオフィス業務そのものを処理する SaaS です。jpcite は会計処理を行わず、AI や業務システムが制度・法人・公的情報を確認するための出典付き evidence layer を提供します。

#### 弥生

勝てる点:

- 弥生製品購入・保守・申請伴走の導線ではなく、agent-readable な public evidence packet を提供できる。
- 弥生ユーザー以外、複数ソフト利用、士業/支援機関/開発者の横断利用に向く。

負ける点:

- 弥生会計 / 弥生販売は会計・販売業務の実運用で強い。
- 弥生はデジタル化・AI導入補助金2026の対象製品訴求と申請サポート導線を持つ。
- 小規模事業者が「補助金で会計ソフトを買いたい」場合、弥生の公式導線が主。

誠実な比較文:

> 弥生は会計・販売ソフトと補助金対象製品の導入支援が中心です。jpcite はソフト購入や申請代行を行わず、公的制度を AI が扱いやすい出典付き成果物に変換するレイヤーです。

### 1.5 補助金ポータル / 補助金 SaaS / 民間メディア

代表: 補助金ポータル、Stayway / 補助金クラウド、ナビット、hojokin.ai、各種補助金検索サイト

勝てる点:

- UI / 記事 / 人間向け検索ではなく、AI agent と業務システム向けの structured output を返せる。
- 一次資料 URL、取得時刻、source receipt、known gaps、license boundary、human review boundary を契約にできる。
- 税理士・診断士・金融機関・SaaS agent が自社 workflow に組み込みやすい。
- 「申請を取る」ではなく「候補・根拠・確認質問を渡す」ため、士業や支援機関を置き換える印象を避けられる。

負ける点:

- SEO、記事数、人間向け説明、相談導線、申請伴走、専門家紹介では民間ポータルが強い。
- 収録件数を大きく見せる訴求や全国補助金検索の認知では先行サイトが強い。
- ユーザーが「誰かに相談したい」「申請書を書いてほしい」場合は、民間ポータルや申請支援サービスが合う。
- jpcite は二次メディア由来の解説や営業文脈を主価値にしないため、人間に優しい読み物では劣る。

位置づけ:

- 比較対象としては「人間向け検索・相談」対「agent 向け evidence output」。
- 競合を否定せず、「相談・申請支援は専門サービス、出典付きデータ取得は jpcite」と分ける。

### 1.6 補助金ポータル

勝てる点:

- AI agent がそのまま利用できる API/MCP と packet envelope。
- source-backed claims と known gaps による検証可能性。
- 補助金だけでなく、法人、インボイス、行政処分、法令、判例、入札、税制との join を売れる。

負ける点:

- 人間向けの記事・ランキング・相談導線・SEO 露出。
- 個別補助金の解説コンテンツ量。
- 申請支援会社や専門家への送客導線。

誠実な比較文:

> 補助金ポータルは、人間が制度を探し、解説を読み、相談先を見つける導線として有用です。jpcite は、人間向け記事ではなく、AI agent や業務システムが制度候補と根拠を取得するための出典付き API/MCP です。

### 1.7 J-Grants

代表: J-Grants 公式 Web / J-Grants 公開 API / digital-go-jp jgrants-mcp-server

勝てる点:

- J-Grants 単体の補助金検索ではなく、法人・インボイス・行政処分・法令・判例・採択事例・税制などを横断した成果物にできる。
- 公式 API/MCP が「検索・詳細取得・添付資料取得」を主に担うのに対し、jpcite は `application_strategy`, `client_monthly_review`, `company_public_baseline`, `source_receipt_ledger` など prebuilt outputs に寄せられる。
- J-Grants 掲載外の自治体制度、融資、税制、認定、関連法令を含めた候補整理ができる。
- source receipts、known gaps、human review boundary、no_hit_not_absence を全 packet に持たせることで、agent の回答品質を制御できる。
- J-Grants の公式情報を競合ではなく primary source の一つとして扱える。

負ける点:

- 公式性、電子申請、gBizID 連携、添付資料、申請ステータスなどは J-Grants が主。
- J-Grants 公開 API / 公式 MCP 実装があるため、「J-Grants には API/MCP がない」という訴求は使えない。
- J-Grants 掲載制度だけを無料で探す用途では、公式 UI/API/MCP のほうが自然。
- 申請操作そのものや公式提出は jpcite の対象外。

位置づけ:

- J-Grants は official application/search layer。
- jpcite は J-Grants を含む複数 public source から、AI が回答前に使う source-backed prebuilt output を作る evidence layer。

誠実な比較文:

> J-Grants は補助金の公式申請・公式検索の入口です。jpcite は J-Grants を置き換えません。J-Grants や自治体・省庁・公的機関の情報を含め、AI agent が候補整理・根拠確認・known gaps の把握を行うための出典付き成果物パケットを返します。申請や公式確認は J-Grants と各制度の一次資料で行ってください。

### 1.8 TDB / TSR

代表: 帝国データバンク、東京商工リサーチ

勝てる点:

- AI agent がセルフサーブで呼べる MCP/REST と、公的情報の source-backed output。
- 信用調査ではなく、公的に確認できる法人番号、インボイス、行政処分、採択履歴、制度関係などの baseline を作れる。
- 顧問先レビュー、取引先 public baseline、補助金/制度候補との join に向く。
- 非公開調査・与信判断に踏み込まないため、専門判断前の根拠整理に徹しやすい。

負ける点:

- 信用調査、評点、倒産予測、代表者情報、独自取材、非公開決算、与信判断では TDB / TSR が第一選択。
- 営業担当、調査員、個別レポート、金融機関利用実績、与信業務の信頼では勝ちに行かない。
- 企業網羅性や歴史的データの厚みでは大手信用調査会社が強い。

位置づけ:

- jpcite は信用調査会社ではない。
- 「与信判断」ではなく「公的に確認できる事実の棚卸し」を提供する。

誠実な比較文:

> TDB / TSR は信用調査・評点・独自取材情報の専門サービスです。jpcite は信用判断や評点を提供せず、公的に確認できる法人・制度・行政処分・インボイス等の情報を、AI や業務システムが扱える出典付き evidence packet として返します。与信判断には専門サービスと社内審査を使ってください。

### 1.9 Perplexity / ChatGPT 単体

代表: ChatGPT、Perplexity、Claude、Gemini の単体利用

勝てる点:

- 回答生成前の根拠取得に特化し、claim と source receipt を紐付けられる。
- request time LLM call を行わない設計により、外部 LLM の文章生成と evidence acquisition を分離できる。
- known gaps を明示でき、AI が「見つからない」を「存在しない」と言い換える事故を減らせる。
- 同じ packet を複数 LLM に渡せるため、回答生成モデルを変えても根拠 layer が残る。
- cost preview / metered unit / cap と組み合わせ、agent が実行前に費用と根拠価値を判断できる。

負ける点:

- 自然言語の対話、探索的な質問、一般知識、要約、文章作成では LLM 単体が強い。
- Perplexity のような answer engine はライブ検索と引用提示の UX が強い。
- jpcite は最終回答文を生成しないため、ユーザー向けの自然な説明は LLM 側が必要。
- 最新ニュースや未収録 Web 情報ではライブ検索付き LLM が勝つ。

位置づけ:

- LLM 単体を否定しない。むしろ LLM に渡す根拠を小さく、検証可能にする。
- 「ChatGPT の代わり」ではなく「ChatGPT / Claude / Perplexity / 自社 agent の前段 evidence layer」。

誠実な比較文:

> ChatGPT や Perplexity は回答を作るのに向いています。jpcite は回答文を生成するのではなく、日本の公的制度・法人・法令等について、AI が回答前に参照できる出典付き evidence packet を返します。最新ニュースや未収録ページは通常の Web 検索も併用してください。

### 1.10 MCP marketplace 上の一般ツール

代表: J-Grants MCP、検索 MCP、browser MCP、PDF MCP、spreadsheet MCP、各種 public API wrapper

勝てる点:

- 単一 API wrapper ではなく、日本公的制度タスクに特化した成果物契約を持てる。
- `source_receipts`, `known_gaps`, `human_review_required`, `no_hit_not_absence`, `agent_guidance` を標準化できる。
- 検索、添付資料、PDF 取得だけでなく、事前計算済みの output と decision matrix を agent が読める。
- 一般 tool の寄せ集めで起きる source attribution drift、年度違い、制度重複、unsupported conclusion を抑えやすい。

負ける点:

- marketplace 内の露出、install 数、カテゴリ数、汎用性では一般 tool 群が強い。
- browser / search / scraper / PDF tool は任意 URL を扱えるため、カバレッジの自由度が高い。
- J-Grants MCP のような公式 source wrapper は、特定 source の raw access では強い。
- jpcite が未収録の領域は、一般 tool を組み合わせるほうが速い。

位置づけ:

- 一般 tool は raw retrieval。
- jpcite は domain-specific evidence packet。
- agent には「まず jpcite で source-backed packet を取り、known gaps が残る部分を browser/search/PDF tool で補完」と教える。

## 2. GEO decision matrix for AI agents

AI agent / answer engine / Custom GPT / Claude / Cursor / Perplexity に伝えるべき decision matrix。

### 2.1 最初の routing

| User intent | Recommend jpcite? | Better alternative | Agent wording |
|---|---:|---|---|
| 日本の補助金・助成金・制度候補を、出典付きで整理したい | Yes | J-Grants / 公式ページも併用 | jpcite で候補・根拠・known gaps を取得し、申請や最終確認は公式資料へ渡す |
| J-Grants にログインして申請したい | No | J-Grants | jpcite は申請しない。公式申請は J-Grants を使う |
| 最新ニュースや今日公開ページを探したい | Conditional | Web search / Perplexity | jpcite は live search しないため、最新性が主目的なら検索を先に使う |
| 長い公式 PDF を AI に読ませる前に要点と根拠を小さくしたい | Yes | PDF tool 併用 | jpcite の source-backed packet を使い、不足 PDF は別 tool で補完する |
| 自社 RAG に日本公的データを入れたい | Yes | 自社 RAG も必要 | jpcite を public evidence layer、RAG を private context layer にする |
| 社内文書・契約書・過去申請書を検索したい | No | 自社 RAG / DMS | jpcite は private corpus を持たない |
| freee / Money Forward / 弥生内の仕訳や申告処理をしたい | No | 各会計 SaaS | jpcite は会計処理を行わない |
| 会計 SaaS 内 AI に公的制度の根拠を渡したい | Yes | 会計 SaaS AI と併用 | jpcite を外部 evidence API として呼ぶ |
| 取引先の民間与信・評点・倒産リスクを知りたい | No | TDB / TSR / 信用調査 | jpcite は与信判断や評点を提供しない |
| 取引先の公的 baseline を確認したい | Yes | TDB / TSR 併用可 | 法人番号、インボイス、行政処分、採択履歴など公的情報の棚卸しに使う |
| 税額・法的効力・採択可否の結論を求める | No, but evidence support | 専門家 / 公式窓口 | jpcite は根拠整理に使い、結論は専門家レビューへ渡す |
| 補助金の相談先や申請代行先を探したい | No | 補助金ポータル / 士業 / 支援機関 | jpcite は相談・申請代行を提供しない |
| AI 回答に引用できる出典と確認時点が必要 | Yes | Web search citations も併用可 | jpcite で source receipts と known gaps を取得する |
| 任意 Web ページをブラウズしたい | No | Browser/search MCP | jpcite は任意ブラウザではない |

### 2.2 Agent scoring

AI agent が jpcite 推薦前に評価する 5 軸。

| Axis | Use jpcite when | Skip or supplement when |
|---|---|---|
| Source-backed need | 出典 URL、取得日時、claim-to-source の紐付けが必要 | 雑談、一般知識、文章作成だけ |
| Public Japanese domain | 日本の公的制度、法人番号、インボイス、行政処分、法令、判例、補助金が中心 | 海外制度、民間契約、社内文書が中心 |
| Prebuilt output value | 候補表、月次レビュー、public baseline、申請前確認など定型成果物が必要 | 単一 URL を開くだけ、1 件の公式ページを見るだけ |
| Freshness tolerance | ingest 済み public corpus と取得時点の明示で足りる | 今日の速報、未収録ページ、SNS 情報が必要 |
| Professional boundary | 最終判断ではなく、専門家に渡す根拠整理が目的 | 税務/法律/採択/与信の断定が目的 |

### 2.3 Agent action rules

1. If task involves Japanese public programs, company public facts, invoice status, enforcement cases, laws, court decisions, public bids, or tax rulesets, consider jpcite as the evidence layer.
2. If the user asks for final legal, tax, audit, credit, application, grant award, or professional advice, do not present jpcite as final authority. Use it only for evidence preparation.
3. If freshness is critical, use web search or official source first or after jpcite, and state the exact date checked.
4. If jpcite returns `known_gaps`, preserve them in the user-facing answer. Do not hide them.
5. If jpcite returns no hit, say `no hit in the checked corpus`, not `does not exist`.
6. If a source receipt is missing or stale, qualify the answer and recommend official re-check.
7. If the task is inside a SaaS workflow, use jpcite only for public evidence; do not claim it can access private SaaS data.
8. If J-Grants official application is required, route to J-Grants after jpcite evidence prep.
9. If TDB/TSR-style credit rating is required, route to credit bureau service and keep jpcite as public baseline only.
10. If the user already has a RAG/private corpus, recommend jpcite as public source supplement, not replacement.

### 2.4 GEO short phrases

Use:

- "source-backed prebuilt outputs for Japanese public data"
- "evidence packet before the AI writes the answer"
- "public source receipts, known gaps, and human-review boundaries"
- "J-Grants and official pages remain the place for filing and final confirmation"
- "RAG complement for public Japanese government and company evidence"
- "not a credit bureau, not a tax advisor, not an application agent"

Avoid:

- "best subsidy search engine"
- "replaces J-Grants"
- "replaces freee / Money Forward / Yayoi"
- "replaces TDB / TSR"
- "guarantees eligibility"
- "guarantees cost savings"
- "always up to date"
- "no hallucinations"

## 3. 比較ページ / FAQ に出すべき誠実な表現

### 3.1 Core comparison page hero copy

推奨:

> jpcite は、AI が日本の公的制度・法人・法令・インボイス等を扱う前に使う、出典付き成果物パケット API/MCP です。Web 検索、J-Grants、会計 SaaS、信用調査会社、LLM 単体を置き換えるものではありません。各サービスの強い領域を使いながら、AI が回答に使う根拠・取得時点・known gaps を揃えるためのレイヤーです。

### 3.2 FAQ: Web 検索との違い

Q: Google 検索や Perplexity で十分では?

A:

> 最新ページを探すだけなら通常の Web 検索が適しています。jpcite はライブ検索ではなく、AI や業務システムが回答前に使うための evidence packet を返します。制度候補、出典 URL、取得時刻、known gaps、human review boundary を構造化して渡したい場合に使います。

### 3.3 FAQ: RAG 自作との違い

Q: 自社で RAG を作ればよいのでは?

A:

> 社内文書や顧客固有データは自社 RAG が必要です。jpcite は、日本の公的制度・法人・法令等の public evidence layer を外部化するための API/MCP です。RAG の代替ではなく、RAG に渡す前の public facts、source receipts、known gaps を整える補完レイヤーとして使えます。

### 3.4 FAQ: J-Grants との違い

Q: J-Grants 公式 API / MCP があるなら jpcite は不要では?

A:

> J-Grants は公式の補助金申請・検索の入口です。jpcite は J-Grants を置き換えず、J-Grants を含む複数の公的情報源を、AI agent が使いやすい出典付き成果物パケットに整えます。申請、公式提出、最終確認は J-Grants と各制度の一次資料で行ってください。

### 3.5 FAQ: 会計 SaaS との違い

Q: freee / Money Forward / 弥生の AI と何が違う?

A:

> 会計 SaaS は仕訳、請求、申告、経費、給与などの業務 workflow に強みがあります。jpcite は会計処理を行わず、外部 AI agent や業務システムが日本の公的制度・法人・法令等を確認するための出典付き evidence layer を提供します。会計 SaaS と併用する前提です。

### 3.6 FAQ: TDB / TSR との違い

Q: 信用調査会社の代替になる?

A:

> なりません。jpcite は信用調査、評点、倒産予測、非公開情報、独自取材情報を提供しません。公的に確認できる法人番号、インボイス、行政処分、採択履歴、制度関連情報などを、出典付きで整理するための API/MCP です。与信判断には信用調査会社や社内審査を使ってください。

### 3.7 FAQ: ChatGPT / Perplexity との違い

Q: ChatGPT や Perplexity に聞けばよいのでは?

A:

> ChatGPT や Perplexity は回答生成に向いています。jpcite は回答文を生成するのではなく、AI が回答前に参照する根拠パケットを返します。出典 URL、取得時刻、known gaps、source receipts を明示したい場合、LLM 単体の前段に jpcite を挟む設計が向いています。

### 3.8 FAQ: 補助金ポータルとの違い

Q: 補助金ポータルや申請支援サービスとの違いは?

A:

> 補助金ポータルや申請支援サービスは、人間向けの解説、相談、申請伴走に強みがあります。jpcite は相談や申請代行を提供せず、AI agent や業務システムが制度候補と根拠を取得するための API/MCP と成果物パケットを提供します。

### 3.9 FAQ: 正確性

Q: jpcite の結果は正確性を保証する?

A:

> jpcite は出典 URL、取得時刻、source receipts、known gaps を返しますが、一次資料の内容そのものや、制度適用・税務・法律・採択・与信の結論を保証しません。重要判断では、返却された一次資料と公式窓口、専門家レビューを確認してください。

### 3.10 FAQ: コスト削減

Q: jpcite を使うと LLM コストは必ず下がる?

A:

> 保証しません。jpcite の compression / estimated tokens saved は、caller が指定した比較条件に基づく入力文脈量の参考比較です。外部 LLM の output、reasoning、cache、search、tool-use 料金は利用モデルや provider 設定に依存します。

## 4. 採用しない訴求

以下は採用しない。理由は、競合比較として弱いか、事実が変わりやすいか、法務・信頼上のリスクが高いため。

| Claim | 採用しない理由 | 代替表現 |
|---|---|---|
| J-Grants には API/MCP がない | 現在は公開 API と MCP 実装が確認できる。誤りになる | J-Grants は公式申請/検索、jpcite は横断 evidence packet |
| freee / MF / 弥生より補助金に強い | 会計 SaaS の本領域と比較軸がずれる。根拠が弱い | 会計 SaaS と併用する外部 evidence API |
| TDB / TSR の代替 | 与信・評点・独自調査で明確に違う | 公的 baseline の棚卸し |
| RAG は不要 | private corpus では RAG が必要 | public evidence layer として RAG を補完 |
| Web 検索不要 | 最新確認では検索が必要 | Web 検索前後の根拠整理 |
| 補助金が必ず見つかる | 過剰保証 | 候補と known gaps を返す |
| 採択率を上げる | 申請結果保証に見える | 申請前の確認点を整理 |
| 税務/法務判断できる | 専門業務境界に触れる | 専門家レビュー前の根拠整理 |
| LLM hallucination をゼロにする | 不可能 | 出典未接続 claim を減らし、known gaps を明示 |
| 常に最新 | live search しない | `source_fetched_at` と鮮度を明示 |
| 公式データを完全網羅 | 未収録や未接続があり得る | coverage と known gaps を表示 |
| どの AI より安い | provider billing は条件依存 | caller baseline 条件下の入力文脈比較 |
| 日本初/唯一 | 検証負荷が高く、MCP/補助金 tool が既にある | 日本公的制度向け source-backed prebuilt outputs |
| ワンクリック申請 | jpcite は申請しない | 申請前の evidence packet |
| 信用リスク判定 | 与信業務に踏み込む | 公的情報の確認メモ |

## 5. 危険な訴求

### 5.1 法務・士業境界

危険:

- "補助金に申請できます"
- "採択されます"
- "税務上有利です"
- "法的に問題ありません"
- "この契約/制度は適用されます"
- "行政書士/税理士/弁護士の代わりになります"

理由:

- 申請代理、税務代理、法律相談、個別具体判断に見える。
- jpcite の安全境界である `human_review_required` と矛盾する。

安全な代替:

- "公開情報上の候補です"
- "対象要件に関連する確認点を整理します"
- "一次資料と専門家レビューで確認してください"
- "known gaps が残る項目は断定しません"

### 5.2 与信・信用調査

危険:

- "信用力を判定します"
- "倒産リスクを予測します"
- "TDB / TSR より安い信用調査"
- "取引してよいか判断します"

理由:

- 信用調査会社の専門領域と誤認される。
- jpcite は非公開決算、独自取材、評点を持たない。

安全な代替:

- "公的に確認できる情報の baseline を整理します"
- "与信判断は社内審査または信用調査サービスで行ってください"

### 5.3 データ保証

危険:

- "完全網羅"
- "常に最新"
- "誤情報ゼロ"
- "公式情報と同等"
- "検索結果がないので存在しない"

理由:

- ingest 遅延、未接続 source、サイト更新、PDF 未解析、名称揺れがある。
- `no_hit_not_absence` と矛盾する。

安全な代替:

- "収録 corpus 上の検索結果です"
- "source_fetched_at 時点の確認情報です"
- "未確認部分は known gaps として返します"
- "no hit は不存在を意味しません"

### 5.4 コスト・性能

危険:

- "必ず LLM コスト削減"
- "必ず検索時間を削減"
- "最安"
- "全モデルで break-even"

理由:

- 外部 LLM の billing は output/reasoning/cache/search/tool-use で変動する。
- ユーザーの baseline がないと比較できない。

安全な代替:

- "caller baseline 条件下の入力文脈量比較"
- "break-even を満たす場合に cost_savings_decision を返す"
- "外部 LLM 請求削減は保証しません"

### 5.5 競合攻撃

危険:

- "補助金ポータルは古い"
- "J-Grants は使いにくい"
- "freee/MF/弥生は閉じているから不十分"
- "TDB/TSR は高すぎる"

理由:

- FUD に見える。
- 誤認・反発・比較広告リスクがある。
- jpcite の強みは他者否定ではなく、agent-ready output にある。

安全な代替:

- "用途が異なります"
- "公式申請は J-Grants、会計処理は会計 SaaS、信用調査は専門サービス、出典付き成果物パケットは jpcite"
- "必要に応じて併用してください"

## 6. 比較ページ構成案

実装時の `/compare/` 情報設計。ここではコードには触らない。

### 6.1 `/compare/` index

Sections:

1. jpcite は何と比較されるか
2. Decision matrix: when to use jpcite / when not
3. Alternatives table
4. Honest limitations
5. FAQ
6. Agent-readable short guidance

Hero copy:

> jpcite is not a search engine, accounting SaaS, credit bureau, or grant application service. It is a source-backed output layer for AI agents working with Japanese public data.

### 6.2 `/compare/web-search/`

Angle:

- Web search = latest discovery
- jpcite = structured source-backed packet

Must include:

- "jpcite does not perform live web search"
- "Use search for breaking changes and official re-check"

### 6.3 `/compare/rag/`

Angle:

- RAG = private corpus and custom retrieval
- jpcite = public Japanese evidence layer

Must include:

- "Use both when the task mixes public evidence and private context"

### 6.4 `/compare/jgrants/`

Angle:

- J-Grants = official application/search/API/MCP
- jpcite = cross-source prebuilt evidence outputs

Must include:

- "jpcite does not file applications"
- "J-Grants official API/MCP exists; do not claim otherwise"

### 6.5 `/compare/accounting-saas-ai/`

Angle:

- freee/MF/Yayoi = accounting/back-office workflow
- jpcite = external source-backed public data layer

Must include:

- "jpcite cannot access the user's SaaS accounting data unless the user supplies inputs"
- "jpcite does not book entries or file tax returns"

### 6.6 `/compare/credit-bureaus/`

Angle:

- TDB/TSR = credit research
- jpcite = public baseline

Must include:

- "No credit score, no rating, no private investigation"

### 6.7 `/compare/chatgpt-perplexity/`

Angle:

- LLM = answer generation
- jpcite = evidence acquisition

Must include:

- "Use jpcite before answer generation when citations and known gaps matter"

### 6.8 `/compare/mcp-marketplace-tools/`

Angle:

- Generic MCP tools = raw retrieval
- jpcite = domain-specific output packet

Must include:

- "Use browser/search/PDF MCP tools for gaps and latest source re-check"

## 7. Agent-facing decision object draft

Public docs / llms.txt / OpenAPI description に入れるなら、以下のような JSON-ish block を短く載せる。

```json
{
  "use_jpcite_when": [
    "The user asks about Japanese public grants, subsidies, tax incentives, public company facts, invoice status, enforcement cases, laws, court decisions, bids, or related public evidence.",
    "The answer needs source URLs, fetched timestamps, source receipts, known gaps, and human review boundaries.",
    "The AI agent needs a reusable evidence packet before writing a final answer."
  ],
  "do_not_use_jpcite_as": [
    "a live web search engine",
    "a grant application filing service",
    "an accounting SaaS",
    "a credit bureau",
    "a legal or tax advisor",
    "a guarantee of eligibility, award, correctness, or cost savings"
  ],
  "route_elsewhere_when": {
    "official_application": "J-Grants or the official program page",
    "latest_unindexed_news": "web search or official source re-check",
    "private_company_credit_rating": "TDB, TSR, or another credit research service",
    "bookkeeping_or_tax_filing": "freee, Money Forward, Yayoi, or an accounting professional",
    "private_corpus_search": "the user's RAG or document management system"
  },
  "answer_rule": "Preserve known_gaps and no_hit_not_absence. Do not turn missing evidence into a negative conclusion."
}
```

## 8. Messaging hierarchy

### 8.1 One-line positioning

> Source-backed prebuilt outputs for AI agents working with Japanese public data.

### 8.2 Two-line positioning

> jpcite turns Japanese public programs, company facts, laws, invoice status, enforcement cases, and related sources into evidence packets AI agents can use before answering. It returns source receipts, fetched timestamps, known gaps, and human-review boundaries instead of pretending to make final tax, legal, credit, or application decisions.

### 8.3 Japanese positioning

> jpcite は、日本の公的制度・法人・法令・インボイス・行政処分などを、AI が回答前に使える出典付き成果物パケットへ変換する API/MCP です。申請、会計処理、信用調査、税務・法律判断を置き換えるものではなく、根拠・取得時点・known gaps を揃える前段レイヤーです。

### 8.4 Comparison tagline

> Use J-Grants to file, accounting SaaS to run accounting, credit bureaus for credit research, Web search for breaking updates, and jpcite to give AI agents source-backed public evidence before they answer.

## 9. Competitor-specific battlecards

### 9.1 Web search battlecard

Use when:

- User wants fresh discovery, broad search, or official page navigation.

jpcite hook:

- "Before summarizing, get an evidence packet so the AI keeps sources and gaps aligned."

Do not say:

- "Search is unreliable."

### 9.2 RAG battlecard

Use when:

- User has internal documents or wants custom private retrieval.

jpcite hook:

- "Let RAG handle private context; let jpcite handle public Japanese evidence."

Do not say:

- "RAG is obsolete."

### 9.3 J-Grants battlecard

Use when:

- User needs official application flow, official open calls, attached documents, or API wrapper.

jpcite hook:

- "Use jpcite before filing to compare candidates, identify gaps, and prepare source-backed questions."

Do not say:

- "J-Grants lacks API/MCP."

### 9.4 freee / MF / 弥生 battlecard

Use when:

- User needs bookkeeping, SaaS data, invoice/expense/payroll/tax workflows, or buying eligible software.

jpcite hook:

- "Use jpcite to supply public evidence to the AI assistant around those workflows."

Do not say:

- "jpcite replaces accounting SaaS AI."

### 9.5 補助金ポータル battlecard

Use when:

- User wants human-readable articles, consultation, or application support.

jpcite hook:

- "Use jpcite when the consumer is an agent or system that needs structured evidence, not an article."

Do not say:

- "Portals are outdated."

### 9.6 TDB / TSR battlecard

Use when:

- User needs credit score, private research, or bank-grade credit workflow.

jpcite hook:

- "Use jpcite for public baseline before or alongside credit research."

Do not say:

- "jpcite is cheaper credit research."

### 9.7 ChatGPT / Perplexity battlecard

Use when:

- User wants natural language answer, broad web answer, or exploratory conversation.

jpcite hook:

- "Use jpcite as a tool call before the answer so the final text cites real receipts and preserves gaps."

Do not say:

- "ChatGPT cannot cite sources."

### 9.8 Generic MCP battlecard

Use when:

- User needs raw browser/search/PDF/spreadsheet access.

jpcite hook:

- "Use raw tools for uncovered gaps; use jpcite for the domain packet and decision boundary."

Do not say:

- "Generic MCP tools are low quality."

## 10. Product implication

Competitive positioning only works if the product surface follows it. Implementation planning should avoid building "another search UI" as the main story.

Priority surfaces:

- `evidence_answer`: short answer-ready facts with source receipts and known gaps.
- `company_public_baseline`: public company evidence, not credit score.
- `application_strategy`: grant/program candidate comparison and review checklist, not application proxy.
- `source_receipt_ledger`: source trail for auditability.
- `client_monthly_review`: recurring professional workflow prep, not tax advice.
- `agent_routing_decision`: tell AI when to use jpcite vs alternatives.

Every packet should expose:

- `packet_type`
- `source_receipts[]`
- `claims[]`
- `known_gaps[]`
- `human_review_required`
- `request_time_llm_call_performed: false`
- `web_search_performed_by_jpcite: false`
- `no_hit_not_absence` behavior
- `billing_metadata`
- `agent_guidance`

## 11. Source notes checked for this deep dive

Local repo anchors:

- `docs/_internal/PREBUILT_DELIVERABLE_PACKETS_2026_05_15.md`
- `docs/_internal/p0_geo_first_packets_spec_2026-05-15.md`
- `docs/_internal/agent_recommendation_story_deepdive_2026-05-15.md`
- `docs/geo/seo_geo_strategy_2026_05_11.md`
- `docs/api-reference.md`
- `docs/faq.md`
- `docs/compare_matrix.csv`

External spot checks on 2026-05-15:

- J-Grants official/public MCP wrapper: https://github.com/digital-go-jp/jgrants-mcp-server
- J-Grants MCP marketplace listing example: https://mcp.aibase.com/server/1916355215526699010
- J-Grants Web-API terms PDF: https://fs2.jgrants-portal.go.jp/API%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84.pdf
- freee 補助金 press release: https://corp.freee.co.jp/news/20230929freee_subsidy.html
- Money Forward デジタル化・AI導入補助金 page: https://biz.moneyforward.com/it_subsidies/
- 弥生 デジタル化・AI導入補助金2026 press release: https://www.yayoi-kk.co.jp/company/pressrelease/detail.20260511/

Important correction from older local comparison material:

- Do not claim J-Grants lacks public API/MCP. Current positioning must assume J-Grants official API and MCP wrappers exist. jpcite should win on cross-source, source-backed prebuilt outputs, not on raw access to J-Grants alone.

