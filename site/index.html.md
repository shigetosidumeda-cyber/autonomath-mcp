---
source_html: index.html
brand: jpcite
canonical: https://jpcite.com/index.html
fetched_at: 2026-05-11T10:54:09.804440+00:00
est_tokens: 4010
token_divisor: 4
license: see https://jpcite.com/tos
---

# index.html

[メインコンテンツへスキップ / Skip to main content ](#main)

[](/)

# AI が日本制度を呼ぶ前の Evidence。

1 call = 1 unit = 税込 ¥3.30。tier なし・月額なし・匿名 3 req/日。

[無料で試す → ](/playground.html?flow=evidence3)[ドキュメント ](/docs/getting-started/)
curl 1 行で Evidence Packet を取得。source_url + source_fetched_at + known_gaps + 8 業法 fence が同梱。

## 利用者別エントリ

### For AI agent devs

Claude MCP / Custom GPT / Cursor / Codex / Anthropic API direct に 1 行で bundle。公開 API / MCP tool set をそのまま呼び出せます。

[1 行で接続 → ](/connect/claude-code.html)

### For 業界実務家

税理士・会計士・行政書士・M&A・信金。AI agent 経由で、顧問先レビュー、M&A DD / 取引先公開情報チェック、制度候補確認などの request 数と料金を事前に見積もれます。

[利用者層別 → ](/audiences/)

### For LLM ops

LLM token と完全独立で ¥3/unit 固定。X-Cost-Cap-JPY + X-Client-Tag で予算と顧客原価を制御。

[料金根拠 → ](/docs/pricing/)

人が画面でブラウズする SaaS ではありません。Custom GPT / Claude MCP / Claude Agent SDK / claude -p / Cursor / Codex に bundle し、AI が読む前に制度データを小さい根拠パケットへ圧縮するレイヤー。1 call = 1 unit = 税込 ¥3.30、tier なし・月額固定なし・匿名 3 req/日。
3 段構造 — 人 → AI agent → jpcite

- 1. 人
税理士・会計士・行政書士・診断士・M&A advisor・信金渉外 が業務質問を投げる。
- →
- 2. AI agent
Claude Desktop / ChatGPT GPT / Cursor / Codex / 顧問先 Slack bot が推論。LLM は agent 側。
- →
- 3. jpcite
出典 URL + 取得時刻 + corpus_snapshot_id + known_gaps + 8 業法 fence を 1 unit で返却。LLM 呼ばない。

jpcite 側は LLM 推論を行わず、検索・構造化・出典メタデータ返却に徹します。agent dev の billing は自前 LLM token と独立で、jpcite は ¥3/unit 固定式。Claude Desktop / Cursor / Cline は MCP、ChatGPT Custom GPT は OpenAPI Actions、社内 AI・業務システムは REST から呼び出します。

[AI agent dev: 1 行で接続 (Claude/Cursor/ChatGPT/Codex) → ](/connect/claude-code.html)[料金: ¥3 per billable unit (税込 ¥3.30、完全従量) → ](/pricing.html)

## 主要 metrics (current public catalog snapshot)

11,601

programs (S=114 / A=1,340)

9,484

法令 catalog (全文対応 6,493)

8

業法 fence (envelope 自動)

151

MCP tools (advertised; availability on /status)

302

REST paths (OpenAPI)

## For AI agent developers

Custom GPT / Anthropic MCP server / Cursor MCP / Codex / Anthropic API direct のどの surface でも、jpcite を 1 install 行で bundle すれば日本公的制度 11,601 + 法令 catalog 9,484 (全文対応 6,493) + 採択 2,286 + 行政処分 1,185 + 適格事業者 13,801 が evidence packet として届きます。LLM 推論は agent 側、jpcite は出典固定の retrieval 層に専念します。

- [ChatGPT Custom GPT ](/connect/chatgpt.html)— OpenAPI Action import (30-path GPT profile)
- [Claude Desktop / MCP ](/connect/claude-code.html)— uvx autonomath-mcp 1 行で公開 MCP tool set に接続
- [Cursor ](/connect/cursor.html)— .cursor/mcp.json に貼って再起動
- [Cline / Codex ](/integrations/cline.html)— VS Code 拡張または agent workflow から MCP server 追加
- [Anthropic API direct ](/docs/getting-started/)— REST API を社内 AI・業務システムの根拠取得に

## For 業界実務家 (AI agent 経由で利用)

士業本人がブラウズする想定ではなく、Claude / GPT / Cursor 側に jpcite を bundle した AI agent を業務に組み込む 6 業種シナリオ。料金は request 数から計算でき、[業種別 use case ](/audiences/) と [cost saving calculator ](/tools/cost_saving_calculator.html) で前提を確認できます。

業種 典型的な使い方 目安 req 税別料金

税理士事務所 顧問先 100 社の月次レビュー 100-150 req/月 ¥300-¥450/月

会計士事務所 監査 10 社のピーク期確認 200-400 req/期 ¥600-¥1,200/期

行政書士 月 25 案件の事前確認 250-500 req/月 ¥750-¥1,500/月

中小企業診断士 50 社スクリーニング + 個社深掘り 80-110 req/月 ¥240-¥330/月

M&A advisor 月 3-5 社のM&A DD / 取引先公開情報チェック 150-250 req/月 ¥450-¥750/月

信用金庫渉外 取引先確認 + 融資前 DD 250-350 req/月 ¥750-¥1,050/月

request 数の考え方と envelope 仕様は [業種別 use case 詳細 ](/audiences/)・ [課金根拠 ](/docs/pricing/)を参照。最終判断は 8 業法の有資格者 (税理士法§52 / 弁護士法§72 / 公認会計士法§47条の2 / 行政書士法§1 / 司法書士法§3 / 社会保険労務士法§27 / 弁理士法§75 / 労働基準法§36)。

- [会社フォルダ Brief / Pack ](/products.html#company-folder): Brief は 1 unit preview。Pack は実行前見積もり units
- [顧問先月次レビュー ](/products.html#monthly-review): 100 社月 ¥5,940
- [一括 1000 案件 triage ](/products.html#application-strategy-pack): 月 ¥52,800
- [M&A DD / 取引先公開情報チェック ](/products.html#public-dd): 200 社月 ¥31,020
- [相談前プレ診断 ](/products.html#pre-consult): 50 件月 ¥1,320

匿名 curl で動作確認 (登録不要) · Playground 成果物プレビュー確認 · 自動化 API/MCP は月次レビュー・DD・一括処理の実行手段

匿名で 3 API/MCP 呼び出し/日まで無料。通常の 1 API/MCP 呼び出し = 1 billable unit = 税込 ¥3.30。最低金額・契約期間なし、いつでも解約可能。

- 出典は省庁・自治体・公庫などの一次資料を優先 (補助金まとめサイトは出典扱いしません)
- 専門業務・申請代行ではないことを API レスポンスで明示
- 適格請求書に対応
登録不要で匿名 3 リクエスト/日まで利用できます

REST / MCP の匿名枠は今すぐ利用可能 ( [開発者向け 5 分クイックスタート ](/docs/getting-started/))。通知チャネルは [保存検索・締切リマインド ](notifications.html)を案内しています。トライアルは [メール認証 (14 日 / 200 req カード不要) ](#path-email-trial)、継続利用は [Pricing ](pricing.html#api-paid)で税込 ¥3.30 / billable unit の完全従量で API キーを発行できます (既存鍵の管理は [ダッシュボード ](dashboard.html))。

## 3 つの試し方から 1 つを選ぶ

### 1. 匿名で試す

登録不要 · 3 req/日/IP

curl / Playground でその場で 3 回まで動作検証。 IP 単位、 JST 翌日 00:00 リセット。

[curl で試す → ](#curl-try)

### 2. メールでトライアル

14 日 / 200 req · カード不要

メールアドレスのみでトライアル API キーを発行。マジックリンク認証、 クレジットカード未登録。

Company URL (leave blank)
メールアドレス トライアル鍵を発行

### 3. 有料 API キーを発行

税込 ¥3.30 / billable unit

Stripe Checkout で即時発行。 完全従量、 月額固定・最低利用期間・解約違約金なし。

[Pricing で発行 → ](pricing.html#api-paid)

既に API キーをお持ちの方は [既存鍵の管理 (ダッシュボード) ](dashboard.html)。 専門業務・申請代行は提供しません。詳細は [利用規約 ](tos.html)· [プライバシー ](privacy.html)· [サポート ](support.html)。

## データと品質

### 9 つのデータセットを 1 つの API で

検索対象制度 11,601 / 全カタログ 14,472 + 採択 + 融資 + 行政処分 + 法令 + 判例 + 税制 + 入札 + 適格事業者

制度・採択事例・融資・行政処分が 1 軸目。法令・判例・税制ルールが 2 軸目。入札・適格請求書発行事業者が 3 軸目。すべてを統一フォーマットで返し、日本語の全文検索が裏で動きます。法人・個人事業主・業種・地域などで横断的に絞り込めます。

- programs · 検索対象 11,601 (Tier S 114 + A 1,340 + B 4,186 + C 5,961 )
- case_studies · 2,286
- loan_programs · 108 (担保 / 個人保証人 / 第三者保証人 三軸分解)
- enforcement_cases · 1,185
- laws · e-Gov CC-BY の法令メタデータと本文対応レコード
- tax_rulesets · 50
- court_decisions · 2,065
- bids · 362
- invoice_registrants · 13,801 (PDL v1.0、出典付き)
- 関係抽出データベース (法人・制度・法令の関係を構造化) · 50 万件超のエンティティ + 600 万件超の事実情報

### 一次資料を追える

主要公開レコードに出典 URL と取得時刻を付与

主要公開レコードでは、省庁 (経産省、農水省、中小企業庁)・政府系金融 (日本政策金融公庫)・自治体などの一次資料 URL を優先して付与します。補助金まとめサイトなどの二次情報源は出典扱いしない方針で、未取得・未確認領域は known_gaps や tier で表示します。

- 毎晩、出典 URL の生存確認を自動実行
- 出典・更新日列を監査項目として保持

### 併用不可・前提条件のルールを 181 本提示

「補助金 A と B は併用不可」を AI に推論させずデータで返す

制度 ID を渡すと、登録済みルールの範囲で併用不可・前提制度不足の確認候補を返します。AI の「それっぽい」推論ではなく、データ化済みのルールで申請前に確認すべき併用リスクを見つけやすくします。最終的な申請可否・併用可否は一次資料と専門家確認を前提とします。

- 併用不可ルール 125 本 + 前提制度ルール 17 本
- 絶対要件 15 本 + その他 24 本
- 制度の品質ラベル付き (S=厳選 / A=高品質 / B=標準 / C=参考)

## 成果物主語で選ぶ

API/MCP、Widget、通知は入口です。実務では、顧問先・案件・取引先ごとに保存できる成果物として使います。

### 会社フォルダ Brief / Pack

顧問先 / 取引先 / 一次調査

法人番号・T番号・会社名から、法人同定、インボイス、採択履歴、行政処分候補、known gaps、次に聞く質問を会社フォルダに貼りやすい形で整理します。

- 会社フォルダ README / CRM メモ / 顧問先質問票に転記
- 匿名 3 リクエスト/日 (IP 単位) 無料
- 継続運用では X-Client-Tag で会社・案件別に集計

[会社調査の始め方 → ](/docs/getting-started/audiences/)· [費用例 → ](/pricing.html)

### 顧問先月次レビュー

税理士 / 社労士 / 診断士 / 事務所チーム

顧問先ごとに、税制・補助金・助成金・融資候補、締切、変更点、known gaps、顧問先に送る確認文面を月次でまとめます。

- 決算前確認、助成金ヒアリング、保存検索の反復運用
- 月次上限と顧客別タグで原価管理

[月次レビューの費用例 → ](pricing.html)

### 申請前 Evidence Packet

行政書士 / 診断士 / 補助金コンサル

地域・業種・投資額・資金使途から、候補制度、併用注意、必要資料、申請前に聞く質問を提案前の下書きとして整理します。

- 採択・受給の保証ではなく、申請前確認の根拠整理
- 除外条件と known gaps を必ず分けて表示

[3回でプレビュー → ](/playground.html?flow=evidence3)

### 相談前プレ診断票

事務所サイト / 相談入口

来訪者の地域・業種・投資予定を、候補制度、根拠URL、known gaps、専門家に聞く質問付きの相談票に変換します。

- Widget は検索だけで終わらせず、相談前パックの入口として使う
- 相談者と専門家の双方にコピーできる質問票を出力

[診断入口を見る → ](widget.html)

### 根拠付き相談パック

Evidence-to-Expert Handoff

相談者側 : 一次資料 URL・取得時刻・known gaps・質問リストを相談前に整理。

専門家側 : 自然候補の表示順は掲載費・成約額に非連動。弁護士カテゴリでは成果課金なし。

- 相談前の evidence brief を作成
- 専門家候補には表示根拠を付与
- 専門業務・申請代行の最終判断は対象外

[Handoff を見る → ](advisors.html)

### 自動化実行

AI agent / 士業システム / 社内システム

上記の成果物を、OpenAPI / MCP / batch / webhook から繰り返し作成します。実行前見積もり、月次上限、顧客別タグで運用できます。

- cost preview で事前見積もり
- X-Client-Tag で顧客・案件別に集計
- 通常 1 API/MCP 呼び出し = 1 billable unit = 税込 ¥3.30

[成果物カタログを見る → ](products.html)

## 9 つの職種で、こう使える

利用者層 別の専用ページに、料金試算、サンプル API、既知の制約を載せています。

### M&A / VC 専門家

投資先デューデリ + 法人ウォッチ

投資・買収候補の法人番号 1 件で、行政処分歴・補助金採択歴・適格請求書発行事業者登録・関連制度を一括取得。 API のレート制限内でまとめて処理できます (例: 100 件まとめて = 500 units = 税込 ¥1,650)。 法人情報の変更は Webhook で通知できます。

- 行政処分 1,185 + 採択 2,286 + 適格事業者 13,801
- 1 案件あたり税込 ¥16.50〜¥55 程度、並列規模に応じてスケール (例: 50 件 = 税込 ¥1,650)
- 月額固定なし、必要な分だけ利用

[M&A / VC 向け詳細 → ](/audiences/vc.html)

### 税理士事務所

顧問先一括処理 + 根拠確認レポート下書き

顧問先 1 社あたり月 ¥30〜60 (通常 call 換算で月 10〜20 units) の従量制。 顧問先別の根拠確認レポート下書き (PDF + 配信フィード) と、 顧問先別 保存検索の一括実行を 1 アクションで回せます。

- 税制ルール 50 件 (措置法・通達リンク付き)
- 顧問先 1 社あたり月 ¥30〜60 (顧問先数に応じてスケール)
- 法令改正アラート (1 通知 ¥3 従量)

[税理士向け詳細 → ](/audiences/tax-advisor.html)

### 公認会計士

確認用の根拠整理 + 法令引用の自動連結

監査人確認用の根拠整理・引用索引の下書きを生成。 法令から通達、 国税不服審判所 裁決事例までを引用チェーンとして自動連結します。 月次運用はクライアント規模に応じてスケール (例: 月 1,000〜2,000 units = ¥3,000〜6,000)。監査意見・監査証明・監査調書の完成物ではありません。

- 研究開発税制 + IT導入補助金の会計処理に関連する公表資料候補
- 裁決事例 + 通達の引用チェーンを自動付与
- 根拠整理 PDF テンプレート同梱

[公認会計士向け → ](/audiences/tax-advisor.html)

### 海外法人・国際課税

e-Gov 法令の英訳 + 租税条約

e-Gov の英訳法令と各国との租税条約を 1 つの API で。 海外子会社・投資ファンドの日本側コンプライアンスを一括処理。 外資規制のかかる制度はフラグ付きで絞り込めます。

- e-Gov 英訳 ( law_articles.body_en 列)
- 租税条約・国際課税の参照導線
- 外資規制フラグ付きの制度フィルタ

[海外法人 向け (EN) → ](/en/audiences/dev.html)

### 補助金コンサルタント

顧問先 横展開 + 採択後の進捗追跡

顧問先 1 社 × 月 10 units × ¥3 = ¥30/社/月 。 顧問先数に応じてスケール (例: 200 社 ¥6,000/月 + 事前リサーチ ¥600 = ¥6,600/月)。 API + Slack Webhook で既存の業務フローに連携でき、採択後の日程通知フローにも組み込めます。

- 1 顧問先 = ¥30/月 (10 units × ¥3)
- 併用ルール 181 本で申請前の確認リスクを機械検出
- CSV 一括判定 + 保存検索の月次自動実行

[補助金コンサル向け → ](/audiences/subsidy-consultant.html)

### 中小企業 (相談前プレ診断)

Web で確認、通知はメールで受け取る

小規模事業向けの相談前プレ診断。今すぐ使う導線は Playground / API / Widget です。保存検索・締切リマインド・相談パック更新はメール通知から始められます。

- 一次資料・未確認点・専門家への質問を整理
- 保存検索と締切通知はメールで受け取れる
- 現行の無料枠と料金は Pricing で確認

[中小企業 向け詳細 → ](/audiences/smb.html)

### 信用金庫・商工会

高品質制度 1,454 件 + 公庫融資

品質ラベル S (厳選 114 件) + A (高品質 1,340 件) = 1,454 件の高品質制度 。 経営相談の場で 「お客様向けに今月使える制度」 を日次で抽出。 締切カレンダーと組み合わせれば、 期限切れ前の制度だけを毎朝抽出できます。

- 制度の品質ラベル: S 厳選 114 件 + A 高品質 1,340 件
- 融資商品 108 件 (担保・個人保証人・第三者保証人で分類)
- 勉強会用の検索ウィジェット 埋込 (通常 1 検索 = 1 課金単位、税別 ¥3 / 税込 ¥3.30、 サイト訪問者の検索ごと従量)

[信金・商工会向け → ](/audiences/admin-scrivener.html)

### 業種別パック (建設 / 製造 / 不動産)

日本標準産業分類で絞り込み、 1 リクエストにまとめ取得

建設業・製造業・不動産業に特化したまとめ取得。 業種別の補助金・通達・国税不服審判所 裁決事例を通常 1 call = 1 課金単位でまとめて更新します。 業界誌の特集ページや、 士業のクライアント提案資料が短時間で揃います。

- 建設業 36 件 + 製造業 71 件 + 不動産業 9 件
- 1 リクエストで 補助金 上位 10 件 + 裁決事例 5 件 + 通達 3 件
- 専門業務・申請代行ではないことをレスポンスで明示

[建設 ](/audiences/construction.html)· [製造 ](/audiences/manufacturing.html)· [不動産 ](/audiences/real_estate.html)

### AI 開発者 (横断利用)

REST + MCP、 151 機能、 SDK 不要

上記すべての利用者層を、 1 つのサーバーから呼べます。 MCP プロトコル準拠、 uvx 1 行で起動。 Evidence Packet で事前に根拠を渡し、ヒット率・追加検索回数・トークン量への影響を自社ベンチマークで測定できます。

- AI から呼べる機能 151 個 / REST 公開 OpenAPI spec
- uvx 1 行で起動 (SDK 不要)
- 無料 3 リクエスト/日で動作確認 → 商用は税込 ¥3.30 / billable unit の完全従量

[開発者向け詳細 → ](/audiences/dev.html)· [機能一覧 ](/docs/mcp-tools/)

## 登録不要で試す — 3 回の無料ライブ検証

3 回/日まで無料、 API キー不要。 1 回目で制度候補、 2 回目で Evidence Packet と事前算出バンドル、 3 回目で入力文脈の参考比較を確認します。

### 1 回目: 制度候補と出典 URL を確認

curl 'https://api.jpcite.com/v1/programs/search?q=IT%E5%B0%8E%E5%85%A5&limit=3' コピー

source_url · source_fetched_at · 品質 tier が返ります。

### 2 回目: Evidence Packet (precomputed) を 1 リクエストで取得

curl 'https://api.jpcite.com/v1/intelligence/precomputed/query?q=%E7%9C%81%E5%8A%9B%E5%8C%96&limit=5' コピー

事前計算済み Evidence Packet を返します。 LLM 呼び出しもライブの Web 検索も行われません。 呼び出し元が比較基準を指定しない限り、 cost delta は表示されません。

### 3 回目: 入力文脈の削減率と採算ライン到達 (break-even) 判定を返す

curl 'https://api.jpcite.com/v1/intelligence/precomputed/query?q=%E7%9C%81%E5%8A%9B%E5%8C%96&limit=5&source_tokens_basis=pdf_pages&source_pdf_pages=30&input_token_price_jpy_per_1m=300' コピー

source_url ・ source_fetched_at ・ known_gaps は Evidence Packet に含まれ、比較基準を渡した場合だけ input-context estimates (入力文脈の削減率、 採算ライン到達 (break-even) 判定、 AI 向け推奨フラグ) を参考値として返します。

ブラウザ完結なら [Playground で3回検証を始める ](/playground.html?flow=evidence3)· 詳細手順は [5 分クイックスタート ](/docs/getting-started/)。 Claude Desktop / Cursor / Cline からも同じ endpoint を呼べます。

AI ツール統合の例 → [Claude Desktop ](/integrations/claude-desktop.html)· [Cursor ](/integrations/cursor.html)· [Cline ](/integrations/cline.html)

これは検索インデックスです。 法律相談 / 税務相談 / 申請代行は提供しません。 詳細は [error_handling ](/docs/error_handling/)· [pricing ](/docs/pricing/)· [利用規約 ](tos.html)。

## 制度プレスクリーン — 3 問で 上位 5 件

都道府県・事業形態・予定投資額を入れるだけで、 11,601 制度 から適合度の高い 上位 5 件 を表示します。無料・登録不要・匿名 3 リクエスト/日/IP。 入力 1 回で結果が返ります。

企業 URL (空欄のまま送信してください)

都道府県 * 全国 (指定なし) 北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県 「全国」を選ぶと地域条件を外して全制度から検索します。都道府県を選ぶと、その県専用制度＋全国制度の両方が候補になります。

事業形態 指定なし 法人 個人事業主 「指定なし」だと両方を含む制度のみヒット。「法人」「個人事業主」を選ぶと専用制度＋共通制度を表示。

予定投資額 (万円) 設備・システム導入などの予定投資額（万円単位、空欄可）。例: 800 = 800 万円。投資額に応じた上限額の制度を上位に並べます。
上位 5 件を見る

回答は AI ではなく、制度データベースから規則ベースでマッチングします (prefecture + target_types + amount_fit)。出典 URL は一次資料を優先。送信内容は保存しません。レート制限のため IP ハッシュのみ記録 (JST 翌日リセット)。

## ChatGPT / Claude と何が違う?

AI は文章を作れます。jpcite は回答を作るのではなく、AI に渡す根拠・出典・既知の欠落を短い資料パケットとして返します。

### 検索前に根拠が整っている

URL・取得時刻・スナップショット ID

AI の Web 検索は探索に向いています。一方、制度判断では「どの一次資料を、いつ取得したデータで見たか」が重要です。jpcite は出典 URL、出典取得時刻、本文ハッシュ、データスナップショット ID をまとめて返し、後から同じ根拠を追跡できます。

### 渡す根拠を先に絞り込める

PDF 全文投入の前段に置く

公募要領や関連ページをそのまま LLM に読ませると入力が膨らみます。jpcite は制度名、対象、金額、締切、出典、既知の欠落を先に構造化して返すため、LLM には必要な根拠だけを渡せます。削減率はモデルと質問に依存するため固定保証はしません。

### 併用可否を同じ形で返す

推論ではなくルール照合

「補助金 A と B を同時に使えるか」は文章のうまさでは決まりません。jpcite は 181 本の 併用不可 / 前提制度 ルールを照合し、同じ入力には同じ結果と根拠を返します。

つまり: AI が書く。jpcite が裏取り材料を渡す。 文章生成はお使いの AI に任せ、出典・取得時刻・ルール判定・既知の欠落を jpcite が短く返します。

## なぜ jpcite か — 税込 ¥3.30/unit の中身

通常 1 call = 1 課金単位、税込 ¥3.30 は、 (a) 複数 DB の横断取得 + (b) 一次資料エビデンス + (c) 鮮度メタデータ をワンコールで提供する対価です。 自前で同等のものを組むと、 公開サイトのスクレイピング・正規化・差分検出・出典管理を継続運用する必要があります。

### (a) 複数 DB を 1 コール で統合

補助金 11,601 + 法令 9,484 + 税制 50 + 法人 167K + 行政処分 1,185

補助金・法令メタデータと法令本文・税制ルールセット・国税庁適格事業者・行政処分・判例・採択事例・融資情報を一つの API で横断検索。 関係抽出データベースも MCP ツールから呼び出せます。

### (b) 出典 URL + 取得時刻 + content_hash 付エビデンス

主要公開レコードに一次資料 URL と取得時刻を付与

出典は省庁・都道府県・政府系金融機関・商工会などの一次 URL を優先します。 二次集約サイトは出典に登録しません。 出典 URL + 取得時刻 + content_hash がそろうため、 「なぜこの制度がヒットしたか」を顧客・監督官庁・相手方に客観的に説明する記録へ転記しやすくなります。 未接続の根拠は known gaps として明示します。 詳細は [透明性レポート ](/transparency.html)。

### (c) 鮮度メタデータ — 中央値 7 日 / 半減期 7 日未満

毎日 出典 URL 死活監視 + 法令差分日次走査

出典の最終取得日は中央値 7 日 (50% の行は直近 7 日以内に再取得)、 鮮度の半減期は 7 日未満。 「最終更新」のような誤誘導はせず、 取得した日 (出典取得) として開示します。 毎晩、 出典 URL の死活監視を自動実行し、 法改正の差分は日次走査。 締切間近の制度・廃止された URL は鮮度メタデータで識別できます。 鮮度の現状は [データ鮮度ページ ](/data-freshness.html)で公開。

### 排他ルールを機械照合 (¥3 に同梱)

181 本の 併用不可 / 前提制度 / 絶対要件 を機械照合

制度 ID 一覧を投げた時点で、 併用不可候補・前提不足候補を返却。 AI の「それっぽい」推論ではなく、 構造化済みルール 181 本 (併用不可 125 + 前提 17 + 絶対要件 15 + その他 24) に照らして確認候補を示します。申請前に確認すべき併用リスクを見つけやすくします。

### 横断連結を 1 リクエストで

制度 → 法令 → 判例 → 行政処分 → 適格事業者

trace_program_to_law ・ combined_compliance_check ・ search_tax_incentives ・ related_programs など 151 MCP ツールで横断解決。 補助金から関連法令・通達・裁決事例・処分歴・登録番号を 1 コールで連結します。

### 自前データ基盤を持たずに使う

スクレイパ・正規化・差分検出・出典管理

同等のデータ層を自前で組むには、 省庁・自治体・公庫の公開ページの継続収集、 スキーマ正規化、 法令改正の差分検出、 出典 URL の生存監視、 集約サイト誤掲載の排除を維持する必要があります。 jpcite は ¥3/課金単位 の従量で、 継続収集・正規化済みの evidence API として使えます。

## 誰のためか

### 開発者 / AI エンジニア

推奨: 会社フォルダ / Evidence成果物

AI agent・SaaS・社内システムに組み込みたい。OpenAPI 3.1、stdio 接続 (MCP)、¥3/課金単位 従量、登録不要の 3 リクエスト/日 で評価できる。

### 中小企業経営者

推奨: 相談前プレ診断票 + 根拠付き相談パック

自社が使える補助金を知りたい、申請まで相談したい。Playground / API で候補を見つけ、一次資料・未確認点・専門家への質問を整理して相談へ進む。保存検索と締切通知はメールで受け取れる。

### 士業 (税理士 / 社労士 / 診断士)

推奨: 法令改正アラート + 相談前プレ診断票 + 専門家登録

法改正に気づきやすくする、事務所サイトで集客、jpcite 経由で案件を受ける。 アラートは 1 通知ごと、ウィジェットは正常処理された検索リクエストごとに ¥3 従量。専門家は弁護士カテゴリを除き成約時のみ支払い。

### 事業会社 (コンプラ / 経理)

推奨: 法令改正アラート + API (社内ワークフロー)

インボイス・電帳法・景表法の変更に社内でキャッチアップ。アラートで気づき、社内ツールから API を叩いて詳細を引く。

## 料金サマリー

成果物と入口チャネルの料金サマリー

成果物/入口 無料枠 有料 税込

Evidence Packet API/MCP 3 req/日 per IP ¥ 3 / billable unit (税別) ¥ 3.30 / billable unit

メール通知チャネル 保存検索・締切リマインド 無料枠内または通常従量 通知内容により表示

法令改正アラート 月次サマリー無料 ¥3 / 通知 (税別) ¥3.30 / 通知

相談前プレ診断 (Widget入口) Widget は公開APIの匿名枠とは別 ¥3 / 正常処理された検索リクエスト (税別) ¥3.30 / 正常処理された検索リクエスト

根拠付き相談パック 相談者は直接課金なし ¥3,000 / 成約 (専門家払い、弁護士カテゴリ除く) ¥3,300 / 成約

[料金を計算する → ](pricing.html)

## お知らせ & 更新

### 製品の変更履歴 (Changelog)

API / MCP / SDK のバージョン更新内容。Keep a Changelog 1.1.0 + Semantic Versioning 2.0.0 準拠、 BREAKING: の接頭辞で互換性破壊を明示。

[Changelog を見る → ](/changelog/)

### 制度変更検出フィード

補助金・税制・認定制度などの 適用条件 差分を毎日 定期処理 で検出して公開する 追記専用 フィード。 RSS / JSON 提供、 CC-BY-4.0 (差分メタデータ)。

[制度変更検出フィードを見る → ](audit-log.html)

## すぐ動かしてみる

登録不要・ 3 リクエスト/日 まで無料。 Claude Desktop / Cursor から uvx 1 行で。

[スタートガイド → ](/docs/getting-started/)· [curl で試す → ](#curl-try)
