# jpcite distribution assets — spec (2026-05-11)

This document lists every visual / video asset the jpcite distribution surfaces
(GitHub repo, PyPI page, npm page, MCP marketplaces, Product Hunt, jpcite.com)
need in order to look credible to a developer landing cold from search / a
catalog listing. Use this as the operator-side production checklist.

Operator-only document. NO external production agencies, NO timeline phases,
NO budget framing — per CLAUDE.md operating principles (`feedback_zero_touch_solo`,
`feedback_no_cost_schedule_hr`, `feedback_no_priority_question`). Either an
asset is made or it is not; the worksheet below is a flat list of "what should
exist," not a sequencing plan.

---

## 1. Inventory — what already exists in the repo

Probed under `site/assets/` and `site/og/` on 2026-05-11.

| Slot                         | Status   | Path                                         |
|------------------------------|----------|----------------------------------------------|
| Brand wordmark / logo (SVG)  | exists   | `site/assets/logo.svg`, `site/assets/logo-v2.svg` |
| Brand mark (icon-only, SVG)  | exists   | `site/assets/mark.svg`, `site/assets/mark-v2.svg` |
| Favicon (multi-size)         | exists   | `favicon.ico` + `favicon-16.png` + `favicon-32.png` + `favicon-192.png` + `favicon-512.png` + `favicon.svg` + `favicon-v2.svg` |
| Apple touch icon             | exists   | `site/assets/apple-touch-icon.png` |
| Open Graph (1200x630)        | exists   | `site/assets/og.png` |
| OG square variant            | exists   | `site/assets/og-square.png` |
| OG Twitter variant           | exists   | `site/assets/og-twitter.png` |
| Per-page OG images           | exists   | `site/og/*.png` (advisors, trial, status, stats, compare, …) |
| GitHub social card           | exists   | `site/assets/github-social-card.png` |
| MCP preview screenshots      | exists   | `site/assets/mcp_preview_1.png`, `mcp_preview_2.png` |
| README status badge          | exists   | `site/assets/README_badge.svg` |
| Demo illustration            | exists   | `site/assets/demo.svg` |

These are sufficient for the existing static site and the GitHub repo card.
The gaps below are about **package registries** (PyPI / npm) and **discovery
surfaces** (Product Hunt, MCP catalogs, Zenn / note / PR TIMES editorial),
which want sizes that the current `site/` assets do not yet produce.

---

## 2. Gap list — what is still missing

Each row lists one asset slot with: (1) the exact spec a downstream surface
wants, (2) the distribution surface(s) that consume it, (3) the production
recipe.

### 2.1 Logo PNG @ 1024×1024 (transparent background)

- **Why**: PyPI does not render SVG on the project page chrome (description
  area renders PNG only). Several MCP catalogs (Smithery, mcp-server.json
  registries, Glama) want a square PNG ≥512px with transparent background.
  Product Hunt's "thumbnail" slot wants 240×240 PNG; supplying 1024×1024
  lets Product Hunt + Zenn editorial down-rez cleanly.
- **Surfaces**: Smithery registry tile · Glama tile · Product Hunt
  thumbnail · Zenn account avatar · note magazine cover · PyPI long-description
  banner (embedded via README image link) · GitHub repo `social_preview`
  fallback.
- **Source of truth**: `site/assets/logo-v2.svg`.
- **Recipe (Mac, no external dep beyond stock tooling + `rsvg-convert`)**:
  ```bash
  # rsvg-convert ships via `brew install librsvg` (one-time)
  rsvg-convert -w 1024 -h 1024 -b "rgba(255,255,255,0)" \
    site/assets/logo-v2.svg \
    -o site/assets/logo-1024.png

  # Also produce the 512 size used by some MCP registries
  rsvg-convert -w 512 -h 512 -b "rgba(255,255,255,0)" \
    site/assets/logo-v2.svg \
    -o site/assets/logo-512.png
  ```
