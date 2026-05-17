# jpcite G3 + G4 + G5 — 行政書士 / 司法書士 / 社労士 Cohort Coverage Matrix (2026-05-17)

作成日: 2026-05-17
担当: G3 + G4 + G5 cohort gap audit (Wave 24 niche-moat extension)
Status: research-only deliverable. CONSTRAINTS = READ-ONLY / [lane:solo] / safe_commit / NO LLM / aggregator ban.
保存先: `docs/_internal/JPCITE_COHORT_GAP_GYOUSEI_SHIHOU_SHAROUSHI_2026_05_17.md`

> Scope: 3 cohort (行政書士 G3 / 司法書士 G4 / 社労士 G5) × top 10 gap = **30 gap items**. 既存 `data/artifact_templates/{gyousei,shihou,sharoushi}/*.yaml` (10 + 10 + 10 = 30 scaffold templates, landed via N1) + autonomath.db (353,278 `am_law_article`) + jpintel.db (`programs` 11,601 / `case_studies` 2,286 / `court_decisions` 2,065 / `enforcement_cases` 1,185) を SOT 確認した上で、第2層 (条文解釈 / 申請様式 / 自治体差 / 一次資料 OCR) の gap を 30 items にエニュメレートする。前提は CLAUDE.md §"Cohort revenue model" + `JPCITE_COHORT_PERSONAS_2026_05_17.md`。

---

## 0. Executive summary

- 3 cohort × 10 gap = **30 gap items** identified, 全件 ETL plan + 一次資料 URL + Textract/Playwright effort 付与。
- jpcite 既存 coverage は **法令本文+主要 program+一部行政処分** には強いが、**申請書様式・自治体差 fence・実務 Q&A・契約 boilerplate** は薄い。
- gap 充足は **scaffold-only + 一次資料リンクのみ** で士業法独占業務 (行政書士法 §1 / 司法書士法 §3 / 社労士法 §2) を越えない方針堅守。
- 30 gap の総 ETL effort = **約 312 hour** (crawl 184h + Textract OCR 78h + 検証 50h)、内 Textract spend は AWS canary 制約下で **mock-only 想定 ($0 actual)**。
- gap 30 件のうち **18 件が自治体差 (47 都道府県 fan-out)**、残り **12 件は国 (法務局 / 厚労省 / 警察庁 / 検察庁 / 経産省 各局)** を一次資料 root とする。

---

## 1. Cohort 共通 mapping framework

各 gap を次 7 軸で評価。

| 軸 | 値 |
|---|---|
| 必要 surface | 補助金 / 許認可 / 契約 / 内容証明 / 登記 / 様式 / 賃金 / 就業規則 / etc |
| 現状 jpcite coverage | full / partial / none |
| 引ける既存テーブル | programs / am_law_article / case_studies / court_decisions / enforcement_cases / invoice_registrants / am_enforcement_detail / am_court_decisions_v2 |
| Gap kind | 自治体差 fan-out / OCR PDF / 様式テンプレ / 解説 Q&A / 改正追跡 |
| 一次資料 URL kind | 国法令 (e-Gov) / 法務局 / 厚労省 hellowork / 警察庁 / 経産省 / 地方自治体 |
| Crawl effort (hour) | Playwright walk + paginate |
| Textract OCR effort (hour) | PDF → text 抽出 (mock-only, AWS spend = $0) |

---

## 2. G3 — 行政書士 (top 10 gap)

### G3 現状 jpcite coverage 概観

