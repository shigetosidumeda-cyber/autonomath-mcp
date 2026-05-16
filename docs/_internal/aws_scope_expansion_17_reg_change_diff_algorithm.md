# AWS Scope Expansion 17/30: 法令改正・制度変更差分アルゴリズム

作成日: 2026-05-15  
対象: jpcite JP public-primary-source corpus / GEO-first packet factory  
前提: AWSコマンド、AWS API、リソース作成、デプロイは行わない。本文書は設計のみ。  
出力先: `/Users/shigetoumeda/jpcite/docs/_internal/aws_scope_expansion_17_reg_change_diff_algorithm.md`

## 0. 結論

このサービスで最も価値が出る差分アルゴリズムは、単なる「条文の変更検知」ではなく、次の一連の変化を一次情報ベースでつなぐものです。

1. パブコメで案が出る。
2. 結果公示で修正有無が出る。
3. 官報または所管省庁ページで公布・告示・通知が出る。
4. e-Gov法令XMLに反映される。
5. 所管省庁のガイドライン、Q&A、手続ページ、様式、標準処理期間が更新される。
6. 業種・許認可・補助金・調達・社内規程・会計CSVレビューに影響する候補が出る。

jpciteが売るべき成果物は、この流れを `source_receipts[]` と `claim_refs[]` で固定し、AIエージェントがエンドユーザーへそのまま渡せる「対応候補packet」に変換したものです。

重要な設計原則は以下です。

- request-time LLMで結論を作らない。
- 差分、期限、対象、必要アクション候補はすべて一次情報のspanまたは構造化フィールドに紐づける。
- LLMやembeddingを使う場合は、候補抽出、分類補助、重複候補の並び替えまでに限定する。
- 「該当なし」は「見つからなかった」だけであり、安全、不要、対象外の証明にしない。
- 法的判断、適法性判断、最終対応要否は出さず、「確認候補」として返す。
- private CSVはAWSへ上げない。CSV由来の事実を使う場合も、ローカル/ユーザー側で抽出した集計・安全識別子だけをprivate overlayとして扱う。

## 1. 作るべき成果物から逆算した位置づけ

### 1.1 高単価になりやすい成果物

法令改正・制度変更差分から売りやすい成果物は、次のようなものです。

| packet | エンドユーザーの問い | 価値 | 価格帯案 |
|---|---|---:|---:|
| `reg_change_impact_brief` | この改正は自社に関係あるか | 影響候補、対象業種、期限、確認先を1枚化 | 500-3,000円/件 |
| `industry_reg_change_digest` | 建設/運輸/人材/金融などで今月変わった制度は何か | 業種別に読むべき変更だけを絞る | 1,000-5,000円/月 |
| `deadline_action_calendar` | 対応期限が近いものだけ知りたい | 施行日、締切、受付期間、経過措置を整理 | 500-2,000円/社/月 |
| `public_comment_to_final_rule_trace` | パブコメ案から最終ルールで何が変わったか | 案、結果、公布、施行の追跡 | 1,000-5,000円/案件 |
| `guideline_update_diff` | ガイドライン/Q&Aがどこだけ変わったか | 省庁ページやPDFの差分を証跡付きで提示 | 500-3,000円/件 |
| `compliance_checklist_delta` | 社内規程/表示/契約/帳票を直す必要候補は何か | 実務アクション候補に翻訳 | 1,000-10,000円/件 |
| `permit_requirement_change_packet` | 許認可や届出要件に変更があるか | 業法、許認可、行政処分リスクをつなぐ | 2,000-20,000円/件 |
| `csv_overlay_reg_change_review` | 会計/給与/取引先CSVから関係しそうな変更はどれか | private factsと公的制度差分の突合 | 1,000-10,000円/回 |

この担当のアルゴリズムは、上記packetの共通基盤として、以下を生成する。

- `change_events[]`: 何が変わったか。
- `impact_candidates[]`: 誰に関係しそうか。
- `deadline_candidates[]`: いつまでに見るべきか。
- `action_candidates[]`: 何を確認すべきか。
- `evidence_graph`: それを支える一次情報の関係グラフ。
- `known_gaps[]`: 分からないこと、未確認のこと、制度上判断できないこと。

## 2. 対象ソース

### 2.1 P0-A: まず差分基盤に必須

| source family | 代表ソース | 取れる情報 | 取得方式 | 差分価値 |
|---|---|---|---|---|
| `law_xml` | e-Gov 法令API / XML一括ダウンロード | 法令ID、法令番号、条文XML、更新法令、施行日 | API、bulk XML | 条文単位の正確なdiff |
| `public_comment` | e-Gov パブリック・コメント | 案件番号、案の公示日、締切、結果公示、提出意見数、所管省庁 | RSS、HTML、添付PDF | 案から確定までの追跡 |
| `gazette` | 官報発行サイト | 法律、政省令、告示、公告、公布日、号外等 | PDF/HTML、Playwright screenshot、OCR | 公布・告示の原本証跡 |
| `ministry_guidance` | 所管省庁の告示/通達/ガイドライン/Q&A/様式 | 実務運用、解釈、期限、手続 | HTML/PDF、Playwright、OCR | 実務アクション候補 |
| `system_pages` | 制度ページ、申請案内、標準処理期間、手続ページ | 受付期間、対象者、必要書類、窓口 | HTML/PDF/screenshot | 補助金・許認可・手続packet |

### 2.2 P0-B: 業種別packetで価値が高い

| source family | 例 | 使い道 |
|---|---|---|
| `license_registry` | 建設業者、宅建業者、金融庁登録業者、医療機能、介護事業者 | 対象業種・許認可の照合 |
| `administrative_sanction` | ネガティブ情報、行政処分、命令、公表 | 変更後のリスク/義務候補 |
| `grant_procurement` | J-Grants、自治体補助金、調達ポータル、入札公告 | 制度変更から機会packetへ接続 |
| `statistics_taxonomy` | e-Stat、産業分類、自治体コード | 業種、地域、規模の絞り込み |