- **Sanity check**: `sips -g pixelHeight -g pixelWidth site/assets/logo-1024.png`
  should print `1024 / 1024`. Open in Preview and confirm transparent
  checkerboard around the mark, not white.

### 2.2 Banner / hero image @ 1280×640

- **Why**: GitHub repository "social preview" wants exactly 1280×640 (also
  acceptable: 1280×720 / 2:1 ratio). Product Hunt gallery wants 1270×760
  (close enough to crop from 1280×640 if mounted with safe-margins).
  Several MCP catalogs surface a banner above the README on the package
  page.
- **Surfaces**: GitHub social preview (Settings → Options → Social
  preview) · Product Hunt gallery · MCP registry listing pages.
- **Composition**: full-bleed jpcite wordmark on left third, single
  primary tagline on right two-thirds. Avoid stacking more than one
  sentence — small renders eat anything below ~32pt.
- **Tagline (locked, single-sentence)**: 「日本の制度横断 REST + MCP API ¥3/req。
  匿名 3 req/日 無料。出典 URL 必須。」
- **Recipe (Figma / Affinity / Sketch / any vector tool the operator
  already owns)**:
  1. New 1280×640 canvas, background = `#0b1220` (matches site dark
     accent in `site/styles/*.css`).
  2. Place `logo-v2.svg` at 1.5x site-header scale, vertically centered,
     left-anchored with 96px margin.
  3. Right column: tagline in `Noto Sans JP Bold 56pt` (or system
     equivalent), color `#e6f0ff`.
  4. Export `site/assets/banner-1280x640.png` (PNG, no transparency).
- **Sanity check**: file <200 KB; readable on a 320px phone preview
  (GitHub mobile renders the social preview at ~320×160).

### 2.3 Product screenshots @ 1920×1080 (3 to 5 shots)

- **Why**: Product Hunt mandates ≥3 gallery shots at 1270×760 minimum;
  Zenn / note articles render images at desktop widths and benefit from
  1080p source so retina screens stay crisp. Most importantly, an MCP
  developer landing on the package page wants to see what they get
  *before* installing.
- **Surfaces**: Product Hunt gallery · Zenn cover image fallback ·
  README screenshots block · MCP registry "preview" tab.
- **Shot list (5 total — operator picks the 3 best for Product Hunt,
  all 5 land in the README)**:
  1. **`shot_01_search.png`** — `https://jpcite.com/search.html` with a
     populated result list (e.g. query `"省エネ"`), tier badges visible.
  2. **`shot_02_program_detail.png`** — single program page showing
     `source_url` chip, eligibility section, exclusion-rule banner.
  3. **`shot_03_mcp_install.png`** — Claude Desktop / VS Code MCP
     extension settings panel mid-install of `autonomath-mcp`, with
     the registry entry highlighted. (Reuses the framing from
     `mcp_preview_1.png` but at 1920×1080.)
  4. **`shot_04_curl_response.png`** — terminal showing
     `curl -s https://api.jpcite.com/v1/programs/search?q=...` JSON
     pretty-printed via `jq`, with `source_url` and `tier` lines
     highlighted.
  5. **`shot_05_dashboard.png`** — `https://jpcite.com/dashboard.html`
     for an authenticated key showing usage events + JST reset note +
     ¥-cap widget.
- **Recipe (Mac, no external app)**:
  ```bash
  # Set Chrome to a clean 1920x1080 window
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --window-size=1920,1080 \
    --window-position=0,0 \
    --hide-scrollbars \
    https://jpcite.com/search.html

  # macOS screenshot of the active window: Cmd+Shift+4, then Space, click
  # the Chrome window. Saves to ~/Desktop/.

  # Crop to exact 1920x1080 if the OS added padding:
  sips -c 1080 1920 ~/Desktop/screenshot.png \
    --out site/assets/screenshots/shot_01_search.png
  ```
  For the terminal shot: `iTerm2 → Profiles → Window → Columns 160 /
  Rows 40 → font 14pt Menlo`. Run the `curl | jq` command, screenshot
  the iTerm window with Cmd+Shift+4 + Space.
