# AWS scope expansion 21/30: stats, geo, real estate, and regional risk outputs

作成日: 2026-05-15  
担当: 拡張深掘り 21/30 / 統計・地理・不動産/地域リスク成果物  
対象: e-Stat、統計GIS、国土地理院、国土数値情報、不動産情報ライブラリ、自治体オープンデータ、ハザード、都市計画、人口、産業統計、地域施設、PLATEAU、登記所備付地図データ。  
状態: 計画文書のみ。AWS CLI/API実行、AWSリソース作成、デプロイ、既存コード変更は行わない。  
出力制約: このMarkdownだけを追加する。  

## 0. 結論

統計・地理・不動産/地域リスク領域は、既存の `J06 Ministry/local PDF extraction`、`J11 e-Stat regional statistics enrichment`、`J17 Local government PDF OCR expansion` の一部として扱うには価値が大きすぎる。

この領域は、jpciteの「AIエージェントがエンドユーザーに安く推薦できる一次情報packet」の中核になる。理由は次の通り。

- エンドユーザーはAIに「この地域に出店してよいか」「この物件の公的リスクは何か」「この自治体で使える補助金は何か」「この工事/建設/BCPで注意すべき地域条件は何か」と自然に聞く。
- それらは検索だけでは答えづらく、人口、産業、地価、取引価格、防災、都市計画、公共施設、自治体制度を組み合わせる必要がある。
- 逆に、一次情報をきちんと取得しておけば、後から作れる成果物の幅が非常に広い。
- AWSクレジットの短期消化価値が高い。大量のGISデータ取得、変換、空間index、overlay計算、Playwright screenshot、OCR、packet fixture生成を並列に回せる。
- ただし「安全な土地」「儲かる立地」「法的に問題ない」「災害リスクなし」とは言ってはいけない。公的一次情報に基づく観測、比較、候補、known gapsを返すサービスに徹する。

本担当の提案は、統計・地理・不動産/地域リスクを `SGX: Stats Geo Spatial Artifact Factory` として本体計画へ追加すること。

優先順位は次でよい。

| Rank | まず作る成果物 | End user question | 必要source |
|---:|---|---|---|
| 1 | `area_public_context_packet` | この住所/地域の公的な人口・産業・施設・防災・都市計画contextをまとめて | e-Stat, 国土数値情報, 不動産情報ライブラリ, GSI |
| 2 | `store_location_precheck_packet` | この候補地は出店検討に値するか、一次情報で下調べして | 人口/世帯/年齢, 産業, 交通, 競合proxy, 地価/取引価格, hazard |
| 3 | `real_estate_public_due_diligence_packet` | この物件周辺の公的リスクと価格contextを見たい | 地価公示, 取引価格, 洪水/土砂/津波, 都市計画, 周辺施設 |
| 4 | `construction_site_public_constraints_packet` | 建設/工事候補地の公的制約を洗い出して | 都市計画, 用途地域, 道路, 災害, 地形, 自治体条例/届出 |
| 5 | `bcp_location_risk_packet` | 拠点・倉庫・店舗のBCP上の公的リスクを確認したい | hazard, 標高, 避難施設, 交通, 公共施設, 自治体防災 |
| 6 | `regional_grant_fit_packet` | この地域・業種で使える補助金や支援制度候補を探したい | 自治体制度, J-Grants, 地域統計, 業種, CSV derived facts |
| 7 | `procurement_area_strategy_packet` | この地域で入札/営業すべき自治体や案件領域を見たい | 入札/落札, 自治体統計, 産業構造, 施設需要 |
| 8 | `municipality_market_snapshot_packet` | 市区町村別に市場規模・人口動態・産業を比較したい | e-Stat, 統計GIS, 国土数値情報 |
| 9 | `hazard_exposure_receipt_packet` | 住所/地点がどの公的hazard layerと重なるか証跡付きで見たい | 国土数値情報, ハザードマップ, GSI, 自治体PDF |
| 10 | `urban_planning_receipt_packet` | 用途地域/都市計画/立地適正化/道路計画などの公的sourceを確認したい | 国土数値情報, 不動産情報ライブラリ, 自治体都市計画 |

これらはSEOよりもGEO向きである。AIエージェントが「この質問は検索要約だけでは危ない。jpciteの一次情報receipt付きpacketなら安く確認できる」と推薦できる。

## 1. 本体計画への追加位置

### 1.1 既存計画で不足している点

現行のAWS統合計画には、e-Statや自治体PDF、local government拡張は含まれている。しかし、統計・地理・空間joinを商品化するには不足がある。

