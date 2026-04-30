# Launch Partner Outreach — 個別アプローチ台帳 (2026-05-06 launch)

> **要約:** `docs/launch_dday_matrix.md` が D-Day の「チャネル別 broadcast」をカバーする一方、本ドキュメントは **specific individual outreach** (記者、OSS/コミュニティ インフルエンサー、B2B パートナー、行政窓口、早期顧客) への 1 対 1 ピッチ台帳。総スロット ≈ 70。**実名はハルシネーション厳禁、placeholder `{name}` のままで出し、ユーザーが launch 前週に一次ソースから実名を埋める**。ブランド / ドメインは rebrand pending (`project_jpintel_trademark_intel_risk`) のため `[BRAND]` / `jpcite.com` / `[HANDLE]` で固定。
>
> 関連: `docs/launch_dday_matrix.md` (broadcast) / `docs/launch_war_room.md` (ops) / `docs/customer_dev_w5.md` (interview pipeline) / `docs/ab_copy_variants.md` (コピー原本) / `research/competitive_landscape.md` (非競合 partner 候補) / `research/outreach_tracker.csv` (進捗管理 CSV)

---

## 0. 原則

1. **名前は一次ソース (staff page / by-line / GitHub / Zenn / LinkedIn) から埋める**。確認できないなら空欄。想像で入れない。
2. 本書は公開 form / 公開 X handle / 公開 GitHub / 会社代表フォーム のみ。個人メール平文化禁止。
3. テンプレは出発点、最終 DM は 1 通ずつ手編集。bulk 送信禁止。
4. 1 媒体につき DM は 1 名まで。複数記者への同日同 pitch 禁止。
5. 「押し」ではなく「地図」。相手の読者 / コミュニティにとっての価値を 1 文で説明してから product の話。

---

## 1. Category A — 日本 tech 媒体 記者 (14 outlets × 2-3 slots ≈ 32)

**アプローチ**: R1 テンプレ (§6.1)。1 媒体に 1 名 (技術ビート) を選び、X DM が空振りなら 3 日空けて 公開問合せフォームから email pitch に切替。

| slot_id | outlet | 想定ビート | 公開 contact URL | 実名 | 実名確認ソース | 採用 template | pitch 想定 angle |
|---|---|---|---|---|---|---|---|
| A01 | TECHPLAY Magazine | dev イベント / コミュニティ | `techplay.jp/event` (各イベントの主催者 info) | {name} | `techplay.jp` 上の主催プロフィール要確認 | R1 | 「補助金 6,658 件を 1 行 curl で」LT ネタ提供 |
| A02 | ITmedia NEWS | 政府 DX / SaaS | `corp.itmedia.co.jp/media/inquiry/articles/` (公開フォーム) | {name} | by-line author ページを記事ごとに拾う | R1 | 「Jグランツ の補完層として API 化」 |
| A03 | ITmedia エンタープライズ | AI / LLM 国内導入 | 同上 | {name} | 同上 | R1 | 「社内 RAG の幻覚を制度 API で止める」 |
| A04 | 日経 xTECH | regtech / 公共 DX | `support.nikkeibp.co.jp/app/answers/list/p/235` (FAQ経由) | {name} | 署名記事から by-line 抽出 | R1 | 「自治体 オープンデータの implementable 化」 |
| A05 | 日経 xTECH IT / Active | ソフトウェア開発 | 同上 | {name} | 同上 | R1 | 「MCP 実装事例・日本発 public server」 |
| A06 | ZDNET Japan | enterprise SaaS / インフラ | 媒体トップ footer の公開フォーム | {name} | 記事の by-line から抽出 | R1 | 「コード first な制度データ、6 ヶ月契約不要」 |
| A07 | Publickey | クラウド / SaaS / OSS | `comment [at] publickey.jp` (公開 email、release 用は `release [at]`) | 新野 淳一 (公開情報: 運営者兼編集長) | `publickey1.jp/about-us.html` | R1 | 「Show HN 化した事例、公開 API のパブリックキー的切り口」 |
| A08 | CodeZine (翔泳社) | 開発者向け技術解説 | `codezine.jp/offering` (寄稿・取材提案フォーム) | {name} | `codezine.jp/author` の author 一覧から MCP / API 系記事の著者を抽出 | R1 | 「MCP server 構築の実装 tips + 国内データ API」 |
| A09 | InfoQ Japan | アーキテクチャ / 実践 | 媒体 footer の editor 連絡先 | {name} | 記事 by-line から拾う | R1 | 「6,658 件を lineage 付きで公開する設計」 |
| A10 | @IT | 開発者向け / Insider.NET 等 | ITmedia 代表フォーム (媒体 footer) | {name} | 連載持ち author を優先 | R1 | 「連載寄稿 or 単発インタビュー」 |
| A11 | Jprogrammer (個人/小規模媒体の場合は skip) | ニッチ dev 媒体 | 媒体 footer 確認 | {name} | staff page | R1 | 「niche API の紹介」 |
| A12 | 窓の杜 | Windows / freeware / ツール系 | `impress.co.jp` 系の公開フォーム | {name} | by-line から抽出 | R1 | 「CLI ツール / OSS としての紹介」 ※ 本命ではない |
| A13 | MarkeZine (翔泳社) | マーケ / SaaS の注目企業 | `markezine.jp/pr/` または `/form/` (媒体ポリシー確認) | {name} | editor by-line | R1 | 「プロダクト紹介ではなく dev エコシステム trend 記事として」 |
| A14 | ASCII.jp | コンシューマ〜tech | `ascii.jp/support/` (公開フォーム) | {name} | editor by-line | R1 | 「ちょっと毛色の違う AI API ローンチ」 |
| A15 | 技術評論社 WEB+DB / Software Design | 書籍連動記事 | `gihyo.jp` 公開フォーム | {name} | 寄稿著者から抽出 | R1 | 「長期寄稿 / 特集寄稿」 (1 本目でこれは重い、温めて 3 ヶ月後に) |

