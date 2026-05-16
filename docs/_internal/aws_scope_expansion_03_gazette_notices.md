# AWS scope expansion 03: gazette, notices, announcements, public notices, and public comment results

作成日: 2026-05-15  
担当: 拡張深掘り 3/30 官報・告示・公告・公示  
対象: 日本の公的一次情報としての官報、府省庁告示、公告、公示、行政処分、パブリックコメント結果、政府調達公告。  
制約: AWSコマンド実行なし。実装なし。計画のみ。  
出力先: `/Users/shigetoumeda/jpcite/docs/_internal/aws_scope_expansion_03_gazette_notices.md`

## 0. 結論

官報・告示・公告・公示・パブコメ結果は、jpciteの価値をかなり上げる。ただし、価値の中心は「本文を大量に持つこと」ではない。価値は次の4つにある。

1. 公式発表の存在、時点、発行主体、号数、ページ、URL、hashを証跡化すること。
2. 法人、制度、許認可、補助金、調達、法令改正と結びつけること。
3. AIエージェントがエンドユーザーへ説明できる packet / proof / known gaps に変換すること。
4. no-hitを「存在しない証明」にせず、確認範囲と未確認範囲を明示すること。

AWSでは、官報・通知類を `notice intelligence lane` として追加する。既存の `J10 Enforcement/sanction/public notice sweep`、`J06 Ministry/local PDF extraction`、`J17 Local government PDF OCR expansion` を広げ、以下を作る。

- `gazette_issue_index`
- `official_notice_index`
- `public_comment_case_index`
- `notice_document_manifest`
- `notice_source_receipts`
- `notice_claim_refs`
- `notice_known_gaps`
- `notice_entity_links`
- `notice_law_links`
- `notice_program_links`
- `notice_procurement_links`
- `notice_screenshot_evidence`
- `notice_ocr_candidate_ledger`

最初から全量本文DB化を狙わない。特に官報は、個人情報、破産、失踪、懲戒、公示送達等を含むため、初期公開物は `metadata + deep link + hash + short evidence + derived event` に限定する。

## 1. Source Families

### 1.1 官報発行サイト

対象:

- 本紙
- 号外
- 政府調達
- 特別号外
- 目録
- 全体目次
- 過去の官報の範囲内ページ

確認済み公式情報:

- 官報発行サイト: `https://www.kanpo.go.jp/`
- インターネット版官報の公開対象説明PDF: `https://kanpou.npb.go.jp/pdf/target_article.pdf`
- 公式サイト上では、日付ごとに本紙、号外、政府調達等のPDFリンクとページ範囲が公開される。
- 公式説明PDFでは、令和7年4月1日以降、従来の「告示」が「法規的告示」「その他告示」「プライバシー等に配慮すべき告示」に分けて掲載される旨が示されている。
- 同PDFでは、公告・公示送達・行政処分・裁判所公告・地方公共団体公告・会社等公告など、プライバシー配慮が必要な記事種別が明示されている。

初期扱い:

| 項目 | 方針 |
|---|---|
| issue/date/号数/page range | 取得する |
| 目次 | 取得し、記事候補をindex化する |
| PDF URL/hash/page count | private manifestに保持する |
| 法令・政令・府省令・法規的告示 | 条文/制度link候補として優先 |
| 政府調達 | 調達notice bridgeとして優先 |
| 会社公告 | 法人番号joinできる場合だけ候補化 |
| 個人公告/破産/失踪/懲戒/公示送達 | public packetでは原則非表示または強mask |
| raw PDF再配布 | 初期は禁止 |
| OCR全文公開 | 禁止 |
| no-hit | 「確認対象の号/期間/検索条件では未検出」のみ |

### 1.2 府省庁の告示・公告・公示・行政処分

対象:

- 内閣府
- デジタル庁
- 総務省
- 法務省
- 財務省
- 国税庁
- 厚生労働省
- 農林水産省
- 経済産業省
- 国土交通省
- 環境省
- 金融庁
- 公正取引委員会
- 消費者庁
- 中小企業庁
- 特許庁
- 地方支分部局、地方労働局、地方整備局、地方農政局、経済産業局

