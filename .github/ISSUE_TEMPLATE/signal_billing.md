---
name: Signal — Billing failure
about: Stripe webhook delivery failure or checkout session drop. PC0 if affecting a paying key. Convert from Stripe dashboard or monitoring alert.
title: "[bug] billing failure: "
labels: ["bug", "PC0", "triage"]
---

## Signal type

Billing / Stripe failure

**Default priority: PC0.** Downgrade to PC1 only if confirmed no paying customer is affected.

## Evidence

```
stripe_event_id:
event_type:          # e.g. invoice.payment_failed, checkout.session.expired
customer_id:
api_key_prefix:      # first 8 chars only — never log the full key
timestamp (UTC):
webhook_delivery_attempts:
last_http_status_from_our_endpoint:
```

## Failure mode

- [ ] Webhook endpoint returned 5xx (our side)
- [ ] Webhook endpoint timed out (> 30 s)
- [ ] Stripe could not reach our endpoint (DNS/TLS failure)
- [ ] `invoice.payment_failed` — customer card declined
- [ ] `checkout.session.expired` — user abandoned before payment
- [ ] Metered billing record not incremented (`jpintel.billing` structlog missing)
- [ ] Other (describe):

## Customer impact

- [ ] Paying customer's API key suspended incorrectly
- [ ] Paying customer billed but quota not granted
- [ ] Anonymous user affected (not billing, but 429-related side effect)
- [ ] No direct customer impact (internal accounting gap)

## Immediate mitigation (if PC0)

<!-- What you did in the first 4 hours to stop the bleeding. -->

## Root cause analysis

<!-- To be filled after fix. -->

## Definition of done

- [ ] Stripe webhook delivery succeeds with HTTP 200 from our endpoint
- [ ] Affected customer's quota restored to correct value
- [ ] `scripts/stripe_smoke_e2e.py` passes end-to-end
- [ ] Root cause documented in `docs/_internal/incident_runbook.md`
- [ ] Prevention mechanism merged (not just the patch)
