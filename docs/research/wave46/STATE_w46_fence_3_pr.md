# Wave 46 — fence_registry 8/8 業法 完備 STATE

| field | value |
|---|---|
| wave | 46 |
| tick | 4 #8 |
| date | 2026-05-12 |
| branch | `feat/jpcite_2026_05_12_wave46_fence_3_complete` |
| base | `main` @ `1ab53b452` (Wave 43.3.10 AX Resilience cells 10-12) |
| pr | _open after push_ |
| lane | `/tmp/jpcite-w46-fence-3.lane/` (mkdir atomic, append-only ledger) |

## Scope

「触らない 8 業法」 fence_registry を 5/8 → 8/8 まで完備。Journey 6-step audit
step 2 (Evaluation) の score を 8.88 → 10.00 に押し上げ、overall を 9.67 →
9.86 に上げる。

`audit_runner_agent_journey.py` の `EIGHT_BUSINESS_LAW_FENCES` 定数が要求する
8 substring のうち、既存登録は 5 件のみ:

| # | 業法 | 既存 id | 既存 law field | substring 一致 |
|---|---|---|---|---|
| 1 | 税理士法 | tax_accountant | 税理士法 | OK |
| 2 | 弁護士法 | lawyer | 弁護士法 | OK |
| 3 | 司法書士法 | judicial_scrivener | 司法書士法 | OK |
| 4 | 行政書士法 | administrative_scrivener | 行政書士法 | OK |
| 5 | 社会保険労務士法 | sharoushi | **社労士法** (短縮形) | **FAIL — short form** |
| 6 | 公認会計士法 | — | — | **FAIL — entry missing** |
| 7 | 弁理士法 | patent_attorney | 弁理士法 | OK |
| 8 | 労働基準法 | — | — | **FAIL — entry missing** |

## Changes

### 1) data/fence_registry.json

- `schema_version` 1.0 → 1.1
- `snapshot_at` 2026-05-11 → 2026-05-12
- `canonical_count` 7 → 8
- 既存 7 fence をすべて Wave 46 schema (scope_negative / fence_type /
  license_required / surface_text / source_url) で再記述。**surface_text
  改ざんなし** — e-Gov 一次出典原文を引用挿入したのみ。
- `sharoushi.law`: **`社労士法` → `社会保険労務士法`** (canonical full form).
  `law_short: "社労士法"` を別フィールドで温存し既存 publish text の
  symbol-link は維持。これにより audit substring 一致。
- **新 fence #6 `cpa` (公認会計士法 §47条の2)** 追加: 監査証明業務の独占。
  EDINET 引用と監査基準 search は may_do、監査意見・財務書類監査・内部統制
  監査は do_not。
- **新 fence #8 `labor_standards` (労働基準法 §12+§32+§36)** 追加: 平均賃金
  /労働時間/36協定の surface 条文を 3 条文まとめて引用。個別事案判断 (do_not)
  と条文 surface 取得 (may_do) を明示分離。

### 2) tests/test_fence_registry_8_complete.py (new, ~180 LOC)

8 test, 全 green:

1. `test_registry_loads_with_eight_or_more_fences` — fences ≥ 8
2. `test_all_eight_business_laws_present_as_substring` — Journey audit と
   同一 substring 検査 (8/8)
3. `test_each_fence_has_wave46_schema_fields` — 8 required fields 完備
4. `test_surface_text_is_real_statute_quote` — ≥ 30 chars + placeholder 検査
5. `test_source_url_points_to_primary_source` — e-Gov / METI 一次出典のみ
   許可 (aggregator 弾く)
6. `test_three_new_wave46_fences_added` — sharoushi(canonical) + cpa +
   labor_standards 3 件存在
7. `test_no_existing_five_fences_were_deleted` — 既存 5 fence 保護 (禁止条項)
8. `test_journey_audit_step2_score_is_full` — subprocess で audit を回し
   step 2 ≥ 9.5 を assert

## Journey 投影

baseline (HEAD pre-PR):

```
step 1 discovery: 9.17
step 2 evaluation: 8.88    ← 5/8 fence
step 3 authentication: 10.0
step 4 execution: 10.0
step 5 recovery: 10.0
step 6 completion: 10.0
overall: 9.67
```

post-PR (verified locally):

```
step 1 discovery: 9.17
step 2 evaluation: 10.00   ← 8/8 fence
step 3 authentication: 10.0
step 4 execution: 10.0
step 5 recovery: 10.0
step 6 completion: 10.0
overall: 9.86
```

→ Journey overall delta **+0.19 (9.67 → 9.86)**, step 2 delta **+1.12 (8.88
→ 10.00)**, 8/8 業法 fence **verdict: COMPLETE**.

「10.0 / 10」ジャストは step 1 (discovery) が 9.17 で頭打ち (`README.md`
の ai-bot UA 列挙の sub-criterion 由来) のため到達せず。本 PR の射程外。

## 禁止条項チェック

| 禁止 | 検査 | 結果 |
|---|---|---|
| 既存 5 fence 削除 | `test_no_existing_five_fences_were_deleted` | PASS — 5 legacy id 全保持 |
| surface text 改ざん | 既存 fence の surface は **新規追加 only** (旧 entry には surface_text フィールドが無かった) | OK |
| main worktree | `/tmp/jpcite-w46-fence-3` (detached worktree) | OK |
| 旧 brand | 旧 `税務会計AI` / `zeimu-kaikei.ai` の挿入なし | OK |
| LLM API | pure stdlib, audit subprocess invocation も `subprocess` のみ | OK |

## check_fence_count.py 残 drift

`scripts/check_fence_count.py` の `fence_count_canonical=7` を保持 (本 PR で
は変更しない)。

drift 内訳 (本 PR 後):

- 51 → 48 件 (本 PR の audit md 上書きで 3 件解消)
- 残 48 件は既存 `8 業法 fence` の publish text (pricing/justification /
  competitive analysis / use case 等) — 旧 7 → 新 8 へ canonical を bump
  するための **別 PR** が必要。本 PR の射程外。

## 次の連動 PR (本 PR 後)

1. `data/facts_registry.json` の `guards.fence_count_canonical` 7 → 8
   bump
2. `site/legal-fence.html` + `site/legal-fence.html.md` の `6 業法` → `8
   業法` 統一
3. `site/trust/purchasing.html` の `5 業法 + 36協定` → `8 業法`
4. `site/llms.txt` の `7 業法 + 関連法` → `8 業法` 統一

## 報告 1-liner

PR `feat/jpcite_2026_05_12_wave46_fence_3_complete`: fence_registry 5/8
→ 8/8 (cpa + labor_standards 新規 + sharoushi 正規化), Journey overall
9.67 → 9.86, step 2 8.88 → 10.00, 8 test green, 禁止条項 5/5 OK.