### 2.3 source_profileに必須の項目

各ソースは、収集前に `source_profile` として固定する。

```json
{
  "source_profile_id": "egov_law_api_v1",
  "source_family": "law_xml",
  "official_name": "e-Gov法令検索 法令API Version 1",
  "publisher": "Digital Agency",
  "base_url": "https://laws.e-gov.go.jp/",
  "fetch_methods": ["api", "bulk_xml"],
  "canonical_time_fields": ["promulgation_date", "enforcement_date", "updated_date"],
  "stable_ids": ["law_id", "law_no", "article_path"],
  "robots_terms_status": "reviewed",
  "license_boundary": "public_primary_source_with_terms_check",
  "allowed_outputs": ["source_receipts", "claim_refs", "diff_summaries", "packet_examples"],
  "disallowed_outputs": ["legal_advice", "proof_of_compliance", "proof_of_non_applicability"]
}
```

## 3. 共通データモデル

### 3.1 source_receipt

全ての差分は、まずreceipt化する。

```json
{
  "source_receipt_id": "sr_20260515_egov_405AC0000000088_20260401",
  "source_profile_id": "egov_law_api_v1",
  "retrieved_at": "2026-05-15T09:00:00+09:00",
  "source_url": "https://laws.e-gov.go.jp/api/1/lawdata/405AC0000000088",
  "document_id": "405AC0000000088",
  "document_title": "行政手続法",
  "document_date": null,
  "effective_date": "2026-04-01",
  "content_type": "application/xml",
  "fetch_method": "api",
  "raw_sha256": "sha256:...",
  "normalized_sha256": "sha256:...",
  "snapshot_ref": "s3://temporary-run-bucket/snapshots/...",
  "screenshot_refs": [],
  "parser_version": "lawxml-normalizer@0.1.0",
  "known_gaps": []
}
```

### 3.2 normalized_document

ソース形式がXML、HTML、PDF、スクリーンショット/OCRのどれでも、差分処理前に同じ抽象構造に変換する。

```json
{
  "normalized_document_id": "nd_...",
  "source_receipt_id": "sr_...",
  "doc_kind": "law_xml",
  "stable_doc_key": "law:405AC0000000088",
  "version_key": "effective:2026-04-01",
  "title": "行政手続法",
  "publisher": "Digital Agency",
  "nodes": [
    {
      "node_id": "law:405AC0000000088:main:article:1:paragraph:1:sentence:1",
      "node_type": "sentence",
      "path": ["MainProvision", "Article[1]", "Paragraph[1]", "Sentence[1]"],
      "display_label": "第一条第一項第一文",
      "text": "...",
      "normalized_text": "...",
      "source_span": {
        "xml_xpath": "/Law/LawBody/MainProvision/Article[@Num='1']/Paragraph[@Num='1']/ParagraphSentence/Sentence[@Num='1']"
      },
      "hash_exact": "sha256:...",
      "hash_normalized": "sha256:...",
      "tokens": ["..."]
    }
  ]
}
```

### 3.3 change_event

変更は、必ず「旧receipt」「新receipt」「旧node」「新node」に紐づける。

```json
{
  "change_event_id": "chg_...",
  "change_type": "modified",
  "doc_kind": "law_xml",
  "stable_doc_key": "law:405AC0000000088",
  "old_source_receipt_id": "sr_old",
  "new_source_receipt_id": "sr_new",
  "old_node_id": "law:...:article:1:paragraph:1",
  "new_node_id": "law:...:article:1:paragraph:1",
  "structural_path_before": "第一条第一項",
  "structural_path_after": "第一条第一項",
  "diff_spans": [
    {
      "op": "replace",
      "before": "30日",
      "after": "45日",
      "before_offset": [120, 123],
      "after_offset": [120, 123]
    }
  ],
  "detected_entities": {
    "dates": [],
    "money": [],
    "durations": ["30日", "45日"],
    "obligation_verbs": []
  },
  "change_class_candidates": ["deadline_or_period_changed"],
  "claim_refs": ["cr_..."],
  "confidence": {
    "change_detection": "high",
    "impact_classification": "medium"
  },
  "known_gaps": []
}
```

### 3.4 impact_candidate

「対象業種」「必要アクション」は法的判断ではなく候補として出す。

```json
{
  "impact_candidate_id": "imp_...",
  "change_event_id": "chg_...",
  "affected_vertical_candidates": [
    {
      "vertical_id": "construction",
      "label": "建設業",
      "basis": "source_taxonomy_and_keyword",
      "claim_refs": ["cr_..."],
      "confidence": "medium"
    }
  ],
  "affected_actor_candidates": [
    {
      "actor_type": "licensed_business_operator",
      "label": "許認可を受けている事業者",
      "basis": "text_span",
      "claim_refs": ["cr_..."],
      "confidence": "high"
    }
  ],
  "not_a_legal_conclusion": true
}
```

### 3.5 action_candidate

```json
{
  "action_candidate_id": "act_...",
  "change_event_id": "chg_...",
  "action_type": "internal_policy_review",
  "title": "社内規程・手続期限の確認候補",
  "who_should_check": ["法務", "総務", "許認可担当"],
  "why": "条文上の期間表現が変更されたため",
  "deadline_candidates": [
    {
      "date": "2026-04-01",
      "kind": "enforcement_date",
      "condition_text": null,
      "claim_refs": ["cr_..."]
    }
  ],
  "claim_refs": ["cr_..."],
  "human_review_required": true,
  "forbidden_claims": [
    "対応不要",
    "適法です",
    "この会社は対象外です"
  ]
}
```

## 4. パイプライン全体

### 4.1 Stage A: Discovery

目的は、取得対象の新旧snapshot候補を見つけること。

入力:

- e-Gov更新法令一覧。
- e-Gov XML一括ダウンロード。
- e-GovパブコメのRSS/案件一覧/結果公示。
- 官報の発行日別ページ、PDF、号外。
- 所管省庁の新着情報、法令、告示、通達、ガイドライン、Q&A、制度ページ。
- 自治体/業界別サイトのRSS、新着ページ、サイトマップ。

出力:

- `discovery_event`
- `fetch_candidate`
- `source_profile_missing_review`

主なルール:

- 公式ソース以外はP0では使わない。
- 民間解説記事は候補発見に使っても、claim_refsにはしない。
- APIまたはbulkがあるものはPlaywrightより優先する。
- Playwrightはfetchが難しい公開一次情報、JS描画、PDFリンク探索、スクリーンショット証跡に使う。
- CAPTCHA、ログイン、アクセス制限回避、規約違反の自動化はしない。

### 4.2 Stage B: Snapshot Capture

各fetch candidateを、再現可能なsnapshotにする。

取得するもの:

- raw response body
- response headers
- final URL
- fetch timestamp
- content hash
- HTML/PDF/XML/text
- Playwright screenshot
- page title
- visible text
- discovered links
- PDF metadata
- OCR入力画像

スクリーンショット方針:

- 幅は1600px以下。
- 原則: desktop 1440px、mobile必要時 390px。
- full page screenshotは巨大化するため、証跡に必要な範囲を優先。
- 対象spanを含む画面、タイトル、URL、更新日、本文周辺を保存。
- screenshot単独でclaimを作らず、HTML/PDF/XML textと合わせてreceiptにする。

### 4.3 Stage C: Canonicalization

差分を安定させるため、形式ごとの揺れを取り除く。

#### 4.3.1 法令XML

正規化対象:

- XML namespace差異。
- 空白、全角/半角の揺れ。
- `Sentence`、`Item`、`Subitem` の番号属性。
- `SupplProvision` の改正附則。
- 別表、様式、画像参照。
- ルビ、注、表。

安定node id:

```text
law:{LawId}:{provision_kind}:{chapter?}:{section?}:article:{Article@Num}:paragraph:{Paragraph@Num}:item:{Item@Num}:sentence:{Sentence@Num}
```

注意:

- 条ずれ、号ずれ、枝番号、別表差し替えを考慮する。
- 改正附則は施行日・経過措置の候補として重要。
- 法令全体のhashだけでは使い物にならない。条、項、号、文、別表セル単位までhash化する。

#### 4.3.2 官報/PDF

正規化対象:

- PDFテキスト抽出。
- ページ番号、段組み、縦書き、脚注。
- OCR結果の座標。
- 告示番号、公布日、号外番号。

OCR品質:

- OCR confidenceが低いspanはclaimに使わない。
- 官報のPDF本文とe-Gov反映後の法令XMLが一致/対応する場合は、法令XMLを主証跡、官報を公布証跡にする。
- 告示・公告などe-Gov XMLに入らないものは、官報PDF/HTMLを主証跡にする。

#### 4.3.3 省庁HTML/PDF/制度ページ

正規化対象:

- nav/footer/sidebar除去。
- 更新日、所管、問い合わせ先、対象者、手続名、受付期間、必要書類。
- 見出し階層。
- 箇条書き、表、注記。
- PDFリンク、様式ファイルリンク。

stable node:

```text
page:{canonical_url}:heading_path:{hash(heading_path)}:block:{ordinal_or_hash}
```

HTML構造が不安定な省庁ページでは、見出しテキストと近傍本文hashを組み合わせる。

### 4.4 Stage D: Structural Diff

差分は3層で取る。

1. document-level diff: 文書の追加、削除、URL変更、タイトル変更。
2. node-level diff: 条、項、見出し、表、PDFセクションごとの追加/削除/変更/移動。
3. span-level diff: 文中の置換、数値、期限、対象者、義務表現の変化。

推奨アルゴリズム:

- XML tree matching: stable path一致を最優先。
- path不一致時: normalized text hash、見出し、近傍node、LCSで対応付け。
- move/renumber detection: 旧nodeと新nodeのtext similarityが高く、pathだけ変わった場合は `moved_or_renumbered`。
- token diff: 日本語tokenizer + char-level diffを併用。
- table diff: 行見出し、列見出し、セルhashで対応付け。
- appendix/form diff: 表や様式はdocument-level変更だけでなく、項目名と入力欄名を抽出する。

変更タイプ:

| change_type | 意味 | 例 |
|---|---|---|
| `added` | 新規条文/見出し/項目 | 新たな届出義務 |
| `deleted` | 削除 | 経過措置終了、要件削除 |
| `modified` | 文章変更 | 期限、対象、手続変更 |
| `moved_or_renumbered` | 移動/番号変更 | 第三条が第四条へ |
| `threshold_changed` | 数値要件変更 | 金額、人数、面積、期間 |
| `deadline_changed` | 締切・施行日・受付期間変更 | 2026-04-01施行 |
| `obligation_strength_changed` | 義務表現の強さ変更 | 努めるから義務へ |
| `scope_changed` | 対象者/対象業種変更 | 中小企業、特定事業者 |
| `procedure_changed` | 手続・書類・様式変更 | 申請書様式改定 |
| `penalty_or_sanction_changed` | 罰則/処分/公表変更 | 罰金額、命令、公表 |
| `benefit_or_subsidy_changed` | 補助金/助成/給付要件変更 | 上限額、対象経費 |
| `draft_to_final_linked` | パブコメ案と結果/公布の接続 | 案件番号から追跡 |

### 4.5 Stage E: Entity and Signal Extraction

差分spanから、実務影響に関係するentityを抽出する。

抽出対象:

- 日付: 公布日、施行日、締切日、受付開始/終了、経過措置期限。
- 期間: 30日、3か月、毎年、四半期、速やかに。
- 金額: 円、万円、補助率、上限額、課徴金、手数料。
- 数量: 従業員数、面積、台数、排出量、売上、資本金。
- 対象者: 事業者、許可業者、登録業者、特定事業者、中小企業者。
- 業種: 建設、運輸、人材、金融、医療、介護、食品、産廃、不動産、IT/個人情報。
- 地域: 都道府県、市区町村、管轄。
- 手続: 申請、届出、報告、保存、表示、公表、確認、許可、登録、更新。
- 書類: 様式、添付書類、証明書、台帳、帳簿。
- 義務/禁止/努力義務/裁量: しなければならない、してはならない、努めなければならない、できる、必要がある。

義務表現の重み:

| phrase class | examples | weight |
|---|---|---:|
| strict_obligation | しなければならない、義務、必要がある | 1.00 |
| prohibition | してはならない、禁止 | 1.00 |
| conditional_obligation | 場合には、対象となる、該当するとき | 0.80 |
| effort | 努めなければならない、努めるものとする | 0.55 |
| permission | できる、可能 | 0.35 |
| guidance | 望ましい、留意する | 0.25 |

注意:

- weightは優先順位付け用であり、法的結論ではない。
- phrase単体で義務を断定しない。条文構造、主語、条件、例外も同時に見る。

### 4.6 Stage F: Cross-source Linkage

変更は単独文書ではなく、制度変更の連鎖としてつなぐ。

リンクキー:

- `law_id`
- `law_no`
- `amend_no`
- `amend_name`
- `promulgation_date`
- `enforcement_date`
- `public_comment_case_no`
- `ministry`
- `gazette_issue_date`
- `gazette_issue_no`
- `notice_no`
- `guideline_title`
- `canonical_url`
- `article_reference`

リンクの種類:

| edge_type | from | to | 意味 |
|---|---|---|---|
| `proposal_for` | public comment draft | law/guideline | 案件が変更対象を示す |
| `result_for` | public comment result | draft | 結果公示 |
| `promulgates` | gazette | law amendment | 官報で公布/告示 |
| `updates_xml` | e-Gov updated law | law XML version | 法令XML反映 |
| `interprets` | guideline/Q&A | law article | ガイドラインが条文を解釈/運用 |
| `changes_procedure` | system page | form/procedure | 手続/様式変更 |
| `affects_registry` | law/guidance | license registry | 許認可/登録業者に関係 |
| `creates_opportunity` | regulation/grant notice | grant/procurement | 補助金/入札機会に関係 |

edge confidence:

- `direct`: 文書内で法令番号、案件番号、告示番号、URLが直接一致。
- `strong`: タイトル、日付、所管、対象法令が一致。
- `medium`: タイトル類似、所管、時期、キーワードが一致。
- `weak`: 候補のみ。packetで主張に使わない。

## 5. 期限・対応日付アルゴリズム

### 5.1 date_candidateの種類

```json
{
  "date_candidate_id": "date_...",
  "date": "2026-04-01",
  "date_kind": "enforcement_date",
  "condition_text": "ただし、次の各号に掲げる規定は...",
  "source_span": {
    "source_receipt_id": "sr_...",
    "node_id": "law:...:suppl:article:1"
  },
  "confidence": "high",
  "needs_human_review": false
}
```

date_kind:

- `promulgation_date`
- `enforcement_date`
- `public_comment_open_date`
- `public_comment_close_date`
- `result_publication_date`
- `application_open_date`
- `application_close_date`
- `transition_deadline`
- `reporting_deadline`
- `renewal_deadline`
- `effective_from`
- `effective_until`
- `unknown_or_conditional`

### 5.2 期限解決の優先順位

1. 構造化APIフィールドの施行日/締切。
2. 法令XMLの改正附則にある施行期日。
3. 官報の公布日/告示日。
4. パブコメ案件の締切/結果公示日。
5. 所管省庁ページの受付期間、適用日、更新日。
6. PDF本文中の日付表現。
7. OCRからの候補。OCR confidenceが低い場合はhuman review。

### 5.3 条件付き施行日の扱い

法令には「一部の規定は別日」「公布の日から起算して...」「政令で定める日」のような条件付き日付が多い。これを単一日付に潰さない。

出力:

- `deadline_candidates[]` に複数保持。
- `condition_text` を原文span付きで保持。
- 対象条項との対応が不明なら `known_gaps` に入れる。
- AIエージェント向け文言は「期限候補」「施行日候補」「条件付き」の表現にする。

禁止:

- 条件付き日付を確定期限として断定する。
- 「この日までに対応必須」と断定する。
- 期限が見つからない場合に「期限なし」と言う。

## 6. 影響範囲推定アルゴリズム

### 6.1 impactは3段階に分ける

1. `direct_impact`: 文書中に対象業種、対象者、許認可名が直接書いてある。
2. `linked_impact`: 対象法令や所管省庁から業種taxonomyに接続できる。
3. `candidate_impact`: キーワード、制度名、登録簿、過去packetから候補化する。

packetで強い表現にできるのは `direct_impact` と `linked_impact` まで。`candidate_impact` は「確認候補」に留める。

### 6.2 vertical taxonomy

初期vertical:

- 建設
- 不動産
- 運輸
- 人材/労務
- 産廃/環境
- 食品/飲食
- 医療/介護
- 金融
- IT/個人情報
- 輸出入/貿易
- 補助金/中小企業支援
- 調達/入札
- 税務/会計
- 消費者対応/表示

各verticalは以下を持つ。

```json
{
  "vertical_id": "construction",
  "labels": ["建設", "建設業", "建築", "住宅"],
  "law_refs": ["建設業法", "建築基準法"],
  "registry_refs": ["mlit_construction_license"],
  "ministry_refs": ["国土交通省"],
  "procedure_keywords": ["許可", "経営事項審査", "入札参加資格"],
  "negative_signal_sources": ["mlit_negative_info"],
  "packet_templates": ["permit_requirement_change_packet", "vendor_risk_packet"]
}
```

### 6.3 impact priority score

