# jpcite Publication Targeting Plan — 2026-05-11

作成日: 2026-05-11 / 対象: organic 自然発見経路 17 publication / 入力 article draft 8 本 (`docs/announce/`)

## このドキュメントの読み方

- **序列無し**: 17 publication は **並列** に列挙。「最初に X」「Phase 1」等の優先順位は付けない。AI が全媒体並走で submit する前提。
- **既存 draft 流用度** = `流用可` / `改稿要` / `新規必要` の 3 段階。8 本既存 draft (zenn / note / prtimes / zeirishi_shimbun / tkc_journal / gyosei_kaiho / ma_online / shindanshi_kaiho) の活用先を可能な限り横展開する。
- **publish 手順** = account 登録 → submit form → editor connect 経路。**営業電話・PR 代理店経由は禁止**、組織既存の編集部メールアドレスまたは public submission form のみ。
- **fee** = publish 費用。原則 organic only → `free` 一択、業界誌で寄稿料 entry がある場合のみ「none (寄稿は原稿料 0 円が業界標準)」と明記。
- **失敗時 fallback** = 当該 angle で reject された場合の改稿軸。

---

## 入力: 既存 article draft 8 本の review summary

PUBLISH_ORDER_2026_05_11.md の audit を踏まえた使い回し可能性。

| draft 元 ID | green/yellow | 主たる切口 | そのまま使える target | 改稿で広げられる target |
|------------|--------------|------------|-----------------------|-------------------------|
| zenn_jpcite_mcp.md | green | MCP architecture + 4 surface 接続 + Evidence Packet 設計 | Zenn / dev.to (翻訳) / Hacker News (英訳) | Qiita / Hashnode / Lobste.rs |
| note_jpcite_mcp.md | green | 起業ストーリー + 5 商品 + 7 業法 fence | note / 中小企業診断士界 (改稿) | Product Hunt (英訳) / 弁護士ドットコム |
| prtimes_jpcite_release.md | green | 公式リリース文体、6 源泉横断、5 商品料金例 | PRTIMES / @Press (転用) / 日経電子版 ニュースリリース | 信用金庫月報 (改稿) |
| zeirishi_shimbun_jpcite.md | yellow (¥3/req patch) | 税理士事務所 ROI、§52 fence 3 層 | 税理士新聞 / 月刊 税理 (改稿) | TKC 月報 |
| tkc_journal_jpcite.md | yellow (¥3/req patch) | 7 業法 disclaimer 階層 + TKC 連携 | TKC 月報 / 月刊 会計人コース (改稿) | 日本公認会計士協会 機関誌 |
| gyosei_kaiho_jpcite.md | yellow (¥3/req patch) | 行政書士法 §19 fence + 許認可 chain | 月刊行政書士 / 月刊登記情報 (改稿) | 弁護士ドットコム (許認可文脈) |
| ma_online_jpcite.md | yellow (¥3/req patch) | 中小 M&A DD recipe r03 + 3 業法 fence | M&A Online / 月刊 M&A (改稿) | 日本 M&A センターパートナー誌 / 信用金庫月報 |
| shindanshi_kaiho_jpcite.md | yellow (¥3/req patch) | 認定支援機関 月次伴走 + 中小企業支援法 + §52 | 中小企業診断士界 / 月刊企業診断 | 信用金庫月報 (公的伴走文脈) |

**summary**: green 3 本 / yellow 5 本 (`¥3/req` 単価 + ROI 数字 patch のみ)。新規執筆を要する angle は後段の **5 publication** (Qiita / dev.to / Hashnode / Hacker News / Product Hunt / Lobste.rs / @Press の英訳・PR 写し換え) のみ。**既存 draft は 8 本中 8 本が何らかの publication に流用可**。

---

## A. 技術コミュニティ (5 publication)

### A1. Zenn (zenn.dev)

