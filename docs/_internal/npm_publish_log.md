# npm Publish Log

One row per publish attempt for `@autonomath/sdk` (or fallback name
`autonomath-sdk`). Append-only; never edit historical rows.

| timestamp (JST)        | version | result                       | sha-256                                                            | sha-1                                       | publisher              | notes                                                                                          |
| ---------------------- | ------- | ---------------------------- | ------------------------------------------------------------------ | ------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------- |
| 2026-04-25 17:35 JST   | 0.2.0   | BLOCKED (no auth)            | 3b0ff64cb9f5c67eb49a8c4a877b21d4d97a2a2679467ad6f0e43e139c324e0f   | 2ce98c820fe1dc5d75e35fa44b7a990ba36b5053    | F5 subagent (build only) | `npm whoami` ENEEDAUTH; `~/.npmrc` absent; `$NPM_TOKEN` unset. Tarball staged at `dist/npm-sdk/autonomath-sdk-0.2.0.tgz` for operator manual publish per `npm_publish_runbook.md`. |

## Pending operator action

- Decide scope path:
  - **A**: create npm org `autonomath`, publish as `@autonomath/sdk`
  - **B**: rename to `autonomath-sdk` (no scope), publish under operator's user account
- Execute `npm publish --access public` per runbook.
- Append a new row to this table with the actual publish timestamp,
  result (`OK` / `FAIL: <reason>`), and the publisher's npm username.
- If the published shasum differs from the value above, rebuild was
  required — note the rebuild reason in the row.

## Tarball provenance (built 2026-04-25)

- Built by: F5 subagent
- Build command: `cd sdk/typescript && npm pack`
- Source commit: (record at publish time via `git rev-parse HEAD`)
- Node version: as installed in the harness (`node -v` to record)
- File count: 19
- Tarball: 19,753 bytes
- Unpacked: 76.3 kB
