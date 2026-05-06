# Repo Hygiene Inventory

- generated_at: `2026-05-06T14:19:24+09:00`
- repo: `/Users/shigetoumeda/jpcite`
- git_modified_entries: `218`
- git_deleted_entries: `1`
- git_untracked_entries: `458`

## Summary By Kind

| kind | top-level count | total size |
|---|---:|---:|
| data_mixed | 1 | 504.9MB |
| generated_or_output | 8 | 1.4GB |
| local_noise | 5 | 1.7GB |
| local_runtime_data | 11 | 11.6GB |
| operator_or_research | 2 | 1.1GB |
| root_file_or_misc | 36 | 2.1MB |
| source_or_test | 7 | 410.2MB |
| tooling_or_cache | 14 | 140.9MB |

## Largest Top-Level Items

| item | kind | status | size |
|---|---|---|---:|
| `autonomath.db` | local_runtime_data | ignored_or_local | 11.5GB |
| `tools` | operator_or_research | tracked_and_untracked | 1.1GB |
| `.venv` | local_noise | ignored_or_local | 969.1MB |
| `.venv312` | local_noise | ignored_or_local | 776.5MB |
| `data` | data_mixed | tracked | 504.9MB |
| `sdk` | source_or_test | tracked_and_untracked | 307.8MB |
| `dist.bak` | generated_or_output | ignored_or_local | 293.1MB |
| `dist.bak2` | generated_or_output | ignored_or_local | 288.3MB |
| `dist` | generated_or_output | ignored_or_local | 272.3MB |
| `site` | generated_or_output | tracked_and_untracked | 270.5MB |
| `analysis_wave18` | generated_or_output | tracked | 148.1MB |
| `autonomath_staging` | generated_or_output | ignored_or_local | 128.1MB |
| `.mypy_cache` | tooling_or_cache | ignored_or_local | 75.3MB |
| `.cache` | tooling_or_cache | ignored_or_local | 64.6MB |
| `examples` | source_or_test | tracked | 45.5MB |
| `autonomath_invoice_mirror.db` | local_runtime_data | ignored_or_local | 40.4MB |
| `graph.sqlite` | local_runtime_data | ignored_or_local | 17.7MB |
| `docs` | source_or_test | tracked_and_untracked | 15.3MB |
| `scripts` | source_or_test | tracked_and_untracked | 15.0MB |
| `tests` | source_or_test | tracked_and_untracked | 14.2MB |

## Non-Destructive Recommendations

1. Treat root-level DB/WAL/SHM files as local runtime data, not source.
2. Keep generated public artifacts reviewable, but separate source changes from generated diffs.
3. Move future offline loop outputs into a single ignored artifact root or keep them under `tools/offline/_inbox/` with a manifest.
4. Keep `DIRECTORY.md` as the human navigation map and this report as the machine-generated inventory.
5. Before deploy, inspect Docker context and git dirty tree by lane: runtime code, migrations, generated public, docs, SDK, operator research.