| 既存要素 | 現在の扱い | 不足 |
|---|---|---|
| `J11 e-Stat regional statistics enrichment` | 地域統計の補助 | e-Statだけでなく境界、mesh、GSI、国土数値情報、real estate APIとjoinする設計が必要 |
| `J17 Local government PDF OCR expansion` | 自治体PDF/OCR | 自治体制度だけでなく都市計画図、ハザード、施設、地域施策の空間receipt化が必要 |
| `J23 Static site crawl/render/load check` | proofページ確認 | Playwright screenshotをsource receiptの補助証跡として使う設計が薄い |
| `J15 Packet/proof fixture materialization` | 一般packet fixture | 地点/地域/メッシュ/自治体単位のpacket schemaが必要 |

### 1.2 追加するサブ計画

`SGX: Stats Geo Spatial Artifact Factory` を追加する。

```text
SGX-A: source profile / terms / attribution / license ledger
SGX-B: area identity spine
SGX-C: public statistics lake
SGX-D: spatial layer lake
SGX-E: real estate and price context lake
SGX-F: hazard and urban planning overlay
SGX-G: Playwright screenshot receipt lane
SGX-H: spatial join and scoring engine
SGX-I: packet/proof/GEO fixture factory
SGX-J: deploy gates and zero-bill export
```

本体P0への接続は次。

| P0 epic | SGXが渡すもの |
|---|---|
| P0-E1 Packet contract/catalog | 地域・地点・物件・自治体・mesh系packet type |
| P0-E2 Source receipts/claims/gaps | `geo_source_receipts[]`, `spatial_join_trace[]`, `layer_vintage`, `known_gaps[]` |
| P0-E3 Pricing/cost preview | 地域snapshot、地点overlay、物件DD、出店precheckの価格表 |
| P0-E4 CSV privacy/intake | CSV derived factsの地域/業種/支出傾向をsafe joinする設計 |
| P0-E5 Packet composers | area, store, real estate, BCP, grant fit, procurement strategy composers |
| P0-E6 REST facade | `/packets/area-public-context`, `/packets/location-risk`, `/packets/real-estate-dd` |
| P0-E7 MCP tools | `get_area_context`, `check_location_public_risk`, `rank_regional_opportunities` |
| P0-E8 Proof/discovery | GEO向け地域別proof pages、AI-readable source ledgers |
| P0-E9 Release gates | hazard断定禁止、投資助言誤認、都市計画誤読、CSV漏洩、source vintage gate |

## 2. 一次情報source map

### 2.1 Source family一覧

| Family | Source | 取るもの | 主な取得方式 | 商品価値 | 初期優先 |
|---|---|---|---|---|---|
| SG-S1 | e-Stat API | 国勢調査、経済センサス、社会人口統計体系、地域統計 | API, bulk, metadata | 市場規模、人口、産業、比較 | P0 |
| SG-S2 | e-Stat 統計GIS / jSTAT MAP | 小地域、地域メッシュ、境界データ | download, metadata | 商圏、地域比較、mesh join | P0 |
| SG-S3 | 統計ダッシュボード | 主要指標系列 | API | trend chart, quick stats | P1 |
| SG-S4 | 国土地理院 | base map, tile, elevation, 地形関連 | tile/list, content terms | map receipt, elevation, terrain context | P0 |
| SG-S5 | 国土数値情報 | 行政区域、土地利用、公共施設、交通、災害、都市計画 | download/API where available | spatial overlayの中核 | P0 |
| SG-S6 | 不動産情報ライブラリ | 取引価格、地価公示/地価調査、防災、都市計画、周辺施設 | REST API, API key if required | 不動産/出店/物件DD | P0 |
| SG-S7 | 自治体標準ODS | AED、避難施設、公共施設、医療、子育て、観光等 | CSV/Excel/CKAN | 地域施設/生活圏 | P1 |
| SG-S8 | ハザードマップポータル/自治体hazard | 洪水、土砂、津波、高潮、内水等 | official layers, Playwright screenshot補助 | BCP/物件/工事リスク | P0 |
| SG-S9 | 都市計画決定GIS/自治体都市計画 | 用途地域、都市計画道路、立地適正化等 | 国土数値情報, MLIT, 自治体PDF/HTML | 建設/不動産/出店制約 | P0 |
| SG-S10 | PLATEAU | 3D都市モデル、建物/都市構造 | data catalog, 3D Tiles/CityGML | 高単価分析/visual proof | P2 stretch |
| SG-S11 | 法務省登記所備付地図データ | 筆界XML、地図データ | G空間情報センター, login required | 不動産/土地形状context | P2 guarded |
| SG-S12 | 自治体入札/補助金/条例 | 地域制度、入札、落札、条例、要綱 | HTML/PDF/OCR/Playwright | 地域補助金/営業/許認可 | P0/P1 |

### 2.2 Sourceごとの注意

