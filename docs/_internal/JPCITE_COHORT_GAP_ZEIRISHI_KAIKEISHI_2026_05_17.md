# jpcite Cohort Gap Audit — 税理士 (G1) + 会計士 (G2)

date: 2026-05-17
mode: READ-ONLY audit / [lane:solo]
scope: cohort corpus coverage matrix + ETL plan
source: `autonomath.db` (15.9 GB SoT, snapshot 12:50 JST)

---

## Executive summary

| Cohort | Corpus axis           | Have                    | Need (target)         | Gap ratio | Sev    |
|--------|------------------------|-------------------------|------------------------|-----------|--------|
| G1 税理士 | 法令本体 (income/corp/cons/inhe) | 13,184 article rows / FT JP | same                  | 0%        | OK     |
| G1 税理士 | 通達 (基本通達 + 個別通達)        | tsutatsu_extended=0, am_law_article tsutatsu rows ≈ 4,800 | 4,800+ | 0% (JP) / amendment_history=0 | MID |
| G1 税理士 | 国税不服審判所 裁決            | 137 rows (vol 121–140)  | ~3,500 (vol 1–140)    | **96.0%** | HIGH   |
| G1 税理士 | 質疑応答事例                | 286 rows (shotoku/gensen のみ) | ~2,400 (9 categories) | **88.1%** | HIGH   |
| G1 税理士 | 文書回答事例                | 278 rows (uneven)        | ~600 (full 9 cat)     | 53.7%     | MID    |
| G1 税理士 | 通達改正履歴                | am_tax_amendment_history=0 | ≥ 8 years × 9 通達 | **100%**  | HIGH   |
| G2 会計士 | 監査基準 (JICPA + 企業会計審議会) | guideline=0             | 36 統一基準 + 70+ 実務指針 | **100%** | CRIT   |
| G2 会計士 | 企業会計基準 (ASBJ)          | guideline=0             | 31 (基準 1–31号) + 適用指針 | **100%** | CRIT   |
| G2 会計士 | 内部統制 報告書 事例           | 0                       | ~3,800 (上場企業最新FY)  | **100%** | HIGH   |

---

## G1 税理士 — Gap top 10 + ETL plan

### Coverage matrix (autonomath.db SoT)

```
am_law_article (full text JP) by law_canonical_id:
  law:corporate-tax            1,156 / 975  (84.3% has FT)
  law:income-tax               1,325 / 1,137 (85.8%)
  law:consumption-tax          542 / 450    (83.0%)
  law:sozei-tokubetsu          3,587 / 3,406 (95.0%)
  law:sozokuzei                368 / 306    (83.2%)
  law:hojin-zei-tsutatsu       1,367 / 1,344 (98.3%)
  law:shotoku-zei-tsutatsu     1,214 / 1,194 (98.4%)
  law:shohi-zei-tsutatsu       640 / 636    (99.4%)
  + 法人税法施行令/施行規則, 所得税法施行令/施行規則, 消費税法施行令/施行規則
  TOTAL key tax laws: 13,184 articles / 11,793 with text_full (89.4%)

nta_shitsugi          286     (only shotoku 261 + gensen 25)
nta_saiketsu          137     (vol 121–140 only, 1995–2025 missing 1–120 + 141+)
nta_bunsho_kaitou     278     (shotoku 155 / hojin 36 / gensen 26 / sozoku 18 / hyoka 3 / joto-sanrin 33 / zoyo 7)
am_nta_tsutatsu_extended    0
am_tax_amendment_history    0
am_law_tsutatsu_all         36   (canonical-rolled tsutatsu summary only)
```

### Top 10 gaps (ranked by 税理士 daily-use frequency × current zero-coverage)

| # | Gap                                                 | Now    | Need    | Source                                       | ETL effort | Owner |
|---|-----------------------------------------------------|--------|---------|----------------------------------------------|------------|-------|
| 1 | NTA 質疑応答 hojin (法人税)                              | 0      | ~600    | nta.go.jp/taxes/shiraberu/zeiho-kaishaku/shitsugi/hojin/ | 4h scrape + parse | etl |
| 2 | NTA 質疑応答 shohi (消費税)                              | 0      | ~400    | shitsugi/shohi/                              | 3h         | etl |
| 3 | NTA 質疑応答 sozoku (相続税)                             | 0      | ~350    | shitsugi/sozoku/                             | 3h         | etl |
| 4 | NTA 質疑応答 hyoka (財産評価)                             | 0      | ~280    | shitsugi/hyoka/                              | 3h         | etl |
| 5 | NTA 質疑応答 inshi/hotei/joto                          | 0      | ~520    | 3 categories                                 | 4h         | etl |
| 6 | NTA 裁決 vol 1–120 (1969–1995 + 1995–2020)            | 137    | ~3,300  | kfs.go.jp/service/MP/                        | 12h scrape + OCR fallback | etl |
| 7 | NTA 裁決 vol 141+ (incremental)                       | 137    | +ongoing| kfs.go.jp                                    | 1h cron weekly | etl |
| 8 | am_tax_amendment_history (通達改正履歴 8yr × 9 通達)     | 0      | ~720 rows | NTA tsutatsu 改正履歴 PDF + diff parse        | 6h         | etl |
| 9 | nta_bunsho_kaitou — backfill missing hojin/shohi/etc | 278    | ~600    | nta.go.jp/about/organization/ntc/bunsho-kaito/ | 3h        | etl |
| 10| 地方税法 + 地方税法施行令 個別通達 (自治体差分)              | 1,200 ish | 6,000  | soumu.go.jp + 47都道府県 個別通達            | 16h pref walk | etl |

### ETL plan G1