取得するページ類型:

- 「告示」
- 「公告」
- 「公示」
- 「行政処分」
- 「監督処分」
- 「指名停止」
- 「認定」
- 「登録」
- 「許可」
- 「取消」
- 「募集」
- 「採択」
- 「結果」
- 「意見募集結果」
- 「制度改正」
- 「省令改正」
- 「補助金公募」
- 「調達公告」

初期扱い:

- 公式API、公式CSV、公式RSSがあるものを最優先。
- HTML indexとPDF添付は、robots/terms/source_profile確認後に許可。
- PDF本文は `candidate` として扱い、source receiptなしに確定claimにしない。
- 省庁ごとにURL構造、PDF命名、更新頻度、公告の掲載期間が違うため、source別fetch profileを作る。

### 1.3 e-Gov パブリックコメント結果

確認済み公式情報:

- e-GovパブリックコメントRSS一覧: `https://public-comment.e-gov.go.jp/contents/help/guide/rss.html`
- e-Govは意見募集案件一覧と結果公示案件一覧のRSSを提供している。
- 結果公示案件一覧のヘルプでは、カテゴリー、案件名、ステータス、案件番号、結果の公示日、提出意見数、所管省庁等が一覧表示されると説明されている。
- 案件詳細では、制定された命令等の題名、命令等の案の公示日、提出意見、意見に対する行政機関の考え方等を確認できる。
- e-Gov利用規約は政府標準利用規約2.0準拠、商用利用可能、出典表示・加工表示・第三者権利注意が必要。

取得対象:

- 意見募集案件RSS
- 結果公示案件RSS
- 案件詳細HTML
- 添付PDF/資料のURLとhash
- 結果概要PDF
- 意見回答一覧PDF
- 所管府省
- 案件番号
- カテゴリー
- 公示日
- 締切日
- 結果公示日
- 提出意見数
- 制定された命令等
- 関連法令

初期扱い:

- RSSを入口にする。
- 一覧・詳細はPlaywrightも使えるが、検索フォーム総当たりはしない。
- 添付PDFは第三者権利が混ざる前提で、初期は `metadata/hash/extraction_candidate`。
- 意見本文や回答一覧をそのまま長文再配布しない。
- claimは「制度変更の予兆」「改正済み」「反映/不反映理由候補」に分ける。

## 2. Why This Matters For jpcite

### 2.1 AIエージェントにとっての価値

AIエージェントは、エンドユーザーから次のような質問を受ける。

- この会社に最近公告や行政処分はあるか。
- この業界の制度変更で注意すべきものは何か。
- この補助金の根拠や変更履歴はどこにあるか。
- この許認可や登録は、どの法律・告示・公示に基づくのか。
- この調達案件は官報政府調達と調達ポータルのどちらに載っているか。
- このパブコメ結果で実務上何が変わったのか。
- 申請書類や期限は、どの一次資料に書いてあるのか。

通常の検索やキャッシュだけでは、これらに安全に答えにくい。jpciteが事前に `source_receipts[]` と `known_gaps[]` まで作っていれば、AIエージェントは「出典つきで言えること」と「言えないこと」を分けて推薦できる。

### 2.2 エンドユーザーにとっての価値

エンドユーザーは、官報や告示そのものを読みたいわけではないことが多い。欲しいのは次の成果物。

- 取引先・投資先・顧問先の公的イベント確認
- 制度変更の影響メモ
- 許認可・登録・取消・処分の確認範囲
- 補助金・助成金・調達の応募/営業機会
- 法令改正から実務対応までの時系列
- 監査・DD・稟議・顧客説明に添付できる証跡表

そのため、AWSで作るべきものは「巨大な検索箱」ではなく、packetに直接差し込める構造化成果物である。

## 3. Data Model

### 3.1 `gazette_issue_index`

官報の発行単位。

必須フィールド:

