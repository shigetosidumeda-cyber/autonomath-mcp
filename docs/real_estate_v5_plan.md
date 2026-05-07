# Real Estate V5 — 4 週ローンチ計画

**期間**: 2026-04-25 → 2026-11-11 (T+200d、実働 4 週)
**対象 cohort**: 不動産 開発 (デベロッパー) / 賃貸管理 (PM 業者) /
不動産 M&A (仲介業者) / 建築設計事務所 / 不動産 SaaS 開発者
**Path**: jpcite コア (¥3/billable unit metered) を **不動産・建築・登記**
領域へ拡張する第 5 波 (V3 Healthcare の B5 pattern を踏襲)。
**判定基準**: launch 直後 30d で 50+ paid request / day を 1 件以上の
cohort 顧客から確認できれば **継続**、未達なら sunset。
**ARR uplift 想定**: Y2+ +¥100-200k/月。

---

## なぜ Real Estate V5 か

- jpcite は 2026-05-06 に農業 + SMB 制度 14,472 件で launch、
  2026-08-04 に Healthcare V3 を加える計画 (V3 = B5 pattern の先行例)。
  Real Estate V5 は同じ pattern (schema migration 先行 + ingest plan) を
  4 週圧縮で実行する第 5 波。
- ターゲット 5 cohort は **建築基準法 / 都市計画法 / 不動産登記法 /
  借地借家法 / 建物区分所有法** という 5 本の根拠法で動き、横串の
  SaaS 型情報配信ニーズが可視化済み。zoning は **用途地域 / 防火地域 /
  高度地区 / 景観地区** で SaaS 化されておらず、構造化 API は空白市場。
- 既存 `laws` (9,484 行) / `tax_rulesets` (35 行) と **法令 unified_id 経由**
  で接続するため、追加コストはスキーマと ingest のみ。MCP server は
  ツール 5 本追加。

## 制約

- **Solo + zero-touch** (memory: `feedback_zero_touch_solo`)。
  営業 / DPA / Slack Connect / onboarding call 等の人的介在機能は提案禁止。
- **Anthropic API は呼ばない** (memory: `feedback_autonomath_no_api_use`)。
  推論は顧客側、当方は API/MCP/静的 docs のみ。
- **brand**: jpcite / 運営は Bookyou株式会社 (T8010001213708)。
  jpintel ブランドはユーザー面に出さない。
- **データ衛生**: `source_url` には一次情報 (国交省 / e-Gov / 法務省 /
  自治体 / 都市計画情報) のみ。集約サイト (suumo / homes / athome /
  lifull) は `source_url` ban list に強制登録。

---

## Week 1 — Schema migration prep (今週、完了)

**Done**

- `scripts/migrations/042_real_estate_schema.sql` 追加
  - `real_estate_programs` (program_kind 5 値 enum / property_type_target /
    law_basis / authority_level / amount_max_yen / tier S-A-B-C-X)
  - `zoning_overlays` (zoning_type 7 値 enum / restrictions_json /
    prefecture+city 必須 / district nullable)
  - 4 インデックス: `idx_real_estate_pref_kind` /
    `idx_real_estate_law` / `idx_zoning_pref_city` / `idx_zoning_type`
- `data/jpintel.db` へ migration 適用 + `schema_migrations` 登録済み
- 本ドキュメント + `docs/real_estate_v5_cohort_personas.md` 公開

**Out of scope (W1)**

- `autonomath.db` への `record_kind='real_estate'` 拡張は **収集 CLI 領域**。
  W2 で別 agent / 別 migration が担当する。
- ingest スクリプト本体 (W2 以降)。

## Week 2 — 法令 ingest (建築基準法 / 都市計画法 / 不動産登記法 / 借地借家法 / 建物区分所有法)

- e-Gov 法令 API から **5 法 + 関係政省令 + 施行令・施行規則** を fetch、
  `laws` に追記。目標 ~500 articles。
- `program_law_refs` 経由で 既存 `programs` の不動産系補助金を再リンク。
- `source_lineage_audit` に whitelist (elaws.e-gov.go.jp, mlit.go.jp,
  moj.go.jp, hourei.net 公的 mirror) を追加。
- 集約サイト除外 list を強化 (suumo / homes / athome / lifull /
  rakumachi / 不動産流通推進センター 二次配信)。

**完了基準**: `SELECT COUNT(*) FROM laws WHERE law_short IN ('建築基準法','都市計画法','不動産登記法','借地借家法','建物区分所有法')` が 5 行以上 + 各法の article 数が 80+。

## Week 3 — 制度 + zoning ingest (国交省 / 都道府県 / 市町村)

- `real_estate_programs` に **~500 programs** ingest:
  - 国交省: 住宅ストック維持・向上促進事業 / サービス付き高齢者向け
    住宅整備事業 / 既存住宅流通・リフォーム推進事業 等
  - 都道府県: 耐震改修助成 / 木造住宅密集地域整備 / 賃貸住宅整備補助
  - 市町村: 空き家活用補助 / 商店街リノベーション補助 (代表 100 都市)
