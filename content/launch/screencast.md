# AutonoMath Launch Screencast — Storyboard

**Product**: AutonoMath (Bookyou株式会社)
**Launch date**: 2026-05-06
**Target duration**: 45–60 seconds
**Format**: `.mov` (H.264 baseline), 2560×1440 preferred / 1920×1080 minimum, 30 fps
**Audio**: None (silent autoplay; burned-in captions only)
**Caption rule**: JP line above EN line, same font, always.

---

## 1. Production Specs

### Recording tool
- **Primary**: macOS built-in screen recording (`⌘⇧5`) — single-window capture mode
- **If multi-camera** (face-in-corner is not recommended for PH muted auto-play): stick to screen-only. Do not add PIP.

### Resolution
- Preferred: 2560×1440 (scaled display, MacBook Pro 14/16 native)
- Minimum: 1920×1080
- Scale UI to 200% (`System Settings → Displays → More Space` then back one notch) so terminal text reads clearly on mobile

### Window arrangement for multi-window scenes
All windows maximised to full screen unless noted otherwise.

| Scene | Window | Position (1920×1080 reference) |
|-------|--------|-------------------------------|
| Beat 1 | Safari on `mhlw.go.jp` or `maff.go.jp` gov.jp subsidy search | Full screen |
| Beat 2 | iTerm2, single pane | Full screen |
| Beat 3 | Claude Desktop — MCP sidebar visible | Full screen |
| Beat 4 | Claude Desktop — response area | Full screen |
| Beat 5 | Safari on `autonomath.ai` pricing section | Full screen |
| Beat 6 | Split: iTerm2 left (900px wide) + `autonomath.ai` right | Left 900px / Right 1020px |

### Mouse cursor
Set to **Large Black** before recording:
`System Settings → Accessibility → Display → Pointer → Pointer size: max, Pointer outline colour: black`

### Captions
- Burn in with **iMovie** (Title → Lower Third, positioned bottom-centre) or **CapCut desktop** (free).
- Font: **Hiragino Sans W6** or **Noto Sans JP Bold** for JP; same face for EN. Size 42pt (1080p baseline).
- JP caption: top line. EN caption: bottom line. 1 px black stroke, white fill. 8-frame fade in/out.
- Max 35 characters per line, 2 lines per beat (JP line + EN line = 2 total lines on screen).

### Audio
None for v1. If a v2 adds a background track, use royalty-free lo-fi instrumental from Pixabay or Free Music Archive, tempo 80–100 BPM, no vocals, Creative Commons 0 licence.

---

## 2. Beat-by-Beat Storyboard

Total storyboard time: **58 seconds**

---

### Beat 1 — Hook (0:00–0:05) — 5 sec

**Visual**
Safari, full screen. Open `https://www.maff.go.jp/j/supply/hozyo/` — the MAFF subsidy index page. The page shows a long list of PDF links. Click one PDF. The PDF opens: it is a formatted table with 40+ rows, no machine-readable structure, no search field. Pan (scroll) slowly down to show how dense it is.

**Caption**
```
JP: 日本の補助金、1件探すだけで3時間
EN: Finding one subsidy: 3 hours wasted
```
Character counts — JP: 20 chars (OK). EN: 30 chars (OK).

**Action**
Slowly scroll the PDF downward. Do not click anything. Let the visual density speak. No narration needed.

---

### Beat 2 — The fix: REST API (0:05–0:14) — 9 sec

**Visual**
iTerm2, full screen. Menlo 18pt, dark background (Tomorrow Night or Dracula). Run:

```
curl "https://api.autonomath.ai/v1/programs/search?q=スマート農業&tier=S&tier=A&limit=5" \
  -H "Authorization: Bearer $AUTONOMATH_KEY"
```

The response JSON arrives within ~1 second. The five hits are visible: each shows `primary_name`, `tier`, `amount_max_man_yen`, `source_url`.

Use `jq` to pretty-print:
```
curl "..." -H "..." | jq '.results[] | {name: .primary_name, tier, amount: .amount_max_man_yen, url: .source_url}'
```

Pause on the output for 2 seconds so viewers can read tier S/A results and the `source_url` pointing to `maff.go.jp`.

**Caption**
```
JP: 9,998件の制度から curl 1本で即答
EN: 9,998 programs — one curl, instant
```
Character counts — JP: 22 chars (OK). EN: 30 chars (OK).

**Action**
Type the command (or paste it — keep key actions at a readable pace). Hit Enter. Let the response render. Do not scroll past it.

