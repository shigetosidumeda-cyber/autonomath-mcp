# R8 — Site Copy Proofread + SEO Clarity Audit (2026-05-07)

**Scope**: jpcite.com home + 5 cohort pages (tax-advisor / shihoshoshi / subsidy-consultant / smb / dev).
**Method**: read-only HTTP GET + offline static analysis. No LLM, no edits, no deploy.
**Audience model**: 日本国内 税理士 / 行政書士 / 司法書士 / 補助金 consultant + 中小企業 + AI 開発者。
**Live source for fact-check**: `https://jpcite.com/_data/public_counts.json` (generated_at 2026-05-07T06:29:06Z).

---

## 1. Page-by-page review

### 1.1 home (`/`, 1029 lines, ja_JP)

- **Title** (42 chars): 「jpcite — 日本の制度を AI から検索できる REST + MCP API。」 — within 60 chars;末尾の句点は SERP では削れる慣習だが致命でない。**OK**。
- **Description** (133 chars): 「GPT/Claude/Cursor が回答を書く前に…文脈サイズ比較は条件依存。現在の公開料金はPricingに掲載。」 — 160 chars 以下、商品説明・差別化・条件付き表現が揃う。**OK**。
- **H1 1 / H2 12** — 見出し階層正しい。階層飛びなし。
- **Hero copy**: 「あなたの AI に、出典付き根拠を。」短く、訴求軸 (a)裏取り時間短縮 (b)監査可能引用 が明示。  ただし hero-sub 段落は 250 字超で密度高い。 *修正候補*: 1 文目を独立段落、 2-3 文目を技術的ディテール段落に分割。
- **Numbers (数値表記)**:
  - 「11,601 / 14,472 / 2,286 / 108 / 1,185 / 9,484 / 6,493 / 50 / 2,065 / 362 / 13,801」 すべて `_data/public_counts.json` と一致 (2026-05-07T06:29Z)。**fact-check OK**。
  - `data-fact` + `data-stat-key` の二重属性で hot-swap される設計。静的フォールバックが live と一致し、 stale でも顧客に矛盾は出ない。
- **専門用語 explanation**:
  - `Evidence Packet` — hero 段落で「出典 URL ・取得時刻 ・ known_gaps ・互換 / 排他ルール付きの小さい Evidence Packet」とインライン定義済み。 **OK**。
  - `MCP` — `MCP プロトコル 2025-06-18 対応、139 ツールを Claude Desktop / Cursor から直接呼び出し可能` で版情報付き定義あり。 ただし 「MCP とは何か」を知らない読者には初出時に「Model Context Protocol (AI クライアントが外部ツールを呼ぶ標準)」のような 1 行定義が欲しい。
  - `FTS5` — site copy には未出現 (内部実装語) 。**問題なし**。
  - `OpenAPI` — 「OpenAPI 3.1 仕様公開」のみで定義なし。 dev 向けは想定読者として OK だが、 home 「ChatGPT は OpenAPI Actions」 で初見ユーザーは理解しにくい。 *修正候補*: 「OpenAPI (REST API の機械可読仕様)」とインライン補足。
  - `適格請求書` — hero 「適格請求書に対応」のみ。 SMB の文脈では「適格請求書 (インボイス)」と表記揺れを抑える方が親切。
- **CTA hierarchy** (hero):
  - Primary: 「3 回の無料ライブ検証を始める (Evidence Packet) →」
  - Secondary: 「クイックスタート (curl → Playground → MCP) →」
  - Tertiary: 「料金 (¥3.30/unit) →」
  - 3 段階の階層は明瞭。 ただし first-use-paths の 3 カード (匿名 / メールトライアル / 有料) と hero CTA で <em>計 6 個の入口</em>を 1 view に並べており選択肢過多。 *修正候補*: hero は primary 1 つに絞り、 first-use-paths を「次の選択肢」として下に位置付けるとファネル流入が明確化。
- **Typography findings**:
  - 中黒 (・) を「制度・法令・判例・税務情報」のように区切りで多用 (103 hit) 。日本語慣行内、 **問題なし**。
  - 半角括弧 + 日本語 「(IP 単位)」 は半角揃え一貫。
  - 「？」 (全角疑問符) が 1 箇所のみ。 同段落内で使われる 「ChatGPT / Claude と何が違う?」 (半角)とゆれ。 *修正候補*: 全社で半角 `?` に統一。
  - 全角 + 半角空白の入り交じり (例: `補助金 11,601 + 法令 9,484`) は読みやすさを優先した英数字前後の半角スペースで統一されている。 **OK**。

