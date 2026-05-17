# jpcite CL20 — G Series (G1-G8) Cohort Gap Matrix Audit Consolidation (2026-05-17)

date: 2026-05-17
mode: READ-ONLY audit / [lane:solo] / safe_commit / NO LLM
scope: 8 cohort (G1 税理士 / G2 会計士 / G3 行政書士 / G4 司法書士 / G5 社労士 / G6 SME 中小経営者 / G7 FDI 国際英訳 / G8 時系列 Dim Q) gap matrix consolidation
source: `autonomath.db` (17.5 GB SoT, snapshot 19:00 JST 2026-05-17)
SOT supersedes: predecessor cohort gap docs (`JPCITE_COHORT_GAP_ZEIRISHI_KAIKEISHI_*` + `JPCITE_COHORT_GAP_SME_FDI_TIMELINE_*` + `JPCITE_COHORT_GAP_GYOUSEI_SHIHOU_SHAROUSHI_*`)

CONTEXT (recap):
- CL20 #324 G1+G2 (税理士+会計士) — AA1+AA2 substrate landed
- CL20 #326 G6+G7+G8 (SME+FDI+時系列) — AA5+AA3+AA4 substrate landed (commits `9296b226d` / `32f5fbc09` / AA4 in 32f5fbc09)
- CL20 #328 G3+G4+G5 (行政書士+司法書士+社労士) — gap audit doc landed but ETL NOT landed (templates 50 scaffolds = data/artifact_templates/ yaml, am_artifact_templates DB 50 row)

---

## Section 1: 8 Cohort × Primary Gap × Current DB Row × Delta to Target

| Cohort | Persona | Primary corpus axis | Current row (autonomath.db) | Target | Delta | AA marker | Status |
|---|---|---|---|---:|---|---|---|
| **G1** | 税理士 | NTA QA shitsugi (9 cat) | 286 | ~2,400 | 88.1% gap | AA1 landed (substrate) | substrate OK / shitsugi backfill outstanding |
| **G1** | 税理士 | NTA 裁決 (vol 1–140) | 137 | ~3,500 | 96.0% gap | AA1 landed (substrate) | substrate OK / saiketsu backfill outstanding |
| **G1** | 税理士 | NTA bunsho_kaitou | 278 | ~600 | 53.7% gap | AA1 landed (substrate) | substrate OK |
| **G1** | 税理士 | am_law_article (tax laws) | 36,541 | same | 0% | AA1 landed (substrate) | full |
| **G1** | 税理士 | tsutatsu_extended / amend_history | 0 / 0 | ~4,800 / 720 | 100% gap | scheduled | outstanding |
| **G2** | 会計士 | am_accounting_standard (ASBJ) | **31** | 31+適用指針 | 0% (base) | AA2 landed (substrate) | substrate OK |
| **G2** | 会計士 | am_audit_standard (JICPA) | **61** | 36+70+ 実務指針 | 0% (base) | AA2 landed (substrate) | substrate OK |
| **G2** | 会計士 | am_internal_control_case | **21** | ~3,800 上場 | 99.4% gap | AA2 landed (substrate) | substrate OK / backfill outstanding |
| **G3** | 行政書士 | artifact_templates segment=行政書士 | **10** (scaffold) | 10 + 10 gap items | scaffold landed / ETL pending | N1 scaffold landed | **outstanding (no AA marker)** |
| **G3** | 行政書士 | 許認可 自治体差 (47 都道府県 fan-out) | 84 reg + 79 cert | 47 pref × 5 業種 fence | 95%+ gap | — | outstanding |
| **G4** | 司法書士 | artifact_templates segment=司法書士 | **10** (scaffold) | 10 + 10 gap items | scaffold landed / ETL pending | N1 scaffold landed | **outstanding (no AA marker)** |
| **G4** | 司法書士 | 商業登記 + 不動産登記 様式 fan-out | am_law_article(商業登記法 211 / 不動産登記法 224 / 規則 400) | 47 法務局 + 250 支局 fan-out | 95%+ gap | — | outstanding |
| **G5** | 社労士 | artifact_templates segment=社労士 | **10** (scaffold) | 10 + 10 gap items | scaffold landed / ETL pending | N1 scaffold landed | **outstanding (no AA marker)** |
| **G5** | 社労士 | 助成金コース + 47 ハロワ + 労働法 | am_law_article(労基/労安/雇保/健保/厚年 8,200+) + programs(厚労省 103) | 47 労働局 + 47 年金事務所 + 47 労基署 + 47 ハロワ fan-out | 95%+ gap | — | outstanding |
| **G6** | SME 中小経営者 | am_adoption_narrative (採択 narrative) | **201,845** | 201,845 (substrate complete) | 0% | **AA5 landed `75ad67718`** | **complete (substrate)** |
| **G6** | SME 中小経営者 | jpi_adoption_records (base) | 201,845 | same | 0% | substrate | full |
| **G6** | SME 中小経営者 | jpi_programs all kinds | 13,578 (6,339 subsidy) | same | 0% | substrate | full |
| **G6** | SME 中小経営者 | am_program_narrative / case_study_narrative | 0 / 0 | 2,286 case + program rollup | 100% gap | secondary | outstanding (lower priority) |
| **G7** | FDI 国際英訳 | am_law_article body_en | **13,542** (jumped from 1) | ~80,000 (JLT 870 laws) | 83% gap (massive substrate land) | **AA3 landed `32f5fbc09`** | **substrate OK (delta target advanced)** |
| **G7** | FDI 国際英訳 | am_tax_treaty | **54** (jumped from 33) | ~80 (MOF) | 33% gap | AA3 landed | **substrate OK** |
| **G8** | 時系列 Dim Q | am_monthly_snapshot_log | **240** (60 mo × 4 axis) | 60 mo × 12 tbl = 720 | 67% gap (snapshot spine wide) | **AA4 landed (in `32f5fbc09`)** | **substrate OK** |
| **G8** | 時系列 Dim Q | am_amendment_diff | 16,116 | 5-year rolling | partial | substrate | full (current window) |
| **G8** | 時系列 Dim Q | am_amendment_snapshot | 14,596 | version_seq 1-2 → 60 | depth gap | substrate | outstanding (depth) |
| **G8** | 時系列 Dim Q | am_entity_monthly_snapshot | 0 | 1 row/houjin/month | 100% gap | substrate | outstanding |

