# AWS scope expansion 19/30: courts, disputes, appeals, and enforcement disclosures

作成日: 2026-05-15  
担当: 拡張深掘り 19/30 / 裁判所・審決・行政不服・紛争/処分公表担当  
対象: jpcite 本体計画、AWS credit run、GEO/MCP/API導線、取引先審査、コンプラ影響、業法チェック成果物  
状態: 計画文書のみ。AWS CLI/API、AWSリソース作成、デプロイ、収集ジョブ実行はしていない。  
出力制約: このMarkdownのみを追加する。  

## 0. 結論

裁判所判例、審決、行政処分、労働委員会命令、行政不服審査の裁決・答申は、jpcite の価値を大きく上げる。ただし、これらは「AIが結論を断定する材料」ではなく、エンドユーザーが欲しい成果物へ変換するための `public dispute and enforcement evidence layer` として扱うべきである。

最も重要な結論:

1. この領域は売れる。取引先審査、許認可/業法チェック、コンプライアンス月次監視、規制変更影響診断、調達/金融/法務DDで明確に課金できる。
2. 裁判例は網羅データではない。裁判所自身が、裁判例情報には全ての判決等が掲載されているわけではないと説明している。したがって no-hit は「裁判例なし」「紛争なし」「安全」の証明にしてはいけない。
3. 行政処分・審決・命令は、裁判例よりも取引先審査や業法チェックへ直結しやすい。P0では行政処分/審決/命令を先に成果物化し、裁判例は「重要判例・行政事件・労働事件・審決取消訴訟の文脈補強」として扱う。
4. AWS credit run では、HTML/PDF/Excel/APIだけでなく、Playwright、1600px以下スクリーンショット、DOM保存、OCR、HAR/console log保存を使い、fetch困難な公式ページも証跡化できる。ただし CAPTCHA回避、アクセス制限回避、ログイン突破、利用規約違反はしない。
5. 出力は `event` ではなく `receipt-backed event candidate` として作る。対象企業との同一性、事件の確定性、上訴/取消/命令変更、匿名化、旧商号、同名企業はすべて `known_gaps[]` に出す。
6. 売り物は「訴訟リスク判定」ではない。売り物は「公的一次情報で確認できる紛争・処分・審決・不服審査の確認範囲付きメモ」である。

この担当で追加すべきAWS job群は、既存のJ01-J40の後続または並走として `J41-J52` に置く。最短本番投入は、FSA行政処分Excel、MLITネガティブ情報、消費者庁処分、JFTC審決等DB、中央労働委員会DB、MHLW労基法令違反公表を先に処理し、裁判所判例検索は P0-B/P1 として限定投入する。

## 1. Product Framing

### 1.1 User Promise

AI agentに対する約束:

> この会社・業種・制度に関係しそうな公的な裁判例、行政処分、審決、命令、裁決・答申を、取得条件・出典・スクリーンショット・未確認範囲つきで返します。結論は断定せず、人間が次に確認すべき材料へ整理します。

エンドユーザーに対する約束:

> 裁判所・行政庁・審査機関の公開一次情報を横断して、取引先確認、許認可確認、コンプライアンス対応、規制変更影響調査の初動を安く速くします。法律判断や適法保証ではなく、確認作業の証跡と見落とし範囲を明示します。

### 1.2 What We Sell

売れる成果物:

| Packet | 主な買い手 | 価値 | 優先 |
|---|---|---|---|
| `counterparty_dispute_enforcement_check` | 営業、購買、経理、法務、AI agent | 取引先の公的処分・審決・紛争候補を確認範囲付きで返す | P0 |
| `public_enforcement_dd_packet` | 法務、M&A、VC、金融、調達 | 行政処分、指名停止、審決、命令、FSA/MLIT/CAA/JFTC等を束ねる | P0 |
| `regulated_business_enforcement_watch` | 許認可業種、士業、FC本部 | 建設、不動産、運輸、金融、人材、食品、医療等の処分差分監視 | P0 |
| `competition_consumer_case_context` | EC、広告、下請、SaaS、メーカー | 景表法、特商法、独禁法、下請/取適法関連の事例確認 | P0 |
| `labor_dispute_compliance_packet` | 人事、社労士、労務SaaS、購買 | 労基法令違反公表、不当労働行為命令、労働事件裁判例を整理 | P0/P1 |
| `financial_enforcement_context_packet` | Fintech、金融、投資、経理 | 金融庁行政処分、SESC勧告、課徴金、登録業者確認への接続 | P0 |
| `administrative_appeal_precedent_packet` | 士業、行政対応企業、自治体対応業者 | 行政不服審査の裁決・答申から処分根拠・争点を確認 | P1 |
| `court_decision_context_packet` | 法務、士業、AI agent | 裁判所判例検索から制度・業法・行政事件・労働事件の文脈を出す | P1 |
| `industry_enforcement_pattern_packet` | 業界団体、監査、保険、コンサル | 処分類型、根拠条文、改善命令、取消事例のパターン化 | P1 |
| `complaint_to_action_research_packet` | 経営者、管理部、顧問士業 | 相談・紛争・処分・裁判のどこを見るべきかの調査計画 | P1 |

### 1.3 Non-Goals

作らないもの:

