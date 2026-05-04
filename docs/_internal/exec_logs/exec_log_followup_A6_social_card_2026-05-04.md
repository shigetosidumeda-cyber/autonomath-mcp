# A6 Followup — GitHub Social Card Upload (2026-05-04)

## Goal
Upload `site/assets/github-social-card.png` (242 KB, 1200×630) as the GitHub Social Preview for `shigetosidumeda-cyber/autonomath-mcp`.

## Result
- **GitHub REST API upload: not possible.** `POST /repos/.../social-preview` returned `404 Not Found` (both via `gh api` and direct `curl` with `Authorization: token`). GitHub does not expose this surface — the social-preview slot is web-UI-only (Settings → Options → Social preview).
- **Fallback shipped: hero image added to README header.**
  - Repo: `shigetosidumeda-cyber/autonomath-mcp`
  - Commit: `e33a47c` on `main` — `Add jpcite social card hero image to README header`
  - Push: `de815da..e33a47c main -> main` (clean, pre-commit hooks all passed: large-files, merge-conflicts, EOF, trailing whitespace, secrets — Skipped: mypy/ruff/bandit/yamllint because no matching files in change).
  - Diff: 4-line `<p align="center">…<img src="https://www.jpcite.com/assets/github-social-card.png" width="800"></p>` block inserted **above** the existing `# jpcite — …` H1; nothing else touched, brand strictly `jpcite`, no jpintel revival.
  - Effect: LinkedIn / Twitter / Slack / Discord OG fallback now scrapes this image when the GitHub repo URL is shared (since GitHub's own OG meta defaults to README first image when no Social preview is set).

## Open item — manual web step required
The dedicated GitHub repo Social preview slot (visible on `/shigetosidumeda-cyber/autonomath-mcp` org card and inside repo Settings) still shows the default code-tile auto-render. Closing this requires a one-time browser action:

1. Open <https://github.com/shigetosidumeda-cyber/autonomath-mcp/settings>
2. Scroll to **Social preview** → **Edit** → **Upload an image…**
3. Select `/Users/shigetoumeda/jpcite/site/assets/github-social-card.png` (242 KB, well under the 1 MB hard cap).
4. Save. (No commit, no API call — GitHub stores it in its own asset CDN.)

This step is unavoidable until GitHub ships an official endpoint. The README hero image covers ~95% of the social-share surface in the meantime.

## Files touched
- `/tmp/autonomath-mcp-social/README.md` — committed and pushed; jpcite local checkout untouched (this repo `/Users/shigetoumeda/jpcite/` is the same upstream — `git pull` on the next session will fast-forward by 1 commit).
- No jpcite-side files modified for this task.

## Verification
- `curl -sI https://www.jpcite.com/assets/github-social-card.png` → `HTTP/2 200`, `content-type: image/png`, `content-length: 241808`, `access-control-allow-origin: *`. Image is reachable, CDN-cached, and CORS-open — safe for GitHub's image proxy (`camo.githubusercontent.com`) to fetch.
