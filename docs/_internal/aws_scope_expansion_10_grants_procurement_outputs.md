# AWS scope expansion 10/30: grants, subsidies, public calls, and procurement outputs

作成日: 2026-05-15
担当: 拡張深掘り 10/30 - 補助金・助成金・公募・入札成果物
対象: jpcite 本体計画、AWS credit run、J-Grants、自治体制度、官報/公示、調達ポータル、JETRO、e-Gov、業法、CSV-derived facts
状態: 計画のみ。AWS CLI/APIコマンド、AWSリソース作成、デプロイ、既存コード変更は行っていない。
出力先: `docs/_internal/aws_scope_expansion_10_grants_procurement_outputs.md`

## 0. 結論

「エンドユーザーがAIに『使える制度を探して』と頼む」場面から逆算すると、補助金・助成金・公募・入札は jpcite の中でも最も売上に近い領域である。

理由は次の通り。

- ユーザーの問いが明確で、支払い意思が発生しやすい。
- 回答に公的一次情報の根拠が必須で、汎用LLMだけでは断定しづらい。
- J-Grants、ミラサポplus、厚労省助成金、自治体、調達ポータル、官報/公示、e-Gov、業法を組み合わせると、単なる検索結果ではなく「候補、根拠、期限、必要書類、未確認範囲、次アクション」を返せる。
- freee / MoneyForward / 弥生などのCSV-derived factsを加えると、ユーザーの事業実態に近い候補順位付けができる。ただし raw CSV は保存・公開・AWS投入しない。
- AIエージェントは「申請できると断定する」よりも、「一次情報ベースで候補を絞り、ギャップを明示し、専門家/窓口確認に渡す」方が安全に推薦できる。

本担当の推奨は、補助金・公募・入札を `subsidy_procurement_output_factory` として本体P0に昇格させることである。

優先順位:

1. `制度候補レーダー`: 低単価・高頻度。AIエージェントが最初に呼びやすい。
2. `CSV overlay 制度候補`: raw CSVなしで事業実態を使う高単価版。
3. `申請準備チェックリスト`: 期限、必要書類、様式、未確認事項を返す。
4. `入札機会レーダー`: 調達ポータル/自治体/JETROを横断するB2B高単価領域。
5. `落札実績/競合/発注機関分析`: 継続課金に向く。
6. `制度変更watch`: e-Gov、官報、パブコメ、所管省庁、自治体差分を使う継続課金。

絶対に守る制約:

- 「使える」「対象」「採択される」「落札できる」「該当なし」と断定しない。
- `no_hit` は常に `no_hit_not_absence`。接続済みsourceで見つからないことは、不存在・不適格・安全の証明ではない。
- request-time LLM は行わない。出力は prebuilt / deterministic / source-backed / reviewable にする。
- CSVは private overlay。raw CSVの永続化、ログ、再配布、引用、スクリーンショット化をしない。
- 公的sourceのraw全文ミラーを売らない。売るのは `source_receipts[]`, `claim_refs[]`, `known_gaps[]`, extracted facts, derived rankings, packet outputs。

## 1. ユーザーの自然な依頼から逆算する

### 1.1 典型プロンプト

AIエージェント側で想定される自然な依頼:

| User prompt | 真のニーズ | jpciteが返すべき成果物 |
|---|---|---|
| うちが使える補助金を探して | 候補の棚卸し、期限、金額、根拠 | `grant_opportunity_radar` |
| このCSVから使える制度ある？ | 事業実態に即した候補順位付け | `csv_overlay_grant_match` |
| IT導入やAI導入に使えるものは？ | DX/IT/AI系の制度候補 | `dx_it_ai_subsidy_pack` |
| 人を採用したい。助成金ある？ | 雇用・訓練・賃上げ系 | `labor_grant_match_pack` |
| 省エネ設備を入れたい | 省エネ・脱炭素・設備投資 | `energy_capex_support_pack` |
| 開業する場所で使える支援は？ | 自治体、創業、空き店舗、地域制度 | `local_startup_program_pack` |
| 補助金申請前に何を準備すればいい？ | 必要書類と不足情報 | `application_readiness_checklist` |
| この補助金に申し込める？ | 要件照合、断定回避 | `eligibility_gap_packet` |
| 入札案件を探して | 公開中案件、資格、期限、仕様 | `procurement_opportunity_radar` |
| 官公庁に売れる先を探して | 発注機関、過去落札、品目 | `public_sales_target_dossier` |
| 競合はどこが落札している？ | 落札実績、金額、発注機関 | `award_competitor_ledger` |
| 来月締切の制度だけ出して | 時限性の高い候補 | `deadline_action_calendar` |
| この業法で必要な登録や許可は？ | 制度利用/入札参加前提の許認可 | `permit_prerequisite_map` |
| 併用できる補助金は？ | 同一経費/補助重複のリスク整理 | `stacking_caution_packet` |

### 1.2 売上になる理由

この領域は「情報検索」ではなく「損益に直結する意思決定支援」である。

ユーザー側の経済価値:

- 補助金候補を1件見つけるだけで、補助上限が数十万から数千万円の可能性がある。
- 申請準備の漏れを減らせる。
- 入札案件の発見が売上機会に直結する。
- 過去落札実績から営業先、競合、価格帯を把握できる。
- 助成金・補助金・入札は締切があるため、継続watchの需要がある。

jpcite側の商用価値:

- AIエージェントが低単価packetを大量に呼びやすい。
- CSV overlayや入札分析は高単価にできる。
- 継続watchでMRR化できる。
- public proof pageに「なぜ汎用LLMではなくjpciteか」を説明しやすい。