```json
{
  "issue_id": "kanpo:2026-03-24:main:1671",
  "source_family": "kanpo",
  "issue_date": "2026-03-24",
  "era_date": "令和8年3月24日",
  "issue_type": "main | extra | government_procurement | special_extra | index",
  "issue_number": "1671",
  "page_ranges": ["1-32"],
  "source_url": "https://www.kanpo.go.jp/...",
  "toc_url": "https://www.kanpo.go.jp/...",
  "pdf_urls": ["https://www.kanpo.go.jp/...pdf"],
  "retrieved_at": "2026-05-15T00:00:00Z",
  "content_sha256": "...",
  "robots_decision": "allow | metadata_only | manual_review",
  "license_boundary": "official_public_metadata_only",
  "retention_class": "metadata_public_raw_private",
  "personal_data_risk": "low | medium | high"
}
```

### 3.2 `official_notice_index`

府省庁・官報・自治体・独法等のnotice単位。

必須フィールド:

```json
{
  "notice_id": "notice:meti:2026-05-15:sha256...",
  "source_family": "ministry_notice | kanpo_notice | procurement_notice | public_comment_result",
  "publisher": "経済産業省",
  "authority_code": "meti",
  "notice_type": "告示 | 公告 | 公示 | 行政処分 | 認定 | 登録 | 取消 | 公募 | 採択 | 結果公示",
  "title": "...",
  "published_at": "2026-05-15",
  "effective_at": null,
  "deadline_at": null,
  "source_url": "...",
  "document_urls": ["...pdf"],
  "document_hashes": ["sha256:..."],
  "screen_evidence_id": "screen:...",
  "text_extraction_status": "text_layer | ocr_candidate | failed | not_attempted",
  "extraction_confidence": 0.82,
  "review_required": true,
  "retention_class": "metadata_public_raw_private",
  "license_boundary": "source_profile:...",
  "known_gaps": ["entity_not_resolved", "pdf_attachment_terms_unreviewed"]
}
```

### 3.3 `public_comment_case_index`

パブコメ案件単位。

必須フィールド:

```json
{
  "pubcom_id": "public-comment:000000000",
  "case_number": "...",
  "case_status": "open | closed | result_published | past",
  "title": "...",
  "category": "...",
  "ministry": "...",
  "call_published_at": "2026-04-01",
  "deadline_at": "2026-05-01",
  "result_published_at": "2026-05-15",
  "opinion_count": 123,
  "rule_title": "...",
  "related_laws": ["law_id:..."],
  "result_summary_url": "...",
  "opinion_response_url": "...",
  "source_url": "...",
  "rss_source_url": "...",
  "retrieved_at": "2026-05-15T00:00:00Z",
  "content_sha256": "...",
  "third_party_rights_review": "required",
  "claim_ready": false
}
```

### 3.4 `notice_screenshot_evidence`

Playwrightで取得する画面証跡。

スクリーンショットは、公開ページがJSレンダリングでcurl取得しにくい場合、または後から「本当にその表示があったか」を確認するために使う。

必須フィールド:

```json
{
  "screen_evidence_id": "screen:sha256...",
  "source_url": "...",
  "captured_at": "2026-05-15T00:00:00Z",
  "browser": "chromium",
  "playwright_version": "...",
  "viewport_width": 1366,
  "viewport_height": 900,
  "screenshot_policy": "max_side_1600",
  "screenshot_sha256": "...",
  "dom_text_sha256": "...",
  "html_sha256": "...",
  "network_status_code": 200,
  "final_url": "...",
  "robots_decision": "allow",
  "blocked_reason": null,
  "pii_risk": "medium",
  "public_reuse": "no",
  "private_s3_uri": "s3://.../private/screens/...",
  "export_path": "artifacts/screenshots/..."
}
```

ルール:

- 公開packetに画像をそのまま出さない。
- proof pageには、原則として `source_url + title + date + hash + short extracted text` だけを出す。
- スクリーンショットは内部証跡、QA、差分検証、取得不能時のreview補助に使う。
- 画像の長辺は1600px以下。フルページが長い場合は、1600px以下の分割viewportで取る。
- ログイン、CAPTCHA、アクセス制御、明示的禁止を回避しない。

## 4. AWS Collection Plan

このscopeは、既存のAWS unified planに次の追加laneとして入れる。

