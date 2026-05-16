# R22 (P0) — Release Capsule Manifest の読み方

> AI agent 向け recipe。jpcite の **Release Capsule** は 1 リリースで agent / 公開 surface に出る全 artifact を 1 manifest にまとめた contract。21 個の `generated_surfaces` + 4 個の Wave 50 新規 gate artifact + 3 個の inline packet を `sha256` で chain し、`runtime_pointer.json` 経由で本番が **どの capsule を見ているか** を 1 file の pointer rollback だけで戻せる。manifest 改ざんは `scripts/check_schema_contract_parity.py` で round-trip 検出される。

- **Audience**: AI agent builder (cohort: `agent_builder`) + 運用者
- **Cost**: manifest 自体は static, ¥0 (capsule artifact 内の packet は outcome 価格に従う)
- **Sensitive**: capsule に含む全 disclaimer envelope (§52 / §72 / §1 / §47条の2) は packet 単位で再貼り付け

## TL;DR

```
release_capsule_manifest.json
  ├─ capsule_id           ("rc1-p0-bootstrap-2026-05-16")
  ├─ capsule_state        ("candidate" / "active" / "superseded")
  ├─ generated_surfaces[] (21 artifact, 各 sha256 + path)
  ├─ gate_artifacts[]     (4 Wave 50 新規 — policy_decision_catalog / csv_private_overlay_contract / billing_event_ledger / aws_budget_canary_attestation)
  ├─ inline_packets[]     (3 free inline — outcome_catalog / capability_matrix / gap_coverage)
  └─ root_sha256          (全 entry の sha256 を concatenate して再 hash した chain root)

runtime_pointer.json
  ├─ active_capsule_id    ("rc1-p0-bootstrap-2026-05-16")
  ├─ previous_capsule_id  ("rc1-p0-bootstrap-2026-05-15")  # rollback target
  └─ promoted_at
```

`active` capsule は **1 つだけ** で、`candidate` → `active` 遷移は `runtime_pointer.json` の `active_capsule_id` 書換のみ。前 capsule は **削除せず** `superseded` に flip + pointer の `previous_capsule_id` に残す → 1 file 書換だけで rollback。

## capsule_state 3 値

| state | 意味 | runtime pointer の扱い |
|---|---|---|
| `candidate` | preflight gate に通したが本番未公開 | pointer から参照されない |
| `active` | 本番公開中 | `runtime_pointer.active_capsule_id` がこの id |
| `superseded` | 旧 active、rollback 用に残す | `previous_capsule_id` がこの id |

`active` → `superseded` 遷移は新 capsule が `active` に promote された瞬間に **自動的に** 行われる (pointer 側の 1 write が両 capsule の論理 state を反転)。capsule artifact 自体は immutable で、`capsule_state` は manifest 内の宣言値だが、source of truth は **pointer**。

## generated_surfaces 21 件 + 4 gate artifact

```json
{
  "capsule_id": "rc1-p0-bootstrap-2026-05-16",
  "capsule_state": "active",
  "generated_surfaces": [
    {"surface_id": "outcome_catalog",                  "path": "site/releases/rc1-p0-bootstrap/outcome_catalog.json",                 "sha256": "..."},
    {"surface_id": "openapi_v1",                        "path": "docs/openapi/v1.json",                                                "sha256": "..."},
    {"surface_id": "llms_txt",                          "path": "site/llms.txt",                                                       "sha256": "..."},
    {"surface_id": "well_known_jpcite",                 "path": "site/.well-known/jpcite.json",                                        "sha256": "..."},
    {"surface_id": "p0_facade_route_jpcite_route",      "path": "site/releases/rc1-p0-bootstrap/p0_jpcite_route.json",                 "sha256": "..."},
    {"surface_id": "p0_facade_route_preview_cost",      "path": "site/releases/rc1-p0-bootstrap/p0_preview_cost.json",                 "sha256": "..."},
    {"surface_id": "p0_facade_route_execute_packet",    "path": "site/releases/rc1-p0-bootstrap/p0_execute_packet.json",               "sha256": "..."},
    {"surface_id": "p0_facade_route_get_packet",        "path": "site/releases/rc1-p0-bootstrap/p0_get_packet.json",                   "sha256": "..."}
  ],
  "gate_artifacts": [
    {"gate_id": "policy_decision_catalog",              "schema": "schemas/jpcir/policy_decision_catalog.schema.json",                 "sha256": "..."},
    {"gate_id": "csv_private_overlay_contract",         "schema": "schemas/jpcir/csv_private_overlay_contract.schema.json",            "sha256": "..."},
    {"gate_id": "billing_event_ledger",                 "schema": "schemas/jpcir/billing_event_ledger.schema.json",                    "sha256": "..."},
    {"gate_id": "aws_budget_canary_attestation",        "schema": "schemas/jpcir/aws_budget_canary_attestation.schema.json",           "sha256": "..."}
  ],
  "inline_packets": [
    {"packet_id": "outcome_catalog_summary",  "ttl_seconds": 86400},
    {"packet_id": "capability_matrix",        "ttl_seconds": 86400},
    {"packet_id": "gap_coverage_summary",     "ttl_seconds": 86400}
  ],
  "root_sha256": "sha256:concat(all entries)"
}
```