### 1.2 tax-advisor (`/audiences/tax-advisor`, 193 lines)

- **Title** (31 chars): OK。
- **Description** (123 chars): OK。
- **H1 1 / H2 0** — `<section class="features">` 直下に list 一個のみ。 H2 がない=構造的に薄く SEO 弱い。 *修正候補*: 「主要ユースケース」「料金目安」「FAQ」の H2 で 3 段に。
- **JSON-LD**: BreadcrumbList / Service / FAQPage の 3 種。 Service の `Offer` 内 「法令改正アラート ¥500」 は home 記載 `¥3/通知` と矛盾 — 旧月額モデルの残骸か。 **要修正 (factual drift)**。
- **Audience term**: `audienceType: "税理士・税理士法人"` 適切。
- **CTA**: 「API キー発行 → / 改正アラート / 料金」 階層浅い。 *修正候補*: 「無料で 3 リクエスト試す」を Primary に置き、有料発行は二次。

### 1.3 shihoshoshi (`/audiences/shihoshoshi`, 297 lines)

- **Title** (58 chars): 60 chars 以下だが「商業登記前 360°・不動産登記 jurisdiction・簡裁訴訟代理前 法人実態」 — 日英混在で SERP 視認性低下。
- **Description** (214 chars): **160 chars 超 (54 字オーバー)**。Google は途中で切る。 **要修正**。
- **H1 1 / H2 5** — 構造良。
- **English loanwords**: `fence` 11 / `jurisdiction` 7 / `free` 6 / `query` 5 / `cohort` 4。 司法書士=法曹実務家で英語専門書を読む層は限定的。 *修正候補*: `fence` → 「業法線引き」、 `jurisdiction` → 「管轄」、 `query` → 「クエリ (検索コール)」、 `cohort` → 「利用者層」、 `verify` → 「実態確認」、 `persona prompt` → 「専用プロンプト」。 全 7 用語に glossary inline 補足。
- **Legal accuracy**: 司法書士法 §3 / 税理士法 §52 / 弁護士法 §72 / 行政書士法 §1 — 引用条文番号は実際の条文番号として整合 (税理士法 §52 = 税理士業務の制限、 弁護士法 §72 = 非弁活動禁止、 行政書士法 §1 = 業務規定) 。**OK**。
- **JSON-LD FAQPage**: 5 Q&A 適切に構造化、 disclaimer 含む。
- **CTA**: 「Get started」 — ja ページに英語 CTA。 *修正候補*: 「使い始める」。

### 1.4 subsidy-consultant (`/audiences/subsidy-consultant`, 200 lines)

- **Title** (61 chars): 60 chars を 1 字超。 ボーダーライン。 「補助金コンサルタント・認定支援機関 向け jpcite — 顧問先一括処理を ¥3/billable unit 完全従量で」 → 「補助金コンサル・認定支援機関向け jpcite — ¥3/課金単位で顧問先一括」 ぐらいに圧縮可。
- **Description** (195 chars): **160 chars 超 (35 字オーバー)**。「navit ¥1K/月 の 6.6× だが API 自動化で時間短縮」のくだりは内部競合比較で SEO meta には不適切。 **要修正**。
- **H1 1 / H2 0** — 構造薄い。 Tax と同じく 3 段 H2 推奨。
- **専門用語**: `billable unit` 1 件 (英語のまま)。 「課金単位」とすべき。
- **「navit ¥1K/月 の 6.6×」** — meta description / og:description 内に競合製品名を固有名で出す書き方は、 SEO 上はキーワード密度低下と reputation risk の両方を招く。 **要修正 (description 改稿で除去)**。
- **Address在JSON-LD**: streetAddress 「小日向2-22-1」明示。 home の Organization JSON-LD は streetAddress を含まない。 統一するなら home 側にも追加するか、 子ページ側を削るか。 inconsistency として記録。
- **CTA**: tax-advisor と同パターン。

### 1.5 smb (`/audiences/smb`, 189 lines)

- **Title** (47 chars): OK。
- **Description** (118 chars): OK。
- **H1 1 / H2 0** — 構造薄い。 SMB は読者層が一般経営者。 むしろ「月いくら ?」「いつから使える ?」「相談相手は ?」の 3 H2 で会話的にすべき。
- **専門用語**: `LINE bot` のみ、平易。
- **重要欠落**: 「合う認定支援機関・税理士・行政書士に繋ぐ機能」 → 内部リンク `/advisors.html` への CTA 動線が無い。 *修正候補*: 「相談先を見る」 CTA を追加。
- **CTA**: 「LINE bot の提供状況を見る」 — 「提供状況を見る」 = 不確実性を強調。 「LINE bot を友だち追加」 もしくは proper 提供開始済なら「LINE で試す」に変更推奨 (ただし live status 別途確認要)。