- 法的助言。
- 訴訟勝敗予測。
- 違法性、適法性、過失、故意の断定。
- 「行政処分歴なし」「訴訟歴なし」「問題なし」「安全」の表示。
- 反社チェックの代替。
- 信用調査会社の与信評点。
- 裁判例の全文再配布サービス。
- 匿名化されている裁判例から、無理に当事者を再識別する機能。
- CAPTCHA、ログイン、アクセス制限、明示的禁止を回避する収集。

## 2. Why This Matters Commercially

### 2.1 End User Pain

エンドユーザーは「判例DB」や「行政処分DB」が欲しいわけではない。欲しいのは次のような成果物である。

- この取引先を新規登録してよいか、少なくとも公的に確認すべき注意点は何か。
- 建設/不動産/運輸/金融/人材/産廃/食品/医療/介護の業法上、どの処分・登録・許認可を見ればよいか。
- 広告表現、EC、サブスク、訪販、下請、個人情報、労務で類似処分や審決があるか。
- 自社の業種に関係する行政処分や裁判例から、今月のコンプラチェックリストを作れるか。
- 補助金や入札の前に、指名停止・処分・登録取消・行政処分の確認漏れがないか。
- 顧問士業や弁護士に相談する前に、一次情報付きの初動メモを作れるか。

jpcite がここに出す価値は、AIが検索して曖昧に答えることではなく、取得済み・検証済み・出典付きの `cheap first pass` を返すことである。

### 2.2 Why AI Agents Recommend It

AI agent がエンドユーザーへ推薦しやすい形:

- 「この会社名で公的処分を見て」と言われたら、MCP toolで `counterparty_dispute_enforcement_check` を呼べる。
- 「この広告表現は過去に処分例がある？」と聞かれたら、`competition_consumer_case_context` を呼べる。
- 「労務リスクをざっくり見たい」と言われたら、`labor_dispute_compliance_packet` を呼べる。
- 「この規制変更の実務影響は？」と聞かれたら、裁判例ではなく、行政処分・審決・命令・ガイドラインを優先して証跡付きで返せる。
- AI側は最終判断をしない。jpciteが `known_gaps[]` と `human_review_required` を返すので、AIは安全に「次に専門家へ確認してください」と言える。

### 2.3 Revenue Logic

課金しやすい順:

1. 取引先1社の公的処分/紛争候補チェック: 低単価・高頻度。
2. 業法別の処分/登録/許認可ウォッチ: 中単価・継続課金。
3. 月次コンプラ監視: 中単価・継続課金。
4. M&A/VC/金融/調達向けDD memo: 高単価・低頻度。
5. 士業/コンサル向け顧客横断レポート: 中高単価・継続課金。

推奨価格帯:

| Output | Preview | Paid |
|---|---:|---:|
| 取引先quick check | 無料でsource count/coverageだけ | 300-1,500円/社 |
| 行政処分DD packet | 無料で主要source候補 | 1,500-5,000円/社 |
| 業法別enforcement watch | 直近件数のみ | 5,000-30,000円/月 |
| 労務/消費者/金融 enforcement context | 見出しのみ | 1,000-8,000円/packet |
| M&A/VC public DD memo | 範囲と見積もり | 10,000-50,000円/件 |

## 3. Source Families

### 3.1 Court Decisions

公式起点:

- 裁判所「裁判例を調べる」: `https://www.courts.go.jp/hanrei/`
- 裁判例検索: `https://www.courts.go.jp/hanrei/search1/index.html?lang=ja`

重要な性質:

- 最高裁判所及び下級裁判所の裁判例を検索できる。
- 最高裁、高裁、下級裁判所速報、行政事件、労働事件、知的財産事件などのカテゴリがある。
- 全ての判決等が掲載されているわけではない。
- 当事者表示が省略されたり、固有名詞が記号化される場合がある。
- 要旨・判示事項・本文・PDF/添付があるが、外字、図表、省略、更正決定の扱いに注意が必要。

収集方針:

- P0では「最近の裁判例」「行政事件」「労働事件」「知財高裁の審決取消訴訟」を優先。
- 全件取得を無理に目指さず、source_profile、検索条件、スクショreceipt、結果件数receiptを整備する。
- 企業同定は原則しない。明示的に企業名が出ている場合だけ `possible_party_match` として扱い、法人番号確定ができない場合はscoreに入れない。
- 裁判例は「背景文脈」「争点例」「行政処分取消の有無」「業法解釈の参考」に使い、取引先リスクの断定には使わない。

### 3.2 JFTC Decisions and Legal Measures

公式起点:

- 公正取引委員会「審決等データベース」: `https://www.jftc.go.jp/shinketsu/`
- 審決等DB本体: `https://snk.jftc.go.jp/`
- 公取委報道発表、法的措置一覧、勧告一覧。

重要な性質:

- 事件名、処分年月日、適用法条、被審人などで検索できる。
- 審決、決定、判決、課徴金納付命令などが含まれる。
- DB内のテキスト表示はテキスト化されたものであり、正確なものはPDF形式を見るべきという注意がある。
- 独禁法、景表法、下請/取適法、民事訴訟法、行政事件訴訟法などの適用法条が検索軸になる。

収集方針:

- P0で処理する。
- `event_type`: `jftc_decision | cease_and_desist_order | surcharge_payment_order | recommendation | court_decision_related_to_jftc`
- PDF hashを必須にし、HTML textは検索補助として扱う。
- 被審人名と法人番号の同定は別ジョブで行う。弱い名前一致は `identity_ambiguous`。
- 競争/表示/下請系の成果物へ直結させる。

### 3.3 Consumer Affairs Agency Dispositions

公式起点:

- 消費者庁「行政処分の状況について知りたい」: `https://www.caa.go.jp/business/disposal/`
- 特定商取引法に基づく措置等。
- 景品表示法に基づく措置等。
- 関連して、消費者安全、リコール、事故情報、機能性表示食品等もP1候補。

重要な性質:

- EC、通販、訪販、広告、景品表示、サブスク、消費者契約、食品表示などに直結する。
- 企業名、措置命令、業務停止命令、指示、注意喚起、根拠法令、表示内容、期間などが成果物化しやすい。

収集方針:

- P0で処理する。
- 特商法・景表法を先にsource_profile化する。
- PDF/HTML本文、別添、スクショ、発表日、根拠法、対象表示、対象商品/サービス、対象事業者を抽出する。
- `ads_ec_representation_check_packet`、`consumer_compliance_watch_packet` に接続する。

### 3.4 FSA and SESC

公式起点:

- 金融庁「行政処分事例集」: `https://www.fsa.go.jp/status/s_jirei/kouhyou.html`
- 行政処分事例集の便利な使い方: `https://www.fsa.go.jp/status/s_jirei/use00.html`
- 証券取引等監視委員会: `https://www.fsa.go.jp/sesc`
- SESC課徴金事例集/開示検査事例集: `https://www.fsa.go.jp/sesc/jirei/index.html`
- SESC取引調査・勧告ページ。

重要な性質:

- 金融庁行政処分事例集はExcelで取得できるため、AWS大量処理に向く。
- 平成14年度以降の金融庁・財務局等の不利益処分事例を対象に、検索可能に整理する趣旨がある。
- SESCは勧告、課徴金、検査結果、告発、無登録業者等に関する情報を持つ。

収集方針:

- P0で処理する。
- Excelを正規化し、処分日、対象業態、対象者名、根拠法令、処分内容、原因事実、所管を構造化する。
- SESCは `recommendation` と `final_order` を分ける。勧告は最終処分ではない場合があるため、stageを必須にする。
- `financial_enforcement_context_packet`、`counterparty_dispute_enforcement_check` に接続する。

### 3.5 MLIT Negative Information

公式起点:

- 国土交通省ネガティブ情報等検索サイト: `https://www.mlit.go.jp/nega-inf/`
- 本サイトについて: `https://www.mlit.go.jp/nega-inf/about.html`
- 検索の使い方: `https://www.mlit.go.jp/nega-inf/howto.html`

重要な性質:

- 国交省所管の事業者等の過去の行政処分歴を検索できる。
- 建設、不動産、旅客運送、貨物運送、自動車整備、旅行、指名停止など、商用需要が非常に高い。
- JavaScript利用が前提の箇所があるため、Playwright captureの効果が大きい。
- 国交省はネガティブ情報公開を、追加ペナルティではなく事業者の適正な事業運営確保などの目的で説明している。jpciteも過剰な断定や懲罰的表示を避ける。

収集方針:

- P0で処理する。
- Playwrightで検索結果、詳細ページ、ページャ、条件、件数をreceipt化する。
- `source_query`: 事業分野、事業者名、都道府県、処分等年月、処分等種類。
- `event_type`: `mlit_negative_info | designation_suspension | license_disposition | business_suspension | cancellation | instruction`
- 建設/不動産/運輸/旅行は最初の高収益verticalとして扱う。

### 3.6 MHLW Labor Standards and Central Labour Relations Commission

公式起点:

- 厚労省「労働基準関係法令違反に係る公表事案」PDF群。
- 中央労働委員会「労働委員会関係 命令・裁判例データベース」: `https://www.mhlw.go.jp/churoi/meirei_db/`

重要な性質:

- 労基法令違反公表は、都道府県労働局が公表した事案の集約PDFとして扱われることがある。
- 中労委DBは、不当労働行為をめぐる命令、労働委員会関係の判決等を収録する。
- 中労委DBは概要情報と全文情報を持ち、事件の経過も顛末情報として示す。

収集方針:

- P0/P1で処理する。
- 労基法令違反PDFはOCR/表抽出に向く。対象事業場、所在地、違反法条、事案概要、送検日などを構造化する。
- 中労委DBは `labor_commission_order` と `labor_court_case` を分ける。
- 労務成果物では、企業の「ブラック度」ではなく、公開事案確認とチェック観点に変換する。

### 3.7 Administrative Appeal Decisions and Recommendations

公式起点:

- 総務省「行政不服審査法」ページ。
- 行政不服審査裁決・答申検索データベース: `https://fufukudb.search.soumu.go.jp/`
- 自治体の行政不服審査会答申ページ。

重要な性質:

- 行政庁の処分または不作為への審査請求について、裁決・答申を検索できる。
- 自治体ページでは、行政不服審査法に基づき答申内容を公表する説明が多い。
- 個人情報が含まれる可能性があり、公開用裁決書でもマスキング不備リスクがある。jpcite側ではPII最小化、表示抑制、再配布制限が必要。

収集方針:

