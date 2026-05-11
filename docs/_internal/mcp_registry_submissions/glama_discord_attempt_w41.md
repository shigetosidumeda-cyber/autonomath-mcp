# Glama Discord escalation — Wave 41 attempt log

**Date**: 2026-05-12 06:30 UTC (15:30 JST)
**Reason**: 24-72h auto-crawl ETA fully exhausted on v0.3.4 (163h+ elapsed). v0.3.5
LIVE_CONFIRMED on Anthropic Official Registry 2026-05-11 20:02 UTC; expected to
restart Glama auto-crawl clock with a fresher upstream signal, but no guarantee
since W28 144h+ window already produced no listing.

## What was attempted (W41, Agent B)

1. **Glama Discord invite alive check** — `GET https://glama.ai/discord` returns
   302 to `https://discord.com/invite/C3eCXhYWtJ` (200). Invite link is live.

2. **Direct Discord incoming-webhook POST** — checked Glama's public web
   surface for an exposed incoming webhook URL for `#support` or
   `#mcp-servers`. **None found**. Discord webhooks are admin-provisioned
   per-channel; Glama maintainers have not published one publicly. This is
   consistent with the W28 verdict in `glama_discord_escalation.md` (operator
   paste-verbatim is the canonical path).

3. **Bot-OAuth alternative** — using a personal Discord bot account with
   `messages.write` scope would require Glama-admin approval on their server,
   which violates `feedback_zero_touch_solo` (no human-in-the-loop ops at a
   steeper cost than a one-shot paste). Rejected.

4. **Cross-channel escalations available**:
   - PR #6192 comment thread: 6 comments to date (W23 + W28 own posts).
     Adding a W41 follow-up comment is the highest-leverage operator-free
     escalation. Deferred to avoid double-posting on the same day as W28.
     Wave 42+ can dispatch with v0.3.5 evidence.
   - X/Twitter DM to @glama_ai: operator-only path (no API tokens stored).
   - GitHub issue on the Glama org repo: no canonical issue tracker URL
     exposed for community submissions; not a viable channel.

## Outcome

**operator_paste_required**.

The canonical message body remains at
`docs/_internal/mcp_registry_submissions/glama_discord_escalation.md` and is
already W41-current (mentions Anthropic Official Registry LIVE, PR #6192
blocked on glama-bot, repo / homepage / topics surface). No edits needed for
W41 paste.

## Why this is operator-only (re-confirmed W41)

- Discord channel-scoped webhooks require Glama-admin provisioning; no
  anonymous incoming-webhook URL is exposed for curl-POST.
- Personal-bot OAuth would require Glama-admin server-side approval —
  steeper cost than a one-shot operator paste.
- Glama has no public REST `submit` endpoint; their `/api/mcp/v1/servers`
  is read-only (verified W22 + W28 + W41).

## Logged at

- `analytics/registry_status_w41.json` → `platforms[id=glama_ai].discord_escalate_attempt_w41`
- This file