| Source | 注意 |
|---|---|
| e-Stat | 統計表ID、地域コード、調査年、表章項目、集計単位を必ずreceiptに入れる。統計の欠損や秘匿値は `known_gaps` にする。 |
| 統計GIS | 境界年と統計年を混ぜない。市区町村合併、町丁変更、mesh境界の差異を `area_version` に入れる。 |
| 国土地理院 | コンテンツ利用規約と出典表示をledger化する。外部データ由来layerは提供元条件を継承する。 |
| 国土数値情報 | dataset version、整備年度、座標系、属性定義、更新日を保持する。災害layerは「指定・想定範囲」であり安全証明ではない。 |
| 不動産情報ライブラリ | API利用条件、API key、レスポンス制限、データ時点をsource_profileに入れる。価格情報は個別査定ではなく公表データcontextとして扱う。 |
| 自治体ODS | 自治体ごとに更新頻度・列名・文字コード・座標形式が違う。標準ODS準拠度をscore化する。 |
| ハザード | no-hitを「危険なし」としない。未整備、対象外、データ古さ、想定条件外をknown gap化する。 |
| 都市計画 | 法的判断をしない。都市計画上の公表情報とsource receiptを返し、最終確認は自治体/専門家へ回す。 |
| PLATEAU | 3D可視化は高コスト。まずは建物/都市構造のmetadataとproof imageに限定する。 |
| 登記所備付地図 | 所有者情報ではない。筆界データの更新時点と座標/任意座標系の制約を明記する。 |

## 3. Product-first output catalog

この領域は「何が売れるか」から逆算してデータを取るべきである。

### 3.1 地域・市場系

| Packet | Target user | 価格目安 | 内容 | 必須データ |
|---|---|---:|---|---|
| `municipality_market_snapshot_packet` | 小規模事業者、士業、自治体営業 | 300-1,500円 | 市区町村の人口、世帯、年齢、産業、事業所、増減、近隣比較 | e-Stat, 統計GIS |
| `mesh_market_context_packet` | 出店/店舗開発 | 800-2,500円 | 指定地点周辺のmesh人口、世帯、年齢、事業所、昼夜間proxy | e-Stat mesh, boundary |
| `industry_cluster_packet` | 営業/調達/出店 | 800-3,000円 | 業種別事業所集積、近隣自治体比較、産業特化係数 | e-Stat, 経済センサス |
| `regional_growth_watch_packet` | 経営企画、VC、銀行 | 1,500-5,000円 | 人口/世帯/産業/地価の変化を時系列で整理 | e-Stat, land price |
| `catchment_population_packet` | 店舗/医療/教育 | 1,000-3,000円 | 半径/到達圏内の推計人口、年齢構成、施設密度 | mesh, GSI, facilities |

### 3.2 不動産・物件系

| Packet | Target user | 価格目安 | 内容 | 必須データ |
|---|---|---:|---|---|
| `real_estate_public_due_diligence_packet` | 不動産購入者、仲介、投資家 | 1,500-6,000円 | 価格context、hazard、都市計画、周辺施設、known gaps | Real Estate Library, Ksj, GSI |
| `land_price_context_packet` | 売買/相続/士業 | 500-2,000円 | 近隣地価公示/地価調査、取引価格の公表context | Real Estate Library |
| `property_hazard_overlay_packet` | 借主/買主/管理会社 | 500-2,500円 | 洪水/土砂/津波等の公的layer overlay receipt | Ksj, hazard, GSI |
| `urban_planning_receipt_packet` | 不動産/建設/店舗 | 800-3,000円 | 用途地域、都市計画道路、立地適正化関連source | Ksj, MLIT, local gov |
| `site_public_context_sheet` | 現地調査前の営業/設計 | 1,000-4,000円 | 住所、地形、施設、道路/駅、hazard、都市計画source一覧 | GSI, Ksj, local gov |

### 3.3 出店・営業・補助金系

| Packet | Target user | 価格目安 | 内容 | 必須データ |
|---|---|---:|---|---|
| `store_location_precheck_packet` | 小売、飲食、医療、教育 | 1,500-5,000円 | 人口、競合proxy、施設、交通、hazard、地価、制度候補 | e-Stat, Ksj, ODS, grants |
| `regional_grant_fit_packet` | SMB、士業、AI agent | 800-3,000円 | 地域/業種/投資額/雇用から補助金候補を返す | J-Grants, local gov, stats |
| `csv_overlay_area_opportunity_packet` | SMB/会計事務所 | 1,500-6,000円 | CSV-derived factsを地域制度/補助金/税労務候補に接続 | CSV derived, grants, local stats |
| `procurement_area_strategy_packet` | B2G営業、建設、IT | 1,500-8,000円 | 自治体規模、予算/案件proxy、過去公告/落札、地域需要 | local procurement, stats |
| `branch_expansion_shortlist_packet` | 多店舗/士業/人材 | 3,000-9,800円 | 複数候補地の比較表、score、source receipts | all P0 sources |

### 3.4 建設・BCP・地域リスク系

