# jpcite 情報収集CLI-B: Output and Market Validation Loop

このファイルは、外部で立ち上げる情報収集CLIにそのまま貼る設計書です。

起動例:

```bash
cd /Users/shigetoumeda/jpcite
claude
/loop tools/offline/INFO_COLLECTOR_OUTPUT_MARKET_2026-05-06.md
```

## 役割

あなたは B2B SaaS / GovTech / AI agent 向けの市場調査・プロダクト戦略担当です。

jpcite が売るべきものは「検索結果」ではなく、ユーザーが次の業務にそのまま使える完成物です。GPT / Claude 単体の文章生成ではなく、jpcite のデータ基盤を使うから出せる深いアウトプットを定義してください。

## 最初にやること

このCLIで使える最大数のサブエージェント / worker を立ち上げ、以下の担当に分けて並列調査してください。

1. Persona research: 税理士、行政書士、補助金コンサル、金融、M&A/VC、営業BD、自治体、AI開発者
2. Artifact design: 課金される完成物テンプレート、必須フィールド、コピー可能部分
3. Competitive workflow: GPT / Claude / Perplexity / JGrants / gBizINFO / 補助金検索SaaSとの差分
4. Benchmark design: 価値を検証する比較テスト、評価指標、サンプル質問
5. Conversion and trust: 初回3回無料の体験で「得だ」と感じさせる導線、信頼表現、避ける表現

サブエージェントが使えないCLIでは、上の5担当を順番に疑似担当として処理してください。

## 書き込み許可範囲

書き込みは以下だけです。

- `tools/offline/_inbox/output_market_validation/`

禁止:

- `src/`, `tests/`, `scripts/`, `docs/`, `site/`, DBファイルの編集
- 価格変更提案を前提にすること
- 外部LLM料金削減を保証する表現
- 税務判断、法律判断、採択可否、融資可否を断定する表現
- ログイン必須・有料・非公開情報の収集

## 既存プロダクト前提

jpcite は回答生成AIではありません。GPT / Claude / Cursor / Cline / ChatGPT Custom GPT などが回答を書く前に呼ぶ Evidence Pre-fetch Layer です。

既存データ基盤:

- 補助金・融資・税制・認定: 14,472 登録、11,684 検索対象
- 採択事例: 2,286
- 融資: 108
- 行政処分: 1,185
- enforcement detail: 22,258
- 法令メタデータ: 9,484
- 法令本文DB: 6,493 法令 / 352,970 条文行
- 判例: 2,065
- 税制ルールセット: 50
- 入札: 362
- 法人マスター: 約167,000
- インボイス登録: 13,801
- AutonoMath: 503,930 entities / 6.12M facts / 177K+ relations / 335K aliases

価格・導線の前提:

- 通常検索・詳細取得は `¥3/req` 税別
- 匿名で1日3回無料
- 価格変更は今回の主目的ではない
- 目的は「初回3回で価値が伝わり、課金ユーザーが深い完成物に満足すること」

## 対象persona

必ず以下を分けて調査してください。

1. 税理士 / 会計事務所
2. 会計士 / 監査法人
3. 行政書士
4. 補助金コンサル / 認定支援機関 / 中小企業診断士
5. 金融機関 / 信金 / 地銀
6. M&A / VC / PE / DD担当
7. 営業BD / 法人営業 / パートナー開拓
8. 自治体 / 商工会 / 支援機関
9. AI agent 開発者 / RAG 開発者 / SaaS 開発者

## Persona別価値マップ

各personaについて、以下を表で整理してください。

| Persona | Current workflow | Pain | GPT/Claudeで足りる場面 | GPT/Claude単体では弱い場面 | jpcite完成物 | 支払い理由 | 導入阻害 | 初回3回で見せるもの |
|---|---|---|---|---|---|---|---|---|

必ず「競合が勝つ用途」も書いてください。競合を過小評価しないでください。

## 完成物カタログ

各personaごとに最低3つ、課金される完成物を定義してください。

完成物の候補:

- Client Evidence Brief
- 法人DD Evidence Dossier
- 補助金・融資・税制 Strategy Report
- 申請前ヒアリングシート
- 必要書類チェックリスト
- 対象外理由レポート
- 顧客CSV一括スクリーニング表
- 融資面談前 公的制度メモ
- 取引先リスク・インボイス確認シート
- 競合/提案先 企業別提案切り口シート
- 自治体向け制度棚卸し・未整備領域レポート
- Evidence Packet付き RAG評価セット

各完成物について、以下を必ず書いてください。

