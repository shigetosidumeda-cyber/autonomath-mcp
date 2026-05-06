# OpenAPI distribution sync - 2026-05-06

担当: distribution/openapi worker

## 実行

- `uv run python scripts/export_agent_openapi.py`
  - `docs/openapi/agent.json` を再生成
  - `site/openapi.agent.json` を再生成
  - `site/docs/openapi/agent.json` を再生成

## 確認

- `docs/openapi/agent.json` と `site/openapi.agent.json` は一致。
- `site/docs/openapi/agent.json` も同一内容で生成済み。ただし `site/docs/` は `.gitignore` 対象。
- SHA-256: `36726cfe0613f137764cd546e48ada6caf1713e6cb719fa3e7c5b6a726425c43`

## company artifact route

- 現在の agent spec に含まれる artifact route は以下。
  - `/v1/artifacts/compatibility_table`
  - `/v1/artifacts/application_strategy_pack`
  - `/v1/artifacts/houjin_dd_pack`
- `docs/openapi/v1.json` 上にも company artifact 専用 route は確認できないため、company artifact route は未実装として扱う。実装済みとは断定しない。