## 2. 本体計画とのマージ位置

現行P0への追加位置:

| P0 epic | 本担当で追加するもの |
|---|---|
| P0-E1 Packet contract/catalog | `grant_opportunity_radar`, `csv_overlay_grant_match`, `procurement_opportunity_radar` などをpacket typeに追加 |
| P0-E2 Source receipts/claims/gaps | 補助金・公募・入札向けの `program_round`, `eligibility_rule`, `procurement_notice`, `award_record` schema |
| P0-E3 Pricing/cost preview | 低単価候補検索、高単価CSV overlay、継続watchの価格表 |
| P0-E4 CSV privacy/intake | raw CSVなしで `derived_business_facts` を制度候補へ接続 |
| P0-E5 Packet composers | 補助金/入札packet composerをP0-Aへ追加 |
| P0-E6 REST facade | `/packets/grants/*`, `/packets/procurement/*` |
| P0-E7 MCP tools | `find_grants`, `match_grants_with_private_facts`, `find_procurement_notices`, `build_application_checklist` |
| P0-E8 Proof/discovery | GEO向け公開ページ: grants/procurement agent guides |
| P0-E9 Release gates | no-hit誤表現、採択保証、CSV漏洩、古い締切、source混同をblockerに追加 |

統合順:

```text
1. Packet contract freeze
2. Source profile / terms / license boundary
3. J-Grants + national program spine
4. Local program and ministry PDF expansion
5. Procurement portal + award open data spine
6. e-Gov / law / public comment / gazette support links
7. CSV-derived facts overlay design
8. Deterministic matching and ranking
9. Packet/proof fixture generation
10. REST/MCP examples
11. GEO discovery pages
12. release gates
13. staging
14. production
15. AWS artifact export
16. zero-bill cleanup
```

## 3. Source composition

### 3.1 Core source families

| Source family | Primary source examples | Role in outputs | Confidence tier |
|---|---|---|---|
| `jgrants_public` | J-Grants public API/search/detail | 国・自治体補助金の候補、募集期間、上限、補助率、添付資料 | A |
| `mirasapo_program` | ミラサポplus、中小企業庁関連ページ | 中小企業向け主要制度、制度ナビ、補助金チラシ、申請ポイント | A/B |
| `mhlw_grants` | 厚労省助成金・奨励金、労働局資料 | 雇用、労働条件、人材開発、賃上げ、業務改善助成金 | A/B |
| `ministry_program_pages` | 経産省、国交省、環境省、農水省等 | 所管省庁ごとの公募、補助、委託、基金 | A/B |
| `local_government_program` | 都道府県/市区町村公式サイト、自治体ODS | 地域補助金、給付金、創業、空き店舗、許認可 | A/B/C |
| `gazette_public_notice` | 官報、公告、公示 | 公布、公告、政府調達、制度イベント | B |
| `p_portal_procurement` | 調達ポータル検索、GEPS関連、落札実績オープンデータ | 公開中調達、落札実績、発注機関、品目 | A/B |
| `jetro_procurement` | JETRO入札/公募/契約情報 | 海外展開・展示会・調査系の公募/入札 | A/B |
| `egov_law_policy` | e-Gov法令、電子申請、RSS、パブコメ | 根拠法令、制度変更、申請手続、予兆 | A/B |
| `industry_regulation` | 建設、運輸、食品、医療、金融、人材などの業法source | 対象業種、許認可、入札資格の前提 | A/B |
| `csv_derived_private` | freee/MF/Yayoi等からの派生fact | 業種・費目・投資・人件費・売上傾向による候補順位付け | private derived |

### 3.2 J-Grantsで取れるべき情報

J-Grantsは最初の制度spineである。

保持するfact:

| Field | 用途 | 注意 |
|---|---|---|
| subsidy id | stable key | バージョン/詳細APIの差分を保持 |
| title/name | 表示と検索 | 年度・回次混同に注意 |
| use purpose | ユーザー意図との照合 | 自由文は分類器ではなくcontrolled mapping |
| industry | 業種候補 | 日本標準産業分類との完全一致扱いにしない |
| target area | 地域照合 | `全国` と都道府県/自治体名を分ける |
| employee range | 従業員条件 | CSV単体では従業員数が出ない場合が多い |
| subsidy rate | 予算目安 | 対象経費/税抜/上限条件を別管理 |
| subsidy max limit | 金額表示 | 申請上限であり受給保証ではない |
| acceptance start/end | deadline calendar | 延長/予算到達/締切変更をknown_gap |
| project deadline | 実施期間 | 交付決定前着手不可などの条件に注意 |
| guideline files | 詳細要件 | base64添付やPDF hash、ページ参照化 |
| application forms | 必要書類 | raw form再配布の可否はterms確認 |

### 3.3 J-Grantsだけでは足りない理由

J-Grantsは重要だが、それだけではjpciteの価値にならない。

不足:

- すべての自治体制度がJ-Grantsに完全掲載されるとは限らない。
- 公募要領PDFの細かい対象外経費、必要書類、加点、事前登録、提出方法はAPIの一覧項目だけでは不足する。
- 助成金、融資、税制、入札、公募委託は別sourceに分かれる。
- 業法上の資格・許認可・所在地要件はJ-Grants単体では確定しない。
- 締切変更、予算到達、FAQ改定、様式差し替えは所管ページが正本になる場合がある。

したがって、J-Grantsは `program candidate spine` とし、最終packetでは必ず `supporting_sources[]` を接続する。

## 4. Output-first product catalog

### 4.1 売上優先度の考え方