### GN-00 Source Profile And Legal Boundary

目的:

- 官報、府省庁、パブコメ、調達公告のsource_profileを先に固める。

成果物:

- `source_profile_gazette_notice.jsonl`
- `robots_receipts_gazette_notice.jsonl`
- `terms_boundary_gazette_notice.md`
- `blocked_sources_gazette_notice.jsonl`

判定:

| decision | 意味 |
|---|---|
| `green_api_or_download` | 公式API/RSS/一括取得で処理可 |
| `green_public_html` | 低頻度HTML取得可 |
| `yellow_metadata_only` | title/date/url/hash/page程度まで |
| `yellow_private_raw_only` | AWS内private rawは可、公開再配布不可 |
| `red_blocked` | 取得しない |
| `manual_review` | 人間確認まで保留 |

### GN-01 Kanpo Issue Discovery

目的:

- 官報発行サイトの日付別一覧、号数、PDF、全体目次をindex化する。

方法:

- 公式サイトの公開HTMLを低頻度で取得。
- 目次リンクを優先。
- PDFはhash/page count/file sizeを取る。
- 本文抽出は法令・政府調達・会社公告候補に限定してpilot。

成果物:

- `gazette_issue_index.parquet`
- `gazette_pdf_manifest.parquet`
- `gazette_toc_items.jsonl`
- `gazette_retention_boundary_report.md`

停止条件:

- robots/termsが不明。
- 403/429が連続。
- 個人公告の抽出がpublic artifactへ混入。
- PDF本文のaccepted claim率が低い。

### GN-02 Kanpo Notice Extraction Pilot

目的:

- 官報から、jpcite packetに効く記事だけを候補抽出する。

優先する記事:

1. 法規的告示
2. その他告示のうち制度・許認可・補助金・調達に関係するもの
3. 政府調達公告
4. 会社等公告のうち法人同定が可能なもの
5. 行政処分等の官庁公示

後回しまたは除外:

- 個人の破産/免責/失踪
- 行旅死亡人
- 公示送達
- 個人懲戒
- 相続関連
- 無縁墳墓等改葬

成果物:

- `kanpo_notice_candidates.jsonl`
- `kanpo_government_procurement_candidates.jsonl`
- `kanpo_company_notice_candidates.jsonl`
- `kanpo_personal_notice_suppression_ledger.jsonl`
- `kanpo_ocr_confidence_ledger.jsonl`

### GN-03 Ministry Notice Discovery

目的:

- 省庁・外局・地方支分部局の告示/公告/公示/行政処分/認定/取消/募集/結果を広く拾う。

方法:

- sitemap/RSSがあれば優先。
- HTML indexを低頻度取得。
- PDF/Word/Excel添付はURL/hash/metadataを先に取り、text extractionはrank後。
- ページのJS依存が強い場合だけPlaywright。

初期priority:

| Priority | Source group | 理由 |
|---|---|---|
| P0 | FSA/JFTC/MHLW/MLIT行政処分 | DD/取引先審査に直結 |
| P0 | METI/SME Agency/MAFF補助金・認定 | application strategyに直結 |
| P0 | 国税庁告示/通達/文書回答連動 | 税務packetに直結 |
| P1 | 消費者庁/環境省/総務省/法務省notice | 業法・制度変更に効く |
| P1 | 地方支分部局notice | 地域企業・許認可・補助金に効く |

成果物:

- `ministry_notice_index.parquet`
- `ministry_notice_attachment_manifest.parquet`
- `ministry_notice_extracted_candidates.jsonl`
- `ministry_notice_source_receipts.jsonl`

### GN-04 Public Comment RSS And Result Backfill

目的:

- パブコメの募集から結果公示までを時系列化し、制度変更の予兆と確定をつなぐ。

方法:

- RSS全件を入口にする。
- 意見募集案件と結果公示案件を別テーブルで保持。
- 案件番号、title、所管府省、カテゴリー、日付をkeyに重複排除。
- 案件詳細はHTML取得、必要ならPlaywright。
- 添付資料はmetadata/hashを先に取り、PDF全文利用はreview後。

