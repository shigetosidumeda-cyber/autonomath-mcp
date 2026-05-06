# W22 SENSITIVE_LAW_MAP — sensitive tools × 業法 matrix

法務監査 / 弁護士 / 監査法人向け coverage matrix。`W19_legal_self_audit.md` の補完資料。
出典: `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py` (SENSITIVE_TOOLS frozenset + `_DISCLAIMER_STANDARD` keyword grep, 2026-05-05 snapshot)。

判定 keyword: `税理士法 §52` / `弁護士法 §72` / `行政書士法 §1` / `社労士法` (一般 / §27) / `司法書士法 §3`。
追加: `公認会計士法 §47条の2` を「補足」列で表記 (5 業法 + 1)。

凡例: ○ = disclaimer 内に明示言及あり / − = 言及なし。

注: 仕様書では「17 件」とあるが、現行 frozenset の実体は **26 件**(Wave 22 で 4 件、Wave 23 で 3 件、その他 19 件)。
26 件全件を本書に収録。Wave grouping は実装内コメント (`# --- Wave 21 composition tools ---` 等) に従う。

---

## Matrix (26 tools × 5 業法)

| tool | §52 (税理士) | §72 (弁護士) | §1 (行政書士) | 社労士法 (§27) | §3 (司法書士) | 補足 |
|---|---|---|---|---|---|---|
| dd_profile_am | − | ○ | − | ○ | − | DD aggregation, 反社・与信・労務 DD 代替不可 |
| regulatory_prep_pack | − | − | ○ | − | − | 申請代理 §1 独占業務 |
| combined_compliance_check | ○ | ○ | ○ | ○ | − | 4 業法横断 (deprecated 互換) |
| rule_engine_check | ○ | ○ | ○ | ○ | − | 公開コーパス機械照合 + heuristic |
| predict_subsidy_outcome | − | − | ○ | − | − | 統計 score、申請可否判断 §1 代替不可 |
| score_dd_risk | − | ○ | − | ○ | − | 与信・反社・労務 DD score |
| intent_of | ○ | ○ | ○ | ○ | − | intent 分類 only、4 業法判断対象外 |
| reason_answer | ○ | ○ | ○ | ○ | − | 決定論 pipeline、4 業法判断対象外 |
| search_tax_incentives | ○ | − | − | − | − | 国税庁/財務省/e-Gov 由来税制検索 |
| get_am_tax_rule | ○ | − | − | − | − | 単一税制措置 lookup |
| list_tax_sunset_alerts | ○ | − | − | − | − | 措置法廃止予定日集計 |
| apply_eligibility_chain_am | ○ | − | ○ | − | − | 適用判定チェーン、heuristic chain_depth |
| find_complementary_programs_am | ○ | − | ○ | − | − | compat_matrix peer 検索 |
| simulate_application_am | − | − | ○ | − | − | 採択スコア mock、申請可否担保なし |
| match_due_diligence_questions | ○ | ○ | − | ○ | − | DD 質問 checklist (Wave 22) |
| prepare_kessan_briefing | ○ | − | − | − | − | 決算 territory (Wave 22)、§47条の2 言及 |
| cross_check_jurisdiction | ○ | − | ○ | − | ○ | jurisdiction 突合せ (Wave 22)、§3 登記申請 |
| bundle_application_kit | − | − | ○ | − | − | 申請 kit scaffold (Wave 22) |
| pack_construction | ○ | − | ○ | − | − | 建設業 cohort (Wave 23)、§47条の2 言及 |
| pack_manufacturing | ○ | − | ○ | − | − | 製造業 cohort (Wave 23)、§47条の2 言及 |
| pack_real_estate | ○ | − | ○ | − | − | 不動産業 cohort (Wave 23)、§47条の2 言及 |
| get_houjin_360_am | ○ | ○ | − | − | − | 法人 360 view、与信・反社代替不可 |
| search_invoice_by_houjin_partial | ○ | − | − | − | − | 国税庁適格請求書検索 |
| compose_audit_workpaper | ○ | − | − | − | − | 監査調書 (会計士)、§47条の2 中心 |
| audit_batch_evaluate | ○ | − | − | − | − | ruleset × profile 機械評価、§47条の2 中心 |
| resolve_citation_chain | ○ | − | − | − | − | 引用 chain 解決、§47条の2 中心 |