評価軸:

```text
revenue_priority_score =
  0.30 * user_frequency
+ 0.25 * willingness_to_pay
+ 0.20 * agent_recommendability
+ 0.15 * source_backing_strength
+ 0.10 * repeatability
- 0.20 * liability_risk
- 0.10 * operational_complexity
```

このscoreは販売優先度であり、適格性判断ではない。

価格帯は「エンドユーザーがAI経由で安く取れる」前提のpacket単価で設計する。専門家相談や申請代行の価格帯とは競合させず、一次情報ベースの下調べ・整理・準備に限定する。

### 4.2 P0-A: すぐ売るべき成果物

| ID | 成果物 | 想定価格/API | 売上優先 | 返す内容 | 必要source | no-hit表現 |
|---|---|---:|---:|---|---|---|
| GPO-01 | `grant_opportunity_radar` | 300-800円 | 100 | 条件に近い制度候補、根拠URL、締切、上限、未確認範囲 | J-Grants, ミラサポ, 自治体, 省庁 | 接続済みsourceでは候補未確認 |
| GPO-02 | `csv_overlay_grant_match` | 1,200-3,000円 | 98 | CSV-derived factsで候補順位付け、費目/売上傾向との接続 | GPO-01 + derived facts | CSVから判定不能な項目をgap |
| GPO-03 | `application_readiness_checklist` | 500-1,500円 | 95 | 必要書類、様式、事前準備、締切、窓口 | 公募要領, 申請ページ, FAQ | 必要書類がsourceから抽出不能 |
| GPO-04 | `eligibility_gap_packet` | 800-2,000円 | 94 | 要件ごとの充足候補/不足/要確認 | 公募要領, 業法, CSV facts | 不適格ではなく未確認 |
| GPO-05 | `deadline_action_calendar` | 300-1,000円 | 90 | 30/60/90日以内の制度締切と次アクション | J-Grants, 自治体, 省庁 | 期限付き候補未確認 |
| GPO-06 | `procurement_opportunity_radar` | 800-3,000円 | 93 | 公開中案件、発注機関、品目、締切、参加前提 | 調達ポータル, 自治体, JETRO | 接続済みsourceで案件未確認 |
| GPO-07 | `bid_readiness_checklist` | 1,000-4,000円 | 88 | 統一資格、電子証明書、GビズID、提出書類、仕様確認 | 調達ポータル, 入札公告, 業法 | 参加可否は発注機関確認 |
| GPO-08 | `award_competitor_ledger` | 1,500-8,000円 | 86 | 過去落札者、金額、発注機関、品目推移 | 落札実績OD, p-portal, 自治体 | 落札実績未確認は競合不在でない |
| GPO-09 | `public_sales_target_dossier` | 2,000-10,000円 | 87 | 発注機関別の需要、過去案件、次回watch条件 | 調達, 落札, 官報, 予算資料 | 次回発注を保証しない |
| GPO-10 | `program_change_watch` | 月980-4,980円 | 91 | 新規/締切変更/FAQ/要領改定/パブコメ予兆 | e-Gov, RSS, 官報, 省庁, 自治体 | 未検知は変更なしの証明でない |

### 4.3 P0-B: 業種別に刺さる成果物

| ID | 成果物 | 主要ユーザー | 想定価格/API | 必要データ | 価値 |
|---|---|---|---:|---|---|
| GPO-11 | `dx_it_ai_subsidy_pack` | 小規模事業者、SaaS導入企業、会計事務所 | 800-2,500円 | IT/AI導入補助、DX施策、CSV費目 | 導入予定支出と制度候補をつなぐ |
| GPO-12 | `labor_grant_match_pack` | 採用/人材育成/賃上げ企業 | 1,000-3,000円 | 厚労省助成金、賃金/人件費derived facts | 助成金の見落としを減らす |
| GPO-13 | `energy_capex_support_pack` | 工場、店舗、物流、設備更新 | 1,000-4,000円 | 省エネ/脱炭素制度、設備支出候補 | 設備投資の補助候補 |
| GPO-14 | `startup_local_program_pack` | 創業者、士業、自治体支援機関 | 500-2,000円 | 自治体創業/空き店舗/融資/商工会 | 地域別の制度棚卸し |
| GPO-15 | `food_restaurant_program_pack` | 飲食/食品製造 | 800-2,500円 | 食品営業許可、自治体支援、商店街補助 | 許認可と制度を接続 |
| GPO-16 | `construction_procurement_pack` | 建設/設備/工事業 | 1,500-6,000円 | 建設業許可、入札、経審/資格、調達 | 入札前提と案件探索 |
| GPO-17 | `healthcare_care_grant_pack` | 医療/介護/福祉 | 1,500-6,000円 | 介護/医療制度、自治体補助、公募 | 制度が分散する領域を整理 |
| GPO-18 | `export_overseas_support_pack` | 輸出/海外展開企業 | 1,000-4,000円 | JETRO, 経産省, 自治体海外展開支援 | 海外展開施策の候補化 |
| GPO-19 | `rural_agri_food_support_pack` | 農水/食品加工/6次産業 | 1,000-4,000円 | 農水省, 自治体, J-Grants | 地方制度との相性が高い |
| GPO-20 | `resilience_disaster_support_pack` | 災害/物価/緊急支援対象 | 500-2,000円 | 自治体, 中小企業庁, 官報/公示 | 緊急性の高い制度探索 |

### 4.4 P1: 高単価・継続課金向け成果物