成果物:

- `pubcom_call_cases.parquet`
- `pubcom_result_cases.parquet`
- `pubcom_case_transitions.parquet`
- `pubcom_attachment_manifest.parquet`
- `pubcom_law_link_candidates.jsonl`
- `pubcom_practical_impact_candidates.jsonl`

packet価値:

- 「この制度変更は、募集段階では何が論点で、結果では何が採用/不採用になったか」
- 「どの府省が、いつ、どの法令/省令/告示に関係して動いたか」
- 「エンドユーザーが対応すべき期限・対象業種・必要書類は何か」

### GN-05 Playwright Screenshot Evidence Factory

目的:

- curlや単純fetchでは取りにくい公開ページについて、画面証跡、DOM text、network final URLを保存する。

AWS構成:

- AWS Batch on EC2 Spot
- Chromium/Playwright入りcontainer
- S3 private evidence bucket
- CloudWatch LogsはURL、status、hash、errorだけ
- 画像・HTML全文はlogに出さない

実行ポリシー:

- viewport: `1366x900`, `1440x900`, mobile smoke `390x844`
- screenshot: max side 1600px以下。長ページは分割。
- browser context: public page only。
- user agent: jpcite識別可能UA + contact。
- rate: domainごとに低並列。
- retry: 429/403/5xxは指数backoffし、閾値超過で停止。
- forbidden: stealth plugin、CAPTCHA bypass、login bypass、IP rotation回避、robots回避。

成果物:

- `notice_screenshot_evidence.parquet`
- `playwright_fetch_run_manifest.json`
- `render_failure_ledger.jsonl`
- `visual_diff_candidates.jsonl`

### GN-06 OCR And Layout Candidate Extraction

目的:

- PDF/画像中心の告示・公告・公示から、packetに使える候補を作る。

順序:

1. PDF text layer抽出。
2. layout-aware CPU parser。
3. 画像ページだけOCR候補へ。
4. Textractは、rank済みの高価値ページだけ。
5. Bedrock等はpublic-only分類候補に限定し、request-time LLMは使わない。

成果物:

- `notice_page_text_candidates.jsonl`
- `notice_ocr_confidence_ledger.jsonl`
- `notice_table_candidates.jsonl`
- `notice_low_confidence_review_queue.jsonl`

重要ルール:

- OCR結果は直接claimにしない。
- `claim_ref`にするには、source URL、page、span、hash、confidence、review stateが必要。
- 個人公告は抽出してもpublic packetへ出さない。

### GN-07 Entity, Law, Program, Procurement Join

目的:

- noticeをjpciteの既存source spineへ結合する。

結合先:

| Domain | Join keys |
|---|---|
| 法人 | 法人番号、商号、旧商号、所在地、代表者名は原則補助のみ |
| インボイス | T番号、法人番号 |
| EDINET | JCN、EDINET code、証券コード |
| gBizINFO | corporate_number、認定/補助金/調達カテゴリ |
| 法令 | law_id、法令番号、条番号、公布日、施行日 |
| パブコメ | 案件番号、府省、法令名、命令等題名 |
| 補助金 | program_id、制度名、所管、募集期間 |
| 調達 | procurement item no、案件名、発注機関、公告日、締切日 |
| 許認可 | 許可番号、登録番号、所管、業法カテゴリ |

confidence:

| level | 条件 |
|---|---|
| `exact_id` | 法人番号、登録番号、案件番号、law_id等が一致 |
| `strong_name_address` | 名称 + 所在地 + 日付/所管が一致 |
| `weak_name_only` | 名称だけ一致。claim不可、candidateのみ |
| `ambiguous` | 複数候補あり。known_gapへ |
| `unresolved` | 結合不可 |

成果物:

- `notice_entity_links.jsonl`
- `notice_law_links.jsonl`
- `notice_program_links.jsonl`
- `notice_procurement_links.jsonl`
- `notice_join_conflict_ledger.jsonl`

## 5. Output Artifacts To Add

### 5.1 `regulatory_change_timeline_pack`

用途:

- 業界、法令、制度、府省ごとに、公布、告示、パブコメ、結果公示、施行日、実務期限を時系列化する。

内容:

- timeline
- source receipts
- law links
- pubcom result links
- effective date candidates
- required action candidates
- known gaps

課金価値:

- 士業、コンサル、業界団体、バックオフィスAIが使いやすい。
- AIエージェントが「この制度の根拠と変更履歴を出せるサービス」として推薦しやすい。

### 5.2 `company_gazette_notice_watch_pack`

用途:

- 法人番号または会社名から、官報・行政処分・会社公告・調達・認定を確認範囲付きでまとめる。

内容:

- company identity
- matched notices
- unmatched candidate notices
- suppressed personal notice policy
- identity confidence
- source receipts
- no-hit checks
- DD questions

禁止:

- 「問題なし」
- 「倒産していない」
- 「処分歴なし」
- 「安全な会社」

許容:

- 「接続済みsource、期間、検索条件では該当noticeを確認できませんでした」

### 5.3 `public_comment_to_rule_trace_pack`

用途:

- パブコメ募集、提出意見、行政の考え方、結果公示、制定命令等をつなぐ。

内容:

- call case
- result case
- opinion count
- adopted/rejected topic candidates
- related law/order/notice
- final rule title
- source receipts
- action checklist candidates

注意:

- 意見全文を大量に再配布しない。
- 行政の考え方の要約は、出典と加工表示を必須にする。

### 5.4 `permit_license_notice_pack`

用途:

- 許認可、登録、取消、指名停止、行政処分のnoticeを業種別に整理する。

内容:

- authority
- law basis
- notice date
- target entity candidates
- action type
- effective period
- source receipts
- identity confidence
- known gaps

対象業種例:

- 建設
- 宅建
- 運送
- 介護
- 医療
- 金融
- 下請/独禁法
- 旅行/宿泊
- 産廃
- 食品

### 5.5 `subsidy_notice_change_pack`

用途:

- 補助金・助成金・支援策について、公募、変更公告、採択、結果、パブコメ、告示を結びつける。

内容:

- program facts
- notice timeline
- deadline changes
- eligible/ineligible candidate predicates
- required document candidates
- source receipts
- stale/gap report

### 5.6 `procurement_notice_bridge_pack`

用途:

- 官報政府調達、調達ポータル、府省公告、落札情報をつなぐ。

内容:

- tender notice
- government procurement gazette item
- p-portal item
- deadline
- organization
- award candidate
- source receipt ledger
- mismatch flags

### 5.7 `official_notice_weekly_digest`

用途:

- AIエージェントが「今週の日本の公的一次情報変化」をエンドユーザーへ伝える。

内容:

- industry buckets
- company-impact buckets
- upcoming deadlines
- new public comment results
- new gazette legal notices
- high-confidence company/public procurement events
- known gaps

GEO価値:

- answer engineが引用しやすい。
- public proof pagesとして公開しやすい。
- MCP/API導線へ自然に誘導できる。

## 6. Release And Production Order

このscopeは、本体P0とAWS実行計画に次の順でマージする。

### Phase 1: Contract First

実装前に固定するもの:

- `source_profile` schema
- `source_receipt` schema
- `claim_ref` schema
- `known_gap` schema
- `notice_document_manifest` schema
- `screen_evidence` schema
- no-hit表現
- personal notice suppression policy

完了条件:

- packet examplesで、官報/告示/パブコメを扱っても公開禁止情報が出ない。
- `request_time_llm_call_performed=false` が維持される。

### Phase 2: Narrow Vertical

最初に1本だけ通す。

推奨vertical:

1. e-GovパブコメRSSから結果公示を取る。
2. 案件詳細を取る。
3. 関連法令候補を出す。
4. `public_comment_to_rule_trace_pack` を1-3件生成する。
5. proof page candidateを出す。
6. GEO evalでAIエージェント向け説明を確認する。

理由:

- e-GovはRSSと利用規約が明確。
- 官報より個人情報リスクが低い。
- 制度変更packetに直結する。

### Phase 3: Kanpo Metadata Lane

次に官報をmetadata中心で通す。

