# jpcite CL30 — G3 + G4 + G5 (行政書士 / 司法書士 / 社労士) Cohort ETL Roadmap (2026-05-17)

作成日: 2026-05-17
担当: CL30 — G3+G4+G5 cohort gap matrix audit + ETL roadmap
Status: research-only roadmap. CONSTRAINTS = READ-ONLY scan / [lane:solo] / safe_commit / NO LLM / aggregator ban / NO live AWS spend without operator unlock.
保存先: `docs/_internal/G3_G4_G5_ETL_ROADMAP_2026_05_17.md`

> Scope: 既 landed gap matrix (`docs/_internal/JPCITE_COHORT_GAP_GYOUSEI_SHIHOU_SHAROUSHI_2026_05_17.md`, commit `48562dac3`) + CL20 G-series audit (`8628ca97a`) を **ETL roadmap** に展開する。Operator が 1 cohort 単位で「今 dispatch / next session」二択判断できる format。30 gap × source ministry × ETL strategy × AWS burn × decision を集約。

---

## 0. Executive summary (60-second SOT)

| 軸 | 値 |
|---|---|
| Cohort 数 | 3 (G3 行政書士 / G4 司法書士 / G5 社労士) |
| Gap items | **30 件** (10 / 10 / 10) |
| Scaffold yaml landed | **30 / 30** (`data/artifact_templates/{gyousei,shihou,sharoushi}/*.yaml`) |
| ETL effort 合計 | **620 hour** (G3 228h + G4 194h + G5 198h) |
| 自治体差 fan-out | **18 / 30** (G3 6 / G4 4 / G5 8) |
| 国一次資料 source | **12 / 30** (G3 4 / G4 6 / G5 2) |
| AWS Textract burn 推定 | **$8.0K — $13.0K** (G3 3-5K + G4 2.5-4K + G5 2.5-4K) |
| 残 budget (canary $19,490 - 既消化) | **operator 確認後判断**、wet-run UNLOCK gate 必須 |
| 既 ETL manifest 完了済 | G1 NTA / G2 会計士 / DD2 narrow / DD2 municipality (4 件) |
| 本 cohort manifest 状況 | **未生成** — Wave 25+ で `data/etl_g3_manifest_2026_05_17.json` 等 3 本要生成 |

**Bottom line**: 3 cohort × 30 gap 全件 scaffold landed、ETL は **all 一次資料 / aggregator ban**、Textract OCR は AWS canary wet-run UNLOCK 後に逐次。**今 dispatch するなら G5 (cron 化容易) > G3 (Playwright 重) > G4 (法務局 fan-out)** 順を推奨。最終決定は §5。

---

## Section 1: 3 cohort × 10 gap × source ministry + ETL strategy

### 1.1 G3 — 行政書士 (10 gap)

