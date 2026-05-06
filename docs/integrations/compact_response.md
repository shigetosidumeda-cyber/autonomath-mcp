# Compact response envelope (`?compact=true`)

When a customer LLM injects a jpcite response straight into its own
context window, every byte costs input tokens. The default response
envelope (Evidence Packet shape, audit-sealed when authenticated)
carries human-readable verbose fields — disclaimers, full HMAC seal
dicts, replay-endpoint URLs — that are useful for ops audits but
pure dead-weight inside an LLM context.

The compact envelope is a **lossy projection** of the full envelope
that strips those verbose fields and replaces a few of them with
short reference ids. The customer SDK (or a one-line lookup in your
prompt) resolves the references back to the full text from the
published tables below.

> Default: full envelope (back-compat preserved).
> Compact: opt-in via `?compact=true` query OR `X-JPCite-Compact: 1` header.
> Never on by default; legacy clients are never broken.

## When to use

Use compact when:

- You pass the response **directly into an LLM prompt context** (Claude,
  GPT, Gemini, Mistral, etc.).
- You want stable *machine-readable* references rather than verbose
  Japanese fence text.
- Your downstream code already recognises the short keys (you have the
  reference tables embedded in your SDK or prompt).

Stay on the default (full) envelope when:

- A human reads the response (debugger, support inbox, audit log).
- You need the full audit seal dict for later forensic verification
  (the compact form keeps only the HMAC).
- You rely on `_next_calls[].args` being pre-computed for you (the
  compact form keeps tool names only and expects you to fill args
  from the row context).

## Token saving (measured)

Sample: a single-program Evidence Packet with 1 record + 4 facts +
3 known-gap entries + audit seal + 4 next-calls (after dedup).

| envelope | bytes (UTF-8 JSON, no whitespace) | ratio |
| --- | --- | --- |
| **full**    | **2,939** | 1.000 |
| **compact** |   **925** | **0.315** |

That is **68.5% smaller** on this sample. Targeted reduction across
the full Evidence Packet surface is **30-50%**; complex packets with
many records compress less aggressively because `records[]` (the
load-bearing inference payload) is preserved verbatim — only the
envelope wrapper shrinks.

A typical claude-3-5-sonnet input price (¥3.40/1M tokens at
2026-05-05) means a 30-50% reduction translates roughly to
**¥0.0008-¥0.0014 saved per response** when the response is piped
into an LLM context window of ~3 KB.

## Wire diff (full → compact)

| full key | compact key | transformation |
| --- | --- | --- |
| `_audit_seal` (8-field dict) | `_seal` (string) | HMAC hex only |
| `_next_calls: [{tool, args}, ...]` | `_nx: ["tool_a", "tool_b"]` | dedup tool name list |
| `_disclaimer` (700-char text) | `_dx` (id, e.g. `disc_§52_v1`) | reference id |
| `quality.known_gaps` (long sentences) | `quality.gaps` (enum codes) | `EP1`-`EP9` codes |
| `verification.replay_endpoint` | (omitted) | re-derive from kind |
| `verification.freshness_endpoint` | (omitted) | always `/v1/meta/freshness` |
| `verification.provenance_endpoint` | `v.pe` | preserved when non-empty |
| `corpus_snapshot_id` (UUID + ISO ts) | `csid` (date-prefix short form) | `20260505-abcd` |
| `packet_id` | `pid` | preserved as-is |
| `generated_at` | `ts` | preserved as-is |
| `api_version`, `answer_not_included` | (omitted) | implied by `_c=1` |

The compact envelope always carries `"_c": 1` so a downstream reader
can detect the projection without sniffing key shapes.

## Disclaimer reference table

Populate this table once into your SDK or LLM system prompt; then any
`_dx` reference in a compact response resolves locally without the
verbose text being re-shipped per request.

