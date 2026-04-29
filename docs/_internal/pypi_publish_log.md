# PyPI Publish Log — `autonomath-mcp`

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Append-only ledger of every PyPI publish attempt for the
`autonomath-mcp` package. Never edit historical rows; corrections go in
the `## Errata` section at the bottom.

Companion runbook: [`pypi_publish_runbook.md`](./pypi_publish_runbook.md)
(execution steps + verify protocol).
Companion log: [`npm_publish_log.md`](./npm_publish_log.md) (TS SDK).

---

## Log table

| timestamp (JST)        | version | result                       | sha-256 (sdist)                                                    | sha-256 (wheel)                                                    | sizes (sdist / wheel) | uploader                  | install verify | notes |
| ---------------------- | ------- | ---------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ | --------------------- | ------------------------- | -------------- | ----- |
| 2026-04-22 (TBD JST)   | 0.2.0   | TBD (operator action)        | TBD (record at upload time via `sha256sum dist/autonomath_mcp-0.2.0.tar.gz`) | TBD (record at upload time via `sha256sum dist/autonomath_mcp-0.2.0-py3-none-any.whl`) | TBD                   | TBD (`twine upload` user) | TBD (clean venv) | v0.2.0 baseline. Built before V4 + Phase A absorption. May or may not be live on PyPI; pending operator verification (`pip index versions autonomath-mcp`). |
| 2026-04-25 (TBD JST)   | 0.3.0   | STAGED (dist/ ready, not uploaded) | TBD (record at upload time)                                        | TBD (record at upload time)                                        | TBD                   | F-series subagent (build only) | TBD (clean venv post-upload) | Wave 20 staged. Absorbs V4 (migrations 046-049, 4 universal tools) + Phase A (7 tools, 8 static taxonomies, 5 example profiles, 36協定 template gated). Manifest bumped in `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json`. Live publish deferred to launch +24h grace per launch CLI plan. |

---

## v0.2.0 — baseline (2026-04-22 build, status TBD)

**Build artifact location**: `dist/autonomath_mcp-0.2.0.tar.gz` + `dist/autonomath_mcp-0.2.0-py3-none-any.whl`

**Pre-upload checklist** (operator, before twine upload):
- [ ] `python -m build --sdist --wheel` 出力が `dist/` にある
- [ ] `twine check dist/autonomath_mcp-0.2.0*` で metadata pass
- [ ] `sha256sum` を取得して上表に記録
- [ ] `pip index versions autonomath-mcp` で 0.2.0 が **未公開** であることを確認 (既公開なら yank 不可なので 0.2.1 に bump)

**Post-upload checklist** (per `pypi_publish_runbook.md` §6):
- [ ] `twine upload dist/autonomath_mcp-0.2.0*` (要 `PYPI_TOKEN`)
- [ ] clean venv で `pip install --no-deps autonomath-mcp==0.2.0` → `from jpintel_mcp.mcp.server import mcp; print('OK')` 印字
- [ ] `git tag v0.2.0 && git push origin v0.2.0`
- [ ] 上表の `result` を `OK` または `FAIL: <reason>` に更新
- [ ] `install verify` 列を `OK (clean venv)` または `FAIL: <ImportError 等>` に更新
- [ ] uploader 列に `twine upload` を実行した PyPI username を記録

---

## v0.3.0 — Wave 20 staged (2026-04-25 build)

**Build artifact location**: `dist/autonomath_mcp-0.3.0.tar.gz` + `dist/autonomath_mcp-0.3.0-py3-none-any.whl`

**Scope of changes (delta from 0.2.0)**:
- migrations 046-049 (annotation, validation, license, jpi_pc_program_health)
- 4 universal MCP/REST tools (`get_annotations`, `validate`, `get_provenance`, `get_provenance_for_fact`)
- Phase A: 7 new tools + 8 static taxonomies + 5 example profiles + 36協定 template
- 36協定 launch gate (`AUTONOMATH_36_KYOTEI_ENABLED=False` default → 69 tools at default gates, 71 if gate flipped)
- entity count 424k → 503k, fact count 5.26M → 6.12M, tool count 59 → 72

**Pre-upload checklist**:
- [ ] CLAUDE.md / DIRECTORY.md の v0.3.0 数値が正しい (2026-04-26 audit 済)
- [ ] `pyproject.toml` version = `0.3.0` ↔ `server.json` version = `0.3.0` の lock-step
- [ ] `twine check dist/autonomath_mcp-0.3.0*` で metadata pass
- [ ] `sha256sum` を取得して上表に記録
- [ ] launch +24h grace (2026-05-07 12:00 JST 目処) を待ってから upload (launch CLI plan 準拠)

**Post-upload checklist**:
- [ ] `twine upload dist/autonomath_mcp-0.3.0*`
- [ ] clean venv で install verify → `from jpintel_mcp.mcp.server import mcp` の `len(mcp._tool_manager.list_tools())` が **72** を返す (`AUTONOMATH_ENABLED=1` 環境)
- [ ] `git tag v0.3.0 && git push origin v0.3.0`
- [ ] MCP registry: `mcp publish server.json` (Official + secondary registries は `mcp_registry_runbook.md` 参照)
- [ ] 上表の result / install verify / uploader 列を更新

---

## Yank / re-release protocol

PyPI は同一 version の再 upload を禁止 (immutable)。問題があった場合:

1. **Yank** (`twine` or pypi.org UI) — 既存 install は壊さないが新規 `pip install` を防ぐ
2. patch version bump (`0.3.0` → `0.3.1`) して **新行を追加** (上表の row は残す、result 列に `YANKED (yyyy-mm-dd, reason: ...)` 追記)
3. yank 理由を本 log の `## Errata` に詳細記録 (どの ImportError / metadata 問題 / security issue が trigger か)

---

## Errata

(空 — closed row の修正はここに reason 付きで記録)

---

## 関連 doc

- [`pypi_publish_runbook.md`](./pypi_publish_runbook.md) — execution 手順 (本 log の参照元)
- [`npm_publish_log.md`](./npm_publish_log.md) — TS SDK の同種 log
- [`hf_publish_log.md`](./hf_publish_log.md) — HuggingFace dataset publish log
- [`mcp_registry_runbook.md`](./mcp_registry_runbook.md) — Official MCP Registry 提出 (PyPI publish と連動)
- `pyproject.toml` — version source of truth (server.json と lock-step)
