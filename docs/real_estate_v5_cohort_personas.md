# Real Estate V5 — 5 Cohort Personas

**目的**: 2026-11-11 launch (T+200d) 前の MCP / API ツール設計と
blog 記事のペルソナ整合チェック。各 persona は **1 cohort = 1 SaaS /
1 ユースケース** を仮定し、**¥3/req metered + zero-touch + organic**
の制約を満たすかを明示する。

> 想定総母数: 不動産業者 約 13 万社 / 一級建築士事務所 約 4 万社 /
> 不動産 SaaS 事業者 約 300 社 / 賃貸管理業 約 5 万社。
> launch+30d で 1 cohort 顧客が 50+ req/day を継続 → 継続 / 未達 → sunset。

---

## 1. 不動産 開発 (デベロッパー)

- **ロール**: 中堅デベロッパー (年間 5-50 棟竣工) の事業企画 / 用地仕入担当。
- **担当範囲**: 用地取得時の zoning 確認、補助制度活用、開発許可申請、
  建築基準法・都市計画法 適合チェック。
- **困りごと**:
  - 用途地域 / 防火地域 / 高度地区 / 景観地区 を市町村ごとに調べると、
    GIS が分散していて 1 案件あたり 3-5 時間かかる。
  - 国交省・都道府県・市町村の住宅整備補助は要件が頻繁に改定され、
    社内データベース更新が追いつかない。
  - 建築基準法 / 都市計画法 改定で過去案件の遡及影響を即答できない。
- **AutonoMath での解像**:
  - `cross_check_zoning(prefecture='東京都', city='港区', district='六本木')`
    で 用途 + 防火 + 高度 を 1 call で重ね合わせ。
  - `search_real_estate_programs(program_kind='subsidy', prefecture='東京都')`
    で開発系補助を一覧。
  - `dd_property_am(canonical_id)` で zoning + 補助 + 法令 + 区域指定を
    1-shot dump。
- **流入想定**: blog 「デベロッパーが用地仕入れ判断を 30 分で固める
  MCP setup」。
- **解像度確認**: ¥3/req × 月 200 call = ¥600。建築士外注 1 案件 ¥300k 比で
  zero-touch 整合。

## 2. 賃貸管理 (PM 業者)

- **ロール**: 賃貸管理業 (1,000-5,000 戸管理) の業務責任者 / 法務担当。
- **担当範囲**: 借地借家法 遵守、賃貸契約改定、原状回復ガイドライン
  運用、空き家活用補助 申請。
- **困りごと**:
  - 借地借家法 / 借地借家法施行令 の改正影響が約款に反映遅延。
    賃借人クレーム発生時に根拠条文を即出せない。
  - 自治体の空き家活用補助 / リフォーム補助 が市町村レベルで分散し、
    複数県管理時に比較できない。
  - 建物区分所有法 の管理組合運営に関する判例追跡が追いつかない。
- **AutonoMath での解像**:
  - `search_real_estate_compliance(law_basis='借地借家法')` で
    関連 enforcement_cases + 判例 を一覧。
  - `search_real_estate_programs(program_kind='subsidy', authority_level='city')`
    で 自治体補助を network 化。
  - `get_zoning_overlay` で物件の zoning を即時参照、賃借人説明資料に直結。
- **流入想定**: blog 「賃貸管理会社が借地借家法改正に
  追従する MCP / Claude setup」。
- **解像度確認**: ¥3/req × 月 300 call = ¥900。判例追跡サービス
  ¥30k/月 比較で 30 倍コスト効率。

## 3. 不動産 M&A (仲介業者 / 不動産仲介)

- **ロール**: 商業不動産 / 工場物件の M&A・売買仲介業者。
- **担当範囲**: 売買時の zoning + 法令 + 補助 + 行政処分歴 due diligence、
  不動産登記法 確認、買主・売主への根拠資料提示。
- **困りごと**:
  - 売買 1 件あたりの DD で zoning / 用途変更可否 / 既存不適格建築の
    判定に 1-2 週間かかる。
  - 不動産登記法 改正 (2024-04 相続登記義務化、以降の段階施行) で
    案件ごとの適用判定がブレる。
  - 売主・買主双方に出す DD レポートの根拠 URL が二次情報だと
    クレーム化する (アグリゲータ依存からの脱却課題)。
- **AutonoMath での解像**:
  - `dd_property_am(canonical_id)` で 1-shot DD レポート (zoning +
    補助 + 法令 + 区域指定 + 行政処分歴) を生成。
  - `search_real_estate_compliance(prefecture=..., property_type_target=...)`
    で同種物件の処分例 / 是正命令履歴を一覧。
  - 出典は全行 一次情報 (国交省 / e-Gov / 法務省 / 自治体) → 顧客提示の
    信頼性が二次情報経由より圧倒的に高い。