- P1で処理する。
- まずsource_profileとcapture adapterを作る。
- 分野別に、許認可、福祉、税、建築、情報公開、産廃、営業許可などの処分根拠法令を分類する。
- 個人名・住所・児童/福祉/医療などのセンシティブ情報は抽出対象外または抑制対象。
- 売り物は「類似裁決の結論」ではなく「行政対応時に確認すべき争点と根拠法令の整理」。

### 3.8 Other Enforcement Sources

P0/P1候補:

- 個人情報保護委員会: 勧告、命令、公表、ガイドライン。
- 公正取引委員会: 独禁法、下請/取適法、フリーランス法、景表法関連。
- 経産省: 補助金取消、製品安全、輸出管理、電気用品、安全規制。
- 環境省/自治体: 産廃許可、行政処分、措置命令。
- 厚労省: 医療、介護、食品、労働者派遣、有料職業紹介。
- 農水省: 食品表示、JAS、農薬/肥料等。
- 総務省/MIC: 電気通信、技適、行政指導/処分。
- 警察庁/都道府県公安委員会: 古物、風営、警備業等。ただし個人情報・地域差が大きいのでP1/P2。

## 4. Unified Event Schema

### 4.1 `public_dispute_enforcement_event`

```json
{
  "event_id": "pdee_20260515_...",
  "schema_version": "2026-05-15",
  "event_family": "court | administrative_enforcement | commission_decision | labor_commission | administrative_appeal | procurement_suspension",
  "event_type": "administrative_order",
  "event_stage": "filed | decision | order | recommendation | final | appealed | reversed | modified | unknown",
  "source_family": "jftc_decision_db",
  "issuing_body": {
    "name": "公正取引委員会",
    "body_type": "agency | court | commission | local_government",
    "jurisdiction": "Japan",
    "official_url": "https://..."
  },
  "event_dates": {
    "published_at": "2026-05-15",
    "decision_at": null,
    "order_at": null,
    "effective_at": null,
    "captured_at": "2026-05-15T00:00:00Z"
  },
  "subject_candidates": [
    {
      "display_name": "株式会社サンプル",
      "corporation_number": null,
      "official_registration_id": null,
      "match_level": "strong_name_address",
      "match_confidence": 0.8,
      "match_basis_receipt_ids": ["sr_..."],
      "identity_known_gaps": ["法人番号がsource本文に明示されていない"]
    }
  ],
  "legal_basis": [
    {
      "law_name": "独占禁止法",
      "article": "第...",
      "source_receipt_id": "sr_law_..."
    }
  ],
  "issue_tags": ["competition", "consumer", "labor", "construction", "financial"],
  "outcome": {
    "label": "措置命令",
    "normalized_outcome": "order",
    "severity_band": "attention_high",
    "summary_from_source": "source-backed short summary only",
    "not_a_legal_opinion": true
  },
  "appeal_chain": {
    "has_known_related_events": false,
    "related_event_ids": [],
    "known_gap": "上訴・取消訴訟の有無は未確認"
  },
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "no_hit_checks": [],
  "human_review_required": true,
  "_disclaimer": "公的一次情報の確認範囲を示すものであり、違法性・適法性・取引可否・信用力を断定しない。"
}
```

### 4.2 Receipt Requirements

各eventには最低1つ以上の `source_receipt` が必要。

必須項目:

- `receipt_id`
- `source_profile_id`
- `official_url`
- `canonical_url`
- `captured_at`
- `capture_method`: `http_get | playwright_dom | playwright_screenshot | pdf_download | excel_download | ocr`
- `query_params`
- `viewport`: スクリーンショットの場合。幅・高さは1600px以下。
- `content_hash`
- `screenshot_hash`
- `pdf_hash`
- `dom_hash`
- `ocr_confidence`
- `license_boundary`
- `robots_or_terms_checked_at`
- `retention_class`

### 4.3 Claim Types

`claim_refs[]` で扱うclaim:

| claim_type | 例 | 注意 |
|---|---|---|
| `source_says_event_published` | 公式ページに公表された | 公表と事実認定は分ける |
| `source_says_order_issued` | 措置命令/業務停止命令 | 根拠法令と発令主体が必要 |
| `source_says_recommendation_made` | SESC/JFTC等の勧告 | 最終処分ではない可能性 |
| `source_says_decision_rendered` | 判決/審決/命令 | 確定性・上訴を別扱い |
| `source_says_registration_cancelled` | 登録取消/許可取消 | 許認可番号・対象範囲必須 |
| `source_says_no_results_for_query` | 検索条件で0件 | 不存在証明にしない |
| `derived_identity_match` | 法人番号等と紐付け | match_level必須 |
| `derived_issue_tag` | 独禁法/景表法/労務等 | ルールベースで付与 |

## 5. Algorithms

### 5.1 Pipeline Overview

処理順:

1. Source profile作成: 公式URL、利用条件、検索方法、更新頻度、取得方法を定義。
2. Acquisition: HTTP/API/Excel/PDF/Playwrightで取得。
3. Receipt generation: DOM/PDF/Excel/screenshot/OCRのhashとquery条件を保存。
4. Parsing: 表、本文、PDF、検索結果、詳細ページを構造化。
5. Event normalization: event_family、event_type、event_stage、issuing_body、dates、legal_basisへ正規化。
6. Identity resolution: 法人番号、登録番号、住所、商号、旧商号で候補同定。
7. Legal basis linking: e-Gov法令、業法source、行政処分sourceと接続。
8. Appeal/status linking: 審決取消訴訟、行政事件、関連命令、上訴/取消/変更を候補接続。
9. Scoring: 注意度、証拠品質、未確認範囲を計算。
10. Packet materialization: 売れる成果物別のfixture、proof page、MCP/API exampleへ変換。

