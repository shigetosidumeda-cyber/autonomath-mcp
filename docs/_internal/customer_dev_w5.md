# Week 5 Customer Development Program (jpintel-mcp)

**Window**: 2026-05-06 (launch +0) → 2026-05-13 (launch +7)
**Owner**: 梅田 (全工程)
**単一ゴール**: **30 人と話し、「なぜ払う / 払わない」を聞き、W6 で作り直す材料を持ち帰る**。

user quote:
> 誰かがアクセスして全く買わないようなものは出してもしょうがない。

このプログラムは lead gen ではない。**「誰がなぜ払うか」を W5 の 7 日で確定させ、W6 の build backlog を書き換える**ためのリサーチである。営業ゼロの原則は崩さない (インタビュー終盤でのピッチ禁止)。

---

## 1. 30-Interview Target (segment 別)

| # | セグメント | 人数 | recruit チャネル | なぜ聞くか |
|---|-----------|------|-----------------|-----------|
| A | Indie AI 開発者 (日本 SMB 向けツール製作) | 10 | Zenn / Qiita の MCP/LLM 記事コメント、X #AI #MCP #Claude hashtag、Smithery/MCP registry 掲載者の DM | Paid ¥0.5/req の主購買層 (月 1K-10K req 帯)。払う動機と抵抗を最優先で取る |
| B | Mid-sized SaaS engineer (日本 SaaS で社内 AI 機能を作る側) | 10 | Smart HR / freee / SmartRound の X mutual follow、Japan SaaS Slack、勉強会 LT 登壇者 | Paid ¥0.5/req のヘビー帯 (月 10K-100K req)。稟議プロセスと internal buy-in の阻害要因を取る |
| C | Enterprise 内製 RAG owner | 5 | LinkedIn DM (タイトル: AI Engineer / Platform Lead / RAG Lead)、X DM。**謝礼の代わりに 30 min の無料コンサル** | Paid ヘビー帯 (月 100K req+) の条件を確認。自動化方針のため個別 SLA / 契約 / on-prem は提供しないと明示し、それで不足な要求を聞く |
| D | 「隣接だが非ターゲット」 (補助金コンサル、税理士 SaaS、行政書士ツール) | 5 | 業界団体 / X 検索 | 「買わない」ことを確認。営業電話されないか、ターゲット外し判断を裏取り |
| **合計** | | **30** | | |

**重要**: A-C は加点、D は「ターゲットから外す」根拠取り。D を曖昧にすると営業要望に引き込まれる。

---

## 2. Interview Script (Mom-Test 準拠・誘導禁止)

### 事前メール (48h 前)

> 件名: 30 分インタビューのお願い (jpintel-mcp / 日本の制度データ API)
>
> [氏名] 様
>
> X / Zenn で [具体的記事・tweet] を拝見しました。日本向け AI プロダクトを作る方の「一次情報アクセス」のワークフローを 30 分だけ教えていただきたく、ご連絡しました。
>
> - 形式: Zoom / Google Meet、30 分
> - 謝礼: Amazon JP ギフトカード ¥1,500
> - 録画: 文字起こしのため録画します (外部公開しません。希望時に消去)
> - 売り込み: しません。こちらが聞き役です
>
> 候補時間 (JST): [3 枠]
>
> 梅田

### 0-5 min — Rapport (現在作っているもの)

- 「今日はお時間ありがとうございます。録画の許可だけ取らせてください」
- 「お作りになっているプロダクトを 2-3 分で教えてください。誰が使って、何が解決されますか」
- 禁止: jpintel の話を一切しない

### 5-15 min — Current Workflow (観察、ピッチ禁止)

Mom-Test 鉄則: **未来形を聞かない、過去と現在だけ聞く**。

- 「直近で日本の補助金 / 制度情報が必要になった場面を、思い出せる限り具体的に教えてください」
- 「そのとき、何をどう調べましたか。URL、ツール、人に聞いた、全部」
- 「どれくらい時間かかりましたか。何が一番面倒でしたか」
- 「その情報を最終的に誰がどう使いましたか」
- 「そのタスク、次も発生しそうですか。頻度は」
- 禁止ワード: 「もし〜があったら便利だと思いますか」(= 全員 Yes と言う嘘質問)

