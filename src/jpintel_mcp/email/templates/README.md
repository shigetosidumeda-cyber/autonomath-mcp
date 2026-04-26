# Email templates

These `.html` / `.txt` pairs are the **source of truth** for every onboarding
email. The runtime uses Postmark's server-side templates (see
`postmark.py::_send`'s `template_alias` path) — the Postmark UI holds a copy
of each template keyed by alias. **These files are the canonical version**;
if Postmark's copy drifts, copy these back in.

The copy in Postmark is edited by humans through the UI without a deploy.
So we keep this repo copy as a read-reference and regression baseline. A CI
check (TODO, post-launch) could diff them. For now the alignment is
human-maintained: whenever anyone edits a Postmark template, mirror the
change here in the same PR.

## Template aliases

| File                         | Postmark `TemplateAlias` | Fired by                          |
|------------------------------|--------------------------|-----------------------------------|
| `onboarding_day0.html/.txt`  | `onboarding-day0`        | `send_day0_welcome` (synchronous, from `api/billing.py`) |
| `onboarding_day1.html/.txt`  | `onboarding-day1`        | `send_day1_quick_win` (via scheduler) |
| `onboarding_day3.html/.txt`  | `onboarding-day3`        | `send_day3_activation`            |
| `onboarding_day7.html/.txt`  | `onboarding-day7`        | `send_day7_value`                 |
| `onboarding_day14.html/.txt` | `onboarding-day14`       | `send_day14_inactive_reminder`    |
| `onboarding_day30.html/.txt` | `onboarding-day30`       | `send_day30_feedback`             |
| `dunning.html/.txt`          | `dunning`                | `send_dunning` (from `api/billing.py` invoice.payment_failed) |
| `key_rotated.html/.txt`      | `key-rotated`            | `send_key_rotated` (from `api/me.py` /v1/me/rotate-key, P1 from key-rotation audit a4298e454aab2aa43) |

All HTML files carry a consistent footer with:
  - contact: `info@bookyou.net` (operator's monitored address; standardised across D+0/D+1/D+3/D+7/D+14/D+30/dunning 2026-04-25)
  - legal entity: `Bookyou 株式会社 (T8010001213708)`
  - unsubscribe: `{{{pm:unsubscribe}}}` (Postmark built-in) — D+0 is a
    transactional receipt and intentionally does NOT carry an unsubscribe
    link; D+1 onwards do.

## `TemplateModel` variables

Most templates share the same base model so the Postmark UI dropdowns
stay consistent. D+0 is the outlier — it is the ONE place the full API
key is rendered, because it is the receipt of key issuance.

| Variable          | Type    | Template(s)   | Notes                                              |
|-------------------|---------|---------------|----------------------------------------------------|
| `email`           | str     | D+0           | Recipient address, shown in greeting line.         |
| `api_key`         | str     | D+0           | Raw API key. Shown once, never persisted.          |
| `key_last4`       | str     | all           | Last 4 chars of the key (D+0 also carries it).     |
| `tier`            | str     | all           | `"free"` / `"paid"`.                               |
| `usage_count`     | int     | D+1, D+3, D+7, D+14, D+30 | Cumulative requests over the customer's lifetime.  |
| `has_used_key`    | bool    | D+3, D+30     | `usage_count > 0`.                                 |
| `examples`        | list    | D+3 only      | The 3 pinned `{unified_id,name,bucket}`.           |
| `unsubscribe_url` | str     | D+1           | Defaults to `{{{pm:unsubscribe}}}` for Postmark's built-in one-click link; overridable by caller. |
| `old_suffix`      | str     | key-rotated   | Last 4 chars of the revoked key.                   |
| `new_suffix`      | str     | key-rotated   | Last 4 chars of the freshly-issued key.            |
| `ip`              | str     | key-rotated   | Caller IP (X-Forwarded-For first hop or request.client.host). |
| `user_agent`      | str     | key-rotated   | Caller User-Agent header, truncated at 256 chars.  |
| `ts_jst`          | str     | key-rotated   | JST-formatted rotation timestamp ("YYYY-MM-DD HH:MM JST"). |

Every template also uses Postmark's built-in `{{{pm:unsubscribe}}}`
placeholder in the footer. Postmark's subscription-change webhook
(`/v1/email/webhook`, `RecordType=SubscriptionChange`) flips the
matching `subscribers` row's `unsubscribed_at` so the scheduler skips
future sends — see `scripts/send_scheduled_emails.py`.