### 5.2 Identity Resolution

match level:

| match_level | score使用 | 条件 |
|---|---|---|
| `exact_corporation_number` | 可 | 法人番号が公式source内で一致 |
| `exact_registration_id` | 可 | 金融登録番号、建設業許可番号、宅建免許番号等が一致 |
| `exact_invoice_number` | 限定可 | T番号から法人番号へ接続できる |
| `name_address_strong` | 条件付き | 商号正規化 + 所在地正規化が一致 |
| `name_address_history` | 条件付き | 旧商号/旧所在地履歴と一致 |
| `name_only_unique_in_source_scope` | 原則不可 | source内では一意でも全国では曖昧 |
| `weak_name_only` | 不可 | 同名企業リスクが高い |
| `court_anonymized_party` | 不可 | A/B/C等の匿名化。再識別しない |
| `no_match` | 不可 | no-hit/gapのみ |

ルール:

- 裁判例で当事者が匿名化されている場合、取引先に紐づけない。
- PDF内の企業名だけで法人番号がない場合、法人番号DBや許認可DBと突合し、曖昧なら `identity_ambiguous`。
- 個人名、代表者名、労働者名、患者名、児童名、住所の詳細は抑制する。
- CSV private overlay由来の取引先名は、AWSにraw投入しない。ローカル側で派生fact化してから、公開sourceへの照合候補だけに使う。

### 5.3 Event Stage Normalization

stage:

- `complaint_or_application`: 申立て、審査請求、訴え提起。
- `investigation`: 検査、調査、監督、報告徴収。
- `recommendation`: 勧告、行政処分勧告、課徴金納付命令勧告。
- `order`: 措置命令、業務停止命令、改善命令、指示、取消。
- `decision`: 審決、命令、裁決、答申、判決。
- `appeal_or_review`: 控訴、上告、審決取消訴訟、行政不服。
- `final_or_closed`: 確定、終結。ただしsourceに明示がある場合のみ。
- `unknown`: 判定不能。

禁止:

- 勧告を処分確定として扱う。
- 申立てを違反認定として扱う。
- 判決掲載を企業不祥事として扱う。
- 取消訴訟があることを、処分の誤り確定として扱う。

### 5.4 Attention Score

名称:

`public_dispute_enforcement_attention_score`

意味:

> 接続済み公的一次情報で確認された紛争・処分・審決等について、人間が確認すべき優先度を示す。信用力、違法性、適法性、安全性、反社性、取引可否の評価ではない。

要素:

```text
base_event_weight
  = event_type_weight
  * stage_weight
  * source_authority_weight
  * identity_match_weight
  * recency_weight
  * evidence_quality_weight
  * legal_basis_specificity_weight

attention_score
  = min(100, round(sum(base_event_weight over events) - mitigation_for_reversal_or_modification))
```

推奨weight例:

| factor | 例 |
|---|---|
| `event_type_weight` | 登録取消 30、業務停止 25、措置命令 22、指名停止 18、勧告 12、判決文脈 8 |
| `stage_weight` | final/order 1.0、recommendation 0.65、filed 0.3、unknown 0.4 |
| `source_authority_weight` | 公式行政庁/裁判所 1.0、自治体公式 0.9、二次資料 0.0 |
| `identity_match_weight` | 法人番号一致 1.0、登録番号一致 0.95、name+address 0.75、name only 0.0 |
| `recency_weight` | 1年以内 1.0、3年以内 0.75、5年以内 0.55、10年以内 0.35、それ以前 0.2 |
| `evidence_quality_weight` | PDF+HTML+スクショ 1.0、PDFのみ 0.9、HTMLのみ 0.8、OCR低信頼 0.5 |
| `legal_basis_specificity_weight` | 条項あり 1.0、法令名のみ 0.75、根拠不明 0.4 |

必ず別軸で出す:

- `evidence_quality_score`
- `coverage_gap_score`
- `identity_confidence`
- `human_review_required`

### 5.5 No-Hit Algorithm

no-hitは次の形に限定する。

```json
{
  "no_hit_type": "query_no_result",
  "source_profile_id": "mlit_negative_info",
  "query": {
    "business_area": "宅地建物取引業者",
    "name": "株式会社サンプル",
    "prefecture": "東京都",
    "period": "all_available"
  },
  "result_count": 0,
  "captured_at": "2026-05-15T00:00:00Z",
  "meaning": "指定したsourceと検索条件では結果が見つからなかった。処分不存在、安全、適法、取引可を意味しない。",
  "known_gaps": [
    "旧商号未検索",
    "関連会社未検索",
    "自治体独自公表は未接続",
    "source更新遅延の可能性"
  ]
}
```

禁止文言:

- `行政処分歴なし`
- `訴訟歴なし`
- `問題なし`
- `違反なし`
- `安全`
- `適法`
- `取引可能`