**Props note**: `$AUTONOMATH_KEY` must be pre-set in the shell profile so the key never appears on screen. Verify with `echo $AUTONOMATH_KEY | wc -c` before recording to confirm it is loaded.

---

### Beat 3 — MCP in Claude Desktop (0:14–0:24) — 10 sec

**Visual**
Claude Desktop, full screen. The left sidebar shows the "autonomath" MCP server with a green connected indicator. The tool count shows "47 tools available" (visible in the MCP server detail panel; 31 core + 16 autonomath). Compose the following prompt in the chat input field — type it slowly enough that it can be read on screen:

> ⚠️ 動画の再録が必要: Claude Desktop UI 内の "31 tools" 表示を 47 tools に更新するには screencast を撮り直す必要があります。copy 更新だけでは UI と narration がズレます。

```
東京都の中小企業が使える IT 補助金を、
排他ルールも含めて教えて
```

Do not hit Enter yet. Hold for 1.5 seconds so the caption can be read, then hit Enter.

**Caption**
```
JP: Claude Desktop に MCP 接続・47 ツール
EN: Claude Desktop MCP · 47 tools
```
Character counts — JP: 22 chars (OK). EN: 30 chars (OK).

> ⚠️ 動画の再録が必要: burned-in caption の "31 ツール" / "31 tools" を 47 に書き換えるには、post 段階で caption を burn し直す (または再録する) 必要があります。copy 更新だけでは表示がズレます。

**Action**
Open Claude Desktop settings briefly to show the MCP server list (green dot next to "autonomath"). Return to chat. Type the prompt. Pause. Hit Enter.

---

### Beat 4 — Claude executes (0:24–0:42) — 18 sec

**Visual**
Claude Desktop response area. Claude's reasoning is visible in real time:
1. Claude calls `search_programs` — tool call indicator appears.
2. Claude calls `get_program` on the top result — second indicator.
3. Claude calls `check_exclusions` — third indicator.
4. The final prose response appears with 3 compatible programs, each with: name, max amount, `source_url`.

Speed up the tool-call phase to approximately 1.5× playback so it feels snappy without losing readability of the final response. Use iMovie speed ramp: tool calls at 1.5×, final response at 1×.

Hold on the final response for 3 seconds. Arrow annotations (added in post) pointing to:
- program name field
- yen amount
- source_url (`go.jp` domain visible)

**Caption**
```
JP: 排他ルールまで自動チェック済み
EN: Exclusion rules: auto-checked
```
Character counts — JP: 15 chars (OK). EN: 28 chars (OK).

**Action**
Let Claude run. Do not touch the mouse during tool-call phase. After the response fully renders, slowly scroll if the response exceeds one screen.

**Props note**: Run this live (not pre-recorded). If the live API call fails during recording, switch to a cached run logged in `~/.cache/autonomath-screencast-takes/` (keep a pre-run session saved there for safety).

---

### Beat 5 — Pricing (0:42–0:52) — 10 sec

**Visual**
Safari, `https://autonomath.ai` pricing section. The section shows:
- "¥3 / リクエスト (税込 ¥3.30)" as the primary figure
- "匿名 50 req/月 無料 (JST 月初リセット)" as the free path
- No plan tiers, no seat counts, no "Pro" badge.

Scroll at a steady pace — not too fast — so the pricing copy is readable. Stop scrolling for 2 seconds before transitioning.

**Caption**
```
JP: ¥3/req 従量・匿名50req/月は無料
EN: ¥3/req metered — 50 free/month anon
```
Character counts — JP: 20 chars (OK). EN: 32 chars (OK).

**Action**
Navigate to `autonomath.ai` in Safari (already open, pre-loaded). Scroll to pricing. Pause. No click needed.

---

### Beat 6 — CTA (0:52–0:58) — 6 sec

**Visual**
Split screen: iTerm2 left (900px), browser right (1020px showing `autonomath.ai` home, logo visible).

In iTerm2, type:
```
uvx autonomath-mcp
```

The MCP server starts clean — no error output. The startup line reads:
```
AutonoMath MCP server ready (47 tools: 31 core + 16 autonomath, protocol 2025-06-18)
```

> ⚠️ 動画の再録が必要: Beat 6 の terminal に映る `autonomath-mcp` 起動ログは server 側の実行時文字列なので、screencast を撮り直さないと古い "31 tools" 表示のまま残ります。

