# MCP Manifest Deep Diff

- generated_at: `2026-05-15T20:00:02+09:00`
- dxt_manifest: `/Users/shigetoumeda/jpcite/dxt/manifest.json`
- registry_manifest: `/Users/shigetoumeda/jpcite/mcp-server.full.json`
- dxt_tool_count: `155`
- registry_tool_count: `155`
- dxt_version: `0.4.0`
- registry_version: `0.4.0`
- dxt_resource_count: `37`
- registry_resource_count: `37`
- hard_drift: `false`
- soft_description_drift: `false`

## Interpretation

- Hard drift means tool names are missing from one manifest.
- Soft drift means the same tool exists but descriptions differ.
- Description drift matters because agent routing depends on WHEN, WHEN NOT, CHAIN, LIMITATIONS, counts, and pricing language.
- Resource drift may be intentional, but it should be explicit because DXT resources can teach Claude Desktop how to use the service.

## Summary

| item | count |
|---|---:|
| missing_in_dxt | 0 |
| missing_in_registry | 0 |
| description_mismatches | 0 |

## Description Mismatches

| tool | dxt first line | registry first line |
|---|---|---|

## Recommended Gate

1. Fail release on hard drift.
2. Review soft drift when counts, pricing, free tier, tool limitations, or routing language differ.
3. Keep DXT resource differences intentional and documented.