**注記**: 実名を置いたのは `publickey1.jp/about-us.html` で明示の **新野 淳一 (A07)** のみ。他 14 枠は `{name}` 維持、launch 前週に各媒体で walk して埋める。

---

## 2. Category B — Dev コミュニティ インフルエンサー (≈20 スロット)

**アプローチ**: C テンプレ (§6.3)。「拡散してください」ではなく「あなたのコミュニティに寄稿 / LT / 読み物 を提供します」。

### 2.1 Zenn/Qiita タグ Top Contributor (10 slots)

| slot_id | pool | 検索手順 (**これがユーザーへの deliverable、実名ではない**) | 採用 template |
|---|---|---|---|
| B01-B03 | Zenn `MCP` タグ Top likes | `zenn.dev/topics/mcp` → Alltime ソート → 上位 10 人のうち、**直近 6 ヶ月 active** で「商用 MCP 使用事例」記事を書いた人 3 人 | C |
| B04-B05 | Zenn `Claude` タグ Top | 同じ手順で `zenn.dev/topics/claude` → Alltime → 上位 5 人から企業所属なし / 個人 dev を 2 人 | C |
| B06-B07 | Qiita `補助金` / `GovTech` | `qiita.com/tags/補助金` `qiita.com/tags/govtech` で記事あり author を 2 人 (国内 regtech の土地勘あり) | C |
| B08 | Zenn `API設計` / `REST` | 直近 1 年で likes 100+ を取った API 設計記事著者 1 人 | C |
| B09-B10 | Zenn `LLM` × `日本語` | LLM + 日本語処理の記事でコミュニティ影響力ある 2 人 | C |

### 2.2 X (Twitter) インフルエンサー (5 slots)

検索手順: `@anthropicAI` を follow、follower 5k+、日本語 tweet 中心の個人 dev 5 名。`from:{handle} claude min_faves:20` で Claude 使用実績確認。公式アカウント / 宣伝案件常連 は除外。

| slot_id | 条件 | 採用 template |
|---|---|---|
| B11 | JP AI エージェント系 (follower 10k+、日本語、個人) | C |
| B12 | 日本語 MCP 実装ブログ持ち | C |
| B13 | 国内 dev + 英語でも発信 | C |
| B14 | GovTech / civic hack 系 | C |
| B15 | Japanese SaaS / B2B engineer | C |