- **Sanity check**: every shot must use real, current production data
  (no staging URLs, no placeholder names) and must have at least one
  `source_url` visible — per `feedback_no_fake_data`.
- **Layout note**: store under `site/assets/screenshots/` so the README
  can reference `https://jpcite.com/assets/screenshots/shot_01_search.png`
  via Cloudflare Pages.

### 2.4 Intro video @ 30–90 seconds, mp4 (H.264, 1080p)

- **Why**: Product Hunt's launch listing renders the first asset as the
  hero; an under-90-second video outperforms a static thumbnail.
  Several MCP catalogs have started accepting demo videos. Zenn / note
  embed YouTube; PR TIMES embeds mp4 directly.
- **Surfaces**: Product Hunt hero · jpcite.com hero replacement
  (`site/index.html`) · YouTube unlisted · Zenn / note embed · MCP
  marketplace entry.
- **Spec**:
  - Container: mp4 (H.264 video, AAC audio).
  - Resolution: 1920×1080.
  - Frame rate: 30 fps.
  - Bitrate: 6–8 Mbps (under 100 MB for a 90-second clip).
  - Audio: optional. Keep silent if narration is not authored — silent
    videos render fine on Product Hunt; voiceover that sounds AI-
    generated reads worse than no narration.
  - Captions: burn-in subtitles in `.srt` if narration is included
    (Product Hunt mutes by default on autoplay).