Hold for 2 seconds.

Then the landing page URL `autonomath.ai` is centred on screen for a final 1.5-second hold. No animation needed.

**Caption**
```
JP: uvx autonomath-mcp で今すぐ試せる
EN: uvx autonomath-mcp — try it now
```
Character counts — JP: 20 chars (OK). EN: 30 chars (OK).

**Action**
Type `uvx autonomath-mcp` at a readable pace. Watch it boot. Hold. No further interaction.

---

### Beat Summary Table

| Beat | Time | Duration | JP chars | EN chars | Over 35? |
|------|------|----------|----------|----------|----------|
| 1 Hook | 0:00–0:05 | 5 s | 17 | 35 | No |
| 2 REST | 0:05–0:14 | 9 s | 22 | 34 | No |
| 3 MCP | 0:14–0:24 | 10 s | 22 | 30 | No |
| 4 Execute | 0:24–0:42 | 18 s | 15 | 28 | No |
| 5 Pricing | 0:42–0:52 | 10 s | 22 | 35 | No |
| 6 CTA | 0:52–0:58 | 6 s | 26 | 31 | No |

**Total: 58 seconds. No caption exceeds 35 characters.**

---

## 3. Pre-Shoot Checklist

### macOS environment
- [ ] Create or switch to a **dedicated macOS user account** (`screencast` or `demo`) with no personal files, a plain dark-grey desktop background (no wallpaper photo), and zero saved passwords
- [ ] Set Pointer to Large Black (`Accessibility → Display → Pointer`)
- [ ] `System Settings → Notifications → Allow Notifications During Screen Recording`: OFF for all apps
- [ ] Menu bar: hide Wi-Fi signal (or use airplane mode + Ethernet), hide Spotlight, hide any third-party icon that could reveal personal info
- [ ] macOS clock: hide seconds to avoid timestamp leaking real date (launch date is 2026-05-06, not earlier)
- [ ] Do Not Disturb: ON for the entire recording session

### Apps to close
- [ ] All apps except iTerm2, Safari, Claude Desktop
- [ ] Quit Finder sidebar cloud sync indicators
- [ ] Close all browser tabs except the two needed (MAFF page + `autonomath.ai`)

### Terminal setup
- [ ] iTerm2 (or Warp) with **Menlo 18pt** or larger
- [ ] Dark theme: Tomorrow Night or Dracula (high contrast for mobile)
- [ ] `export AUTONOMATH_KEY=<your_key>` pre-loaded in `.zshrc` of the demo account — confirm with `echo $AUTONOMATH_KEY | wc -c` returning >1 before recording
- [ ] `jq` installed: `brew install jq`
- [ ] `uvx` installed (via `pip install uv`): `uvx --version`
- [ ] Test full curl + jq command end-to-end before recording; save the exact command in a scratch buffer to paste during recording

### Claude Desktop
- [ ] AutonoMath MCP server configured and connected (green dot)
- [ ] No other MCP servers connected (minimise visual noise)
- [ ] MCP tool list visible: confirm "47 tools available" appears before recording (31 core + 16 autonomath; requires v0.2.0 server with `AUTONOMATH_ENABLED=true`)

### API readiness
- [ ] Pre-run the Beat 4 query once and save the response to `~/.cache/autonomath-screencast-takes/beat4-cached.json` as a fallback
- [ ] Confirm live API response time < 2 seconds for Beat 2 query (run 3× to verify)

### Browser
- [ ] `autonomath.ai` pre-loaded in Safari, scroll position at hero top
- [ ] MAFF subsidy index page pre-loaded in a second tab (no login required)
- [ ] Zoom level 100%

### Practice
- [ ] Run through the full sequence **3× from cold** before the final take
- [ ] Time each practice run with a stopwatch; target 55–60 seconds total
- [ ] Rehearse Beat 4 without touching the mouse once Enter is pressed

---

## 4. Post-Production Checklist

### Editing (iMovie or DaVinci Resolve free)
- [ ] Cut all pauses > 0.5 seconds (be aggressive — aim for 58 s finished cut)
- [ ] Speed ramp Beat 4 tool-call phase to 1.5× (iMovie: hold clip → Speed → Custom 150%)
- [ ] Hold Beat 4 final response at 1× for minimum 3 seconds
- [ ] Add **arrow annotations** in Beat 4 pointing to: `primary_name`, `amount_max_man_yen`, `source_url`
- [ ] Add **rectangle highlight** around the `tier` value (S or A) in Beat 2 JSON output
- [ ] Burn in captions per spec (JP above, EN below, Hiragino Sans W6 42pt, white + 1px black stroke)
- [ ] Confirm no frame contains the string "jpintel" — search visually frame by frame at 1× speed through the terminal output
- [ ] Confirm no `source_url` in the JSON output resolves to an aggregator domain (noukaweb, hojyokin-portal, biz.stayway, etc.)