### 2.3 コミュニティサーバー 管理者 (3 slots)

個別メンバーに DM しない。server admin に公開 channel での自己紹介可否のみ問い合わせ。

| slot_id | server | 接触方法 | 採用 template |
|---|---|---|---|
| B16 | Anthropic Discord (MCP 系チャンネル) | 公式 Discord 参加 → `#self-promotion` 規約確認後、gate 満たして投稿。admin DM は規約違反の場合あり、まず読む | C (admin 宛ての場合) |
| B17 | Smithery MCP registry Discord | Smithery 公式ページから invite、server 内 rules.md 熟読、admin bot 経由の申請ルートがあればそれ | C |
| B18 | Zenn Discord (もしコミュニティサーバーがあれば) | 公式経由で invite 確認。存在しない場合はこの slot を落として代わりに Qiita コミュニティへ振替 | C |

### 2.4 勉強会 / LT 主催 (2 slots)

| slot_id | pool | 検索手順 | 採用 template |
|---|---|---|---|
| B19 | connpass.com `MCP` / `Claude Desktop` 勉強会 直近 3 ヶ月の主催者 1 名 | `connpass.com/search/?q=MCP` → 主催者プロフィール公開 URL のみ | C |
| B20 | 日本語 AI エージェント / LLM アプリ勉強会 主催 1 名 | 同様 | C |

---

## 3. Category C — B2B パートナー / Integrator (10 スロット)

**アプローチ**: B テンプレ (§6.4)。revenue-share か co-marketing の明示。

| slot_id | 対象カテゴリ | 具体候補 (公開企業) | 公開 contact | 採用 template | 提案 value |
|---|---|---|---|---|---|
| C01 | 中小企業診断士 協会 | 一般社団法人 中小企業診断協会 (`j-smeca.jp`) | 代表お問い合わせフォーム (公開) | B | 会員向け「制度データ API 引き合わせ」コンテンツ寄稿 |
| C02 | 農業経営コンサル firm | `docs/customer_dev_w5.md` Dセグメント の隣接先 から 1 社 | 各社お問い合わせフォーム | B | 顧客向け 月次 補助金カタログ 自動生成 |
| C03 | 地方自治体向け DX 受託開発 | {company placeholder — 公開企業 ISID / TIS / Skybridge 等の自治体 DX 部門} | 各社プレス窓口 | B | 自治体案件での API 引用許諾・co-author 事例 |
| C04 | Cursor integration team | Cursor 公式 support / community URL | 公式 Discord・GitHub discussion | B | MCP registry 自主登録 + Cursor blog での 技術記事 co-post |
| C05 | Cline IDE / Continue.dev | 各プロジェクトの GitHub discussion | GitHub Issues (公開) | B | MCP registry 自主登録 + 英語公式 example repo へ PR |
| C06 | Windsurf (Codeium) | Codeium 公式 contact | 公式 contact form | B | 同上 |
| C07 | freee | `corp.freee.co.jp` プレス / partnership | 公開プレス窓口 | B | 「freee ユーザー向け 補助金 discovery カード」概念実証 |
| C08 | マネーフォワード | `corp.moneyforward.com` プレス / partnership | 公開プレス窓口 | B | 同上 |
| C09 | Smithery / MCP registry | `smithery.ai` 公開 contact | 公開 form | B | server 掲載 + フィーチャー枠 |
| C10 | Pulse MCP | `pulsemcp.com` 公開 contact | 公開 form | B | server 掲載 |

**注**: C07-C08 (freee / MF) は launch 当日 DM 成立薄。launch 前に プレス窓口 へ 1 枚 PDF、2-3 週間後に技術ペアリング打診。D-Day は「launch 報告」で留める。

---

## 4. Category D — 行政窓口 (5-10 スロット)

**トーン**: 取材依頼ではなく「公開データの利用者としての利用報告 + データ品質フィードバック」が正面玄関。

