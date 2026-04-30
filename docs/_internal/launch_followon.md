# Launch Follow-On Plan — D+1 through D+28

> **要約:** 2026-05-06 launch 後、静寂期を作らないための段階投入計画 (D+1 / D+3 / D+7 / D+14 / D+21 / D+28)。全体は 4 週間 1,000h の中の「コンテンツ + 顧客接点」ラインで、**製品改善は別ライン** (`docs/POST_DEPLOY_PLAN_W5_W8.md`)。本 doc は「どのタイミングで何を出すか」だけを扱う。
>
> ドメイン / ブランド名は rebrand pending のため `jpcite.com` / `[BRAND]` で統一。content 本体はここで書かない (outline のみ、pillar 記事は `docs/content_flywheel.md` agent が担当)。

関連: `docs/launch_dday_matrix.md` (当日) / `docs/customer_dev_w5.md` (interview 手順) / `docs/content_flywheel.md` (pillar) / `docs/retention_digest.md` (W7 digest) / `docs/POST_DEPLOY_PLAN_W5_W8.md` (W5-W8 backlog).

---

## 1. D+1 (2026-05-07 Thu) — Warm outreach email batch

**目的**: launch 当日 reaction を残した visitor 50 名に 1:1 DM / メール。一斉配信ではなく **per-recipient render** (同一文面の mass blast ではない)。

**ソース** (`docs/customer_dev_w5.md` §3 と重複): Zenn コメント / X replies / HN thread で質問した人 / 当日 `/v1/subscribers` に signup した人 / MCP 系 Discord で反応した人。

**上限**: 50 送信。一括スクリプトではなく、1 通書くごとに文脈に合わせて 2-3 文 customize。

**テンプレ (コピペ base)**:

```
件名: 昨日は [記事 / comment] ありがとうございました — 5 分だけ感想聞かせてください

[氏名] 様

昨日 [BRAND] を launch した梅田と申します。
[具体的 reference — Zenn コメントの引用 / X リプの引用 / HN の質問の引用] を拝見し、
[この 1 点に具体的にリアクション: 「その使い方は想定していませんでした」等、
相手の発言に具体的に返す]。

今つくっているものの「何が足りないか」を、もしお時間いただけるなら 30 分だけ
教えていただきたいです (売り込みはしません、録画は非公開)。

- Zoom / Meet 30 min
- 謝礼 Amazon JP ギフトカード ¥1,500
- 候補時間 [3 枠]

触ってみてのご感想 1 行だけでも嬉しいです。

梅田
```

**禁止**: ファーストネーム呼び捨て / 営業 CTA / tracking pixel / campaign id。成功指標: 50 送信 → 返信 ≥ 10 → call 予約 ≥ 5 (< 10% は launch 記事のクオリティ問題)。

---

## 2. D+3 (2026-05-09 Sat) — "What we learned in 72h" blog

**publish 判断 gate** (事前に決める):

| 条件 | Action |
|------|--------|
| signups ≥ 100 **かつ** paid ≥ 3 | publish (full 数値公開) |
| signups ≥ 100 かつ paid = 0 | publish (qualitative only、数値は absolute 非公開) |
| signups < 50 | **skip**。72h 記事は sample size が足りない、素振りに終わる |

**outline (投下時の骨格)**:

```
H1: 72時間で何が起きたか — [BRAND] launch 後の中間報告

H2: 数字 (公開できるものだけ)
  - unique visitors / 記事 PV / HN position history / signups
  - D+0 から D+3 の各日の 4 数字 snapshot
  - conversion funnel 各段の drop 率 (比率のみ、絶対値は小さければ非公開)

H2: Top 5 検索クエリ
  - Cloudflare Analytics の referrer + `/v1/programs/search?q=...` 集計
  - 我々の仮説と違った 2 本を強調

H2: 最も意外だった反応
  - 1-2 件の具体的 X / Zenn comment (本人に許諾取ってから引用)
  - 我々が想定していなかったユースケース

H2: P0 で直したこと
  - 3-5 件の hotfix (CHANGELOG から抽出)
  - 各 1 行で何が壊れていて、何で直したか

H2: 次の 2 週間
  - `docs/POST_DEPLOY_PLAN_W5_W8.md` の W6 backlog を要約 (5 本)
  - ユーザーが「待てば来る」と知れるように
```

