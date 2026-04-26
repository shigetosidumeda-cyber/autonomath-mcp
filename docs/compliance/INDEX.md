# compliance/ INDEX

Legal and data-governance documents intended for the public-facing site plus internal governance reference.

| File | Purpose | Typical placement |
|---|---|---|
| `privacy_policy.md` | Privacy policy (personal information / Act on the Protection of Personal Information). | Production `docs/compliance/privacy_policy.md` (public). |
| `terms_of_service.md` | Terms of service covering API, pricing, and liability. | Production `docs/compliance/terms_of_service.md` (public). |
| `landing_disclaimer.md` | Landing-page disclaimer about nature of service (not advisory). | Production `docs/compliance/landing_disclaimer.md` (public). |
| `data_governance.md` | Internal data governance baseline. | Production `docs/compliance/data_governance.md` (public reference). |
| `electronic_bookkeeping.md` | Notes regarding 電子帳簿保存法 / invoice / receipt retention. | Production `docs/compliance/electronic_bookkeeping.md`. |
| `data_subject_rights.md` | Procedures for data subject access / deletion requests. | Production `docs/compliance/data_subject_rights.md`. |
| `tokushoho.md` | 特定商取引法に基づく表記 (canonical docs version, mirrors `site/tokushoho.html`). | Production `docs/compliance/tokushoho.md` (public). |

## Notes

- All of these are drafts. Before going live, a human review is required; legal text in particular should be re-read with today's date and company identity (Bookyou 株式会社 / T8010001213708).
- Do NOT overwrite production versions without a PR and explicit approval.
- Zero-touch / solo principle applies: keep procedures automatable. Avoid adding human-only channels (phone tree, Slack-only).
