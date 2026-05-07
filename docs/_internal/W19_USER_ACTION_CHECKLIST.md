# W19 ユーザー action チェックリスト

最終更新: 2026-05-05 (Wave 19 進行中)

このファイルは **AI が代行不可能な作業** だけをまとめた最小チェックリスト。
これ以外の全ては AI が並列で進めている。

---

## ✅ 完了済 (AI 側)

- [x] W19-1 弁護士相談 outline → `docs/_internal/W19_lawyer_consult_outline.md` (5,132 字、17 disclaimer verbatim 入り)
- [x] W19-9 self-managed secret 生成 → `~/.jpcite_secrets_self.env` (API_KEY_SALT + AUDIT_SEAL_KEY)
- [x] W19-10 Python dist build → `dist/autonomath_mcp-0.3.3-py3-none-any.whl` + `.tar.gz` (twine check pass、`docs/_internal/W19_PYPI_PUBLISH_READY.md` に publish 1-line cmd)

## ⏳ 進行中 (AI 側、background agent)

- [ ] W19-2 Browser extension (Chrome MV3) → `sdk/browser-extension/`
- [ ] W19-3 VS Code extension → `sdk/vscode-extension/`
- [ ] W19-4 Reference agent npm `@jpcite/agents` → `sdk/agents/`
- [ ] W19-5 Static landing page 47×22 = 1,034 page → `site/audiences/{pref}/{ind}/index.html`
- [ ] W19-8 Merkle hash chain audit → `scripts/cron/merkle_anchor_daily.py` + `/v1/audit/proof/{epid}` endpoint
- [ ] W19-11 GitHub rename script + diff → `docs/_internal/W19_github_rename_*.md`
- [ ] W19-12 freee/MF marketplace 申請書 → `docs/_internal/marketplace_application/`
- [ ] W19-13 corpus pre-embedding pipeline → `tools/offline/embed_corpus_local.py`
- [ ] W19-14 Cloudflare 301 自動化 → `scripts/ops/cloudflare_redirect.sh`

## 🔒 ゲート待ち (ユーザー yes/no 待ち)

- [ ] W19-6 Stripe Credit prepay 仕組み (yes 来たら即実装)
- [ ] W19-7 bulk endpoint `/v1/evidence/packets/batch` (yes 来たら即実装)

---

## ⚠️ ユーザーにしかできない 4 件

### Action 1: `~/.jpcite_secrets.env` を作る (5 分)

下記コマンドを実行 → 12 値を REPLACE_ME から書き換え:

```bash
cat > ~/.jpcite_secrets.env << 'EOF'
# Stripe (https://dashboard.stripe.com → Developers → API keys)
STRIPE_SECRET_KEY=sk_live_REPLACE_ME
STRIPE_WEBHOOK_SECRET=whsec_REPLACE_ME

# Sentry (https://sentry.io → Settings → Projects → jpcite → Client Keys)
SENTRY_DSN=https://REPLACE_ME@sentry.io/PROJECT_ID

# Telegram bot (@BotFather → /newbot) — env var name は TG_BOT_TOKEN (code/workflow も TG_*)
TG_BOT_TOKEN=REPLACE_ME

# Cloudflare R2 (https://dash.cloudflare.com → R2 → Manage API Tokens)
R2_ACCESS_KEY_ID=REPLACE_ME
R2_SECRET_ACCESS_KEY=REPLACE_ME
R2_BUCKET=jpcite-backup

# Cloudflare API (https://dash.cloudflare.com → My Profile → API Tokens)
# scope: Zone:DNS:Edit + Zone:Page Rules:Edit (zeimu-kaikei.ai zone のみ)
CLOUDFLARE_API_TOKEN=REPLACE_ME
CLOUDFLARE_ZONE_ID_ZEIMU_KAIKEI=REPLACE_ME

# PyPI (https://pypi.org → Account settings → API tokens)
PYPI_TOKEN=pypi-REPLACE_ME

# npm (https://www.npmjs.com → Tokens、または "npm login")
NPM_TOKEN=npm_REPLACE_ME
EOF
chmod 600 ~/.jpcite_secrets.env
```

→ AI に「secrets 入れた」と一言伝えるだけで、Fly deploy / PyPI publish / npm publish / Cloudflare 301 を全自動化。

### Action 2: 5 つの yes/no 戦略判断

| # | 判断 | yes/no |
|---|---|---|
| 1 | Stripe Credit prepay 仕組み (¥300K/¥1M/¥3M 一括前払 → ¥3/billable unit 引き落とし、tier 不要で稟議通る) | __ |
| 2 | bulk endpoint `/v1/evidence/packets/batch` (1 req で 100 lookup ¥300) | __ |
| 3 | Reference agent npm `@jpcite/agents` を本気で publish (W19-4 で既に skeleton 作成中) | __ |
| 4 | English MCP wedge を切り出して foreign investor 向けに ¥10/req 帯で展開 | __ |
| 5 | Public Benchmark Leaderboard (Japan Compliance Reasoning Benchmark v1) を出す | __ |

→ yes と返ったものから順次 stream 化。

### Action 3: 弁護士スポット相談 (1 回限り、¥30K-80K)

`docs/_internal/W19_lawyer_consult_outline.md` を弁護士に email で送るだけ。
質問は yes/no 1 個 (「17 sensitive tool の disclaimer は業法違反該当しないか?」)。
返信を待って、必要なら disclaimer 微調整 (これは AI 側でやる)。

弁護士の探し方の例 (参考):
- 知的財産 + 業法 (税理士法・弁護士法) の双方カバーする弁護士
- スタートアップ法務に明るい (例: STORIA法律事務所、AZX、TMI 等)
- email で "spot consultation, 1 yes/no question, ¥50K budget" として依頼

### Action 4: freee / MoneyForward marketplace 申請 (KYC 署名)

W19-12 完了後 `docs/_internal/marketplace_application/` 配下に申請書 markdown が出来る。
あなたは:
1. markdown を PDF に変換 (`pandoc` で 1 cmd: `pandoc input.md -o output.pdf`)
2. PDF に Bookyou株式会社 代表 梅田茂利 として電子署名
3. freee/MF それぞれの developer console から提出

(電子署名なしで提出できる場合は #2 skip)

---

## まとめ

**ユーザーが今やる action は 1 つだけ**:

→ **`~/.jpcite_secrets.env` を作って 12 値を埋める** (Action 1)

これが完了すれば、PyPI publish / npm publish / Fly deploy / Cloudflare 301 が全自動で進む。
他の 3 action (yes/no、弁護士、marketplace 申請) は task 完了後にまとめて。
