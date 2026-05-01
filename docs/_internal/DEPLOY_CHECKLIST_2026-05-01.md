# Deploy Checklist — 2026-05-01

> 2026-05-01 safety override: CURRENT STATUS = **DEPLOY NO-GO** for the
> current dirty checkout. The commands below are operator checklist examples,
> not permission to run from this tree. Deploy only from a clean reviewed commit
> SHA after full tests, Docker context audit, migration guard, production
> snapshot check, and secret/publication audit are green.

jpcite production deploy gate. Production deploy only proceeds when the gates below are green and the operator selects an explicit clean commit SHA.

- **Operator**: Bookyou株式会社, 代表 梅田茂利
- **Contact**: info@bookyou.net
- **適格請求書発行事業者番号**: T8010001213708
- **Target version**: v0.3.2
- **Launch target**: 2026-05-06 — this checklist gates the 2026-05-01 deploy that precedes it.

---

## 最終 GO / NO-GO 判定

最後にこの欄を埋めて確定する。A〜E の全 P0 (本番 blocker) が緑なら GO。F は non-blocker、G は失敗時の rollback 戦略。

- [ ] **A. Pre-deploy 確認** すべて済
- [ ] **B. テストゲート** すべて pass
- [ ] **C. データ整合確認** 数値一致 / target 達成 or 段階展開明示
- [ ] **D. デプロイ手順** 全 step 完了
- [ ] **E. デプロイ後 smoke** 全 endpoint 200
- [ ] **F. 既知の Non-blocker** 把握済 (本番 push を止めない)
- [ ] **G. Rollback 戦略** snapshot + 直近 image tag 控え済

判定欄:

- [ ] **GO** — 全項目緑、本番 push 実行
- [ ] **NO-GO** — blocker 検出、修正後に再評価

判定者署名 (operator): _______________________   日時: _______________________

---

## A. Pre-deploy 確認 (5 項目)

- [ ] `git status` clean、全変更が reviewed file list に一致して commit 済
- [ ] `CHANGELOG.md` v0.3.2 エントリ追記済
- [ ] `CLAUDE.md` の current state (Section A 進捗 / 数値) が現状を反映
- [ ] OpenAPI spec 再生成済: `uv run python scripts/export_openapi.py --out docs/openapi/v1.json`
- [ ] 依存関係表 (下記 §依存関係) の version すべて 0.3.2 一致

## B. テストゲート (8 項目)

すべて `.venv/bin/` 経由で実行。CI green は前提だが、本番 push 前に手元で再走させる。

- [ ] Critical lint clean: `uv run ruff check src/jpintel_mcp tests scripts/etl scripts/cron tools/offline --select F,E9,B006,B008,B017,B018,B020,B904`
- [ ] `pytest tests/test_endpoint_smoke.py` pass
- [ ] `pytest tests/test_no_llm_in_production.py` pass
- [ ] `pytest tests/test_advisory_lock.py tests/test_audit_log.py tests/test_health_deep.py tests/test_universal_envelope.py tests/test_accounting.py` pass (新規追加 14 件分含む)
- [ ] `pytest tests/test_search_relevance.py tests/test_api.py` pass (`api/programs.py` 変更カバー)
- [ ] `uv run mypy src/jpintel_mcp/ --exclude '_archive'` 件数 73 以下
- [ ] `mkdocs build --strict` clean
- [ ] (任意) `pytest tests/e2e/` Playwright suite pass — gate 入りは手動

## C. データ整合確認 (8 項目)

CLAUDE.md と DB 実値の突合。**target に届かない A5 / B13 は段階展開として明示**、blocker 扱いしない。

- [ ] `data/jpintel.db` の `programs` 行数 = **14,472** (searchable 11,684 / quarantine X = 2,788)
- [ ] `autonomath.db` の `am_entities` 行数 = **503,930**
- [ ] **A4** `am_source.content_hash` NULL = **0** (達成済)
- [ ] **A5** `am_source.last_verified` 件数 ≥ **6,667** — 段階展開、target 95,000 (進行中、blocker ではない)
- [ ] **A6** `am_entity_facts.source_id` 件数 ≥ **2,461,196** (source_id 伝播の現在値)
- [ ] **D9** `programs.aliases_json` non-empty = **9,996** (達成済)
- [ ] **B13** prefecture 欠損 = **6,011** / municipality 欠損 = **11,350** (進行中、blocker ではない)
- [ ] **E1** `analysis_wave18/license_review_queue.csv` 1,425 data rows / 1,426 lines incl. header (達成済)

確認クエリ例:

```bash
sqlite3 data/jpintel.db "SELECT COUNT(*) FROM programs;"
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_entities;"
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_source WHERE content_hash IS NULL;"
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_source WHERE last_verified IS NOT NULL;"
sqlite3 autonomath.db "SELECT COUNT(*) FROM am_entity_facts WHERE source_id IS NOT NULL;"
sqlite3 data/jpintel.db "SELECT COUNT(*) FROM programs WHERE aliases_json IS NOT NULL AND aliases_json != '[]';"
sqlite3 data/jpintel.db "SELECT SUM(CASE WHEN prefecture IS NULL OR prefecture='' THEN 1 ELSE 0 END), SUM(CASE WHEN municipality IS NULL OR municipality='' THEN 1 ELSE 0 END) FROM programs;"
wc -l analysis_wave18/license_review_queue.csv
```

