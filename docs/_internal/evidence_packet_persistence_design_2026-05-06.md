# Evidence Packet persistence design 2026-05-06

## 目的

`src/jpintel_mcp/services/evidence_packet.py` は現在、明示的に `NO writes` の read-only composer として設計されている。Evidence Packet persistence は、この composer を壊さず、REST 境界で optional に保存できる薄い入口を追加する。

この設計のゴールは以下。

- 既存 Evidence Packet のレスポンス shape と composer の read-only 性を維持する。
- `persist=true` を指定した場合だけ、返却済み Evidence Packet を後から参照・監査できる台帳へ保存する。
- 匿名 3 回/日の無料体験は、保存機能の所有者確認と長期保持から切り離す。
- `audit_seal` と Merkle anchor の役割を分離し、二重管理や不整合を避ける。

## 調査結果

対象ファイルから確認した現状。

- `services/evidence_packet.py`
  - module docstring が `NO writes` を明示している。
  - `EvidencePacketComposer._open_ro()` が SQLite URI `mode=ro` で DB を開く。
  - `compose_for_program()` / `compose_for_houjin()` / `compose_for_query()` は envelope を合成して返すだけ。
  - packet id は `evp_<16hex>` 形式。
  - in-memory TTL cache があるため、同じ入力でも保存責務を composer に入れると cache hit と write の関係が壊れる。

- `api/evidence.py`
  - REST endpoint は composer 呼び出し後に `_gate_evidence_envelope()` で license gate を適用する。
  - JSON の場合だけ `attach_seal_to_body()` を呼び、paid key では `audit_seal` が付く。
  - anonymous conversion CTA は audit seal の後に付与され、seal hash surface から外されている。
  - `log_usage()` は最後に呼ばれ、匿名 quota は router mount の `AnonIpLimitDep` で処理される。

- `api/_audit_seal.py`
  - `attach_seal_to_body()` は `api_key_hash` がない場合 no-op。
  - paid JSON response では `audit_seal` を body に付け、`audit_seals` に best-effort persist する。
  - `audit_seal` は response hash / request hash / source_urls / HMAC の真正性証明であり、Evidence Packet 本体の検索用保存ではない。

- `scripts/migrations/146_audit_merkle_anchor.sql`
  - `audit_merkle_anchor` / `audit_merkle_leaves` は日次 Merkle root と leaf を保存する。
  - 現行 cron は `usage_events` から `evp_<usage_events.id>` を作る設計で、composer の `packet_id` と同一ではない可能性がある。
  - `evidence_packet_id` から inclusion proof を引くための列は既にある。

- `tests/test_evidence_packet*.py`
  - composer の read-only DB 前提、citation status、packet profile、REST/MCP surface が広くテストされている。
  - persistence を composer に直接混ぜると既存 fixture DB に write table を要求し、回帰範囲が過大になる。

## 方針

### composer は read-only のまま固定する

`EvidencePacketComposer` に DB write、保存フラグ、保存先 connection、audit seal、user/key 情報を入れない。composer の責務は「現在の corpus から Evidence Packet envelope を合成する」だけに固定する。

保存は新規 module `src/jpintel_mcp/services/evidence_packet_persistence.py` で扱う。入口は REST handler 側に置く。

推奨フロー:

1. `api/evidence.py` が composer から envelope を受け取る。
2. `_gate_evidence_envelope()` で license gate 済みの公開可能 envelope にする。
3. JSON の場合は既存通り `attach_seal_to_body()` を実行する。
4. `persist=true` かつ保存可能な caller の場合だけ、`persist_evidence_packet(conn, envelope, request_meta, ctx)` を呼ぶ。
5. 保存結果を JSON response に `persistence` block として追加する。CSV/MD は body に保存情報を埋めず、header か JSON のみ対応から始める。
6. 既存 `log_usage()` はそのまま呼ぶ。

保存対象は「composer 生 envelope」ではなく、「license gate と audit seal 適用後に caller へ返す JSON envelope」を canonical JSON 化したものにする。これにより、後日参照される内容と実際に顧客が受け取った内容が一致する。

## schema 案

想定 migration: `scripts/migrations/177_evidence_packet_persistence.sql`

DB は `jpintel.db` 側に置く。理由は API key、usage、audit_seals と同じ customer/account 境界であり、`autonomath.db` は corpus/read-heavy asset として扱うため。

### `evidence_packet`

1 packet response につき 1 row。