| field | value |
|-------|-------|
| 載りやすい angle | 「日本 RAG API の design 哲学 + MCP integration の 1 行 install」。Evidence Packet (`source_url + fetched_at + content_hash`) 必須化と FTS5 + sqlite-vec の 2 階建て検索が技術系 reader に刺さる。`uvx autonomath-mcp` 1 行で Claude Code に追加できる点を tag `mcp` `claudecode` `rag` で拾われる。 |
| 既存 draft 流用度 | **流用可** (zenn_jpcite_mcp.md は zenn 用 frontmatter 完備、type: tech、topics 6 個入り) |
| publish 手順 | (1) zenn.dev signup → GitHub 連携 → (2) `npx zenn-cli@latest init` で local repo に jpcite repo を bind → (3) `articles/<slug>.md` に既存 draft を置き `git push` → publication = "true" で即時公開 → (4) Topics Feed (`zenn.dev/topics/mcp`) に自動掲載 |
| review SLA | 即時公開 (editor review なし) |
| fee | free |
| 期待 reach | tech 系 月間 700万 PV (Zenn 公式)、tag `mcp` は新興だが Claude Code 拡大で月間数万 PV 規模、`claudecode` `rag` 累積で 1 万 PV/月 想定 |
| 失敗時 fallback | 即時公開なので reject 概念なし。stars 伸びない場合は Topic を `openapi` `stripe` 追加して再 distribute |

### A2. Qiita (qiita.com)

| field | value |
|-------|-------|
| 載りやすい angle | 「Stripe metered billing で `¥3/req` 完全従量 API を作る → SQLite FTS5 trigram + sqlite-vec で 9.4 GB を p50 50ms」。Zenn より「実装 how-to」志向、tag `Python` `FastAPI` `Stripe` `MCP` `RAG` `SQLite` で流入。新規執筆推奨だが zenn draft の technical sections (アーキテクチャ + ライセンスとデータ源) を 70% 流用可。 |
| 既存 draft 流用度 | **改稿要** (zenn draft をベースに「how-to」体に書き換え、frontmatter / topics 規約に揃える) |
| publish 手順 | (1) qiita.com signup (GitHub / Google) → (2) editor で markdown 記事作成 → (3) tags 5 個まで指定 → (4) 公開ボタンで即時 |
| review SLA | 即時公開 |
| fee | free |
| 期待 reach | 日本 dev 月間 1,000 万 UU 規模、人気 tag (Python / FastAPI) で `LGTM` がつけば feed トップ露出。`MCP` `RAG` tag は新興、累積 5,000-2 万 PV/月 想定 |
| 失敗時 fallback | LGTM 伸びない場合は tag を `OpenAPI` `Cloudflare` `Fly` 追加。または「9.4 GB SQLite を Fly.io で運用する話」と切り口を変えて再投稿 |

### A3. note (note.com)

