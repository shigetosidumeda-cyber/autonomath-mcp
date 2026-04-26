# Directory Map (AutonoMath repo)

新 agent session の 最初 30 秒で 全体把握 する用.

## Top-level (役割別 aliasing)

| ディレクトリ / ファイル | 役割 | 主要 entry point |
|---|---|---|
| `src/` | **Python コード源泉** (API server + MCP server + ingest + billing) | `src/jpintel_mcp/api/main.py` (FastAPI), `src/jpintel_mcp/mcp/server.py` (MCP) |
| `tests/` | unit + integration + e2e | `pytest tests/` (256 本), e2e は `pytest tests/e2e` |
| `scripts/` | ops / maintenance スクリプト | `scripts/migrate.py` (deploy 時 auto), `scripts/ingest_tier.py` |
| `scripts/migrations/` | SQL migration files | 001-009 適用済 / 006 draft (adoption) |
| `scripts/ingest/` | PoC ingest scripts | `poc_adoption_jigyou_saikouchiku.py` |
| `scripts/_archive/` | 役割終了 one-shot scripts (reference 用) | `fix_uni_*`, `fix_url_*`, `apply_prefecture_*` (2026-04-23 execute 済) |
| `data/` | SQLite DB + 中間 data files (git 管理外) | `data/jpintel.db` (172MB) |
| `docs/` | **Customer-facing docs** (MkDocs で `site/docs/` に build) | `docs/index.md`, `docs/getting-started.md` |
| `docs/_internal/` | 内部 運用 docs (deploy / incident / sdk release 等) | `docs/_internal/ingest_automation.md`, `docs/_internal/deploy_gotchas.md` |
| `docs/_internal/archive/` | 過去文書 (launch 2026-04-23 等) | `launch_2026-04-23/` |
| `site/` | **Customer-facing static HTML** (landing / pricing / ToS / privacy / 特商法 / dashboard) | `site/index.html`, `site/pricing.html` |
| `site/docs/` | MkDocs build output (`.gitignore`済) | — |
| `overrides/` | MkDocs template override | `partials/footer.html` 等 |
| `sdk/python/` | Python SDK (PyPI `autonomath`) | `sdk/python/autonomath/` |
| `sdk/typescript/` | TypeScript SDK (npm `@autonomath/sdk`) | `sdk/typescript/src/` |
| `examples/` | integration sample code | `examples/python/`, `examples/typescript/` |
| `research/` | **設計 / 研究 / 戦略 docs** (内部思考) | `research/data_expansion_design.md` (9,775+ 行 canonical) |
| `research/_archive/pre_launch_decisions/` | launch 前 決定済 docs (reference) | `domain_*`, `trademark_jp.md`, `url_integrity_*`, `admin_dashboard_design.md` 等 |
| `loadtest/` | k6 load test scenarios | — |
| `.github/` | CI / CD workflows | `.github/workflows/*.yml` |

## Root-level 重要 files

| ファイル | 役割 |
|---|---|
| `README.md` | 公開用 project README |
| `CHANGELOG.md` | リリースノート |
| `DIRECTORY.md` | **本ファイル** — ディレクトリ navigation |
| `fly.toml` | Fly.io deploy 設定 (app=`autonomath-api`, nrt) |
| `Dockerfile` | 本番 container image |
| `pyproject.toml` | Python project 定義 |
| `mkdocs.yml` | docs site 生成設定 |
| `.env.example` | 環境変数テンプレ |
| `.gitignore` | Git 除外 |
| `.pre-commit-config.yaml` | pre-commit hooks |
| `.github/workflows/` | CI/CD |
| `uv.lock` | Python dependencies lock |
| `mcp-server.json` | MCP registry submission manifest |
| `smithery.yaml` | Smithery registry submission |

## 設計 の 正本 (Canonical)

- **全体 設計**: `research/data_expansion_design.md` (9,775 行 v13) — 冒頭 TL;DR + Quick Start + Canonical Facts + Glossary + Anti-patterns
- **外部 data**: `/Users/shigetoumeda/Autonomath/data/` (138k 採択者 等、未 merge)
- **Auto-memory**: `/Users/shigetoumeda/.claude/projects/-Users-shigetoumeda/memory/` (project / feedback / user / reference の 4 分類)

## 本番 infra 入り口

| 環境 | URL |
|---|---|
| 本番 API | https://api.autonomath.ai |
| Website | https://autonomath.ai |
| Fly.io app | `autonomath-api` (nrt) |
| Fly SSH | `flyctl ssh console -a autonomath-api` |
| Fly logs | `flyctl logs -a autonomath-api` |
| deploy | `flyctl deploy -a autonomath-api --remote-only` |

## 新 agent session 読む順 (最速)

1. `research/data_expansion_design.md` の 冒頭 6 section (TL;DR → Anti-patterns) — 5 分
2. 本 DIRECTORY.md (全体 配置) — 1 分
3. 対象 task に応じた section (Quick Start の 類型別 map 参照)

