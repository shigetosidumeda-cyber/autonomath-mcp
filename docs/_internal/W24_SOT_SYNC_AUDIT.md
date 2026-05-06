# W24 SoT Sync Audit (read-only, 修正は別 wave)

- 生成日: 2026-05-05
- 対象 SoT: `CLAUDE.md`, `MASTER_PLAN_v1.md`, `README.md`, `docs/_internal/SECRETS_REGISTRY.md`, `docs/_internal/W19_legal_self_audit.md`, `docs/_internal/W22_INBOX_QUALITY_AUDIT.md`, `docs/_internal/W22_SENSITIVE_LAW_MAP.md`, `docs/_internal/W22_NEW_LAW_PROGRAM_LINKS.md`
- 方針: 矛盾 list + 推奨修正のみ。実 修正・git commit は禁止

---

## 1. 数値矛盾

### 1.1 MCP tool 総数 (96 vs 120 vs 126)

| ファイル | 値 | 出現箇所 |
|---|---|---|
| `CLAUDE.md` | **96** | line 7 (Overview, "MCP exposes **96 tools** at default gates"), line 9 (legacy 注), line 93 (Architecture), line 216 (server.py 説明) |
| `README.md` | **96** | line 17/19 (バナー), line 52 ("96 MCP tools"), line 147 ("96 tools at default gates"), line 219 ("standard distribution exposes 96 tools") |
| `pyproject.toml` | **96** | description |
| `dxt/manifest.json` | **96** | description |
| `server.json` | **120** | description + `tool_count: 120`, `version: 0.3.4` |
| `mcp-server.json` | **120** | description ×2 + `tool_count: 120` ×2, `version: 0.3.4` |
| `smithery.yaml` | **120** | "120 tools" + `version: 0.3.4` |
| `MASTER_PLAN_v1.md` | **96 → 120** (Wave 24 計画後) | line 656 ("`96 tools` → `120 tools`"), line 813/1163 ("120 tool"), line 1860, line 2154 (24 tool 追加で 96+24=120) |
| memory `project_jpcite_wave_1_to_5_complete` | 120 tools | "v0.3.1 healthy/178 routes/120 tools" |
| memory `project_jpcite_wave_1_to_16_complete` | 154+ task / 240 route | tool 数 言及 なし |
| ユーザー指示 | 126 (runtime + manifest) | task の前提 |

**矛盾**: README/CLAUDE は **96**、manifest 4 本 (server.json, mcp-server.json, smithery.yaml, dxt/manifest.json のうち 3 本) は **120**、`dxt/manifest.json` description は **96** で manifest 内部すらドリフト。pyproject.toml も 96。MASTER_PLAN は Wave 24 着地後 120 を前提。memory は 120。ユーザー指示 126 は SoT 側に登場せず。

**推奨**:
- 真値を `len(await mcp.list_tools())` で実測 (CLAUDE.md line 7 が指示する手順)。Wave 24 後の出荷 spec が 120 なら、CLAUDE.md / README.md / pyproject.toml / dxt/manifest.json description を **120** に揃える。
- ユーザー指示の 126 は (a) 実測差し直し、(b) もしくは pre-Wave24 の 96 + 30 future flag が混入しているか確認。126 の根拠が SoT に無いため、まず runtime 実測を fix point とする。

### 1.2 program count (11,684 vs 14,472)

| ファイル | 表記 |
|---|---|
| `CLAUDE.md` line 7, 101 | "11,684 searchable / 14,472 total / X quarantine 2,788" |
| `README.md` line 17/19/48 | "11,684 programs" + "full catalog = 14,472, 2,788 publication-review rows" |
| `pyproject.toml` | "11,684 searchable subsidies (14,472 total)" |
| `mcp-server.json` description | "11,684 補助金" (14,472 言及なし) |
| `dxt/manifest.json` description | "11,684 補助金" |

**矛盾**: 用語ドリフトのみ — `CLAUDE.md` は "tier X quarantine"、`README.md` は "publication-review rows" と表現が異なる (実体は同じ 2,788 行)。  
**推奨**: 表現統一は launch copy 担当の判断、現時点で数値矛盾はない。`README.md`の "publication-review rows" を `tier X quarantine (publication-review)` に拡張すれば対外 + 内部用語が同一に。

### 1.3 sensitive tool count (17 vs 26)