| field | value |
|-------|-------|
| 載りやすい angle | 「税理士向け API を solo founder が組織なしで作って 5 商品出した起業ストーリー」。技術 + 起業 + 業界話の交点。note は SNS 拡散 (X / LinkedIn) 起点として強い。既存 draft (note_jpcite_mcp.md) は note 用に最初から書かれている。 |
| 既存 draft 流用度 | **流用可** (note_jpcite_mcp.md そのまま公開可、green) |
| publish 手順 | (1) note.com signup → (2) editor で markdown 風入力 → (3) ハッシュタグ (#AI / #起業 / #税理士 / #補助金) 設定 → (4) 公開 |
| review SLA | 即時公開 |
| fee | free |
| 期待 reach | note 月間 6,500 万 UU、ハッシュタグ `#起業` `#AI` で初週 数千 view、業界クラスタ拾えれば累積 1-3 万 view |
| 失敗時 fallback | リーチ伸びない場合は note のマガジン (例: 「solo founder の AI プロダクト」) を自作して他記事束ねる。または同記事を LinkedIn 全文転載 |

### A4. dev.to (dev.to)

| field | value |
|-------|-------|
| 載りやすい angle | "Japanese public-info RAG MCP server — 139 tools, 9.4 GB SQLite FTS5, 1-line `uvx` install for Claude Code / Cursor". 英語圏 AI dev 向けに 「Japan-specific RAG benchmark」「MCP design patterns」軸で出す。 |
| 既存 draft 流用度 | **改稿要** (zenn draft 全文英訳 + Japan-specific 文脈の説明追加 / 英語 reader 向けに「なぜ日本特化が necessary か」の framing を冒頭に挿入) |
| publish 手順 | (1) dev.to signup (GitHub) → (2) "Create new post" → markdown editor → (3) tags `mcp` `ai` `rag` `python` `showdev` → (4) Publish |
| review SLA | 即時公開 (community moderation あり、spam フラグ無ければ即) |
| fee | free |
| 期待 reach | dev.to 月間 800 万 UU、`#showdev` tag で初週 数百 view、「reactions ≥ 30」で community feed top 24h 露出 |
| 失敗時 fallback | reactions 30 未満なら cross-post → Hashnode / Medium で再露出 |

### A5. Hashnode (hashnode.com)

| field | value |
|-------|-------|
| 載りやすい angle | "Designing an Evidence-First MCP Server: source_url + fetched_at + content_hash on every tool response". 技術的 design pattern 寄りに切る (AI hallucination 対策視点)。Hashnode は dev.to より長文 / 技術深掘り好む傾向。 |
| 既存 draft 流用度 | **改稿要** (dev.to 版を Evidence Packet design pattern 中心に再構成、コード例 + JSON schema 例を厚くする) |
| publish 手順 | (1) hashnode.com signup → (2) 自分のドメイン (例: `bookyou.hashnode.dev`) で blog 作成 → (3) "Write" editor → markdown → (4) tags 5 個 → Publish |
| review SLA | 即時公開 |
| fee | free |
| 期待 reach | Hashnode 月間 400 万 dev、`#mcp` `#ai` `#rag` tag で 数百-千 view/月 |
| 失敗時 fallback | Hashnode の "Featured" 拾われなければ自ドメイン (`bookyou.net` の blog サブパス想定) に canonical 移動して SEO 集約 |

---

## B. 業界紙 (organic 寄稿、7 publication)

### B1. 税理士新聞 (zeirishi-shimbun.co.jp)

| field | value |
|-------|-------|
| 載りやすい angle | 「AI で取りこぼし防止 — 顧問先 100 社の月次 review を ¥3/req 完全従量で自動化」。§52 fence 設計と ROI 試算の 2 軸。税理士新聞は中堅事務所向け、「事務所経営 / 生産性 / コンプライアンス」が 3 大関心軸。 |
| 既存 draft 流用度 | **流用可 (¥3/req patch 後)** (zeirishi_shimbun_jpcite.md、L27 単価 + L46 ROI 計算式の 2 箇所修正のみ) |
| publish 手順 | (1) 税理士新聞 公式 web の「寄稿・記事提供」窓口 (info@) に寄稿企画書 (200 字概要 + 本文 .docx) を送付 → (2) 編集部 review → (3) 採用なら誌面 + web 掲載 |
| review SLA | 2-4 週 (業界紙標準、月刊紙の編集締切に依存) |
| fee | none (寄稿料 0 円が業界標準、原稿掲載は無料、有料記事広告は別枠で organic only 方針より除外) |
| 期待 reach | 税理士新聞 発行部数 約 3.5 万、web 月間 数十万 PV。掲載されれば顧問契約士業の cohort #2 「税理士 (kaikei pack)」を直撃 |
| 失敗時 fallback | reject なら angle を「業法 fence 7 本の disclaimer 自動付与」に絞り直し、月刊 税理 (中央経済社) / 税理士界 (日税連機関誌) に転載 |

### B2. TKC 月報 (TKC Journal)

| field | value |
|-------|-------|
| 載りやすい angle | 「TKC OMS の外部連携設計に jpcite を組み込む — 顧問先 master と公的情報の月次 join」。TKC ユーザは「TKC OMS / FX / e-TAX」が前提、外部 API を OMS workflow に組み込む実装イメージを示すと刺さる。 |
| 既存 draft 流用度 | **流用可 (¥3/req patch 後)** (tkc_journal_jpcite.md、req 単価 1 行 + 業法 6 番統一 patch) |
| publish 手順 | (1) TKC 全国会の「機関誌・記事提供」窓口に企画書送付 → (2) 編集部審査 → (3) 採用なら TKC 月報 + TKC ユーザ会 web 掲載 |
| review SLA | 4-6 週 (月刊、編集委員会 review あり) |
| fee | none (寄稿料 0 円) |
| 期待 reach | TKC 全国会 約 1.1 万会員、TKC 月報 発行部数 約 1 万、TKC ユーザ会員サイト UU 数万 |
| 失敗時 fallback | reject なら angle を「TKC 連携でなく税理士事務所 DX 一般論」に広げて月刊 会計人コース (中央経済社) / 月刊 戦略経営者 (TKC グループ) に転載 |

### B3. 行政書士界 (日本行政書士会連合会 機関誌)

| field | value |
|-------|-------|
| 載りやすい angle | 「許認可 eligibility chain の事前整理を ¥3/req で artifact 化 — §19 を犯さない設計」。行政書士界 (日行連) は機関誌、§19 fence の機械的担保 + recipe r05 の使い分けが reader 関心軸。 |
| 既存 draft 流用度 | **流用可 (¥3/req patch 後)** (gyosei_kaiho_jpcite.md、L56 API ¥1,200 を ¥3 base 再計算) |
| publish 手順 | (1) 日行連 広報部 (gyosei@gyosei.or.jp 系) に寄稿企画書送付 → (2) 機関誌編集委員会 review → (3) 採用なら「月刊 日本行政」誌面掲載 |
| review SLA | 6-8 週 (月刊、編集委員会 + 連合会理事 review あり) |
| fee | none (寄稿料 0 円) |
| 期待 reach | 日行連会員 約 5 万人、機関誌 発行部数 約 5 万、業務 monitor の AI 化が会員関心トピック |
| 失敗時 fallback | reject なら angle を「単位行政書士会の業務効率化研修」向けに再構成し、月刊 登記情報 (民事法務協会) / 月刊 行政書士 (テイハン社) に転載 |

### B4. M&A Online (maonline.jp)

| field | value |
|-------|-------|
| 載りやすい angle | 「中小 M&A の公開情報 DD を 5 分で artifact 化 — 弁護士法 §72 / 税理士法 §52 / 金商法 §29 の 3 業法 fence 設計」。M&A Online は中小 M&A 仲介・FAS・PE 系 reader、DD 効率化が最大関心軸。 |
| 既存 draft 流用度 | **流用可 (¥3/req patch 後)** (ma_online_jpcite.md、L51 API ¥600 + L66 ¥120/案件 を ¥3 base 再計算) |
| publish 手順 | (1) M&A Online 編集部 (editor@maonline.jp 系) に寄稿企画書送付 → (2) 編集 review → (3) 採用なら maonline.jp 掲載 + メルマガ配信 |
| review SLA | 2-4 週 (web 専業、月刊紙より速い) |
| fee | none |
| 期待 reach | maonline.jp 月間 約 200 万 PV、メルマガ会員 数万、M&A 仲介・PE・FAS reader |
| 失敗時 fallback | reject なら angle を「M&A 仲介の 1 次 screening 自動化」に再構成し、Strainer / Forbes JAPAN (M&A 特集枠) / 日経 M&A データに転載 |

### B5. 中小企業診断士界 (中小企業診断協会 機関誌)

| field | value |
|-------|-------|
| 載りやすい angle | 「認定支援機関 月次伴走を ¥3/req で支援 — 中小企業支援法 + §52 の 2 業法 fence」。診断協会機関誌は会員診断士向け、認定支援機関業務 + 補助金活用 + 経営革新の 3 軸が刺さる。 |
| 既存 draft 流用度 | **流用可 (¥3/req patch 後)** (shindanshi_kaiho_jpcite.md、L1 directive + 業法名統一 patch) |
| publish 手順 | (1) 中小企業診断協会 広報部 (info@j-smeca.jp 系) に寄稿企画書送付 → (2) 編集委員会 review → (3) 採用なら「月刊 企業診断」または「中小企業診断士界」誌面掲載 |
| review SLA | 4-8 週 (月刊、編集委員会 + 協会理事 review あり) |
| fee | none (寄稿料 0 円) |
| 期待 reach | 中小企業診断協会 約 2.7 万会員、機関誌 発行部数 約 3 万、業務支援ツールの AI 化が会員関心軸 |
| 失敗時 fallback | reject なら angle を「単位診断士会の研修教材」向けに再構成し、月刊 企業診断 (同友館) に転載 |

### B6. 弁護士ドットコムニュース (bengo4.com/topics)

| field | value |
|-------|-------|
| 載りやすい angle | 「AI が法律 / 行政情報を出力する時の業法 fence — 弁護士法 §72 を軸に 7 業法 disclaimer 階層」。法務 AI 界隈は §72 抵触リスクが共通関心軸、jpcite の「個別法律相談を一切しない設計」+ disclaimer chain 継承 ToS が刺さる。 |
| 既存 draft 流用度 | **改稿要** (note_jpcite_mcp.md + tkc_journal_jpcite.md の業法 fence sections を抜粋し、弁護士法 §72 軸で再構成。tkc draft の 7 業法 disclaimer 階層 sections (L9-L17 業法列挙 + L36-41 disclaimer 階層) を主体に rewrite) |
| publish 手順 | (1) 弁護士ドットコム編集部 (editor@bengo4.com 系) に寄稿企画書送付 → (2) 編集 review → (3) 採用なら bengo4.com/topics 掲載 |
| review SLA | 2-4 週 |
| fee | none |
| 期待 reach | bengo4.com 月間 約 6,000 万 PV、法務系最大級メディア、法務 AI 文脈で reader 拾える |
| 失敗時 fallback | reject なら angle を「企業法務担当者向け Legal AI 比較」に広げ、ビジネス法務 (中央経済社) / 月刊 法律のひろば (ぎょうせい) に転載 |

### B7. 信用金庫月報 (信金中央金庫 機関誌)

| field | value |
|-------|-------|
| 載りやすい angle | 「信金取引先の公的情報 monitor を ¥3/req で自動化 — 顧客の補助金候補・行政処分・適格事業者状態を月次 alert」。信金は中小企業伴走の主役、取引先別の公的情報 monitor が職員業務の手作業領域。cohort #7「信金商工会 organic」直撃 angle。 |
| 既存 draft 流用度 | **改稿要** (prtimes draft + shindanshi draft の認定支援機関業務章を組み合わせ、信金職員視点に書き換え。融資前 DD + 取引先 monitor + 経営支援 (中小機構連携) の 3 軸に再構成) |
| publish 手順 | (1) 信金中央金庫 信金月報編集部 (info@scbri.jp 系) に寄稿企画書送付 → (2) 編集委員会 review → (3) 採用なら信金月報 + scbri.jp 掲載 |
| review SLA | 6-8 週 (月刊、編集委員会 review) |
| fee | none |
| 期待 reach | 信金月報 発行部数 約 1 万、信金中央金庫研究員 + 信金本部経営企画 reader、信金本部の意思決定者 reach |
| 失敗時 fallback | reject なら angle を「商工会 / 商工会議所の経営指導員向け公的情報 monitor」に広げ、商工会議所月報 / 中小企業 (中小機構機関誌) に転載 |

---

## C. 公的リリース (2 publication)

### C1. PRTIMES (prtimes.jp)

| field | value |
|-------|-------|
| 載りやすい angle | 「Bookyou株式会社 が 日本公的制度 AI 横断 API『jpcite』β 公開」。公式リリースとして検索エンジン indexing + 二次転載 (livedoor / Yahoo / 日経電子版 ニュースリリース) を一括獲得。 |
| 既存 draft 流用度 | **流用可** (prtimes_jpcite_release.md、green、そのまま転載可) |
| publish 手順 | (1) prtimes.jp 法人 signup → (2) 法人登記情報 (T8010001213708) + 担当者情報 → (3) 配信原稿入稿 (markdown 不可、HTML / リッチエディタ) → (4) 媒体カテゴリ「IT / ソフトウェア」「金融 / 経済」選択 → (5) 配信予約 |
| review SLA | 営業日 1-3 日 (PR TIMES 編集 review) |
| fee | none (初回 5 リリースまで無料プラン or 30,000 円/件 単発プラン — **organic only 方針より単発 30,000 円は許容範囲外、初回無料枠のみ利用**) |
| 期待 reach | PR TIMES 月間 5,000 万 PV、媒体 7,500 社配信、二次転載で日経電子版 / Yahoo / livedoor / antenna 等に自動 indexing |
| 失敗時 fallback | reject なら angle を「適格事業者 13,801 件の AI 横断 monitor」に絞り直し再 submit、または @Press に転載 |

### C2. @Press (atpress.ne.jp)

| field | value |
|-------|-------|
| 載りやすい angle | PR TIMES と同内容、@Press は配信先媒体構成が一部異なり (主に新聞社 + 地方紙系) 補完的 reach。新興 SaaS 系 reach は PR TIMES、地方紙系 reach は @Press と棲み分け。 |
| 既存 draft 流用度 | **改稿要** (prtimes draft をベースに @Press の入稿ガイドラインに合わせ短縮 + 「企業 / 経済」「IT / モバイル / 通信」カテゴリ最適化) |
| publish 手順 | (1) atpress.ne.jp 法人 signup → (2) 法人情報入稿 → (3) 配信原稿入力 → (4) 配信予約 |
| review SLA | 営業日 2-5 日 (@Press 編集 review) |
| fee | none (初回無料枠なし、最安 30,000 円/件、**organic only 方針より見送り検討対象** — 自社 RSS / Google News サイトマップで代替可能) |
| 期待 reach | @Press 配信先 8,000 媒体、新聞社系 (毎日 / 朝日 / 読売 / 共同通信) reach が PR TIMES より厚い |
| 失敗時 fallback | fee 制約で見送り場合は自社 RSS feed (`https://jpcite.com/rss`) + Google News Publisher Center + IndexNow ping で代替 (自社 cron `index_now_ping.py` 既存活用) |

---

## D. 海外 dev / 起業向け (3 publication)

### D1. Hacker News (news.ycombinator.com)

| field | value |
|-------|-------|
| 載りやすい angle | "Show HN: jpcite — Japanese public-info MCP server (11k+ subsidies, 9k+ laws, 1-line `uvx` for Claude Code)". HN は (a) MCP / Claude Code 文脈 (b) "Show HN" (c) Japan-specific RAG 視点で front page 到達可能性あり。Evidence Packet design (`source_url + fetched_at + content_hash`) + 7 業法 fence は LLM hallucination + legal compliance 文脈で関心を引く。 |
| 既存 draft 流用度 | **改稿要** (zenn draft を英訳し、3-paragraph 短縮版を HN 本文に / submit link は `https://jpcite.com` に / コメント欄で長文 detail) |
| publish 手順 | (1) news.ycombinator.com signup (account age ≥ 30d 必要、karma 不問) → (2) "submit" → title "Show HN: jpcite — ..." → URL = `https://jpcite.com` → (3) 投稿後 30 分間 first-page chance、コメント返信で karma 集約 |
| review SLA | 即時公開 (community vote ベース、flag 多いと shadow ban) |
| fee | free |
| 期待 reach | HN front page 入りで 1 日 5-10 万 PV、front 落ちても "new" feed で 数千 PV |
| 失敗時 fallback | front page 入らず数十 PV で止まれば、24h 後に Lobste.rs / Reddit r/MachineLearning に angle を変えて再 submit |

### D2. Product Hunt (producthunt.com)

| field | value |
|-------|-------|
| 載りやすい angle | "jpcite — Public-info MCP server for Japanese subsidies, laws, M&A DD. 1-line install, ¥3/req fully metered." Product Hunt は launch day vote game、Maker comment + first-day vote が key。Topics = "AI" "Developer Tools" "APIs" "Productivity". |
| 既存 draft 流用度 | **改稿要** (note + zenn draft から marketing copy 抜粋し、PH の Tagline (60 字) + Description (260 字) + Gallery (5 image) フォーマットに整形) |
| publish 手順 | (1) producthunt.com signup → (2) "Submit a product" → (3) Tagline / Description / Topics / Gallery / Maker comment 入力 → (4) Launch 日予約 (publish 24h vote window) |
| review SLA | submit から launch まで 1-3 日 (PH staff approve) |
| fee | free |
| 期待 reach | PH launch day で 1,000-10,000 visit、top 5 入りで翌週 100,000 visit、newsletter 配信先 100 万人 |
| 失敗時 fallback | top 10 入らずなら、Indie Hackers / BetaList / Launching Next にクロス submit |

### D3. Lobste.rs (lobste.rs)

| field | value |
|-------|-------|
| 載りやすい angle | "MCP server design: source_url + fetched_at + content_hash on every tool response, anti-hallucination by construction". Lobste.rs はインバイト制 / 技術コミュニティ高品質、AI hallucination + API design + Japanese RAG benchmarks の 3 軸が刺さる。 |
| 既存 draft 流用度 | **改稿要** (dev.to + Hashnode 版を 1,500 字程度に短縮、技術 design pattern に絞る) |
| publish 手順 | (1) Lobste.rs invite 取得 (既存ユーザ紹介必要、organic 経路では Twitter / Mastodon で Lobsters ユーザに依頼) → (2) submit → URL + Tags (`programming` `ai` `databases`) → (3) コミュニティ vote |
| review SLA | 即時公開 (invite 取得後) |
| fee | free |
| 期待 reach | Lobste.rs 月間 100 万 UU、front page 入りで 数千 PV、技術深掘り好きの reader |
| 失敗時 fallback | invite 取得できない場合は Lobsters は見送り、HN + dev.to + Hashnode の 3 軸に絞る |

---

## 全 17 publication 対応度サマリ

| categ | publication | draft 流用度 | fee | 期待 reach (月間) | review SLA |
|-------|-------------|---------------|-----|------------------|------------|
| A 技術 | Zenn | 流用可 (zenn draft) | free | 700万 PV | 即時 |
| A 技術 | Qiita | 改稿要 | free | 1000万 UU | 即時 |
| A 技術 | note | 流用可 (note draft) | free | 6500万 UU | 即時 |
| A 技術 | dev.to | 改稿要 (zenn 英訳) | free | 800万 UU | 即時 |
| A 技術 | Hashnode | 改稿要 (dev.to 派生) | free | 400万 dev | 即時 |
| B 業界紙 | 税理士新聞 | 流用可 (zeirishi patch) | none | 3.5万部 | 2-4 週 |
| B 業界紙 | TKC 月報 | 流用可 (tkc patch) | none | 1.1万会員 | 4-6 週 |
| B 業界紙 | 行政書士界 | 流用可 (gyosei patch) | none | 5万会員 | 6-8 週 |
| B 業界紙 | M&A Online | 流用可 (ma patch) | none | 200万 PV | 2-4 週 |
| B 業界紙 | 中小企業診断士界 | 流用可 (shindanshi patch) | none | 2.7万会員 | 4-8 週 |
| B 業界紙 | 弁護士ドットコム | 改稿要 (note+tkc 抜粋) | none | 6000万 PV | 2-4 週 |
| B 業界紙 | 信用金庫月報 | 改稿要 (prtimes+shindanshi) | none | 1万部 | 6-8 週 |
| C 公的 | PRTIMES | 流用可 (prtimes draft) | free (初回枠) | 5000万 PV | 1-3 日 |
| C 公的 | @Press | 改稿要 (prtimes 派生) | 30,000 円 (見送り推奨) | 8000媒体 | 2-5 日 |
| D 海外 | Hacker News | 改稿要 (zenn 英訳短縮) | free | 1日 5-10万 PV (front 時) | 即時 |
| D 海外 | Product Hunt | 改稿要 (note+zenn 抜粋英訳) | free | launch day 1k-10k | 1-3 日 |
| D 海外 | Lobste.rs | 改稿要 (dev.to 短縮) | free | 100万 UU | 即時 (invite 後) |

### 流用 vs 新規執筆カウント

- **そのまま流用可**: 5 publication (Zenn / note / 税理士新聞 / TKC 月報 / 行政書士界 / M&A Online / 中小企業診断士界 / PRTIMES — yellow draft は ¥3/req patch のみ)
- **既存 draft からの改稿で対応**: 9 publication (Qiita / dev.to / Hashnode / 弁護士ドットコム / 信用金庫月報 / @Press / Hacker News / Product Hunt / Lobste.rs)
- **完全に新規執筆が必要な publication**: **0 件** (全 17 publication が既存 8 draft の流用または改稿で cover 可能)

### 角度の被り回避

- 同一 angle (例: ¥3/req ROI) を複数 publication に出さず、各 publication で **load-bearing な切口** を 1 つに絞る:
  - 税理士新聞 = ROI + §52
  - TKC 月報 = 7 業法 disclaimer
  - 行政書士界 = §19 + chain
  - M&A Online = DD recipe r03 + 3 業法
  - 中小企業診断士界 = 認定支援機関 + 中小企業支援法
  - 弁護士ドットコム = §72 + disclaimer chain ToS 継承
  - 信用金庫月報 = 取引先 monitor + 融資前 DD
- 技術系も Zenn (MCP architecture) / Qiita (Stripe + FTS5 how-to) / dev.to (Japan RAG benchmark) / Hashnode (Evidence Packet design pattern) / HN (Show HN: 1-line install) / Lobsters (anti-hallucination by construction) で重複を避ける

---

## organic only 方針の遵守確認

| 禁則 | 本 plan の対応 |
|------|----------------|
| 営業電話 editor connect | publication の public submission form / 編集部メール窓口のみ使用 |
| PR 代理店依頼 | 全 publication 自社 (Bookyou株式会社 info@bookyou.net) で submit |
| 広告枠購入 | 17 publication 中 fee 発生は PR TIMES 単発 30,000 円 / @Press 30,000 円 のみ、両方とも **初回無料枠** or **見送り** で対応、organic only 維持 |
| X ヶ月以内 publish | スケジュール pin 無し、submit 完了は AI が並列ですぐ実行可能、SLA は publication 側の review window のみ |
| 「最初に X 媒体」 | 17 publication 並列 submit (各 form / メール送付は 17 並列タスクとして AI が即時実行可能) |
| Phase 1 / MVP publish | 段階分割無し、17 publication 同時並列 |
| 旧 brand 露出 | 8 draft 全てで「税務会計AI」「AutonoMath」「zeimu-kaikei.ai」「jpintel」言及無し audit 済 (PUBLISH_ORDER_2026_05_11.md の green 判定通り)、yellow draft も旧 brand は green 維持 |

---

## 編集 connect の優先窓口 (organic 限定)

各 publication の公式 submission form / 編集部メールアドレス (推測 + 公開情報ベース、submit 前に **最新版を web で再確認** 推奨):

| publication | submission 窓口 |
|-------------|------------------|
| Zenn | GitHub 連携 → zenn.dev/dashboard で publish (editor 不要) |
| Qiita | qiita.com/edit で publish (editor 不要) |
| note | note.com/notes/new で publish (editor 不要) |
| dev.to | dev.to/new で publish (editor 不要) |
| Hashnode | hashnode.com/new で publish (editor 不要) |
| 税理士新聞 | 公式 web の「お問い合わせ・寄稿」窓口 (info@zeirishi-shimbun.co.jp 系) |
| TKC 月報 | TKC 全国会 広報部 / TKC 全国会 会員向け窓口 (公式 web より) |
| 行政書士界 | 日本行政書士会連合会 広報部 (info@gyosei.or.jp 系) |
| M&A Online | maonline.jp 編集部 (info@maonline.jp 系) |
| 中小企業診断士界 | 中小企業診断協会 広報部 (info@j-smeca.jp 系) |
| 弁護士ドットコム | bengo4.com 編集部 (editor 系メール、または公式 web の寄稿窓口) |
| 信用金庫月報 | 信金中央金庫 信金中金月報 編集部 (scbri.jp 系) |
| PRTIMES | prtimes.jp で法人 signup → 配信 form (editor 不要) |
| @Press | atpress.ne.jp で法人 signup → 配信 form (editor 不要) |
| Hacker News | news.ycombinator.com で account 作成 → submit form (editor 不要) |
| Product Hunt | producthunt.com で submit form (editor 不要) |
| Lobste.rs | invite 取得後 lobste.rs/stories/new で submit (editor 不要) |

**editor 不要 publication 数**: 10 件 (Zenn / Qiita / note / dev.to / Hashnode / PRTIMES / @Press / HN / PH / Lobsters)
**editor 経由 publication 数**: 7 件 (税理士新聞 / TKC 月報 / 行政書士界 / M&A Online / 中小企業診断士界 / 弁護士ドットコム / 信用金庫月報)

editor 経由 publication 7 件は 公式 web の「寄稿企画書提出」窓口に統一して並列送付。各窓口は採否 review 期間が 2-8 週でばらつくため、結果は publication 側ペースに任せる (こちらから催促・営業電話は禁則)。

---

## 計測 hook (各 publication publish 後)

PUBLISH_ORDER_2026_05_11.md の 24h 計測 KPI を **publication-aware** に拡張:

- Google Search Console: `referrer:` クエリで publication 別 referral session 分解
- Cloudflare Analytics: Top referrers で `zenn.dev` / `qiita.com` / `note.com` / `dev.to` / `prtimes.jp` 等 ranking
- jpcite usage_events: `referer` header で AI agent UA (Claude / GPT / Cursor / Codex) と publication referrer の cross-tab
- X-Client-Tag: 顧問先 attribution の cohort #2 (税理士) 流入 source 特定

publication 別 referral session の中央値が baseline (organic search 単独) を 24h で超えていれば成功シグナル。超えなければ angle 改稿 → 別 publication への転載で再 distribute。

---

## まとめ

17 publication × 4 categories (A 技術 5 / B 業界紙 7 / C 公的 2 / D 海外 3)、全て organic only 経路、既存 8 draft で **流用可 8 件 / 改稿可 9 件 / 新規執筆必要 0 件**。fee は free / none が 15 件、fee 発生 2 件 (PR TIMES 初回無料枠 + @Press 見送り推奨) で organic only 方針維持。並列 submit 前提、AI が 17 form / 7 編集部メール送付を即時実行可能。