- **Script (≤90 seconds — operator films directly, OBS Studio captures
  the screen — installed via `brew install obs` or downloaded from
  https://obsproject.com)**:
  ```
  0:00–0:08   Static: "jpcite — Japan public-program REST + MCP API"
              (banner card; jpcite logo + tagline; no movement)
  0:08–0:20   Screen: VS Code with .vscode/mcp.json open.
              Cursor pastes: { "jpcite": { "command": "npx", "args": ["-y", "@autonomath/sdk"] } }
              File save → MCP icon turns green in status bar.
  0:20–0:35   Screen: VS Code chat panel.
              Type: "東京都の省エネ補助金を tier S/A だけ教えて"
              Agent calls jpcite MCP, response renders 3-5 programs with
              tier badges + source_url chips.
  0:35–0:55   Screen: terminal split.
              Left:  curl -sS "https://api.jpcite.com/v1/programs/search?q=省エネ&tier=S,A&prefecture=東京都" | jq '.results[0]'
              Right: same JSON shape highlighted.
              Caption: "Same data. REST or MCP. ¥3/req. 3 req/day anonymous."
  0:55–1:15   Screen: jpcite.com/dashboard.html.
              Show usage events, JST reset, ¥-cap widget.
              Caption: "Anonymous tier resets 00:00 JST. No tiers. No seats."
  1:15–1:30   Closing card: "pip install autonomath  ·  npm i @autonomath/sdk
                              jpcite.com"
  ```
- **Recipe (OBS one-time setup, then record-export-trim)**:
  1. OBS scene: one "Display Capture" source for the active monitor at
     1920×1080 → Settings → Output → Recording → format mp4, encoder
     `Apple VideoToolbox H.264`, bitrate 8000 Kbps. Audio: disable
     desktop + mic if narration-free.
  2. Record the steps above start-to-finish without cuts. Re-record if
     anything misfires — editing is not in scope.
  3. Trim the head/tail in QuickTime: `File → Open → Edit → Trim → Done
     → File → Export As → 1080p`.
  4. Save to `site/assets/jpcite-intro-90s.mp4`. Mirror to YouTube
     (unlisted) so Zenn / note can embed.
- **Sanity check**: file <100 MB; ffprobe shows duration <100s,
  resolution 1920×1080, codec h264:
  ```bash
  ffprobe -v error -show_entries stream=width,height,codec_name \
    -show_entries format=duration,size \
    site/assets/jpcite-intro-90s.mp4
  ```
- **No narration policy**: if recording voiceover is awkward, ship
  silent with captions only — silent demos are common on Product Hunt
  and read as deliberate, whereas weak narration reads as amateur.

---

## 3. Asset → surface routing table

| Asset                         | GitHub | PyPI | npm  | Product Hunt | MCP catalogs | jpcite.com | Zenn / note / PR TIMES |
|-------------------------------|--------|------|------|--------------|--------------|------------|------------------------|
| logo-1024.png (transparent)   | repo social preview alt | README image | README image | thumbnail 240×240 | tile / avatar | header (existing SVG primary) | author avatar |
| logo-512.png (transparent)    | —      | —    | —    | —            | tile alt size | —          | —                      |
| banner-1280x640.png           | social preview | —    | —    | gallery 1    | banner       | OG fallback | article cover (Zenn) |
| shot_01..05.png (1920×1080)   | README | README link | README link | gallery 2-4  | preview tab  | screenshots block | article body images |
| jpcite-intro-90s.mp4          | README link | README link | README link | hero slot 1  | demo link    | hero replacement | embed (Zenn/note YouTube; PR TIMES direct mp4) |
| favicon / OG / per-page OG    | already live | — | — | —            | —            | already live | —                      |

---

## 4. Production worksheet (single page, no phases)

Mark each row when the file exists at the listed path. Order is irrelevant —
this is a flat checklist, not a sequence.

```
[ ] site/assets/logo-1024.png         (1024×1024 transparent PNG, ≤200 KB)
[ ] site/assets/logo-512.png          (512×512 transparent PNG, ≤80 KB)
[ ] site/assets/banner-1280x640.png   (1280×640 PNG, ≤200 KB)
[ ] site/assets/screenshots/shot_01_search.png         (1920×1080 PNG)
[ ] site/assets/screenshots/shot_02_program_detail.png (1920×1080 PNG)
[ ] site/assets/screenshots/shot_03_mcp_install.png    (1920×1080 PNG)
[ ] site/assets/screenshots/shot_04_curl_response.png  (1920×1080 PNG)
[ ] site/assets/screenshots/shot_05_dashboard.png      (1920×1080 PNG)
[ ] site/assets/jpcite-intro-90s.mp4                   (≤90s, ≤100 MB, h264 1080p30)
[ ] YouTube unlisted upload of jpcite-intro-90s.mp4    (for Zenn / note embed)
[ ] GitHub repo → Settings → Options → Social preview = banner-1280x640.png
[ ] Product Hunt draft → hero=intro mp4, gallery=banner + 3 shots, thumbnail=logo-1024
[ ] jpcite.com README image links updated to point at /assets/screenshots/*.png
```

After each artifact lands under `site/assets/`, the Cloudflare Pages deploy
automatically serves it at `https://jpcite.com/assets/...` — no extra wiring
needed.

---

## 5. Brand discipline (do not violate)

Per CLAUDE.md and memory:

- The user-facing brand is **jpcite**. Do not surface the historical names
  (税務会計AI / AutonoMath / zeimu-kaikei.ai) in any new asset. They may
  appear only as a small "previously known as" footnote where SEO continuity
  matters — never in a hero, banner, video script, or screenshot caption.
- The PyPI package is `autonomath` and the npm package is `@autonomath/sdk`
  for compatibility with already-published metadata — these strings are
  technical identifiers, not brand surfaces, and must remain as-is in
  install command captions (`pip install autonomath`, `npm i @autonomath/sdk`).
- "jpintel" must not appear in user-facing copy (Intel 著名商標衝突濃厚 —
  see `feedback_zero_touch_solo` and the CLAUDE.md trademark clause). Repo
  paths under `src/jpintel_mcp/` are internal-only.
- Pricing copy in any caption must read **¥3/req fully metered**, **anonymous
  3 req/day**, **no tiers / no seats / no annual minimums**. Do not invent
  "Pro plan" / "Enterprise" / "Free tier" framing.
- Source citations matter on screenshots. Every result visible in a shot must
  show a real `source_url` row — no aggregator placeholders, no demo data.
