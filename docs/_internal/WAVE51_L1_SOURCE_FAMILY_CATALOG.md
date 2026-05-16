# Wave 51 L1 source family — 完全 catalog draft (30+ family roster)

**status**: 設計のみ / 実装禁止 (design doc only, no implementation)
**author**: jpcite ops
**date**: 2026-05-16
**SOT marker**: `docs/_internal/WAVE51_L1_SOURCE_FAMILY_CATALOG.md`
**supersedes**: なし (Wave 51 L1+L2 design = `docs/_internal/WAVE51_L1_L2_DESIGN.md` の roster 軸詳細化)
**precedes**: `outcome_source_crosswalk.json` (`site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json`) を 14 outcome × 6 family = 84 entry → **14 outcome × 30 family = 420 entry** に拡張する起点

---

## 0. 位置付け — Wave 50 RC1 → Wave 51 L1 完全 roster

Wave 50 RC1 で **14 outcome contract × 6 source family = 84 entry** が `outcome_source_crosswalk.json` に landed。Wave 51 L1 は **outcome を増やさず source family を 30+ に拡張** し、cross product を 420 entry に解放する。本 doc は L1+L2 design (`WAVE51_L1_L2_DESIGN.md`) で粗描された 30+ source roster を **完全 catalog** として固定し、ministry / category / license / access_mode / refresh / priority の 6 軸で全 family を列挙する。

**Wave 51 L1 の AX 連動**: agent funnel 6 段 (Discoverability / Justifiability / Trustability / Accessibility / Payability / Retainability) のうち **Discoverability + Justifiability + Trustability** の 3 軸を 30+ source で底上げ。**federated MCP recommendation hub 化 (Dim R)** の前提条件 = 「あらゆる公的 source を 1 hop で justifiable に拾える」状態を狙う。

---

## 1. 完全 catalog — 30+ family roster

