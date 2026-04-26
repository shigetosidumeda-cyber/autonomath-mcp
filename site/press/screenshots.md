# Screenshots catalog

Press-kit screenshots are **not bundled** into this repo — files are 100-400KB each and
would balloon the repo. Source images live under `/tmp/ux_jpintel/` on the maintainer's
machine and must be **regenerated on launch** (post-domain + post-rebrand) before release
to press.

Regenerate via Playwright walk (width ≤ 1880px, per project convention):
```
python scripts/ux_walk.py --out /tmp/ux_jpintel
```

## Available shots (2026-04-23)

| File | ~Size | What it shows |
|---|---|---|
| `ux_index.png` | 217 KB | Landing hero + features + demo |
| `ux_index_newsletter.png` | 130 KB | Newsletter section close-up |
| `ux_pricing.png` | 161 KB | Pricing page (4 tiers) |
| `ux_privacy.png` | 322 KB | Privacy policy full page |
| `ux_tos.png` | 410 KB | Terms of service full page |
| `ux_tos_tall.png` | 418 KB | ToS tall viewport |
| `ux_tokushoho.png` | 268 KB | 特定商取引法 page |
| `ux_tokushoho_fixed.png` | 268 KB | 特商法 post-fix |
| `ux_tokushoho_fixed_top.png` | 212 KB | 特商法 above-the-fold |
| `ux_tokushoho_top.png` | 212 KB | 特商法 top portion |
| `ux_docs_index.png` | 211 KB | Docs landing |
| `ux_dashboard.png` | 91 KB | User dashboard |
| `ux_dashboard_top.png` | 54 KB | Dashboard above-the-fold |
| `ux_unsubscribe.png` | 27 KB | Newsletter unsubscribe flow |

## Press-use guidance

- Preferred width: 1440-1880 px (Retina-safe, CLI-safe).
- No dark-mode variants yet; requests accepted post-launch.
- Crop/edit at will — logo must not be altered (see `logos.zip`).

## Requesting high-res press pack

Email `hello@<DOMAIN_PLACEHOLDER>` with outlet + deadline.
Response SLA: 24h JST business-day.