推奨文言:

- `接続済みsourceと指定条件では未検出`
- `未検出は不存在を意味しません`
- `旧商号、関連会社、自治体source、非掲載裁判例は未確認です`

## 6. AWS Collection Design

### 6.1 Can AWS Do Playwright and Screenshot Capture?

できる。今回のAWS credit runでは、fetch困難な公式ページに対して以下の構成を使う。

- AWS Batch or ECS/Fargate task。
- Playwright + Chromium container。
- viewport width/height は1600px以下。
- HTML DOM snapshot。
- page screenshot。必要なら複数枚に分割し、各画像は1600px以下。
- PDF download。
- Excel/CSV download。
- HARまたはnetwork summary。
- console error summary。
- OCR input image/PDF。
- content hash / screenshot hash / OCR confidence。

明示する制限:

- CAPTCHA突破はしない。
- robots/termsに反する自動取得はしない。
- ログインが必要な領域は扱わない。
- rate limitを尊重する。
- 個人情報やセンシティブ情報の再配布を避ける。

### 6.2 Screenshot Standard

標準:

```json
{
  "viewport": {"width": 1440, "height": 1200},
  "max_image_dimension_px": 1600,
  "device_scale_factor": 1,
  "full_page": false,
  "capture_slices": true,
  "slice_height": 1200,
  "redaction": {
    "pii_patterns": ["email", "phone", "personal_address_when_not_business"],
    "manual_review_required_for_sensitive_domains": true
  }
}
```

理由:

- ユーザーの意図どおり、スクリーンショットは1600px以下で扱う。
- full-page巨大画像は保存・OCR・レビューが重く、hash比較も扱いにくい。
- 複数sliceに分ければ、viewport receiptとして十分であり、後で人間が追いやすい。

### 6.3 Job Set J41-J52

| Job | Name | Purpose | Priority |
|---|---|---|---|
| J41 | Court source profile and recent cases canary | 裁判所検索、最近の裁判例、行政/労働/IPカテゴリの取得可能性確認 | P1 |
| J42 | Court decision metadata extraction | 事件番号、裁判年月日、裁判所、カテゴリ、要旨、PDF hash抽出 | P1 |
| J43 | Court context packet fixture | 行政事件/労働事件/審決取消訴訟の成果物fixture化 | P1 |
| J44 | JFTC decision database capture | 審決等DBをPlaywrightで検索・PDF取得・event化 | P0 |
| J45 | CAA enforcement capture | 特商法/景表法処分、注意喚起、PDF/HTML取得 | P0 |
| J46 | FSA/SESC enforcement capture | 行政処分Excel、SESC勧告/課徴金/検査結果取得 | P0 |
| J47 | MLIT negative info capture | 建設/不動産/運輸/旅行/指名停止をPlaywrightで取得 | P0 |
| J48 | MHLW labor enforcement capture | 労基法令違反PDF、中労委命令/裁判例DB取得 | P0/P1 |
| J49 | Administrative appeal DB canary | 総務省/自治体の裁決・答申DB取得、PII gate検証 | P1 |
| J50 | Enforcement event graph build | 複数sourceのevent重複、関連、上訴/取消候補をgraph化 | P0 |
| J51 | Packet/proof materialization | 売れるpacket例、proof page、MCP/API example生成 | P0 |
| J52 | GEO answer fixture generation | AI agent向け質問例、推薦文、no-hit安全表現のfixture化 | P0 |

### 6.4 Cost and Speed

今回のクレジット消化方針に合わせる。

- まずJ44-J48を高速に回す。これは成果物直結で、費用対効果が高い。
- J41-J43は裁判所の負荷と規約・網羅性リスクを見ながら限定実行。
- J49はPIIリスクがあるためcanary中心。
- J50-J52は本番デプロイに直結するため必ず実行。

追加予算目安:

| Area | Estimated useful spend |
|---|---:|
| Playwright capture containers | USD 700-1,800 |
| PDF/Excel extraction and OCR | USD 500-1,500 |
| Textract/OCR pilot for scanned PDFs | USD 500-1,200 |
| Batch QA/rerun/dedupe | USD 400-900 |
| Packet/proof/GEO fixture generation | USD 300-700 |
| Total | USD 2,400-6,100 |

これは全体AWS計画のstretch枠から吸収する。低価値な広範囲OCRより、この領域を優先する方が売上に近い。

## 7. Output Packets

### 7.1 `counterparty_dispute_enforcement_check`

入力:

- corporation_number 任意。
- invoice_number 任意。
- name 必須または任意。
- address 任意。
- industry 任意。
- region 任意。
- include_sources: `mlit | fsa | caa | jftc | mhlw | courts | admin_appeal`

出力:

- subject identity resolution。
- connected source list。
- event candidates。
- no-hit checks。
- attention score。
- evidence quality。
- coverage gaps。
- recommended next checks。

価値:

- AIが「この取引先について、公的一次情報で確認できる注意点だけ先に見ます」と推薦できる。
- 営業/購買/経理/管理部が低単価で使える。

### 7.2 `public_enforcement_dd_packet`

入力:

- company identifiers。
- target vertical。
- period。
- include_related_entities boolean。

出力:

