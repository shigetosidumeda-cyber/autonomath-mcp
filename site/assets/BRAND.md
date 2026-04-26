# jpintel-mcp — Brand guidelines

Minimal brand system for a developer-tool API. Priority: legibility and consistency over decoration.

## Colors

| Role    | Value     | Usage                                       |
|---------|-----------|---------------------------------------------|
| Accent  | `#1e3a8a` | Mark background, hero backgrounds, primary CTA, focus ring |
| Primary | `#ffffff` | Page background, on-accent text             |
| Text    | `#0f172a` | Body copy, wordmark on light background     |
| Muted   | `#64748b` | Secondary UI text (labels, captions)        |
| Rule    | `#e2e8f0` | Dividers, table borders                     |

Contrast (WCAG):
- `#0f172a` on `#ffffff` = 18.1:1 (AAA)
- `#ffffff` on `#1e3a8a` = 9.4:1 (AAA)
- `#1e3a8a` on `#ffffff` = 9.4:1 (AAA)

Do not introduce additional accent hues. One brand color keeps the surface legible.

## Typography

System font stack (no web font dependency):

```
-apple-system, BlinkMacSystemFont, "Segoe UI", "Yu Gothic UI",
"Hiragino Sans", system-ui, sans-serif
```

Monospace (code, badges, the `jp` mark):

```
ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace
```

Weights:
- 400 — body copy
- 500 — UI labels
- 600 — headings, wordmark, mark, meta

Letter-spacing:
- Wordmark `jpintel` / `jpintel-mcp`: `-1.2` to `-1.8` (tight)
- Mark `jp`: `-0.5`
- Meta / code: `0`

## Logo usage

### Wordmark (`logo.svg`)
- Minimum width: 80px (wide) / 24px tall
- Clear-space: one letter-height on all sides
- Default color: `#0f172a` on light bg, `#ffffff` on accent bg
- Do NOT re-space letters, do NOT italicize, do NOT add drop-shadow

### Mark (`mark.svg`)
- 40x40 square, 6px rounded corners, `jp` centered
- Minimum size: 24x24 on screen, 16x16 for favicon
- Use only on accent (`#1e3a8a`) background or on pure white (see `favicon-*`)
- The mark is NOT a logo-lockup companion — use wordmark alone in most cases

### Lockup (wordmark + mark)
- Gap between mark and wordmark = 0.4x mark width (e.g. 16px for a 40px mark)
- Vertical-center align to mark
- Never rotate either element

## OG / social images

Three variants under `site/assets/`:
- `og.png` — 1200x630 (default Open Graph)
- `og-twitter.png` — 1200x600 (Twitter summary_large_image)
- `og-square.png` — 1200x1200 (Instagram / LinkedIn / Mastodon)

All share the layout: mark + wordmark top-left, rule + tagline centered, program-count meta bottom-left. Regenerate by running the Chrome headless command documented in `README_badge` history (see repo history for the exact invocation).

## Favicon

- `favicon.svg` — scalable, preferred by modern browsers
- `favicon-32.png` — 32x32 raster
- `favicon-16.png` — 16x16 raster
- `apple-touch-icon.png` — 180x180 for iOS home screen

All use the same `jp` mark on accent background.

## Do NOT

- Rotate the mark or wordmark
- Recolor either (no gradients, no alternate hues, no stroke)
- Stretch or skew — always preserve aspect ratio
- Add drop-shadow, glow, outer ring, or 3D effect
- Place on a busy photo background
- Insert emoji, flag, sakura, kanji-stamp, or other cliché imagery adjacent to the logo
- Translate "jpintel" — it is a proper noun

## Sizes at a glance

| Asset              | Dim         | Format | Bytes (approx) |
|--------------------|-------------|--------|----------------|
| logo.svg           | 200x44      | SVG    | 0.5 KB         |
| mark.svg           | 40x40       | SVG    | 0.5 KB         |
| favicon.svg        | 40x40       | SVG    | 0.5 KB         |
| favicon-16.png     | 16x16       | PNG    | 0.4 KB         |
| favicon-32.png     | 32x32       | PNG    | 0.7 KB         |
| apple-touch-icon   | 180x180     | PNG    | 3.5 KB         |
| og.png             | 1200x630    | PNG    | 34 KB          |
| og-twitter.png     | 1200x600    | PNG    | 33 KB          |
| og-square.png      | 1200x1200   | PNG    | 48 KB          |
| README_badge.svg   | 120x20      | SVG    | 0.5 KB         |
