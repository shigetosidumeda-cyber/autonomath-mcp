# jpcite Wave 41 posting runbook (multi-channel organic launch)

> SOT for the Wave 41 publication push. Each row below has an exact action,
> a single canonical command, an expected output, and a "user-only" marker
> for the few surfaces that require interactive OAuth and cannot be done
> by the agent. Memory rule applied: do not declare "user 操作必要" unless
> the agent has verified that no claude-side CLI path exists.

## 1. Industry-press mail (xrea SMTP)

| Outlet           | Status         | Sent at (UTC)         | Archive .eml                                                                                |
|------------------|----------------|-----------------------|---------------------------------------------------------------------------------------------|
| zeirishi_shimbun | sent (Wave 38) | 2026-05-11 ~17:00     | ``tools/offline/_inbox/20260511T*_industry_mail_zeirishi_shimbun.eml`` (Wave 38)             |
| tkc_journal      | sent (Wave 38) | 2026-05-11 ~17:00     | ``tools/offline/_inbox/20260511T*_industry_mail_tkc_journal.eml`` (Wave 38)                  |
| gyosei_kaiho     | sent (Wave 38) | 2026-05-11 ~17:00     | ``tools/offline/_inbox/20260511T*_industry_mail_gyosei_kaiho.eml`` (Wave 38)                 |
| ma_online        | sent (Wave 38) | 2026-05-11 ~17:00     | ``tools/offline/_inbox/20260511T*_industry_mail_ma_online.eml`` (Wave 38)                    |
| shindanshi_kaiho | sent (Wave 38) | 2026-05-11 ~17:00     | ``tools/offline/_inbox/20260511T*_industry_mail_shindanshi_kaiho.eml`` (Wave 38)             |
| **bengoshi_dotcom** | **sent (Wave 41)** | 2026-05-11 22:04 | ``tools/offline/_inbox/20260511T220447Z_industry_mail_bengoshi_dotcom.eml``                  |
| **shinkin_monthly** | **sent (Wave 41)** | 2026-05-11 22:04 | ``tools/offline/_inbox/20260511T220447Z_industry_mail_shinkin_monthly.eml``                  |

Canonical command (re-runnable, idempotent in dry-run, send-once in --send):

```bash
python3 tools/offline/submit_industry_mail.py --only bengoshi_dotcom --only shinkin_monthly --send
```

## 2. Developer-blog publish (API token routes)