**word target**: 2,000-3,000 字。Zenn + cross-post 1 回 (note.com は +7 日後、`content_flywheel.md` §6)。

**KPI of the post itself**: publish から 48h で PV ≥ 1,500 / signups ≥ 30 追加 → 成立。未達なら content frequency を落として次の D+7 interview に reframe。

---

## 3. D+7 (2026-05-13 Wed) — First customer interview batch

**内容**: `docs/customer_dev_w5.md` 30 interview の最初の 5 件が D+7 時点で完了想定。post-launch の質問セットは pre-launch と違う — 「触ったか」「触らなかったならなぜか」を前面に。pre-launch は「現在のワークフロー → product surfaces → switch/pay」、post-launch は surfaces が不要で **actual-use reconstruction** に置換。

### 3.2 post-launch 質問セット (30 min 枠)

```
0-3 min: 近況、録画許諾、今日のお時間感謝

3-10 min: Actual use reconstruction (pre-launch とここが最大の差)
  - 「先日 [BRAND] の記事を見てからの 7 日間、何をされましたか」
  - 「API キー取得しましたか? / しなかったなら何で止まりましたか」
  - 「curl or SDK or MCP のどれで叩こうとしましたか / 実際に叩きましたか」
  - 「叩いた結果を、どのように product / RAG / chat に繋ごうとしましたか」
  - 「最後に何をしたあと離脱しましたか」
  → ここが hell-yes / hell-no の分水嶺

10-18 min: Friction mapping
  - 「docs のどこで詰まりましたか」(具体 URL + screenshot までもらう)
  - 「response JSON で足りないフィールドは何でしたか」(実物を開きながら)
  - 「MCP サーバー起動で詰まったポイントは」(Claude Desktop 側の config も併せて)
  - 「自分のプロダクトのどこに embed しようとしましたか」
  → 「使いづらさ」を具体名詞で回収

18-25 min: Pay motivation (pre-launch と同じ 4 質問)
  - 従量 ¥3/req、月 1 万で ¥30,000、10 万で ¥30 万: 自分のカード or 会社経費
  - 稟議に必要な書類 / SLA / 契約条項 (完全セルフサーブ方針、個別契約なしと明示し、それで止まるかを聞く)
  - 「今日この話を聞いて、払う確率は 10 中いくつ上がりましたか / 下がりましたか」
  - 「払わない理由を 1 つだけ挙げるなら」

25-30 min: Referral + close
  - 「誰に紹介したくなりますか」(名前 1-2)
  - こちら (梅田) が貢献できる未解決課題あれば 30 min gift 提案
```

**diff**: 「もし〜があったら」は pre-launch 禁止、post-launch は「触った後に欲しいと思った機能」は OK (= 直近過去の reflection)。

### 3.3 アウトプット

- `research/interviews/2026-05-13_[handle].md` に 5 件
- `research/customer_dev_log.csv` に行追加
- **5 件毎 thesis レビュー** (`customer_dev_w5.md` §6) — 5 人中 0 が「払う」なら positioning 根本見直し

---

## 4. D+14 (2026-05-20 Wed) — Pillar article second wave

**来るもの**: `docs/content_flywheel.md` から **4 本** (Zenn publish)。Mon / Tue / Thu / Fri のスタガード配信で金曜までに 1 週間が持続的にコンテンツ供給される状態を作る。

