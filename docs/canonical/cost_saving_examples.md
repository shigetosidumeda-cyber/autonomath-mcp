# jpcite Cost Saving Examples (per audience)

**Status**: canonical SOT (Wave 46 tick#4)
**Last updated**: 2026-05-12
**Brand**: jpcite (Bookyou株式会社)
**Pricing model**: ¥3/billable unit 完全従量、anonymous 3 req/日 free per IP

## Background — why "cost saving" not ROI/ARR

旧来の audience page は ROI / ARR / 年¥X / 年商 等の SaaS 系 metric を多用していた。 これは
- (1) AutoNoMath 系の SaaS 月額モデル時代の名残で、本来 jpcite は per-request 従量 ¥3 のみ
- (2) ROI 計算には「顧客の機会損失」を絡める必要があり、業種別の前提が透明性を欠く
- (3) ARR / 年¥ は AI agent 時代の per-call 経済性とは合わない

→ Wave 46 tick#3 で `cpa_firm` / `shindanshi` / `ma_advisor` の 3 page を「per-case cost saving table (純 LLM vs jpcite ¥3/req)」に置換済。 本 doc は残 14 page で利用する **業種別 persona × realistic frequency × 純 LLM vs jpcite ¥3/req** の cost saving 試算を canonical 化する。

## Method — per-case cost saving 算出式

```
case_cost_saving = LLM_only_manual_cost − jpcite_request_cost
LLM_only_manual_cost = manual_hours × hourly_rate (¥10,000/h 標準)
jpcite_request_cost = num_requests × ¥3
```

- `manual_hours`: 純粋に AI を補助無しで使い、 hallucination 裏取り + 一次 URL 手動探索 + 法令引用整形まで含めた工数
- `hourly_rate`: 業種別標準 (士業 ¥10,000/h、 金融機関職員 ¥6,000/h、 建設業コンサル ¥8,000/h、 中央会 ¥5,000/h 等)
- `num_requests`: jpcite MCP / REST 経由の 1 case あたり典型 request 数 (1-6 程度)

## 14 page 業種別 cost saving 表

| audience | persona | case | manual cost (純 LLM) | jpcite cost | per-case saving |
|---|---|---|---|---|---|
| **admin-scrivener** | 行政書士 / 事務所 5 案件/月 | 許認可 案件 1 件 prep | 3.5h × ¥10,000 = ¥35,000 | 1.5 req × ¥3 = ¥4.5 | **¥34,995** |
| **construction** | 建設業特化コンサル / 顧問 10 社 | 工事 1 案件 補助金抽出 | 4.0h × ¥8,000 = ¥32,000 | 2 req × ¥3 = ¥6 | **¥31,994** |
| **dev** | AI 開発者 / Claude Desktop 個人 | 試作 1 endpoint 検証 | 2.0h × ¥10,000 = ¥20,000 | 5 req × ¥3 = ¥15 | **¥19,985** |
| **index** | 全 audience アグリゲータ | 平均 case (全 page 加重) | 3.0h × ¥9,000 = ¥27,000 | 3 req × ¥3 = ¥9 | **¥26,991** |
| **journalist** | 記者・調査会社 / 1 取材先 | 法人裏取り 1 件 | 1.5h × ¥8,000 = ¥12,000 | 3 req × ¥3 = ¥9 | **¥11,991** |
| **manufacturing** | 製造業特化コンサル / 顧問 10 社 | 設備投資 1 案件抽出 | 4.0h × ¥8,000 = ¥32,000 | 2 req × ¥3 = ¥6 | **¥31,994** |
| **real_estate** | 不動産業特化コンサル / 顧問 8 社 | 賃貸事業 1 案件抽出 | 3.5h × ¥8,000 = ¥28,000 | 2 req × ¥3 = ¥6 | **¥27,994** |
| **shihoshoshi** | 司法書士 / 商業登記 1 件 | houjin 360° + jurisdiction | 3.0h × ¥10,000 = ¥30,000 | 2 req × ¥3 = ¥6 | **¥29,994** |
| **shinkin** | 信用金庫 取引先担当 / 月 100 取引先 | 1 取引先 補助金 + マル経 | 1.2h × ¥6,000 = ¥7,200 | 2 req × ¥3 = ¥6 | **¥7,194** |
| **shokokai** | 商工会 経営指導員 / 月 200 巡回先 | 1 巡回先 持続化補助金 案内 | 0.8h × ¥5,000 = ¥4,000 | 2 req × ¥3 = ¥6 | **¥3,994** |
| **smb** | 中小企業経営者 / 自社案件 | 自社の補助金候補 1 件相談前準備 | 2.0h × ¥5,000 = ¥10,000 | 3 req × ¥3 = ¥9 | **¥9,991** |
| **subsidy-consultant** | 補助金コンサル / 顧問 30 社 | 1 顧問先 月次スクリーニング | 1.5h × ¥8,000 = ¥12,000 | 3 req × ¥3 = ¥9 | **¥11,991** |
| **tax-advisor** | 税理士 / 顧問先 50 社 | 1 顧問先 措置法確認 | 1.0h × ¥10,000 = ¥10,000 | 2 req × ¥3 = ¥6 | **¥9,994** |
| **vc** | VC / M&A / 1 投資先 DD | 法人 1 社 行政処分 + 採択 + 適格 | 4.0h × ¥10,000 = ¥40,000 | 4 req × ¥3 = ¥12 | **¥39,988** |

### Saving range summary

- **最小**: ¥3,994/case (shokokai 経営指導員 — 巡回 frequency 高 / hourly rate 低)
- **最大**: ¥39,988/case (vc 法人 DD — 高 hourly + 多 endpoint 横断)
- **中央値**: ¥19,985/case (dev 試作 1 endpoint 検証)

## Disclaimers — 透明性 fence

1. **推定値**: 全数値は典型 case の参考値。実 case は工数 / hourly rate / req 数で変動する。
2. **AI 単体 baseline**: 「外部公的制度根拠なしの汎用 LLM 出力」を前提。 hallucination 裏取り工数を含む。
3. **誇大広告意図なし**: jpcite は事実検索 + scaffold 提供のみ。 専門家業務 (税理士業 / 行政書士業 / 司法書士業 / 監査意見 / 法律判断) は資格者本人の専権事項。
4. **¥3/req 完全従量**: anonymous 3 req/日 free per IP は API key なしで利用可 (JST 翌日 00:00 reset)。
5. **税抜表記**: ¥3/req は税抜 (qualified invoice T8010001213708)。

## Related pages

- `/audiences/cpa_firm.html` (tick#3 landed)
- `/audiences/shindanshi.html` (tick#3 landed)
- `/audiences/ma_advisor.html` (tick#3 landed)
- `/pricing.html` (¥3/req 完全従量)

## References

- pricing model: AutonoMath EC v4 改訂 (2026-04-30、¥3/req × Free 3 req/日)
- agent KPI 8: Cost-to-Serve / ASR / ARC / Spending Variance (Wave 16)
- agent funnel 6: Justifiability (Wave 43.5)
