# Landing Page 景表法 Disclaimer Blocks

**対象**: autonomath.ai (本番 landing page / 各 product page)
**規制対象法**: 不当景品類及び不当表示防止法 (景品表示法、景表法)、消費者契約法
**最終改訂日**: 2026-04-24
**事業者**: Bookyou株式会社 (T8010001213708)

---

## 0. 使い方

この文書は、autonomath.ai 本番 site で **そのまま再利用できる reusable block** を集めたものです。各 section の HTML / Markdown をコピーして landing page / docs に配置してください。

**重要**: landing page 公開前に、本文書の `blocks/` セクションを全 page に反映することを推奨します。

---

## 1. 景表法 NG 表現集 (絶対に使わない)

以下は本 site / docs / API response / marketing email 等で**一切使用しません**。

### 1.1 断定表現 (優良誤認のリスク)

| NG 表現 | 理由 |
|---|---|
| 「必ず受給できる」 | 受給可否は審査結果次第、断定不可 |
| 「100% 採択される」 | 採択率は制度ごと異なり、100% は虚偽 |
| 「絶対に通る」 | 審査は個別判断、断定不可 |
| 「確実に採択」 | 確実性は保証できない |
| 「申請すれば誰でも」 | 要件 mismatch で不採択の可能性 |
| 「〇〇万円が必ず入る」 | 交付決定前の金額は確定しない |
| 「国が保証」 | 当社は国とは無関係 |
| 「AI が審査を通す」 | 審査権限は所管機関、AI は申請補助に過ぎない |

### 1.2 比較優位の誇張 (優良誤認 / 有利誤認のリスク)

| NG 表現 | 理由 |
|---|---|
| 「日本最大の補助金 DB」 | 客観的比較根拠なしでは景表法違反 |
| 「業界 No.1」 | 出典・調査主体が必須 |
| 「唯一の〇〇」 | 反証が一つでもあれば虚偽 |
| 「他社より 10 倍速い」 | 測定条件の明示なしでは不可 |
| 「最も正確な制度情報」 | 客観指標が必要 |

### 1.3 誘引性の強い表現 (消費者契約法上のリスク)

| NG 表現 | 理由 |
|---|---|
| 「今すぐ申込まないと損」 | 不退去・煽動 |
| 「限定〇〇名」 | 実際に限定されていない場合、景表法違反 |
| 「今だけ無料」 | 実質恒久無料の場合は虚偽 |

### 1.4 推奨表現 (OK)

以下の表現は、事実に基づく限り使用可能です:

- 「補助金の **一次資料へのリンク** を提供します」
- 「制度 metadata を **canonical 形式で** 整理しています」
- 「受給可否の判断は **各制度の所管窓口にご確認ください**」
- 「採択事例として〇件の交付決定が **公開情報** に基づき整理されています」
- 「**2026 年 4 月時点** で DB に収録されている制度は N 件です」(調査時点の明示)

---

## 2. Reusable Blocks (コピペ用)

### Block A: hero section 直下の disclaimer (全 page 必須)

```markdown
> AutonoMath は、日本の補助金・助成金・融資制度等に関する **一次資料へのリンクおよび canonical metadata** を提供するデータサービスです。受給可否・申請可否の最終判断は、各制度の所管窓口 (地方農政局、自治体担当課、公庫支店等) にご確認ください。当社は受給を保証するものではありません。
```

### Block B: API response 再利用時の disclaimer (docs / example に配置)

```markdown
**お客様への依頼**: AutonoMath の response を自社 app / 顧客提案 / report 等で再利用する際は、以下の disclaimer を末尾に付与することを強く推奨します。

> 本情報は AutonoMath DB (https://autonomath.ai) に基づく参考情報です。制度内容は頻繁に改訂されるため、最新の受給要件・申請締切は各制度の所管窓口にご確認ください。受給可否は審査結果次第であり、本情報は受給を保証するものではありません。
```

### Block C: pricing page の disclaimer

```markdown
> 表示価格は日本国内利用者向け (消費税 10% 込) です。決済は Stripe Japan 経由。当社は PCI-DSS 対象外であり、カード情報は保持しません。

> 本サービスの利用料金は、補助金・助成金の **検索・参照サービス** への対価であり、受給額に対する成功報酬ではありません。申請代行・受給保証は提供していません。
```