| 日 (JST) | slug | pillar | target KW |
|---------|------|--------|-----------|
| 月 5/18 | `/articles/aomori-smart-agri-2026` | A (都道府県×業種) | 青森県 認定新規就農者 補助金 2026 |
| 火 5/19 | `/articles/claude-desktop-subsidy-mcp` | B (AI × 補助金) | Claude Desktop 補助金 MCP |
| 木 5/21 | `/articles/jgrants-vs-jpintel` | C (比較) | Jグランツ API 併用 補助金検索 |
| 金 5/22 | `/articles/hokkaido-dairy-dx-2026` | A (都道府県×業種) | 北海道 酪農 補助金 DX 2026 |

**word target** 各 5,000-7,000 字、**構造は** `content_flywheel.md` §3 (Intro / 制度一覧 / 併用シナリオ / timeline / FAQ / API で引く / 公式ソース)。

**本 doc の範囲**: **outline のみ**、本文執筆は content flywheel agent が担当。本 doc の stance は「schedule と pillar mix を崩さない」。

**tone check**:
- 「2026 年最新」と書くなら 2026 年固有情報が本文に最低 3 個ないと misleading
- 「いかがでしたか」「まとめ」禁止 (`content_flywheel.md` §5)
- 月 5 本以上は NG (薄くなる、月 4-5 本で fix)

---

## 5. D+21 (2026-05-27 Wed) — First retention digest send

**前提**: `docs/retention_digest.md` 設計通り。migration `005_usage_params.sql` が W6 (5/13) までに本番適用済、W7 (5/20) に smoke send (社内 5 通)、**5/27 が全量初回**。

**D+21 初回で守ること**:

1. 送信上限 `--limit 500` (全量ではなく、まず 500 通で open rate / bounce / spam complaint を測る)
2. 送信時刻 **水 09:00 JST** (朝通勤時、JP で open 率が安定する)
3. 件名 A/B **なし** (初回は統制して base rate を取る)
4. fallback template (検索履歴ゼロユーザー) の発火率を測る — 50% 超なら content formula 要再設計

**kill-switch**:

| 初回結果 | Action |
|---------|--------|
| open rate < 20% かつ unsubscribe > 5% | 1 週 pause、件名再考 |
| bounce > 5% | Postmark reputation 汚染前に停止、email list hygiene |
| spam complaint > 0.3% | 即 pause、全 list に戻って opt-in 確認 |
| open rate ≥ 25% かつ CTR ≥ 8% | 2 週目から full 配信 + §7 の A/B 開始 |

**stance**: content 詳細は `retention_digest.md` に任せ、本 doc は「送るべきか (volume 条件)」のみ (§7 参照)。

---

## 6. D+28 (2026-06-03 Wed) — Monthly recap public post

**判断 gate**:

| Revenue state | 公開する数字 |
|---------------|-------------|
| MRR ≥ ¥50,000 | 数字そのまま (MRR / paid 数 / 平均契約単価 / churn 件数) |
| MRR ¥10,000-49,999 | 絶対値公開可 (transparency が JP indie community の reward) |
| MRR < ¥10,000 | 「まだ小さい、しかし funnel の具体数値は開示」— paid 数 / signup 数 / conversion% を出す、MRR 絶対値は省略 |
| MRR = 0 | 金銭非公開、「30日で何を学んだか」の qualitative post にフォーカス |

**outline**:

```
H1: [BRAND] launch から 30 日 — 数字と学びの公開

H2: 数字 (上記 gate で決まる粒度)
  - signups / paid / MRR (公開可なら) / churn / retained MAU

H2: 最大の surprise 3 本
  - 「想定していた A が起きず、B が起きた」パターン
  - 例: 想定 = RAG 開発者、実際 = 税理士業の個人開発者 (あれば)

H2: 最大の不具合 3 本
  - 直した hotfix の中から 3 件、恥ずかしさを隠さず公開

H2: 次の 30 日でやること
  - W9-W12 計画 (POST_DEPLOY_PLAN_W5_W8 の fork 判定後)

H2: 質問・提案の窓口
  - hello@jpcite.com、Zenn コメント、X DM
```

