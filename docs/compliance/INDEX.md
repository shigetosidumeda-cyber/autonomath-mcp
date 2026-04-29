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

## 税理士法 §52 / 弁護士法 §72 fence

The brand sits at `zeimu-kaikei.ai` — 税務会計 territory — and the operator (Bookyou 株式会社) has no licensed 税理士 / 弁護士 staff. Every tax-related surface MUST declare the output information retrieval, NOT 税務助言:

- **Site copy** — `site/tos.html`, `site/en/tos.html`, `site/audiences/tax-advisor.html`, `site/en/audiences/tax-advisor.html`, `site/index.html`, `site/pricing.html` carry the disclaimer prominently (callout box, NOT footer-only).
- **TOS** — `tos.html` §5 covers 弁護士法 §72 / 税理士法 §52 / 公認会計士法 §47-2 / 社会保険労務士法 §27 / 行政書士法 §1-2.
- **API responses** — `/v1/tax_rulesets/*` (search / get / evaluate), `/v1/am/tax_incentives`, `/v1/am/tax_rule` inject `_disclaimer` 注記 key. See `src/jpintel_mcp/api/tax_rulesets.py:_TAX_DISCLAIMER` and `src/jpintel_mcp/api/autonomath.py:_TAX_DISCLAIMER`.
- **MCP tools** — `search_tax_incentives`, `get_am_tax_rule`, `list_tax_sunset_alerts` are listed in `envelope_wrapper.SENSITIVE_TOOLS` so every MCP 注記 carries `_disclaimer`. Mirrors `combined_compliance_check` / `rule_engine_check` pattern.

Disclaimer copy (canonical Japanese — translate to EN for `/en/*`):

> 本情報は税務助言ではありません。 AutonoMath は公的機関が公表する税制・補助金・法令情報を検索・整理して提供するサービスで、 税理士法 §52 に基づき個別具体的な税務判断・申告書作成代行は行いません。 個別案件は資格を有する税理士に必ずご相談ください。 本サービスの情報利用により生じた損害について、 当社は一切の責任を負いません。

Solo + zero-touch: **DO NOT** add references to "弊社の税理士チーム" / "提携税理士" / "サポート窓口" — those don't exist. The disclaimer routes users to **their own** 税理士.