### 15-25 min — Product Surfaces (3 面見せて observe)

見せる順:
1. **Landing page URL** (説明せず URL だけ共有、30 秒黙って読んでもらう)
2. **`/v1/programs/search` の JSON レスポンス** (raw、整形せず)
3. **Claude Desktop に MCP 統合済みの画面で 1 クエリ実行**

各面で聞く:
- 「今画面見て、最初に考えたことを言葉にしてください」
- 「自分のプロダクトで使うとしたら、どこで使いそうですか / 使えなさそうですか」
- 「足りないと感じたフィールド / 機能はありますか」

禁止: 機能説明を先回りしない。相手が混乱していたら **混乱のポイントをメモ** (= docs の欠陥)。

### 25-30 min — Switch / Pay / Recommend

- 「今の調べ方を捨てて、これに置き換わるとしたら、何が揃っていたら置き換えますか」
- 「従量 ¥0.5/req、月 1 万 req で ¥5,000、10 万 req で ¥5 万。自分のカードで払いますか、会社の経費ですか」(払う主体を特定)
- 「会社経費なら、稟議を通すのに必要な書類 / SLA / 契約条項はなんですか」
- 「誰にこれを紹介したくなりますか。名前出せる人 1-2 名」(紹介先が 0 なら fit 低い)

### 48h Follow-up (必須)

call で出た具体ユースケースに対して、こちらで 1 クエリ作って Slack / DM:

> 先日のインタビューありがとうございました。話に出た「[具体ユースケース]」を jpintel で試すと、こうなります:
> [実レスポンス JSON の 5 行 + landing へのリンク]
> もし 5 分だけ触ってみていただけたら、感想を 1 行だけ返していただけると嬉しいです。

**触った人数 / 触らなかった人数**を数える = intent signal の最重要指標。

---

## 3. Recruitment Channels + Copy (コピペ用)

### 3.1 Zenn コメント (MCP / LLM 記事向け)

> [記事タイトル] 拝読しました。[記事の具体ポイント] が特に勉強になりました。
>
> 日本向け AI プロダクトを作る方の「制度データの取り回し」について、30 分インタビューさせてください (Amazon ギフト ¥1,500)。私は jpintel-mcp という日本の制度 API を作っているのですが、**売り込みではなく**、みなさんのワークフローを知りたいです。
>
> 興味あれば [DM リンク / email] までどうぞ。— 梅田

### 3.2 X DM (JP, A/B セグメント)

> 初めまして、梅田と申します。[具体 tweet の引用] 拝見しました。
>
> 日本向け AI プロダクトを作られている方に 30 分だけ「制度情報の調べ方」を教えていただくインタビューをしています (Amazon JP ギフト ¥1,500、売り込み無し、録画は外部非公開)。
>
> ご興味あれば候補日お送りします。無理なら無視してください。

### 3.3 LinkedIn DM (C セグメント・enterprise)

> Hello [Name], I'm Shigetoshi Umeda, building jpintel-mcp, a Japanese institutional data API.
>
> I'm researching how enterprise RAG teams in Japan source primary-source Japanese regulatory / subsidy data. Could I trade 30 min of your time for 30 min of free consulting on your ingestion pipeline (you pick the topic)? No pitch.
>
> Calendly: [link]

### 3.4 HN "Ask HN" (英、international enterprise 向け・補助枠)

> **Ask HN: How do you source Japanese regulatory / subsidy data for your RAG?**
>
> Building an API that returns 6,771 Japanese institutional programs (subsidies, tax, loans, law) as structured JSON + MCP tools. Curious what teams currently do — scraping, vendors, manual, nothing.
>
> If you work on a RAG / agent product that touches Japan and can spare 30 min, I'll pay $15 gift card. Reply or email: [addr].

### 3.5 MCP コミュニティ (Discord / Slack)

**事前に channel を特定する**:
- Anthropic Discord `#mcp` 系 channel
- modelcontextprotocol/servers GitHub discussion
- Smithery Discord
- Cursor Discord `#community`