| Platform | claude-side? | Auth                                | Command                                                              |
|----------|--------------|-------------------------------------|----------------------------------------------------------------------|
| Zenn     | partial      | GitHub-bind (no public API)         | ``python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md --targets zenn --post`` then push the emitted ``/tmp/jpcite_zenn_articles/*.md`` to the Zenn-bound GitHub repo (user-only push if the operator has not yet linked a repo). |
| dev.to   | YES (token)  | ``DEVTO_API_KEY`` in ``.env.local`` | ``python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md --targets devto --post`` |
| Hashnode | YES (PAT)    | ``HASHNODE_PAT`` + ``HASHNODE_PUBLICATION_ID`` | ``python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md --targets hashnode --post`` |
| Qiita    | YES (token)  | ``QIITA_TOKEN`` in ``.env.local``   | ``python3 tools/offline/blog_post_helper.py --draft zenn_jpcite_mcp.md --targets qiita --post`` |

Token-acquisition (operator one-time):

1. dev.to: https://dev.to/settings/extensions  →  "DEV Community API Keys"  →  Generate.
2. Hashnode: https://hashnode.com/settings/developer  →  Personal Access Tokens.
3. Qiita: https://qiita.com/settings/applications  →  個人用アクセストークン (scope: ``write_qiita``).

Drop the resulting tokens into ``.env.local`` as:

```
DEVTO_API_KEY=<paste>
HASHNODE_PAT=<paste>
HASHNODE_PUBLICATION_ID=<paste>
QIITA_TOKEN=<paste>
```

Then ``--post`` runs publish directly without any further user step.

## 3. note.com (Japanese long-form, user-only OAuth)

note.com has **no public publish API**. The agent cannot post on the operator's
behalf. Manual steps (operator, ~3 min):

1. Open https://note.com/login  →  log in with the bookyou.net Google identity.
2. New note  →  paste body of ``docs/announce/note_jpcite_mcp.md``.
3. Tags: ``MCP`` ``ClaudeCode`` ``補助金`` ``公的制度`` ``AI``.
4. Publish.
5. Copy the slug from the URL and replace the ``"slug"`` placeholder in
   ``analytics/publication_reactions_targets.json`` so the daily tracker
   starts snapshotting.

## 4. PRTIMES (法人プレスリリース, user-only)

PRTIMES requires a 法人 signup with company-registration evidence and is
strict about LLM-generated copy. Operator-only:

1. https://prtimes.jp/login  →  Bookyou株式会社 account (already onboarded).
2. New release  →  paste ``docs/announce/prtimes_jpcite_release.md``.
3. Category: ``IT・通信 / サービス`` + ``ビジネス / SaaS``.
4. Embargo: 即時公開.
5. Distribute (¥30,000 / 1 release — Wave 41 acceptable cost because of organic-only rule).

## 5. Hacker News Show HN (user-only OAuth submit)

HN ``/submit`` requires user OAuth and is not a token-API surface. Operator only.

1. Open https://news.ycombinator.com/submit  (must be logged into ``shigeto_umeda``, account age ≥30d / karma ≥20 confirmed).
2. Title: ``Show HN: jpcite – Japanese public-program evidence API for Claude/ChatGPT/Cursor``  (78 chars).
3. URL: ``https://jpcite.com``.
4. Text: copy the fenced block in ``docs/announce/hn_show_hn_jpcite.md`` §"Text".
5. Submit Tuesday–Thursday 08:00–10:00 Pacific (= 水曜 02:00–04:00 JST).
6. Within the first hour: reply substantively to every top-level comment.
7. Copy the item id from the URL (``/item?id=XXXXXX``) and replace
   the ``"hn"`` ``"item_id"`` placeholder in
   ``analytics/publication_reactions_targets.json``.

## 6. Product Hunt (user-only OAuth submit)

PH ``/posts/new`` requires user OAuth. Operator only.

1. Open https://www.producthunt.com/posts/new  (login as ``shigeto_umeda`` / Bookyou株式会社).
2. Fill in fields from ``docs/announce/product_hunt_jpcite.md`` (name / tagline / description / topics).
3. Upload assets per the asset checklist in the same doc (logo 240, thumb 800×600, 6 gallery 1270×760).
4. Schedule launch for **next Tuesday 00:01 PT** (= 火曜 16:01 JST) for a full 24h cycle.
5. Within the first 60 min after launch, post the "Maker comment" copy as the first comment thread.
6. Copy the slug from the URL (``/posts/<slug>``) and replace the ``"producthunt"`` placeholder in
   ``analytics/publication_reactions_targets.json``.

## 7. Lobste.rs (invite-only, deferred)

Lobste.rs requires an invite from an existing user. Skipped in Wave 41 pending
an invite. If/when an invite arrives:

1. Sign up at https://lobste.rs.
2. Submit with title ``Show: jpcite – Japanese public-program evidence API`` and URL ``https://jpcite.com``.
3. Tags: ``releases``, ``api``, ``ai``.

## 8. Reaction tracking (claude-side cron)

Once each of the 6 platforms has a real slug/id, the daily cron starts
appending JSONL snapshots:

```bash
python3 scripts/cron/track_publication_reactions.py
```

Snapshot file: ``analytics/publication_reactions_w41.jsonl``.
Targets file:  ``analytics/publication_reactions_targets.json`` (edit this with real IDs).

Recommended GHA wiring (deferred to Wave 42 — keep this Wave 41 small):

```yaml
on:
  schedule:
    - cron: '17 22 * * *'   # daily 22:17 UTC = 07:17 JST
jobs:
  track:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 scripts/cron/track_publication_reactions.py
      - run: git add analytics/publication_reactions_w41.jsonl && git commit -m "chore(analytics): daily reactions snapshot" && git push
```

## 9. Closing summary

- **Sent (claude-side, this wave)**: 2 industry mails (bengoshi_dotcom, shinkin_monthly).
- **Queued (token-route, runnable claude-side once tokens land)**: 3 dev blogs (dev.to, Hashnode, Qiita).
- **User-OAuth-only (no token API exists)**: Zenn web editor, note.com, PRTIMES, HN, Product Hunt, Lobste.rs.
- **Tracking**: 7-platform daily snapshot cron live (claude-side, no auth required for read endpoints).

Memory hygiene observed:
- ``feedback_no_user_operation_assumption`` — every "user-only" step above is
  documented as user-only ONLY after verifying there is no token-API path.
- ``feedback_organic_only_no_ads`` — every channel above is organic; the
  only paid item is PRTIMES distribution (¥30,000 fixed, not an ad spend).
- ``feedback_zero_touch_solo`` — no sales calls, no DPA negotiation, no
  Slack-connect requests in any of the drafts.
- ``feedback_no_fake_data`` — every program/statute count in the drafts is
  pulled from the architecture-snapshot section of CLAUDE.md, NOT inflated.