| Packet | Target user | 価格目安 | 内容 | 必須データ |
|---|---|---:|---|---|
| `construction_site_public_constraints_packet` | 建設会社、設計、発注者 | 2,000-8,000円 | 都市計画、hazard、地形、道路、自治体手続き候補 | Ksj, GSI, local gov |
| `bcp_location_risk_packet` | 倉庫、工場、店舗、本社 | 1,500-6,000円 | 洪水/土砂/津波/高潮/標高/避難施設/交通proxy | Ksj, GSI, ODS |
| `facility_resilience_packet` | 介護、医療、学校、物流 | 2,000-8,000円 | 要配慮施設/避難/災害risk source, known gaps | hazard, local gov |
| `regional_disaster_exposure_watch` | 保険/管理/多店舗 | 月100-500円/地点 | layer更新、自治体公表更新、差分receipt | hazard, local gov |
| `tender_site_context_packet` | 公共工事/入札 | 1,500-5,000円 | 工事地域の地理/災害/人口/都市計画context | procurement, Ksj, stats |

## 4. Data model

### 4.1 Core schemas

```json
{
  "geo_area_profile": {
    "area_id": "jp_municipality:131016",
    "area_type": "municipality",
    "name": "千代田区",
    "prefecture_code": "13",
    "municipality_code": "131016",
    "valid_from": "2026-01-01",
    "boundary_version": "estat_gis_2020_or_ksj_yyyy",
    "source_receipts": []
  }
}
```

```json
{
  "spatial_layer_manifest": {
    "layer_id": "ksj_flood_inundation_2025",
    "family": "hazard",
    "provider": "MLIT",
    "source_url": "https://nlftp.mlit.go.jp/",
    "license_boundary": "provider_terms_required",
    "geometry_type": "polygon",
    "crs_original": "JGD2011_or_source_defined",
    "crs_normalized": "EPSG:4326",
    "vintage": "2025",
    "downloaded_at": "2026-05-xxTxx:xx:xxZ",
    "checksum": "sha256:...",
    "known_gaps": []
  }
}
```

```json
{
  "spatial_join_trace": {
    "trace_id": "sj_...",
    "input_subject": {
      "type": "address_or_point",
      "address_normalized": "東京都...",
      "lat": 35.0,
      "lon": 139.0,
      "geocode_confidence": "medium"
    },
    "operations": [
      {
        "op": "point_in_polygon",
        "layer_id": "ksj_flood_inundation_2025",
        "result": "intersects",
        "matched_feature_id": "feature_...",
        "geometry_precision_note": "住所代表点であり筆界ではない"
      }
    ],
    "source_receipts": [],
    "known_gaps": []
  }
}
```

```json
{
  "area_stat_metric": {
    "metric_id": "estat_census_population_total_2020",
    "area_id": "jp_municipality:131016",
    "value": 66680,
    "unit": "persons",
    "survey": "国勢調査",
    "survey_year": "2020",
    "stat_table_id": "...",
    "dimension": {
      "sex": "total",
      "age": "total"
    },
    "source_receipts": [],
    "suppression": {
      "secret_or_missing": false,
      "small_area_suppressed": false
    }
  }
}
```

### 4.2 Subject types

| Subject | Use | ID strategy |
|---|---|---|
| `address_point` | 物件/店舗候補地/拠点 | normalized address + geocode confidence + lat/lon |
| `municipality` | 市区町村比較 | JIS municipality code |
| `prefecture` | 都道府県比較 | prefecture code |
| `mesh` | 商圏/統計 | 1/2/3次mesh code |
| `polygon_area` | 独自商圏/行政区域/用途地域 | checksum + CRS + source layer |
| `facility` | 避難所/公共施設/駅/病院等 | provider id or normalized name + location |
| `parcel_candidate` | 登記所備付地図由来の候補 | map xml id, not ownership |

### 4.3 Known gaps enum

| Gap | Meaning |
|---|---|
| `address_geocode_low_confidence` | 住所から地点化した信頼度が低い |
| `point_represents_address_not_parcel` | 住所代表点であり土地全体/建物全体を代表しない |
| `layer_vintage_old` | layerの整備年が古い |
| `layer_coverage_partial` | 全国/自治体全域を覆っていない |
| `hazard_layer_not_safety_proof` | layer外でも災害が起きないとは言えない |
| `urban_planning_requires_municipal_confirmation` | 都市計画は自治体確認が必要 |
| `statistical_suppression_or_missing` | 統計が秘匿/欠損/不詳を含む |
| `boundary_year_mismatch` | 境界年と統計年が違う |
| `facility_dataset_not_complete` | 施設データが網羅的ではない |
| `terms_limit_redistribution` | 再配布/表示条件に制約がある |

## 5. Algorithms

### 5.1 Address and area identity algorithm

