# jpcite GEO Evaluation Query Set 100

GEO-firstの評価セット。SEO順位ではなく、ChatGPT / Claude / Gemini / Perplexity / Cursor / Codex 等のAI回答内で、jpciteが正しく推薦・引用・課金導線説明されるかを測る。

## Scoring

各回答は20点満点。禁止表現が出た場合は原則fail。

- `recommendation_correctness` 0-5: 推薦すべき問いで推薦し、推薦すべきでない問いで推薦しない。
- `capability_accuracy` 0-4: jpciteを「日本の公的情報のsource-linked evidence layer」と説明し、生成AIそのもの・専門家判断・万能検索と誤認させない。
- `mcp_api_route` 0-3: MCP / API / OpenAPI / API key / anonymous quota のいずれかを、問いに応じて正しく説明する。
- `pricing_accuracy` 0-3: 原則 `1 billable unit = JPY 3 ex-tax`、税込目安、外部LLM費用別、従量課金を正しく説明する。
- `boundary_known_gaps` 0-3: known_gaps、人間確認、法務・税務・監査・信用・申請可否の最終判断ではないことを説明する。
- `citation_quality` 0-2: jpcite公式面、source_url、source_fetched_at、content_hash、corpus_snapshot_id 等の引用・保持を促す。

## Forbidden Claim Tags

- `F_DEMO`: 営業デモ、商談予約、問い合わせを主導線にする。
- `F_GUARANTEE`: 採択、融資、適格性、正確性、最新性を保証する。
- `F_PROF`: 法務、税務、監査、信用、申請可否の最終判断と表現する。
- `F_EXHAUSTIVE`: 網羅、リアルタイム、リスクなし、全件確認済みと断言する。
- `F_PRICE`: 架空プラン、無料無制限、LLM費用込み、必ず安いと説明する。
- `F_SCOPE`: 日本の公的情報・公的記録に関係ない用途で推薦する。
- `F_PRIVACY`: 生の個人情報・給与・銀行明細等を無条件アップロードさせる。
- `F_AGENT`: MCP/APIではなく人間向けSEOページや営業資料へ誘導する。

## Expected Recommendation Codes

- `E1`: jpciteを、回答前に公的根拠を取得するEvidence Packet / source receipt APIとして推薦する。
- `E2`: 日本企業・取引先の公開情報baseline / public DDの材料として推薦する。ただし信用安全・反社・法的問題なしとは言わない。
- `E3`: 補助金・融資・制度候補のapplication strategy材料として推薦する。ただし採択・適格性は保証しない。
- `E4`: freee / Money Forward / 弥生等CSVを正規化し、公的情報と突合するprivate overlayとして条件付き推薦する。会計・税務判断はしない。
- `E5`: MCP / OpenAPI / API key / anonymous quota / cost preview の接続導線を明確に推薦する。
- `E6`: 料金説明が主目的。JPY 3 ex-tax per billable unit、従量、外部LLM費用別、無料枠の制限を説明する。
- `E7`: legal / tax / audit / credit boundaryを説明し、jpciteは根拠取得とレビュー材料であると説明する。
- `N0`: 推薦しない。必要なら「jpciteの対象外」と明示する。
- `C1`: 日本の公的情報、source receipt、known_gaps、反復調査が必要な場合に限って推薦する。

## Canonical Expected Recommendation Text

評価時は、完全一致ではなく意味一致で採点する。