| family_id | ministry | category | license | access_mode | refresh | priority |
| --- | --- | --- | --- | --- | --- | --- |
| egov_laws_regulations | e-Gov (デジタル庁) | 法令本文 | CC-BY 4.0 | API | daily | P0 |
| nta_invoice_publication | NTA (国税庁) | 適格請求書発行事業者 | OGL-2.0 (PDL v1.0) | bulk CSV | monthly | P0 |
| gbizinfo_houjin | 経産省 (gBizINFO) | 法人基本情報 | CC-BY 4.0 | API | daily | P0 |
| edinet_disclosure | 金融庁 (EDINET) | 有価証券報告書・開示 | 利用規約 | XBRL bulk | quarterly | P0 |
| jgrants_subsidy_portal | デジタル庁 (jGrants) | 補助金ポータル | CC-BY 4.0 | API + bulk | daily | P0 |
| sangyo_houjin_registry | 法務省 | 法人登記 (商業・法人) | 利用規約 | bulk | weekly | P0 |
| meti_subsidies | 経産省 | 補助金 (一般・経営支援) | OGL-2.0 | website | weekly | P1 |
| mlit_permits | 国交省 | 建設業許可・宅建業 | 利用規約 | website | monthly | P1 |
| mhlw_labor | 厚労省 | 労働基準・労災・社保 | OGL-2.0 | website + PDF | monthly | P1 |
| maff_grants_extended | 農水省 | 農業補助金 (交付決定) | OGL-2.0 | bulk Excel | quarterly | P1 |
| env_regulations | 環境省 | 環境規制・廃棄物・CO2 | OGL-2.0 | API | weekly | P1 |
| soumu_local_gov | 総務省 | 自治体財政・地方税 | 利用規約 | website | quarterly | P1 |
| mof_subsidies | 財務省 | 税制・予算・関税 | OGL-2.0 | website | monthly | P1 |
| mext_research | 文科省 | 研究助成・科研費 | OGL-2.0 | website | monthly | P1 |
| nta_invoice_extended | NTA (国税庁) | invoice 拡張 (zenken bulk) | OGL-2.0 (PDL v1.0) | bulk CSV | monthly | P1 |
| egov_amendment_diff | e-Gov | 法令改正 diff | CC-BY 4.0 | API | daily | P1 |
| jfc_loans | 公庫 (日本政策金融公庫) | 融資制度 | 利用規約 | website + Playwright | weekly | P1 |
| smrj_business | 中小機構 (中小企業基盤整備機構) | 中小企業支援 | OGL-2.0 | API + website | monthly | P1 |
| unic_pmda | PMDA (医薬品医療機器総合機構) | 医療規制・GMP | 利用規約 | website | monthly | P1 |
| court_decisions | 裁判所 | 判例・裁判例 | 利用規約 | website + bulk | monthly | P1 |
| enforcement_actions | 各省庁 (METI/MHLW/MAFF 等) | 行政処分公表 | 利用規約 | website | weekly | P1 |
| gazette_official | 官報 | 公示・公告 | 利用規約 | bulk + website | daily | P1 |
| gbizinfo_houjin_extended | 経産省 (gBizINFO) | 法人 deep (届出・許認可) | CC-BY 4.0 | API | daily | P1 |
| pref_47_municipal | 47 都道府県 (segmented wrapper) | 自治体公報・補助金 | 各自治体 license | website + API | weekly | P2 |
| muni_800_segments | 800 主要市町村 (deep wrapper) | 自治体公報 (deep) | 各自治体 license | website | monthly | P2 |
| jetro_invest | JETRO (日本貿易振興機構) | 外国投資・海外展開 | OGL-2.0 | website | monthly | P2 |
| jisc_standards | 経産省 (JISC) | JIS 規格・認証 | 利用規約 | API + PDF | quarterly | P2 |
| tokkyo_jpo | 特許庁 (JPO) | 特許・商標公報 | 利用規約 | API | weekly | P2 |
| mafg_climate | 環境省 (気候変動枠) | 気候統計・GHG 排出 | OGL-2.0 | API | weekly | P2 |
| estat_statistics | 総務省 (e-Stat) | 政府統計 | OGL-2.0 | API | weekly | P2 |
| njss_bids_aggregated | NJSS + 各自治体 | 入札公示 (中央+地方) | 利用規約 | website + API | weekly | P2 |
| nta_pdb_personal | NTA (国税庁) | 個人税務 (取扱注意) | (取扱注意) | API | private | P2_restricted |

**family 件数**: **32 family** (P0=6, P1=17, P2=8, P2_restricted=1)
**catalog 行数 (table 本体)**: **32 行** (header + separator を除く)

---

## 2. priority breakdown (4 層)

### 2.1 P0 (6 family) — Wave 51 L1 即時着手対象

| family_id | 理由 |
| --- | --- |
| egov_laws_regulations | 既存 6 family、法令本文の SoT。AX Trustability の根幹 |
| nta_invoice_publication | 既存、PDL v1.0 で API 再配布可、agent justifiability core |
| gbizinfo_houjin | 既存、法人 master の API 軸、houjin_bangou ↔ 制度 join 起点 |
| edinet_disclosure | 既存、上場・大企業 cohort の disclosure 軸 |
| jgrants_subsidy_portal | 既存、補助金 portal の canonical surface |
| sangyo_houjin_registry | **新規 P0**、法人登記 bulk、houjin_bangou の SoT を法務省側から bind |

### 2.2 P1 (17 family) — Wave 51 L1 Day 8-21 で着地

中央省庁横断 + 司法 + 公庫 + 官報 + 行政処分。`meti_subsidies` `mlit_permits` `mhlw_labor` `maff_grants_extended` `env_regulations` `soumu_local_gov` `mof_subsidies` `mext_research` `nta_invoice_extended` `egov_amendment_diff` `jfc_loans` `smrj_business` `unic_pmda` `court_decisions` `enforcement_actions` `gazette_official` `gbizinfo_houjin_extended`。各 family の access_mode は website / API / bulk / Playwright を混在、refresh は weekly / monthly / quarterly の 3 軸で stagger。

### 2.3 P2 (8 family) — Wave 51 L1 Day 22-28 で残務として着地