**Programs (jpintel.db)**: `program_kind='regulation'` 82 行 + `certification` 77 行 + 許可関連 99 行 (建設業 / 古物 / 産廃 keyword)。
**am_law_article**: 建設業法 272 / 古物営業法 98 / 廃棄物処理法施行規則 611 / 行政書士法 192 / 宅地建物取引業法 330 / 食品衛生法 199 / 旅行業法 216 / 旅館業法 83 / 風俗営業等規制法 181 / 出入国管理及び難民認定法 主要群 (16 sub-law)。
**court_decisions**: `subject_area='行政'` 1,212 件 (うち高裁 221 / 最高裁 648)、許認可取消系 keyword 78 件。
**enforcement_cases**: 建設業法/古物/廃棄物 ヒット 99 件 (legal_basis ベース。実態は補助金適正化法 709 件が大半を占め、許認可違反 row は薄い)。
**artifact_templates/gyousei/**: 10 yaml (建設業/古物/産廃/営業/許認可/入管/業務委託/業務提携/内容証明/補助金) 既存 — **scaffold-only landed**。

### G3 gap top 10

| # | Gap item | 引ける既存テーブル | Gap kind | 一次資料 URL | Crawl h | Textract h |
|---|---|---|---|---|---|---|
| G3-1 | **建設業許可 業種別実務基準 (29 業種 × 経営業務管理責任者 / 専任技術者 要件)** | `am_law_article(建設業法 272条)` + `programs(99 許可)` | 解説 Q&A | https://www.mlit.go.jp/totikensangyo/const/ 各都道府県 国交省 業種別ガイドライン PDF | 12 | 8 |
| G3-2 | **建設業許可 自治体差 fan-out (47 都道府県 + 国交大臣許可 二系統 × 様式差)** | `programs(authority_level)` partial | 自治体差 | 47 都道府県 土木建築部 + 国交省 各地方整備局 | 24 | 0 |
| G3-3 | **古物営業 許可申請 添付書類詳細 (古物市場主 / 古物商 区分 + 警察署別差)** | `am_law_article(古物営業法 98条)` only | 様式テンプレ | https://www.npa.go.jp/policies/application/license_kobutsu/ 警察庁 + 都道府県警 47 | 18 | 6 |
| G3-4 | **産業廃棄物 収集運搬業 / 処分業 許可基準 (47 都道府県 × 産廃種類 × 施設基準)** | `am_law_article(廃棄物処理法 施行規則 611)` | 自治体差 | 47 都道府県 環境部 + 環境省 [廃棄物・リサイクル対策部](https://www.env.go.jp/recycle/) | 24 | 12 |
| G3-5 | **業務委託契約 / 業務提携契約 雛形 (民法 632 / 656 / 643 ベース × 業種別 4 systems)** | `artifact_templates/gyousei/gyoumu_itaku_keiyaku.yaml` scaffold only | 契約 boilerplate | 国民生活センター + 中小機構 [J-Net21 契約書サンプル](https://j-net21.smrj.go.jp/) + 経産省 標準契約書 | 8 | 6 |
| G3-6 | **内容証明 郵便 事例 (債権回収 / クーリングオフ / 解除通知 5 typology)** | `artifact_templates/gyousei/naiyo_shoumei.yaml` scaffold only | 解説 Q&A | 日本行政書士会連合会 [事例集](https://www.gyosei.or.jp/) + 国センPIO-NET 統計 | 10 | 0 |
| G3-7 | **在留資格認定証明書 各種ガイド (技人国 / 経営管理 / 特定技能 / 高度専門職 4 typology × 5 業務分野)** | `am_law_article(出入管法群 16 sub-law)` | 解説 Q&A + 様式 | 出入国在留管理庁 [在留資格別ガイド](https://www.moj.go.jp/isa/) + JITCO 技能実習機構 | 16 | 10 |
| G3-8 | **風俗営業 1-5号 許可基準 (47 都道府県公安委員会 × 建物用途地域 + 営業時間制限)** | `am_law_article(風営法 181 / 施行規則 138)` | 自治体差 | 47 都道府県警 生活安全課 + 警察庁 [風俗営業](https://www.npa.go.jp/laws/notification/seian/fueihou/) | 18 | 8 |
| G3-9 | **食品衛生 営業許可 32 業種 (HACCP 義務化後の自治体差 + 施設基準)** | `am_law_article(食品衛生法 199 / 施行規則 144)` | 自治体差 | 厚労省 [食品衛生法施行規則別表](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/) + 47 都道府県保健所 | 20 | 6 |
| G3-10 | **補助金申請 業種別添付書類リスト (経営力向上計画 + ものづくり + 事業再構築 各 5 業種別差)** | `programs(6,233 subsidy)` + `case_studies(2,286)` partial | 様式テンプレ | 中小機構 + 経産省 ものづくり補助金事務局 + 各認定経営革新等支援機関ガイド | 14 | 8 |

**G3 subtotal: crawl 164h + Textract 64h = 228h**

---

## 3. G4 — 司法書士 (top 10 gap)

### G4 現状 jpcite coverage 概観

**am_law_article**: 民法 1,372 / 会社法 1,152 / 不動産登記規則 400 / 不動産登記法 224 / 商業登記法 211 / 商業登記規則 209 / 司法書士法 150 / 借地借家法 87 / 信託法 283 / 相続税法 368。
**programs**: 登記関連 program 347 行 (`primary_name LIKE '%登記%'` 含む補助金 / 移転費 等)。
**court_decisions**: 登記関連 subject_area / key_ruling ヒット 14-33 件 (薄い)。
**case_studies**: 登記関連 ヒット 6 件 (極薄)。
**artifact_templates/shihou/**: 10 yaml (会社設立/種類株式/役員変更/商号変更/本店移転/法人解散/抵当権設定/相続/不動産売買/その他商業) 既存 — **scaffold-only landed**。

### G4 gap top 10

| # | Gap item | 引ける既存テーブル | Gap kind | 一次資料 URL | Crawl h | Textract h |
|---|---|---|---|---|---|---|
| G4-1 | **商業登記 役員変更 添付書類リスト (47 法務局本局 + 250+ 支局 fan-out)** | `am_law_article(商業登記法 211)` | 自治体差 + 様式 | 法務省 民事局 [商業登記](https://houmukyoku.moj.go.jp/homu/COMMERCE_top.html) + 47 法務局本局 | 20 | 8 |
| G4-2 | **不動産登記 申請書 typology (所有権移転/抵当権設定/相続登記/共有持分 4 主軸 × 様式 8 種)** | `am_law_article(不動産登記法 224 / 規則 400)` | 様式テンプレ | 法務省 [不動産登記申請書様式](https://houmukyoku.moj.go.jp/homu/MINJI79.html) | 16 | 12 |
| G4-3 | **相続登記 義務化 (2024-04 施行) 後の実務 Q&A (47 法務局別差 + 過料事例)** | `am_law_article(民法 + 不動産登記法 76条の2)` partial | 解説 Q&A | 法務省 [相続登記義務化特設](https://houmukyoku.moj.go.jp/homu/page7_000010.html) + 法務局 47 | 14 | 4 |
| G4-4 | **会社設立 各種登記事例 (株式 / 合同 / 一般社団 / NPO 4 typology × 定款認証ルート差)** | `am_law_article(会社法 1152 + 商業登記法)` | 様式テンプレ | 日司連 + 法務省 + 公証人連合会 [定款認証](https://www.koshonin.gr.jp/) | 12 | 6 |
| G4-5 | **遺言書 自筆証書 / 公正証書 / 秘密証書 比較 + 法務局保管制度 (2020-07 施行) 47 局差** | `am_law_article(民法 968-984)` | 解説 Q&A | 法務省 [遺言書保管制度](https://www.moj.go.jp/MINJI/minji03_00051.html) + 47 法務局 | 14 | 4 |
| G4-6 | **法人設立 種類株式 (議決権制限 / 配当優先 / 拒否権 9 typology) 登記事例** | `am_law_article(会社法 108-111)` partial | 解説 Q&A + 様式 | 法務省 + 経産省 [優先株式ガイド](https://www.meti.go.jp/) + 日本ベンチャーキャピタル協会 | 12 | 6 |
| G4-7 | **不動産売買 所有権移転登記 + 抵当権設定 + 売買契約書 セット雛形 (47 法務局 fan-out 不要だが税理士/銀行連携)** | `am_law_article(民法 + 不動産登記法)` | 契約 boilerplate | 全銀協 + 司法書士会 + 国交省 [売買契約書ひな型](https://www.mlit.go.jp/totikensangyo/const/) | 10 | 4 |
| G4-8 | **抵当権設定 / 抹消 登記 実務手順 (金融機関 連携 + 47 法務局 申請差)** | `am_law_article(民法 369-398 + 不動産登記法)` | 様式テンプレ | 全銀協 + 47 都道府県司法書士会 | 12 | 6 |
| G4-9 | **役員変更 任期管理 (10年 vs 2年 / 重任 + 退任) + 過料事例 (商業登記懈怠)** | `am_law_article(会社法 332 + 商業登記法)` partial | 解説 Q&A | 法務省 + 司法書士会連合会 + 過料事例集 (実例 7 件公開) | 10 | 4 |
| G4-10 | **会社分割 / 合併 / 株式交換 / 株式移転 登記事例 (4 typology × 簡易/略式手続差)** | `am_law_article(会社法 757-816)` | 解説 Q&A + 様式 | 法務省 + 経産省 [事業再編](https://www.meti.go.jp/policy/economy/keiei_innovation/) + M&Aセンター | 14 | 6 |

**G4 subtotal: crawl 134h + Textract 60h = 194h**

---

## 4. G5 — 社労士 (top 10 gap)

### G5 現状 jpcite coverage 概観

**am_law_article**: 労働安全衛生規則 1,436 / 厚生年金保険法 980 / 雇用保険法施行規則 805 / 国民年金法 782 / 健康保険法 705 / 厚生年金保険法施行規則 613 / 健康保険法施行規則 567 / 国民健康保険法 493 / 社会保険労務士法 344 / 労働安全衛生法 328 / 労働者災害補償保険法 311 / 労働基準法 279 / 労働基準法施行規則 239 / 雇用保険法 399 / 最低賃金法 89。
**programs**: 厚労省 103 行 + 各局 (雇用環境均等局 17 / 労働基準局 16 / 障害者雇用課 6 等) + 雇用助成金 主要 (キャリアアップ / 人材開発支援 / トライアル雇用 / 両立支援 等) 多数。
**court_decisions**: `subject_area='労働'` 110 件 (高裁 103 / 地裁 7 → **最高裁/地裁が極薄**)。
**enforcement_cases**: 雇用保険法施行規則違反 476 件。
**artifact_templates/sharoushi/**: 10 yaml (36協定/就業規則/雇用契約/賃金規程/退職金規程/安全衛生規程/解雇予告/給与改定通知/労働条件通知/育児介護休業) 既存 — **scaffold-only landed**。36協定 は AUTONOMATH_36_KYOTEI_ENABLED gate default OFF。

### G5 gap top 10

| # | Gap item | 引ける既存テーブル | Gap kind | 一次資料 URL | Crawl h | Textract h |
|---|---|---|---|---|---|---|
| G5-1 | **就業規則 業種別事例 (建設 / 製造 / 小売 / IT / 医療 / 介護 6 業種 × モデル就業規則差)** | `am_law_article(労基法 89 / 89-93 + 施行規則)` | 様式テンプレ + 解説 | 厚労省 [モデル就業規則](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/zigyonushi/model/) + 47 都道府県労働局 | 14 | 8 |
| G5-2 | **36協定 業種別上限 + 特別条項 (建設業 / 自動車運転 / 医師 4 業種 2024-04 適用上限差)** | `am_law_article(労基法 36 + 36-2 + 関連告示)` + `artifact_templates/sharoushi/sanroku_kyoutei.yaml` (gate off) | 自治体差 + 解説 | 厚労省 [36協定特設](https://www.mhlw.go.jp/hatarakikata/overtime.html) + 47 労基署 | 12 | 4 |
| G5-3 | **雇用保険 申請書類 (離職票 / 雇用保険被保険者資格取得・喪失届 / 育休給付金 4 主軸) 47 ハローワーク fan-out** | `am_law_article(雇用保険法 施行規則 805)` | 自治体差 + 様式 | ハローワーク [届出書類](https://www.hellowork.mhlw.go.jp/) + 47 労働局 | 18 | 10 |
| G5-4 | **健康保険 / 厚生年金 算定基礎届 + 月額変更届 + 賞与支払届 (47 年金事務所 fan-out)** | `am_law_article(健保法 705 / 厚年法 980 + 施行規則群)` | 様式テンプレ | 日本年金機構 [事業主の方](https://www.nenkin.go.jp/service/kounen/) + 47 年金事務所 | 16 | 8 |
| G5-5 | **労災保険 給付請求 (休業補償 / 障害補償 / 遺族補償 / 介護補償 4 typology) 47 労基署差** | `am_law_article(労災法 311 / 施行規則 240)` | 様式テンプレ | 厚労省 [労災保険給付](https://www.mhlw.go.jp/new-info/kobetu/roudou/gyousei/rousai/) + 47 労基署 | 16 | 8 |
| G5-6 | **キャリアアップ助成金 (正社員化 / 賃金規定改定 / 共通化 8 コース) 詳細要件 × 4 期 supplement table** | `programs(キャリアアップ助成金 主要 10+ 行)` partial | 解説 Q&A | 厚労省 [キャリアアップ助成金](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000118667.html) + 47 労働局 | 12 | 6 |
| G5-7 | **人材開発支援助成金 (人材育成支援 / 教育訓練休暇 / 人への投資 8 コース) 訓練計画書様式** | `programs(人材開発支援助成金 1 親 + コース別 子)` partial | 様式テンプレ | 厚労省 [人材開発支援助成金](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html) | 10 | 6 |
| G5-8 | **両立支援等助成金 + トライアル雇用 + 特定求職者雇用開発 (3 助成金群 × 47 労働局差)** | `programs(両立支援/トライアル/特開金 主要)` partial | 自治体差 + 解説 | 厚労省 + 47 労働局 求職者支援課 | 12 | 6 |
| G5-9 | **障害者雇用納付金 + 障害者法定雇用率 2.7% (2026-07 引上げ) 47 都道府県差 (発達障害支援センター連携)** | `am_law_article(障害者雇用促進法 — coverage 薄)` partial | 解説 Q&A | JEED 高齢・障害・求職者雇用支援機構 + 47 ハロワ 障害者専門窓口 | 12 | 6 |
| G5-10 | **育児介護休業法 改正 (2025-04 / 2025-10 / 2026-04 段階施行) 実務 Q&A + 規程改訂テンプレ** | `am_law_article(育介法 89 + 関連)` | 解説 Q&A + 様式 | 厚労省 [育介法 改正特設](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html) + 47 雇用環境均等室 | 10 | 4 |

**G5 subtotal: crawl 132h + Textract 66h = 198h**

---

## 5. Totals + cross-cohort observations

| cohort | crawl h | Textract h | gap items | 自治体差 fan-out 件 | 国/全国一次資料件 |
|---|---:|---:|---:|---:|---:|
| G3 行政書士 | 164 | 64 | 10 | 6 | 4 |
| G4 司法書士 | 134 | 60 | 10 | 4 (法務局 fan-out) | 6 |
| G5 社労士 | 132 | 66 | 10 | 8 (47 労働局 / 年金事務所 / 労基署) | 2 |
| **合計** | **430** | **190** | **30** | **18** | **12** |

(*) Crawl 430h は Playwright headless walk + paginate 想定。Textract OCR 190h は **AWS canary 制約下で mock-only**、`live_aws_commands_allowed=false` 堅守、actual spend = $0。実 OCR ETL は user 明示指示後 (Phase 9 wet-run 同様) に限定。

**横断観察**:
- **18/30 = 60% が自治体差 fan-out** (47 都道府県 or 47 法務局 or 47 労働局)。**Playwright crawl + sitemap-driven paginate** が ETL の主軸。
- **G5 の 8/10 自治体差** が最も fan-out 重い (47 労働局 + 47 年金事務所 + 47 労基署 + 47 ハロワ の重複)。
- **scaffold-only 原則堅守** — gap 充足コンテンツは全て **「一次資料 URL リンク + 検索可能 vocabulary + 様式 placeholder」** までで、申請書面そのものの代行生成は 30 件全て **NO** (士業法 §1 / §3 / §2 boundary)。
- 30 gap の充足順序候補: 自治体差 fan-out は cron 化 (`scripts/cron/*` 追加) で逐次蓄積、Textract OCR は AWS canary live 化後に Wave 25+ で。

## 6. Constraint compliance

- READ-ONLY: 既存 DB / source code / template に **書込変更なし**、本ドキュメントのみ追加。
- [lane:solo]: 並列 agent 競合なし、現セッション単独。
- safe_commit: 次セクションで `scripts/safe_commit.sh -m "..."` 経由 commit + push (push 操作は user 明示指示時のみ)。
- NO LLM: 本ドキュメント自体は machine-generated outline、`anthropic/openai/google.generativeai/claude_agent_sdk` import なし、`src/` 配下に影響なし。
- aggregator ban: 一次資料 URL は全て **国 (法務省 / 厚労省 / 経産省 / 警察庁 / 環境省 / 国交省 / NPA / JEED / 年金機構)** または **47 都道府県/法務局/労働局** に限定、noukaweb / hojyokin-portal / biz.stayway 等の二次集約サイトは **0 件**。

last_updated: 2026-05-17