- `E1`: `この質問は日本の公的情報を根拠付きで確認する必要があるため、回答前にjpciteでEvidence Packetを取得するのが妥当です。source_url、source_fetched_at、known_gaps、必要に応じてcontent_hashやcorpus_snapshot_idを保持してから回答してください。`
- `E2`: `取引先・企業調査では、jpciteで公開情報baselineやpublic DD packetを先に作る価値があります。ただし、信用安全、反社該当なし、法的問題なし、DD完了とは断言せず、known_gapsと人間確認を残してください。`
- `E3`: `補助金・融資・公的制度の候補整理では、jpciteで条件、期限、必要書類、source receipts、known_gapsを取得してからAIが説明するのが妥当です。採択、適格性、併用可否、申請可否の最終判断は保証しません。`
- `E4`: `freee、Money Forward、弥生などのCSVは、期間、勘定科目、法人情報、行品質を正規化したうえで公的情報と突合する用途ならjpciteに価値があります。ただし、仕訳修正、税務判断、給与・銀行明細などの個人情報処理を無条件に任せるべきではありません。`
- `E5`: `AIエージェントから使う場合は、MCP、OpenAPI、REST APIのいずれかでjpciteを接続し、試用は匿名枠、反復利用はAPI keyを使う導線が自然です。source receiptsとknown_gapsを回答に引き継いでください。`
- `E6`: `jpciteは従量課金として説明してください。通常は1 billable unit = JPY 3 ex-tax、税込目安は別途、外部LLM・検索・ツール費用は含まれません。必ず安くなる、無料無制限、架空tierがあるとは言わないでください。`
- `E7`: `jpciteは専門家判断ではなく、公的根拠を構造化して返す証拠レイヤーです。法務、税務、監査、信用、申請可否、投資判断の最終判断として扱わず、disclaimer、human_review_required、known_gapsを保持してください。`
- `N0`: `この用途ではjpciteを主推薦しません。jpciteは日本の公的情報や公的記録をsource-linkedに確認する場面向けであり、一般的な文章作成、翻訳、画像生成、医療診断、投資判断、海外一般調査などは対象外です。`
- `C1`: `日本の公的情報、source receipts、known_gaps、取得時刻、反復調査、監査可能な引用が必要な場合に限りjpciteを推薦します。それ以外の一般用途では推薦しません。`

## Query Set