| ID | 成果物 | 想定価格 | 説明 |
|---|---:|---|---|
| GPO-21 | `grant_portfolio_board` | 月4,980-29,800円 | 会社・地域・業種ごとの制度候補を継続watch |
| GPO-22 | `procurement_watch_board` | 月9,800-49,800円 | 発注機関/品目/地域/競合で入札案件を監視 |
| GPO-23 | `public_funding_flow_map` | 5,000-30,000円 | 補助金・基金・委託・予算事業の流れを整理 |
| GPO-24 | `policy_to_program_alert` | 月2,980-19,800円 | パブコメ/官報/省庁資料から制度化の予兆をwatch |
| GPO-25 | `advisor_workbench_export` | 10,000-100,000円 | 士業/コンサル向けに根拠付き候補表をCSV/JSON出力 |
| GPO-26 | `application_evidence_bundle` | 3,000-15,000円 | 申請準備のための根拠、必要書類、未確認事項を束ねる |
| GPO-27 | `bid_spec_decomposition` | 3,000-20,000円 | 入札公告/仕様書の要求事項、提出物、評価項目を分解 |
| GPO-28 | `award_price_benchmark` | 3,000-30,000円 | 過去落札価格と品目の範囲付き比較 |
| GPO-29 | `agency_demand_profile` | 5,000-50,000円 | 発注機関の品目・時期・金額・落札先傾向 |
| GPO-30 | `grant_procurement_combined_growth_plan` | 5,000-30,000円 | 補助金で能力整備し、公共営業へつなぐ計画 |

## 5. Output details

### 5.1 `grant_opportunity_radar`

目的:

AIエージェントが最初に安く呼べる「制度候補一覧」。エンドユーザーの自然条件から、公的一次情報に接続した候補だけを返す。

入力:

```json
{
  "location": "東京都渋谷区",
  "industry_hint": "飲食店",
  "business_stage": "既存事業",
  "intent": "省エネ設備を入れたい",
  "company_size_hint": "小規模",
  "deadline_window_days": 90,
  "private_facts_available": false
}
```

出力:

```json
{
  "packet_type": "grant_opportunity_radar",
  "request_time_llm_call_performed": false,
  "results": [
    {
      "program_round_id": "prg_...",
      "title": "制度名",
      "source_family": "jgrants_public",
      "match_strength": "candidate_high",
      "why_matched": [
        {
          "claim": "対象地域が東京都を含む候補として抽出された",
          "claim_ref": "cr_..."
        }
      ],
      "amount_summary": {
        "subsidy_rate": "source_text_or_normalized",
        "max_amount": 1000000,
        "amount_caution": "上限額であり受給保証ではない"
      },
      "deadline": {
        "acceptance_end": "2026-06-15",
        "deadline_confidence": "source_backed"
      },
      "next_actions": [
        "公募要領の対象者欄を確認",
        "対象経費に該当する見積を分けて確認"
      ],
      "source_receipts": ["sr_..."],
      "known_gaps": ["kg_..."]
    }
  ],
  "no_hit_policy": "no_hit_not_absence"
}
```

売り方:

- 無料/低額のpreviewで上位3件だけ表示。
- 有料packetで根拠、締切、必要書類、known gapsを返す。
- AIエージェントには「この候補を申請可否に変換しない」制約込みで返す。

### 5.2 `csv_overlay_grant_match`

目的:

ユーザーが会計CSVをAIに渡したとき、raw CSVを保存せずに、derived factsだけで制度候補を順位付けする。

使えるderived facts:

| CSV由来fact | 例 | 使い道 | 注意 |
|---|---|---|---|
| revenue_trend | 直近月次売上の増減 | 事業成長/減少/災害支援候補 | 採択/対象判定にはしない |
| expense_categories | 広告費、消耗品、旅費、外注費 | 対象経費候補との照合 | 勘定科目名は各社差分あり |
| capex_hint | 工具器具備品、機械装置 | 設備投資系補助候補 | 固定資産台帳がないと弱い |
| software_saas_spend | ソフトウェア、通信費、クラウド | IT/DX/AI導入候補 | 既支出と補助対象時期に注意 |
| payroll_hint | 給与、法定福利費 | 雇用/賃上げ/人材開発系 | 従業員数や賃金改定は別途確認 |
| rent_location_hint | 地代家賃、支店名 | 地域/店舗/空き店舗制度候補 | 住所の正規化が必要 |
| vendor_concentration | 特定取引先支出 | 事業転換/設備/外注支援候補 | 取引先名は公開しない |
| invoice_tax_hint | 消費税/インボイス関連 | インボイス対応/会計ソフト系 | 税務判断はしない |

処理方針:

```text
raw CSV -> local/session parser -> derived facts -> salted hash / aggregate -> packet composer
```

禁止:

- raw CSVをAWS S3へアップロードしない。
- raw CSV行、摘要、取引先名、金額明細をpacketに出さない。
- 個別の支出が補助対象になると断定しない。

出力文言:

- 良い: 「CSV由来の集計では、IT/クラウド関連支出の候補が検出されたため、DX/IT系制度を上位にしています」
- 悪い: 「このソフトウェア費用は補助対象です」

### 5.3 `application_readiness_checklist`

目的:

申請前に「何を用意するか」を返す。これは検索より支払い意思が強い。

項目:

| Checklist item | Source | 出力例 |
|---|---|---|
| 公募期間 | J-Grants / 所管ページ | 受付開始/終了、変更watch |
| 対象者 | 公募要領 | 法人種別、所在地、従業員、業種 |
| 対象事業 | 公募要領 | 設備導入、販路開拓、IT導入等 |
| 対象経費 | 公募要領 | 機械装置、広報費、委託費等 |
| 対象外経費 | 公募要領 | 交付決定前発注、汎用品等 |
| 補助率/上限 | J-Grants / 要領 | 表示、条件分岐 |
| 加点/優先 | 要領/FAQ | 賃上げ、認定、計画書等 |
| 必要書類 | 要領/申請ページ | 事業計画、見積、決算書等 |
| 申請方法 | J-Grants/所管ページ | GビズID、電子申請、郵送 |
| 事前登録 | GビズID/認定支援機関等 | 所要日数は保証しない |
| 相談先 | 公式窓口 | 窓口名、URL |

AIへの返し方:

```text
このpacketは準備事項の整理です。申請可否、採択可能性、専門的判断は保証しません。
```

### 5.4 `eligibility_gap_packet`

目的:

ユーザーが「申し込める？」と聞いた時に、断定せず、要件ごとに証拠と不足を返す。

判定段階:

| Status | 意味 | 表示 |
|---|---|---|
| `source_backed_match_candidate` | sourceと入力factが近い | 候補として表示 |
| `user_fact_missing` | 必要なユーザー情報がない | 質問候補へ |
| `source_ambiguous` | source文言が曖昧/抽出弱い | 人間確認 |
| `potential_conflict` | 入力factと要件が衝突する可能性 | 注意 |
| `not_evaluated` | 未対応source/未取得 | known_gap |

禁止:

- `eligible=true`
- `ineligible=true`
- `will_be_accepted=true`
- `safe_to_apply=true`

### 5.5 `procurement_opportunity_radar`

目的:

調達ポータル、自治体、JETROなどから、公開中/最近確認された入札・公募案件を候補化する。

入力:

```json
{
  "products_or_services": ["Web制作", "システム保守"],
  "regions": ["東京都", "全国"],
  "agency_types": ["central_government", "local_government", "jetro"],
  "deadline_window_days": 60,
  "qualification_hints": ["全省庁統一資格なし", "GビズIDあり"]
}
```

返す内容:

| Field | 説明 |
|---|---|
| procurement_notice_id | 案件ID |
| title | 案件名 |
| procuring_entity | 発注機関 |
| procurement_kind | 入札公告、意見招請、資料招請、随意契約関連等 |
| product_category | 品目分類 |
| region | 地域/履行場所 |
| publish_date | 公開日 |
| deadline | 入札/提出期限 |
| participation_prerequisites | 統一資格、電子証明書、GビズID、業許可等 |
| source_receipts | 根拠 |
| known_gaps | 未確認範囲 |

安全文言:

- 良い: 「公開中sourceで条件に近い案件候補を確認しました」
- 悪い: 「この案件に参加できます」

### 5.6 `award_competitor_ledger`

目的:

過去落札実績から、市場・競合・価格帯を把握する。

返す内容:

| Field | 説明 |
|---|---|
| award_record_id | 落札実績ID |
| awardee_name | 落札者名 |
| awardee法人番号候補 | exact matchのみ |
| amount | 落札金額 |
| procuring_entity | 発注機関 |
| procurement_title | 件名 |
| award_date | 落札日 |
| product_category | 品目 |
| source_receipts | 調達ポータル/自治体/公告 |
| name_match_confidence | 法人名寄せの信頼度 |

禁止:

- 競合の信用評価を断定しない。
- 名称一致だけで同一法人と断定しない。
- 落札価格から次回価格を保証しない。

### 5.7 `program_change_watch`

目的:

締切変更、公募開始、要領改定、FAQ更新、パブコメ結果、官報公示などを監視する継続課金商品。

watch対象:

- J-Grants新規/更新
- ミラサポplus掲載変更
- 所管省庁の公募ページ
- 自治体制度ページ/PDF/Excel
- e-Gov RSS/パブコメ
- 官報/公示/公告
- 調達ポータル公開案件/落札実績

出力:

```json
{
  "packet_type": "program_change_watch",
  "changes": [
    {
      "change_type": "deadline_updated",
      "program_round_id": "prg_...",
      "old_value_hash": "sha256:...",
      "new_value": "2026-06-15",
      "source_receipts": ["sr_..."],
      "action": "申請準備期限を再確認"
    }
  ],
  "known_gaps": [
    {
      "gap_type": "source_not_checked_today",
      "source_family": "local_government_program"
    }
  ]
}
```

## 6. Deterministic matching design

### 6.1 Matching should produce candidates, not conclusions

制度候補の順位付けは、`eligibility` ではなく `candidate fit` として出す。

```text
candidate_fit_score =
  25 * location_signal
+ 20 * purpose_signal
+ 15 * industry_signal
+ 15 * size_signal
+ 10 * expense_signal
+ 10 * deadline_signal
+  5 * source_quality_signal
- 20 * missing_required_user_facts_penalty
- 15 * stale_source_penalty
- 15 * terms_unclear_penalty
- 30 * explicit_conflict_penalty
```

表示区分:

| Score | Label | 表示 |
|---:|---|---|
| 80-100 | `candidate_high` | 上位候補。ただし申請可否ではない |
| 60-79 | `candidate_medium` | 条件に近い候補 |
| 40-59 | `candidate_low` | 参考候補 |
| 0-39 | `not_ranked` | 表示しないか、known_gap |

### 6.2 Feature definitions