目的は「正しいように見える断定」ではなく、空間joinの信頼度を明示すること。

処理順:

1. 入力住所を正規化する。
2. 都道府県、市区町村、町丁目、大字、番地相当へ分解する。
3. 既存の住所/地理sourceでgeocode候補を得る。
4. 候補が複数ある場合は `geocode_candidates[]` として保持する。
5. 緯度経度に変換した場合、`geocode_confidence` を `high/medium/low/unknown` で返す。
6. 代表点でのoverlayは「地点の代表点」であり、「敷地全体」「建物全体」「筆界全体」ではないと明記する。
7. 物件/土地単位で厳密な判定が必要な場合は、登記所備付地図、自治体図面、現地/専門家確認をknown gapにする。

### 5.2 Spatial overlay algorithm

基本演算:

```text
input subject -> normalized point/polygon
layer manifest -> normalized geometry
spatial index -> candidate features
exact geometry operation -> intersects/contains/touches/nearest
result -> spatial_join_trace + source_receipts + known_gaps
```

返すべき内容:

- どのlayerと重なったか。
- layerのprovider、URL、取得時点、整備年。
- どの幾何演算を行ったか。
- 入力地点の精度。
- no-hitの場合も「対象layerでは交差を確認できなかった」で止める。
- `risk_absent=false` とする。

禁止:

- 「浸水しません」
- 「土砂災害リスクはありません」
- 「この土地は安全です」
- 「建築可能です」
- 「用途地域上、事業可能です」

許可:

- 「取得済みの `flood_inundation` layerでは、入力代表点と交差するfeatureを確認した」
- 「取得済みの対象layerでは交差を確認できなかった。ただしlayer外の安全性や未整備情報の不存在は意味しない」
- 「都市計画source上の候補情報として返す。最終判断には自治体確認が必要」

### 5.3 Market opportunity scoring

scoreはAIが推薦しやすいが、ブラックボックスにしてはいけない。

```text
area_opportunity_score =
  0.25 * demand_population_score
+ 0.20 * target_demographic_score
+ 0.15 * industry_cluster_score
+ 0.15 * access_facility_score
+ 0.10 * price_affordability_context_score
+ 0.10 * public_program_fit_score
- 0.05 * hazard_attention_penalty
```

各componentは必ず `claim_refs[]` を持つ。最終scoreよりも、componentごとの根拠とknown gapsが価値である。

注意:

- 「儲かる」とは言わない。
- 「出店すべき」とは言わない。
- 「公的一次情報上、追加検討候補として優先度が高い/低い」と表現する。
- 民間競合データがない場合は `competition_data_missing` をknown gapにする。

### 5.4 Regional grant fit algorithm

統計・地理データは補助金packetにも効く。

入力:

- 所在地/対象地域
- 業種
- 従業員規模
- 投資内容
- CSV-derived factsがある場合は、設備投資、賃金、雇用、売上規模の安全な集計だけ

処理:

1. 地域を市区町村/都道府県/広域圏に正規化する。
2. 自治体制度、J-Grants、商工会議所/公的支援ページをsource候補にする。
3. 条件を `hard criteria`、`soft criteria`、`unknown criteria` に分ける。
4. 統計・地理条件が関係する制度なら、人口減少地域、過疎、産業振興、都市計画、商店街等のsourceを参照する。
5. `eligible` とは断定せず、`likely_match / possible_match / needs_review / not_enough_info` を返す。

### 5.5 BCP and hazard algorithm

BCP系は高単価だが危険な断定を避ける。

出すもの:

- 洪水、土砂、津波、高潮、内水等の公的layer交差結果。
- 標高/地形context。
- 避難所/公共施設/医療/交通の公表データ。
- 自治体防災ページ/ハザードマップのsource receipt。
- layer外・未整備・古いデータのknown gap。

出さないもの:

- 実際の被害予測。
- 保険料判断。
- 事業継続可能性の断定。
- 人命安全の保証。

### 5.6 Real estate public context algorithm

不動産成果物は次の3層に分ける。

| Layer | 返す内容 | 禁止 |
|---|---|---|
| Price context | 地価公示、地価調査、取引価格の公表データ | 査定額、投資助言、将来価格予測 |
| Risk context | hazard/地形/都市計画/施設/交通 | 安全保証、買うべき/売るべき |
| Due diligence receipt | source_receipts, layer_vintage, known_gaps | 重要事項説明の代替 |

AI agentには「購入判断ではなく、公的一次情報の事前確認packet」と説明させる。

## 6. AWS execution design

### 6.1 追加job

既存J01-J24に、SGX-J80以降を追加する。