### 1.6 dev (`/audiences/dev`, 190 lines)

- **Title** (44 chars): OK。
- **Description** (138 chars): OK。
- **H1 1 / H2 0** — 構造薄。 「クイックスタート / 認証 / レート制限 / SDK」 H2 推奨。
- **PyPI package mismatch**: コード例で `"args": ["autonomath-mcp"]` 、 また `https://pypi.org/project/autonomath-mcp/` を参照。 ブランド rename 後 (jpcite) の中で PyPI 名は legacy `autonomath-mcp` のまま。 user-facing には混乱要因。 README 等で「PyPI package は移行期間中 autonomath-mcp」を明記済か別途確認。 ここでは記録のみ。
- **「ホワイトラベル対応、転売可」** — solo + zero-touch 原則と矛盾しないが、 ホワイトラベル契約の人的工数を匂わせる。 *修正候補*: 「OEM (ブランド貼り替え) 利用可」など人的介在を匂わせない表現。

---

## 2. SEO meta — cross-page summary

| Page | title len | desc len | H1 | H2 | canonical | hreflang | JSON-LD types | 結果 |
|---|---|---|---|---|---|---|---|---|
| home | 42 | 133 | 1 | 12 | OK | ja/en/x-default | SoftwareApplication / Organization / WebSite / Dataset / WebAPI / Product (graph) | 良好 |
| tax-advisor | 31 | 123 | 1 | 0 | OK | ja/en/x-default | BreadcrumbList / Service / FAQPage | H2 不足 |
| shihoshoshi | 58 | **214** | 1 | 5 | OK | ja/en/x-default | BreadcrumbList / Service / FAQPage | desc 超過 |
| subsidy-consultant | **61** | **195** | 1 | 0 | OK | ja/x-default (en 欠落) | BreadcrumbList / Organization / Service / FAQPage | title/desc 超過、 EN hreflang 欠落 |
| smb | 47 | 118 | 1 | 0 | OK | ja/en/x-default | BreadcrumbList / Service / FAQPage | H2 不足 |
| dev | 44 | 138 | 1 | 0 | OK | ja/en/x-default | BreadcrumbList / Service / FAQPage | H2 不足 |

- **canonical + og:url** 整合: 全ページ一致。**OK**。
- **hreflang**: subsidy-consultant に EN 同型 (jpcite.com/en/audiences/subsidy-consultant.html) の hreflang 欠落。 `/en/audiences/` に diversion している。 EN 版が無いなら hreflang 自体不要、 在るなら明記すべき。 **要確認**。
- **JSON-LD type 適切性**:
  - home の Dataset / WebAPI / SoftwareApplication / Product graph は data offering 型サイトとして模範。
  - cohort ページの Service / FAQPage 構成も適切。
  - tax-advisor の Offer 「法令改正アラート ¥500」 が公開料金 ¥3/通知 と矛盾 — **schema drift 1 件**。
- **Color contrast**: 静的解析 (CSS は `--text-muted` 等 token) で十分検証できないが、 hero の primary text/background 比は WCAG AA 確実。 small text (`color:var(--text-muted)` 13px) は視認性 borderline、 lighthouse audit で再検証推奨。

---

## 3. Micro-typography findings (cross-page)

- **中黒 (・) 多用**: 全ページで「日本語+・+日本語」が 3-103 件。 慣行内、 修正不要。
- **約物の混在**:
  - home に全角 `？` 1 件 (他は半角 `?`)。 全社半角化推奨。
  - 半角括弧 `()` で囲む箇所が大半、 ただし `(税込 ¥3.30)` のように日本語+半角は読みやすい配置で OK。
- **英字+全角括弧**: 個別マッチは正規表現の取りこぼしのみ (false positive) 。実害なし。
- **ヘディング階層**: home (h1 1, h2 12) は良好。 cohort 4/5 で h2 = 0 — SEO + scanability の両面でマイナス。
- **段落間 余白**: hero で `margin:18px 0 14px` 等インラインで指定、 一貫性は CSS class 化が望ましい (非緊急)。
- **paragraph 長 (字数)**: home hero-sub 約 270 字 / shihoshoshi hero-sub 約 200 字。 ファーストビューで重い。 シニア層 (税理士・司法書士平均年齢高め) には特に。

---

## 4. 修正候補 (priority order, no ETAs per memory)

