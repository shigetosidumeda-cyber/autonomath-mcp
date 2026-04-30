# Phase A handoff 精査 (launch CLI 視点)

**Date**: 2026-04-25 21:40 JST
**Author**: launch CLI
**対象**: `docs/_internal/PHASE_A_HANDOFF_2026-04-25.md` の audit

---

## TL;DR

absorption CLI の Phase A は **lifesaving な質**。私 (launch CLI) が J/K audit で発見した P0-1 (models shadow) を absorption CLI が proactive 解消、L1 が no-op で済んだ。+7 tools / +7 endpoints / models 統合 / health_router 分離 / target_db marker 設計 全部 **正しく実装** されている。

ただし **3 つの重要事項** で確認/追加対応が必要:

1. **production v15 deploy が Phase A を含んでいない** → `/v1/am/health/deep` が production で 404
2. **私の L 系列と absorption CLI の Phase A で同じ file を編集** → file は最後の write が勝ってる、両者の意図が両立しているか確認
3. **manifest 数値 drift** が 55 / 13,578 / 416,375 のまま (Phase A で 66 / 503,930 になったが doc 反映途中)

---

## 1. ローカル状態の verify (claim 通り動いてるか)

### ✅ confirmed
- **66 tools** 確定: `len(server.mcp._tool_manager._tools)` = 66
- **Phase A 7 tools 全部 registered**: `deep_health_am / list_static_resources_am / get_static_resource_am / list_example_profiles_am / get_example_profile_am / render_36_kyotei_am / get_36_kyotei_metadata_am`
- **pytest 1122 passed / 8 skipped / 0 failed** (139 秒)
- **`health_router` 分離設計** が正しく実装 (autonomath.py:75 + 928)
- **models/__init__.py 統合**: import OK、autonomath-mcp init exit 0

### ⚠️ production gap
- **`/v1/am/health/deep` → production 404** (まだ deploy されていない)
- production v15 image は L 系列 + Phase A 反映前なので、deploy しないと顧客が見れる新 endpoint は 0
- 監視 ping 用 deep_health は launch 時に必要

---

## 2. Phase A の評価 (内容ごと)

### 2.1 +7 tools の品質

| tool | 評価 |
|---|---|
| `list_static_resources_am` / `get_static_resource_am` | ✅ 8 タクソノミ (glossary / seido / dealbreakers / money_types / obligations / sector_combos / agri / templates) → AI agent が「何の単語使うか」 discoverable に |
| `list_example_profiles_am` / `get_example_profile_am` | ✅ 5 example persona (A_ichigo_20a / D_rice_200a / J_new_corp / N_minimal / Q_dairy_100head + bc666_plan_map) → AI agent が「typical input shape」を学習可能 |
| `render_36_kyotei_am` / `get_36_kyotei_metadata_am` | ⚠️ **法的精度要確認**: 36協定 (時間外労働の労使協定) は社労士 → 労基署 提出書類。生成内容の error が brand 損傷リスク高い。validation 必須 |
| `deep_health_am` | ✅ operator 監視用、内部実装は `_health_deep.py:get_deep_health()` の 10-check (DB ファイル / WAL / row count / migration / precompute)、launch 当日 必要 |

→ 4/7 は安全 (read-only taxonomies + example data)、2/7 (36協定) は **法務 review 必要**、1/7 (deep_health) は launch 当日活用

### 2.2 architectural decisions

#### ✅ health_router 分離 (AnonIpLimitDep bypass)
- 鋭い設計、launch CLI 側で見落としていた
- production の uptime 監視で **匿名 50 req/月 quota が即枯渇** する hazard を回避
- 私の I8 perf bench でも /healthz が同 quota で 429 返した経験あり、解決策として完全に正しい

#### ✅ target_db marker (`-- target_db: autonomath` 1行目限定)
- migration 046/047/049 が test fixture (jpintel.db) で fail する問題を解決
- **5 行 scan limit** で CREATE TRIGGER body 内の偶然 match 防御
- 新規 migration を書く規約として正しい

#### ✅ envelope merge は production 維持、test 緩和
- `_envelope_merge` (server.py:780-820) は **9 keys + meta** を additive merge:
  - status, result_count, explanation, suggested_actions, api_version, tool_name, query_echo, latency_ms, evidence_source_count
- 私 L5 が wired したのと整合 (`_envelope_merge` という helper は absorption CLI 製、L5 が `_with_mcp_telemetry` 経由で 71 tool に適用)
- test 側を `==` から `.issubset()` に緩める判断は正しい (production 行動を破壊しない方が AI agent UX 重要)

#### ✅ models/ 統合 (package 優先)
- 444 行を `models/__init__.py` に統合 + `models.py` 削除
- `premium_response.py` を sibling module として並列追加
- 私 L1 が同じ修正をするはずだったが、absorption CLI が先に proactive 解消 → L1 は no-op で済んだ