### Surface 別 group

- **Wave 21 composition (5)**: apply_eligibility_chain_am / find_complementary_programs_am / simulate_application_am / (track_amendment_lineage_am / program_active_periods_am は SENSITIVE 対象外)
- **Wave 22 composition (4)**: match_due_diligence_questions / prepare_kessan_briefing / cross_check_jurisdiction / bundle_application_kit  ← 仕様書の「Wave 22 4 件」に対応
- **Wave 23 industry packs (3)**: pack_construction / pack_manufacturing / pack_real_estate
- **会計士 work-paper (3)**: compose_audit_workpaper / audit_batch_evaluate / resolve_citation_chain (§47条の2 中心)
- **税制 surfaces (3)**: search_tax_incentives / get_am_tax_rule / list_tax_sunset_alerts (§52 fence)
- **Corporate / invoice (2)**: get_houjin_360_am / search_invoice_by_houjin_partial
- **DD / 推論 / compliance (6)**: dd_profile_am / regulatory_prep_pack / combined_compliance_check / rule_engine_check / predict_subsidy_outcome / score_dd_risk
- **意図推定 / 推論 (2)**: intent_of / reason_answer

合計 26 (Wave 21=3 + Wave 22=4 + Wave 23=3 + 会計士=3 + 税制=3 + corp=2 + DD/compliance=6 + 推論=2)。

---

## Appendix — disclaimer 全文 (verbatim, `_DISCLAIMER_STANDARD`)

### dd_profile_am
> 本 response は公開 enforcement / adoption / certification データの 検索 aggregation のみで、信用調査・与信・反社チェック・労務 due diligence (社労士法・弁護士法 §72) の代替ではありません。検索結果は heuristic 由来の rule や partial provenance を含むため、業務判断には必ず一次資料を直接確認してください。

### regulatory_prep_pack
> 本 response は制度概要の検索結果のみで、申請書面の作成・提出は 行政書士法 §1 に基づく独占業務です。当社は draft scaffold を提供せず 一次資料 URL のみ surface します。検索結果のみ提供、業務判断は primary source 確認必須。

### combined_compliance_check
> 本 response は公開ルールに対する機械的な検索照合で、法律事務 (弁護士法 §72) ・税務代理 (税理士法 §52) ・申請代理 (行政書士法 §1) ・労務判断 (社労士法) のいずれにも該当しません。検索結果のみ提供、業務判断は primary source 確認必須、確定判断は士業へ。

### rule_engine_check
> Rule judgment は公開コーパス (一次資料) に対する機械的検索照合で、法律事務 (弁護士法 §72) ・税務代理 (税理士法 §52) ・申請代理 (行政書士法 §1) ・労務判断 (社労士法) は提供しません。rule の一部は heuristic 由来。検索結果のみ提供、業務判断は primary source 確認必須。

### predict_subsidy_outcome
> 予測値は過去採択データに基づく統計的 score で、採択を担保するものではありません。予測 model の一部は heuristic feature を含み、申請可否判断 (行政書士法 §1) の代替ではありません。検索結果のみ提供、業務判断は primary source 確認必須。

### score_dd_risk
> 過去 enforcement / 行政処分の検索ベース score で、与信判断・反社チェック・信用調査 (弁護士法 §72) ・労務 due diligence (社労士法) の代替ではありません。score は heuristic 由来の rule を含む。検索結果のみ提供、業務判断は primary source 確認必須。