```json
{
  "artifact_name": "法人DD Evidence Dossier",
  "persona": "M&A/VC/DD",
  "user_input": ["houjin_bangou", "company_name"],
  "output_format": "markdown|json|csv|docx",
  "required_sections": [
    "executive_summary",
    "cross_source_signals",
    "risk_timeline",
    "public_funding_history",
    "invoice_status",
    "enforcement_history",
    "procurement_or_adoption_records",
    "source_list",
    "known_gaps",
    "human_review_questions"
  ],
  "data_joins": ["houjin_master", "invoice_registrants", "enforcement_cases", "adoption_records"],
  "copy_paste_ready_parts": ["DD質問票", "社内メモ", "顧客確認メール"],
  "human_review_required": ["最終与信判断", "法的評価"],
  "paid_reason": "手作業で複数公的DBを確認する時間を短縮し、出典付きで再確認できる"
}
```

## 標準回答構造

jpciteを使ったAI回答の標準構造を作ってください。

1. 結論候補
2. なぜ見るべきか / 見送るべきか
3. cross-source signals
4. 完成物
5. 根拠一覧
6. next actions
7. known_gaps / 確認範囲
8. 判断境界

persona別に最低1つずつ、サンプル回答の骨子を作ってください。実在制度名を使う場合は一次資料で確認できるものだけにしてください。確認できない場合は仮名にしてください。

## 満足条件 / 不満条件

満足条件:

- 最初の30秒で結論候補が見える
- 一次資料URLに戻れる
- 取得日時が分かる
- 対象外理由が分かる
- `known_gaps` が隠されていない
- 次に顧客へ聞く質問が具体的
- メール、稟議、面談メモ、DD質問票に転用できる
- 最終判断を人間に残している

不満条件:

- 候補一覧だけで終わる
- 出典URLがない
- 取得日や更新状況がない
- 過剰断定している
- 税務・法律・申請可否を断言する
- 地域・業種に合わない
- GPT / Claude の一般回答との差が見えない
- 無料の公式サイトとの差がない

## 競合比較

以下を比較してください。

- GPT / Claude / Gemini 単体
- Perplexity / Google検索
- JGrants / JGrants API / JGrants MCP
- gBizINFO
- 国税庁 適格請求書発行事業者公表サイト
- e-Gov法令検索
- TDB / TSR
- 補助金検索SaaS / 補助金ポータル
- freee / Money Forward / 会計SaaS
- 自前スクレイピング / 社内RAG

比較軸:

- 一次資料URL
- `fetched_at`
- `content_hash`
- 再現性
- 横断範囲
- 法人・制度・法令・行政処分・採択の結合
- MCP / REST API 利用
- LLM agent への組み込みやすさ
- 初回3回無料で価値が見えるか
- 競合が勝つ用途
- jpcite が勝つ用途
- 正面衝突を避けるべき用途

## 検証ベンチ

以下の3 armで比較ベンチを設計してください。

- `direct_web`: GPT/Claude + Web検索
- `jpcite_packet`: ユーザー質問 + jpcite Evidence Packet、Web検索OFF
- `jpcite_precomputed_intelligence`: 事前生成されたjpcite intelligence bundle、Web検索OFF

測定指標:

- exact_match
- citation_rate
- unsupported_claim_rate
- source_url coverage
- fetched_at coverage
- known_gaps coverage
- answer usefulness score
- time_to_first_usable_answer
- input_tokens
- output_tokens
- web_search_count
- jpcite_requests
- yen_cost_per_answer
- reviewer_minutes_saved
- copy_paste artifact completion rate

persona別に最低5問ずつベンチクエリを作ってください。

各クエリには以下を付けてください。

- query
- persona
- expected artifact
- required evidence type
- pass criteria
- fail criteria
- human reviewer checklist

## 書くべき成果物

保存先:

- `tools/offline/_inbox/output_market_validation/persona_value_map.md`
- `tools/offline/_inbox/output_market_validation/artifact_catalog.md`
- `tools/offline/_inbox/output_market_validation/competitive_matrix.md`
- `tools/offline/_inbox/output_market_validation/benchmark_design.md`
- `tools/offline/_inbox/output_market_validation/interview_questions.md`
- `tools/offline/_inbox/output_market_validation/progress.md`

## 最終回答の構成

最終回答は以下の順番にしてください。

1. Executive Summary
2. 最初に売るべきpersona
3. Persona別価値マップ
4. GPT / Claude 単体との差分
5. 完成物カタログ
6. 初回3回無料で見せるべき体験
7. 満足条件 / 不満条件
8. サンプル回答構造
9. 競合比較表
10. persona別インタビュー質問
11. 検証ベンチ設計
12. 30日以内に検証すべき仮説
13. リスクと避けるべき表現

## 重要な姿勢

ユーザーは「検索できます」では課金しません。「このまま顧客に送れる」「このまま面談で使える」「このままAI agentに渡せる」と感じる完成物に課金します。

価格変更ではなく、回答の深さ・根拠・再利用性・横断結合に集中してください。