**tone**: 日本の dev / indie コミュニティは transparency を reward する。盛り上げ用数字は逆効果、**小さくても正直** が信頼の通貨。

---

## 7. Kill-switch triggers for the content plan

全体が「計画どおりに進まなければどこで止めて組み替えるか」の事前コミット。情緒判断を排除する。

| Trigger (日時 + 条件) | Action |
|-----------------------|--------|
| **D+7 で signups < 50** | D+14 の pillar 記事 2 本に減らし、残り 2 本を **customer interview 深掘り** (calls 5 本追加予約) に振替。paid tier 訴求のコピー全修正を W6 に強制挿入 |
| **D+14 で paid subs < 5** | D+21 の retention digest を **skip** (sample 足りない、spam リスクの方が大きい)。digest 工数 (40h) を W7 の conversion funnel fix (`conversion_funnel.md` §4) に全振り |
| **D+14 で pillar article 4 本目の publish に間に合わない** | 3 本で止める (無理押しは `content_flywheel.md` §5 で禁じている薄さにつながる)。遅れた 1 本は D+21 に延期、content_flywheel 月間 20 本の schedule は 1 本繰り下げで維持 |
| **D+21 の digest 初回で open < 15%** | 2 週目 pause、件名 + 時間 + content を全面見直し (`retention_digest.md` §7 A/B)。3 週連続 < 15% なら W11 まで digest 凍結 |
| **D+28 で MRR < ¥10,000 かつ MAU < 200** | D+28 public post は **skip or qualitative only**、monthly recap のリズム自体を月次から四半期次に downgrade。content flywheel は pillar A (都道府県×業種) に weight 寄せ、B/C を半分に |
| **launch 後いずれかの週で P0 hotfix が 3 件/週超** | content 全凍結、`POST_DEPLOY_PLAN_W5_W8.md` §9 の stabilization sprint 発動、この doc の schedule は全部 +1 週ずらす |
| **商標 Intel 衝突再発 (launch 後、弁理士連絡 or cease letter)** | 全 schedule 停止、rebrand 24h 発動 (`project_jpintel_trademark_intel_risk`)。既 publish 済記事の ブランド名 grep + rewrite が先、新規投入は凍結 |

**原則**: kill switch は **日付 + 数値** で自動判定 (情緒を排除)。超えたら「悔しいから続ける」禁止、即切替。

---

## 8. Schedule at a glance

```
D+0 (05-06 水)  launch → dday_matrix
D+1 (05-07 木)  50 warm outreach (§1)
D+3 (05-09 土)  "72h learned" blog (gate クリア時、§2)
D+4-D+6        interview 進行 (customer_dev_w5 §7)
D+7 (05-13 水)  5 interview / 週次レトロ / digest migration 本番適用
D+8-D+13       W6 backlog (POST_DEPLOY_PLAN §3)
D+14 (05-20)   pillar Mon/Tue/Thu/Fri 計 4 本 (§4)
D+15-D+20      W7 backlog、digest smoke
D+21 (05-27 水) retention digest 全量初回 500 通 (§5)
D+22-D+27      W8 backlog、digest 週次 2 回目
D+28 (06-03 水) monthly recap public post (§6) + W9 計画 commit
```

---

## 9. Non-goals

- Product Hunt 再投下・同一 subreddit 2 週連続投稿 (低品質フィード penalty)
- 有料広告 (Google / X / Meta) — `POST_DEPLOY_PLAN_W5_W8.md` §7 で dark pattern 隣接として除外
- インフルエンサー謝礼 / paid shoutout — `competitive_watch.md` §7 non-goals と整合
- Cold email 一斉配信 (warm outreach §1 は per-recipient render のみ)
- "launch 2.0" 再打ち — Month 2 の English relaunch まで単発で行く

---

最終更新: 2026-04-23 / 次回更新予定: D+28 (2026-06-03) recap 投下時。
