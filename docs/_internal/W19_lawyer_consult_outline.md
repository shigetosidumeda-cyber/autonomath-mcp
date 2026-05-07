# W19 弁護士スポット相談 outline (jpcite §L1 sensitive 17 件)

2026-05-05 / Bookyou株式会社 (T8010001213708) 代表 梅田茂利 / info@bookyou.net
想定費用 ¥30K-80K spot 1回 / email 回答可 / 30 分読込前提 (本書 3,000字以内)

## 1. 案件概要 (300字)

jpcite は日本国の公的制度 (補助金・融資・税制・認定・行政処分等) のメタデータを REST API + MCP server で配信する evidence-first context layer。Bookyou株式会社単独運営、¥3/billable unit 完全従量。返り値は「制度候補・出典 URL・取得時刻・content hash・併用ルール・根拠パケット」のみで、自然言語回答生成は顧客側 LLM。当社は法律・税務・労務助言を一切提供せず、検索インデックスとして機能する。

## 2. ご相談したい 1 点 (yes/no)

> **§3 の 17 sensitive tool の `_disclaimer` を毎 response に自動添付し、利用規約 §5 (§4) で士業独占業務を全面否認している前提で、本サービスの API/MCP 提供が、弁護士法 §72 / 税理士法 §52 / 行政書士法 §1 / 社労士法 §27 / 司法書士法 §3 のいずれかに該当する非有資格者業務とみなされ、提供を中止すべき水準にあるか?**

`yes (中止すべき)` / `no (現状文面で運用継続可)` / `条件付き no (修正点 X)` でご回答ください。

## 3. 17 sensitive tool disclaimer 文面 (実物)

抽出元: `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py` `SENSITIVE_TOOLS` 中 §L1 弁護士 review band = Wave22 4件 + Wave24 13件 = 17件。

### Wave22 (4)

1. **`bundle_application_kit`**: 本 response は公開公募要領 + 採択事例 + 必要書類リストの assembly で、申請書面の作成・提出代行は行政書士法 §1 の独占業務です。当社は scaffold + primary source URL のみ surface し、書面作成自体は提供しません。最終申請判断は資格を有する行政書士・中小企業診断士・税理士へ。
2. **`cross_check_jurisdiction`**: 本 response は houjin_master + invoice_registrants + adoption_records の住所・所在地データの突合せで、税務代理 (税理士法 §52) ・登記申請 (司法書士法 §3) ・行政書士業務 (行政書士法 §1) の代替ではありません。不一致検出は heuristic で、確定判断は資格を有する士業に必ずご相談ください。
3. **`prepare_kessan_briefing`**: 本 response は am_amendment_diff + jpi_tax_rulesets の機械的 aggregation による 決算期前後の制度変動 briefing で、税務代理 (税理士法 §52) ・申告書作成代行は提供しません。差分検知は heuristic を含み、決算書面・申告書面の作成は資格を有する税理士・公認会計士に必ずご相談ください。
4. **`match_due_diligence_questions`**: 本 response は dd_question_templates (60行) と houjin / adoption / enforcement / invoice corpora の機械的 join による DD 質問 checklist で、信用調査・反社チェック (弁護士法 §72) ・労務 due diligence (社労士法) ・税務助言 (税理士法 §52) の代替ではありません。質問は情報照会 checklist で、確定判断は資格を有する士業に必ずご相談ください。

### Wave24 (13)

