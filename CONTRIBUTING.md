# Contributing to jpcite

ありがとう。jpcite は Bookyou株式会社 (T8010001213708) が単独運営の API/MCP サービスです。

## ライセンス
MIT (LICENSE 参照)。Contribution は同 MIT で受領。

## 投稿経路
- Bug report: GitHub Issue (label: `bug`)
- Feature request: GitHub Discussion → Issue
- Pull Request: feature branch → PR → main merge (CI green required)

## PR check
- [ ] CI pre-deploy gate 全 pass (`ruff format` / `mypy --strict src/` / `pytest` / `lighthouse-ci` / `axe-a11y`)
- [ ] CHANGELOG.md `[Unreleased]` に 1 行追加
- [ ] commit message: feat / fix / docs / chore / test / refactor の prefix
- [ ] **LLM API import 禁止** (anthropic / openai / google.generativeai / claude_agent_sdk) — `src/`, `scripts/cron/`, `scripts/etl/`, `tests/` 配下では絶対。`tools/offline/` のみ可
- [ ] 業法 fence 7 業法 (税理士/弁護士/司法書士/行政書士/社労士/中小企業診断士/弁理士) を犯さない出力設計

## 質問
info@bookyou.net (24h SLA)
