# Wave 46 tick6#10 — site/ 全 page fence_count 8/8 整合 STATE

**日時**: 2026-05-12
**Lane**: feat/jpcite_2026_05_12_wave46_fence_site_drift
**Worktree**: /tmp/jpcite-w46-fence-site
**Memory**: feedback_destruction_free_organization / feedback_completion_gate_minimal

---

## 1. 目的

Canonical fence_count = **8 業法** (税理士 / 弁護士 / 会計士 / 行政書士 / 司法書士 /
社労士 / 弁理士 / 労基) に対し、site/ surface text に旧 "6 業法" / "7 業法" /
"5 業法 + 36協定" のドリフトが 12 行残存していたため、numeric の整合性 (count
の 7→8 漏れ) のみを修正する。**法律名そのもの・36協定 等の surface 改ざんは
行わない** (CONSTITUTION 整合)。

## 2. 修正前の drift list (main HEAD `3ac9f652`)

```
site/llms.txt:469                       7 業法 + 関連法 (...弁理士法 §75 + ...)
site/legal-fence.html.md:17             # jpcite が触らない 6 業法
site/legal-fence.html.md:19             該当する 6 業法 (...社会保険労務士法 §27)
site/.well-known/mcp.json:275           7 業法フェンス (税理士/弁護士/...弁理士)
site/trust/purchasing.html:207          法令フェンス (5 業法 + 36協定)
                                          触らない 6 業法を 1 page で開示
site/trust/purchasing.html:268          6. 法令フェンス (5 業法 + 36協定)
site/trust/purchasing.html:269          全 6 業法の境界線
site/connect/chatgpt.html:37            Instructions に 7 業法 fence
site/connect/chatgpt.html:207           7 業法 fence とは?
site/connect/claude-code.html:210       7 業法 fence とは?
site/connect/codex.html:166             7 業法 fence とは?
site/connect/cursor.html:211            7 業法 fence とは?
```

**合計**: 12 hit、8 ファイル

## 3. 修正方針

- **数値のみ修正** (count = 8)。法律名そのもの (税理士法 §52 等) は触らない
- canonical legal-fence.html がすでに `8 業法 (... / 弁理士法 §75 / 労働基準法 §36)`
  と宣言済 (line 7/8/10/11/20/21/40/41/64/227/228 等) — site/ 内の他 page を
  これに合わせる
- purchasing.html §6 の bullet list には弁理士法 §75 / 労働基準法 §36 を 2 行追加
  (本文 8 業法と齐合)
- mcp.json description は 8 業法フェンス (税理士/弁護士/会計士/司法書士/行政書士/
  社労士/弁理士/労基) に変更
- 連発防止 test を tests/test_fence_site_count.py に新設 (~95 LOC)

## 4. 修正後の状態

```
$ grep -rn "6 業法\|7 業法\|5 業法" site/ --include="*.html" --include="*.md" \
    --include="*.txt" --include="*.json"
(no output → 0 hit)
```

**drift = 0**

## 5. 変更ファイル一覧

| Path | 変更内容 |
|------|---------|
| site/llms.txt | line 469: "7 業法 + 関連法" → "8 業法 + 関連法" (+労働基準法 §36 追記) |
| site/legal-fence.html.md | line 17/19: 見出し + lead "6 業法" → "8 業法" (+弁理士法 §75 / 労働基準法 §36) |
| site/.well-known/mcp.json | line 275: fence resource description "7 業法 (...中小企業診断士...)" → "8 業法 (...弁理士/労基)" |
| site/trust/purchasing.html | line 207: table cell "5 業法 + 36協定 / 6 業法を" → "8 業法 + 36協定 / 8 業法を" |
| site/trust/purchasing.html | line 268-269: §6 heading + lead "5 業法 + 36協定 / 6 業法" → "8 業法 + 36協定 / 8 業法" |
| site/trust/purchasing.html | line 276-277 後: 弁理士法 §75 + 労働基準法 §36 の bullet 2 行追加 |
| site/connect/chatgpt.html | line 37/207: schema.org HowToStep + FAQ summary "7 業法" → "8 業法" |
| site/connect/claude-code.html | line 210: FAQ summary "7 業法" → "8 業法" |
| site/connect/codex.html | line 166: FAQ summary "7 業法" → "8 業法" |
| site/connect/cursor.html | line 211: FAQ summary "7 業法" → "8 業法" |
| tests/test_fence_site_count.py | **新規** (~95 LOC), 6 test function (DRIFT_RE grep + CANONICAL_RE check) |
| docs/research/wave46/STATE_w46_tick6_fence_site.md | **本文書** (新規) |

## 6. test 結果

```
PASS test_no_5_6_7_gyohou_drift_in_site
PASS test_legal_fence_page_states_8_gyohou
PASS test_legal_fence_md_states_8_gyohou
PASS test_purchasing_page_states_8_gyohou
PASS test_llms_txt_states_8_gyohou
PASS test_connect_pages_state_8_gyohou_fence
```

(python3.12 standalone import 実行、6/6 PASS)

## 7. 禁止事項チェック

- [x] 法律名そのものは触らない (税理士法 §52 等は維持)
- [x] 8 業法 reasoning 全消し無し (canonical 内容は維持、count のみ整合)
- [x] main worktree 不使用 (`/tmp/jpcite-w46-fence-site` から作業)
- [x] 旧 brand (税務会計AI/AutonoMath/zeimu-kaikei.ai) は触らない
- [x] LLM API 不使用 (grep + manual edit のみ)
- [x] feedback_destruction_free_organization: 削除無し、すべて in-place 更新
- [x] feedback_completion_gate_minimal: blocker は drift = 0 の grep 1 軸のみ

## 8. PR

- **PR #143**: https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/143
- branch: `feat/jpcite_2026_05_12_wave46_fence_site_drift`
- commit: `99989a8fe` (1 commit; 10 files changed, +214 / -12)
- base: `origin/main` @ `3ac9f6524`