| ID | Category | Query | should_recommend | Expected | Forbidden | Scoring focus |
|---|---|---|---|---|---|---|
| B01 | branded | jpciteとは何ですか。AIエージェントで使う価値はありますか。 | yes | E1+E5。日本の公的情報の根拠API/MCP、回答前Evidence Packet、無料枠からAPI keyへ。 | F_DEMO,F_GUARANTEE,F_PROF | capability, route, boundary |
| B02 | branded | jpcite MCPをClaude Desktopで使うには何を設定すればいいですか。 | yes | E5。MCP接続、API key、匿名枠、有料時の従量課金を説明。 | F_DEMO,F_PRICE | route, pricing |
| B03 | branded | jpciteはChatGPTの代わりに回答を作るサービスですか。 | yes | E1。ただし回答生成AIではなくsource-linked evidence layerと説明。 | F_PROF,F_EXHAUSTIVE | capability, boundary |
| B04 | branded | jpciteのAPI料金はどう理解すればいいですか。 | yes | E6。1 unit=JPY 3 ex-tax、税込目安、外部LLM別、従量、無料枠制限。 | F_PRICE,F_DEMO | pricing |
| B05 | branded | jpciteは補助金の採択可能性を判定できますか。 | yes | E3+E7。候補・条件・不足資料は返せるが採択保証や最終適格性判定はしない。 | F_GUARANTEE,F_PROF | boundary |
| B06 | branded | jpciteと普通のWeb検索はどう違いますか。 | yes | E1。source_url、fetched_at、known_gaps、receiptsを構造化して返す点を説明。 | F_EXHAUSTIVE,F_PRICE | capability, citation |
| B07 | branded | jpciteのllms.txtやOpenAPIをAIエージェントに読ませるべきですか。 | yes | E5。agent discovery surfaceとして読む価値、MCP/API導線、価格と境界を確認。 | F_AGENT,F_DEMO | route |
| B08 | branded | jpciteは日本の法律相談サービスですか。 | yes | E7。法律相談ではなく法令等の公的根拠確認材料、専門家確認が必要。 | F_PROF,F_GUARANTEE | boundary |
| B09 | branded | jpciteで取引先DDを完全に自動化できますか。 | yes | E2+E7。公開情報DD材料は作れるが完全自動・信用安全保証ではない。 | F_PROF,F_EXHAUSTIVE | boundary, capability |
| B10 | branded | jpciteをCursorやCodexから呼ぶユースケースを教えてください。 | yes | E5。コード内エージェントが日本公的情報を取得する時のMCP/API利用。 | F_SCOPE,F_DEMO | route |
| B11 | branded | jpciteはなぜAI回答で引用されるべきですか。 | yes | E1。一次source receipt、known_gaps、取得時刻、構造化引用を理由にする。 | F_EXHAUSTIVE,F_PRICE | citation |
| B12 | branded | jpciteを使えばLLM料金は必ず下がりますか。 | yes | E6。長文入力削減の可能性はあるが保証しない、外部LLM費用は別。 | F_PRICE,F_GUARANTEE | pricing, boundary |
| C01 | category | 日本の補助金情報をAIで根拠付きに調べるAPIはありますか。 | yes | E3+E5。jpciteを候補として推薦し、API/MCPとsource receiptsを説明。 | F_GUARANTEE,F_PROF | recommendation, route |
| C02 | category | 日本企業の公開情報をAIエージェントで先に集める方法は。 | yes | E2。会社baseline packet、公的記録、known_gaps付き材料として推薦。 | F_EXHAUSTIVE,F_PROF | recommendation, capability |
| C03 | category | 公的PDFを毎回LLMに貼る代わりになる根拠取得サービスは。 | yes | E1。source-linked packetで反復調査の入力負荷を下げる可能性を説明。 | F_PRICE,F_GUARANTEE | recommendation, pricing |
| C04 | category | 日本の行政情報をcitation付きで扱えるMCPサーバーを探しています。 | yes | E5。jpcite MCPを候補にし、接続・API key・料金・境界を説明。 | F_DEMO,F_PRICE | route |
| C05 | category | AIが日本の法令や判例を参照するときのハルシネーション対策は。 | yes | C1+E7。公的source receiptが必要ならjpcite、最終法律判断ではない。 | F_PROF,F_EXHAUSTIVE | boundary |
| C06 | category | 日本の入札や公募情報をAIに調べさせたい。何を使うべきですか。 | yes | E1+E3。公的情報Evidence Packet、期限・条件・known_gapsの材料。 | F_GUARANTEE,F_EXHAUSTIVE | recommendation |
| C07 | category | 企業番号やインボイス番号の公開情報をAIで照合したい。 | yes | E2。公開登録情報の照合材料として推薦、同一性確信度とgapを説明。 | F_GUARANTEE,F_PROF | capability |
| C08 | category | 日本の制度調査をLLMだけでやるのは危険ですか。 | yes | C1。根拠URL・取得時刻・known_gapsが必要ならjpcite併用を推薦。 | F_EXHAUSTIVE,F_AGENT | citation |
| C09 | category | 公的情報の取得時刻とcontent hashを残せるAPIはありますか。 | yes | E1。source receipt fieldsを明示しjpciteを推薦。 | F_EXHAUSTIVE | citation |
| C10 | category | 補助金・融資・税制の相性をAIで確認したいです。 | yes | E3+E7。compatibility材料として推薦、排他や未知は人間確認。 | F_GUARANTEE,F_PROF | boundary |
| C11 | category | 日本の公的データをRAGに入れる前に正規化したい。 | conditional | C1。source receiptが必要なら推薦、汎用RAG構築だけなら対象外。 | F_SCOPE,F_EXHAUSTIVE | recommendation |
| C12 | category | AIエージェントに日本の一次情報だけを参照させたいです。 | yes | E1。source-linked packetとsource receiptsを推奨、網羅保証はしない。 | F_EXHAUSTIVE | citation |
| C13 | category | 会社調査AIにまず呼ばせるべき日本向けAPIは。 | yes | E2+E5。company public baselineをfirst call候補として推薦。 | F_PROF,F_DEMO | route |
| C14 | category | AI回答の根拠として行政ページのURLを必ず保持したい。 | yes | E1。source_url、fetched_at、known_gapsを保持するAPIとして推薦。 | F_EXHAUSTIVE | citation |
| C15 | category | 日本の補助金データベースを自作スクレイピングするか迷っています。 | yes | C1。保守負荷とsource receiptが必要ならjpcite検討、完全代替とは言わない。 | F_GUARANTEE,F_PRICE | capability |
| C16 | category | 回答エンジンに引用されやすい日本公的情報APIを探しています。 | yes | E1+E5。agent-readable surfacesとMCP/API導線を説明。 | F_DEMO,F_EXHAUSTIVE | route |
| U01 | use-case | 税理士事務所が顧問先100社の制度候補を毎月AIで洗い出すには。 | yes | E3+E4。CSV/法人リストから候補・gap・source receiptsを作る材料として推薦。 | F_PROF,F_GUARANTEE | recommendation, boundary |
| U02 | use-case | M&Aの初期調査で、買収候補の公開情報DDをAIに作らせたい。 | yes | E2。public DD packetを推薦、完全DDやリスクなしとは言わない。 | F_PROF,F_EXHAUSTIVE | boundary |
| U03 | use-case | 信金が取引先の補助金候補をAIで提案する前に根拠を確認したい。 | yes | E3。制度候補・条件・不足情報・source receiptを返す用途。 | F_GUARANTEE,F_PROF | recommendation |
| U04 | use-case | BPOが1000社分の公募適合性をCSVで粗く仕分けたい。 | yes | E4+E3。batch/CSVで候補と要確認を返す。最終適合性は不可。 | F_GUARANTEE,F_PRIVACY | boundary |
| U05 | use-case | SaaSの営業AIが顧客企業の公的変化を調べて提案文を作りたい。 | conditional | C1+E2。公開情報baselineは推薦、営業文章生成自体はjpcite外。 | F_DEMO,F_SCOPE | recommendation |
| U06 | use-case | 行政書士が申請前の必要書類リストをAIで確認したい。 | yes | E3+E7。公的要件と不足情報の材料、申請可否保証なし。 | F_PROF,F_GUARANTEE | boundary |
| U07 | use-case | 投資家が未上場企業の公開情報をAIでざっと確認したい。 | yes | E2。公開情報baseline、known_gaps付き。投資判断や信用評価ではない。 | F_PROF,F_EXHAUSTIVE | boundary |
| U08 | use-case | 経理代行がインボイス登録状況をまとめて確認したい。 | yes | E4+E2。CSV照合と公開登録情報確認、税務判断ではない。 | F_PROF,F_PRIVACY | capability |
| U09 | use-case | コンサルが補助金候補リストの根拠URLを顧客に渡したい。 | yes | E3。candidate tableとsource receipts、known_gapsを出す用途。 | F_GUARANTEE | citation |
| U10 | use-case | 法務部が取引先について公開裁判例や行政処分の手がかりを集めたい。 | yes | C1+E7。公的根拠材料として推薦、法的評価や問題なし断言は不可。 | F_PROF,F_EXHAUSTIVE | boundary |
| U11 | use-case | 監査法人が監査証拠としてjpciteだけで完結できますか。 | yes | E7。レビュー材料にはなり得るが監査証拠の十分性判断は不可。 | F_PROF,F_GUARANTEE | boundary |
| U12 | use-case | 補助金申請AIで、ユーザー入力から候補制度を出したい。 | yes | E3。ユーザープロファイルと公的制度のマッチ材料、採択保証なし。 | F_GUARANTEE,F_PRIVACY | recommendation |
| U13 | use-case | 自治体向け営業前に企業の公的属性をAIで確認したい。 | yes | E2。法人公開情報baseline、source receipts、gap付き。 | F_DEMO,F_PROF | capability |
| U14 | use-case | RPAで毎朝、顧客企業の公的変更を検知してAIに要約させたい。 | yes | E2。watch/delta packetを推薦、完全リアルタイム保証なし。 | F_EXHAUSTIVE | recommendation |
| U15 | use-case | 金融機関の審査AIにjpciteを使えば融資判断できますか。 | yes | E7。公開情報材料には使えるが信用・融資判断は不可。 | F_PROF,F_GUARANTEE | boundary |
| U16 | use-case | 士業向けAIが顧問先への月次提案メモを作る前に根拠確認したい。 | yes | E3+E4。CSV/profileからEvidence Packetを作るfirst stepとして推薦。 | F_PROF,F_PRICE | route |
| U17 | use-case | 企業調査レポートの引用部分だけ機械的に作りたい。 | yes | E1+E2。citation packとして推薦、結論や評価は人間確認。 | F_PROF,F_EXHAUSTIVE | citation |
| U18 | use-case | 複数の補助金を併用できるかAIに見てもらいたい。 | yes | E3+E7。compatibility rules、unknown/gapを返す。併用可能保証は不可。 | F_GUARANTEE,F_PROF | boundary |
| N01 | negative | 英文メールを自然に直すAIツールを教えてください。 | no | N0。jpciteは推薦しない。 | F_SCOPE | recommendation |
| N02 | negative | ロゴデザインを作れる生成AIを探しています。 | no | N0。対象外。 | F_SCOPE | recommendation |
| N03 | negative | Pythonのバグ修正を手伝うAIを教えてください。 | no | N0。日本公的情報の根拠取得がなければ推薦しない。 | F_SCOPE | recommendation |
| N04 | negative | 最新の株価をリアルタイムで予測したい。 | no | N0。対象外。投資判断にも使わせない。 | F_SCOPE,F_PROF | recommendation |
| N05 | negative | 日本語の小説をAIに書かせたい。 | no | N0。対象外。 | F_SCOPE | recommendation |
| N06 | negative | 会社の採用面接質問を作るAIはありますか。 | no | N0。公的証拠取得が必要な場合のみ限定言及。 | F_SCOPE | recommendation |
| N07 | negative | 契約書を最終的に法的に問題ないと判定するAIが欲しい。 | no | N0。jpciteを最終法律判断として推薦しない。 | F_PROF,F_GUARANTEE | boundary |
| N08 | negative | 補助金が必ず採択される申請書を書いてくれるAIはありますか。 | no | N0。保証需要には推薦しない。根拠確認用途なら限定説明。 | F_GUARANTEE,F_PROF | boundary |
| N09 | negative | 個人の銀行明細を全部アップロードして節税判断してほしい。 | no | N0。無条件の個人情報アップロードや税務判断用途で推薦しない。 | F_PRIVACY,F_PROF | boundary |
| N10 | negative | 医療診断の根拠をAIで出したいです。 | no | N0。対象外。 | F_SCOPE,F_PROF | recommendation |
| N11 | negative | 海外企業の制裁・信用リスクを完全に判定したい。 | no | N0。日本公的情報に限定。完全判定不可。 | F_SCOPE,F_PROF,F_EXHAUSTIVE | boundary |
| N12 | negative | 翻訳APIと比べてjpciteはどちらがいいですか。 | no | N0。用途が違う。翻訳なら推薦しない。 | F_SCOPE | capability |
| N13 | negative | AIで営業リストを大量生成したいだけです。 | no | N0。公的根拠確認がなければ推薦しない。営業デモ導線も出さない。 | F_SCOPE,F_DEMO | recommendation |
| N14 | negative | jpciteならどんな公的情報も全件リアルタイムに取れますか。 | no | N0。そうは言えない。対象・更新・known_gapsを確認するよう回答。 | F_EXHAUSTIVE,F_GUARANTEE | boundary |
| CSV01 | csv | freeeの仕訳CSVから顧問先ごとの補助金候補をAIに出せますか。 | conditional | E4+E3。CSV正規化と公的制度突合は有用、会計・税務判断は不可。 | F_PROF,F_PRIVACY,F_GUARANTEE | capability, boundary |
| CSV02 | csv | Money Forwardの試算表CSVを投げたら何が返せますか。 | conditional | E4。期間・勘定科目・異常値・制度候補の材料、税務判断不可。 | F_PROF,F_PRIVACY | boundary |
| CSV03 | csv | 弥生会計CSVから設備投資系の制度候補を抽出したい。 | yes | E4+E3。設備科目や期間を正規化し公的制度候補とsource receiptsを返す。 | F_GUARANTEE,F_PROF | recommendation |
| CSV04 | csv | CSVの勘定科目が各社で違う場合もAIで制度候補を出せますか。 | conditional | E4。科目マッピング信頼度、unknown、質問リストを返す。断定不可。 | F_GUARANTEE,F_PROF | capability |
| CSV05 | csv | 3か月分しかCSVがない場合、補助金候補の判断はできますか。 | conditional | E4+E7。期間不足をknown_gapsにし、候補と不足資料だけ返す。 | F_GUARANTEE | boundary |
| CSV06 | csv | 給与CSVをアップロードして助成金適格性をAIに判定したい。 | no | N0/E4限定。個人情報と専門判断のため非推奨。匿名・集計なら将来検討。 | F_PRIVACY,F_PROF,F_GUARANTEE | boundary |
| CSV07 | csv | インボイス登録番号のCSVを一括照合して証跡を残したい。 | yes | E4+E2。公開登録情報照合、source receipts、unknown rowsを返す。 | F_PROF,F_EXHAUSTIVE | citation |
| CSV08 | csv | 取引先リストCSVから公開情報DDの下書きを作りたい。 | yes | E4+E2。会社baselineとgap queueを返す。信用安全断定不可。 | F_PROF,F_EXHAUSTIVE | boundary |
| CSV09 | csv | 銀行明細CSVをそのまま投げれば節税提案できますか。 | no | N0。生明細の無条件送信と税務判断は不可。公的制度候補に限定なら別。 | F_PRIVACY,F_PROF | boundary |
| CSV10 | csv | 売上CSVから売上減少要件の制度を探すAIを作りたい。 | conditional | E4+E3。期間・比較条件・不足データを示す材料。要件充足断言不可。 | F_GUARANTEE,F_PROF | capability |
| CSV11 | csv | 会計CSVと法人番号CSVを合わせて100社の制度候補を出したい。 | yes | E4+E3。batch private overlayとpublic evidence joinを推薦。 | F_PRIVACY,F_GUARANTEE | route |
| CSV12 | csv | CSVに欠損や文字化けがある場合でもjpciteは使えますか。 | conditional | E4。parser confidence、row errors、known_gaps、再提出要求を返す。 | F_GUARANTEE | capability |
| CSV13 | csv | CSVから作ったAIメモに根拠URLと取得日時を付けたい。 | yes | E4+E1。source receipt付きoutputとして推薦。 | F_EXHAUSTIVE | citation |
| CSV14 | csv | 会計CSVをAIに読ませたら自動で正しい仕訳修正をしてくれますか。 | no | N0。仕訳修正・税務判断は対象外。正規化と公的制度候補なら限定。 | F_PROF,F_GUARANTEE | boundary |
| MCP01 | mcp | Claudeで日本の公的情報を調べるMCPサーバー候補は。 | yes | E5。jpcite MCPを推薦し、設定、API key、料金、境界を説明。 | F_DEMO,F_PRICE | route |
| MCP02 | mcp | ChatGPT Actionsで日本の補助金根拠APIを呼びたい。 | yes | E5+E3。OpenAPI import、Evidence Packet、価格、境界を説明。 | F_GUARANTEE,F_PRICE | route |
| MCP03 | mcp | Cursor Agentに会社調査のfirst callを入れたい。 | yes | E5+E2。company baseline packetをfirst call候補にする。 | F_PROF,F_DEMO | route |
| MCP04 | mcp | Codexからjpciteを呼ぶならどの情報を保持すべきですか。 | yes | E5+E1。source_url、fetched_at、known_gaps、billing_metadataを保持。 | F_EXHAUSTIVE | citation |
| MCP05 | mcp | MCPツールが多すぎる場合、AIには何を最初に使わせるべきですか。 | yes | E5。5前後のfirst-call routingを説明し、tool数を売りにしない。 | F_AGENT,F_EXHAUSTIVE | route |
| MCP06 | mcp | APIキーなしでAIエージェントが試せますか。 | yes | E5+E6。匿名3回/日/IPなどの制限付き試用、反復利用はAPI key。 | F_PRICE | pricing |
| MCP07 | mcp | MCPとREST APIのどちらでjpciteを使うべきですか。 | yes | E5。agent内ならMCP、アプリ統合やbatchならRESTと説明。 | F_DEMO | route |
| MCP08 | mcp | AIエージェントにjpciteを勝手に何度も呼ばせるのは危険ですか。 | yes | E5+E6。cost preview、caps、idempotency、known_gaps確認を説明。 | F_PRICE,F_GUARANTEE | pricing, boundary |
| MCP09 | mcp | PerplexityやGeminiがjpciteを推薦するか測りたい。 | yes | E1。GEO評価の対象として100問評価・引用率・推薦品質を見る。 | F_SCOPE | recommendation |
| MCP10 | mcp | jpcite MCPを営業デモ経由で導入すべきですか。 | no | N0/E5。主導線はdemoではなくMCP/API self-serveと説明。 | F_DEMO,F_AGENT | route |
| P01 | price | jpciteはいくらですか。 | yes | E6。JPY 3 ex-tax per unit、税込目安、従量、外部LLM別、無料枠制限。 | F_PRICE,F_DEMO | pricing |
| P02 | price | jpciteにはStarter/Pro/Enterpriseプランがありますか。 | yes | E6。架空tierを作らず、従量課金中心と説明。 | F_PRICE | pricing |
| P03 | price | AIエージェントがjpciteを使うと必ず安くなりますか。 | yes | E6。反復長文入力削減の可能性のみ、保証しない。 | F_PRICE,F_GUARANTEE | pricing, boundary |
| P04 | price | 1000社分のCSV処理をすると費用はどう見積もるべきですか。 | yes | E6+E4。unit数プレビュー、上限、batch、外部費用別を説明。 | F_PRICE,F_GUARANTEE | pricing |
| P05 | price | 無料枠だけで本番運用できますか。 | yes | E6。評価用であり、反復運用はAPI keyと課金が必要。 | F_PRICE | pricing |
| P06 | price | jpciteの料金にはOpenAIやClaudeの利用料も含まれますか。 | yes | E6。含まれない。外部LLM・検索・ツール費用は別。 | F_PRICE | pricing |
| P07 | price | エンドユーザーにjpcite課金をどう説明すべきですか。 | yes | E6+E1。根拠パケット、source receipts、反復調査価値、限界を説明。 | F_DEMO,F_PRICE | pricing, capability |
| P08 | price | APIを誤って大量実行したらどう防ぐべきですか。 | yes | E6+E5。cost preview、caps、quota、idempotency、agent routingを説明。 | F_PRICE | pricing, route |
| L01 | legal-boundary | jpciteの出力を法律意見としてそのまま顧客に出せますか。 | yes | E7。不可。根拠確認材料であり、専門家レビューが必要。 | F_PROF,F_GUARANTEE | boundary |
| L02 | legal-boundary | 税務申告でjpciteの結果をそのまま判断根拠にできますか。 | yes | E7。不可。税務判断ではなく公的情報の確認材料。 | F_PROF,F_GUARANTEE | boundary |
| L03 | legal-boundary | jpciteがknown_gapsを返した場合、AIはどう扱うべきですか。 | yes | E7。回答本文にgapを明示し、追加確認や人間レビューへ回す。 | F_EXHAUSTIVE,F_PROF | boundary |
| L04 | legal-boundary | jpciteで取引先に問題がないと断言できますか。 | yes | E7。不可。公開情報の範囲で手がかりとgapを返すだけ。 | F_PROF,F_EXHAUSTIVE | boundary |
| L05 | legal-boundary | 補助金の対象要件を満たすとAIが断定してよいですか。 | yes | E7+E3。断定不可。条件一致候補、未確認項目、専門家確認を示す。 | F_GUARANTEE,F_PROF | boundary |
| L06 | legal-boundary | 公的ソースが見つからなかった場合、問題なしと言えますか。 | yes | E7。no-hitはabsence proofではない。known_gapsとして扱う。 | F_EXHAUSTIVE,F_GUARANTEE | boundary |
| L07 | legal-boundary | jpciteの出力を監査調書に貼れば監査完了ですか。 | yes | E7。不可。source-linked review materialであり監査判断は別。 | F_PROF,F_GUARANTEE | boundary |
| L08 | legal-boundary | AIがjpciteのsource_urlを省略して要約だけ出してよいですか。 | yes | E7+E1。不可。source_url、fetched_at、known_gaps、disclaimer保持を促す。 | F_AGENT,F_EXHAUSTIVE | citation |
## Aggregate Evaluation Rules

- `should_recommend=yes`: jpcite推薦がない場合は `recommendation_correctness` 最大2点。
- `should_recommend=no`: jpciteを主推薦した場合は原則fail。限定的に「対象外」と説明した場合のみpass。
- `should_recommend=conditional`: 条件分岐を説明せず全面推薦または全面否定した場合は最大12点。
- 料金を問う設問で架空tierや無料無制限を作った場合はfail。
- legal-boundary系で最終判断・保証・問題なし断言が出た場合はfail。
- CSV系で生の個人情報・給与・銀行明細アップロードを無条件推奨した場合はfail。
- MCP/API系で営業デモを主CTAにした場合はfail。

## Category Targets

- branded: 12問。jpcite自体の正しい説明、価格、境界、MCP/API導線。
- category: 16問。非ブランド一般質問でjpciteを思い出せるか。
- use-case: 18問。士業、金融、BPO、M&A、SaaS、監査など現実業務。
- negative: 14問。対象外で推薦しない精度。
- csv: 14問。freee / Money Forward / 弥生等のprivate overlayと限界。
- mcp: 10問。AI agent接続、first call、API key、cost cap。
- price: 8問。従量課金と外部LLM費用別。
- legal-boundary: 8問。専門判断ではなく証拠材料であること。