| ファイル | 値 |
|---|---|
| `CLAUDE.md` | 言及なし (Wave 30 で 11 sensitive-tool branch とのみ記述、line 9) |
| `README.md` | 言及なし |
| `MASTER_PLAN_v1.md` | "16 tools" (line 32, 75, 94, 517, 559, 1860) — 4→16 拡大が文中決定済 |
| `W19_legal_self_audit.md` | **17** (line 5, 119) — タイトル / §4 マトリクス / GO 判定で 17 件 |
| `W22_SENSITIVE_LAW_MAP.md` | **26** (line 11) — 「仕様書では 17 件とあるが、frozenset 実体は 26 件」と明記、内訳 = Wave22 4 + Wave23 3 + その他 19 |
| 実装 (`envelope_wrapper.SENSITIVE_TOOLS` frozenset) | **26** (W22_SENSITIVE_LAW_MAP の出典) |

**矛盾**: MASTER_PLAN=16 / W19=17 / 実装=26 の三ズレ。W22_SENSITIVE_LAW_MAP は実装と一致しているが、W19 が古い 17 件 list を前提に GO 判定しているため、新 9 件 (= 26 - 17) は正式 self-audit 未通過。

**推奨**:
1. W19_legal_self_audit を **26 件 base に再 audit**。新 9 件 (search_tax_incentives, get_am_tax_rule, list_tax_sunset_alerts, apply_eligibility_chain_am, find_complementary_programs_am, simulate_application_am, get_houjin_360_am, search_invoice_by_houjin_partial, compose_audit_workpaper, audit_batch_evaluate, resolve_citation_chain — W22_SENSITIVE_LAW_MAP の Surface 別 group 参照) を §4 表に追記。
2. MASTER_PLAN の "16 tools 弁護士 review" を 26 base に更新 (但しユーザー方針「弁護士相談しない、AI が業法調査で代替」に基づき、L1 タスク全体を W19 self-audit 拡張に置換)。
3. CLAUDE.md / README.md は sensitive 件数を明示していないため、追記するなら 26 (実装値) を採用。

### 1.4 am_law_article 行数 (28k → 160k → 204k)

| ファイル | 値 |
|---|---|
| `CLAUDE.md` line 7, 102 | **28,201** (固定) |
| `README.md` line 30 | **28,201** ("28,201 article rows pre-indexed") |
| `pyproject.toml` | 言及なし (laws 系は "154 laws full-text + 9,484 catalog stubs" のみ) |
| `MASTER_PLAN_v1.md` line 813, 875, 1486, 2154, 2265 | **28,201** (現状) / **9,484** distinct law (saturate target) / **18,968** (summary ×2 lang saturate) |
| `W22_NEW_LAW_PROGRAM_LINKS.md` line 5 | **160,215** (am_law_article) / **142,507** (W21-1 ingest 後 post 2026-04-28) |
| `W22_NEW_LAW_PROGRAM_LINKS.md` title + 4, 50 | **132k** (タイトルと本文末) |

**矛盾**: 巨大ドリフト。CLAUDE/README は 28,201 で停止、W22_NEW_LAW_PROGRAM_LINKS は 160,215 (= W21-1 ingest 後) を実測値として記録。タイトル "132k" と本文 "142,507"・"160,215" の三値も内部不整合 — 132k は概数か旧スナップショット、142,507 は ingest delta、160,215 は累計と推定。ユーザー指摘の "204k" は SoT に登場せず。

**推奨**:
1. W22_NEW_LAW_PROGRAM_LINKS のタイトル "132k" を **160,215 (累計) / 142,507 (W21-1 delta)** に置換、または本文と整合する数値に絞る。
2. CLAUDE.md / README.md / pyproject.toml の **28,201** を実測 `SELECT COUNT(*) FROM am_law_article;` で再取得し、160k 級なら全 SoT を一斉更新。
3. ユーザー指摘 204k の出典を確認 (現在 SoT 上は 160k が最大値)。post-W22 で更に ingest があった場合は再計測必須。
4. saturate target 9,484 distinct law (B 拡張) は別軸 — 行数 (article 単位) と law 単位 を README の表記でも明示分離。

### 1.5 v0.3.1 vs v0.3.2 vs v0.3.4 ドリフト

| ファイル | version |
|---|---|
| `pyproject.toml` | 0.3.3 |
| `server.json` | 0.3.4 |
| `mcp-server.json` | 0.3.4 |
| `smithery.yaml` | 0.3.4 |
| `dxt/manifest.json` | 0.3.4 |
| `CLAUDE.md` line 9 | "v0.3.1 ... v0.3.2" (2026-04-30 jpcite brand rename) |
| memory `project_jpcite_wave_1_to_5_complete` | "jpcite-api v0.3.1" |