| id | full text |
| --- | --- |
| `disc_evp_v1` | Evidence Packet bundles primary-source citations and rule verdicts; it is not legal, tax, or grant-application advice. Final decisions require 専門家 (税理士 / 行政書士 / 中小企業 診断士 / 認定支援機関) review. |
| `disc_seal_v1` | 信頼できる出典として運用する場合は、verify_endpoint で seal の真正性を確認してください。 |
| `disc_§52_v1` | 本 response は公開コーパスに対する機械的検索照合で、税理士法 §52 (税務代理) ・弁護士法 §72 (法律事務) ・行政書士法 §1 (申請代理) ・社労士法 (労務判断) のいずれにも該当しません。検索結果のみ提供、業務判断は primary source 確認必須、確定判断は士業へ。 |
| `disc_§47_2_v1` | 公認会計士法 §47条の2 監査役務外領域の検索結果のみ。意見表明・保証業務には該当せず、監査人による独立性ある検証が必要です。 |

The id schema is `<topic>_v<version>`. We bump the suffix when the
text changes; older clients keep working because we never re-key an
existing id in place.

## Known-gaps enum reference

| code | meaning |
| --- | --- |
| `EP1` | Per-fact provenance unavailable (source_id NULL on this entity) |
| `EP2` | Citation verification stale (last live URL probe > 30 days) |
| `EP3` | Recent amendment diff not yet ingested (am_amendment_diff lag) |
| `EP4` | Coverage score below 0.6 (sparse fact set on this subject) |
| `EP5` | Partner compatibility heuristic (am_compat_matrix inferred edge) |
| `EP6` | License is `unknown` for at least one cited source |
| `EP7` | Result truncated (record cap reached; paginate via cursor) |
| `EP8` | Snapshot drift (corpus_snapshot_id older than freshness target) |
| `EP9` | Source URL no longer reachable (last 24h liveness probe failed) |

Unknown gap sentences map to `Z` so the count stays honest. Treat
`Z` as "data quality issue, see the full envelope at the same URL
without `?compact=true` for details".

## Round-trip / loss surface

The compact envelope is **deliberately lossy**. The customer can
either consume the compact form directly with the reference tables
above, or call `from_compact(...)` (Python helper exposed at
`jpintel_mcp.api._compact_envelope`) to expand the envelope back to
the canonical full keys.

What survives the round-trip:

- `records[]` / `results[]` (verbatim — the load-bearing inference payload)
- `citations[]` (verbatim)
- `meta`, `status`, `warnings[]`, `_warning`, `error`
- `quality.{coverage_score, freshness_*, human_review_required}`
- `quality.known_gaps` (recovered as canonical reference text)
- `_disclaimer` (recovered as canonical reference text)
- `_audit_seal.hmac` (only the HMAC — call `/v1/audit/seals/{seal_id}` for the rest)
- `_next_calls[].tool` (args are NOT preserved — fill them from row context)
- `corpus_snapshot_id` (preserved in shortened form)

What is dropped (call the full envelope if you need it):

- `_audit_seal.{seal_id, ts, source_urls, query_hash, response_hash, ...}`
- `verification.{replay_endpoint, freshness_endpoint}`
- `quality.known_gaps_inventory` (the verbose per-record breakdown)
- `api_version`, `answer_not_included` (implied flags)

## Example

```bash
# Default (full envelope):
curl 'https://api.jpcite.com/v1/programs/UNI-test-s-1/evidence' \
     -H 'X-API-Key: ...'
# → ~2.9 KB JSON with verbose _disclaimer + full _audit_seal dict

# Compact:
curl 'https://api.jpcite.com/v1/programs/UNI-test-s-1/evidence?compact=true' \
     -H 'X-API-Key: ...'
# → ~0.9 KB JSON, identical inference payload, references for the rest
```

```python
# Python — opt-in via header (works on any route).
import httpx
r = httpx.get(
    "https://api.jpcite.com/v1/programs/UNI-test-s-1/evidence",
    headers={"X-API-Key": "...", "X-JPCite-Compact": "1"},
)
compact = r.json()
assert compact["_c"] == 1            # detect projection
disclaimer = DISCLAIMER_TABLE[compact["_dx"]]   # resolve locally
seal_hmac = compact["_seal"]                    # HMAC for later verify
```

The published id schema is stable (we never re-key in place), so a
client that holds a stale `disc_§52_v1` row keeps working — they will
just quote slightly older wording until they refresh the table from
this doc.
