---
source_html: pricing.html
brand: jpcite
canonical: https://jpcite.com/pricing.html
fetched_at: 2026-05-14T12:37:46.667530+00:00
est_tokens: 2378
token_divisor: 4
license: see https://jpcite.com/tos
---

# pricing.html

[メインコンテンツへスキップ / Skip to main content ](#main)

[](index.html)

最初の 3 req は ¥0 から始められます

登録なし・カード不要。匿名 3 req/日 per IP の無料枠で [playground ](/playground.html?flow=evidence3)から本番 API を直接試せます。気に入ったら [4 step オンボーディング ](/onboarding.html)でサインイン、課金設定、API 呼出と進めます。

→ 次のアクション: [はじめての方ガイド (4 step) ](/onboarding.html)· [3 req 無料で試す ](/playground.html?flow=evidence3)

# ¥3/billable unit metered (税込 ¥3.30)

Stripe 経由・completely_metered・月額 minimum なし・tier なし。匿名 3 req/日 per IP は登録不要で無料 (JST 翌日 00:00 リセット)。

AI agent (Custom GPT / Claude MCP / Cursor / Codex / Anthropic API direct) が日本公的制度・法令・判例・税務・適格事業者を扱う前に呼ぶ Evidence prefetch layer。通常の単発 API/MCP 呼び出しは 1 billable unit、batch/export は事前表示の式で算出します。jpcite 側は LLM 推論を一切しないため、agent dev の自前 LLM token と完全独立で jpcite の単価は固定式です。反復実行では月次上限・X-Cost-Cap-JPY・X-Client-Tag を組み合わせ予算と顧客別原価を管理できます。

## 長文資料を毎回 LLM に渡す場合との費用比較式

LLM に資料 chunk を毎回読ませる場合、費用は 投入 tokens × 利用モデルの input 単価 + output tokens です。jpcite を挟む場合、費用は jpcite ¥3/billable unit + Evidence Packet を読む少量 tokens です。

- 数十ページの公的資料を毎回投げる反復 agent では、入力 token と遅延を下げやすい設計です。
- 1 回だけの軽い質問、短い 1 ページ確認、無料検索で足りる内容では、jpcite を挟まない方が安い場合があります。
- モデル単価は外部 LLM 側で変動します。jpcite は根拠取得部分を ¥3/billable unit に固定し、LLM 推論費と分けて管理できます。

月の利用量 請求額 (税込)

月 100 units ¥330

月 1,000 units ¥3,300

月 10,000 units ¥33,000

月 100,000 units ¥330,000

[3回の無料ライブ検証を始める → ](/playground.html?flow=evidence3)[API キー発行 (¥3.30/unit) → ](#api-paid)

REST のお試し画面: [playground ](playground.html)· 月額シミュレーション: [calculator ](/calculator.html)

## cost examples — AI agent 経由 5 シナリオ

.well-known/mcp.json の cost_examples に対応する 5 シナリオ。AI agent (Claude / GPT / Cursor) 経由で jpcite を呼んだ際の典型 req 数 と税込課金。実行前見積もりは POST /v1/cost/preview で確認できます。

会社フォルダ Brief / Pack

1 unit / Brief preview

company_folder_brief は税込 ¥3.30 の単発 preview。複数 section を束ねる Pack workflow は、法人同定 + invoice + 採択 + 行政処分 + source_receipts + known_gaps の実行前見積もり units で課金されます。

顧問先月次レビュー (100 社)

¥5,940 / 月

1,800 req × ¥3.30。 X-Client-Tag で顧問先別原価集計、税理士法 §52 fence 自動。

一括 1000 案件 triage

¥52,800 / 月

16,000 req × ¥3.30。1 案件 ¥52.80 で公的 DD layer。 Idempotency-Key で再送安全。

公開情報 DD (200 社)

¥31,020 / 月

9,400 req × ¥3.30。M&A advisor の公開情報 DD evidence packet / question checklist、弁護士法 §72 fence 同梱。

相談前プレ診断 (50 件)

¥1,320 / 月

400 req × ¥3.30。事前リサーチ + 候補制度 + 排他確認を AI agent から自動。

業種別の request 数と料金例は [業種別 use case (税理士・会計士・行政書士・診断士・M&A・信金) ](/audiences/)・課金根拠は [justification ](/docs/pricing/)・月額シミュレーションは [calculator ](/calculator.html)・前提付きの入力文脈比較は [Evidence cost calculator ](/tools/cost_saving_calculator.html)。

入力文脈量の参考比較 — stated baseline (2026-05-12 公開単価)

baseline は Claude Sonnet 4.5 ($3 / $15 per MTok)、Anthropic web search ($10/1k)、USD/JPY=150、下記 use case の token/search 回数です。この条件で「長文資料・検索結果を毎回 AI に渡す場合」と「jpcite の Evidence Packet を先に読む場合」の API fee delta だけを比較し、入力文脈と検索呼び出しの節約余地を示します。外部 provider の token + search API fee と jpcite fee 以外は含みません。

- 1 case あたりの参考: external provider API fee ¥51-¥136.50 / jpcite metered fee ¥6-¥15
- 6 use case (M&A DD / 補助金抽出 / 税理士措置法 / 行政書士許認可 / 信金マル経 / dev 試作) 合計参考: external provider API fee ¥528 / jpcite fee ¥51 / API fee delta ¥477
- 同じ baseline で use case #3 を 100 回反復する参考: external provider API fee ¥7,650 / jpcite fee ¥600 / monthly API fee delta ¥7,050 / annualized reference ¥84,600
- 同じ確認を反復する業務では、Evidence Packet を先に読むことで入力文脈を小さくできます。ただし安くなるかは model、cache、prompt、検索回数に依存します。

計算式・前提は [Evidence cost calculator ](/tools/cost_saving_calculator.html)で確認できます。実請求額は provider、model、cache、tool 設定、為替、prompt に依存します。業務効果、売上、利益、専門判断の価値は含みません。

## jpcite vs web search — 構造比較

AI agent から web search で公的制度を扱う場合、aggregator 孫引き・fetched_at 不明・業法 fence なしの結果は追加確認が必要です。jpcite 税別 ¥3/billable unit は出典固定 + 業法 fence + 監査対応の対価です。

軸 web search (Perplexity / Tavily / Exa / 一般 SERP) jpcite (税別 ¥3/billable unit)

出典 URL aggregator (noukaweb / hojyokin-portal / biz.stayway) 経由が上位、孫引きで旧版要件ミラー 省庁・自治体・公庫の一次 URL に直リンク。aggregator は source_url 登録 ban

取得時刻 HTML に fetched_at なし。サイト自己申告「最終更新」のみ 主要な公開検索 / Evidence response で source_fetched_at を返します。値は jpcite の取得・構造化時刻であり、一次情報源の公表日・更新日・有効期限を示すものではありません。

業法 fence 一般的な web search では、専門判断に必要な注意書きや業法上の境界表示が応答ごとに揃わない場合があります 税務・法律・申請・監査・与信前確認などの sensitive surface では、対象領域に応じた 8 業法 fence note を返す設計です

排他 / 前提ルール LLM 推論だけでは同時利用可否の根拠確認が必要 181 ルール (排他 125 + 前提 17 + 絶対 15 + その他 24) を機械照合、AI 推論不要

監査 / 顧問先説明 URL のみ、content_hash / corpus_snapshot_id なし content_hash や corpus_snapshot_id など、利用可能な範囲の再確認用メタデータを返します。監査・DD では一次資料と専門家レビューを併用してください

100 req コスト caller 側の LLM token / web search / cache 条件に依存。出典確認を multi-turn で行う場合は provider 側の課金単位も確認が必要 ¥330 (税込)。出典 URL・取得時点・known gaps・業法 fence を同じ envelope で返却。広い実行は /v1/cost/preview と X-Cost-Cap-JPY で事前に上限を設定

## 成果物の反復運用では、先に上限を決める

AI agent / 士業システム / 社内ワークフローで反復利用する場合は、会社フォルダ、顧問先レビュー、申請前 Evidence Packet、公開情報 DD packet ごとに、実行前見積もり、月次上限、実行単位の予算、顧客別タグを設定してください。通常の単発 API/MCP 呼び出しは 1 billable unit = 税込 ¥3.30、batch / export / fanout は見積もり表示の units で課金されます。

1. 無料見積もり

/v1/cost/preview で batch / export / fanout の予測 units と金額を先に確認。見積もり自体は匿名 3 回枠を消費しません。

2. 実行時の上限

有料 POST は X-Cost-Cap-JPY と Idempotency-Key で予算超過と二重課金を抑制。

3. 顧客別の原価管理

X-Client-Tag で会社フォルダ、 顧問先、 案件ごとの利用量を分けて追跡。

成果物ワークフロー例 月間 units の目安 税込目安

顧問先月次レビュー: 50 社を月 10 回確認 500 units ¥1,650

申請前 Evidence Packet: 受付案件 200 件を 3 call で一次整理 600 units ¥1,980

AI agent: 20 users が営業日ごとに 10 evidence artifacts 約 4,000 units 約 ¥13,200

## 無料 3 回で確認すること

匿名 3 リクエスト/日 (IP 単位、 JST 翌日 00:00 リセット) の代表的な検証フローで、 課金前に下の 5 点を確認できます。 source_url、 source_fetched_at、 known_gaps、 確認範囲を見て、 継続利用や MCP / OpenAPI への組み込みに進むか判断できます。

確認項目 どこで返るか

1. 出典 URL がある 主要な公開検索 / Evidence response の source_url を確認します。 まとめサイト経由ではなく、 省庁 / 自治体 / 公庫の一次資料に直リンクしているか目視確認します。

2. source_fetched_at がある 最終更新ではなく jpcite が出典を最後に取得した時刻 。 古い出典や per-source 内訳は [データ鮮度 ](data-freshness.html)で確認できます。

3. Evidence Packet で quality.known_gaps を確認できる Evidence / intelligence response では、未接続 / 未取得 / 未抽出の領域を known gaps として返します。 「何を知らないか」 が分かることで、 AI が引用時に過剰主張せずに済みます。

4. packet tokens vs baseline 比較が返る GET /v1/intelligence/precomputed/query に source_tokens_basis=pdf_pages + source_pdf_pages + input_token_price_jpy_per_1m を渡すと、 compression.packet_tokens_estimate · compression.source_tokens_estimate · compression.input_context_reduction_rate が返ります。 caller baseline が無いと cost 比較は出ません。

5. recommend_for_cost_savings が true になる条件 caller baseline + 入力 token 単価が揃い、 break_even_met=true (avoided_tokens × 単価 ≥ ¥3) を満たした時のみ agent_recommendation.recommend_for_cost_savings=true 。 baseline 未指定なら必ず false で cost_savings_decision=needs_caller_baseline を返します。

break_even_met の正しい読み方: これは入力文脈量の参考比較だけです。 出力 tokens、 reasoning tokens、 cache、 provider tool / search 料金、 為替、 外部 LLM 側の請求仕様は含みません。 詳細は [docs/pricing ](/docs/pricing/)をご覧ください。

[Playground で 3 回検証する → ](/playground.html?flow=evidence3)[5 分クイックスタート → ](/docs/getting-started/)

## ¥3/billable unit の根拠 — 価値統合の 3 軸

通常 call 1 unit の ¥3 (税込 ¥3.30) は、 単発の検索結果ではなく 複数 DB を結合した監査対応形式の応答 の対価です。batch/export は事前表示の billable units 式で計算します。LLM API 利用料ではなく、 統合 + 出典 + 鮮度の 3 軸で正当化されます。

1. 複数 DB 統合

複数データセットを通常 call 1 unit で結合

制度 / 法令 / 法人 / 行政処分 / 採択事例を結合した一貫レコードを返却。 個別データソースを叩いて自前で結合する手間が不要です。

2. 一次出典 + 監査対応

URL + content_hash + fetched_at

主要レコードに官公庁・公庫・地方自治体の一次 URL を付与。 取得時刻と内容ハッシュも同梱するため、 監査・DD・顧問先説明用の記録に転記しやすい形で扱えます。 民間まとめサイトへの孫引きはしません。

3. 鮮度 + コスト決定性

鮮度分布は live 開示

出典の取得日は行ごとに返却し、現在の鮮度分布は [データ鮮度 ](data-freshness.html)で公開します。 税込 ¥3.30/unit は jpcite の billable API/MCP call 単価です。通常 call は 1 unit です。 外部 LLM 側の token / search / cache / tool cost は利用者のモデル設定に依存します。

詳細は [データ鮮度 ](data-freshness.html)・ [出典一覧 ](sources.html)・ [信頼センター ](trust.html)をご覧ください。

## Evidence Packet の入力文脈節約 calculator (参考値)

ソース PDF / トークン量 と 外部 LLM の 入力 token 単価 (¥/1M) を入力すると、 jpcite Evidence Packet で 圧縮される入力 tokens、 jpcite 1 unit コスト、 入力文脈 break-even を ブラウザ内で 算定します。 fetch なし、 LLM 呼び出しなし。 外部 LLM の 出力 tokens / reasoning tokens / cache / provider tool / search / 為替 は本計算に含まれません — 入力文脈の参考比較のみです。

ソース PDF ページ数 片方だけ入力。 両方入れた場合 token 数を優先。

またはソース token 数 直接 token 数 (1 ページ ≒ 700 token 換算)

入力 token 単価 (¥/1M) 外部 LLM の 入力 token 価格 (例 Claude Opus ≒ ¥2,250)

jpcite packet token (推定) 例: 1,500 token。実測値は用途とベンチ条件で変動

ソース token 推定

—

圧縮される入力 tokens (参考)

—

jpcite 1 unit コスト (税別)

¥3.00

入力文脈 break-even

—

入力に応じて更新

免責: 本計算は 入力文脈 (input tokens) のみの参考比較です。 外部 LLM の token / search / cache / tool 料金、 出力 tokens、 reasoning tokens、 為替、 prompt scaffold、 cache hit rate、 provider 側 web search 課金は含まれません。 これは外部 LLM 請求額の削減額表示ではなく、caller baseline 条件下の入力文脈比較です。 差額はワークロード・モデル・プロンプト・キャッシュ状態で大きく変動します。 ベンチ手順は [bench methodology ](/benchmark/)をご参照ください。

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

ダッシュボードから Stripe Customer Portal を開いてキャンセルできます。キャンセル後も当月末までは API アクセス可能で、当月利用分のみ ¥3/billable unit 従量請求が発生します。API キーの無効化・削除・ローテーションは当該キーの利用停止であり、課金契約の解約には該当しません。次月以降の課金は停止します。解約違約金・最低利用期間はありません。
返金はありますか?

役務提供開始後の通常利用分は返金対象外です。ただし、重複請求、単価・unit 式の誤適用、成立していないリクエストへの課金、または重大な不適合により課金が発生した場合は、調査のうえ返金または次月請求からの減額で対応します。
予算上限を設定できますか?

はい。 ダッシュボードで月額上限を任意の円額で設定可能。 設定額に達した場合、次の JST 月次請求サイクルまで API は cap_reached で停止します。 広い batch / fanout では request 単位の X-Cost-Cap-JPY 、POST 再試行には Idempotency-Key 、顧客・案件別の集計には X-Client-Tag も併用できます。
