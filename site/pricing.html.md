---
source_html: pricing.html
brand: jpcite
canonical: https://jpcite.com/pricing.html
fetched_at: 2026-05-11T10:54:09.819404+00:00
est_tokens: 2242
token_divisor: 4
license: see https://jpcite.com/tos
---

# pricing.html

[メインコンテンツへスキップ / Skip to main content ](#main)

[](index.html)

# ¥3/req metered (税込 ¥3.30) 

Stripe 経由・completely_metered・月額 minimum なし・tier なし。匿名 3 req/日 per IP は登録不要で無料 (JST 翌日 00:00 リセット)。 

AI agent (Custom GPT / Claude MCP / Cursor / Codex / Anthropic API direct) が日本公的制度・法令・判例・税務・適格事業者を扱う前に呼ぶ Evidence prefetch layer。1 API/MCP 呼び出し = 1 billable unit。jpcite 側は LLM 推論を一切しないため、agent dev の自前 LLM token と完全独立で jpcite の単価は固定式です。反復実行では月次上限・X-Cost-Cap-JPY・X-Client-Tag を組み合わせ予算と顧客別原価を管理できます。 

月の利用量 請求額 (税込) 

月 100 units ¥330 

月 1,000 units ¥3,300 

月 10,000 units ¥33,000 

月 100,000 units ¥330,000 

[3回の無料ライブ検証を始める → ](/playground.html?flow=evidence3)[API キー発行 (¥3.30/unit) → ](#api-paid)

REST のお試し画面: [playground ](playground.html)· 月額シミュレーション: [calculator ](/calculator.html)

## cost examples — AI agent 経由 5 シナリオ 

.well-known/mcp.json の cost_examples に対応する 5 シナリオ。AI agent (Claude / GPT / Cursor) 経由で jpcite を呼んだ際の典型 req 数 と税込課金。実行前見積もりは POST /v1/cost/preview で確認できます。 

会社フォルダ作成パック 

¥59.40 / 1 社 

18 req × ¥3.30。法人番号 1 つで法人同定 + invoice + 採択 + 行政処分 + known_gaps を bundle。 

顧問先月次レビュー (100 社) 

¥5,940 / 月 

1,800 req × ¥3.30。 X-Client-Tag で顧問先別原価集計、税理士法 §52 fence 自動。 

BPO 1000 案件 triage 

¥52,800 / 月 

16,000 req × ¥3.30。1 案件 ¥52.80 で公的 DD layer。 Idempotency-Key で再送安全。 

公開情報 DD (200 社) 

¥31,020 / 月 

9,400 req × ¥3.30。M&A advisor の DD deck assembly、弁護士法 §72 fence 同梱。 

相談前プレ診断 (50 件) 

¥1,320 / 月 

400 req × ¥3.30。事前リサーチ + 候補制度 + 排他確認を AI agent から自動。 

詳細 ROI 倍率は [業種別 use case (税理士・会計士・行政書士・診断士・M&A・信金) ](/docs/use_cases/by_industry_2026_05_11.md)・課金根拠は [justification ](/docs/pricing/justification_2026_05_11.md)。 

## jpcite vs web search — 構造比較 

AI agent から web search で公的制度を扱うと、aggregator 孫引き・fetched_at 不明・業法 fence なしで業務利用に耐えません。jpcite ¥3/req は出典固定 + 業法 fence + 監査対応の対価です。 

軸 web search (Perplexity / Tavily / Exa / 一般 SERP) jpcite (¥3/req) 

出典 URL aggregator (noukaweb / hojyokin-portal / biz.stayway) 経由が上位、孫引きで旧版要件ミラー 省庁・自治体・公庫の一次 URL に直リンク。aggregator は source_url 登録 ban 

取得時刻 HTML に fetched_at なし。サイト自己申告「最終更新」のみ 全 response に source_fetched_at 、優先出典の再取得中央値 約 7 日 

業法 fence なし — 個別税務助言 / 監査意見 / 申請書面 / 登記代理を平気で生成 → 業法抵触リスク 8 業法 fence (税理士§52 / 弁護士§72 / 公認会計士§47条の2 / 司法書士§3 / 行政書士§1 / 社労士§27 / 中小企業診断士登録規則 / 弁理士§75) を envelope 自動付与 

排他 / 前提ルール LLM 推論で「同時利用できそう」を hallucinate 181 ルール (排他 125 + 前提 17 + 絶対 15 + その他 24) を機械照合、AI 推論不要 

監査 / 顧問先説明 URL のみ、content_hash / corpus_snapshot_id なし content_hash + corpus_snapshot_id + Merkle proof で再現可能性 

100 req コスト ¥10-100 程度の LLM token 課金。安いが取りこぼし確率高、顧問契約解除 ¥36-120万/年 リスク ¥330 (税込)。取りこぼし回避で 1,000-3,600 倍 ROI 

## 成果物の反復運用では、先に上限を決める 

AI agent / BPO / 士業システムで反復利用する場合は、 会社フォルダ、 顧問先レビュー、 申請戦略パック、 公開情報DDパックごとに、 実行前見積もり、 月次上限、 実行単位の予算、 顧客別タグを設定してください。 価格は通常 1 API/MCP 呼び出し = 1 billable unit = 税込 ¥3.30 です。 

1. 無料見積もり 

/v1/cost/preview で batch / export / fanout の予測 units と金額を先に確認。見積もり自体は匿名 3 回枠を消費しません。 

2. 実行時の上限 

有料 POST は X-Cost-Cap-JPY と Idempotency-Key で予算超過と二重課金を抑制。 

3. 顧客別の原価管理 

X-Client-Tag で会社フォルダ、 顧問先、 案件ごとの利用量を分けて追跡。 

成果物ワークフロー例 月間 units の目安 税込目安 

顧問先月次レビュー: 50 社を月 10 回確認 500 units ¥1,650 

申請戦略パック: 受付案件 200 件を 3 call で一次整理 600 units ¥1,980 

AI agent: 20 users が営業日ごとに 10 evidence artifacts 約 4,000 units 約 ¥13,200 

## 無料 3 回で確認すること 

匿名 3 リクエスト/日 (IP 単位、 JST 翌日 00:00 リセット) の代表的な検証フローで、 課金前に下の 5 点を確認できます。 source_url、 source_fetched_at、 known_gaps、 確認範囲を見て、 継続利用や MCP / OpenAPI への組み込みに進むか判断できます。 

確認項目 どこで返るか 

1. 出典 URL がある 主要な公開検索 / Evidence response の source_url を確認します。 まとめサイト経由ではなく、 省庁 / 自治体 / 公庫の一次資料に直リンクしているか目視確認します。 

2. source_fetched_at がある 最終更新ではなく jpcite が出典を最後に取得した時刻 。 優先度の高い出典の再取得中央値は約 7 日で、 古ければ [データ鮮度 ](data-freshness.html)で per-source 内訳を確認できます。 

3. Evidence Packet で quality.known_gaps を確認できる Evidence / intelligence response では、未接続 / 未取得 / 未抽出の領域を known gaps として返します。 「何を知らないか」 が分かることで、 AI が引用時に過剰主張せずに済みます。 

4. packet tokens vs baseline 比較が返る GET /v1/intelligence/precomputed/query に source_tokens_basis=pdf_pages + source_pdf_pages + input_token_price_jpy_per_1m を渡すと、 compression.packet_tokens_estimate · compression.source_tokens_estimate · compression.input_context_reduction_rate が返ります。 caller baseline が無いと cost 比較は出ません。 

5. recommend_for_cost_savings が true になる条件 caller baseline + 入力 token 単価が揃い、 break_even_met=true (avoided_tokens × 単価 ≥ ¥3) を満たした時のみ agent_recommendation.recommend_for_cost_savings=true 。 baseline 未指定なら必ず false で cost_savings_decision=needs_caller_baseline を返します。 

break_even_met の正しい読み方: これは入力文脈量の参考比較だけです。 出力 tokens、 reasoning tokens、 cache、 provider tool / search 料金、 為替、 外部 LLM 側の請求仕様は含みません。 詳細は [docs/pricing ](/docs/pricing/)をご覧ください。 

[Playground で 3 回検証する → ](/playground.html?flow=evidence3)[5 分クイックスタート → ](/docs/getting-started/)

## ¥3/unit の根拠 — 価値統合の 3 軸 

通常 call 1 unit の ¥3 (税込 ¥3.30) は、 単発の検索結果ではなく 複数 DB を結合した監査対応形式の応答 の対価です。batch/export は事前表示の billable units 式で計算します。LLM API 利用料ではなく、 統合 + 出典 + 鮮度の 3 軸で正当化されます。 

1. 複数 DB 統合 

複数データセットを通常 call 1 unit で結合 

制度 / 法令 / 法人 / 行政処分 / 採択事例を結合した一貫レコードを返却。 個別データソースを叩いて自前で結合する手間が不要です。 

2. 一次出典 + 監査対応 

URL + content_hash + fetched_at 

主要レコードに官公庁・公庫・地方自治体の一次 URL を付与。 取得時刻と内容ハッシュも同梱するため、 監査・DD・顧問先説明用の記録に転記しやすい形で扱えます。 民間まとめサイトへの孫引きはしません。 

3. 鮮度 + コスト決定性 

再取得中央値は約 7 日 

優先度の高い出典の再取得中央値は約 7 日です。 税込 ¥3.30/unit は jpcite の billable API/MCP call 単価です。通常 call は 1 unit です。 外部 LLM 側の token / search / cache / tool cost は利用者のモデル設定に依存します。 

詳細は [データ鮮度 ](data-freshness.html)・ [出典一覧 ](sources.html)・ [信頼センター ](trust.html)をご覧ください。 

## 入力文脈 break-even calculator (参考値) 

ソース PDF / トークン量 と 外部 LLM の 入力 token 単価 (¥/1M) を入力すると、 jpcite Evidence Packet で 削減見込みのある 入力 tokens、 jpcite 1 unit コスト、 入力文脈 break-even を ブラウザ内で 算定します。 fetch なし、 LLM 呼び出しなし。 外部 LLM の 出力 tokens / reasoning tokens / cache / provider tool / search / 為替 は本計算に含まれません — 入力文脈の参考比較のみです。 

ソース PDF ページ数 片方だけ入力。 両方入れた場合 token 数を優先。 

またはソース token 数 直接 token 数 (1 ページ ≒ 700 token 換算) 

入力 token 単価 (¥/1M) 外部 LLM の 入力 token 価格 (例 Claude Opus ≒ ¥2,250) 

jpcite packet token (推定) 例: 1,500 token。実測値は用途とベンチ条件で変動 

ソース token 推定 

— 

削減見込み 入力 tokens 

— 

jpcite 1 unit コスト (税別) 

¥3.00 

入力文脈 break-even 

— 

入力に応じて更新 

免責: 本計算は 入力文脈 (input tokens) のみの参考比較です。 外部 LLM の token / search / cache / tool 料金、 出力 tokens、 reasoning tokens、 為替、 prompt scaffold、 cache hit rate、 provider 側 web search 課金は含まれません。 これは外部 LLM 請求額の削減保証ではなく、caller baseline 条件下の入力文脈比較です。 削減効果はワークロード・モデル・プロンプト・キャッシュ状態で大きく変動します。 ベンチ手順は [bench methodology ](/benchmark/)をご参照ください。 

## クレジットパック — 匿名 3 req/日 超過時の選択肢 

匿名 3 req/IP/日 の無料枠を超えた時、 サブスクリプション (API キー) を作らずに買い切りで追加リクエストを購入できる ad-hoc クレジットパック。 単価は ¥3/req 据え置き、 パック内割引なし、 解約手続き不要。 階層プランではなく、 完全従量の補助路です。 

クレジットパック 100 req 

¥300 (税別) 

100 req 分 / ¥3.00 per req 据え置き。 Stripe Checkout で 1 分入金。 

クレジットパック 500 req 

¥1,500 (税別) 

500 req 分 / ¥3.00 per req 据え置き。 パック内割引なし、 階層なし。 

クレジットパック 1,000 req 

¥3,000 (税別) 

1,000 req 分 / ¥3.00 per req 据え置き。 法人 / 個人どちらでも適格請求書発行。 

取得方法: POST /v1/billing/credit/anon/purchase で Stripe Checkout URL を取得 → 入金後にクレジットコードが発行され、 X-Credit-Pack ヘッダで以降の req に充当。 サブスクリプション (¥3/req metered) と並行運用可能で、 既存 API キー保有者にも公開されています。 

クレジットパックは買い切り。 期限なし、 返金なし (適格請求書 ¥X,XXX 1 本)。 残数は GET /v1/billing/credit/balance で確認できます。 

## ボリュームリベート — 月 1M req 超で自動適用 

単月で 1,000,000 billable units を超えた利用者には、 超過分について ¥0.50/req のリベートを 遡及的に Stripe Credit Note で発行 し、 翌月請求に自動充当します。 階層プラン ("最初の 1M は ¥3、 それ以降は ¥2.5" のような構造) ではありません。 全 req は一貫して ¥3 課金され、 リベートは別行で表示されます。 

月間 units 通常請求 (税別) リベート (Credit Note) 実効単価 

月 100,000 units ¥300,000 ¥0 ¥3.00 

月 1,000,000 units ¥3,000,000 ¥0 ¥3.00 

月 2,000,000 units ¥6,000,000 −¥500,000 ¥2.75 

月 5,000,000 units ¥15,000,000 −¥2,000,000 ¥2.60 

リベートは毎月 2 日 JST 03:00 (前月確定後) に scripts/cron/volume_rebate.py が自動発行。 申請不要、 連絡不要。 「階層プラン」 「年間最低利用量」 「上位プラン」 のような構造には移行しません — 単月超過時のみ発生する事後調整です。 

## 匿名 

¥0 

3 req/日、 JST 翌日 00:00 リセット 
[始める ](/docs/getting-started/)

## 従量 

¥ 3.30 / unit (税込) 

通常検索・詳細取得は 1 unit。batch/export は事前表示の式で計算。監査 workpaper など固定 export fee を含む endpoint は実行前に内訳を表示します。月額固定なし。 

反復実行では、月額上限、 X-Cost-Cap-JPY 、 Idempotency-Key 、 X-Client-Tag を組み合わせて、予算と顧客別原価を管理できます。 
[利用規約 ](tos.html)・ [プライバシー ](privacy.html)・ [特商法表記 ](tokushoho.html)に同意したうえで決済に進みます。 API キーを発行 → (¥3.30/unit 従量) 

上記にご同意いただくとボタンが有効になります。決済後、API キーを 1 回だけ表示します。利用量・請求・再発行はダッシュボードで管理できます。 

[月額をシミュレーションする → ](/calculator.html)

## よくある質問 

階層プランはないんですか? 

ありません。通常の検索・詳細取得は税込 ¥3.30 / billable unit の完全従量のみ。batch/export は ID 件数や bundle size に応じた式を事前に表示します。 
適格請求書 (インボイス) はもらえますか? 

はい。 月初に自動発行し、 ダッシュボードからダウンロードできます。 適格請求書制度に対応した請求書を発行します。 
解約手続きは? 

ダッシュボードから Stripe Customer Portal を開いてキャンセルできます。キャンセル後も当月末までは API アクセス可能で、当月利用分のみ ¥3/billable unit 従量請求が発生します。次月以降の課金は停止します。解約違約金・最低利用期間はありません。 
返金はありますか? 

従量課金のためすでに呼び出した分の返金はありません。 サービス障害による誤課金の可能性がある場合は [info@bookyou.net ](mailto:info@bookyou.net)で確認し、必要に応じて返金します。 
予算上限を設定できますか? 

はい。 ダッシュボードで月額上限を任意の円額で設定可能。 設定額に達した場合、次の JST 月次請求サイクルまで API は cap_reached で停止します。 広い batch / fanout では request 単位の X-Cost-Cap-JPY 、POST 再試行には Idempotency-Key 、顧客・案件別の集計には X-Client-Tag も併用できます。