- `zoning_overlays` に **23 区 + 政令市 20 都市** の用途地域 /
  防火地域 / 高度地区 を ingest (~1,000 overlay rows)。
  - 出典: 都市計画情報インターネット提供 (各自治体 GIS 公開分)
  - `restrictions_json` schema: `{kenpei: int, yoseki: int, height_max_m: int,
    nichiei_hours: float, special_use: str | null}`

**完了基準**: tier S+A 合計 ≥ 80 件 / `excluded=0` 行 ≥ 400 件 /
全行 source_url 一次情報 / zoning_overlays 1,000 行 + 全 23 区 coverage。

## Week 4 — MCP / REST tool 5 本追加

| ツール名                              | 系統        | 概要                                                              |
|---------------------------------------|-------------|-------------------------------------------------------------------|
| `search_real_estate_programs`         | jpintel     | `real_estate_programs` 全文検索 (全文検索インデックス + program_kind + law_basis filter) |
| `get_zoning_overlay`                  | jpintel     | (prefecture, city, district) で zoning_overlays lookup            |
| `search_real_estate_compliance`       | jpintel     | 不動産系 enforcement_cases + 行政処分横断 (建築士法等含む)        |
| `dd_property_am`                      | autonomath  | 1-shot due diligence (zoning + 補助 + 法令 + 区域指定)            |
| `cross_check_zoning`                  | jpintel     | 複数 overlay (用途地域 + 防火 + 高度) を 1 call で重ね合わせ    |

- `server.json` の `version` を bump (V3 後の連番に揃える)。
- `mkdocs build --strict` 通過 (新規 nav: Real Estate V5)。
- OpenAPI 再エクスポート (`scripts/export_openapi.py`)。
- 各 tool の docstring + JSON schema + per_tool_precision 行。

### Status update — 2026-04-25 (P6-F W4 scaffolding 完了)

Scaffolding が **本日着地** (`src/jpintel_mcp/mcp/real_estate_tools/`):

- `__init__.py` + `tools.py` で 5 stub 全て `@mcp.tool` 登録。
  対象 tool は `search_real_estate_programs` / `get_zoning_overlay` /
  `search_real_estate_compliance` / `dd_property_am` / `cross_check_zoning`。
- 各 stub は sentinel 注記
  `{"status": "not_implemented_until_T+200d", "launch_target": "2026-11-22", ...}`
  を返す。paginated 検索系は ``total=0`` + ``results=[]`` を併記し、no-match
  との区別が機械可読 (`status` キーで判定)。実 SQL は **T+200d 直前**
  (target 2026-11-22) で本 stub の body 差し替えとして land する。
- `AUTONOMATH_REAL_ESTATE_ENABLED` env (default `False`) で gate。
  launch (2026-05-06) 時点では disabled、manifest は **139 tools** のまま。
- operator が `True` に flip すると 69 + 5 = **139 tools** に増えるので、
  T+150d 程度で partner 向け OpenAPI 事前公開・契約面の peer review が可能。
- `tests/test_real_estate_tools.py` が
  ① env-False で 139 tools / ② env-True で 139 tools / ③ sentinel 注記
  return / ④ 各 stub の signature shape (parameter set + 型注釈 + docstring)
  を担保。
- migration 042 (real_estate_programs + zoning_overlays) は C7 で適用済み。
  T+200d の作業範囲は **stub body の SQL 化** に限定済み (signature /
  docstring / env gate / 登録順序は確定)。

これで V5 の launch path は **TODO body 5 箇所の SQL 差し替え + W2/W3 ingest**
の 2 軸に分離。signature 確定済みのため、docs / OpenAPI / dxt manifest は
T+200d を待たず先行公開できる。

---

## リスク

1. **都市計画情報の TOS が再配布制限を含む** → W3 で license 再評価。
   ban list に落ちた場合は `zoning_overlays` を delta-only に縮退、
   bulk 配信は launch 後に license 取得まで保留 (V3 PMDA と同じパターン)。
2. **建築基準法は条例委任が大きい** (各自治体の建築条例) → W2 では
   国法 + 政省令のみを正本扱いし、条例は W3 の `real_estate_programs` 側
   に `authority_level='city'` で吸収。法 vs 条例の境界は `law_basis`
   テキストで識別可能に保つ。
3. **不動産登記法の改定 cycle** (2026 年改正の経過措置あり) →
   `tax_rulesets` 同様に `effective_until` のクリフ flag を W2 で導入、
   2026/2027 の段階施行を `application_close_at` で表現。
4. **全文検索インデックス (3-gram) の単漢字偽陽性** (例: `地` で `団地・農地・林地・敷地`
   が混在ヒット) → `programs` 同様、2 文字以上の漢字熟語はクオート検索
   を強制、加えて `property_type_target` enum で post-filter。

## Out of scope (V5 終了後)

- 個人向け住宅ローン比較 (B2C 領域、zero-touch と整合しない、CS 線形増)。
- 不動産投資 利回り試算 (推論は顧客側 — `feedback_autonomath_no_api_use`)。
- 海外不動産 (法体系が別)。
- 都市計画決定 / 開発許可 申請業務代行 (士業独占 + zero-touch 不整合)。
