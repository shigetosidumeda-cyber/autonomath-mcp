# Healthcare V3 — 6 週ローンチ計画

**期間**: 2026-04-25 → 2026-08-04 (T+90d)
**対象 cohort**: 医療法人 (3-5k 法人) / 介護施設 (50k+) / 薬局 (60k+) / 訪問介護
**Path**: jpcite コア (¥3/req metered) を医療・介護・薬局領域へ拡張する第3波。
**判定基準**: launch 直後 30d で 50+ paid request / day 流入を 1 件以上の cohort 顧客から確認できれば **継続**、未達なら sunset。

---

## なぜ Healthcare V3 か

- jpcite は 2026-05-06 に農業 + SMB 制度 13,578 件で launch する。
  Healthcare はその cohort 拡張 — `programs` テーブルへ無理に詰め込まず、
  **専用テーブル 2 本** (`medical_institutions` / `care_subsidies`) を別建てする。
- ターゲット 3 cohort は **薬機法 / 医療法 / 介護保険法** という 3 本の
  根拠法で制度が組まれており、横串の SaaS 型情報配信ニーズが可視化済み。
- 既存 `laws` (9,484 行) / `tax_rulesets` (35 行) と **法令 unified_id 経由**
  で接続するため、追加コストはスキーマと ingest のみ。MCP server は
  ツール 6 本追加で 84 → 85 (1 sunset 込み)。

## 制約

- **Solo + zero-touch** (memory: `feedback_zero_touch_solo`)。
  営業 / DPA / Slack Connect / onboarding call 等の人的介在機能は提案禁止。
- **Anthropic API は呼ばない** (memory: `feedback_autonomath_no_api_use`)。
  推論は顧客側、当方は API/MCP/静的 docs のみ。
- **brand**: jpcite / 運営は Bookyou株式会社 (T8010001213708)。
  jpintel ブランドはユーザー面に出さない。
- **データ衛生**: `source_url` には一次情報 (厚労省 / PMDA / 自治体 / e-Gov)
  のみ。集約サイト (medley / care-net / 医療系 SEO サイト) は ban list。

---

## Week 1 — Schema migration prep (今週、完了)

**Done**

- `scripts/migrations/039_healthcare_schema.sql` 追加
  - `medical_institutions` (institution_type 6 値 enum / beds / 許可番号 / JSIC)
  - `care_subsidies` (law_basis / authority_level enum / tier S-A-B-C-X)
  - 4 インデックス: `idx_medical_pref_type` / `idx_medical_jsic` /
    `idx_care_pref` / `idx_care_law`
- `data/jpintel.db` へ migration 適用 + `schema_migrations` 登録済み
- 本ドキュメント + `docs/healthcare_v3_cohort_personas.md` 公開

**Out of scope (W1)**

- `autonomath.db` への `record_kind='healthcare'` 拡張は **収集 CLI 領域**。
  W2-W3 で別 agent が担当する。
- ingest スクリプト本体 (W2 以降)。

## Week 2 — 法令 ingest (薬機法 / 医療法 / 介護保険法)

- e-Gov 法令 API から **3 法 + 関係政省令** を fetch、`laws` に追記。
  目標 ~500 articles。
- `program_law_refs` 経由で 既存 `programs` の 医療系 補助金を再リンク。
- `source_lineage_audit` に whitelist (elaws.e-gov.go.jp, mhlw.go.jp,
  pmda.go.jp) を追加。

**完了基準**: `SELECT COUNT(*) FROM laws WHERE law_short IN ('薬機法','医療法','介護保険法')` が 3 行以上 + 各法の article 数が 100+。

## Week 3 — 制度 + 認定 ingest (厚労省 / PMDA / 自治体)

- `care_subsidies` に **~500 programs** ingest:
  - 厚労省: 介護報酬加算 / 薬局機能強化加算 / 認知症対応型サービス費等
  - 自治体: 開設費補助 / 設備整備補助 (47 都道府県の代表値ベンチマーク)
- `medical_institutions` に **~200 cert/許可** ingest:
  - 都道府県登録 医療法人一覧 (PDF/HTML)
  - 介護事業者検索 (WAM NET 公開分)
  - 厚生局公開 薬局リスト (delta only — bulk は launch 後の license 検討)

**完了基準**: tier S+A 合計 ≥ 80 件 / `excluded=0` 行 ≥ 400 件 / 全行 source_url 一次情報。