優先順位付けは、売上と実務重要度のために必要。ただしscoreは法的結論ではない。

```text
impact_priority =
  source_authority_weight
  * change_type_weight
  * obligation_weight
  * deadline_urgency_weight
  * vertical_revenue_weight
  * evidence_confidence_weight
  * recency_weight
```

例:

- `source_authority_weight`: e-Gov法令XML、官報、所管省庁公式を高くする。
- `change_type_weight`: 罰則、許認可、期限、対象範囲、義務を高くする。
- `deadline_urgency_weight`: 30日以内、90日以内、半年以内。
- `vertical_revenue_weight`: 建設、運輸、人材、金融、医療/介護、産廃、補助金/調達を高める。
- `evidence_confidence_weight`: direct 1.0、strong 0.85、medium 0.55、weak 0.2。

計算例:

```json
{
  "impact_priority": 0.68,
  "score_components": {
    "source_authority_weight": 1.0,
    "change_type_weight": 0.9,
    "obligation_weight": 0.8,
    "deadline_urgency_weight": 0.7,
    "vertical_revenue_weight": 1.2,
    "evidence_confidence_weight": 0.9,
    "recency_weight": 1.0
  },
  "score_is_not_legal_judgment": true
}
```

## 7. action_candidate生成

### 7.1 テンプレート方式

生成文は自由生成しない。テンプレートにsource spanを差し込む。

テンプレート:

```text
{source_title} の {changed_part_label} に変更があります。
変更種別は {change_class} の候補です。
{affected_actor} に関係する可能性があります。
{date_kind} は {date} の候補です。
根拠: {claim_refs}
注意: これは法的判断ではなく、一次情報に基づく確認候補です。
```

### 7.2 action_type

| action_type | 出す条件 | 例 |
|---|---|---|
| `read_change_brief` | 重要度が低くても更新あり | 変更点確認 |
| `deadline_review` | 施行日/締切/受付期間が変わった | カレンダー登録候補 |
| `internal_policy_review` | 義務/禁止/努力義務/保存/報告が変わった | 社内規程確認 |
| `contract_or_terms_review` | 表示、契約、利用規約、説明義務が変わった | 約款確認 |
| `permit_or_registration_review` | 許可、登録、更新、届出が変わった | 許認可担当確認 |
| `form_update_review` | 様式、添付書類、電子申請が変わった | 申請書式確認 |
| `customer_notice_review` | 顧客通知/表示/公表が変わった | 顧客案内確認 |
| `vendor_check_review` | 取引先資格/行政処分/登録が関係 | 取引先審査 |
| `grant_or_procurement_review` | 補助金/入札/公募が関係 | 申請準備候補 |
| `csv_overlay_review` | 会計/給与/取引先の安全集計と関係 | private overlay確認 |

### 7.3 禁止文言

以下はpacketで出さない。

- 「対応不要です」
- 「適法です」
- 「違法です」
- 「対象外です」
- 「この会社は申請できます」
- 「リスクはありません」
- 「法令違反はありません」
- 「この変更だけ見れば十分です」

許容文言:

- 「確認候補です」
- 「一次情報上、関連する可能性があります」
- 「期限候補です」
- 「対象者候補です」
- 「人による確認が必要です」
- 「このsource setでは追加情報が見つかっていません」

## 8. no-hitとknown_gaps

### 8.1 no-hitの意味

no-hitは、検索対象source setで該当する候補が見つからなかったことだけを意味する。

```json
{
  "no_hit": true,
  "no_hit_meaning": "no_hit_not_absence",
  "searched_sources": ["egov_law_update", "public_comment_rss"],
  "not_searched_sources": ["local_government_pdf", "paid_database"],
  "known_gaps": [
    {
      "gap_type": "source_scope_gap",
      "message": "自治体PDFは今回の検索対象外です。"
    }
  ]
}
```

### 8.2 known_gaps類型

- `source_scope_gap`: まだ収集していないsource family。
- `parser_gap`: OCR、表、画像、様式などでparse不十分。
- `linkage_gap`: パブコメと官報/法令XMLの接続が弱い。
- `date_gap`: 条件付き施行日が解決できない。
- `vertical_gap`: 業種候補が直接sourceに書かれていない。
- `private_context_gap`: 会社の事業内容、許認可、従業員数、所在地が必要。
- `human_review_gap`: 人の確認が必要。

## 9. Playwright / screenshot / OCRの使い方

### 9.1 使う場面

- APIやbulkで取れない省庁ページ。
- JS描画で本文やPDFリンクが出るページ。
- 官報や自治体サイトなど、証跡として画面保存が必要なページ。
- PDFリンク一覧がHTMLから取れないページ。
- 取得後に「その時点で見えていた情報」を示す必要があるページ。

### 9.2 使わない場面

- e-Gov法令XMLのようにAPI/bulkがあるもの。
- robots/termsで自動取得が不適切なもの。
- CAPTCHA、ログイン、アクセス制限があるもの。
- 負荷試験に近い大量アクセス。

### 9.3 screenshot receipt

```json
{
  "screenshot_receipt_id": "ss_...",
  "source_receipt_id": "sr_...",
  "viewport": {
    "width": 1440,
    "height": 1200,
    "device_scale_factor": 1
  },
  "capture_mode": "targeted_section",
  "image_sha256": "sha256:...",
  "visible_url": "https://...",
  "visible_title": "...",
  "contains_claim_span": true,
  "claim_span_bbox": [120, 340, 920, 520],
  "ocr_used": false
}
```

### 9.4 OCR policy

- OCRはtext extractionの補助。
- OCR由来spanは `ocr_confidence` を持つ。
- 重要claimには、可能ならPDF embedded text、HTML text、法令XMLで再確認する。
- OCRだけが根拠の場合は `human_review_required=true`。

## 10. AWS実行時の設計への接続

この文書ではAWSコマンドは実行しない。ただし、実際のAWS credit runに組み込む場合は以下の構成にする。

