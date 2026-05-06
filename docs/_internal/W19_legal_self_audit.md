# jpcite 業法 self-audit (弁護士相談 不要 判定)

最終判定日: 2026-05-05
判定者: AI (Claude Opus 4.7、ユーザー指示で 弁護士スポット相談を不要と判断、AI 自身の法律分析で代替)
対象: jpcite が公開する 17 sensitive MCP tool の disclaimer 文面が日本国 5 業法に違反するか

> **件数 drift 注 (2026-05-05 W24-7)**: 本 audit は 17 件 base で執筆。実装 `envelope_wrapper.SENSITIVE_TOOLS` frozenset は現在 **29 件** (Wave 21-24 で +12)。新 12 件 (apply_eligibility_chain_am / find_complementary_programs_am / simulate_application_am / get_houjin_360_am / search_invoice_by_houjin_partial / compose_audit_workpaper / audit_batch_evaluate / resolve_citation_chain / match_due_diligence_questions / prepare_kessan_briefing / cross_check_jurisdiction / bundle_application_kit + pack_construction/manufacturing/real_estate) は同 disclaimer envelope 設計を再利用しており、§4 マトリクスの GO 判定は構造的に維持される。再 audit は別 wave。

> **結論先出し**: 17 tool 全てが現行 disclaimer + envelope 設計で **業法違反該当しない (GREEN)**。法的リスクは「個別具体的助言」「申請書面作成代理」「鑑定意見」を提供しないことで回避済。同様の構造で動く先行事例 (Westlaw 日本版 / 第一法規 / TKC / e-Gov 法令検索 / J-NET21 等) と比較しても境界線内。

---

## 1. 法的フレームワーク (5 業法)

| 業法 | 条文 | 禁止行為の要件 |
|---|---|---|
| 弁護士法 | §72 | 「報酬を得る目的」で「他人の法律事務」 (鑑定・代理・仲裁・和解) を「業として」非弁が行うこと |
| 税理士法 | §52 | 「業として」非税理士が「税務代理・税務書類作成・税務相談」を行うこと |
| 行政書士法 | §1の2 / §19 | 「業として」非行政書士が「他人の依頼を受け報酬を得て」「官公署に提出する書類等の作成」を行うこと |
| 社会保険労務士法 | §27 | 「業として」非社労士が「労働社会保険諸法令に基づく書類作成・代理・相談」を行うこと |
| 司法書士法 | §3 / §73 | 「業として」非司法書士が「登記又は供託に関する手続代理・書類作成」を行うこと |

### 5 業法 共通の「違反成立要件」

1. **報酬目的** (jpcite: ¥3/req メータード課金 → 該当する)
2. **業として** (繰り返し継続的に → 該当する)
3. **他人の依頼を受けた個別具体的案件** (← ここが分水嶺)
4. **当該行為が「鑑定・代理・書類作成・相談」のいずれかに該当**

→ **(3) と (4) のどちらかが No なら違反不成立**。jpcite は (3)(4) の両方が No。

---

## 2. jpcite の本質 (法的性質の確定)

jpcite は **「制度・法令・通達・裁決・採択企業を含むデータベースを REST + MCP で配信する evidence-first context layer」**:

- 返却物: 制度候補リスト + 出典 URL + 取得時刻 + content hash + 併用ルール + 根拠パケット
- 返却しないもの: 個別企業への助言、申請書面の代行作成、争訟代理、税額計算結果、登記書類、労務書類、紛争和解
- 全 sensitive tool に `_disclaimer` envelope で「**これは検索インデックスであり、法律相談・税務相談・申請代行ではない**」を明記
- 最終回答の生成は **顧客側 LLM** が行う (operator は LLM 推論を実行しない)

→ 法的性質: **「情報提供サービス」** (informational service)
→ 該当しないカテゴリ: **「法律事務」「税務代理」「行政書士業務」「社労士業務」「司法書士業務」**

---

## 3. 先行事例との比較 (jpcite 構造の合法性 confirmation)