### Exports
- [ ] **H.264 MP4** — `autonomath-demo.mp4`, target < 50 MB for self-hosting. Export: 2560×1440, H.264 High, 8 Mbps, AAC silence track for compatibility.
- [ ] **ProRes/MOV** — `autonomath-demo.mov` for Product Hunt upload (PH accepts `.mov` up to 500 MB; use this master file).
- [ ] **10-second GIF** — extract Beat 2 + Beat 3 transition (curl → Claude MCP, approximately 0:05–0:15). Export at 640×360, 15 fps with `ffmpeg`:
  ```
  ffmpeg -ss 5 -t 10 -i autonomath-demo.mp4 \
    -vf "fps=15,scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
    -loop 0 autonomath-demo-preview.gif
  ```
- [ ] **Thumbnail frame** — capture the Beat 3 frame (Claude Desktop with green MCP dot + "47 tools available") as a 1280×720 PNG for Product Hunt gallery cover.

### Hosting
- [ ] Upload `autonomath-demo.mp4` and `autonomath-demo.mov` to `autonomath.ai/assets/` (Cloudflare Pages CDN, no YouTube dependency)
- [ ] Upload `autonomath-demo-preview.gif` alongside for HN linking
- [ ] Verify `Content-Type: video/mp4` header is returned for the MP4 (Cloudflare Pages serves this correctly by default)
- [ ] Test autoplay muted in a Chrome incognito window on mobile viewport (375px) before publishing

### Quality check before publish
- [ ] Watch full cut on an iPhone (small screen is the worst case for caption legibility)
- [ ] Confirm every `source_url` shown on screen is a live `go.jp` or `jfc.go.jp` URL
- [ ] Confirm no claim in captions implies existing user base (no "1000+ companies", no testimonials)
- [ ] Confirm pricing copy matches current live site exactly

---

## 5. Localization

### One video, two audiences
The silent-autoplay caption strategy means the same `.mov` file serves both the Product Hunt Japan audience (reading JP captions) and the HN international audience (reading EN captions). No separate cuts needed for v1.

### Tech terms — do not translate
The following terms appear identically in JP and EN captions and must not be Japanified or modified:
`curl`, `MCP`, `Claude Desktop`, `uvx`, `autonomath-mcp`, `JSON`, `tier`, `source_url`, `Bearer`, `jq`

### Caption typography contract
| Property | Value |
|----------|-------|
| JP line position | Upper of the two caption lines |
| EN line position | Lower of the two caption lines |
| Font (both) | Hiragino Sans W6 (macOS) or Noto Sans JP Bold (cross-platform) |
| Size (1080p) | 42 pt |
| Size (1440p) | 56 pt |
| Fill | #FFFFFF |
| Stroke | 1px #000000 |
| Background | None (stroke provides sufficient legibility) |
| Fade | 8 frames in / 8 frames out |
| Alignment | Centre-horizontal, 8% from bottom edge |
| Line spacing | 1.2× |

### Verification
After burning captions, screenshot Beat 2 and Beat 6 frames. Confirm the JP line is visually above the EN line in both. Confirm no character is clipped at the frame edge on a 375px-wide mobile crop.

---

## Props & Environment Checklist Summary

| Item | Required for |
|------|-------------|
| Dedicated macOS user account (`demo`) | All beats — no personal data exposure |
| Large Black cursor | All beats — mobile legibility |
| iTerm2 + Menlo 18pt + dark theme | Beats 2 and 6 |
| `$AUTONOMATH_KEY` in demo account `.zshrc` | Beat 2 |
| `jq` installed | Beat 2 |
| `uvx` installed | Beat 6 |
| Claude Desktop + autonomath MCP configured | Beats 3 and 4 |
| Safari with 2 tabs pre-loaded | Beats 1 and 5 |
| Beat 4 cached response as fallback | Beat 4 |
| Notifications OFF + Do Not Disturb ON | All beats |
| Stopwatch app for practice runs | Pre-shoot |
| ffmpeg installed | Post-production GIF export |
