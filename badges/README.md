# Local SVG badges

Offline copies of the README badges. Useful when:

- shields.io is unreachable (CI offline, air-gapped review).
- A vendor's GitHub mirror needs a self-contained copy.
- Documentation is rendered statically without network access.

| File | Subject | Notes |
| --- | --- | --- |
| `pypi-version.svg`   | PyPI version (v0.3.0)  | Update on release. |
| `pypi-downloads.svg` | PyPI downloads / month | Static placeholder; live version uses shields.io. |
| `license-mit.svg`    | License: MIT           | Repo is MIT-licensed. |
| `mcp-version.svg`    | MCP protocol 2025-06-18 | Update when upgrading the MCP protocol target. |
| `api-status.svg`     | API status placeholder  | Live page lives at `https://zeimu-kaikei.ai/status`. |

The live README links shields.io URLs first; the local copies here are
linked as backup. To regenerate after a version bump, edit the SVG
`<text>` elements directly — the badges follow the standard shields.io
flat layout (height 20, rounded corners, two-tone).