### 10.1 自走設計

Codex/Claude Codeのrate limitが来ても、AWS側は止まらず進むようにする。

- job specsをS3に置く。
- AWS BatchまたはStep Functionsでqueue駆動にする。
- 各jobはidempotentにする。
- `run_manifest` に全job、input、output、status、cost tagを記録する。
- CloudWatch Events/EventBridgeで定期的にqueueを進める。
- cost stoplineだけは自動で新規job投入を止める。
- operatorが不在でもdrainできる。

### 10.2 速くcreditを価値に変える優先順位

1. e-Gov bulk/XML差分を全量処理。
2. パブコメ案件/結果の広域取得。
3. 官報/告示/公告のPDF/HTML/screenshot/OCR処理。
4. 所管省庁の業種別ガイドライン/通達/Q&A/様式の広域取得。
5. 建設、不動産、運輸、人材、産廃、金融、医療/介護、食品のvertical packet生成。
6. Playwright screenshot/OCRを広げ、fetch困難ページを補完。
7. GEO proof pages、OpenAPI/MCP例、packet examplesに変換。
8. 全成果物をrepo/import可能な形式でexport。
9. AWS zero-bill cleanup。

### 10.3 credit stoplineとの接続

既存統合計画と同じ停止線を使う。

- Watch: USD 17,000。
- Slowdown: USD 18,300。
- No-new-work: USD 18,900。
- Stretch manual approval: USD 19,100-19,300。
- Absolute safety line: USD 19,300。

USD 19,493.94を厳密な目標にしない。Cost Explorer、請求反映、税、非credit対象、data transfer、ログ、public IPv4などの遅延/例外があるため、現金請求を避けるには安全余白が必要。

## 11. 実装ジョブ案

### 11.1 RCD-J01: law XML snapshot

目的:

- e-Gov法令API/bulkから法令XML snapshotを作る。

成果物:

- `source_receipts/law_xml/*.jsonl`
- `normalized_documents/law_xml/*.jsonl`
- `law_node_index/*.parquet`

QA:

- XML parse成功率。
- LawId/LawNum/LawTitle coverage。
- Article/Paragraph/Sentence node count。
- hash stability。

### 11.2 RCD-J02: law update diff

目的:

- 更新法令一覧と過去snapshotから差分を作る。

成果物:

- `change_events/law_xml/*.jsonl`
- `diff_spans/law_xml/*.jsonl`
- `deadline_candidates/law_xml/*.jsonl`

QA:

- 旧版/新版のpairing率。
- moved/renumbered誤検出率。
- 施行日抽出率。

### 11.3 RCD-J03: public comment trace

目的:

- パブコメの募集案件、結果公示、添付資料を追跡する。

成果物:

- `source_receipts/public_comment/*.jsonl`
- `public_comment_cases/*.jsonl`
- `proposal_result_edges/*.jsonl`

QA:

- 案件番号coverage。
- 締切/結果日coverage。
- 添付PDF取得率。

### 11.4 RCD-J04: gazette notice capture

目的:

- 官報の公布/告示/公告を取得し、法令XML/省庁ページへリンクする。

成果物:

- `source_receipts/gazette/*.jsonl`
- `gazette_notice_index/*.jsonl`
- `gazette_law_edges/*.jsonl`
- `screenshot_receipts/gazette/*.jsonl`

QA:

- 発行日coverage。
- PDF text extraction率。
- OCR confidence分布。
- 官報番号/日付/告示番号抽出率。

### 11.5 RCD-J05: ministry guidance diff

目的:

- 告示、通達、ガイドライン、Q&A、制度ページの差分を取る。

成果物:

- `source_receipts/ministry_guidance/*.jsonl`
- `normalized_documents/ministry_guidance/*.jsonl`
- `change_events/ministry_guidance/*.jsonl`

QA:

- canonical URL dedupe。
- nav/footer除去精度。
- PDF/HTML同一文書の重複排除。
- 更新日抽出率。

### 11.6 RCD-J06: entity and deadline extraction

目的:

- 日付、期限、金額、義務表現、対象者、業種を抽出する。

成果物:

- `detected_entities/*.jsonl`
- `deadline_candidates/*.jsonl`
- `obligation_signal_candidates/*.jsonl`

QA:

- date parse precision。
- conditional date recall。
- threshold extraction precision。

### 11.7 RCD-J07: impact graph

目的:

- 法令/制度変更を業種、許認可、手続、補助金/調達、CSV overlay候補へ接続する。

成果物:

- `evidence_graph/edges/*.jsonl`
- `impact_candidates/*.jsonl`
- `vertical_impact_index/*.jsonl`

QA:

- direct/strong/medium/weak edge distribution。
- weak edgeがclaim_refsに昇格していないこと。
- vertical mapping explainability。

### 11.8 RCD-J08: action packet materialization

目的:

- AIエージェントに売れるpacketを作る。

成果物:

- `packet_examples/reg_change_impact_brief/*.json`
- `packet_examples/deadline_action_calendar/*.json`
- `packet_examples/guideline_update_diff/*.json`
- `packet_examples/public_comment_trace/*.json`

QA:

- source_receipts必須。
- claim_refs必須。
- known_gaps必須。
- forbidden claims scan。
- request_time_llm_call_performed=false。

## 12. packet schema

### 12.1 reg_change_impact_brief

```json
{
  "packet_type": "reg_change_impact_brief",
  "packet_version": "0.1.0",
  "query_context": {
    "vertical": "construction",
    "region": "Japan",
    "date_range": {
      "from": "2026-04-01",
      "to": "2026-05-15"
    }
  },
  "summary": {
    "title": "建設業向け制度変更の確認候補",
    "not_legal_advice": true,
    "request_time_llm_call_performed": false
  },
  "change_events": [],
  "impact_candidates": [],
  "deadline_candidates": [],
  "action_candidates": [],
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "billing_metadata": {
    "unit": "packet",
    "estimated_source_count": 0
  },
  "human_review_required": true,
  "_disclaimer": "一次情報に基づく確認候補であり、法的助言または適法性判断ではありません。"
}
```