投稿コピー:

> Hi — I run a public MCP server (jpintel-mcp, Japanese institutional data). Doing user research this week, 30 min call + ¥1,500 / $15 gift card, no sales pitch, just want to learn how you use MCP servers in prod. DM if interested.

### 3.6 謝礼・倫理

- Amazon JP ギフト ¥1,500 × 30 = **¥45,000 予算確保**
- 録画の事前同意、外部非公開を明記
- インタビュー中のピッチ禁止。最後の「switch / pay」質問のみ prod 価格に言及
- D セグメントには無償 (「ターゲット外を確認する」目的なので、謝礼出すと義理が発生する)

---

## 4. Tracking Template

CSV: `/Users/shigetoumeda/jpintel-mcp/research/customer_dev_log.csv`

列:

```
id, name, segment, recruit_channel, call_date, call_minutes, fit_score_1_10, top_pain, top_blocker_to_buy, would_pay_personal_or_company, followup_sent_date, followup_clicked, followup_tried_api, direct_quote, next_action
```

運用:
- call 終了 15 分以内に **quote と fit_score** だけは埋める (記憶が鮮明なうち)
- fit_score 基準: 10=「今すぐ払う」、7=「条件揃えば払う」、5=「無料なら使う」、3=「使わない」、1=「そもそも対象外」
- top_quote は **相手の言葉そのまま、要約しない**。W5 分析と W6 landing コピーで使う

---

## 5. W5 末の分析 Deliverable

ファイル: `/Users/shigetoumeda/jpintel-mcp/research/customer_dev_analysis_w5.md`

含むもの:

1. **5 personas** (各 1 段落 + 3 quote + fit_score 分布)
2. **Top 10 unsolved pains** (頻度順、quote 付き)
3. **5 "hell yes" features** (2 人以上が unprompted で欲しがったもの)
4. **3 "definitely won't pay" reasons** (= dead-end。W6 で避ける)

納期: 2026-05-13 23:59 JST。翌日の W6 kickoff で backlog を書き換える入力にする。

---

## 6. Iteration Rule (pivot trigger)

- **5 call ごと** に 30 分、thesis レビュー。現時点の 5 persona 仮説を書き直す
- **15 call 時点で、誘導なしに「払う」と言った人が 0 なら** → positioning / 機能が根本的にズレている。残り 15 call を「なぜ既存ツールで足りているか」に舵切り
- **8 call 以上が同じ未対応ユースケースに収束したら** → W6 で最優先で実装。他の backlog は凍結
- **D セグメント (隣接非ターゲット) が「使いたい」と言ったら警戒**。営業要望に引き込まれる兆候 → 断る理由を明文化し、README に追記

---

## 7. タイムライン (7 日)

| 日 | 作業 | 目標 call 数 |
|---|------|-------------|
| 05-06 (火) | launch 当日。recruit メッセージ全 channel 一斉投下、calendar 枠開放 | 0 |
| 05-07 (水) | 朝 4 call、夕 3 call (A セグメント中心) | 7 |
| 05-08 (木) | 朝 3 call、夕 3 call。5 call review | 6 |
| 05-09 (金) | 朝 3 call、夕 2 call。B セグメント投入 | 5 |
| 05-10 (土) | 休息半日、午後 3 call (indie は土日 OK) | 3 |
| 05-11 (日) | HN post の反応処理、C セグメント 2 call | 2 |
| 05-12 (月) | C/D 残り埋め、followup 集計 | 5 |
| 05-13 (火) | 予備 2 call + 分析 md 執筆 | 2 |
| **計** | | **30** |

1 日 5-7 call は限界。**2 call 目ごとに 15 分 buffer**、食事と仮眠を削らない (品質低下する)。

---

## 8. やらないこと (明文化)

- 営業電話・pilot 提案・説明会 (README 原則 1)
- インタビュー中のピッチ (最後の質問以外)
- 「書類を代行生成します」の示唆 (行政書士法抵触、README 原則 4)
- D セグメントへの迎合 (補助金コンサル向け機能は作らない)
- 500 call / 100 call 規模への拡大 (30 で止め、W6 build に移る)