| Feature | 取り方 | 注意 |
|---|---|---|
| location_signal | 都道府県/市区町村/全国/事業所所在地 | 本店所在地と実施場所を分ける |
| purpose_signal | ユーザー意図と制度目的のcontrolled mapping | LLM分類ではなく辞書/embedding offline |
| industry_signal | J-Grants industry / 業法 / CSV費目 | 業種名は曖昧なのでgapを残す |
| size_signal | 従業員/資本金/売上規模 | CSVで従業員数は通常取れない |
| expense_signal | 対象経費とCSV-derived expense | 既支出が対象外の場合がある |
| deadline_signal | 現在日と受付終了 | 延長/予算到達で変わる |
| source_quality_signal | API/公式PDF/検索画面/OCR | OCRはconfidence gate |

### 6.3 Conflict handling

`explicit_conflict` の例:

- 募集終了日が過去で、延長sourceがない。
- 対象地域が明示的に異なる。
- 対象者が法人限定なのに入力が個人のみ。
- 業種が明示的に除外されている。
- 交付決定前着手不可の制度で、CSV-derived factsが既支出を示す可能性がある。

ただし、conflictがあっても「対象外」と断定せず、`potential_conflict` として返す。

## 7. Data requirements by output

| Output | 必須データ | あると高価値なデータ | なくても出せるか |
|---|---|---|---|
| `grant_opportunity_radar` | J-Grants, ミラサポ, 省庁/自治体source profile | CSV-derived facts, 業法, e-Gov | 可能 |
| `csv_overlay_grant_match` | derived facts, program candidates | 固定資産/従業員/所在地正規化 | raw CSVなしで可能 |
| `application_readiness_checklist` | 公募要領/PDF/申請ページ | FAQ, 様式, GビズID情報 | 要領がないと低品質 |
| `eligibility_gap_packet` | 要件抽出, ユーザーfact | 業法/許認可/所在地 | gaps多めで可能 |
| `deadline_action_calendar` | 受付開始/終了/締切 | 変更watch, FAQ更新 | 可能 |
| `procurement_opportunity_radar` | 調達公告/検索結果 | 資格情報, 過去落札 | 可能 |
| `bid_readiness_checklist` | 入札公告/仕様書 | 統一資格/業許可source | 仕様書が必要 |
| `award_competitor_ledger` | 落札実績OD | 法人番号名寄せ, gBizINFO | 可能 |
| `public_sales_target_dossier` | 過去案件/発注機関/品目 | 予算資料, 官報, 公募予定 | 可能 |
| `program_change_watch` | source snapshots/diffs | RSS, Playwright screenshot, PDF hash | 継続sourceが必要 |

## 8. AWS job plan for this domain

この担当の追加jobは、既存 J01-J24 の中に `GPO lane` として差し込む。

### 8.1 New lane names

| Job | Name | Purpose | Output |
|---|---|---|---|
| GPO-J01 | program source profile | 補助金/助成金/公募/入札sourceのterms/robots/profile | `program_source_profiles.jsonl` |
| GPO-J02 | J-Grants API mirror | J-Grants一覧/詳細/API schema drift取得 | `jgrants_program_rounds.parquet` |
| GPO-J03 | guideline attachment parser | 公募要領/交付要綱/様式のmetadata/extracted sections | `program_documents.jsonl` |
| GPO-J04 | Mirasapo national tracker | 中小企業向け主要制度/チラシ/申請ポイント | `mirasapo_program_events.jsonl` |
| GPO-J05 | MHLW grant tracker | 厚労省助成金/労働局系制度source候補 | `mhlw_grant_candidates.jsonl` |
| GPO-J06 | ministry program crawler | 所管省庁の公募/補助/委託ページ | `ministry_program_candidates.jsonl` |
| GPO-J07 | local program crawler | 自治体補助金/支援制度/給付金 | `local_program_candidates.jsonl` |
| GPO-J08 | p-portal notice capture | 調達ポータル検索/公告receipt | `procurement_notices.jsonl` |
| GPO-J09 | p-portal award open data | 落札実績ODの全件/差分 | `award_records.parquet` |
| GPO-J10 | JETRO procurement capture | JETRO入札/公募/契約情報 | `jetro_procurement_candidates.jsonl` |
| GPO-J11 | e-Gov policy connector | 法令/電子申請/RSS/パブコメ接続 | `policy_change_refs.jsonl` |
| GPO-J12 | industry prerequisite crosswalk | 業法/許認可/資格の前提条件 | `permit_prerequisite_crosswalk.jsonl` |
| GPO-J13 | CSV derived fact harness | synthetic/header-only fixtureで照合検証 | `csv_overlay_match_tests.jsonl` |
| GPO-J14 | deterministic matcher | 候補score/gap/rank生成 | `grant_procurement_match_candidates.jsonl` |
| GPO-J15 | packet fixture factory | packet/proof examples | `packet_examples/grants_procurement/*.json` |
| GPO-J16 | no-hit and forbidden-claim eval | 断定/保証/漏洩をblock | `grant_procurement_eval_report.json` |

### 8.2 Playwright/screenshot use

使う場面:

- 調達ポータルの検索画面や詳細画面で、通常fetchだけではDOMが不安定な場合。
- 自治体ページがJS/古いCMS/PDFリンク混在で、リンク抽出が不安定な場合。
- 公募ページの更新差分を視覚的に確認したい場合。

制限:

- viewportは1600px以下。
- screenshotは証跡であり、公開成果物の主データにしない。
- CAPTCHA、ログイン突破、アクセス制限回避、総当たり検索は禁止。
- 個人情報/非公開情報/応募者マイページは対象外。

保存するmetadata:

```json
{
  "capture_id": "cap_...",
  "url": "https://...",
  "final_url": "https://...",
  "viewport": {"width": 1280, "height": 1600},
  "captured_at": "2026-05-15T00:00:00Z",
  "dom_sha256": "sha256:...",
  "screenshot_sha256": "sha256:...",
  "robots_decision": "allowed_or_manual_review",
  "public_publish_allowed": false,
  "source_receipt_id": "sr_..."
}
```

## 9. Schema proposals

### 9.1 `program_round`

```json
{
  "schema_id": "jpcite.program_round",
  "schema_version": "2026-05-15",
  "program_round_id": "prg_...",
  "source_family": "jgrants_public",
  "source_program_id": "S0J...",
  "title": "制度名",
  "institution_name": "所管/実施機関",
  "program_type": "subsidy|grant|benefit|loan|tax|public_call|unknown",
  "target_area": {
    "normalized": ["JP-13"],
    "source_text": "東京都 / 全国"
  },
  "industry_targets": [],
  "use_purposes": [],
  "employee_requirements": [],
  "amount_rules": [],
  "date_rules": [],
  "document_refs": [],
  "source_receipts": [],
  "known_gaps": [],
  "claim_refs": []
}
```

### 9.2 `program_requirement`

```json
{
  "schema_id": "jpcite.program_requirement",
  "requirement_id": "req_...",
  "program_round_id": "prg_...",
  "requirement_type": "target_user|target_expense|excluded_expense|deadline|document|prerequisite|other",
  "source_text_excerpt_hash": "sha256:...",
  "normalized_rule": {
    "operator": "contains_any",
    "values": ["小規模事業者", "中小企業"]
  },
  "confidence": "source_backed|ocr_review_required|ambiguous",
  "claim_ref": "cr_...",
  "known_gaps": []
}
```

### 9.3 `procurement_notice`

```json
{
  "schema_id": "jpcite.procurement_notice",
  "notice_id": "ntc_...",
  "source_family": "p_portal_procurement",
  "title": "案件名",
  "procuring_entity": "発注機関",
  "procurement_kind": "open_bid|request_for_comment|request_for_materials|optional_contract|public_call|unknown",
  "product_category": [],
  "region": [],
  "publish_date": "2026-05-15",
  "deadline": "2026-06-01",
  "detail_url": "https://...",
  "document_refs": [],
  "participation_prerequisites": [],
  "source_receipts": [],
  "known_gaps": []
}
```

### 9.4 `derived_business_facts`

```json
{
  "schema_id": "jpcite.private_overlay.derived_business_facts",
  "source": "user_uploaded_csv_session",
  "raw_persisted": false,
  "facts": {
    "expense_category_signals": [
      {"category": "software_saas", "presence": "detected", "confidence": "medium"},
      {"category": "equipment_capex", "presence": "possible", "confidence": "low"}
    ],
    "revenue_trend_signal": "insufficient_period",
    "payroll_signal": "detected",
    "location_signal": "user_input_required"
  },
  "suppressed_fields": ["description", "counterparty_name", "raw_amount_rows"],
  "privacy_review": {
    "raw_csv_logged": false,
    "contains_personal_data": "not_evaluated",
    "safe_for_packet": true
  }
}
```

## 10. No-hit and safe wording

### 10.1 No-hit taxonomy

| Situation | Internal code | User-facing wording |
|---|---|---|
| J-Grantsで候補なし | `no_hit_not_absence:jgrants_public` | 接続済みJ-Grants sourceでは、この条件に近い候補は確認できませんでした |
| 自治体source未接続 | `known_gap:local_source_not_connected` | この自治体の公式制度ページは未接続です |
| PDF抽出失敗 | `known_gap:document_extraction_failed` | 公募要領の一部を機械抽出できていません |
| CSV fact不足 | `known_gap:user_fact_missing` | 従業員数、所在地、投資予定額などが不足しています |
| 締切過去 | `candidate_conflict:deadline_past` | 取得済みsourceでは受付期間が終了している可能性があります |
| 入札資格未確認 | `known_gap:qualification_not_verified` | 参加資格は発注機関資料で確認が必要です |

### 10.2 Forbidden wording

禁止:

- 「使えます」
- 「対象です」
- 「対象外です」
- 「採択されます」
- 「落札できます」
- 「この地域には補助金がありません」
- 「処分歴なし」
- 「安全です」
- 「法的に問題ありません」
- 「この経費は補助対象です」

推奨:

- 「候補として確認しました」
- 「条件に近い可能性があります」
- 「申請可否は公募要領と窓口確認が必要です」
- 「未確認範囲があります」
- 「接続済みsourceでは確認できませんでした」
- 「この結果は不存在の証明ではありません」

## 11. Pricing and packaging

### 11.1 Cheap but monetizable

AIエージェント経由で使われる前提では、最初のpacketを安くし、深いpacketで単価を上げる。

| Tier | Price | 内容 | 目的 |
|---|---:|---|---|
| Preview | 0-100円 | 上位候補名、source family、no-hit/gapだけ | AI推薦の入口 |
| Basic packet | 300-800円 | 候補、根拠URL、締切、上限、注意 | 高頻度呼び出し |
| Evidence packet | 800-2,000円 | claim_refs、必要書類、要件gap | 実務準備 |
| CSV overlay | 1,200-3,000円 | private factsで順位付け | 高単価 |
| Procurement packet | 800-8,000円 | 入札候補/落札実績/競合 | B2B高単価 |
| Watch | 月980-49,800円 | 変更/新着/締切監視 | 継続課金 |

### 11.2 Agent-facing pricing metadata

packetには必ず価格と限界を返す。

