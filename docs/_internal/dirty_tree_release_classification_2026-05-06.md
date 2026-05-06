# Dirty tree release classification 2026-05-06

## 現状サマリ

- 作業ディレクトリ: `/Users/shigetoumeda/jpcite`
- 取得日時: 2026-05-06
- `git status --porcelain=v1` 実測: 674件
  - ` M`: 202件
  - `D `: 1件
  - `??`: 471件
- `git diff --stat` 実測: 202 files changed, 35627 insertions(+), 16452 deletions(-)
- 依頼文の「672件」と実測が一致しないため、deploy前に必ず再集計すること。
- この分類はパス名と変更種別による一次仕分け。コード内容のレビュー結果ではない。

### 上位ディレクトリ別件数

| top-level | 件数 | 主な内容 |
| --- | ---: | --- |
| `scripts` | 191 | migrations, cron, etl, registry/export/generator scripts |
| `docs` | 112 | public docs, internal docs, integrations, launch/runbook |
| `site` | 111 | built site HTML/assets/generated JSON |
| `tests` | 91 | unit/smoke/integration tests |
| `src` | 77 | API/MCP/services/billing/ingest implementation |
| `tools` | 28 | offline runners, inbox/quarantine outputs |
| `sdk` | 24 | Python/TypeScript/agents/npm package, extensions |
| `.github` | 9 | scheduled workflows |
| `benchmarks` | 3 | benchmark outputs/workspaces |
| `examples`, `dxt`, `data` | 2 each | examples, DXT metadata, data logs/report |
| other root files/dirs | 22 | configs, README, lockfiles, backup dirs, venv |

## 今回投入候補

合計: 349件 (` M`: 49, `??`: 300)

本番改善P0の候補。ただし、このまま全投入ではなく、関連する実装・migration・testをセットでレビューする前提。

| 範囲 | 件数 | 判断 |
| --- | ---: | --- |
| `src/jpintel_mcp/**` | 77 | API/MCP/servicesの実装変更。今回の主候補。 |
| `tests/**` | 91 | 実装変更と対になる検証候補。 |
| `scripts/migrations/**` | 128 | DB変更候補。順序、rollback、既存wave番号重複を必ず確認。 |
| `scripts/cron/**` | 14 | 定期実行系。workflowや環境変数とセット確認。 |
| `scripts/etl/**` | 25 | データ基盤更新候補。DB負荷と再実行性を確認。 |
| `.github/workflows/**` | 9 | scheduled workflow候補。頻度、secret、外部API負荷を確認。 |
| `.dockerignore`, `entrypoint.sh`, `pyproject.toml`, `uv.lock`, `monitoring/sla_targets.yaml` | 5 | deploy/runtime/依存/監視に関わるため候補。ただし単独投入は避ける。 |

主な注意点:

- migrationsが128件あり、P0で必要なDB変更だけに絞るべき。
- cron/etl/workflowは本番で自動起動・外部アクセス・DB書き込みが発生し得るため、投入前に無効化条件と環境変数を確認する。
- `src`と`tests`は広範囲にまたがるため、機能単位で小さく切ってrelease対象を確定する。

## 後回し候補

合計: 43件 (` M`: 27, `??`: 16)

本番反映の前提にならない、またはP0のdeploy対象に混ぜるとレビュー範囲を増やすもの。

| 範囲 | 件数 | 判断 |
| --- | ---: | --- |
| `docs/launch/**`, `docs/launch_assets/**`, `docs/blog/**` | 18 | launch/PR/投稿文。deploy可否とは分ける。 |
| `docs/runbook/**` | 9 | 運用文書。内容確認後に別PR候補。 |
| `docs/partnerships/**`, outreach/press/roadmap/plans | 8 | 事業・広報・計画系。P0 releaseから分離。 |
| `benchmarks/**` | 3 | benchmark作業領域。結果だけ必要なら別途精査。 |
| `sdk/browser-extension/**`, `sdk/vscode-extension/**` | 2 | 拡張機能の新規領域。P0本体から分離。 |
| `CLAUDE.md`, `MASTER_PLAN_v1.md`, `pypi-jpcite-meta/` | 3 | 作業メモ/配布準備系。deploy対象外寄り。 |

## 生成物/再生成物候補

合計: 119件 (` M`: 59, `??`: 60)