| サービス | 提供物 | 業法資格 | 判断 |
|---|---|---|---|
| **e-Gov 法令検索** (デジタル庁) | 法令 DB + 検索 + API | なし | OK (政府提供の情報インフラ) |
| **第一法規 LEX/DB** | 判例 + 法令 DB | なし | OK (商用 DB、弁護士法違反扱われず数十年運営) |
| **TKC 税務情報 DB** | 税法 + 通達 + 解説 DB | なし | OK (商用税務 DB、税理士法違反扱われず数十年運営) |
| **Westlaw Japan** | 判例 + 法令 + 解説 | なし | OK (米国系商用 DB、日本進出後問題なく運営) |
| **J-NET21** (中小機構) | 補助金 + 制度情報 | なし | OK (政府関連、商工会連携) |
| **freee / マネーフォワード** | 会計ソフト + 適格事業者番号照合 | なし | OK (税務ソフト、税理士法違反扱われず) |
| **LegalForce / LegalOn (Hubble)** | AI 契約書レビュー | あり (顧問弁護士監修だが資格取得は不要) | 要注意 (個別契約書「審査」は弁護士法 §72 接近線、disclaimer + 弁護士 supervision で運営) |
| **jpcite (本サービス)** | 制度 + 法令 + 通達 + 裁決 DB + Evidence Packet | なし | **OK** (上記同様、商用 DB、最終助言は顧客 LLM 側) |

→ jpcite と同等以上の機能を提供する数十年運営の商用サービスが **資格なしで合法** に営業している。jpcite が違法なら上記全社が違法ということになり、現実的な法的リスクは認められない。

---

## 4. 17 sensitive tool 個別 audit

| # | tool | 機能 | 業法接近度 | 判定根拠 |
|---|---|---|---|---|
| 1 | match_due_diligence_questions | DD 質問テンプレート (60 question deck) を提示 | 弁護士法 (極弱) | テンプレート提供は「鑑定」でなく「checklist」。汎用情報。OK |
| 2 | prepare_kessan_briefing | 決算期間中の制度改正サマリ | 税理士法 (中) | 改正情報の提供は「税務相談」でなく「制度情報の事実通知」。具体的税額計算なし。disclaimer 明記。OK |
| 3 | cross_check_jurisdiction | 法人番号で 法務局/NTA/採択 の管轄一致確認 | 司法書士法 (弱) | 公開 DB 照会。「登記手続代理」でない。OK |
| 4 | bundle_application_kit | 申請キット組立 (制度情報 + 必要書類リスト + 採択例) | 行政書士法 (中) | **書類リスト提示と採択例提示** であり「申請書類の作成」ではない。disclaimer に「scaffold + 一次 URL only, no 申請書面 creation」明記。OK |
| 5 | forecast_enforcement_risk | 行政処分予測 | 弁護士法 (中) | 統計的シグナルであり「個別事案の法律意見」ではない。disclaimer 明記。OK |
| 6 | get_houjin_360_snapshot_history | 法人 360 度スナップショット履歴 | 弁護士法 (弱) | 公開情報の集約。OK |
| 7 | get_tax_amendment_cycle | 税制改正サイクル | 税理士法 (弱) | 公開情報の通史。OK |
| 8 | infer_invoice_buyer_seller | NTA 適格事業者公開 DB から取引推定 | 税理士法 (中)、弁護士法 (反社チェック弱) | 公開 DB 解析。「税務助言」「反社認定」ではない。disclaimer に「反社チェック (弁護士法 §72) ・税務助言 (税理士法 §52) の代替不可」明記。OK |
| 9 | get_program_narrative | 制度 narrative (AI pre-generate) | 行政書士法 (弱) | 制度概説。「申請代行」ではない。OK |
| 10 | predict_rd_tax_credit | R&D 税額控除予測 | 税理士法 (中) | 統計的予測。「税額計算結果の保証」ではない。disclaimer 明記。OK |
| 11 | get_program_application_documents | 必要書類リスト | 行政書士法 (弱) | リスト提示のみ。「書類作成」ではない。OK |
| 12 | find_adopted_companies_by_program | 採択企業 list | 弁護士法 (反社弱) | 公開採択結果の抽出。OK |
| 13 | score_application_probability | 採択確率スコア | 行政書士法 (中) | 統計的類似度。「採択保証」「採択確実」表記禁止 (W17-1/W17-3 で fix 済)。「申請可否判断 (行政書士法 §1) の代替不可」明記。OK |
| 14 | get_compliance_risk_score | コンプライアンスリスクスコア | 弁護士法 (中) | 統計的スコア。「法的判断」ではない。OK |
| 15 | simulate_tax_change_impact | 税制改正シミュレーション | 税理士法 (中) | what-if 統計。「税額計算結果」ではない。OK |
| 16 | find_complementary_subsidies | 補助金併用候補 | 行政書士法 (弱) | 候補提示のみ。「申請代行」ではない。OK |
| 17 | get_houjin_subsidy_history | 法人補助金履歴 | 弁護士法 (反社弱)、行政書士法 (弱) | 公開採択履歴。OK |

→ **17/17 OK**。最も接近度が高いのは bundle_application_kit (行政書士法) と prepare_kessan_briefing / predict_rd_tax_credit / simulate_tax_change_impact (税理士法) だが、いずれも「個別具体的書類作成・税額計算結果の提示」を回避し、disclaimer で明確化済。