| slot_id | 対象 | 公開 contact URL | 採用 template | アプローチ要点 |
|---|---|---|---|---|
| D01 | デジタル庁 | `forms.office.com/r/QVZ0HSP6Se` (ご意見・ご要望 公式 form) | G | 「Jグランツ 公開 API を活用した サードパーティ API 実装事例 ご報告」。リリース後 1 週以内。 |
| D02 | MAFF 経営局 (代表 お問い合わせ) | `maff.go.jp/j/apply/recp/index.html` | G | 「MAFF 公開資料を API 化、lineage を保持して引用」。データ更新通知の email リスト登録希望も同封。 |
| D03 | 中小企業庁 広報 | 中小企業庁 代表 form (公開ページ footer) | G | D02 と同様の構成。プロモーション department ではなく政策情報広報の窓口。 |
| D04 | JFC (日本政策金融公庫) 広報 | `jfc.go.jp` 公開 form | G | 公庫の個別融資制度に `source_url` を張って参照していること、表記誤りがあれば修正する旨。 |
| D05 | 47 都道府県 CDO / デジタル推進室 | 各都道府県デジタル推進担当 公開 form (47 個) | G | Wave 1 は「公開 CDO 情報のある 5 県」のみに絞る: 例 神奈川 / 福島 / 兵庫 / 東京 / 大阪 等、実際に CDO ポスト公開の自治体のみ。**未公開の県に「CDO 様」宛てで出さない**。 |
| D06 | 経産省 IT戦略室 / Digital Marketplace 関連 | 代表 form | G | 公開 API の活用事例として |
| D07 | 国税庁 (参考データ先) | 代表 form | G | 税関連記述の一次リンクを国税庁 PDF に張っている旨の挨拶、誤訂正窓口の案内リクエスト |

**トーン要点** (§6.5 詳細): 「貴省の公開データを構造化しました」を主語に「相互リンク」「品質フィードバック」で着地。PR ブースト的記述は逆効果。PDF 1 枚添付 (概要 + データソース一覧 + 連絡先) 想定。

---

## 5. Category E — 早期顧客 ターゲット (10 スロット)

**位置付け**: `customer_dev_w5.md` §1 の A/B セグメントと重なるが、本 E は「個別指名で interview → 早期顧客候補」に格上げする Tier。interview コピーは `customer_dev_w5.md` §3 を流用。

| slot_id | pool | 検索手順 | 採用 template |
|---|---|---|---|
| E01-E05 | 青森 / 北海道 / 鹿児島 の agritech / ag-SaaS 5 社 | `crunchbase.com` / 各社 HP / `startup-db.com` で「農業 AI」「農業 SaaS」+ 地域フィルタ。設立 3-7 年 / 従業員 5-50 を優先 | E |
| E06-E08 | 大手 行政書士 firm 3 社 | 日本行政書士会連合会 公開名簿 から 法人化済みの大手 3 社 (補助金申請 領域明記) | E (間接的に、顧客への提供価値前提) |
| E09-E10 | AI コンサル firm (日本語クライアント) 2 社 | `linkedin.com` で「AI consulting Japan 中堅」、`openwork.jp` で評価の安定した企業 | E (resale / partnership 混在) |

**recruit コピー**: `customer_dev_w5.md` §3.2-3.3 を流用。重複テンプレ作らない。違いは「Interview + 早期顧客 onboarding」追加 (§6.6)。

---

## 6. Pitch テンプレ (編集用雛形)

> **使い方**: 下は出発点。1 通につき最低 3 箇所は相手固有情報に差し替え (相手の記事 1 本 / プロフィール関心事 / 過去発言との接続)。差し替え 1 箇所以下なら出さない。

### 6.1 R1 — 記者コールド pitch (日本語、X DM ≤ 180 字 / email ≤ 400 words)

**X DM 版 (≤ 180 字、最も短い):**

```
{name} 様、[BRAND] (日本の制度データ 6,658 件を REST+MCP で公開) を 2026/5/6 に launch しました。{outlet} の {ビート名} で取り上げ得そうでしたら、D+3 に 5 分デモで 15 分だけ話せますか。{Zenn launch URL}
```

