# Repo Organization Assessment 2026-05-06

## Verdict

結論として、このリポジトリは「思想と主要境界はかなり整理されている」が、「この上なく美しい」とはまだ言い切れない。

理由は明確で、`DIRECTORY.md` に書かれている責務分離は良い一方、現在の作業ツリーでは live source、生成物、研究成果、operator handoff、巨大DB、配布物backup、未追跡workflowが同じ視界に入りやすい。これは開発速度、deploy判断、agent作業、コードレビュー、障害時復旧のすべてで認知負荷になる。

この監査では削除やrevertは行わない。今後のプロジェクト改善に効く「境界の明文化」「継続監視」「commit分割」「生成物とsource of truthの分離」を優先する。

## What Is Already Good

- `src/jpintel_mcp/`, `scripts/`, `tests/`, `docs/`, `site/`, `sdk/`, `tools/offline/` の主要責務は `DIRECTORY.md` で説明されている。
- production code と operator-only LLM/offline work の境界が `tools/offline/` として意識されている。
- `scripts/cron`, `scripts/ingest`, `scripts/etl`, `scripts/ops`, `scripts/migrations` の大分類は今後も維持する価値がある。
- `docs/` と `site/` は source docs と public static output の役割が分かれている。
- `.dockerignore` は `autonomath.db`, `site/`, `sdk/`, `tools/offline/`, `docs/_internal/` を本番imageから外す方針を持っている。
- OpenAPI、MCP、llms、SDK、siteの配布surfaceが明示的に存在し、AI/GEO向けの出口が多い。

## What Is Not Beautiful Yet

### 1. Root Worktree Is Too Heavy

実測メモ:

- `autonomath.db`: about 12GB
- `tools/`: about 1.1GB
- `data/`: about 513MB
- `sdk/`: about 356MB
- `site/`: about 299MB
- `dist/`: about 300MB
- `dist.bak/`: about 319MB
- `dist.bak2/`: about 314MB
- `analysis_wave18/`: about 150MB
- `autonomath_staging/`: about 135MB

本番に必要なもの、生成で再現できるもの、operator research、過去backupが同じ階層に見えるため、agentや人間が「今触ってよいもの」を判断しづらい。

### 2. Dirty Tree Is Too Wide For Safe Deployment Reasoning

現在は docs/site/sdk/scripts/src/tests/workflows/generated OpenAPI など、非常に広範囲に変更がある。これは開発の勢いとしては理解できるが、deploy判断では危険になる。

特に危険なのは、以下が同時に混ざること。

- runtime code
- migration
- cron
- billing/auth/security
- generated OpenAPI/site
- launch/docs copy
- SDK
- operator research prompt
- DB/data/output

この状態では「何をdeployするのか」「何をcommitするのか」「何が生成物なのか」が曖昧になりやすい。

### 3. Source Of Truth And Generated Output Are Still Mixed In Reviews

`docs/openapi/*.json`, `site/openapi.agent.json`, `site/docs/openapi/*.json`, `site/*.html`, `site/en/*.html`, `site/llms*.txt` などは配布上重要だが、生成物でもある。

source changeとgenerated diffが同じreviewに入ると、実装の意図が読みにくい。生成物を追跡する方針自体はあり得るが、その場合は「生成物commit」「source commit」を分ける必要がある。

### 4. Research And Operator Loops Are Valuable But Too Visible

`analysis_wave18/`, `analysis_value/`, `research/`, `tools/offline/_inbox/`, `docs/_internal/` はサービス改善の資産だが、量が多い。現状は開発者・agentが読むべきものと、読んではいけない/触ってはいけないものが混ざる。

特に外部CLIが書く `tools/offline/_inbox/*` は、sourceではなく「調査成果の受信箱」として扱うべき。

### 5. Test Surface Is Strong But Ownership Is Hard To See

`tests/` は広く、CI対象subsetとfull pytestの差が大きい。今後の改善には、ディレクトリ美化よりも「どの領域の変更でどのテストを必ず回すか」が効く。

## Target Topology

今すぐ物理移動する必要はないが、概念上は以下に分ける。