### 12.2 claim_ref

```json
{
  "claim_ref_id": "cr_...",
  "claim_text": "施行日候補は2026-04-01です。",
  "source_receipt_id": "sr_...",
  "node_id": "law:...",
  "source_span": {
    "start": 120,
    "end": 132,
    "text_hash": "sha256:..."
  },
  "support_level": "direct",
  "must_not_expand_beyond_span": true
}
```

## 13. アルゴリズム詳細

### 13.1 XML tree matching

手順:

1. 旧XMLと新XMLをparseする。
2. nodeごとにstable pathを作る。
3. stable pathが一致するnodeをpairにする。
4. stable pathが消えたnode、新しく出たnodeを候補集合にする。
5. 候補集合内でnormalized text similarityを計算する。
6. similarityが高いものをmove/renumber候補にする。
7. 残りをadded/deletedにする。
8. pairごとにspan diffを取る。
9. 数値/日付/義務表現の変化をclassifyする。

擬似コード:

```text
old_nodes = normalize_law_xml(old_xml)
new_nodes = normalize_law_xml(new_xml)

pairs = match_by_stable_path(old_nodes, new_nodes)
unmatched_old, unmatched_new = subtract_matched(old_nodes, new_nodes, pairs)

move_pairs = match_by_similarity(
  unmatched_old,
  unmatched_new,
  keys = [node_type, heading, normalized_text, neighbor_hash],
  threshold = 0.86
)

events = []
for pair in pairs + move_pairs:
  if pair.hash_normalized_equal:
    continue
  spans = token_and_char_diff(pair.old.text, pair.new.text)
  classes = classify_change(spans, pair.old, pair.new)
  events.append(change_event(pair, spans, classes))

for node in unmatched_new - move_pairs.new:
  events.append(added(node))

for node in unmatched_old - move_pairs.old:
  events.append(deleted(node))
```

### 13.2 Japanese legal text tokenization

tokenizerは補助であり、最終diffは文字位置も保持する。

正規化:

- Unicode normalize NFKC。ただし法令番号や固有表記は原文も保持。
- 全角数字/漢数字を数値候補として並列保持。
- 句読点、括弧、号番号をtokenに保持。
- 「一」「二」「三」が号番号か数値かをpath contextで判定。

### 13.3 table diff

表は通常の文章diffでは誤差が大きい。

手順:

1. caption、表番号、直前見出しを取得。
2. header row/columnを推定。
3. row keyを作る。
4. column keyを作る。
5. cell単位でhash比較。
6. 金額、補助率、対象経費、必要書類の変化をclassifyする。

### 13.4 guideline page diff

省庁ページはHTML構造が頻繁に変わるため、DOM pathだけに依存しない。

matching key:

- canonical URL
- title
- heading path
- nearest heading text
- normalized block text hash
- published/updated date
- PDF filename
- link text

noise除去:

- nav
- footer
- SNS
- breadcrumb
- 共通問い合わせ枠
- アクセシビリティリンク
- サイト内検索

ただし、問い合わせ先が制度上重要な場合は `contact_block` として別nodeに残す。

### 13.5 public comment to final trace

手順:

1. パブコメ案件番号を主キーにする。
2. 募集案件から、案件名、案の公示日、締切、所管、省令案/告示案/PDFを取得。
3. 結果公示から、結果公示日、提出意見数、修正有無、資料PDFを取得。
4. 案件名と対象法令名をextractする。
5. 官報/告示/e-Gov更新法令と `title_similarity + ministry + date window + law_no` で候補リンクする。
6. `direct` でないlinkはpacket上で「接続候補」と表示する。

### 13.6 promulgation to enforcement resolution

公布日と施行日は別物なので混同しない。

優先:

- `enforcement_date` field
- 改正附則の施行期日
- 官報/法令本文内の施行期日
- 所管省庁ページの適用日

出力では必ず `date_kind` を付ける。

## 14. 品質ゲート

### 14.1 release blocker

以下が1つでもある場合、production packetに出さない。

- `source_receipts[]` が空。
- `claim_refs[]` が空。
- `known_gaps[]` がない。
- `request_time_llm_call_performed` がtrue。
- OCRのみで重要claimを断定している。
- weak linkageを直接根拠として強い結論に使っている。
- no-hitをabsence/safetyとして表現している。
- 施行日と公布日を混同している。
- パブコメ案を確定ルールとして表現している。
- 条件付き施行日を単一の確定期限として表現している。
- 法的助言、適法性判断、対応不要判断が含まれる。
- private CSV raw dataを保持/表示/ログに出している。

### 14.2 metric

| metric | 目標 |
|---|---:|
| source_receipt coverage | 100% |
| claim_ref coverage for user-facing claims | 100% |
| date_kind coverage | 99%+ |
| no-hit safe wording | 100% |
| forbidden claim count | 0 |
| weak edge promoted to claim | 0 |
| screenshot width policy violation | 0 |
| raw CSV leak | 0 |

### 14.3 golden fixtures

最低限必要なfixture:

- 法令XMLで条文が1語だけ変わる。
- 条番号がずれる。
- 附則の施行日だけ変わる。
- 別表の金額が変わる。
- パブコメ募集から結果公示に移る。
- 官報告示だけに出る変更。
- 省庁PDFの様式が変わる。
- HTMLページのnavだけが変わる。
- OCR confidenceが低くhuman reviewに落ちる。
- no-hitの安全表現。

## 15. 本体P0計画へのマージ順

このアルゴリズムは、本体P0計画では以下の順で入れる。

