# CLAUDE.md — Claude Code session-start shim

> This file is the **Claude-specific** entry. The canonical, vendor-neutral source of truth is the root `AGENTS.md` — read it first.
> If anything below conflicts with `AGENTS.md`, `AGENTS.md` wins.
> Last canonical edit: 2026-05-17 (Harness H3 — Agent Entry SOT shrink).

## Pointer to the SOT

For project identity, hard constraints, architecture, key commands, quality gates, and "what NOT to do" — read `AGENTS.md` at the repo root. Do **not** duplicate those rules here.

For live counts (MCP tools, REST routes, OpenAPI paths, program counts) — never hardcode. Read:

- `scripts/distribution_manifest.yml` — canonical published counts.
- `len(await mcp.list_tools())` — runtime MCP tool count.
- `python scripts/probe_runtime_distribution.py` — one-pass runtime + manifest probe.

## Memory + persistent context

- Operator-side daily state and cross-session feedback live in `memory/MEMORY.md` (not in repo). Honour the constraints recorded there — they override defaults.
- Repo-side persistent docs live under `docs/_internal/`. Treat `docs/_internal/historical/` as archaeology only — do not extend.
- When the operator says "remember X across sessions", write to `memory/MEMORY.md`. Copy the durable subset into root `AGENTS.md` only after operator confirmation.

## Claude-specific operating notes

These are conventions the operator (Umeda) has consolidated through prior sessions. They override Claude defaults inside this repo.

- **Parallel sub-agents.** Aim for 10+ concurrent agents on independent surfaces. Sub-8 is a signal to widen the lane plan. Same-file refactors run **serial** (`lane:solo`) — parallel agents on a contended file end in revert wars.
- **Lane claim atomic.** Use `mkdir` exclusive claim + append-only `AGENT_LEDGER` row before starting a parallel sub-task. Never assume an unclaimed lane is yours.
- **safe_commit.** Always commit through `scripts/safe_commit.sh -m "subject [lane:solo]"`. Never `--no-verify`. Pre-commit auto-fix can silently abort the commit; the wrapper detects HEAD non-movement and exits non-zero loudly.
- **Co-Author trailer.** Every commit message ends with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- **Validation before apply.** For large edits, search the affected paths, run `pytest` on the touched module subset, then `npm run validate` / `make` target if applicable, **before** declaring done.
- **Self-check figures.** Read tool output / Vision-LLM result yourself before showing to the operator. Don'\''t surface raw fetches unverified.
- **Verify before apologizing.** If you suspect a bug, a missing file, or operator action needed — run 5 `grep` / `ls` / `read` commands first. Apologies must come with evidence.
- **Encoding.** Shift_JIS files cannot be touched with `Edit` / `Write`. Use `iconv` + Python binary replace.
- **Images.** Files larger than 1600px on a side must be `sips`-resized into `/tmp/` before `Read`.
- **No priority / schedule / cost questions.** The operator answers yes-or-no on "do we do X" — never on "what'\''s the priority of X" or "how many hours". (Memory: `feedback_no_priority_question`.)
- **Aggressive action over caution.** When a problem is found, fix immediately rather than escalating for confirmation. Confirmation requests slow the loop.

## Loop discipline

- **Once a loop is started (`/loop` or operator says "keep going"), never stop on completion / error / done.** Use `ScheduleWakeup` and continue until the operator explicitly says `stop`. (Memory: `feedback_loop_never_stop`.)
- **No permission-asking inside a loop.** Operator has pre-authorized — execute through.
- After a strategic pivot or large landing, **slow down** for one cycle. Don'\''t queue-ahead.

## Architecture quick refresh

(Full detail in `AGENTS.md` §3. This is a Claude-side cheat sheet.)

- Source dir `src/jpintel_mcp/` (do NOT rename). PyPI: `autonomath-mcp`. npm: `@bookyou/jpcite`.
- Two SQLite stores: `data/jpintel.db` (~352 MB, FTS5 trigram) and `autonomath.db` at repo root (~9.4 GB, post-migration-032 unified DB). No cross-DB ATTACH.
- FAISS IVF+PQ on entity embeddings (`nprobe=8` floor — higher is latency-only).
- Athena warehouse with `projection.enabled` on partitioned tables (PERF-38).

## See also

- **`AGENTS.md`** — root vendor-neutral SOT (read first).
- `.agent.md` / `.cursorrules` / `.windsurfrules` / `.mcp.json` — vendor shims (counts removed; defer to AGENTS.md).
- `docs/_internal/historical/CLAUDE_WAVE_HISTORY_2026_05_06_2026_05_16.md` — Wave 17..51 / tick 1..150 historical log.
- `docs/_internal/HARNESS_H3_AGENTS_SOT_2026_05_17.md` — this migration'\''s landing notes.
- `docs/_internal/AGENT_HARNESS_REMEDIATION_PLAN_2026_05_17.md` — deep-dive plan that motivated H3.
- `DIRECTORY.md` — directory map.
- `docs/agents.md` — sample integrations.