5. **`forecast_enforcement_risk`**: 本 response は過去 enforcement 事例の統計的予測で、法律事務 (弁護士法 §72) ・労務判断 (社労士法 §27) ・与信判断・信用調査の代替ではありません。予測 score は heuristic feature を含み、個別事案の判断には必ず資格を有する弁護士・社労士にご相談ください。
6. **`get_houjin_360_snapshot_history`**: 本 response は法人 360 view の時系列 snapshot で、信用情報の提供 (信用情報法) ・個人情報の第三者提供 (個人情報保護法 §27) ・反社チェック (弁護士法 §72) ・税務助言 (税理士法 §52) には該当しません。snapshot は公表時点の値で改正・取消の可能性があり、与信判断・反社チェックの代替ではありません。最新は一次資料でご確認ください。
7. **`get_tax_amendment_cycle`**: 本 response は am_amendment_snapshot 由来の税制改正サイクル分析で、税務助言ではありません。当社は税理士法 §52 に基づき個別具体的な税務判断・申告書作成代行を行いません。改正サイクルは過去実績に基づく傾向分析で将来の改正を担保しません。個別判断は資格を有する税理士へ。
8. **`infer_invoice_buyer_seller`**: 本 response は適格請求書登録データから取引関係を推定する機械的 join で、信用情報の提供 (信用情報法) ・個人情報の目的外利用 (個人情報保護法 §17/§21) ・反社チェック (弁護士法 §72) ・税務助言 (税理士法 §52) には該当しません。推定結果は heuristic で、実際の取引関係を担保しません。与信判断には一次資料を必ずご確認ください。
9. **`get_program_narrative`**: 本 response は LLM 由来の制度概要 narrative で、原文の正確性を担保しません (LLM 生成テキスト)。申請書面の作成・提出は行政書士法 §1 に基づく独占業務であり、当社は narrative + 一次 URL のみ surface し申請書面は作成しません。最終判断は資格を有する行政書士へ。
10. **`predict_rd_tax_credit`**: 本 response は研究開発税制 (措置法 §42-4) の試算で、税務助言ではありません。当社は税理士法 §52 に基づき個別具体的な税務判断・申告書作成代行を行いません。試算 model は heuristic feature を含み、実際の控除額は事業計画書・試験研究費の認定に依存します。個別判断は税理士へ。
11. **`get_program_application_documents`**: 本 response は公募要領 + 必要書類リストの assembly で、申請書面の作成・提出は行政書士法 §1 に基づく独占業務です。当社は document リスト + 一次 URL のみ surface し書面作成自体は提供しません。最終申請判断は資格を有する行政書士・中小企業診断士へ。
12. **`find_adopted_companies_by_program`**: 本 response は採択企業の機械的検索で、個人情報の目的外利用 (個人情報保護法 §17/§21) ・信用情報の提供 (信用情報法) ・反社チェック (弁護士法 §72) ・申請代理 (行政書士法 §1) には該当しません。公表採択者リスト由来の機械的検索のみで、与信判断・反社チェックの代替ではありません。本データを評価・営業に使用する際は本人同意を確認してください。
13. **`score_application_probability`**: 本 score は am_recommended_programs + am_capital_band_program_match + am_program_adoption_stats の統計的類似度であり、採択確率の予測ではありません。実際の採否は事業計画書の質・審査委員評価に依存します。本 score を「採択確実」「採択率予測」として広告・営業に使用することは景表法違反のリスクがあります。申請可否判断 (行政書士法 §1) の代替ではなく、当社は本 score の利用に起因する損害について責任を負いません。
14. **`get_compliance_risk_score`**: 本 score は公開 enforcement / 行政処分データの機械的検索 score で、信用情報の提供 (信用情報法) ・法律事務 (弁護士法 §72) ・名誉毀損に該当する評価語 (悪質・重大 等) は redact しています。score は heuristic 由来で、与信判断・反社チェックの代替ではありません。業務判断には一次資料の確認と資格を有する弁護士へのご相談が必須です。
15. **`simulate_tax_change_impact`**: 本 response は税制改正前後の制度適用変化の試算で、税務助言ではありません。当社は税理士法 §52 に基づき個別具体的な税務判断・申告書作成代行を行いません。試算は am_amendment_diff + jpi_tax_rulesets 由来の機械的計算で、実際の影響額は会計処理・他制度との併用関係に依存します。個別判断は資格を有する税理士に必ずご相談ください。
16. **`find_complementary_subsidies`**: 本 response は am_compat_matrix の機械的 peer 検索による補助金併用候補で、申請書面作成・申請代理は行政書士法 §1 の独占業務です。compat_status='unknown' rows は heuristic 由来で、併用可否の確定判断は申請要領を一次資料で必ずご確認ください。最終判断は行政書士へ。
17. **`get_houjin_subsidy_history`**: 本 response は法人別の補助金交付履歴で、個人情報の目的外利用 (個人情報保護法 §17/§21) ・信用情報の提供 (信用情報法) ・反社チェック (弁護士法 §72) ・申請代理 (行政書士法 §1) には該当しません。公表交付決定リスト由来の機械的検索のみで、与信判断・信用調査の代替ではありません。本データを評価・営業に使用する際は本人同意を確認してください。

## 4. 利用規約・特商法 関連条項

- **利用規約 `https://jpcite.com/tos.html`**: 第5条 (士業業法遵守 — 弁護士法 §72・税理士法 §52・公認会計士法 §47条の2・社労士法 §27・行政書士法 §1の2 全面否認) / 第7条+7条の2 (情報の正確性否認・外部 AI 出力特別条項) / 第14条+14条の2 (免責) / 第15条 (責任制限) / 第16条 (消費者契約法) / 第19条の3 (audit_seal は §41/§47条の2 代替ではない)
- **特商法 `https://jpcite.com/tokushoho.html`**: 事業者名・所在地・適格請求書番号 T8010001213708 / ¥3/billable unit 税込 ¥3.30 / 通信販売 (特商法 §15の3 によりクーリングオフ適用除外)

## 5. サービスの本質 (免責の根拠)

返り値構成要素のみ:
- 制度候補リスト (PK + 名称)
- 出典 URL (経産省・国税庁・e-Gov 法令・JFC・各都道府県等の一次資料)
- 取得時刻 (`source_fetched_at`) + content hash (改ざん検知)
- 併用ルール (`am_compat_matrix` 機械的 peer 検索)
- 根拠パケット (法令条文・公募要領・採択事例の引用 chain)

**自然言語回答生成・個別事案当てはめ・申告書面/申請書面作成は全て顧客側 LLM または顧客側士業が実施。** 当社サーバ内 LLM 推論は原則なし (`get_program_narrative` のみ事前生成テキスト cache 配信、disclaimer 明示)。

## 6. 費用・連絡先

- **費用**: ¥30,000-80,000 (1 回 spot) / 銀行振込 / 適格請求書 T8010001213708
- **形式**: email 回答のみで可、面談不要
- **回答期限**: 2026年5月中 (本番ローンチ 2026-05-06 前後の運用継続判定)
- **連絡先**: info@bookyou.net (Bookyou株式会社 代表 梅田茂利)