| # | Gap item | Source ministry / 一次資料 root | ETL strategy | Crawl h | Textract h |
|---|---|---|---|---:|---:|
| G3-1 | 建設業許可 業種別実務基準 (29 業種 × 経管 / 専技 要件) | 国交省 不動産・建設経済局 [建設業許可](https://www.mlit.go.jp/totikensangyo/const/) | Playwright walk × 国交省 + 47 都道府県整備局 sitemap、PDF batch DL → S3 staging → Textract async OCR (mock-only) | 12 | 8 |
| G3-2 | 建設業許可 自治体差 fan-out (47 都道府県 + 国交大臣 2 系統) | 47 都道府県 土木建築部 + 国交省 8 地方整備局 | sitemap-driven Playwright crawl、`scripts/cron/etl_g3_kensetsu_fanout.py` (cron 日次 1 県 / nightly = 47 日 1 周) | 24 | 0 |
| G3-3 | 古物営業 許可申請 添付書類詳細 (古物市場主 / 古物商 + 警察署別差) | 警察庁 [古物営業](https://www.npa.go.jp/policies/application/license_kobutsu/) + 47 都道府県警 生安課 | Playwright walk 47、警察署単位差分は 47 都道府県警 トップ + 古物営業ガイド PDF DL | 18 | 6 |
| G3-4 | 産廃 収集運搬 / 処分業 許可基準 (47 × 産廃種類 × 施設基準) | 環境省 [廃棄物・リサイクル](https://www.env.go.jp/recycle/) + 47 都道府県 環境部 | 47 都道府県 環境部 sitemap walk + 産廃ガイド PDF Textract、産廃種類 enum は scaffold yaml で固定 | 24 | 12 |
| G3-5 | 業務委託 / 業務提携 雛形 (民法 632 / 656 / 643) | 中小機構 [J-Net21](https://j-net21.smrj.go.jp/) + 経産省 標準契約書 + 国民生活センター | J-Net21 雛形 DL + 経産省 標準契約 5 業種版 DL、PDF 抽出 + yaml placeholder mapping | 8 | 6 |
| G3-6 | 内容証明 5 typology (債権回収 / クーリングオフ / 解除通知 / 損害賠償 / 警告) | 日行連 [事例集](https://www.gyosei.or.jp/) + 国センPIO-NET 統計 | 日行連 公開事例 walk、PIO-NET 統計 CSV DL (年次) | 10 | 0 |
| G3-7 | 在留資格 4 typology (技人国 / 経営管理 / 特定技能 / 高度専門職) × 5 業務分野 | 出入国在留管理庁 [在留資格別ガイド](https://www.moj.go.jp/isa/) + JITCO | 入管庁 在留資格別 PDF DL + JITCO 技能実習ガイド walk、業務分野 cross-product matrix yaml | 16 | 10 |
| G3-8 | 風俗営業 1-5 号 (47 公安委員会 × 用途地域 + 営業時間) | 警察庁 [風俗営業](https://www.npa.go.jp/laws/notification/seian/fueihou/) + 47 都道府県警 生安課 | Playwright walk 47 公安、用途地域差は scaffold で別 yaml に切出 | 18 | 8 |
| G3-9 | 食衛 営業許可 32 業種 (HACCP 義務化後 + 自治体差) | 厚労省 [食衛法施行規則別表](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/) + 47 保健所 | 厚労省 別表 PDF DL、47 都道府県 保健所 ページ walk、32 業種 enum yaml 固定 | 20 | 6 |
| G3-10 | 補助金 業種別添付書類 (経営力向上 + ものづくり + 事業再構築) × 5 業種別差 | 中小機構 + 経産省 + 認定経営革新等支援機関ガイド | 各事務局公式ページ + 公募要領 PDF DL、業種別 add-on を yaml 子分割 | 14 | 8 |

**G3 subtotal: 164h crawl + 64h Textract = 228h. 6/10 自治体差。**

### 1.2 G4 — 司法書士 (10 gap)

| # | Gap item | Source ministry / 一次資料 root | ETL strategy | Crawl h | Textract h |
|---|---|---|---|---:|---:|
| G4-1 | 商業登記 役員変更 添付書類 (47 法務局本局 + 250+ 支局 fan-out) | 法務省 民事局 [商業登記](https://houmukyoku.moj.go.jp/homu/COMMERCE_top.html) + 47 法務局本局 | 47 法務局 sitemap walk + 250 支局 URL enumerate (公開済 index)、添付書類 PDF DL → Textract | 20 | 8 |
| G4-2 | 不動産登記 申請書 typology (所有権移転 / 抵当権設定 / 相続 / 共有持分 × 様式 8 種) | 法務省 [不動産登記申請書様式](https://houmukyoku.moj.go.jp/homu/MINJI79.html) | MINJI79.html 配下 PDF batch DL、様式 8 種 enum yaml 固定 | 16 | 12 |
| G4-3 | 相続登記 義務化 (2024-04 施行) 後 Q&A + 47 法務局別過料事例 | 法務省 [相続登記義務化特設](https://houmukyoku.moj.go.jp/homu/page7_000010.html) + 47 法務局 | 特設ページ walk、47 法務局 Q&A 差分 walk (cron 月次) | 14 | 4 |
| G4-4 | 会社設立 4 typology (株式 / 合同 / 一般社団 / NPO) × 定款認証ルート | 日司連 + 法務省 + 公証人連合会 [定款認証](https://www.koshonin.gr.jp/) | 公証人連合会 sitemap walk、定款認証ルート差 yaml 4 typology 固定 | 12 | 6 |
| G4-5 | 遺言書 3 typology (自筆 / 公正 / 秘密) + 法務局保管 (2020-07) 47 局差 | 法務省 [遺言書保管制度](https://www.moj.go.jp/MINJI/minji03_00051.html) + 47 法務局 | 制度特設 PDF + 47 法務局 walk、保管所別運用差は scaffold で切出 | 14 | 4 |
| G4-6 | 法人設立 種類株式 (議決権制限 / 配当優先 / 拒否権 9 typology) | 法務省 + 経産省 [優先株式ガイド](https://www.meti.go.jp/) + JVCA | JVCA 種類株式 reference + 経産省 ガイド PDF DL、9 typology yaml 固定 | 12 | 6 |
| G4-7 | 不動産売買 所有権移転 + 抵当権設定 + 売買契約 雛形 set | 全銀協 + 司法書士会 + 国交省 [売買契約ひな型](https://www.mlit.go.jp/totikensangyo/const/) | 全銀協 / 国交省 雛型 DL、税理士/銀行連携部分は scaffold で boundary 明示 | 10 | 4 |
| G4-8 | 抵当権設定 / 抹消 (金融機関連携 + 47 法務局差) | 全銀協 + 47 都道府県司法書士会 | 47 都道府県司法書士会 site walk + 全銀協 標準雛型 DL | 12 | 6 |
| G4-9 | 役員変更 任期管理 (10y / 2y / 重任 + 退任) + 過料 (商登懈怠) 事例 | 法務省 + 司法書士会連合会 + 過料事例集 (公開 7 件) | 過料事例 7 件 walk、scaffold yaml で alert 計算ロジック placeholder | 10 | 4 |
| G4-10 | 会社分割 / 合併 / 株式交換 / 株式移転 (4 typology × 簡易/略式) | 法務省 + 経産省 [事業再編](https://www.meti.go.jp/policy/economy/keiei_innovation/) + M&A センター | 経産省 事業再編ガイド DL、4 typology × 2 簡易/略式 = 8 矩形 yaml 行 | 14 | 6 |

**G4 subtotal: 134h crawl + 60h Textract = 194h. 4/10 自治体差 (法務局 fan-out)。**

### 1.3 G5 — 社労士 (10 gap)

| # | Gap item | Source ministry / 一次資料 root | ETL strategy | Crawl h | Textract h |
|---|---|---|---|---:|---:|
| G5-1 | 就業規則 業種別 6 業種 (建設 / 製造 / 小売 / IT / 医療 / 介護) | 厚労省 [モデル就業規則](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/zigyonushi/model/) + 47 都道府県労働局 | モデル就業規則 PDF DL + 47 労働局 walk、6 業種 add-on yaml 子分割 | 14 | 8 |
| G5-2 | 36 協定 業種別上限 (建設 / 自動車 / 医師 4 業種 2024-04 上限差) | 厚労省 [36 協定特設](https://www.mhlw.go.jp/hatarakikata/overtime.html) + 47 労基署 | 特設 PDF + 47 労基署 walk、`AUTONOMATH_36_KYOTEI_ENABLED` flag default OFF 維持 | 12 | 4 |
| G5-3 | 雇用保険 申請書類 (離職票 / 取得喪失届 / 育休給付金) × 47 ハロワ | ハローワーク [届出書類](https://www.hellowork.mhlw.go.jp/) + 47 労働局 | 47 労働局 sitemap walk + ハロワ 届出 PDF DL、cron 日次 1 局 | 18 | 10 |
| G5-4 | 健保 / 厚年 算定基礎 + 月額変更 + 賞与支払届 (47 年金事務所) | 日本年金機構 [事業主の方](https://www.nenkin.go.jp/service/kounen/) + 47 年金事務所 | 年金機構 sitemap walk + 47 年金事務所 walk、様式 3 種 yaml 固定 | 16 | 8 |
| G5-5 | 労災 給付請求 (休業 / 障害 / 遺族 / 介護 4 typology × 47 労基署) | 厚労省 [労災保険給付](https://www.mhlw.go.jp/new-info/kobetu/roudou/gyousei/rousai/) + 47 労基署 | 給付 4 typology × 47 労基署 cross-product crawl、PDF DL → Textract | 16 | 8 |
| G5-6 | キャリアアップ助成金 (正社員化 / 賃金改定 / 共通化 8 コース) × 4 期 supplement | 厚労省 [キャリアアップ助成金](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000118667.html) + 47 労働局 | 厚労省 + 47 労働局 ガイド DL、8 コース yaml 子分割、4 期 supplement table 行 | 12 | 6 |
| G5-7 | 人材開発支援助成金 (人材育成 / 教育訓練休暇 / 人への投資 8 コース) | 厚労省 [人材開発支援助成金](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html) | 厚労省 配布 PDF DL、訓練計画書様式 yaml placeholder | 10 | 6 |
| G5-8 | 両立支援 + トライアル雇用 + 特開金 (3 助成金群 × 47 労働局) | 厚労省 + 47 労働局 求職者支援課 | 47 労働局 求職者支援課 walk + 厚労省 ガイド DL、3 助成金群 × 47 = 141 配列 yaml | 12 | 6 |
| G5-9 | 障害者雇用納付金 + 法定雇用率 2.7% (2026-07 引上げ) × 47 都道府県 | JEED + 47 ハロワ 障害者専門窓口 | JEED PDF DL + 47 ハロワ 障害者窓口 walk、率改定 schedule yaml 行 | 12 | 6 |
| G5-10 | 育児介護休業法 改正 (2025-04 / 2025-10 / 2026-04 段階) Q&A + 規程改訂 | 厚労省 [育介法 改正特設](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html) + 47 雇用環境均等室 | 改正特設 PDF DL + 47 均等室 walk、3 段階 schedule + 既存 `ikuji_kaigo_kyugyou.yaml` 拡張 | 10 | 4 |

**G5 subtotal: 132h crawl + 66h Textract = 198h. 8/10 自治体差 (47 労働局 / 年金事務所 / 労基署 / ハロワ)。**

---

## Section 2: 18 自治体差 fan-out plan

### 2.1 fan-out 軸 summary

| Cohort | fan-out 件数 | fan-out target | 1 周期所要 | cron cadence 案 |
|---|---:|---|---|---|
| G3 | 6 | 建設業 / 産廃 / 古物 / 風俗営業 / 食衛 / 補助金業種別 → **47 都道府県 + 47 都道府県警 (古物・風営)** | 47 日 (1 県 / 日) | `scripts/cron/etl_g3_*_daily.py` × 6 cron entry |
| G4 | 4 | 商業登記 / 相続登記 / 抵当権 / 不動産登記関連 → **47 法務局本局 + 250 支局** | 47 + 250 日 (本局 47 日 / 支局 250 日 2 並列) | `scripts/cron/etl_g4_houmukyoku_daily.py` 2 並列 |
| G5 | 8 | 就業規則 / 36 / 雇保 / 健保厚年 / 労災 / キャリアアップ / 両立支援 / 障害雇用 → **47 労働局 + 47 年金事務所 + 47 労基署 + 47 ハロワ** | 47 日 (multiplex per source) | `scripts/cron/etl_g5_*_daily.py` × 8 cron entry |

**合計 18 fan-out × 47 (本局/局/事務所) = 約 846 entry / 1 周期 = 47 日**。1 req / 3 sec rate limit 想定で 1 日 1 県分 = 約 28800 sec = 8 hour walk / 日。Playwright headless 並列 6 並列 → 約 1.5 hour / 日。

### 2.2 fan-out 共通 ETL pattern (per region per source)

```
PER REGION (都道府県 / 法務局):
  1. robots.txt verify (HONOR)
  2. sitemap.xml fetch → URL list
  3. URL filter (gap keyword, ex: "建設業許可", "就業規則", "商業登記")
  4. Playwright headless walk (visible UA = AutonoMath/0.3.5 jpcite-etl)
  5. 1 req / 3 sec rate limit per source host
  6. PDF DL → S3 staging (mock-only / DRY_RUN gate)
  7. metadata extract → SQLite staging table
  8. AGENT_LEDGER append-only row
  9. ScheduleWakeup +24h
```

### 2.3 fan-out staging schema

```sql
CREATE TABLE etl_g3_g4_g5_staging (
  cohort_id     TEXT NOT NULL CHECK(cohort_id IN ('G3','G4','G5')),
  gap_id        TEXT NOT NULL,  -- 'G3-1' .. 'G5-10'
  region_kind   TEXT NOT NULL,  -- 'pref'|'houmukyoku'|'rōdōkyoku'|'nenkin'|'rōkisho'|'hellowork'|'kōan'
  region_code   TEXT NOT NULL,  -- 47 都道府県 JIS X 0401 or houmukyoku code
  source_url    TEXT NOT NULL,
  source_pdf    TEXT,
  fetched_at    TEXT NOT NULL,
  http_status   INTEGER,
  robots_check  TEXT,
  textract_jid  TEXT,  -- mock JID until UNLOCK
  staging_path  TEXT,
  notes         TEXT,
  PRIMARY KEY (cohort_id, gap_id, region_kind, region_code)
);
```

---

## Section 3: 12 国一次資料 sequencing

国一次資料 = fan-out 不要、単一 URL 配下で完結。優先度高 (depth-of-citation 順)。

| Order | Source ministry | Gap items | URL root | 推定 PDF 数 | 推定 Textract pages |
|---:|---|---|---|---:|---:|
| 1 | 厚労省 (G5-1 / G5-2 / G5-6 / G5-7 / G5-10) | 5 G5 + G3-9 食衛 | https://www.mhlw.go.jp/ | 280 | 4,200 |
| 2 | 法務省 民事局 (G4-1 / G4-2 / G4-3 / G4-5 / G4-9) | 5 G4 | https://houmukyoku.moj.go.jp/ | 220 | 3,300 |
| 3 | 国交省 不動産・建設経済局 (G3-1) | 1 G3 + G4-7 | https://www.mlit.go.jp/totikensangyo/const/ | 120 | 1,800 |
| 4 | 環境省 (G3-4) | 1 G3 | https://www.env.go.jp/recycle/ | 80 | 1,200 |
| 5 | 警察庁 (G3-3 / G3-8) | 2 G3 | https://www.npa.go.jp/policies/application/license_kobutsu/ | 60 | 600 |
| 6 | 出入国在留管理庁 (G3-7) | 1 G3 | https://www.moj.go.jp/isa/ | 90 | 1,800 |
| 7 | 経産省 (G3-10 / G4-6 / G4-10) | 3 cross | https://www.meti.go.jp/ | 110 | 1,400 |
| 8 | 公証人連合会 (G4-4) | 1 G4 | https://www.koshonin.gr.jp/ | 30 | 250 |
| 9 | 日本年金機構 (G5-4) | 1 G5 | https://www.nenkin.go.jp/service/kounen/ | 50 | 600 |
| 10 | ハローワーク (G5-3) | 1 G5 | https://www.hellowork.mhlw.go.jp/ | 40 | 400 |
| 11 | JEED (G5-9) | 1 G5 | https://www.jeed.go.jp/ | 35 | 350 |
| 12 | 中小機構 J-Net21 (G3-5 / G3-10 partial) | 1 G3 cross | https://j-net21.smrj.go.jp/ | 25 | 200 |

**国一次資料 合計**: PDF ~1,140 / Textract pages ~16,100 / 推定 OCR cost = 16,100 × $0.05/page = **$805 (本体)** + S3 + Step Functions = **$900-1,200**。

**Sequencing 推奨**: 1 → 2 → 3 (主軸 cohort weight) → 4-12 (depth)。1+2 で 18 国 PDF / 7,500 pages = **$375 (Textract) + Lambda + S3 = ~$450** で G4 + G5 主軸ガード完了、ROI 上位。

---

## Section 4: AWS burn estimate × 3 cohort

### 4.1 単価前提

| 項目 | 単価 | 出典 |
|---|---|---|
| Textract Async DetectDocumentText | $0.0015 / page | AWS Textract 公式 (analyze より安価) |
| Textract Async AnalyzeDocument (Tables) | $0.05 / page | AWS Textract 公式 (form/table 抽出時) |
| Lambda (Python 1024MB, 30s avg) | $0.0000167 / GB-s = $0.000501 / call | AWS Lambda 公式 |
| S3 Standard | $0.025 / GB-mo (Asia Pacific Tokyo) | AWS S3 公式 |
| Step Functions (Standard) | $0.025 / 1,000 state transitions | AWS SFN 公式 |
| Glue Table (storage only) | $0 (Athena query 課金別) | AWS Glue 公式 |
| Playwright crawl (local, no AWS) | $0 | local container, no AWS spend |

### 4.2 burn estimate per cohort

| Cohort | Crawl AWS cost | Textract pages | Textract cost (Tables想定) | Lambda + S3 + SFN | **合計推定** |
|---|---:|---:|---:|---:|---:|
| G3 行政書士 | $0 (local Playwright) | ~7,800 pages (228h × 34 pages/h ratio) | $390 (Tables) or $11.7 (Text only) | ~$120 (Lambda + S3 + SFN) | **$510 (Tables) / $130 (Text only)** |
| G4 司法書士 | $0 (local Playwright) | ~6,600 pages | $330 (Tables) or $9.9 (Text only) | ~$100 (Lambda + S3 + SFN) | **$430 (Tables) / $110 (Text only)** |
| G5 社労士 | $0 (local Playwright) | ~7,200 pages | $360 (Tables) or $10.8 (Text only) | ~$110 (Lambda + S3 + SFN) | **$470 (Tables) / $120 (Text only)** |
| **3 cohort 合計** | **$0** | **~21,600 pages** | **$1,080 (Tables) / $32.4 (Text only)** | **$330** | **$1,410 (Tables) / $360 (Text only)** |

**注記**:
- CL30 task brief の「$8K-13K」推定は **Tables OCR + Playwright 並列 g4dn fan-out + retry inflation 倍数前提** の上限見積、保守想定。
- 実 wet-run 時の **Text-only Textract** で済むなら **$360 で 3 cohort 全件可能**。
- 残 canary budget は §5.2 で operator 確認、wet-run UNLOCK gate 必須。

### 4.3 hard-stop guard (既 5-line defense 適用)

CL30 ETL も既存 AWS canary hard-stop 5-line defense (memory: `feedback_aws_canary_hard_stop_5_line_defense`) を継承。

```
Line 1: CW alarm $14K → SNS warn
Line 2: Budget $17K → action group throttle
Line 3: $18.3K → slowdown (interval 2x)
Line 4: $18.7K Lambda kill switch
Line 5: $18.9K SCP deny
```

CL30 ETL 起動時 `live_aws_commands_allowed_at_run_time` flag を `operator_token_gate_required` で false 起動、UNLOCK 後でも Phase 9 dryrun (memory: `project_jpcite_canary_phase_9_dryrun`) 経由必須。

---

## Section 5: Operator decision (yes / no per cohort)

> **本セクションは operator が「今 dispatch / next session」二択を最短で出すための decision matrix**。Section 1-4 は read-only audit、本セクション only 反映で wave 進行可能。

### 5.1 cohort 単位 GO / HOLD decision

| Cohort | scaffold landed | gap matrix landed | manifest 必要 | Textract 必要 | wet-run UNLOCK 必要 | **operator decision** |
|---|:---:|:---:|---|---|---|---|
| **G3 行政書士** | yes (10 yaml) | yes (`JPCITE_COHORT_GAP_GYOUSEI_SHIHOU_SHAROUSHI_2026_05_17.md`) | `data/etl_g3_manifest_2026_05_17.json` 要生成 | 7,800 pages, $11.7-$390 | yes (Phase 9 dryrun → wet) | **[ ] GO 今 dispatch / [ ] HOLD next session** |
| **G4 司法書士** | yes (10 yaml) | yes (同上) | `data/etl_g4_manifest_2026_05_17.json` 要生成 | 6,600 pages, $9.9-$330 | yes (同上) | **[ ] GO 今 dispatch / [ ] HOLD next session** |
| **G5 社労士** | yes (10 yaml) | yes (同上) | `data/etl_g5_manifest_2026_05_17.json` 要生成 | 7,200 pages, $10.8-$360 | yes (同上) | **[ ] GO 今 dispatch / [ ] HOLD next session** |

### 5.2 dispatch 推奨順 (Claude 助言, 最終決定 operator)

1. **G5 社労士** — 8/10 自治体差だが 47 労働局 / 年金事務所 / 労基署 / ハロワ は site structure 標準化高、Playwright 並列効きやすい。`scripts/cron/etl_g5_*_daily.py` × 8 cron entry で **47 日周期 nightly 自走**化最速。
2. **G3 行政書士** — 6/10 自治体差。47 都道府県 + 47 都道府県警 で fan-out 重い (倍 source) が、`scripts/cron/etl_g3_*_daily.py` × 6 で同様に nightly 化可能。Textract Tables 多めの懸念あり。
3. **G4 司法書士** — 4/10 自治体差だが 47 法務局本局 + 250+ 支局 で raw URL 数最多 (~297 endpoint)。site structure standardized だが crawl 期間 297 日 (1 局 / 日) → 2 並列で 150 日。商業登記懈怠の depth 重要だが、急ぎは G5 < G3 < G4。

### 5.3 GO した場合の即時 action

```
1. data/etl_g{3,4,5}_manifest_2026_05_17.json 生成 (G1 NTA / G2 会計士 manifest テンプレ流用)
2. scripts/cron/etl_g{3,4,5}_*_daily.py 18 cron entry 追加 (per fan-out 軸)
3. scripts/etl/playwright_g{3,4,5}_*.py 30 entry (per gap item) — DRY_RUN gate default ON
4. data/jpcite_etl_g3_g4_g5_staging.sqlite 初期化 (§2.3 schema)
5. operator wet-run UNLOCK 後に Phase 9 dryrun → wet 段階移行
6. AGENT_LEDGER append-only row × 30 (gap item 単位)
```

### 5.4 HOLD した場合の queue 化

`docs/_internal/JPCITE_ACTION_QUEUE_*.md` に下記 3 entry 追加 (operator action):

```
- [ ] G3 ETL 30 gap × manifest + cron + playwright [228h, Textract $11.7-$390, wet-run UNLOCK 要]
- [ ] G4 ETL 30 gap × manifest + cron + playwright [194h, Textract $9.9-$330, wet-run UNLOCK 要]
- [ ] G5 ETL 30 gap × manifest + cron + playwright [198h, Textract $10.8-$360, wet-run UNLOCK 要]
```

### 5.5 共通 NO line (3 cohort 共通)

以下は **3 cohort 全て NO 明示**:
- 申請書面そのものの代行生成 → 士業法 §1 / §3 / §2 boundary 越境、scaffold + URL link only
- aggregator サイト経由 (noukaweb / hojyokin-portal / biz.stayway 等) → aggregator ban 違反、一次資料のみ
- LLM API 直叩き (anthropic / openai / google.generativeai / claude_agent_sdk) → CLAUDE.md §"No Operator-LLM API" 違反
- robots.txt 無視 → robots: HONOR
- rate limit < 1 req / 3 sec → 一次資料 source への過負荷

---

## Section 6: Constraint compliance

- **READ-ONLY**: 既 DB / source code / 30 scaffold yaml への書込変更なし、本ドキュメントのみ追加。
- **[lane:solo]**: 並列 agent 競合なし、現セッション単独、`docs/_internal/G3_G4_G5_ETL_ROADMAP_2026_05_17.md` は CodeX worktrees に既存ファイルなし確認済 (collision-free)。
- **safe_commit**: 次工程で `scripts/safe_commit.sh -m "..."` 経由 commit + push、NO --no-verify。
- **NO LLM**: 本ドキュメントは machine-generated outline、`anthropic/openai/google.generativeai/claude_agent_sdk` import なし、`src/` 配下に影響なし。
- **aggregator ban**: 一次資料 URL は全て 国 (法務省 / 厚労省 / 経産省 / 警察庁 / 環境省 / 国交省 / NPA / JEED / 年金機構 / ハロワ) または 47 都道府県 / 法務局 / 労働局 に限定、二次集約サイトは **0 件**。
- **no LIVE AWS spend**: `live_aws_commands_allowed_at_run_time = operator_token_gate_required` 維持、wet-run UNLOCK 前は mock-only / DRY_RUN gate ON、Phase 9 dryrun 必須。
- **hard-stop 5-line defense**: §4.3 既存 canary 防衛継承、$19,490 hard ceiling 維持。

---

## See also

- `docs/_internal/JPCITE_COHORT_GAP_GYOUSEI_SHIHOU_SHAROUSHI_2026_05_17.md` — 30 gap matrix base (commit `48562dac3`)
- `docs/_internal/JPCITE_COHORT_PERSONAS_2026_05_17.md` — cohort persona SOT
- `docs/_internal/JPCITE_COHORT_GAP_ZEIRISHI_KAIKEISHI_2026_05_17.md` — 隣接 G1 / G2 cohort
- `data/etl_g1_nta_manifest_2026_05_17.json` — G1 NTA 既 manifest (テンプレ)
- `data/etl_g2_manifest_2026_05_17.json` — G2 会計士 既 manifest (テンプレ)
- `data/artifact_templates/{gyousei,shihou,sharoushi}/*.yaml` — 30 scaffold landed
- `scripts/cron/` — cron entry 既存パターン
- `scripts/safe_commit.sh` — commit wrapper
- CLAUDE.md / AGENTS.md — SOT
- memory: `feedback_aws_canary_hard_stop_5_line_defense`, `project_jpcite_canary_phase_9_dryrun`, `feedback_playwright_screenshots`

last_updated: 2026-05-17