## D. デプロイ手順 (5 項目)

CLAUDE.md `Release checklist` 準拠。各コマンドは gate green 後、clean commit SHA に対して operator が実行する。

- [ ] PyPI publish は package contents audit 後に operator-only (`PYPI_TOKEN` 必要)
- [ ] MCP registry publish は manifest audit 後に operator-only
- [ ] Cloudflare Pages 自動 deploy (`main` push を trigger)
- [ ] Fly deploy は snapshot ID / rollback image tag 記録後に operator-only
- [ ] tag / push は reviewed commit SHA に対して operator-only

注: autonomath-target migrations は `entrypoint.sh` §4 で `data/autonomath.db` に自動適用される。`fly.toml` の `release_command` を有効化しない (CLAUDE.md gotcha 参照)。

## E. デプロイ後 smoke (4 項目)

deploy 完了から 5 分以内に確認。1 つでも 200 が返らなければ §G rollback 検討。

- [ ] `curl -fsS 'https://api.jpcite.com/v1/programs/search?q=補助金'` 200 + JSON envelope
- [ ] `curl -fsS https://jpcite.com` 200 (Cloudflare Pages apex)
- [ ] MCP server 経由で `list_open_programs` が `tools/call` で 200 envelope を返す (operator の DXT 接続で確認)
- [ ] Stripe webhook 着弾確認 (`/v1/billing/webhook` への直近 event 記録 + dashboard ログ)

## F. 既知の Non-blocker (3 項目)

下記は本番 push を止めない。launch 後に対応。

- [ ] `tests/test_license_gate.py` (修正中、CI で skip / xfail されている)
- [ ] `tests/test_short_ascii_perf.py` (rate limit harness drift、本番 path に影響なし)
- [ ] migrations 105-119 の rollback 欠落 (既存運用 risk、deploy blocker ではない。CRITICAL list は §G 参照)

## G. Rollback 戦略 (3 項目)

deploy 失敗時の戻し手順。**事前に snapshot ID と直近 image tag を控えておく**。

- [ ] **Pre-deploy backup**: `fly volumes snapshots create <volume-id> --app autonomath-api --json` を deploy 直前に実行、snapshot ID を記録
- [ ] **DB rollback**: `scripts/migrations/*_rollback.sql` (一部のみ完備、現状 `065_compat_matrix_uni_id_backfill_rollback.sql` と `082_relation_density_expansion_rollback.sql` の 2 本のみ。migrations 105-119 は rollback なし — 失敗時は snapshot 復元一択)
- [ ] **Code rollback**: `fly deploy --image <previous-tag>` で直前 image に戻す。直近の安定 tag を ` fly releases list` で確認しておく

---

## 依存関係 (version 一致表)

すべて **0.3.2** で揃っていること。1 つでもズレたら NO-GO。

| ファイル | キー | 期待値 | 確認方法 |
|---|---|---|---|
| `pyproject.toml` | `version = "..."` | 0.3.2 | `grep '^version' pyproject.toml` |
| `server.json` | `"version"` (top-level + packages[].version) | 0.3.2 | `grep '"version"' server.json` |
| `dxt/manifest.json` | `"version"` | 0.3.2 | `grep '"version"' dxt/manifest.json` |
| `smithery.yaml` | `version: "..."` | 0.3.2 | `grep version smithery.yaml` |

確認 one-liner:

```bash
uv run python - <<'PY'
import json, re, sys
from pathlib import Path
expected = "0.3.2"
checks = {
    "pyproject.toml": re.search(r'^version = "([^"]+)"', Path("pyproject.toml").read_text(), re.M).group(1),
    "server.json": json.loads(Path("server.json").read_text())["version"],
    "server.json packages": json.loads(Path("server.json").read_text())["packages"][0]["version"],
    "dxt/manifest.json": json.loads(Path("dxt/manifest.json").read_text())["version"],
    "smithery.yaml": re.search(r'^\s*version:\s*"?([^"\n]+)"?', Path("smithery.yaml").read_text(), re.M).group(1),
}
bad = {k: v for k, v in checks.items() if v != expected}
print(checks)
sys.exit(1 if bad else 0)
PY
```

---

## Section 項目集計

- A. Pre-deploy 確認: **5**
- B. テストゲート: **8**
- C. データ整合確認: **8**
- D. デプロイ手順: **5**
- E. デプロイ後 smoke: **4**
- F. 既知の Non-blocker: **3**
- G. Rollback 戦略: **3**
- 最終 GO/NO-GO 判定: **9** (7 section gate + GO/NO-GO 2 択)

**合計 unchecked checkbox 数: 45** (deploy 開始時点で全 unchecked)
**checked: 0**

---

## Contact

**Bookyou株式会社**
info@bookyou.net
適格請求書発行事業者番号 T8010001213708
代表 梅田茂利