- 行政処分一覧。
- 審決/命令/勧告候補。
- 許認可/登録取消候補。
- 指名停止候補。
- 労基/労働委員会候補。
- 裁判例context候補。
- 重要source receipt。
- `unknown_or_not_connected_sources`。

価値:

- M&A、VC、金融、B2B購買の初動DD。
- 高単価にしやすい。

### 7.3 `regulated_business_enforcement_watch`

入力:

- industry: construction, real_estate, transport, travel, financial, staffing, waste, food, healthcare。
- region。
- watchlist subjects。

出力:

- 新規処分。
- 更新/取消/停止。
- 指名停止。
- 法令根拠。
- 自社/取引先への関係可能性。
- 次の確認項目。

価値:

- 継続課金向き。
- AI agentが「毎月確認しましょう」と推薦しやすい。

### 7.4 `competition_consumer_case_context`

対象:

- 独禁法。
- 景表法。
- 特商法。
- 下請/取適法。
- フリーランス法。
- EC/広告/サブスク/訪販/メーカー/卸売。

出力:

- 類似テーマの処分/審決/命令候補。
- 根拠法令。
- 表示/取引条件/契約類型。
- 禁止表現ではなく確認観点。
- `not_a_legal_advice`。

価値:

- 広告表現、LP、営業資料、利用規約、代理店契約の初動確認で売れる。

### 7.5 `labor_dispute_compliance_packet`

対象:

- 労基法令違反公表事案。
- 不当労働行為命令。
- 労働委員会関係裁判例。
- 裁判所労働事件。

出力:

- 業種/地域別の公表事案。
- 違反法条/命令類型。
- 労務チェックリスト。
- 自社に関係しそうな確認質問。
- `human_review_required`。

価値:

- 社労士、労務SaaS、人事、購買、人材業界に売れる。

### 7.6 `administrative_appeal_precedent_packet`

対象:

- 行政不服審査裁決。
- 行政不服審査会答申。
- 自治体答申。

出力:

- 処分根拠法令。
- 処分類型。
- 争点。
- 裁決/答申の方向性。
- 追加確認すべき事実。
- PII抑制済みsummary。

価値:

- 行政対応、許認可、補助金不採択、福祉/税/建築/情報公開などに使える。
- ただしPIIリスクが高いため、P1で慎重に投入。

## 8. Frontend and GEO Story

### 8.1 Public Pages

GEO向け公開ページ:

- `/jp/packets/counterparty-dispute-enforcement-check`
- `/jp/packets/public-enforcement-dd`
- `/jp/packets/regulatory-enforcement-watch`
- `/jp/packets/competition-consumer-case-context`
- `/jp/packets/labor-dispute-compliance`
- `/jp/sources/courts-hanrei`
- `/jp/sources/jftc-decisions`
- `/jp/sources/fsa-administrative-actions`
- `/jp/sources/mlit-negative-information`
- `/jp/sources/mhlw-labor-publication`

ページに必ず出す:

- 何が取れるか。
- 何は断定しないか。
- no-hitの意味。
- source_receipts例。
- MCP/API tool名。
- 価格preview。

### 8.2 Agent Tool Descriptions

MCP tool例:

```json
{
  "name": "jp_counterparty_dispute_enforcement_check",
  "description": "法人名、法人番号、許認可番号などから、日本の公的一次情報に基づく行政処分・審決・命令・裁判例文脈候補を確認範囲付きで返します。取引可否、信用力、違法性、安全性は断定しません。",
  "input_schema": {
    "type": "object",
    "properties": {
      "corporation_number": {"type": "string"},
      "name": {"type": "string"},
      "address": {"type": "string"},
      "industry": {"type": "string"},
      "include_court_context": {"type": "boolean"}
    }
  }
}
```

AI agentが言うべき推薦文:

> 公的sourceの確認範囲付きで、行政処分・審決・命令・裁判例文脈を先に見られます。結果が出なくても「問題なし」ではなく、未確認範囲も一緒に返ります。

AI agentが言ってはいけない推薦文:

- `訴訟歴がないか調べられます`
- `行政処分歴なしを証明できます`
- `取引してよいか判定できます`
- `法的に安全か確認できます`

## 9. Merge Order with Main Plan

本体計画とAWS計画へのマージ順:

1. P0 contractに `public_dispute_enforcement_event` を追加。
2. `source_profile` schemaに Playwright receipt / screenshot slice / OCR confidence を追加。
3. `known_gaps` taxonomyに `court_not_exhaustive`、`anonymized_party`、`appeal_status_unknown`、`identity_ambiguous`、`local_source_not_connected` を追加。
4. J44-J48をAWS fast laneに入れる。
5. J50でevent graphを作る。
6. J51でpacket fixtureを作る。
7. P0 packet composerに `counterparty_dispute_enforcement_check` を追加。
8. MCP/APIに1 toolだけ先行追加。
9. GEO public pageを追加。
10. production deploy gateで no-hit、disclaimer、receipt、PII、billing metadataを検査。
11. J41-J43/J49はP1として、staging後に追加投入。

実装優先:

| Order | Work | Reason |
|---:|---|---|
| 1 | FSA行政処分Excel ingest | 構造化しやすく商用価値が高い |
| 2 | MLIT negative info Playwright canary | 建設/不動産/運輸で売上に近い |
| 3 | CAA/JFTC ingest | EC/広告/下請/競争で横断需要が高い |
| 4 | MHLW労基PDF/中労委DB | 労務需要が強い |
| 5 | Event graph + packet fixture | 本番導線へ直結 |
| 6 | Court context limited | 断定リスクが高いため限定投入 |
| 7 | Admin appeal canary | PIIリスクがあるため慎重に |