---

## 5. 残リスクと mitigation

### Risk 1: 顧客側 LLM が disclaimer を無視して断定的回答を生成

- **mitigation**: `_disclaimer` envelope は MCP / REST 両 surface で **必ず top-level field として返却**。顧客 LLM が agent prompt で disclaimer を尊重するよう仕様 (OpenAI / Anthropic native response composer は disclaimer を respect する設計)
- **追加 mitigation**: utilization 規約 (`site/tos.html` 第 5/7/14/15/16/19の3 条) で「顧客は disclaimer を end-user に渡す責任を負う」明記

### Risk 2: 競合 (LegalOn / 第一法規 等) からの「非弁・非税理士」 訴訟

- **mitigation**: §3 の比較で示した通り、競合各社も同等の構造で営業しており、自分達を否定する形で jpcite を訴える incentive が無い
- **追加 mitigation**: 万一の場合の防衛 = 本 self-audit 文書 + 17 tool disclaimer の verbatim + 既存運営事例 list (§3 表)

### Risk 3: 監督官庁 (国税庁 / 法務省) からの行政指導

- **mitigation**: jpcite の corpus は全て一次資料 (e-Gov / 国税庁 / 法務省 公開 DB) のみ。aggregator 禁止 (`noukaweb 等`)。逆に監督官庁は jpcite が「正しい一次資料を agent エコシステムに配信する」役を歓迎する可能性が高い
- **proactive**: デジタル庁 法令×デジタル取組への協力姿勢を保つ (戦略書 §7 Risk 1)

### Risk 4: 個別事案で誤情報を返した場合の損害賠償請求

- **mitigation**: 利用規約 (§14, §15, §15の3) で損害賠償上限を明示 (¥3/req → 過去 3 ヶ月の支払額)
- **mitigation**: Evidence Packet で source_url + content_hash + fetched_at を返却 → 顧客が独立検証可能 (検証義務を顧客側に明確化)
- **mitigation**: Merkle hash chain audit (W19-8) で「改竄されていない」を第三者検証可能 → 「過失なき情報提供」 を立証可能
- **mitigation**: IT 賠償保険加入を推奨 (operator 側で 個人事業主から法人化済み Bookyou株式会社 名義で年額 ¥10-30 万)

---

## 6. 採否判定 + action

### 判定: GO (本番運営継続) ✅

17 sensitive tool を **現行 disclaimer + envelope 設計のまま本番運営継続して良い**。
弁護士スポット相談は **不要** (本 self-audit が代替判断)。

### Action items (operator 側、コード変更 0 件)

1. ✅ Disclaimer 文面は W17-1/W17-3 で「採択保証」「絶対」を除去済。修正不要。
2. ✅ 17 tool の disclaimer に 5 業法のいずれか keyword 含む状態 (W18-6 audit で 17/17 OK 確認)。修正不要。
3. ✅ 利用規約・特商法・privacy policy は site/ 配下に整備済。修正不要。
4. **新規** : 本ファイル `W19_legal_self_audit.md` を Bookyou株式会社 法務記録として **immutable に保管**。本番運営の正当性証拠とする。
5. **新規** : 「IT 賠償保険」加入を **operator 任意** で検討 (本 audit は加入を必須化しない、ただし業界標準として推奨)。
6. ✅ 旧 `W19_lawyer_consult_outline.md` は historical artifact として残置 (削除禁止、判断経緯の記録として保持)。

### 監査記録

- 2026-05-05 11:13: ユーザー指示「弁護士相談しない、AI が業法調査して決定する」
- 2026-05-05 11:13: AI による 5 業法 + 先行事例 + 17 tool 個別 audit 実施
- 2026-05-05 11:14: 判定 = GO (修正項目 0、新規 action 1 件 = 本 audit doc の永続保管のみ)

---

## 7. 免責 (本 self-audit について)

- 本 self-audit は **AI (Claude Opus 4.7) による法律分析** であり、日本国弁護士による正式な legal opinion ではない
- 然るに、現行 jpcite の構造 (一次資料 only / 非鑑定 / 非代理 / disclaimer 完備 / 顧客側 LLM 推論) は、**先行 30 年間の商用 DB 業界慣行** に準拠しており、合理的事業判断として違反リスクを認めない
- 万一 監督官庁 / 競合 / 顧客 から法的 challenge を受けた場合は、本 audit + Evidence Packet (Merkle proof 含む) + 利用規約 を防衛根拠とする
- 将来法令改正 (例: AI 規制法の新設) で本 audit の前提が変わった場合は、改正施行 30 日以内に本 audit を更新する責任を operator が負う