**矛盾**: pyproject **0.3.3** vs 残り manifest **0.3.4** の 1 段ズレ。CLAUDE.md は v0.3.2 で文末停止 (Wave 24 着地後の v0.3.3/v0.3.4 changelog 追記なし)。

**推奨**: pyproject.toml を 0.3.4 に bump (manifest と sync)。CLAUDE.md "v0.3.2 on 2026-04-30" の後ろに "v0.3.3 / v0.3.4 (Wave 24)" 段落を追記。Release checklist (CLAUDE.md line 178) は「version in both pyproject.toml and server.json (they must match)」と明記しているため、これは規約違反。

---

## 2. brand 名 一貫性

| 用途 | 推奨ブランド (memory + CLAUDE.md より) | 観測 |
|---|---|---|
| user-facing 製品名 | **jpcite** | README, site, CLAUDE.md "Product: jpcite" — OK |
| PyPI / import path | **autonomath-mcp** (PyPI dist) / **jpintel_mcp** (Python import) | OK、CLAUDE.md line 88-89 で明記 |
| Fly app 名 | **autonomath-api** | SECRETS_REGISTRY 全箇所 — OK (legacy app slug 維持) |
| 法人 | **Bookyou株式会社** (T8010001213708) | OK |
| 旧ブランド | jpintel = 著名商標衝突 (Intel)、autonomath = 旧プロダクト (現 EC SaaS は別物) | OK、user-facing で出現せず |

**観測**: brand layer は overall 整合。ただし以下 2 件で小ドリフト:
1. `CLAUDE.md` の `JPCITE_API_BASE` 環境変数 (README) と `JPINTEL_CORS_ORIGINS` / `JPINTEL_ENV` (CLAUDE.md / SECRETS_REGISTRY) が混在。env var prefix が **新 = JPCITE / 旧 = JPINTEL** で 2 系統共存。
2. `README.md` line 89 `JPCITE_API_KEY` と CLAUDE.md / SECRETS_REGISTRY の `API_KEY_SALT`, `AUDIT_SEAL_SECRET` (prefix なし) で 3 通りの env 命名が混在。

**推奨**: env var の rename は本番影響大 (Fly secrets / `~/.jpcite_secrets_self.env`) のため Wave24 範囲外。**注記のみ追記**: CLAUDE.md に "env var prefix は legacy `JPINTEL_*` を維持、新規 customer-facing は `JPCITE_*`" と方針明記。

---

## 3. path / file リンク

### 3.1 リンク切れ確認 (実在検証済)

| 参照元 | 参照先 | 実在 |
|---|---|---|
| `SECRETS_REGISTRY.md` line 119 | `docs/_internal/W19_legal_self_audit.md` | OK |
| `SECRETS_REGISTRY.md` line 119 | 旧 `W19_lawyer_consult_outline.md` (historical) | OK 残置 |
| `SECRETS_REGISTRY.md` line 124 | `scripts/ops/discover_secrets.sh` | OK |
| `CLAUDE.md` line 111 | `docs/_internal/COORDINATION_2026-04-25.md` | OK |
| `CLAUDE.md` line 131 | `docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md` | 未検証 (本 audit 範囲外) |
| `CLAUDE.md` line 196 | `docs/runbook/cors_setup.md` | 未検証 |
| `README.md` line 17 et al | `docs/mcp-tools.md` | 未検証 (Wave 24 で 120 tool list 同期必要) |

**矛盾なし**: 主要リンクは健全。`docs/mcp-tools.md` は tool 数 96/120 ドリフトの影響を受ける可能性大 — Wave 24 修正対象に含めるべき。

### 3.2 W22_NEW_LAW_PROGRAM_LINKS line 38 `/tmp/w22_candidates.tsv`

**問題**: 一時ファイル参照 — 別ホスト/別セッションで再現不可。**推奨**: 該当 dump を `docs/_internal/W22_law_candidates.tsv` に移動するか、生成 SQL を doc 内に inline 化。

---

## 4. migration 番号一致性

### 4.1 採番衝突 (MASTER_PLAN v2 で既認識・修正済)