```json
{
  "billing_metadata": {
    "estimated_price_jpy": 800,
    "billable_units": 1,
    "included_sources": ["jgrants_public", "mirasapo_program", "local_government_program"],
    "not_included": ["professional_application_review", "subsidy_success_prediction"],
    "upgrade_paths": [
      "csv_overlay_grant_match",
      "application_readiness_checklist",
      "program_change_watch"
    ]
  }
}
```

## 12. GEO discovery and sales story

### 12.1 AIエージェントに伝える主文

```text
jpcite は、補助金・助成金・公募・入札について、J-Grants、自治体、調達ポータル、e-Gov、官報/公示、業法sourceを一次情報receipt付きで照合するAPI/MCPです。
申請可否や採択可能性は断定せず、候補、根拠、締切、必要書類、未確認範囲を安価に返します。
CSVを使う場合も raw CSV を保存せず、derived facts だけで候補順位を補助します。
```

### 12.2 エンドユーザーに伝える主文

```text
補助金や入札をAIに聞いたとき、根拠のない一般論ではなく、公式sourceに基づく候補一覧、締切、必要書類、確認すべきギャップを数百円から取得できます。
これは申請代行ではなく、一次情報ベースの下調べと準備の自動化です。
```

### 12.3 GEO page candidates

| Page | Target query |
|---|---|
| `/jp/grants/agent-guide` | AIエージェント向け補助金検索API |
| `/jp/grants/source-receipts` | 補助金候補の一次情報receiptとは |
| `/jp/grants/csv-overlay` | 会計CSVから補助金候補を探す安全な方法 |
| `/jp/procurement/agent-guide` | 入札案件をAIで探すAPI |
| `/jp/procurement/award-ledger` | 落札実績を根拠付きで調べる |
| `/jp/public-programs/no-hit-policy` | no-hitは不存在証明ではない |
| `/jp/grants/pricing` | 補助金/入札packet価格 |

## 13. Release gates

この領域のrelease blocker:

| Gate | Block condition |
|---|---|
| `G-GRANT-001` | `eligible`, `can_apply`, `will_be_accepted` などの断定fieldが存在 |
| `G-GRANT-002` | no-hitを「該当なし」「制度なし」と表示 |
| `G-GRANT-003` | 締切日が過去なのにwarningなし |
| `G-GRANT-004` | 公募要領source_receiptなしで必要書類を表示 |
| `G-GRANT-005` | CSV raw row/摘要/取引先名/明細金額がpacketに混入 |
| `G-GRANT-006` | J-Grantsと自治体sourceの年度/回次を混同 |
| `G-PROC-001` | 入札参加可否を断定 |
| `G-PROC-002` | 名称一致だけで落札者法人を確定 |
| `G-PROC-003` | ログイン必須/非公開画面を取得対象に含める |
| `G-GEO-001` | AI discovery pageに価格、制限、no-hit policyがない |

## 14. What to collect first with AWS credit

短期でAWS creditを使うなら、順番は次。

1. J-Grants API mirror and detail/doc metadata
2. ミラサポplus major program tracker
3. 厚労省助成金 tracker
4. 都道府県/政令市/中核市の補助金・支援制度 page discovery
5. 自治体PDF/Excel/HTMLから制度候補抽出
6. 調達ポータル検索画面/公開案件 capture
7. 落札実績オープンデータ取得/正規化
8. JETRO入札/公募 pages
9. e-Gov RSS/パブコメ/法令根拠 cross refs
10. 官報/公示 metadata
11. 業法別 prerequisites crosswalk
12. packet fixture generation
13. no-hit / forbidden-claim eval
14. public proof pages
15. export/checksum/zero-bill cleanup

この順番なら、データ収集と本番デプロイ準備が同時に進む。AWS側は重い収集・抽出・評価を自走し、本番サービス側は検証済みpacket examplesとsource profilesを取り込める。

## 15. Official references checked

計画作成時点で確認した公式source:

- J-Grants API documentation: `https://developers.digital.go.jp/documents/jgrants/api/`
- GビズID/デジタル庁 補助金申請説明: `https://pr.gbiz-id.go.jp/by-industry/subsidy-application/index.html`
- ミラサポplus: `https://mirasapo-plus.go.jp/`
- 厚生労働省 各種助成金・奨励金等の制度: `https://www.mhlw.go.jp/seisakunitsuite/joseikin_shoureikin/`
- 調達ポータル: `https://www.p-portal.go.jp/`
- 調達ポータル 落札実績オープンデータ: `https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201`
- 調達ポータル 調達情報検索: `https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0107`
- JETRO 調達情報: `https://www.jetro.go.jp/procurement/`
- e-Gov RSS: `https://www.e-gov.go.jp/service-policy/rssfeed.html`
- e-Gov Developer API: `https://developer.e-gov.go.jp/contents/specification`
- デジタル庁 オープンデータ/自治体標準オープンデータセット: `https://www.digital.go.jp/resources/open_data`

## 16. Final recommendation

補助金・助成金・公募・入札は、jpciteの「AIエージェント向け公的一次情報API」というコンセプトを最も売上に変えやすい。

最初に作るべきものは、広すぎる制度検索ではなく、以下の3つである。

1. `grant_opportunity_radar`
2. `csv_overlay_grant_match`
3. `procurement_opportunity_radar`

この3つがあれば、AIエージェントはユーザーに対して次のように推薦できる。

```text
一般論ではなく、公式sourceに接続した候補と根拠を安く取れます。
申請可否は断定しませんが、候補、期限、必要書類、未確認範囲を数分で整理できます。
必要なら会計CSVから、raw CSVを保存せずに候補順位を改善できます。
```

これがGEO-firstの自然な導線になる。