## Week 4 — MCP / REST tool 6 本追加 (合計 84 → 85)

| ツール名                              | 系統        | 概要                                                       |
|---------------------------------------|-------------|------------------------------------------------------------|
| `search_healthcare_programs`          | jpintel     | `care_subsidies` 全文検索 (全文検索インデックス (3-gram) + law_basis filter)|
| `get_medical_institution`             | jpintel     | `medical_institutions` PK lookup (canonical_id)            |
| `search_healthcare_compliance`        | jpintel     | 法令違反 / 行政処分横断 (medical 系 enforcement_cases)     |
| `check_drug_approval`                 | jpintel     | PMDA 承認情報 lookup (薬局・医療法人向け)                  |
| `search_care_subsidies`               | jpintel     | prefecture + institution_type_target で絞り込み            |
| `dd_medical_institution_am`           | autonomath  | 1-shot due diligence (cert + enforcement + region facts)   |

- `server.json` の `version` を 0.3.0 へ。
- 既存 `analysis_wave14` の sunset tool 1 本を delisted (差し引き +5、
  純増だが nominally 84 + 1 sunset = **85 manifest entries**)。

### Status update — 2026-04-25 (P6-D scaffolding 完了)

Scaffolding が **本日着地** (`src/jpintel_mcp/mcp/healthcare_tools/`):

- `__init__.py` + `tools.py` で 6 stub 全て `@mcp.tool` 登録 (合計 332 行).
- 各 stub は sentinel 注記 `{"status": "not_implemented_until_T+90d", "results": []}` を返す。実 SQL は **W4 (T+90d, 2026-08-04)** で TODO コメントの位置に書き足し。
- `AUTONOMATH_HEALTHCARE_ENABLED` env (default `False`) で gate。launch (2026-05-06) 時点では disabled、manifest は 89 tools のまま。
- operator が `True` に flip すると 89 + 6 = **95 tools** に増えるので W4 直前に契約面の事前確認が可能。
- `tests/test_healthcare_tools.py` が
  ① env-False で 89 tools / ② env-True で 95 tools / ③ sentinel 注記 return / ④ 各 stub の signature shape を担保。

これで W4 で触る範囲は **TODO コメント 6 箇所の SQL body 差し替えのみ** に縮小済み。signature / docstring / env gate / 登録順序は確定済みで再 deploy なしに query layer を埋められる。

## Week 5 — Doc + manifest + DXT 0.3.0 regen

- 各 tool の docstring + JSON schema + per_tool_precision 行。
- `mkdocs build --strict` 通過 (新規 nav: 医療・介護・薬局)。
- `dxt/` に 0.3.0 manifest 再生成、105 tool 全件 schema export。
- OpenAPI 再エクスポート (`scripts/export_openapi.py`)。

## Week 6 — Cohort onboarding + testimonial collection

- 公開 5 personas (`healthcare_v3_cohort_personas.md`) に対する
  ブログ記事 5 本を `docs/blog/` に published=false で stash、launch 当日 flip。
- 流入経路: organic SEO のみ (memory: `feedback_organic_only_no_ads`)。
- `launch+30d` レビュー: 1 paid cohort 顧客が 50+ req/day 維持 → 継続、
  未達 → sunset (ツール 6 本は flag off だけで disable 可能な設計)。

---

## リスク

1. **PMDA / 厚生局の TOS が再配布制限を含む** → W3 で license 再評価。
   ban list に落ちた場合は `medical_institutions` を delta-only に縮退、
   bulk 配信は launch 後に license 取得まで保留。
2. **介護保険法は 3 年改定 cycle** (次回 2027-04 改定) → `effective_until`
   2027-03-31 のクリフ flag を `tax_rulesets` と同じパターンで設計。
3. **medical 全文検索インデックス (3-gram) の単漢字偽陽性** (例: `薬` で `麻薬` ヒット) →
   `programs` 同様、2 文字以上の漢字熟語はクオート検索を強制。

## Out of scope (V3 終了後)

- 歯科医院 / 鍼灸接骨院 (W6 後の V4 候補)。
- 患者向け制度 (高額療養費 等) — B2C 領域なので solo + zero-touch と整合しない。
- AI 診断 / 電子カルテ統合 — 推論は顧客側 (memory: `feedback_autonomath_no_api_use`)。