**email 版 (≤ 400 words):**

```
件名: 日本の制度 6,658 件を REST + MCP で公開する API ([BRAND]) の launch ご案内

{name} 様

{outlet} でご執筆の「{相手の実記事タイトル、1 本 具体的に}」を読んで、制度データ / 公共 DX 領域に明るい書き手にお届けしたく、ご連絡しました。

私 (梅田) は 2026-05-06 に [BRAND] を launch しました。内容:

- 日本の制度 6,658 件 (中央省庁 + 47 都道府県 + JFC + 税制等) を REST + MCP で直引き
- 全件 source_url + fetched_at の一次資料リンク付き
- 排他ルール 35+ をデータとして同梱 (「この補助金と併用可?」に答える API 層)
- Jグランツ が「申請 portal」なら、これは「discovery + 併用判定」層

記事素材として:
1. 「日本の補助金 API を 1 行 curl で」デモ動画 60 秒
2. 構築中に出会った 公開データの壁 3 件 (MAFF PDF / 都道府県 HTML / 一次資料 lineage)
3. 私への取材 (30 分、日本語・英語可)

D+3 の 5 月 9 日 (土) 以降、15 分お話しできるタイミングがあれば候補日を頂けるとありがたいです。

梅田 茂利
jpcite.com / [HANDLE]
```

### 6.2 R2 — 記者フォローアップ (D+3、HN traction 後)

```
件名: 先日ご連絡した [BRAND] launch の続報 (HN front page / Zenn X Y いいね)

{name} 様

5/6 にご連絡した [BRAND] の launch 後 72h のデータです:
- Hacker News: {HN score / コメント数}、{HN URL}
- Zenn: {いいね数 / コメント数}、{記事 URL}

この pickup の中で、国内 dev コミュニティから寄せられた 具体的ユースケース 2 件:

1. {具体ユースケース 1 — 相手の読者にハマりそうなもの}
2. {具体ユースケース 2 — 数字付きで}

30 分だけ電話でお話できれば、記事の切り口としての筋を一緒に詰められるかもと思いました。

(同じ内容をまだ 20 名以下にしか送っていません — 他社 pickup と重ねたくないので一報ください。)
```

### 6.3 C — コミュニティリーダー pitch (提供先行)

```
{name} さん、はじめまして。{コミュニティ名} の {相手の具体貢献 1 つ} いつも拝見しています。

2026-05-06 に [BRAND] (日本の制度データ 6,658 件を REST + MCP で公開) を launch しました。

コミュニティに還元したいこと (選んでいただければ):
- MCP server 構築の実装 writeup (無料、連載可、誤字 reviewer 歓迎)
- LT 15 分 (オンライン / 関東オフライン どちらも)
- API キー 200 枚ぶんの credit を勉強会景品として寄贈 (¥500k 相当、要開示なら私の名前で)

告知協力 は期待していません。コミュニティの tone に合う関わり方だけご相談できればと思います。

梅田
[HANDLE]
```

### 6.4 B — B2B パートナー紹介

```
件名: [BRAND] × {相手会社名} の API 連携ご相談

{company} 御中 / {name} 様

私たちは 2026-05-06 に日本の制度データ API [BRAND] を公開しました (6,658 件、REST + MCP、一次資料 lineage 全件)。

貴社の {相手のプロダクト・サービス} のユーザー ({相手顧客セグメント}) にとって「自分に使える補助金 / 制度が自動で浮かぶ」体験は価値があるのではと考えています。

連携パターン (どれが近いかだけでもご教示いただければ):

1. **Embed (co-marketing)**: 貴社ダッシュボードに [BRAND] の widget を掲載、[BRAND] は貴社ロゴと事例共有
2. **Revenue share**: 貴社経由で流入したユーザーの API 課金 20% 還元 (一般的な SaaS 提携条件に合わせます)
3. **データ提供 (one-way)**: 御社内製 RAG の制度情報ソースとして [BRAND] の API を OEM

launch 週は私も時間が取れます。30 分だけ顔合わせ可能であれば候補日を頂戴できますと幸いです。

梅田 茂利
jpcite.com
```