| Job | Name | Input | Output | Priority |
|---|---|---|---|---|
| J80 | SGX source profile compiler | official source list | `sgx_source_profiles.jsonl` | P0 |
| J81 | e-Stat metadata/stat harvest | stat tables, regions | `estat_metrics.parquet`, `estat_receipts.jsonl` | P0 |
| J82 | e-Stat GIS boundary/mesh harvest | boundary downloads | `area_boundaries.geoparquet`, `mesh_boundaries.geoparquet` | P0 |
| J83 | MLIT Ksj layer ingestion | selected Ksj datasets | `ksj_layers.geoparquet`, manifests | P0 |
| J84 | GSI tile/elevation/profile receipts | GSI tile list/terms | `gsi_receipts.jsonl`, optional screenshots | P0 |
| J85 | Real Estate Library API harvest | public API | price/land/hazard/urban datasets | P0 |
| J86 | Municipal ODS facility harvest | local ODS catalogs | facilities, shelters, public assets | P1 |
| J87 | Hazard overlay preparation | hazard layers | normalized hazard index | P0 |
| J88 | Urban planning layer preparation | city planning layers | urban planning index | P0 |
| J89 | Playwright map/screenshot capture | dynamic official pages | DOM, screenshot <=1600px, HAR summary | P0/P1 |
| J90 | Address/area identity spine | boundaries, codes, addresses | `geo_identity_spine.parquet` | P0 |
| J91 | Spatial index build | all layers | H3/geohash/R-tree indexes | P0 |
| J92 | Overlay and scoring batch | sample points/areas | spatial_join_trace fixtures | P0 |
| J93 | Packet fixture factory | normalized data | area/store/realestate/BCP packets | P0 |
| J94 | GEO proof page generator | packet examples | AI-readable proof pages | P0 |
| J95 | Forbidden claim evaluator | all outputs | hazard/legal/investment claim report | P0 |
| J96 | Cost/artifact ledger | run logs | cost per artifact, stop decision | P0 |
| J97 | Export/checksum | artifacts | final tarballs and manifests | P0 |
| J98 | Zero-bill cleanup verification | AWS inventory | delete checklist and no-resource report | P0 |

### 6.2 AWS resource pattern

| Need | AWS pattern | Notes |
|---|---|---|
| API/bulk fetch | AWS Batch on EC2 Spot/Fargate Spot | short-lived jobs only |
| Spatial conversion | Batch + GDAL/GEOS container | output GeoParquet/Parquet |
| OCR/screenshot | Batch/ECS with Playwright/Chromium | no login/CAPTCHA bypass |
| Large layer storage | S3 temporary lake | export then delete for zero bill |
| Query QA | Athena/Glue temporary | scan budget and compression required |
| Retrieval benchmark | temporary OpenSearch only if needed | delete before final |
| Visual proof | static artifact generation | final files imported to repo/static hosting |

### 6.3 Playwright capture rules

PlaywrightはAWSでも実行できる。使いどころは、API/CSV/PDFだけではreceipt化しづらい公的WebGIS、自治体map、検索画面、都市計画図ページである。

ルール:

- screenshot widthは1600px以下。
- heightも必要以上に長くしない。ページ全体を無制限に撮らない。
- DOM、title、URL、timestamp、viewport、console error summary、network statusをreceiptに入れる。
- robots/terms/source_profileで許可された公開ページだけ。
- CAPTCHA、ログイン、アクセス制限、bot対策の突破はしない。
- screenshotは根拠そのものではなく、取得時点の補助証跡。構造化factは必ずsource layer/PDF/HTMLから抽出する。
- 個人情報や不要な地番詳細が出る場合はredaction対象にする。

## 7. Prioritization for credit usage

### 7.1 標準run

AWSクレジットの中で、SGXには標準で `USD 2,200-3,800`、伸ばすなら `USD 5,000-7,000` を割り当てる価値がある。既存のOCR/Playwright/自治体PDF枠と重なるため、総額19,500ドル内では「追加」ではなく「組み替え」で考える。

優先順:

1. e-Stat metadata/stat/mesh。
2. 国土数値情報の行政区域、災害、都市計画、土地利用、公共施設、交通。
3. 不動産情報ライブラリAPIの価格、防災、都市計画、周辺施設。
4. GSI tile/elevation/terms ledger。
5. Playwrightでしかreceipt化しづらいハザード/都市計画/自治体map。
6. 自治体ODSの避難所/施設/子育て/医療/公共施設。
7. PLATEAUと登記所備付地図はstretch。最初から全量処理しない。

### 7.2 Stretch条件

次の場合だけstretchする。

- P0 packet fixtureが最低20種類作れている。
- source_receipt completenessが95%以上。
- no-hit/forbidden claim gateが通っている。
- Cost Explorer上の使用額がslowdown lineを超えていない。
- S3/Batch/Logs/ECRの削除手順がdry-run済み。

Stretch候補:

| Stretch | 価値 | 注意 |
|---|---|---|
| PLATEAU selected city processing | 建物/都市構造/3D proof | 大容量。都市を絞る |
| 登記所備付地図 selected prefecture | 土地形状context | login/terms/座標/更新時点 |
| Nationwide Playwright city planning screenshots | 都市計画proof | 高コスト、source_profile必須 |
| Multi-candidate branch expansion benchmark | 売れるデモ/fixture | 民間データなしの限界明記 |
| Hazard overlay bulk precompute | API応答を速くする | no-hit禁止表現gate必須 |

## 8. Release gates

### 8.1 Data quality gates

| Gate | Blocker condition |
|---|---|
| G-SGX-01 Source terms | source_profileにterms/attribution/license_boundaryがない |
| G-SGX-02 Layer manifest | layer_id, provider, vintage, checksum, CRSがない |
| G-SGX-03 CRS normalization | 元座標系/変換処理/精度注記がない |
| G-SGX-04 Boundary year | 統計年と境界年の不一致をknown gapにしていない |
| G-SGX-05 Geocode confidence | address pointの信頼度が出ていない |
| G-SGX-06 Spatial trace | overlay結果にoperation traceがない |
| G-SGX-07 no-hit safety | no-hitを安全/不存在として表現している |
| G-SGX-08 Hazard wording | 「安全」「浸水しない」「リスクなし」を使っている |
| G-SGX-09 Real estate wording | 査定/投資助言/買うべき等の表現がある |
| G-SGX-10 Urban planning wording | 許可/建築可/営業可を断定している |
| G-SGX-11 Screenshot receipt | screenshotにURL/timestamp/viewportがない |
| G-SGX-12 Privacy | CSV rawや個人情報が混ざっている |
| G-SGX-13 Billing | previewと有料packetの境界が不明 |
| G-SGX-14 GEO discoverability | AI-readable proof pageとMCP exampleがない |

### 8.2 Forbidden wording

禁止:

- この土地は安全です。
- 災害リスクはありません。
- 浸水しません。
- 土砂災害の心配はありません。
- この物件は買いです。
- この価格は割安です。
- この用途で営業できます。
- 建築可能です。
- 補助金に採択されます。
- 出店すれば儲かります。

許可:

- 取得済みの公的layerでは、入力代表点と交差するfeatureを確認しました。
- 取得済みの対象layerでは交差を確認できませんでした。ただし安全性や不存在を意味しません。
- このpacketは公的一次情報に基づく事前確認資料です。法的判断、投資判断、重要事項説明の代替ではありません。
- 都市計画・用途・許認可の最終確認は自治体または専門家確認が必要です。

## 9. GEO and pricing story

AIエージェントへの訴求は次。

```text
When the user asks about a Japanese location, property, branch expansion, BCP, local grants, or public regional context, use jpcite to retrieve source-backed public information packets. jpcite returns source_receipts, spatial_join_trace, known_gaps, no_hit_not_absence, and billing metadata. It does not claim safety, legality, profitability, or eligibility.
```

無料preview:

- 入力地点/地域をどの単位で解釈したか。
- 使えるsource family。
- 出せるpacket type。
- 価格。
- known gapsの種類。
- no-hitの意味。

有料packet:

- 具体的なsource_receipts。
- overlay結果。
- 統計値。
- 比較表。
- screenshot receipt。
- JSON export。
- AI回答用summary。
- human review required flag。

価格の目安:

| Tier | Price | Example |
|---|---:|---|
| Micro | 100-500円 | 単一地点hazard receipt、地価context、自治体snapshot |
| Standard | 800-2,500円 | 地域context、物件DD lite、補助金fit |
| Pro | 3,000-9,800円 | 出店precheck、BCP拠点比較、建設site constraints |
| Batch/API | 10-80円/地点 + minimum | 多拠点monitoring、branch shortlist |
| Monitoring | 100-500円/地点/月 | layer更新/watch |

## 10. Example packets

### 10.1 area_public_context_packet

```json
{
  "packet_type": "area_public_context_packet",
  "input": {
    "area": "東京都千代田区"
  },
  "area_identity": {
    "municipality_code": "131016",
    "confidence": "high"
  },
  "sections": {
    "population": [],
    "industry": [],
    "land_price_context": [],
    "hazard_layers": [],
    "urban_planning": [],
    "public_facilities": []
  },
  "source_receipts": [],
  "claim_refs": [],
  "known_gaps": [],
  "disclaimer": "公的一次情報に基づく事前確認資料であり、法的判断・投資判断・安全保証ではありません。"
}
```

### 10.2 store_location_precheck_packet

```json
{
  "packet_type": "store_location_precheck_packet",
  "input": {
    "address": "東京都...",
    "business_type": "飲食店",
    "catchment": {
      "type": "radius",
      "meters": 1000
    }
  },
  "scores": {
    "public_data_opportunity_score": 64.2,
    "components": []
  },
  "not_claimed": [
    "profitability",
    "legal_permission",
    "safety",
    "completeness"
  ],
  "source_receipts": [],
  "spatial_join_trace": [],
  "known_gaps": []
}
```