- **流入想定**: blog 「商業不動産 M&A の DD を 1 日に短縮する
  AutonoMath setup」。
- **解像度確認**: ¥3/req × 月 500 call = ¥1,500。DD 外注 1 案件 ¥500k
  比較で初年度回収。

## 4. 建築設計事務所

- **ロール**: 一級建築士事務所 (所員 5-30 名) の主任建築士・統括設計者。
- **担当範囲**: 建築確認申請、構造・設備設計、建築基準法・都市計画法
  + 各自治体条例の重ね合わせチェック、確認申請補助制度の活用。
- **困りごと**:
  - 建築基準法 + 各自治体条例 の重ね合わせが市ごとに違い、
    案件着手時のリサーチが反復作業化。
  - 用途地域変更や容積率緩和の特例制度 (総合設計制度等) の最新
    要件を追う工数が大きい。
  - 構造設計の根拠条文を確認申請書に正確引用する際の、改正履歴
    追跡 (建築基準法施行令の改正系譜) が紙ベース。
- **AutonoMath での解像**:
  - `cross_check_zoning(...)` で 用途 + 防火 + 高度 + 景観 を 1 call。
  - `search_real_estate_programs(program_kind='certification')` で
    総合設計 / 認定建築物 / 性能評価制度を一覧。
  - MCP 経由で Claude Sub-agent に `search_real_estate_compliance` を
    与え、自社設計 review に組み込み。
- **流入想定**: blog 「建築設計事務所が確認申請を 1 日短縮する
  MCP / Claude setup」。
- **解像度確認**: ¥3/req × 月 250 call = ¥750。設計補助スタッフ
  人件費 ¥300k/月 比較で 400 倍コスト効率。

## 5. 不動産 SaaS 開発者

- **ロール**: 物件管理 / 仲介支援 / 査定 SaaS の開発者・PdM。
- **担当範囲**: 自社 SaaS に「zoning 自動取得 + 補助制度検索 + 法令
  根拠引用」機能を組み込みたい開発者。
- **困りごと**:
  - 各自治体 GIS / e-Gov XML / 国交省 PDF を自社で parse すると
    工数 6 人月 + 維持費が青天井。商用 license 付きの構造化 API が
    なかった。
  - LLM agent から「建築基準法 第 X 条の根拠を引用」させたいが、
    アグリゲータ (suumo / 不動産流通推進センター 二次配信) URL を
    渡すと信頼性で顧客クレーム化する。
- **AutonoMath での解像**:
  - REST API `/v1/real_estate/programs` (W4 で公開) を SaaS バックエンドに
    プロキシ。出典 URL は一次情報のみ保証。
  - MCP 経由で Claude Sub-agent に `search_real_estate_programs` /
    `get_zoning_overlay` / `dd_property_am` を与え、自社 UI から
    自然言語クエリ。
- **流入想定**: blog 「不動産 SaaS に 1 日で zoning + 補助を組み込む
  (AutonoMath REST + MCP)」。
- **解像度確認**: ¥3/req × エンドユーザ 1,000 call/日 = ¥3,000/日 = ¥90k/月。
  自前構築 6 人月 ¥6M+ 比較で初年度即回収。

---

## 整合チェック (5 personas 横断)

- **¥3/req metered で全 persona ROI 黒字** — tier SKU 不要を再確認。
- **zero-touch 整合** — 5 persona いずれも DPA / Slack Connect / phone を
  必要としない。SaaS 開発者は技術 docs + REST/MCP のみで完結、
  デベロッパー / M&A / 建築士 / PM 業者は一次情報の構造化 API のみで
  業務に組み込める。
- **organic 整合** — 5 persona × blog 1 本 = 計 5 記事で SEO 入口。
  広告 / 営業 / cold outreach なし (memory: `feedback_organic_only_no_ads`)。
- **データ衛生** — 5 persona いずれも一次情報 (国交省 / e-Gov / 法務省 /
  自治体 GIS) を要求。アグリゲータ ban list は強化方向のみ。
- **brand 整合** — 5 persona いずれも AutonoMath ブランドで完結、
  jpintel ブランドはユーザー面に出さない。

## 不採用 persona (記録)

- **個人住宅購入者** (B2C 領域) — zero-touch と整合しない、CS 負荷が
  線形に増える。住宅ローン比較 / 物件選定は対象外。
- **不動産投資家 個人** — 利回り試算は推論領域 (顧客側) で、当方の
  価値は構造化情報配信のみ → 整合しないので除外。
- **海外不動産 投資家** — 法体系が別 (各国の zoning / 登記)、
  日本国内一次情報の射程外。
- **行政書士 / 司法書士 (申請業務)** — 士業独占業務に踏み込む扱い、
  zero-touch ops と整合しない (CS 質問が法的助言に近接する)。
  V6 候補で再評価。