### 2.3 fix した legacy debt 6 件 — 全部正しい修正

| 修正 | 評価 |
|---|---|
| migration 049 routing | ✅ marker scheme で test fixture と production 分離 |
| precompute_schemas drift | ✅ `am_db_path` override + missing-table tolerance + PC_TABLES_AM 33 計算 |
| test_stats freshness contamination | ✅ `UPDATE programs SET source_fetched_at=NULL WHERE unified_id LIKE 'UNI-test-%'` で session-scoped fixture leak 解消 |
| l4_query_cache fixture | ✅ 既に self-heal 実装済 (api/stats.py:59-145、L5/B-A8 系列が実装) と判明 → 当方も触らない方針で OK |
| MCP envelope test drift | ✅ 4 test を `.issubset()` / 引き算後 `==` に緩和、production code 無変更 |
| healthcare/RE count assertion | ✅ 55→66 / 61→72 反映、私 L2 の docstring 更新と整合 |

### 2.4 deferred 4 件

| 項目 | 評価 |
|---|---|
| FTS+vec rebuild (~2.2h) | ✅ 正当に deferred、annotation text + 21 corp.* facts は post-launch で OK |
| `am_entity_facts.source_id` backfill | ✅ am_entity_source rollup 待ちで後回し、blocker でない |
| manifest version bump v0.2.0→v0.3.0 | ⚠️ 私 I1 が drift sync 完了直後に Phase A で +7 tools 追加 → manifests は 13,578 / 55 / 416,375 の 古い数値のまま、66 / 503,930 反映されていない。**launch 前に re-sync 必要** |
| CLAUDE.md 行 9 と 33 legacy "tools 59" | ✅ 意図的 historical note、保持で OK |

---

## 3. 私 (launch CLI) との file overlap 検証

私 (L1-L6) と absorption CLI (Phase A) が **並走で同じ file** を編集していた。最終的に各 file は誰が write したか:

| file | absorption CLI が touched | L 系列が touched | 最終状態 |
|---|---|---|---|
| `src/jpintel_mcp/models/__init__.py` | ✅ 統合 | (L1 dispatch 済だが no-op で完了、absorption の work を尊重) | absorption CLI 版 |
| `src/jpintel_mcp/mcp/server.py` (332KB、最大 file) | ✅ `_envelope_merge` + Phase A 7 tool registration + healthcare/RE registration | ✅ L2 (get_meta dynamic / list_exclusion_rules envelope) + L3 (check_exclusions dual-key) + L5 (`_with_mcp_telemetry` wiring) | **両者の変更が共存しているはず** (mtime 21:10 = L 系列が最後 write) |
| `src/jpintel_mcp/api/main.py` | ✅ `health_router` mount + Phase A glue | ✅ L2 (request_id propagation) + L4 (strict_query middleware register + global error handler) | **両者の変更が共存** (mtime 20:51) |
| `src/jpintel_mcp/api/autonomath.py` | ✅ Phase A 7 endpoint + `health_router` 分離 | ✅ L5 (`_apply_envelope`) + L6 (response_model annotate) | **両者の変更が共存** (mtime 20:57) |
| `src/jpintel_mcp/api/stats.py` | ✅ self-heal logic | ✅ L5 (cache.l4 統合) + L6 (response_model) | **L5/L6 が後から書いた** (mtime 21:02) |
| `src/jpintel_mcp/api/billing.py` | (未触) | ✅ L2 (charge.refunded handler) | L 系列のみ |
| `src/jpintel_mcp/mcp/healthcare_tools/tools.py` | (未触) | ✅ L2 (docstring T+90d 明記) | L 系列のみ |
| `scripts/migrations/050+` | (未作) | ✅ L3 (050 Tier=X / 051 exclusion_uid) | L 系列のみ |
| `tests/test_*` | ✅ Phase A test 追加 + 既存 test 緩和 | ✅ L 系列で test 追加 (test_strict_query / test_error_envelope / test_envelope_wiring) | 両者共存 |

**Verify**: pytest 1122 passed = 両者の変更が **両立して PASS** している。これは coordination の成功例。

### 3.1 L 系列との conflict reconciliation