1. `source_profile` 拡張: law/public_comment/gazette/ministry_guidance/system_pagesを登録。
2. `source_receipt` schema拡張: screenshot/OCR/PDF metadataを追加。
3. `normalized_document` と `normalized_node` を追加。
4. `change_event` schemaを追加。
5. e-Gov法令XML diffの最小実装。
6. パブコメ案件/結果traceの最小実装。
7. 官報/告示receiptの最小実装。
8. ministry guideline diffの最小実装。
9. `impact_candidate` と `action_candidate` を追加。
10. `reg_change_impact_brief` packetを生成。
11. `deadline_action_calendar` packetを生成。
12. GEO proof pageへ公開例を追加。
13. OpenAPI/MCP toolに `get_reg_change_packet` と `list_deadline_candidates` を追加。
14. production release gateに差分packetのforbidden claim testを追加。

## 16. MCP/API tool案

### 16.1 `get_reg_change_packet`

入力:

```json
{
  "vertical": "construction",
  "date_from": "2026-04-01",
  "date_to": "2026-05-15",
  "region": "JP",
  "include_action_candidates": true,
  "include_public_comment_trace": true
}
```

出力:

- `reg_change_impact_brief`
- `source_receipts[]`
- `claim_refs[]`
- `known_gaps[]`
- `billing_metadata`

### 16.2 `diff_law_article`

入力:

```json
{
  "law_id": "405AC0000000088",
  "article": "1",
  "old_date": "2025-04-01",
  "new_date": "2026-04-01"
}
```

出力:

- article-level diff
- span diff
- source receipts
- date candidates

### 16.3 `list_deadline_candidates`

入力:

```json
{
  "vertical": "food",
  "date_to": "2026-06-30",
  "deadline_kinds": ["enforcement_date", "application_close_date"]
}
```

出力:

- deadline candidates
- action candidates
- source receipts
- known gaps

## 17. 売上に直結する初期packet候補

### 17.1 建設業向け

- 建設業法/建築基準法/国交省告示/ネガティブ情報/入札制度変更。
- 成果物: `permit_requirement_change_packet`、`deadline_action_calendar`、`bid_eligibility_change_brief`。

### 17.2 人材/労務向け

- 労働法令、助成金、社会保険、最低賃金、雇用関係様式。
- 成果物: `labor_reg_change_digest`、`subsidy_deadline_packet`。

### 17.3 金融/士業向け

- 金融庁登録、監督指針、パブコメ、法令改正。
- 成果物: `financial_compliance_change_brief`、`client_alert_draft_evidence_packet`。

### 17.4 食品/飲食向け

- 食品衛生、表示、営業許可、リコール、公表。
- 成果物: `food_label_rule_change_packet`、`permit_update_checklist`。

### 17.5 IT/個人情報向け

- 個人情報保護委員会ガイドライン、Q&A、漏えい報告、委託先管理。
- 成果物: `privacy_guideline_diff`、`privacy_action_candidate_packet`。

### 17.6 補助金/調達向け

- J-Grants、自治体補助金、官報公告、調達ポータル。
- 成果物: `grant_rule_change_packet`、`procurement_requirement_change_brief`。

## 18. リスクと対策

| risk | 内容 | 対策 |
|---|---|---|
| 法令XML反映遅延 | 官報とe-Gov更新にタイムラグ | 官報receiptとe-Gov receiptを別扱い |
| パブコメ案の誤用 | 案を確定制度と誤解 | `status=draft/result/final` を必須 |
| 条件付き施行日 | 一部施行、政令委任 | 複数date candidateとcondition_text |
| OCR誤認識 | 縦書きPDF、表、画像 | confidenceとhuman review |
| 省庁ページ改修 | DOM pathが変わる | heading/text hashで対応 |
| weak linkage | タイトル類似だけで接続 | weakはclaimに使わない |
| 法的助言化 | 対応要否を断定 | action candidateに限定 |
| private CSV漏えい | raw CSVの保持 | raw不保存、derived factsのみ |
| AWS過剰課金 | OCR/Playwright/logs肥大 | stopline、log retention、queue throttle |

## 19. 実装時の最小P0スライス

最初に作るべき最小機能:

1. e-Gov法令XMLのsnapshotとnode index。
2. update law listからの新旧diff。
3. date/threshold/obligation signal抽出。
4. パブコメ案件番号と結果公示のreceipt化。
5. 官報または省庁ページのscreenshot receipt最小対応。
6. `reg_change_impact_brief` packet 20例。
7. `deadline_action_calendar` packet 20例。
8. forbidden claims test。
9. GEO proof page 10例。

これだけで、AIエージェントは以下を推薦できる。

- 「この業種の制度変更を証跡付きで確認できます」
- 「施行日・締切候補をカレンダー化できます」
- 「パブコメ案から最終ルールまで追跡できます」
- 「社内規程/許認可/補助金/調達の確認候補に変換できます」

## 20. 参照した公式情報

- e-Gov法令検索 法令API Version 1: `https://laws.e-gov.go.jp/docs/law-data-basic/8529371-law-api-v1/`
- e-Gov法令検索 XML一括ダウンロード: `https://laws.e-gov.go.jp/bulkdownload/`
- e-Gov法令検索 更新法令一覧: `https://laws.e-gov.go.jp/update/`
- e-Gov法令XML構造ドキュメント: `https://laws.e-gov.go.jp/docs/law-data-basic/8ebd8bc-law-structure-and-xml/`
- 法令API Version2 リリース告知: `https://laws.e-gov.go.jp/file/%E6%B3%95%E4%BB%A4API%E3%83%90%E3%83%BC%E3%82%B8%E3%83%A7%E3%83%B32%E3%83%AA%E3%83%AA%E3%83%BC%E3%82%B9%E3%81%AE%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B.pdf`
- e-Gov APIカタログ 法令API: `https://api-catalog.e-gov.go.jp/info/ja/apicatalog/view/44`
- e-Gov パブリック・コメント: `https://public-comment.e-gov.go.jp/servlet/Public`
- e-Gov RSSフィードについて: `https://www.e-gov.go.jp/service-policy/rssfeed.html`