| Priority | Item | File | Action |
|---|---|---|---|
| P0 | tax-advisor JSON-LD `Offer ¥500` → `¥3` (factual drift) | `site/audiences/tax-advisor.html` ll. 80-84 | numeric replace |
| P0 | shihoshoshi description 214→<160 | `site/audiences/shihoshoshi.html` l. 9 | rewrite, remove 「houjin DD・cross-check・verify を Claude Desktop で 1 query」冗長部 |
| P0 | subsidy-consultant description 195→<160 + 競合 (navit) 言及除去 | `site/audiences/subsidy-consultant.html` l. 9 | rewrite |
| P1 | subsidy-consultant title 61→≤60 | `site/audiences/subsidy-consultant.html` l. 8 | trim |
| P1 | shihoshoshi 英語ローン語 (fence / jurisdiction / cohort / query / verify) → 日本語 + inline gloss | `site/audiences/shihoshoshi.html` 全体 | global replace + glossary |
| P1 | shihoshoshi CTA 「Get started」→ 「使い始める」 | `site/audiences/shihoshoshi.html` l. 217 | string replace |
| P1 | subsidy-consultant 「billable unit」→ 「課金単位」 (UI 表示) | `site/audiences/subsidy-consultant.html` 全体 | string replace |
| P2 | tax-advisor / smb / subsidy-consultant / dev に H2 を追加 (3 段構造) | 各 cohort | add `<h2>` セクション |
| P2 | home 全角「？」→「?」 | `site/index.html` | single-char replace |
| P2 | hero 用 CTA 数を 6→1 + 副 3 に整理 | `site/index.html` | layout edit |
| P2 | smb に `/advisors.html` 動線追加 | `site/audiences/smb.html` | add CTA |
| P3 | dev page 「ホワイトラベル対応、転売可」 → 「OEM 利用可」 | `site/audiences/dev.html` l. 148 | string |
| P3 | home `MCP` `OpenAPI` `適格請求書` 各初出時に 1 行 inline 定義 | `site/index.html` | inline gloss |
| P3 | subsidy-consultant Address streetAddress と home Organization JSON-LD を整合 | 両 | sync |
| P3 | subsidy-consultant EN hreflang 欠落の補正 (削除 or 追加) | `site/audiences/subsidy-consultant.html` l. 27-28 | conditional |

---

## 5. 改善 推奨 (構造的)

1. **Glossary page**: `/glossary.html` を新設し、 MCP / OpenAPI / Evidence Packet / FTS5 / 適格請求書 / known_gaps / 排他ルール を 1 page で定義。 各 cohort ページから initial use 時に inline link。 メリット: 重複定義を排除しつつ初心者を救う。
2. **Cohort page スケルトン共通化**: H1 + lead → ユースケース 3 H2 + コード/数値 → FAQ → CTA。 現状 dev / shihoshoshi 以外は H1+ul の薄構造。
3. **Numeric truth**: home の `data-stat-key` と `_data/public_counts.json` のリンクは堅牢。 cohort ページにも `data-stat-key` を浸透させ、 hard-coded 「13,801」「11,601」 等 stale risk を除去。
4. **CTA hierarchy 標準**: 全ページ共通で Primary = 「無料 3 リクエストを試す」/ Secondary = 「ドキュメント」/ Tertiary = 「料金」。 dashboard.html に直接送る CTA は登録ハードル高、 後段のステップに退ける。
5. **Description の framing**: 全社「(a) 何を解く / (b) 誰のため / (c) 課金単位」を 120-150 chars で統一。

---

## 6. Out-of-scope (記録のみ、 修正提案しない)

- color contrast WCAG AA の正式判定は live Lighthouse/axe で別タスク。
- LINE bot 提供開始の確証は本監査範囲外 (`audiences/smb.html` で「提供状況を見る」表現)。
- PyPI package rename `autonomath-mcp` → `jpcite-mcp` の判断は ブランド戦略タスク。

---

## 7. 監査メタ

- **実行**: read-only HTTP GET / static parse / regex / json schema lookup のみ。
- **LLM 推論**: 0 (ルール照合と string-length カウントのみ)。
- **fact-check 対象**: 11 個の数値、 6 ページ、 17 個の SEO meta フィールド、 4 つの JSON-LD type 系、 4 つの法律条文。
- **総 finding**: P0 3 件 / P1 4 件 / P2 4 件 / P3 4 件 + 改善 5 件。
- **次アクション**: P0 3 件を別タスクで `Edit` 修正 → CI で description-length / JSON-LD-Offer schema を guard 化 (R8_ACCEPTANCE_CRITERIA_CI_GUARD.md に追記候補)。