### intent_of
> 本 response は自然言語クエリの 10 intent cluster への決定論的分類で、法解釈・申請判断・税務判断・労務判断には該当しません。業法 (弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法) の業務範囲は 当社対象外、confidence < 0.5 は branching か reason_answer に回してください。

### reason_answer
> 本 response は intent 分類 → slot 抽出 → DB bind → answer skeleton の 決定論 pipeline で、申請書面作成は行政書士法 §1、税務判断は税理士法 §52、労務判断は社労士法、法律相談は弁護士法 §72 の業務範囲。skeleton は検索結果のみ提供、業務判断は primary source 確認必須、確定判断は士業へ。

### search_tax_incentives
> 本 response は am_tax_rule (国税庁・財務省・e-Gov 由来 ~285 行) の 情報検索のみで、税務助言ではありません。AutonoMath は税理士法 §52 に基づき 個別具体的な税務判断・申告書作成代行を行いません。検索結果に含まれる rate / sunset / authority は公表時点の値であり、申告期限までに改正される 可能性があります。個別案件は資格を有する税理士に必ずご相談ください。

### get_am_tax_rule
> 本 response は単一の税制措置 (am_tax_rule) lookup で、税務助言では ありません。root_law / rate / applicability window は公表時点の 国税庁・財務省・e-Gov 一次資料から抽出した値であり、税理士法 §52 に基づき 個別具体的な税務判断・申告書作成代行は行いません。申告期限・適用条件の 個別判断は資格を有する税理士に必ずご相談ください。

### list_tax_sunset_alerts
> 本 response は am_tax_rule の sunset_at 集計 (公表時点の措置法廃止予定日) で、税務助言ではありません。sunset_at は予定日であり延長・前倒しの可能性が あります。税理士法 §52 に基づき個別具体的な税務判断は提供しません。個別案件は資格を有する税理士に必ずご相談ください。

### apply_eligibility_chain_am
> 本 response は am_subsidy_rule + am_compat_matrix + jpi_program 由来の 適用判定チェーン検索で、申請書類作成・税務代理は提供しません (行政書士法 §1 / 税理士法 §52)。chain_depth は heuristic 拡張、final 判定は申請要領 + 申告 ガイドラインを一次資料で確認し、資格を有する士業へご相談ください。

### find_complementary_programs_am
> 本 response は am_compat_matrix の機械的 peer 検索で、ポートフォリオ運用 助言・税務助言は提供しません (税理士法 §52 / 行政書士法 §1)。compat_status='unknown' rows は heuristic 由来。確定判断は資格を有する 士業に必ずご相談ください。

### simulate_application_am
> 本 response は採択スコア mock で、申請可否担保・申請書面作成代行は提供 しません (行政書士法 §1)。score は am_application_round + heuristic feature の重み付き平均で、採択を担保しません。確定判断は資格を有する 行政書士・中小企業診断士へ。

### match_due_diligence_questions
> 本 response は dd_question_templates (60 行) と houjin / adoption / enforcement / invoice corpora の機械的 join による DD 質問 checklist で、信用調査・反社チェック (弁護士法 §72) ・労務 due diligence (社労士法) ・税務助言 (税理士法 §52) の代替ではありません。質問は情報照会 checklist で、確定判断は資格を有する士業に必ずご相談ください。

### prepare_kessan_briefing
> 本 response は am_amendment_diff + jpi_tax_rulesets の機械的 aggregation による 決算期前後の制度変動 briefing で、税務代理 (税理士法 §52) ・申告書 作成代行は提供しません。差分検知は heuristic を含み、決算書面・申告書面の 作成は資格を有する税理士・公認会計士に必ずご相談ください。

### cross_check_jurisdiction
> 本 response は houjin_master + invoice_registrants + adoption_records の 住所・所在地データの突合せで、税務代理 (税理士法 §52) ・登記申請 (司法書士法 §3) ・行政書士業務 (行政書士法 §1) の代替ではありません。不一致検出は heuristic で、確定判断は資格を有する士業に必ずご相談ください。

