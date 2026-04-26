---
name: Signal — User feedback
about: Email to info@bookyou.net, Zenn comment, or HN thread originated. Convert to Issue so it enters the priority queue.
title: "[feedback] "
labels: ["triage"]
---

## Signal type

User feedback (email / Zenn / HN / X)

## Source

- [ ] Email to info@bookyou.net
- [ ] GitHub Issue (direct — add priority label and close this)
- [ ] Zenn comment — article URL: ___
- [ ] HN thread — URL: ___
- [ ] X / other social

## User message (redacted)

<!-- Paste verbatim, removing any PII (email, API key, company name if not needed). -->

```
Date:
Channel:
Message:
```

## Signal classification

- [ ] **Bug report** → relabel `bug`, apply decision tree for PC level
- [ ] **Data gap** → relabel `data-gap`, apply H1–H5 heuristics (docs/improvement_loop.md §5)
- [ ] **Docs gap** → relabel `docs-gap`, typically PC3/PC4
- [ ] **Feature request** → relabel `feature-request`, default PC4
- [ ] **Abuse / spam** → relabel `abuse`, check rate-limit logs
- [ ] **Growth opportunity** → relabel `growth-opp` (e.g. user asking if we cover a dataset we don't yet)

## Priority (after classification)

- [ ] PC0 — paying customer, broken
- [ ] PC1 — vocal named user, widespread or common path broken
- [ ] PC2 — 中核 use case degraded
- [ ] PC3 — user blocked but has workaround
- [ ] PC4 — polish / nice-to-have

## Operator reply sent?

- [ ] Yes — reply sent within 24 h (email or comment)
- [ ] No — not yet

## Definition of done

- [ ] User received a reply (even if "noted, in backlog")
- [ ] If actionable: fix merged and user notified via the same channel
- [ ] If PC4 batch: closed with "added to quarterly batch" comment