## 10. Quality Gates

release blocker:

- source receiptなしのevent。
- PDF hashなしでPDF由来claimを出す。
- screenshotが1600pxを超える。
- no-hitを不存在/安全/問題なしへ変換している。
- 勧告を最終処分として扱っている。
- 申立て/訴え提起を違反認定として扱っている。
- 匿名裁判例を企業に紐付けている。
- 弱い名前一致をscoreに入れている。
- PII抑制なしで行政不服・労務・裁判例本文を表示している。
- request-time LLMにsourceなしの結論を生成させている。
- raw CSVをAWSへ上げている。
- AWS成果物を直接productionに出している。

acceptance gates:

- G01: 全eventに `source_receipts[]` がある。
- G02: 全claimに `claim_refs[]` がある。
- G03: 全packetに `known_gaps[]` がある。
- G04: `human_review_required=true` が正しく入る。
- G05: no-hit文言が許可リストだけ。
- G06: PII scanner合格。
- G07: screenshot dimension scanner合格。
- G08: OCR confidence低いclaimは `needs_review`。
- G09: identity matchが弱いeventはattention scoreから除外。
- G10: public pages/MCP/OpenAPIの説明が一致。

## 11. Risks and Controls

### 11.1 Court Coverage Risk

リスク:

- 裁判所DBに全判決がない。
- 当事者が匿名化される。
- 掲載情報が原文と完全一致しない場合がある。

対策:

- `court_not_exhaustive` gapを常時出す。
- 裁判例は企業スコアではなくcontext扱い。
- 当事者匿名化は再識別しない。

### 11.2 False Positive Identity Risk

リスク:

- 同名会社、旧商号、支店、屋号、個人事業主で誤紐付けする。

対策:

- 法人番号/登録番号優先。
- name-only matchはscore除外。
- ambiguity countを表示。
- 人間確認フラグ。

### 11.3 Procedural Status Risk

リスク:

- 勧告、命令、判決、裁決、答申、取消訴訟の関係を誤る。

対策:

- `event_stage` を必須。
- `appeal_chain` を別graphにする。
- 確定はsource明示がない限り出さない。

### 11.4 PII and Sensitive Data Risk

リスク:

- 裁判例、行政不服、労務資料に個人情報が含まれる。

対策:

- personal name/address/health/labor/minor tagsを抑制。
- 公開sourceでも必要以上に再表示しない。
- raw documentはinternal artifact。public packetには要約/receiptだけ。
- PII leak scanをrelease blockerにする。

### 11.5 Terms and Load Risk

リスク:

- Playwrightで公式サイトへ過負荷をかける。
- 利用条件に反する。

対策:

- source_profileごとのrate limit。
- canaryから始める。
- robots/terms ledger。
- CAPTCHA/ログイン/制限回避禁止。

## 12. Final Recommendation

この領域はAWS credit runに追加すべきである。特に、FSA、MLIT、CAA、JFTC、MHLW/中労委は「売れる成果物から逆算」したときに優先度が高い。

一方、裁判所判例と行政不服DBは、商用価値は高いが誤解・PII・網羅性リスクも高い。最初は広く深く取り切る対象ではなく、source_profile、canary、限定packet fixture、禁止表現gateを先に作る。

最終的に作るべき価値は次の一文に集約できる。

> AIが取引先、業法、規制、広告、労務、金融、調達について質問されたとき、jpciteは公的一次情報の処分・審決・命令・裁判例文脈を、証跡・未確認範囲・安全なno-hit表現つきで安く返す。

これにより、単なる情報キャッシュではなく、AI agentがエンドユーザーへ推薦しやすい有料成果物になる。

## 13. Official References Checked

- 裁判所 裁判例を調べる: https://www.courts.go.jp/hanrei/
- 裁判所 裁判例検索: https://www.courts.go.jp/hanrei/search1/index.html?lang=ja
- 公正取引委員会 審決等データベース: https://www.jftc.go.jp/shinketsu/
- 公正取引委員会 審決等DB本体: https://snk.jftc.go.jp/
- 消費者庁 行政処分の状況: https://www.caa.go.jp/business/disposal/
- 金融庁 行政処分事例集: https://www.fsa.go.jp/status/s_jirei/kouhyou.html
- 金融庁 行政処分事例集の使い方: https://www.fsa.go.jp/status/s_jirei/use00.html
- 証券取引等監視委員会: https://www.fsa.go.jp/sesc
- SESC 課徴金事例集・開示検査事例集: https://www.fsa.go.jp/sesc/jirei/index.html
- 国土交通省 ネガティブ情報等検索サイト: https://www.mlit.go.jp/nega-inf/
- 国土交通省 ネガティブ情報等検索サイト 本サイトについて: https://www.mlit.go.jp/nega-inf/about.html
- 中央労働委員会 労働委員会関係 命令・裁判例データベース: https://www.mhlw.go.jp/churoi/meirei_db/
- 総務省 行政不服審査裁決・答申検索データベース: https://fufukudb.search.soumu.go.jp/
