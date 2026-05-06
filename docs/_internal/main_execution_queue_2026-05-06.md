# 本体実行キュー 2026-05-06

## 現在の状態

外部CLI-Aの SourceProfile は本体側で受け取り済み。CLI-Bの市場/完成物側は継続確認対象。

- CLI-A: 一次情報ソース / 取得方式 / 利用条件 / schema backlog 受け取り済み
- CLI-B: 課金される完成物 / persona価値 / benchmark / 初回3回無料体験

本体側は外部CLIの終了待ちをしない。受け皿は作成済みなので、次は完成物APIとETL接続へ進める。

## いま本体がやること

### 1. Evidence Packet永続化の前提整理

現状:

- `src/jpintel_mcp/services/evidence_packet.py` は明示的に `NO writes`
- Evidence Packetは都度合成で、保存台帳は未実装
- 既存API shapeを壊してはいけない

進め方:

- 既存 composer は読み取り専用のまま維持
- optional persistence を別モジュールとして設計する
- `persist=true` または有料key自動保存の設計だけ先に切る
- 匿名3回枠は保存しない、または短期保持にする

### 2. Corpus Snapshot / Source Document / Artifact / Extracted Fact のschema案を固める

外部CLIの結果に左右されない中核テーブル:

- `corpus_snapshot`
- `artifact`
- `source_document`
- `extracted_fact`
- `entity_id_bridge`
- `evidence_packet`
- `evidence_packet_item`

これらは、後からgBizINFO、EDINET、NTA、調達、官報などが増えても共通で使う。

状態:

- `172_corpus_snapshot.sql`
- `173_artifact.sql`
- `174_source_document.sql`
- `175_extracted_fact.sql`
- `176_source_foundation_domain_tables.sql`

上記は実装済み。`tests/test_derived_data_layer_migrations.py` で2回適用とrollbackを確認する。

### 3. 既存derived layerとの接続確認

既に存在するが未適用/未活用のmigration:

- `scripts/migrations/170_program_decision_layer.sql`
- `scripts/migrations/171_corporate_risk_layer.sql`

本体側はこれを以下のartifactへ接続する。

- `compatibility_table`
- `houjin_dd_pack`
- `application_kit`
- `tax_client_impact_memo`
- `monitoring_digest`

### 4. Artifact APIの共通response contractを先に決める

全artifactは最低限以下を返す。

```json
{
  "artifact_id": "art_...",
  "artifact_type": "houjin_dd_pack",
  "corpus_snapshot_id": "snap_...",
  "packet_id": "pkt_...",
  "summary": {},
  "sections": [],
  "sources": [],
  "known_gaps": [],
  "next_actions": [],
  "human_review_required": [],
  "audit_seal": {}
}
```

目的:

- 外部CLI-Bが完成物カタログを出した後、response shapeへ落としやすくする
- GPT / Claude / Cursor に渡すとき、毎回同じ構造で読ませる
- 「候補一覧」ではなく「完成物」として返す

## 外部CLIの結果が来たらやること

### CLI-A受け取り

読み込むファイル:

- `tools/offline/_inbox/public_source_foundation/source_profiles_YYYY-MM-DD.jsonl`
- `tools/offline/_inbox/public_source_foundation/schema_backlog.md`
- `tools/offline/_inbox/public_source_foundation/risk_register.md`

処理:

1. P0ソースだけ抽出
2. `source_document` で受けられる項目と、個別tableが必要な項目を分ける
3. APIキー・利用規約・robotsリスクがあるものは実装キューから外す
4. join keyが明確なものから `entity_id_bridge` に接続する

### CLI-B受け取り

読み込むファイル:

- `tools/offline/_inbox/output_market_validation/artifact_catalog.md`
- `tools/offline/_inbox/output_market_validation/persona_value_map.md`
- `tools/offline/_inbox/output_market_validation/benchmark_design.md`

処理:

1. 最初に売るpersonaを1つに絞る
2. そのpersona向けartifactを1つだけ最小実装する
3. benchmark queryをテストケース化する
4. 初回3回無料で見せるサンプル導線に反映する

## 先にやらないこと

- 公開サイトの数字を今すぐ変えない
- 価格を変えない
- WAF本番変更をいきなり行わない
- 外部CLIが収集中のソースを先回りして実装しない
- Evidence Packet composer を直接write可能にしない

## 最初の実装スライス候補

### Slice 1: schema-only foundation

目的:

- 既存API挙動を変えずに、台帳を追加できる状態にする

対象:

- `172_corpus_snapshot.sql`
- `173_artifact.sql`
- `174_source_document.sql`
- `175_extracted_fact.sql`
- `176_source_foundation_domain_tables.sql`
- rollback migration
- schema guard test

状態:

- 実装済み。
- `compatibility_table` artifact API も最初の完成物として実装済み。

### Slice 2: domain source ETL receivers

目的:

- 外部CLI-Aの P0/P1 情報源を、既存API正本へ安全に接続する

対象:

- `houjin_change_history` への法人番号差分取り込み
- `am_enforcement_source_index` へのFSA/JFTC/MHLW/MLIT source row投入
- `law_revisions` / `law_attachment` へのe-Gov revision metadata投入
- `procurement_award` へのp-portal落札明細投入

注意:

- 既存 `bids` / `am_enforcement_detail` / `laws` / `am_law` をいきなり正本変更しない。
- companion table で受け、reconcile jobで既存API正本へ反映する。

### Slice 3: packet persistence design

目的:

- Evidence Packetを後から参照できるようにする

対象:

- `177_evidence_packet_persistence.sql`
- `services/evidence_packet_persistence.py`
- `persist=true` のAPI設計
- existing endpoint regression

### Slice 4: next paid artifact

目的:

- `compatibility_table` の次に、有料ユーザーが「完成物」として受け取れる深い回答を返す

候補:

- `houjin_dd_pack`
- `monitoring_digest`
- `tax_client_impact_memo`

判断軸:

- 既存データだけで根拠付きにできるか
- 無料3回/日の体験で価値が伝わるか
- GPT / Claude単体より、横断データ・出典固定・known gaps・確認質問で勝てるか

## 次の確認コマンド

外部CLIの進捗確認:

```bash
find tools/offline/_inbox/public_source_foundation -maxdepth 2 -type f 2>/dev/null | sort
find tools/offline/_inbox/output_market_validation -maxdepth 2 -type f 2>/dev/null | sort
```

既存実装確認:

```bash
rg -n "NO writes|evidence_packet|corpus_snapshot|source_document|artifact" src tests scripts
```

## 現時点の結論

本体は、外部CLIが調べた情報をすぐDB/API/完成物へ落とせるように、まず schema-only foundation から進めるのが一番よい。