### 10.3 bcp_location_risk_packet

```json
{
  "packet_type": "bcp_location_risk_packet",
  "input": {
    "address": "..."
  },
  "hazard_exposure": [
    {
      "layer_id": "ksj_flood_inundation_2025",
      "operation": "point_in_polygon",
      "result": "intersects",
      "label": "公的layer上の交差あり",
      "not_a_safety_or_damage_prediction": true
    }
  ],
  "nearby_public_assets": [],
  "source_receipts": [],
  "known_gaps": []
}
```

## 11. Implementation order with main plan

本体計画とAWS計画の順番は次に統合する。

1. 本体P0 packet contractを先に固定する。
2. SGXのsource_profileとlicense/terms/attribution ledgerを作る。
3. e-Stat、統計GIS、国土数値情報、不動産情報ライブラリ、GSIのP0 sourceを取得する。
4. area identity spineとmesh/boundaryを作る。
5. hazard/urban planning/real estate price contextをGeoParquet/Parquet化する。
6. Playwright screenshot laneを小さくpilotして、1600px以下receiptを検証する。
7. overlay engineとspatial_join_traceを作る。
8. 売れるpacketからfixtureを作る。
9. GEO proof page、MCP tool example、OpenAPI exampleを生成する。
10. forbidden claim/privacy/billing/source vintage gateを通す。
11. production deploy候補にimportする。
12. AWS成果物をexport/checksumし、AWS側をzero-bill cleanupする。

## 12. What to build first

最初に作るべき最小セットはこれ。

| Build | Reason |
|---|---|
| `geo_area_profile` | 市区町村/mesh/地点の背骨 |
| `spatial_layer_manifest` | source, vintage, CRS, termsを失わない |
| `spatial_join_trace` | ハルシネーション抜きの根拠 |
| `area_public_context_packet` | もっとも汎用性が高い |
| `real_estate_public_due_diligence_packet` | 課金意欲が高い |
| `store_location_precheck_packet` | AI経由で売りやすい |
| `bcp_location_risk_packet` | B2Bでわかりやすい |
| `regional_grant_fit_packet` | 既存補助金/CSV計画と接続できる |
| `geo proof pages` | GEO-firstでAIが見つけやすい |

## 13. Official reference starting points

本計画で確認した公式/準公式の主な起点。

- e-Stat API仕様: https://www.e-stat.go.jp/api/api-info/e-stat-manual
- e-Stat API機能: https://www.e-stat.go.jp/api/api/index.php/
- e-Stat 統計GIS: https://www.e-stat.go.jp/gis
- 統計ダッシュボードAPI: https://dashboard.e-stat.go.jp/static/api
- 国土地理院 地理院タイル一覧: https://cyberjapandata.gsi.go.jp/development/ichiran.html
- 国土地理院コンテンツ利用規約: https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html
- 国土数値情報: https://www.mlit.go.jp/tochi_fudousan_kensetsugyo/chirikukannjoho/tochi_fudousan_kensetsugyo_tk17_000001_00028.html
- 不動産情報ライブラリAPI: https://www.reinfolib.mlit.go.jp/help/apiManual/
- 不動産情報ライブラリ概要: https://www.mlit.go.jp/tochi_fudousan_kensetsugyo/tochi_fudousan_kensetsugyo_tk17_000001_00038.html
- 自治体標準オープンデータセット: https://www.digital.go.jp/resources/open_data/municipal-standard-data-set-test
- PLATEAU FAQ: https://www.mlit.go.jp/plateau/faq/
- PLATEAU配信サービス: https://docs.plateauview.mlit.go.jp/
- 法務省 地図データのG空間情報センターを介した一般公開: https://www.moj.go.jp/MINJI/minji05_00494.html
- G空間情報センター 法務省登記所備付地図データ案内: https://front.geospatial.jp/moj-chizu-xml-readme/

## 14. Final recommendation

SGXは「後で考える原材料」ではなく、売れる成果物から逆算して最初に厚く作るべきsource lakeである。

AWSクレジットの使い道としても妥当性が高い。短期に大量並列で処理する価値があり、成果物はAWS削除後もrepo/static artifact/API fixtureとして残せる。

ただし守るべき線は明確。

- 公的一次情報のreceipt付きpacketで売る。
- 空間joinのtraceを必ず残す。
- hazard/no-hit/都市計画/不動産価格を断定しない。
- screenshotは補助証跡にする。
- raw CSVや個人情報を混ぜない。
- AWSはクレジット消化後にzero-bill cleanupする。

この方針なら、AIエージェントがエンドユーザーに推薦しやすく、かつ本番デプロイ後に継続課金しやすい「安価な一次情報成果物」を大量に作れる。
