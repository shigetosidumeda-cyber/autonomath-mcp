# jpcite — Brand Guidelines

Updated 2026-04-30 with the official logo lockup.

Minimal brand system for a developer-tool API. Priority: legibility and consistency over decoration.

## Logo

The official lockup is **mark + wordtype** rendered together. The mark alone may be used in tight spaces (favicon, app icons).

**Mark anatomy** — two shapes:
1. **Dot** (lower-left): citation marker — the bullet that signals a referenced fact.
2. **Page** (upper-right): document with a triangular folded-corner notch — the cited source itself.

The composition reads as "a citation pointing at a source", which is the product's positioning.

### Asset paths

All variants live under `site/assets/brand/`. Public-facing entry points are at `site/assets/` for backward compatibility.

| Use case | File | Notes |
|---|---|---|
| Browser favicon (svg) | `assets/favicon.svg` (= `assets/mark.svg` = `assets/logo.svg`) | currentColor — inherits CSS dark mode |
| Browser favicon (raster) | `assets/favicon-{16,32,192,512}.png` | transparent-bg, fill `#0d1117` |
| Apple touch icon | `assets/apple-touch-icon.png` | 180×180, transparent |
| Lockup (cream bg) | `assets/brand/jpcite-lockup-light.png` | 1033×302, official light-theme lockup |
| Lockup (black bg) | `assets/brand/jpcite-lockup-dark.png` | 1033×302, official dark-theme lockup |
| Lockup sized | `assets/brand/lockup-{300,600,900,1200,1600}-{light,dark}.png` | preset widths |
| Mark only sized | `assets/brand/mark-{16,32,64,128,256,512,1024}-{light,dark}.png` | with bg color (cream/black) baked in |
| Mark transparent | `assets/brand/mark-transparent-{16,32,64,128,180,192,256,512,1024}-{light,dark}.png` | for OS / app launchers |
| OG image (1200×630) | `assets/og.png` (= `assets/og-twitter.png`) | lockup on cream |
| OG square (1200×1200) | `assets/og-square.png` | mark on cream, for some platforms |
| Source bitmaps | `assets/brand/raw/jpcite-lockup-{light,dark}-source.png` | original 1672×941 PNG, immutable reference |

### Re-rasterizing

To regenerate sized PNGs from the SVG, run:

```bash
.venv/bin/python -c "
import cairosvg
SVG = open('site/assets/brand/jpcite-mark.svg').read().replace('currentColor', '#0d1117')
for size in (16, 32, 64, 128, 180, 192, 256, 512, 1024):
    cairosvg.svg2png(bytestring=SVG.encode(),
        write_to=f'site/assets/brand/mark-transparent-{size}-light.png',
        output_width=size, output_height=size)
"
```

To regenerate from the source bitmap (lockup PNG variants), see the script at the head of this commit's diff.

## Colors

| Role | Value | Usage |
|---|---|---|
| Logo (light theme) | `#0d1117` | Mark + wordtype on cream / white background |
| Logo (dark theme) | `#fafafa` | Mark + wordtype on near-black background |
| Background (light) | `#fcf8f4` (source) / `#ffffff` (web) | Source uses cream; site uses pure white |
| Background (dark) | `#0d1117` | Used by `prefers-color-scheme: dark` site CSS |
| Accent | `#1e3a8a` | CTA buttons, focus ring |
| Text | `#111111` (light) / `#e6edf3` (dark) | Body copy |
| Muted | `#404040` (light) / `#8b949e` (dark) | Captions, labels |
| Border | `#e5e5e5` (light) / `#30363d` (dark) | Dividers |

WCAG (contrast):
- `#0d1117` on `#fcf8f4` = 18.4 : 1 (AAA)
- `#fafafa` on `#0d1117` = 18.0 : 1 (AAA)
- `#1e3a8a` on `#ffffff` = 9.4 : 1 (AAA)

Do not introduce additional accent hues. One brand color keeps the surface legible.

## Typography

System font stack (no web font dependency for lockup; web fonts only on documentation):

```
-apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Yu Gothic UI",
"Meiryo", system-ui, sans-serif
```

Monospace (code blocks):

```
ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace
```

The wordtype in the official lockup is a custom-spaced "jpcite" rendering. When using "jpcite" in HTML body text, system fonts are acceptable — do NOT try to recreate the lockup with web text.

## Usage rules

- **Min size**: lockup ≥ 200 px wide. Below that, use mark only.
- **Clear space**: minimum padding around the lockup = the height of the dot (≈ 1/4 of the lockup height).
- **Backgrounds**: cream / white / near-black only. NO gradients, NO photo backgrounds, NO outline strokes, NO color fills other than `#0d1117` or `#fafafa`.
- **Don't**: stretch, rotate, recolor outside the palette, recombine the dot and page into a single shape, italicize, or add drop-shadow.
- **Dark mode**: web pages use the SVG with `currentColor` so it auto-flips with `prefers-color-scheme`. For static contexts, choose `lockup-dark.png` or `mark-transparent-*-dark.png` explicitly.

## Sizes at a glance

| Asset | Dimensions | Format |
|---|---|---|
| `assets/favicon.svg` (= mark.svg, logo.svg) | viewBox 256×256 | SVG (currentColor) |
| `assets/favicon-16.png` | 16×16 | PNG (transparent) |
| `assets/favicon-32.png` | 32×32 | PNG (transparent) |
| `assets/favicon-192.png` | 192×192 | PNG (transparent) |
| `assets/favicon-512.png` | 512×512 | PNG (transparent) |
| `assets/apple-touch-icon.png` | 180×180 | PNG (transparent) |
| `assets/og.png` (= og-twitter.png) | 1200×630 | PNG (cream bg, light lockup) |
| `assets/og-square.png` | 1200×1200 | PNG (cream bg, mark) |
| `assets/brand/jpcite-lockup-light.png` | 1033×302 | PNG (cream bg) |
| `assets/brand/jpcite-lockup-dark.png` | 1033×302 | PNG (black bg) |