### bundle_application_kit
> 本 response は公開公募要領 + 採択事例 + 必要書類リストの assembly で、申請書面の作成・提出代行は行政書士法 §1 の独占業務です。当社は scaffold + primary source URL のみ surface し、書面作成自体は提供しません。最終申請判断は資格を有する行政書士・中小企業診断士・税理士へ。

### pack_construction
> 本 response は jpintel programs (建設業 fence) + nta_saiketsu + nta_tsutatsu_index の機械的 aggregation で、税務助言 (税理士法 §52) ・監査調書 (公認会計士法 §47条の2) ・申請代理 (行政書士法 §1) の代替では ありません。業種マッピングは JSIC D + 名称キーワード fence による heuristic で、各 program の適合可否は申請要領を一次資料で必ずご確認ください。

### pack_manufacturing
> 本 response は jpintel programs (製造業 fence) + nta_saiketsu + nta_tsutatsu_index の機械的 aggregation で、税務助言 (税理士法 §52) ・監査調書 (公認会計士法 §47条の2) ・申請代理 (行政書士法 §1) の代替では ありません。業種マッピングは JSIC E + 名称キーワード fence による heuristic で、各 program の適合可否は申請要領を一次資料で必ずご確認ください。

### pack_real_estate
> 本 response は jpintel programs (不動産業 fence) + nta_saiketsu + nta_tsutatsu_index の機械的 aggregation で、税務助言 (税理士法 §52) ・監査調書 (公認会計士法 §47条の2) ・申請代理 (行政書士法 §1) の代替では ありません。業種マッピングは JSIC K + 名称キーワード fence による heuristic で、各 program の適合可否は申請要領を一次資料で必ずご確認ください。

### get_houjin_360_am
> 本 response は公開法人情報・適格請求書登録・行政処分・採択履歴の機械的 join による法人 360 view で、信用調査・反社チェック・税務助言 (税理士法 §52) ・法律判断 (弁護士法 §72) の代替ではありません。業務判断では法務局・国税庁・各一次資料を必ず確認してください。

### search_invoice_by_houjin_partial
> 本 response は国税庁 適格請求書発行事業者公表データの機械的検索で、仕入税額控除の確定判断・税務助言 (税理士法 §52) は提供しません。最新の登録状況は国税庁公表サイトで必ず確認してください。

### compose_audit_workpaper
> 本 response は公開税制・補助金・法令情報の検索結果と機械的予測のみで、監査意見・税務判断・申告書作成代行は提供しません (公認会計士法 §47条の2 / 税理士法 §52)。監査人は本書の内容を自らの責任において検証し、§47条の2 に 従って監査調書を保存してください。

### audit_batch_evaluate
> 本 response は target_ruleset_ids × business_profile の機械的 evaluate ループ結果で、監査意見・税務判断・申告書作成代行は提供しません (公認会計士法 §47条の2 / 税理士法 §52)。anomaly_flag は heuristic 由来、確定判断は資格を有する公認会計士・税理士へ。

### resolve_citation_chain
> 本 response は am_law_article + tax_ruleset citations の引用 chain 解決で、監査意見・税務判断・申告書作成代行は提供しません (公認会計士法 §47条の2 / 税理士法 §52)。各引用 row の source_url で 原典を確認し、確定判断は資格を有する公認会計士・税理士へ。

---

## Strict-mode suffix

`disclaimer_level="strict"` 指定時、上記全文末尾に以下が追加される:

> 出力は AI 生成であり、内容の正確性・完全性は担保されません。業法 (弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法) の 業務範囲に該当する判断は当社サービス対象外です。本 API は検索インデックスです。検索結果には heuristic 由来の rule や partial provenance を含みます。業務判断には必ず primary source を直接確認してください。