### Block D: footer 全 page 共通

```markdown
---

**AutonoMath** is operated by Bookyou株式会社 (法人番号: T8010001213708)
〒112-0006 東京都文京区小日向2-22-1
Email: info@bookyou.net

[Privacy Policy](/compliance/privacy_policy) | [Terms of Service](/compliance/terms_of_service) | [Data Governance](/compliance/data_governance) | [特定商取引法に基づく表示](/compliance/tokushoho)
```

### Block E: 「この制度が使える」系 claim を避ける文案 (example page)

NG:

```
✗ 「新規就農者のあなたには、この補助金が使えます」
✗ 「300 万円の受給が可能です」
✗ 「今すぐ申請して 500 万円 ゲット」
```

OK:

```
○ 「新規就農者向けの制度として、以下の一次資料があります」
○ 「公表されている交付上限は 300 万円です (出典: 〇〇省 YYYY 年度)」
○ 「申請可否は所管窓口の〇〇課 (連絡先: XXX) にご確認ください」
```

### Block F: 事例紹介 (case study) の注意

```markdown
> 当 page の事例は **公開情報** (交付決定公表資料、プレスリリース等) に基づきます。個別事業者の機密情報は含まれていません。事例の再現性を保証するものではなく、同じ要件の申請者が必ず同じ結果を得られるものではありません。
```

### Block G: 「数字を出すなら出典を明示」

| 表現 | 要件 |
|---|---|
| 「DB には N 件の制度を収録」 | 調査時点・集計方法を併記 |
| 「〇〇制度の採択率は 60%」 | 出典 (省庁公表資料) の URL |
| 「平均交付額は 300 万円」 | 集計期間・母集団 (N) の明示 |

**例**:

```markdown
> 2026 年 4 月 25 日時点で、AutonoMath DB には **13,578 件** の制度 (補助金 / 融資 / 税制 / 認定、tier S/A/B/C、excluded=0) が canonical 形式で収録されています (出典: 当社 DB の `programs` テーブル)。
```

---

## 3. 各 page 別 checklist

### 3.1 Top page (autonomath.ai)

- [ ] Block A (hero 直下 disclaimer) 配置
- [ ] 「必ず」「100%」「絶対」 等の NG 表現 grep = 0 件
- [ ] Block D (footer) 配置
- [ ] 登録 CTA 周辺に Block E の範囲内文案のみ

### 3.2 Pricing page

- [ ] Block C (pricing disclaimer) 配置
- [ ] 消費税込み価格の明示 (¥3.30/req)
- [ ] 「無料」表記には「月 50 req まで」の条件明記
- [ ] Block D (footer) 配置

### 3.3 Docs / API reference

- [ ] Block B (response 再利用 disclaimer) 配置
- [ ] example response 末尾にも disclaimer 注記
- [ ] Block D (footer) 配置

### 3.4 Case study / marketing blog

- [ ] Block F (事例紹介 disclaimer) 配置
- [ ] 全数値に Block G の出典明示
- [ ] 固有事業者の特定可能情報 (名称・住所等) は許諾書面保管
- [ ] Block D (footer) 配置

---

## 4. 実装時の自動 check 推奨

本番 site deploy pipeline に以下の grep check を組み込むことを推奨します (CI で fail させる):

```bash
# NG 表現 grep (本番 deploy ブロック条件)
grep -rE "(必ず受給|100%採択|絶対に通る|確実に採択|絶対通る)" public/ && exit 1
grep -rE "(日本最大|業界No\.?1|唯一の)" public/ && exit 1
```

---

## 5. 参考法令・ガイドライン

- 不当景品類及び不当表示防止法 (景品表示法)
- 消費者庁「景品表示法における違反事例集」
- 消費者契約法
- 特定商取引法 (詳細は `terms_of_service.md` および特商法表示ページ)

---

## 6. 更新履歴

- 2026-04-24: 初版策定

**Bookyou株式会社** (T8010001213708) / `info@bookyou.net`