```text
runtime_source:
  src/
  scripts/cron/
  scripts/ops/
  scripts/migrations/
  entrypoint.sh
  Dockerfile
  fly.toml

public_source:
  docs/
  overrides/
  mkdocs.yml
  README.md
  DIRECTORY.md

generated_public:
  site/
  docs/openapi/*.json
  site/openapi*.json
  site/docs/openapi/*.json
  site/llms*.txt

data_runtime_seed:
  data/jpintel.db
  data/unified_registry.json
  data/autonomath_static/

local_or_remote_runtime_data:
  autonomath.db
  *.db-wal
  *.db-shm
  dist.bak*/
  analysis_wave18/
  autonomath_staging/

operator_research:
  tools/offline/
  tools/offline/_inbox/
  docs/_internal/
  research/

client_surfaces:
  sdk/
  dxt/
  examples/
  mcp-server*.json
  server.json
  smithery.yaml
```

## Improvement Plan

### P0: Make The Current State Observable

- Keep this audit and update it when the repo shape changes materially.
- Add a repo organization inventory script that reports:
  - top-level size
  - top-level tracked/untracked/ignored status
  - generated/public/source categories
  - files that likely should not enter Docker context
  - huge local runtime files
- Generate a small Markdown report under `docs/_internal/` or `tools/offline/_inbox/_repo_health/`.

### P1: Define Commit Lanes

Future work should be split into these commit lanes:

1. runtime code and tests
2. migrations and DB bootstrap
3. generated OpenAPI/site/llms
4. docs/copy only
5. SDK/package surfaces
6. operator research prompts and inbox reports
7. deploy/CI/Docker

This reduces review risk and makes production deploys easier to reason about.

### P2: Make Generated Artifacts Explicit

For each generated family, document the command that regenerates it.

- OpenAPI full: `scripts/export_openapi.py`
- OpenAPI agent: `scripts/export_agent_openapi.py`
- llms full: `scripts/regen_llms_full.py`, `scripts/regen_llms_full_en.py`
- site pages: generation scripts under `scripts/generate_*`
- public counts: `scripts/generate_public_counts.py`

Generated files may remain tracked if Cloudflare/static deploy requires them, but source and generated diffs should be reviewed separately.

### P3: Quarantine Local-Only Heavy Artifacts Without Deleting

Do not delete unknown artifacts. First classify.

Candidates for local-only or archive treatment:

- `dist.bak/`, `dist.bak2/`, `dist.bak3/`
- root `*.db`, `*.db-shm`, `*.db-wal`
- `.venv312/`
- `analysis_wave18/`
- `autonomath_staging/`
- large generated `site/` subtrees that are reproducible

The safe move is not removal. The safe move is to document ownership and decide whether each is:

- source
- generated but tracked
- generated and ignored
- local runtime
- remote artifact
- archive
- operator inbox

### P4: Strengthen Agent Navigation

Agents should read in this order:

1. `DIRECTORY.md`
2. `CLAUDE.md`
3. task-specific source files
4. this repo organization assessment
5. only then broad search

This prevents agents from treating research output, generated site output, and runtime source as equal.

## Service Impact

This is not cosmetic. A cleaner repository directly improves the service:

- Faster onboarding for AI agents and humans.
- Lower deploy risk because generated/docs/source changes are separated.
- Better quality of external CLI research because outputs land in predictable inboxes.
- Easier production incident response because runtime source and operator notes are separated.
- Faster implementation of new artifacts because source profiles, schema backlog, and artifact specs have known landing zones.
- Better GEO/API reliability because OpenAPI/MCP/llms generation is explicit.

## Immediate Next Actions

1. Add or run a repo organization inventory script.
2. Keep `DIRECTORY.md` as the canonical map, but update counts and currently observed directories.
3. Add a generated-artifact policy section to `DIRECTORY.md` or a separate internal doc.
4. Split future commits by commit lane.
5. Before any production deploy, review Docker context and dirty tree by lane.

## Current Answer To The User Question

「この上なく美しく整理されていますか？」への答えは、現時点では No.

ただし、整理の思想はかなり良い。問題は構成思想ではなく、現在の作業ツリーに蓄積した研究成果・生成物・巨大DB・配布backup・未追跡ファイルが多すぎること。ここを非破壊で可視化し、source of truth と generated/output を分ければ、今後のプロジェクト速度と本番安全性はかなり上がる。