本番反映の危険物。原則として手編集差分を直接releaseに混ぜず、生成元・生成コマンド・成果物の必要性を確認する。

| 範囲 | 件数 | 判断 |
| --- | ---: | --- |
| `site/**` | 111 | build済みsite。`mkdocs`/site generatorの成果物候補。 |
| `docs/openapi/agent.json`, `docs/openapi/v1.json` | 2 | OpenAPI export成果物候補。 |
| `docs/compare_matrix.csv` | 1 | compare page生成元/生成物の確認が必要。 |
| `.venv312/` | 1 | 仮想環境。絶対にrelease対象へ入れない。 |
| `dist.bak/`, `dist.bak2/`, `dist.bak3/` | 3 | backup/build退避物。絶対にrelease対象へ入れない。 |
| `pyproject.toml.bak` | 1 | backupファイル。release対象外。 |

主な注意点:

- `site/downloads/autonomath-mcp.mcpb` はバイナリ差分。生成元と配布意図の確認なしに投入しない。
- `site/openapi.agent.json` と `docs/openapi/agent.json` のような重複生成物は、片方だけ古い可能性がある。
- `.venv312` と `dist.bak*` はdirty treeから残っているだけならignore/cleanup方針を別途決める。ただしこの作業では削除しない。

## 要確認候補

合計: 163件 (` M`: 67, `D `: 1, `??`: 95)

releaseに入る可能性はあるが、所有者・生成元・配布面・互換性の確認が必要なもの。

| 範囲 | 件数 | 判断 |
| --- | ---: | --- |
| `docs/_internal/**` | 44 | 内部成果物・調査メモ。公開release対象から原則分離。 |
| `docs/integrations/**`, `docs/cookbook/**`, public docs主要ファイル | 30 | 公開docsとして必要か、site生成に含まれるかを確認。 |
| `tools/offline/**` | 28 | offline runnerとinbox/quarantine成果物が混在。成果物混入に注意。 |
| `scripts/**` migrations/cron/etl以外 | 24 | generator/export/registry系。生成元か運用スクリプトか要確認。 |
| `sdk/**` 本体/README/tests/package | 22 | SDK配布面に影響。versioningとnpm/pypi方針を確認。 |
| `data/**` | 2 | report/log。生成物か監査証跡か確認。 |
| `dxt/**`, `examples/**` | 4 | 配布・サンプル面。manifestとの整合を確認。 |
| root config/docs | 8 | `README.md`, `mkdocs.yml`, `mcp-server*.json`, `server.json`, `smithery.yaml`, `overrides/**` など。 |
| `sdk/typescript/autonomath-sdk-0.2.0.tgz` | 1 deleted | 削除差分。配布tarballの扱いを必ず確認。 |

主な注意点:

- `docs/_internal/marketplace_application/` と `tools/offline/_inbox/` は成果物・申請素材の可能性があり、公開成果物へ混ぜない。
- `mcp-server*.json`, `server.json`, `smithery.yaml`, `dxt/manifest.json` は外部ディレクトリ/registry連携に影響するため、manifest drift確認が必要。
- SDKは複数パッケージが同時に変わっているため、release versionとgenerated clientの出所をそろえる。

## deploy前に必ず見るコマンド

```bash
git status --porcelain=v1 | awk 'END {print NR}'
git status --porcelain=v1 | awk '{s=substr($0,1,2); c[s]++} END {for (s in c) print s, c[s]}' | sort
git status --porcelain=v1 | sed 's/^...//' | awk '{split($0,a,"/"); print a[1]}' | sort | uniq -c | sort -nr
git diff --stat
git diff --name-only -- src tests scripts/migrations scripts/cron scripts/etl .github/workflows pyproject.toml uv.lock entrypoint.sh .dockerignore monitoring/sla_targets.yaml
git status --porcelain=v1 -- .venv312 'dist.bak*' site docs/openapi tools/offline/_inbox tools/offline/_quarantine
git diff -- docs/openapi/agent.json docs/openapi/v1.json site/openapi.agent.json site/mcp-server.json site/server.json
git diff -- scripts/distribution_manifest.yml mcp-server.json mcp-server.full.json mcp-server.core.json mcp-server.composition.json server.json smithery.yaml dxt/manifest.json
git diff --name-status -- sdk
```