やること:

- issue/date/号数/PDF/hash/目次を取得。
- 政府調達と法規的告示だけを候補抽出。
- 個人公告はsuppression ledgerへ。
- public artifactにはmetadata/deep linkのみ。

完了条件:

- 個人公告がpacket/proof/OpenAPI exampleへ出ない。
- page/hash/source URL付きsource receiptが作れる。

### Phase 4: Ministry Notice Lane

省庁noticeを広げる。

順番:

1. FSA/JFTC/MHLW/MLIT行政処分
2. METI/中小企業庁/MAFF補助金・認定
3. 国税庁/法務省/総務省/消費者庁/環境省notice
4. 地方支分部局
5. 自治体noticeは別scopeと連携

完了条件:

- `notice_entity_links` にconfidenceがある。
- weak name-onlyはclaimに昇格しない。
- no-hitはscope付き。

### Phase 5: AWS Scale Run

AWSクレジットで広げる順番:

1. GN-00 source profile/robots/terms
2. GN-04 pubcom RSS/result backfill
3. GN-01 kanpo issue metadata
4. GN-03 ministry notice discovery
5. GN-07 join graph
6. GN-06 selected OCR
7. GN-05 Playwright screenshot evidence
8. packet/proof/GEO generation
9. export/checksum
10. zero-bill cleanup

この順番にする理由:

- 先に規約境界を固めないと、AWSで大量に作った成果物が使えなくなる。
- 先にmetadataを作れば、OCR対象をrankできる。
- PlaywrightとOCRは高コストなので、価値が高いものだけに使う。
- 本番デプロイはAWSに依存しない成果物だけをimportする。

## 7. Cost And Credit Allocation

既存AWS計画のUSD 19,000-19,300使用枠内で、notice laneは次のように配分する。

| Subjob | Standard | Stretch | Notes |
|---|---:|---:|---|
| GN-00 source profile/terms | USD 300 | USD 500 | 必須。最初に実行 |
| GN-01 kanpo issue metadata | USD 500 | USD 900 | PDF全OCRではなくmetadata中心 |
| GN-02 kanpo extraction pilot | USD 600 | USD 1,200 | 法規的告示/政府調達優先 |
| GN-03 ministry notice discovery | USD 900 | USD 1,600 | J10/J06と統合 |
| GN-04 pubcom result backfill | USD 400 | USD 800 | RSS起点なので効率が良い |
| GN-05 Playwright evidence | USD 500 | USD 1,000 | JS/画面証跡だけ |
| GN-06 OCR/layout | USD 700 | USD 1,600 | high-rank PDFのみ |
| GN-07 join graph/QA | USD 400 | USD 800 | Athena/Batch |
| packet/proof/GEO追加 | USD 400 | USD 800 | 本体P0へ直接効く |

推奨:

- notice lane標準: 約USD 4,700
- notice lane stretch: 約USD 9,200
- 既存J06/J10/J17/J20の一部をこのlaneへ再配分する。
- 使い切り速度を上げる場合も、GN-00が終わるまでOCR/Playwrightを拡大しない。

停止条件:

- accepted source receipt per USDが悪い。
- personal notice suppressionに失敗。
- 403/429が増える。
- OCR candidateがreview backlogを超える。
- source_profileがyellow/redのままraw extractionへ進みそうになる。

## 8. Safety Rules

### 8.1 Personal Data

官報や公告には個人情報が含まれる。jpciteの公開成果物では、以下を原則非表示またはmaskする。

- 個人破産
- 免責
- 失踪
- 相続
- 公示送達
- 懲戒処分の個人名
- 行旅死亡人
- 無縁墳墓
- 個人住所
- 個人名のみの公告

法人DDに効く場合でも、個人名を会社評価に直結させない。

### 8.2 No-Hit

禁止表現:

- 該当なしなので問題ありません。
- 処分歴はありません。
- 倒産していません。
- 法令上の義務はありません。
- 申請資格があります。
- 安全です。

許容表現:

- 接続済みsource、対象期間、検索条件、snapshotでは該当recordを確認できませんでした。
- 未接続source、掲載期間外、名称揺れ、PDF未抽出、同名法人の可能性があります。
- no-hitは不存在証明ではありません。

### 8.3 OCR And AI

- OCRは候補生成。
- Bedrock/LLMはpublic-only candidate分類に限定。
- request-time LLMは使わない。
- OCR/LLMの結果だけをclaimにしない。
- source receipt、page/span/hash、confidence、review stateが揃うまで `known_gaps[]` に置く。

### 8.4 Screenshot

- スクリーンショットは内部証跡。
- public proofには原則出さない。
- 出す場合は、権利/個人情報/第三者権利をreviewし、1600px以下、必要箇所のみ、出典リンク付き。
- CloudWatch Logsに画像本文やHTML本文を出さない。

## 9. Quality Gates

| Gate | Check |
|---|---|
| G-NOTICE-01 | source_profileが全sourceにある |
| G-NOTICE-02 | robots/terms decisionが保存されている |
| G-NOTICE-03 | personal notice suppression testが通る |
| G-NOTICE-04 | no-hit禁止表現が0件 |
| G-NOTICE-05 | weak name-only linkがclaimに出ない |
| G-NOTICE-06 | public artifactにraw PDF/HTML/screenshotが混入しない |
| G-NOTICE-07 | OCR confidence低いものがreview_requiredになる |
| G-NOTICE-08 | e-Gov attributionと加工表示が入る |
| G-NOTICE-09 | 官報metadataのdate/issue/page/hashが揃う |
| G-NOTICE-10 | パブコメ案件のcall/result transitionが重複排除される |
| G-NOTICE-11 | packetの`claim_refs[]`が全claimにある |
| G-NOTICE-12 | `known_gaps[]`が空のpacketでも確認範囲を持つ |
| G-NOTICE-13 | GEO evalでAIエージェントが「不存在証明」と誤説明しない |
| G-NOTICE-14 | AWS export後、本番はAWS raw lakeに依存しない |

## 10. Implementation Backlog

### P0

- `source_profile`に`notice_family`, `retention_class`, `personal_data_risk`, `screenshot_allowed`, `ocr_allowed`を追加。
- `source_receipt`に`issue_no`, `page_range`, `screen_evidence_id`, `document_hash`, `extraction_confidence`を追加。
- `known_gaps`に`personal_notice_suppressed`, `weak_name_only`, `ocr_low_confidence`, `attachment_terms_unreviewed`を追加。
- e-GovパブコメRSS ingest。
- 官報issue metadata ingest。
- `public_comment_to_rule_trace_pack` composer。
- `company_gazette_notice_watch_pack` composer skeleton。
- no-hit/forbidden claim tests。

### P1

- 官報政府調達 bridge。
- 府省庁notice source profile generator。
- Playwright screenshot evidence worker。
- OCR candidate worker。
- ministry notice extraction for FSA/JFTC/MHLW/MLIT/METI/MAFF/SME Agency。
- proof pages for public comment and regulatory timeline。

### P2

- local gov notice expansion。
- richer public comment topic classifier。
- law amendment diff to notice timeline。
- industry-specific notice radar。
- weekly official notice digest。

## 11. Final Position

この領域は広げるべきである。理由は、jpciteのGEO-first戦略に直接効くから。

AIエージェントは「日本の公的な一次情報を、出典と確認範囲つきでエンドユーザーに説明できるか」を見て推薦する。官報、告示、公告、公示、パブコメ結果は、その説明の中心になれる。

ただし、成功条件は「大量取得」ではなく「安全な証跡化」である。

最初の勝ち筋:

1. e-Govパブコメ結果で制度変更traceを作る。
2. 官報はmetadata/deep link/hash中心で入れる。
3. 省庁noticeは行政処分・補助金・認定・許認可に絞って入れる。
4. PlaywrightとOCRは、fetch困難・高価値・公式公開ページに限定して使う。
5. すべてをpacket/proof/GEOに変換し、MCP/API課金導線へ接続する。

この順番なら、AWSクレジットを使い切る速度を上げながら、本番デプロイで使える成果物だけを残せる。