## sha256 chain の検証 (agent 側)

agent は capsule を信用する前に下記を実行:

```python
import hashlib, json
manifest = json.loads(open("site/releases/rc1-p0-bootstrap/release_capsule_manifest.json").read())

# 1. 各 surface の sha256 を local file から再計算
for s in manifest["generated_surfaces"]:
    actual = hashlib.sha256(open(s["path"], "rb").read()).hexdigest()
    assert actual == s["sha256"].removeprefix("sha256:"), f"sha mismatch: {s['surface_id']}"

# 2. chain root を再計算
joined = "".join(s["sha256"] for s in manifest["generated_surfaces"] + manifest["gate_artifacts"])
root = "sha256:" + hashlib.sha256(joined.encode()).hexdigest()
assert root == manifest["root_sha256"]
```

mismatch を検出した capsule は **使わない** (pointer 経由で `previous_capsule_id` に手動 rollback)。

## pointer rollback (1 file 書換)

```bash
# 現在 active を確認
jq '.active_capsule_id' site/releases/runtime_pointer.json
# => "rc1-p0-bootstrap-2026-05-16"

# 前 capsule に戻す
jq '.previous_capsule_id as $prev | .active_capsule_id as $cur |
    .active_capsule_id = $prev | .previous_capsule_id = $cur |
    .promoted_at = (now | strftime("%Y-%m-%dT%H:%M:%S+09:00"))' \
   site/releases/runtime_pointer.json > /tmp/pointer.new.json
mv /tmp/pointer.new.json site/releases/runtime_pointer.json
```

公開 surface (OpenAPI / llms.txt / .well-known) は **静的 file をそのまま** rollback 先 capsule から読み出すので、配信側の cache invalidate さえ走れば即時切替。

## Error handling

| 検出 | 意味 | agent 側の対処 |
|---|---|---|
| `root_sha256` mismatch | capsule 改ざん / file 欠落 | 当該 capsule 使わず pointer rollback |
| `capsule_state == "candidate"` で `active_capsule_id` 指している | preflight 未通過 | pointer 修正、CI で blocked |
| `previous_capsule_id` が null | 初回 active、rollback 不能 | candidate を 1 つ確保してから promote |
| schema file 未登録 (`gate_artifacts` に無い) | jpcir registry 漏れ | `schemas/jpcir/_registry.json` 追記 |

## 関連

- [R17 — 4 P0 Facade Tools](r17_4_p0_facade_tools.md)
- [R18 — 14 Outcome Contract](r18_14_outcome_contracts.md)
- [R23 — 5 Preflight Gate](r23_5_preflight_gates.md) (capsule を gate 通過させる順序)
- [R24 — billing_event_ledger](r24_billing_event_ledger.md)
- contract: `schemas/jpcir/release_capsule_manifest.schema.json`
- registry: `schemas/jpcir/_registry.json`
- parity check: `scripts/check_schema_contract_parity.py`