### 6.5 G — 行政窓口レター (data-quality-first)

```
件名: 公開データ 利用ご報告: [BRAND] による {省庁名} 公開情報の構造化・API 化について

{省庁・自治体名} 御中

私 (梅田 茂利、個人事業主) は 2026-05-06 に [BRAND] を公開しました。貴省・貴庁の公開情報のうち、以下を構造化データ + API で再公開しています (source_url / fetched_at 全件付き、転載ではなく リファレンス + 二次構造化):

- 対象: {具体制度 3 件 列挙}
- 出典の扱い: 全件が貴省 Web サイトの一次 URL を `source_url` フィールドに保持、ユーザー側 UI / LLM エージェント 側 で 1 クリックで原文参照できる構造
- 更新頻度: 週次 差分スキャン、変更時は貴省の告示を参照

ご相談・ご確認 いただきたい 3 点:

1. **表記誤り窓口**: こちら側で制度名や上限金額に誤記を見つけた場合の訂正申告窓口はどちらになりますでしょうか
2. **データ更新 告知リスト**: 貴省の制度改正 告知メールリストがあれば申込希望 (公開されている登録ページへの案内をいただければ)
3. **相互参照**: 貴省のオープンデータポータルで「利用事例」紹介枠がある場合、本 API を掲載いただけると ユーザー 側の一次資料回帰が促進されます

梅田 茂利
jpcite.com / 代表メール 公開連絡先 (hello@jpcite.com)
```

**意図**: press coverage ではなく「公開データが使われている」事実報告 → データ品質ループ開通。12-24 ヶ月後の partnership foundation。

### 6.6 E — 早期顧客 (short, personal)

```
{name} 様

{相手会社の具体事業} にて 日本の 補助金 / 制度データ を検索することがもしあれば、2026-05-06 公開の [BRAND] を 無料枠 (月 100 req) で試していただけないでしょうか。

3 分だけ Demo 動画 (60 秒): {URL}

30 分 interview (`customer_dev_w5.md` の枠) に応じていただければ、カード課金不要・¥1,500 Amazon ギフト でのお時間御礼、そのまま ¥5,000 分の API credit (10,000 req 相当) を Stripe Customer.balance に付与します。

断りも歓迎です。一筆で十分です。

梅田 茂利 / [HANDLE]
```

---

## 7. 倫理ガードレール (やらない事、明文化)

1. **1 投稿の @-mention は 最大 2 名**。それ以上は spray、spam 判定、相手のミュート 即発動。
2. **mass DM スクリプト 全面禁止**。本 doc のテンプレを **1 通ずつ手で編集せず** bulk 送信する行為は、全 category で禁止。
3. **偽「拝読しました」禁止**。「{相手記事タイトル}」欄は 実際に 読んだ記事のタイトル で埋める。読んでいないなら、その pitch は出さない or 読んでから出す。
4. **偽 urgency 禁止**。「先着 10 名」「今だけベータ」等、事実でない scarcity を書かない (`launch_compliance_checklist.md` §4 / 景表法)。
5. **RT / follower / GitHub star の購入 全面禁止**。
6. **HN / Reddit での sockpuppet upvote 禁止** (`launch_dday_matrix.md` §6 tone check と整合)。
7. **PR エージェンシーの "auto-reply seeding" 禁止**。もし将来 PR 代理店を使う日が来たら、媒体側に代理関係を明示。
8. **招待制 Slack / Discord のログスクレイピング 禁止**。参加している channel の公開規約に沿った self-promo のみ (`docs/launch_dday_matrix.md` §4 の「invite 制、community fit 前提」と整合)。
9. **個人メールアドレスの平文掲載禁止**。本 doc / tracker CSV の双方で、公開 form URL / 公開 X handle / 公開 GitHub profile のみ。
10. **「拡散してください」framing 禁止**。C テンプレは提供先行 (記事 / LT / credit 寄贈) で設計済み。

---

## 8. 優先順位 / 時間割

`docs/launch_dday_matrix.md` §1 の timeline と干渉しない outreach 枠:

| 日時 (JST) | アクション | 枚数 | テンプレ |
|---|---|---|---|
| **D-1 (5/5) 18:00-21:00** | Warm contacts (既に面識あり or 過去 positive やりとり) 10 名 personalize | 10 | R1 / C / E 混在、手書き per-recipient |
| **D-Day (5/6) 14:00-14:30** | 記者 pitch 3 名 (優先度 高、Publickey / 日経 xTECH / ITmedia) | 3 | R1 |
| **D-Day (5/6) 14:30-15:15** | コミュニティリーダー 5 名 (Zenn MCP タグ top + X 高 engagement 2 + connpass 主催 1) | 5 | C |
| **D-Day (5/6) 15:15-16:00** | B2B パートナー 10 社 (Smithery / Pulse MCP は D0 必須、freee / MF は公開プレス窓口に short note) | 10 | B |
| **D+3 (5/9)** | 記者返信なし 3 名へ R2 follow-up (HN score / Zenn 反応 を添える) | ≤3 | R2 |
| **D+7 (5/13)** | 初動 KPI (signup / paid / engagement) が目標下限を超えていれば second wave (Category B 残り + Category C 4-8 社) | 10-15 | C / B |

**注**: D-Day 18 通 + D-1 warm 10 通 = 計 28 通/48h。これ以上は品質保てない。D-Day は broadcast・監視・metrics と並走するため outreach 枠は最大 3 時間。

---

## 9. 運用 / 進捗管理

- 進捗 CSV: `research/outreach_tracker.csv` (62 slot pre-seed 済)。
- 1 通ごとに `outreach_date` / `contact_handle` 更新。返信時 `response_*` / `outcome` 埋める。
- 週次で reply rate / conversion 集計。reply rate 10% 割れならテンプレ書き直し。
- 実名空欄は「未送信」扱い。launch 後 2 週間で埋められない slot は削除 (実名を作るな)。

---

## 10. Report (自己検証)

- **総スロット数**: Category A 15 / B 20 / C 10 / D 7 / E 10 = **62 スロット** (≈70 目標のうち、E カテゴリ を 10 で固定し、D を 7 に絞った結果)。
- **公開情報で 実名を埋められたもの**: 1 件のみ — **新野 淳一 (Publickey 運営者、A07)**。出典 `publickey1.jp/about-us.html`。他の 61 slot は ユーザーが一次ソースから埋める placeholder。B / D / E の検索手順は §2-5 の表に明示済み。
- **公開 URL を 確認済 contact**: 6 件 — ITmedia (`corp.itmedia.co.jp/media/inquiry/articles/`)、日経 xTECH (`support.nikkeibp.co.jp/app/answers/list/p/235`)、Publickey (`comment [at] publickey.jp`)、CodeZine (`codezine.jp/offering`)、ASCII.jp (`ascii.jp/support/`)、デジタル庁 (`forms.office.com/r/QVZ0HSP6Se`)、MAFF (`maff.go.jp/j/apply/recp/index.html`)。
- **成功確率が最も低い Category**: **A (tech 媒体 記者)**。理由: (1) 日本媒体の取材 capacity 限定、(2) launch ネタ単独の記事化率 < 5%、story arc 2 本目 (数字変化 / 面白い failure / 人物) が必要、(3) D-Day 3 件 pitch で 2 件返信も危うい。**「launch 週の短期 coverage」ではなく「3-6 ヶ月の関係構築」フレームで運営**。R2 より「6 ヶ月後 再連絡 list」保管の期待値が高い。
- **標準 playbook 外の D-Day 1 手**: **データ誤記 bug bounty**。HN / X thread で「誤記見つけたら修正申告 form から送信、初回 3 名に ¥5,000 Amazon ギフト、修正は public diff で commit」と明示。狙い: (a) 技術 audience に中身を見せる動線、(b) 後日 記者 pitch に「読者参加で訂正が回る」独自 narrative、(c) 行政窓口 (§4) に「ユーザー参加型訂正フロー」を提示できる。予算は `customer_dev_w5.md` §3.6 の ¥45,000 と別枠、¥30,000 capping。景表法上「懸賞」表示要否のみ launch 前確認。