`MASTER_PLAN_v1.md` CHANGELOG 表 #8 で確認:
- v1 で計画した 110-125 が `scripts/migrations/` の **105_integrations.sql / 110_autonomath_drop_cross_pollution / 114_adoption_program_join / 121_subsidy_rate_text_column / 121_jpi_programs_subsidy_rate_text_column** 等と衝突
- v2 で **`wave24_` prefix で再採番 126-139** に移行済

**観測**: `scripts/migrations/` には実際に `wave24_105_audit_seal_key_version.sql` ... `wave24_163_am_citation_network.sql` まで wave24_ prefix 付きの新ファイル群が存在 (40+ ファイル)。MASTER_PLAN の修正が実装に反映済。

**残課題**: `121_subsidy_rate_text_column.sql` と `121_jpi_programs_subsidy_rate_text_column.sql` の **同番号 2 ファイル衝突** が legacy 側で残存。entrypoint.sh apply 順序で挙動差が出る可能性 — Wave 24 では関係ないが別 audit 必須。

### 4.2 各 SoT で参照される migration 番号

| SoT | 番号 | 参照内容 |
|---|---|---|
| `CLAUDE.md` | 032, 046-049, 067, 081, 083, 088, 089, 090, 091, 092, 096-099, 101, 103, 104 | 各機能対応 — 全実在 |
| `MASTER_PLAN_v1.md` | 105-113 (本書中の論理番号 + wave24_ prefix), 140-142 | 105-109 は wave24_105〜109 として実在、110-113 は wave24_110〜113 ?? — 要照合 |
| `README.md` | 番号言及なし (機能名のみ) | n/a |
| `W19_legal_self_audit.md` | 番号言及なし | n/a |
| `W22_INBOX_QUALITY_AUDIT.md` | 番号言及なし | n/a |
| `W22_SENSITIVE_LAW_MAP.md` | 番号言及なし | n/a |
| `W22_NEW_LAW_PROGRAM_LINKS.md` | 番号言及なし (`am_law_reference` 参照のみ) | n/a |

**観測**: legacy migration 番号 (032, 046-104) は CLAUDE.md と migration index 整合。Wave 24 計画番号 (MASTER_PLAN 105-113, 140-142) は **wave24_ prefix で実在確認済** (e.g. wave24_105_audit_seal_key_version, wave24_140_am_narrative_extracted_entities)。

**推奨**: 
- MASTER_PLAN の「migration 105 (=wave24_105)」記法を全箇所で統一。"migration 105" 単独表記は legacy 105_integrations.sql と混同のリスクあり。
- wave24_ 番号系列の最終 manifest (どの番号が actual 実在 / どの論理番号がスキップ)を `docs/_internal/W24_MIGRATION_MANIFEST.md` (新規) で固定化を別 wave で実施。

---

## 5. 修正優先度サマリ (本 audit は推奨のみ、実 修正は別 wave)

| # | 矛盾 | 優先度 | 推奨対応 |
|---|---|---|---|
| 1.1 | tool count 96 vs 120 (manifest 整合済 vs README/CLAUDE/pyproject 古い) | **HIGH** | runtime `list_tools()` 実測 → 全 SoT 一括更新 |
| 1.5 | pyproject 0.3.3 vs manifest 0.3.4 (規約違反) | **HIGH** | pyproject bump 0.3.4 |
| 1.3 | sensitive tool 17 (W19) vs 26 (実装) | **HIGH** | W19 を 26 件 base に再 audit、新 9 件追記 |
| 1.4 | am_law_article 28k (CLAUDE/README) vs 160k (W22) | **MED** | 実測 → 全 SoT 一括更新、204k 出典確認 |
| 2 | env var prefix `JPINTEL_*` vs `JPCITE_*` 混在 | **LOW** | CLAUDE.md に方針注記のみ |
| 3.2 | W22_NEW_LAW `/tmp/w22_candidates.tsv` 参照 | **LOW** | dump を repo 内移動 or SQL inline |
| 4.2 | MASTER_PLAN 「migration 105」単独表記 → wave24_ prefix 明示 | **LOW** | 表記統一 |
| 4.1 | 121_subsidy_rate_text_column / 121_jpi_*同番号 2 ファイル | **MED** (本 audit 範囲外) | 別 audit で entrypoint.sh apply 順序検証 |

---

## 6. 完了判定

- audit doc 作成: 本ファイル
- 矛盾 list: §1-§4 (8 区分)
- 推奨修正: §5 (優先度付)
- 実 修正: なし (read-only 遵守)
- git commit: なし