---

## Section 2: G Series Completion Status — 5 / 8 Complete

| # | Cohort | AA marker | Substrate | Status | Symbol |
|---|---|---|---|---|---|
| G1 | 税理士 | AA1 (#324) | 36,541 article + 701 NTA QA/saiketsu/bunsho | substrate landed | DONE |
| G2 | 会計士 | AA2 (#324) | 31 ASBJ + 61 JICPA + 21 IC case | substrate landed | DONE |
| G3 | 行政書士 | — | 10 scaffold yaml only / ETL pending | **OUTSTANDING** | TODO |
| G4 | 司法書士 | — | 10 scaffold yaml only / ETL pending | **OUTSTANDING** | TODO |
| G5 | 社労士 | — | 10 scaffold yaml only / ETL pending | **OUTSTANDING** | TODO |
| G6 | SME 中小経営者 | AA5 (`75ad67718`) | 201,845 am_adoption_narrative + FTS5 trigram | substrate landed | DONE |
| G7 | FDI 国際英訳 | AA3 (`32f5fbc09`) | body_en 1 → 13,542 (+13,541 row), treaty 33 → 54 | substrate landed | DONE |
| G8 | 時系列 Dim Q | AA4 (in `32f5fbc09`) | monthly_snapshot 60 mo × 4 axis = 240 entries | substrate landed | DONE |

**Score: 5 / 8 = 62.5% complete (substrate basis).** Outstanding: G3 + G4 + G5 (3 cohorts).

---

## Section 3: G3 + G4 + G5 ETL Roadmap (Outstanding Work)

### G3 — 行政書士 (top 10 gap items, ETL effort ≈ 228 hour)

| # | Item | 一次資料 root | Existing script | Crawl h | Textract h | Suggested burn |
|---|---|---|---:|---:|---:|---|
| G3-1 | 建設業許可 29 業種 × 経管 / 専技 要件 | mlit.go.jp/totikensangyo/const/ | new `ingest_kensetsugyou_kyoka_29.py` | 12 | 8 | crawl Phase A |
| G3-2 | 建設業許可 47 都道府県 fan-out | 47 pref 土木建築部 + 国交省地方整備局 | new `ingest_kensetsugyou_pref_47.py` | 24 | 0 | crawl Phase B |
| G3-3 | 古物営業 警察庁 + 47 都道府県警 | npa.go.jp/policies/application/license_kobutsu/ | new `ingest_kobutsu_47.py` | 18 | 6 | crawl Phase B |
| G3-4 | 産廃 47 都道府県 × 種類 × 施設 | env.go.jp/recycle/ + 47 pref 環境部 | new `ingest_sanpai_pref_47.py` | 24 | 12 | crawl Phase B + OCR |
| G3-5 | 業務委託契約 / 業務提携 4 system 雛形 | j-net21.smrj.go.jp + 経産省標準契約書 | new `ingest_keiyaku_template.py` | 8 | 6 | crawl Phase A |
| G3-6 | 内容証明 5 typology 事例 | gyosei.or.jp + 国センPIO-NET | new `ingest_naiyo_shomei.py` | 10 | 0 | crawl Phase A |
| G3-7 | 在留資格 4 typology × 5 業務 | moj.go.jp/isa/ + JITCO | new `ingest_zairyu_4typology.py` | 16 | 10 | crawl Phase B |
| G3-8 | 風俗営業 1-5号 47 都道府県公安委員会 | npa.go.jp + 47 都道府県警 | new `ingest_fueihou_47.py` | 18 | 8 | crawl Phase B |
| G3-9 | 食品衛生 営業許可 32 業種 + 47 保健所 | mhlw.go.jp + 47 pref 保健所 | new `ingest_shokuhin_47.py` | 20 | 6 | crawl Phase C |
| G3-10 | 補助金 業種別添付書類 5 業種 | 中小機構 + 経産省事務局 | new `ingest_hojokin_attachments.py` | 14 | 8 | crawl Phase A |
| **subtotal** | | | | **164** | **64** | **228h total** |

### G4 — 司法書士 (top 10 gap items, ETL effort ≈ 194 hour)

| # | Item | 一次資料 root | Existing script | Crawl h | Textract h |
|---|---|---|---:|---:|---:|
| G4-1 | 商業登記 役員変更 47 法務局 + 支局 fan-out | houmukyoku.moj.go.jp/homu/COMMERCE_top.html | new `ingest_shougyou_torokin_fan_out.py` | 20 | 8 |
| G4-2 | 不動産登記 申請書 4 typology × 8 様式 | houmukyoku.moj.go.jp/homu/MINJI79.html | new `ingest_fudosan_form.py` | 16 | 12 |
| G4-3 | 相続登記義務化 (2024-04) 法務局別差 + 過料 | moj.go.jp/MINJI/minji03_00051.html | new `ingest_souzoku_giumu.py` | 14 | 4 |
| G4-4 | 会社設立 4 typology × 公証人 ルート差 | koshonin.gr.jp + 日司連 | new `ingest_kaisha_setsuritsu.py` | 12 | 6 |
| G4-5 | 遺言書 3 typology + 法務局保管制度 47 局 | moj.go.jp/MINJI/minji03_00051.html | new `ingest_yuigon.py` | 14 | 4 |
| G4-6 | 種類株式 9 typology 登記事例 | meti.go.jp + 日本VCA | new `ingest_shurui_kabushiki.py` | 12 | 6 |
| G4-7 | 不動産売買 売買契約 + 抵当権設定 セット | 全銀協 + 司法書士会 + 国交省 | new `ingest_fudosan_baibai.py` | 10 | 4 |
| G4-8 | 抵当権 設定 / 抹消 47 法務局差 | 全銀協 + 47 都道府県司法書士会 | new `ingest_teitouken.py` | 12 | 6 |
| G4-9 | 役員変更 任期管理 + 過料事例 | moj.go.jp + 司法書士会連合会 | new `ingest_yakuin_henkou.py` | 10 | 4 |
| G4-10 | 会社分割 / 合併 / 株式交換 / 移転 4 typology | meti.go.jp/policy/economy/keiei_innovation/ | new `ingest_kumiawase.py` | 14 | 6 |
| **subtotal** | | | | **134** | **60** | **194h total** |

### G5 — 社労士 (top 10 gap items, ETL effort ≈ 198 hour)

| # | Item | 一次資料 root | Existing script | Crawl h | Textract h |
|---|---|---|---:|---:|---:|
| G5-1 | 就業規則 業種別 6 業種 + 47 都道府県労働局 | mhlw.go.jp/stf/seisakunitsuite/.../model/ | new `ingest_shugyo_kisoku_6gyou.py` | 14 | 8 |
| G5-2 | 36協定 4 業種 2024-04 上限 + 47 労基署 | mhlw.go.jp/hatarakikata/overtime.html | new `ingest_36kyoutei_4gyou.py` | 12 | 4 |
| G5-3 | 雇用保険 4 主軸 + 47 ハロワ | hellowork.mhlw.go.jp + 47 労働局 | new `ingest_koyou_hoken_47.py` | 18 | 10 |
| G5-4 | 健保 / 厚年 算定基礎 + 47 年金事務所 | nenkin.go.jp + 47 年金事務所 | new `ingest_nenkin_47.py` | 16 | 8 |
| G5-5 | 労災給付 4 typology + 47 労基署 | mhlw.go.jp/new-info/kobetu/roudou/.../rousai/ | new `ingest_rousai_4typology.py` | 16 | 8 |
| G5-6 | キャリアアップ助成金 8 コース × 4 期 | mhlw.go.jp/stf/seisakunitsuite/.../0000118667.html | new `ingest_career_up_8course.py` | 12 | 6 |
| G5-7 | 人材開発支援助成金 8 コース 訓練計画書 | mhlw.go.jp/.../d01-1.html | new `ingest_jinzai_kaihatsu.py` | 10 | 6 |
| G5-8 | 両立 + トライアル + 特開金 47 労働局差 | mhlw.go.jp + 47 労働局 求職者支援 | new `ingest_3joseikin.py` | 12 | 6 |
| G5-9 | 障害者雇用納付金 + 法定雇用率 2.7% (2026-07) | JEED + 47 ハロワ障害者専門 | new `ingest_shougaisha_koyou.py` | 12 | 6 |
| G5-10 | 育介法改正 2025/26 段階施行 規程テンプレ | mhlw.go.jp/.../0000130583.html + 47 雇用環境均等室 | new `ingest_ikukai_kaisei.py` | 10 | 4 |
| **subtotal** | | | | **132** | **66** | **198h total** |

**G3+G4+G5 GRAND TOTAL = crawl 430h + Textract 190h = 620 hour, 30 gap items, 18 自治体差 fan-out + 12 国一次資料.**

**Burn footprint estimate (assuming AWS canary EB DISABLED / Textract mock-only $0):**
- Playwright headless walk: local-only, $0 (per `feedback_packet_gen_runs_local_not_batch`).
- Textract OCR: mock-only $0 until user explicit Phase 9+ wet-run UNLOCK.
- S3 staging: ≤500MB raw PDF, ≤$0.013/month (post-Athena Parquet ZSTD).

---

## Section 4: Cohort Coverage % Per Persona

| Persona | Substrate landed | Direct endpoint coverage | Composed tool coverage | Cohort total coverage % | Outstanding axis |
|---|---|---|---|---:|---|
| 税理士 (G1) | AA1 (36,541 法令本文 + 701 NTA QA/saiketsu) | 6 / 8 業務 direct | 2 / 8 業務 composed | **75%** | NTA QA backfill (88.1% gap), 通達改正 (100% gap) |
| 会計士 (G2) | AA2 (31 ASBJ + 61 JICPA + 21 IC case) | 5 / 8 業務 | 3 / 8 業務 composed | **62%** (越権 J-SOX 監査意見除外) | 内部統制 IC case 99.4% gap |
| 行政書士 (G3) | scaffold-only (10 yaml × N1) | 4 / 8 業務 direct (許認可/補助金/post-award) | 1 / 8 業務 composed (bundle_application_kit) | **30%** | 10 gap items × 47 fan-out, AA marker pending |
| 司法書士 (G4) | scaffold-only (10 yaml × N1) | 2 / 8 業務 (越権 不動産登記/相続を除く) | 2 / 8 業務 composed | **25%** | 10 gap items × 47 法務局 fan-out, AA marker pending |
| 社労士 (G5) | scaffold-only (10 yaml × N1) | 3 / 8 業務 (越権 個別労務代理を除く) | 1 / 8 業務 composed | **30%** | 10 gap items × 47 労働局/年金/労基/ハロワ fan-out, AA marker pending |
| SME 中小経営者 (G6) | AA5 (201,845 narrative) | 5 / 8 業務 direct | 2 / 8 業務 composed | **85%** (top cohort) | 経営者 segment ID 列 / 業種 SME flag 一部 |
| FDI 国際英訳 (G7) | AA3 (body_en 13,542 + treaty 54) | 3 / 6 業務 direct (法令英訳/treaty/EJ matching) | 1 / 6 業務 composed | **50%** (depth jump from 1.5%) | JLT 残 ~67K article + PE 28 row |
| 時系列 Dim Q (G8) | AA4 (snapshot 60 mo × 4 axis) | 4 / 5 業務 (as_of view + diff + amendment trace + monthly digest) | 1 / 5 業務 composed | **70%** | entity_monthly_snapshot 0 row / snapshot 8 tbl × 60 mo backfill |

**Weighted cohort coverage (substrate × axis density):**
- 5 cohort substrate complete (G1/G2/G6/G7/G8) = **5/8 = 62.5%**
- 3 cohort scaffold-only (G3/G4/G5) = **3/8 = 37.5% outstanding**
- Top-2 cohort (G1 + G6) average **80% coverage**, bottom-3 (G3/G4/G5) average **28% coverage** — clear bifurcation.

---

## Section 5: Operator Decision — G3+G4+G5 Dispatch Timing

### Decision space (Yes/No only, per `feedback_no_priority_question`)

**Question for operator:** G3+G4+G5 ETL (30 gap items × 620 hour total) を **今 dispatch するか next session か**?

### Trade-off matrix (READ-ONLY observation)

| 軸 | 今 dispatch | next session |
|---|---|---|
| Substrate completeness | 5/8 → 8/8 (this session 完了) | 5/8 hold |
| AWS canary spend | $0 (Playwright local + Textract mock) | $0 |
| Lane contention | parallel agents 18-30 同時並走 (Wave 60+ pattern) | next session で同等 |
| `feedback_slow_pace_pivot` 適合 | OK (大決定なし、ETL 拡張のみ) | OK (1 cycle 待ち pattern) |
| `feedback_loop_never_stop` 適合 | OK (ScheduleWakeup で連続) | OK |
| `feedback_18_agent_10_tick_rc1_pattern` 適合 | OK (Stream pattern 確立) | OK |
| Wave 95+ への influence | G3+G4+G5 cohort packet を Wave 95 で活用可能 | Wave 96+ slip |

### Recommendation (machine view, operator approval required)

**観察 only**: 既存 Wave 60-94 ramp (累計 432 outcome) + PERF-1..32 + Athena Q1-Q47 が landed 済みで、G3+G4+G5 dispatch の technical prerequisite (Playwright walk infrastructure, am_artifact_templates schema, jpi_programs `authority_level` column) は既に整っている。620h crawl + OCR は **lane:solo per script** で 30 script × 2-3 agent = 60-90 agent burst で wall time 8-12 hour 想定。

**Operator-decidable**: 今 dispatch / next session の二択 — **本 audit doc は decision substrate のみ提供、dispatch 判断は operator が下す**。

---

## Section 6: Constraint Compliance

- **READ-ONLY**: 既存 DB / source code / template に書込変更なし、本ドキュメントのみ追加。
- **[lane:solo]**: 並列 agent 競合なし、新 doc file のみ create (CodeX collision avoidance ✓)。
- **safe_commit.sh**: 次セクションで `scripts/safe_commit.sh -m "..."` 経由 commit、`--no-verify` 不使用。
- **NO LLM**: 本ドキュメントは machine-generated audit outline、`anthropic/openai/google.generativeai/claude_agent_sdk` import なし、src/ 配下に影響なし。
- **Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>** trailer 付与。

last_updated: 2026-05-17 19:00 JST