自治体 segmented (pref_47 / muni_800 wrapper) + JETRO + JISC + 特許庁 + 環境気候 + e-Stat + NJSS 入札。**pref_47 / muni_800 は 1 family wrapper + family_subkey で 47 + 800 segment に展開** (parent count は 2 のまま分布は 847)、crosswalk entry は wrapper 単位で 1 entry に集約。

### 2.4 P2_restricted (1 family) — 隔離扱い

| family_id | 隔離理由 |
| --- | --- |
| nta_pdb_personal | 個人税務 (取扱注意)、private access のみ、cross product 420 entry の対象外、Wave 51 L1 では実装しない |

---

## 3. license / access_mode の合計 cross product

### 3.1 license 軸 (5 種類)

- `CC-BY 4.0` (e-Gov / gBizINFO / jGrants)
- `OGL-2.0` (NTA / MHLW / MAFF / 環境 / 財務 / 文科 / SMRJ / e-Stat / JETRO 等)
- `PDL v1.0` (NTA invoice 特化、OGL-2.0 と並列)
- `利用規約` (EDINET / 法人登記 / 国交 / 総務 / 公庫 / 裁判所 / 官報 / PMDA / JISC / 特許庁 / NJSS)
- `各自治体 license` (pref_47 / muni_800)

### 3.2 access_mode 軸 (約 14 outcome に対応)

`API` / `bulk CSV` / `bulk Excel` / `XBRL bulk` / `website` / `website + API` / `website + PDF` / `website + Playwright` / `website + bulk` / `bulk + website` / `API + bulk` / `API + PDF` / `private API` / `各自治体 license` の 14 outcome。

### 3.3 合計 cross product = 14 × 30 = 420 entry

`outcome_source_crosswalk.json` の cross product を 84 → **420 entry** に拡張、`outcome_source_crosswalk_v2.json` (Wave 51 L1 で起票予定) を成果物として固定する。実際は outcome の性質で間引かれ **350±20 entry** に収束見込み (P2_restricted の `nta_pdb_personal` は除外)。

---

## 4. Wave 51 L1 implementation step (起点のみ)

実装は **Wave 51 L1 着手後に別 doc で展開** (本 doc は設計のみ)、以下は起点 anchor:

1. **migration 105 起票**: `am_source_family_metadata` table を `scripts/migrations/105_wave51_source_family_metadata.sql` で起票 (target_db: autonomath, idempotent CREATE IF NOT EXISTS、column = source_family_id / ministry_code / category / source_category / license / refresh_frequency / authority_url / is_segmented / segment_dimension / notes)
2. **seed row 32 件投入**: 本 catalog の 32 family を seed として bulk insert、segmented 2 件 (pref_47 / muni_800) は `is_segmented=1` + `segment_dimension='prefecture_code' / 'municipality_code'` で展開
3. **`outcome_source_crosswalk_v2.json` 起票**: 14 outcome × 30 family = 420 entry を P0 → P1 → P2 順に landing、P2_restricted は除外
4. **ETL stub 17 本起票**: P1 新規 17 family の ETL stub (`scripts/etl/ingest_<family_id>.py`) を skeleton 化、Wave 51 L1 Day 8-21 で実装
5. **acceptance test 起票**: 30+ family 全件の source family metadata round-trip + crosswalk integrity test を `tests/acceptance/test_wave51_l1_source_family_catalog.py` で起票

---

## 5. SOT marker

- **本 doc**: `docs/_internal/WAVE51_L1_SOURCE_FAMILY_CATALOG.md` (Wave 51 L1 source roster の正本)
- **上位 design**: `docs/_internal/WAVE51_L1_L2_DESIGN.md` (Wave 51 L1+L2 全体設計)
- **roadmap**: `docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md` (Day 1-28 Gantt)
- **plan**: `docs/_internal/WAVE51_plan.md` (Wave 51 骨子 159 行)
- **crosswalk target (将来)**: `site/releases/rc1-p0-bootstrap/outcome_source_crosswalk_v2.json` (420 entry、Wave 51 L1 着地時)
- **migration target (将来)**: `scripts/migrations/105_wave51_source_family_metadata.sql`

last_updated: 2026-05-16