| L agent | claim | absorption CLI 状態 | 確認 |
|---|---|---|---|
| L1 P0-1 models shadow | absorption 解消済、no-op | ✅ confirmed (L1 報告と一致) | OK |
| L2 α2 get_meta dynamic | hardcoded 47/31 → live=66 | ✅ live 66 confirmed | OK |
| L2 α11 list_exclusion_rules envelope | union return → envelope 統一 | ✅ Phase A handoff §2.5 で envelope-key issue 言及、test も緩和 | 整合 |
| L3 γ1 Tier=X migration 050 | 1,206 → 0 | ✅ migration 050 既 apply | OK |
| L3 γ2 exclusion_rules dual-key migration 051 | 23 row resolved + dual-key matching | (Phase A 触っていない領域) | OK、L3 専有 |
| L4 δ1 strict_query middleware | ?fake_param=xyz → 422 | (Phase A 触っていない) | OK、L4 専有 |
| L4 δ2 _error_envelope.py | 5xx 統一 / request_id "unset" | (Phase A 触っていない) | OK、L4 専有 |
| L5 β1 envelope wiring (71 tool) | `_envelope_merge` を `_with_mcp_telemetry` 経由で全 tool に適用 | ✅ Phase A handoff §2.5 で `_envelope_merge` mention あり、整合 | OK |
| L5 β3 cache.l4 統合 | api/stats.py の inline cache → l4 helper | ✅ Phase A §2.4 で「self-heal 実装済」言及、L5 がそれを l4 helper に統合 | OK |
| L6 ε response_model | 32 endpoint annotate / OpenAPI 27→6 | (Phase A 触っていない) | OK、L6 専有 |

→ **reconciliation 成功**、両者の変更が両立して 1122 pass。

---

## 4. 残 concerns (audit 上重要)

### concern-1: production v15 が Phase A 含まない
- v15 deploy は L 系列 + Phase A 前
- 顧客が `/v1/am/health/deep` 等 Phase A 新 endpoint 叩いても 404
- **次の deploy で全部反映**、それまで「Phase A 完了」は コードベース上のみ
- launch 時 (5/6) の deploy で完成

### concern-2: manifest version bump が deferred
- pyproject.toml / server.json / dxt/manifest.json / smithery.yaml が **v0.2.0 のまま**
- description の数値も 55 / 13,578 / 416,375 で古い
- Phase A 後の正値は 66 / 13,578 / 503,930
- **launch 前 manifest sweep 必要** (~1h、私 launch CLI でやれる)

### concern-3: 36協定テンプレート (`render_36_kyotei_am`) の法的精度
- 雇用契約 / 労使協定 系は 社労士業務、誤った generation は brand 損傷
- launch 前に **法務 review** 推奨 (operator manual)
- もし review NG なら env gate (`AUTONOMATH_36_KYOTEI_ENABLED`) で disable しておく

### concern-4: `_envelope_merge` の `meta` key conflict
- absorption CLI: `_envelope_merge` は「native meta なき場合のみ meta を merge」
- L5: `_with_mcp_telemetry` decorator が `_envelope_merge` を呼ぶ
- L6: `response_model` で `extra="allow"` 指定して envelope passthrough
- → 3 layer chain、native meta あり/なし で挙動が変わる場合の test coverage 不足の可能性
- L5 test_envelope_wiring + Phase A test 両方 PASS なので **実害なし** だが、**edge case を docstring に書くべき**

### concern-5: deep_health の monitoring runbook
- absorption CLI が `health_router` 分離した正しい設計
- ただし **これを使う運用 runbook が docs/_internal/ にない**
- Cloudflare uptime / UptimeRobot / Pingdom 等の URL 設定例 + 何 second interval が良いか
- → docs/_internal/health_monitoring_runbook.md 新規 必要

---

## 5. 連動して launch CLI 側で必要な action

| # | action | 工数 |
|---|---|---|
| 5-1 | manifest version bump v0.2.0 → v0.3.0 + 数値 sweep (66 tools / 13578 / 503930) | 1h |
| 5-2 | Phase A 反映 production deploy (flyctl deploy) | 0.5h (deploy + smoke) |
| 5-3 | docs/_internal/health_monitoring_runbook.md 新規 | 0.5h |
| 5-4 | 36協定 法務 review 結果による gate 判断 (launch CLI 側で env 配線) | 0.5h |
| 5-5 | `_envelope_merge` × `response_model` × `_with_mcp_telemetry` の chain edge case test | 1h |

合計 ~3.5h、private timing で実施可能。

---

## 6. 結論

absorption CLI の Phase A は **設計・実装・test・doc 全部高品質**。L 系列との conflict reconciliation も成功 (両者並走 → pytest 1122 PASS)。

ただし、**production deploy しない限り顧客が触れない** ので、Phase A の価値が surface 化するには次の deploy が必須。

私 (launch CLI) の次手:
1. coordination doc に「Phase A 内容を確認、production deploy で全部反映」と書く
2. manifest bump (v0.3.0) を絶対 launch 前に実施
3. 36協定 tool だけは法務 review まで env-gate 推奨を operator に伝える
4. health_monitoring_runbook を書く

衝突なく進められる、両 CLI が並走して reach した quality。良い coordination 例。

---

End of audit.