```sql
CREATE TABLE IF NOT EXISTS evidence_packet (
    packet_id              TEXT PRIMARY KEY,
    endpoint               TEXT NOT NULL,
    subject_kind           TEXT,
    subject_id             TEXT,
    query_hash             TEXT NOT NULL,
    request_params_json    TEXT,
    api_key_hash           TEXT NOT NULL,
    client_tag             TEXT,
    corpus_snapshot_id     TEXT,
    api_version            TEXT,
    packet_profile         TEXT,
    output_format          TEXT NOT NULL DEFAULT 'json',
    record_count           INTEGER NOT NULL DEFAULT 0,
    content_hash           TEXT NOT NULL,
    body_json              TEXT NOT NULL,
    audit_seal_id          TEXT,
    audit_call_id          TEXT,
    known_gaps_json        TEXT NOT NULL DEFAULT '[]',
    license_gate_json      TEXT,
    persisted_at           TEXT NOT NULL DEFAULT (datetime('now')),
    retention_until        TEXT,
    deleted_at             TEXT,
    FOREIGN KEY(api_key_hash) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_evidence_packet_key_created
    ON evidence_packet(api_key_hash, persisted_at);

CREATE INDEX IF NOT EXISTS idx_evidence_packet_subject
    ON evidence_packet(subject_kind, subject_id, persisted_at);

CREATE INDEX IF NOT EXISTS idx_evidence_packet_audit_seal
    ON evidence_packet(audit_seal_id)
    WHERE audit_seal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_packet_query_hash
    ON evidence_packet(api_key_hash, query_hash, persisted_at);
```

Notes:

- `request_params_json` は raw query を含み得るため、保存前に既存の canonical params 方針へ寄せる。query text は PII を含む可能性があるので、最小実装では `query_hash` 必須、`request_params_json` は allow-list field のみ保存する。
- `body_json` は caller へ返す JSON envelope の canonical JSON。CSV/MD 保存は初期対象外。
- `content_hash` は `sha256(canonical body_json)`。`audit_seal.subject_hash` / `response_hash` と比較できる。
- `audit_seal_id` と `audit_call_id` は `audit_seals` への緩い参照。SQLite FK は migration drift を避けるため必須にしない。
- `retention_until` は paid key の保存ポリシーに従う。初期値は 7 年にせず、プロダクト保存期間を別途決める。税務証跡の 7 年保持は `audit_seals` 側の責務。

### `evidence_packet_item`

packet 内の `records[]` と主要 citation/source を検索しやすくする派生 row。本文の正本は `evidence_packet.body_json`。

```sql
CREATE TABLE IF NOT EXISTS evidence_packet_item (
    packet_id                    TEXT NOT NULL,
    item_index                   INTEGER NOT NULL,
    entity_id                    TEXT,
    subject_kind                 TEXT,
    subject_id                   TEXT,
    primary_name                 TEXT,
    source_url                   TEXT,
    citation_verification_status TEXT,
    citation_verified_at         TEXT,
    fact_count                   INTEGER NOT NULL DEFAULT 0,
    rule_count                   INTEGER NOT NULL DEFAULT 0,
    item_hash                    TEXT NOT NULL,
    item_json                    TEXT NOT NULL,
    PRIMARY KEY(packet_id, item_index),
    FOREIGN KEY(packet_id) REFERENCES evidence_packet(packet_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_packet_item_entity
    ON evidence_packet_item(entity_id, packet_id);

CREATE INDEX IF NOT EXISTS idx_evidence_packet_item_source
    ON evidence_packet_item(source_url);

CREATE INDEX IF NOT EXISTS idx_evidence_packet_item_status
    ON evidence_packet_item(citation_verification_status);
```

Notes:

- `item_json` は `records[item_index]` の canonical JSON。
- `item_hash` は `sha256(item_json)`。
- `citation_verification_status` は record の代表値として、`evidence_value.citations[]` から `entity_id + source_url` で拾える最も強い status を保存する。複数 citation の完全な一覧は `body_json` に残す。
- 将来 `source_document_id` / `fact_id` / `citation_verification_id` が正規化されたら nullable column を追加する。現時点では既存 composer がその ID を安定して返していないため、先に `entity_id` / `source_url` / hash で運用する。

## REST API 追加方針

### single GET

`GET /v1/evidence/packets/{subject_kind}/{subject_id}?persist=true`

追加 query parameter:

- `persist: bool = false`

初期制約:

- `output_format=json` のみ保存可能。
- `ctx.key_hash` がない anonymous caller は保存不可。
- 既存 response shape は壊さず、保存した場合だけ top-level に以下を追加する。

```json
{
  "persistence": {
    "persisted": true,
    "packet_id": "evp_...",
    "content_hash": "sha256:...",
    "retrieve_endpoint": "/v1/me/evidence/packets/evp_...",
    "audit_seal_id": "seal_..."
  }
}
```

保存しない通常リクエストでは `persistence` block を出さない。`persist=false` が既定なので、既存 client の JSON parser への影響を最小化する。

### query POST

`POST /v1/evidence/packets/query?persist=true`

追加 query parameter:

- `persist: bool = false`

request body に `persist` を入れない。既存 `EvidencePacketQueryBody` の意味を増やすより、GET と同じ query parameter に統一する。

### retrieve endpoint

保存実装スライスでは、以下の read endpoint を同時に設計する。

- `GET /v1/me/evidence/packets/{packet_id}`
- `GET /v1/me/evidence/packets?limit=...&cursor=...`

認可:

- `api_key_hash` が一致する row だけ返す。
- operator/admin 向け横断検索は別 endpoint に分ける。

## 匿名 3 回/日の保存方針

匿名 caller は durable persistence しない。

理由:

- `attach_seal_to_body()` は anonymous では no-op で、所有者付きの `audit_seal` がない。
- 後日取得 endpoint で本人性を確認する安定 identifier がない。
- query text に個人情報や顧問先情報が混入する可能性があり、IP hash だけで長期保存するのはリスクが高い。
- 現在の anonymous 3 回/日は product discovery のための read quota であり、保存台帳の無料枠ではない。

挙動案:

- anonymous + `persist=false`: 既存通り。保存しない。
- anonymous + `persist=true`: `401` か `403` で `api_key_required_for_persistence` を返す。
- anonymous の 3 回/日 quota は Evidence Packet compose そのものにだけ適用する。保存失敗を別 quota として数えないため、認証チェックは composer 実行前に置く。

将来、共有リンクやサンプル保存が必要になった場合でも、`evidence_packet` 本表ではなく TTL 付き ephemeral cache として別設計にする。

## paid key 自動保存の是非

初期実装では paid key でも自動保存しない。`persist=true` の明示 opt-in のみにする。

理由:

- Evidence Packet は query text と顧客業務文脈を含むことがある。明示 opt-in なしの本文保存は説明責任が重い。
- paid key の高頻度利用で `body_json` が急増し、SQLite volume と backup サイズが読みにくくなる。
- 既に paid JSON response には `audit_seal` と `audit_seals` 保存があるため、真正性証明だけなら自動保存なしでも成立する。
- 初期段階では retrieval UX と削除/保持ポリシーを検証しながら保存量を制御したい。

将来案:

- `api_keys` または customer settings に `auto_persist_evidence_packets INTEGER DEFAULT 0` を追加する。
- dashboard で明示有効化した key だけ auto-save。
- endpoint 単位 opt-out と `X-JPCite-Persist: false` を用意する。

## audit_seal / Merkle anchor との関係

### audit_seal

`audit_seal` は「この response body が Bookyou の secret で署名された」ことを示す HMAC 証跡。Evidence Packet persistence は「その response body を後から取得できるように保存する」台帳。

関係:

- paid JSON + `persist=true` では、`attach_seal_to_body()` 後の body を保存する。
- `evidence_packet.audit_seal_id` には `body["audit_seal"]["seal_id"]` を入れる。
- `evidence_packet.audit_call_id` には legacy `call_id` を入れる。
- `evidence_packet.content_hash` は保存 body の hash。`audit_seal.response_hash` または `subject_hash` と一致確認できる。

注意:

- anonymous は `audit_seal` が付かないので persistence 不可。
- conversion CTA は既存通り seal 後に付くため、保存対象に含めないか、保存前に除外する。証跡対象は evidence content に限定する。

### Merkle anchor

現行 migration 146 / cron は `usage_events` の row id から `evp_<usage_events.id>` を作って Merkle leaf にしている。一方、Evidence Packet composer の `packet_id` は `evp_<uuid16>`。このままだと `GET /v1/audit/proof/{packet_id}` と保存 packet の ID がずれる。

推奨修正方針:

- Evidence Packet persistence の `packet_id` を正とする。
- Merkle leaf は保存済み `evidence_packet` row を対象にする。
- leaf hash は `sha256(packet_id || content_hash || persisted_at)` にする。
- `audit_merkle_leaves.evidence_packet_id` には `evidence_packet.packet_id` を入れる。

移行上の注意:

- 既存 `usage_events` based anchor は billing call 証跡として意味があるが、Evidence Packet 本文の inclusion proof とは別物。
- 後続実装では cron を `usage_events` leaf と `evidence_packet` leaf のどちらに寄せるか決める。Evidence Packet persistence の目的からは `evidence_packet` leaf が自然。
- 既存 `/v1/audit/proof/{evidence_packet_id}` は `audit_merkle_leaves` を読むだけなので、leaf producer を切り替えても read API は維持できる。

## 実装順序

1. `177_evidence_packet_persistence.sql` を追加する。
   - `evidence_packet`
   - `evidence_packet_item`
   - indexes
   - rollback migration も追加する。

2. `services/evidence_packet_persistence.py` を追加する。
   - `canonical_json()`
   - `sha256_hex()`
   - `build_packet_rows()`
   - `persist_evidence_packet(conn, envelope, request_meta, ctx)`
   - composer import は不要。保存 service は envelope dict だけを見る。

3. REST に `persist: bool = false` を追加する。
   - `GET /v1/evidence/packets/{subject_kind}/{subject_id}`
   - `POST /v1/evidence/packets/query`
   - anonymous + `persist=true` は composer 実行前に reject。
   - `output_format != json && persist=true` は `422`。

4. paid JSON path で保存を呼ぶ。
   - license gate 後。
   - audit seal 後。
   - conversion CTA 前、または保存前に CTA を除外。
   - 保存失敗は初期段階では `500` ではなく `persistence.persisted=false` + warning にするか、明示保存要求なので `503` にするかを product で決める。証跡用途を重視するなら `persist=true` の失敗は `503` が妥当。

5. retrieval endpoint を追加する。
   - `GET /v1/me/evidence/packets/{packet_id}`
   - `GET /v1/me/evidence/packets`
   - key owner check 必須。

6. Merkle anchor producer を evidence_packet row 対応に更新する。
   - migration 146 の table は流用可能。
   - cron の leaf source を `evidence_packet` にするか、別 mode を追加する。

## テスト案

### migration / schema

- migration 適用後に `evidence_packet` / `evidence_packet_item` と index が存在する。
- rollback で追加 table/index が消える。
- `packet_id` primary key と `(packet_id, item_index)` primary key が効く。

### persistence service

- envelope から `content_hash` と `item_hash` が deterministic に生成される。
- `records[]` が 0 件でも `evidence_packet` row は保存され、`evidence_packet_item` は 0 件。
- `known_gaps_json` が `quality.known_gaps` から保存される。
- `audit_seal_id` / `audit_call_id` が body から抽出される。
- 同じ `packet_id` の二重保存は idempotent に扱うか明示エラーにする。

### REST

- 既存 `persist` 未指定の `tests/test_evidence_packet*.py` は保存 table なしでも通る。
- paid key + `persist=true` + JSON で `evidence_packet` と `evidence_packet_item` が保存され、response に `persistence.persisted=true` が付く。
- paid key + `persist=true` + `output_format=csv` は `422`。
- anonymous + `persist=true` は composer 実行前に `401/403` になり、保存 row が作られない。
- anonymous + `persist=false` は既存通り 3 回/日の read quota だけ消費する。
- `persist=true` の保存 body hash が `audit_seal.response_hash` と一致する。

### retrieval

- owner key は保存 packet を取得できる。
- 別 key は `404` または `403`。
- list endpoint は `api_key_hash` scope のみ返す。
- deleted row は取得不可。

### audit / merkle

- 日次 cron が `evidence_packet` row から `audit_merkle_leaves.evidence_packet_id = packet_id` を生成できる。
- `/v1/audit/proof/{packet_id}` が保存 packet の Merkle proof を返せる。
- `leaf_hash = sha256(packet_id || content_hash || persisted_at)` を verifier が再計算できる。

## 未決事項

- `persist=true` で保存失敗した場合、response を失敗にするか、packet は返して warning にするか。
- paid key auto-save を将来入れる場合の customer setting table。
- `body_json` の retention。`audit_seals` は 7 年保持だが、Evidence Packet 本文は同じ期間である必要はない。
- Merkle anchor を `usage_events` と `evidence_packet` の両方にするか、Evidence Packet 本文証跡へ寄せるか。