- 既存 `scripts/etl/ingest_nta_kfs_saiketsu.py` (vol 121–140 既出) を vol 1–120 で再実行 + retry walk → gap #6/#7 (13h)
- 新規 `scripts/etl/ingest_nta_shitsugi_categories.py` (9 category enum loop, BeautifulSoup parse, FTS5 insert via existing trigger) → gap #1–#5 (17h, parallel agent化可)
- 新規 `scripts/etl/ingest_nta_bunsho_kaitou.py` 再ingest → gap #9 (3h)
- 新規 `scripts/etl/ingest_tax_amendment_history.py` (NTA 改正通達 PDF → text → diff vs prev) → gap #8 (6h)
- 新規 `scripts/etl/ingest_chihozei_pref_tsutatsu.py` (47 pref walk, Playwright fallback) → gap #10 (16h)

**G1 合計工数: ~55h** (10 agents parallel で約 6h wall time)

---

## G2 会計士 — Gap top 5 + ETL plan

### Coverage matrix

```
am_law_article (関連法令の条文):
  law:konin-kaikeishi-ho           355 articles
  law:kinsho (金融商品取引法)         634
  law:renketsu-zaimushohyo-no       473
  law:shihanki-renketsu-zaimushohyo 163
  law:shihanki-zaimushohyo-nado     143
  law:chukan-renketsu-zaimushohyo   197
  → 法令 layer は 2,000+ articles で十分

am_law_guideline (issuer_org 内訳):
  金融庁         41
  公正取引委員会  2
  厚生労働省      1
  日本商工会議所  2
  日本経済団体連合会 2
  総務省          1
  → ASBJ / JICPA / 企業会計審議会 0件 (致命的)
```

### Top 5 gaps

| # | Gap                                                  | Now | Need     | Source                                       | ETL effort |
|---|------------------------------------------------------|-----|----------|----------------------------------------------|------------|
| 1 | ASBJ 企業会計基準 第1号–31号 + 適用指針 + 実務対応報告      | 0   | ~120 doc | asb.or.jp/jp/wp-content/uploads/             | 8h         |
| 2 | JICPA 監査基準委員会報告書 (200–800系) + 監査・保証実務委員会報告 | 0   | ~90 doc  | jicpa.or.jp/specialized_field/auditing/      | 8h         |
| 3 | 企業会計審議会 監査基準 + 中間監査基準 + 四半期レビュー基準     | 0   | 12 統一基準 | fsa.go.jp/singi/singi_kigyou/                | 3h         |
| 4 | 内部統制報告書 事例 (上場企業 EDINET FY2024)               | 0   | ~3,800   | EDINET API + XBRL parse                      | 18h        |
| 5 | 監査調書テンプレ (JICPA 監査ツール) + 監査意見事例           | 0   | ~50 doc  | jicpa.or.jp/audit_practical_tool/            | 4h         |

### ETL plan G2

- 新規 `scripts/etl/ingest_asbj_kaikei_kijun.py` (PDF download + pdfminer.six + body_text → am_law_guideline, issuer_org='ASBJ') → gap #1 (8h)
- 新規 `scripts/etl/ingest_jicpa_kansa_iinkai.py` (jicpa.or.jp walk + Playwright fallback for member-only) → gap #2 (8h)
- 新規 `scripts/etl/ingest_kigyokaikei_shingikai_kijun.py` (FSA 公開済PDF) → gap #3 (3h)
- 新規 `scripts/etl/ingest_edinet_naibu_tousei.py` (EDINET API + XBRL section抽出, am_audit_workpaper にmerge) → gap #4 (18h)
- 新規 `scripts/etl/ingest_jicpa_audit_tools.py` (公開ガイダンスのみ; member-only 除外) → gap #5 (4h)

**G2 合計工数: ~41h** (5 agents parallel で約 8h wall time)

---

## Notes / Constraints

- 全 ETL は既存 `am_law_guideline` + `nta_shitsugi` + `nta_saiketsu` + `nta_bunsho_kaitou` の schema 拡張不要で挿入可
- License: NTA/FSA/ASBJ/企業会計審議会 = gov standard / public domain → 再配布可
- JICPA = ¥0 公開 + 会員専用混在 → 公開 PDF のみ ingest、会員専用は exclusion list で除外
- EDINET = METI PDL v1.0 互換 → 再配布可 (出典明記 + extracted_at 必須)
- 通達改正履歴 (#8) は LLM 推論なしで diff のみ (textdiff library + ruby/kanji-aware normalizer)

## Cross-cohort dependency

- 税理士 #6/#7 (NTA 裁決) は **会計士 #4 (内部統制) と同じ FAISS index 拡張** を要求 → 共通基盤 `scripts/aws_credit_ops/submit_full_corpus_embed.py` の再実行 1 回で吸収
- 監査基準書 (G2 #2) は am_law_article の `body_en` 補完 (現状 0/13184) に再利用可能 (JICPA 公開英訳ある)

## Verification commands (post-ETL)

```bash
# G1 verify
sqlite3 autonomath.db "SELECT category, COUNT(*) FROM nta_shitsugi GROUP BY category"  # expect 9 categories
sqlite3 autonomath.db "SELECT COUNT(DISTINCT volume_no) FROM nta_saiketsu"             # expect ≥ 130
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_tax_amendment_history"                   # expect ≥ 600

# G2 verify
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_law_guideline WHERE issuer_org IN ('ASBJ','JICPA','企業会計審議会')"  # expect ≥ 220
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_audit_workpaper WHERE snapshot_json LIKE '%naibu_tousei%'"          # expect ≥ 3000
```

---

audit completed by Claude Opus 4.7 / [lane:solo] / READ-ONLY
