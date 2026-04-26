# autonomath.com DNS Runbook (.ai vs .com 整合)

**Status**: deferred (post-launch T+0 〜 T+1w 推奨)
**Owner**: operator (credential 必須)
**Last verified**: 2026-04-25 by subagent I6

---

## 1. 現状診断 (2026-04-25 dig 実測)

### autonomath.ai (production, OWNED)
- A: 104.21.45.66, 172.67.210.190 (Cloudflare)
- NS: shane.ns.cloudflare.com / romina.ns.cloudflare.com
- HTTP: 200, server=cloudflare, TLS valid, CSP/HSTS 設定済
- 用途: production 本番 (Cloudflare Pages + Workers)

### autonomath.com (NOT OWNED — dan.com aftermarket 出品中)
- A: 76.223.54.146, 13.248.169.48
- NS: ns1.dan.com / ns2.dan.com
- Registrar: GoDaddy Online Services Cayman Islands Ltd. (Uniregistry)
- HTTP: 405 → redirect to `https://autonomath.com/lander` (dan.com 売却 lander)
- HTML body: `<script>window.onload=function(){window.location.href="/lander"}</script>`
- **重大**: NS が dan.com に向いている = この domain は **第三者が dan.com で sale 出品中**。我々は所有していない。

---

## 2. 選択肢 (operator 判断)

### Option A: `.com` を購入する
- **コスト**: dan.com aftermarket 価格 (typically USD $1k〜$50k for short brand names; check https://dan.com/buy-domain/autonomath.com for actual ask)
- **メリット**: typo trap 防止 (ユーザー `.com` 入力時に parking page でなく canonical へ 301 可能)、brand 防衛
- **デメリット**: 投機価格の可能性。`.ai` で十分 brand 確立済なら不要
- **判断軸**: launch 後の `.com` typo 流入率 (Cloudflare Analytics で referrer 監視) が weekly >10 なら検討

### Option B: `.com` を諦める (recommended for solo + zero-touch + organic only)
- **理由**: 投資ゼロ原則 (memory `feedback_organic_only_no_ads`)、$1k〜投機購入は organic 路線と矛盾
- **mitigation**:
  - すべての公開素材 (blog/docs/JSON-LD/email/Stripe/GitHub) で `https://autonomath.ai` 表記を厳守
  - `.com` typo は parking page を見せるが我々の責任外 (3rd party owns)
  - canonical link / OG / Schema.org `url` は既に `.ai` 統一済 (site/index.html L22, L38, L65, L84 確認済)

### Option C: 暫定 awareness (no purchase)
- 何もしない。launch 後も `.com` は dan.com 出品状態のまま。
- ユーザー教育を docs/blog で `autonomath.ai` のみに絞る (URL 表記の徹底)

---

## 3. Option A 選択時の operator 手順

> **前提**: dan.com の Buy Now or 交渉で `.com` を取得後の流れ。

### 3-1. dan.com で購入
1. https://dan.com/buy-domain/autonomath.com にアクセス
2. "Buy Now" or "Make Offer" 選択
3. Escrow 経由で送金 (typically 1-7 days settlement)
4. Bookyou株式会社 名義で受領 (T8010001213708, 文京区小日向2-22-1)

### 3-2. registrar 移管 (任意 — Cloudflare Registrar 推奨)
1. dan.com push delivery (買主 registrar へ直接 push) で受け取り
2. Cloudflare Registrar 利用なら現状の registrar から transfer-out → Cloudflare へ transfer-in
3. WHOIS privacy 有効化

### 3-3. Cloudflare に domain 追加
1. Cloudflare Dashboard → Add Site → `autonomath.com` (Free plan で OK)
2. NS 提示される (例: alice.ns.cloudflare.com / bob.ns.cloudflare.com)
3. registrar 側で NS を上記 2 本に変更
4. propagation 1〜24h で Cloudflare が `Active` になる

### 3-4. DNS records (Cloudflare 側)
```
Type   Name    Content                  Proxy
A      @       192.0.2.1 (placeholder)  Proxied (orange)
A      www     192.0.2.1 (placeholder)  Proxied (orange)
```
※ A 値は Cloudflare proxy がカバーするので何でも可 (RFC 5737 placeholder で十分)。CNAME flattening でも可。

### 3-5. 301 redirect rule (全 path → `.ai`)
**Cloudflare Dashboard → Rules → Redirect Rules → Create rule:**
- Name: `autonomath.com → autonomath.ai canonical 301`
- When incoming requests match: `(http.host eq "autonomath.com") or (http.host eq "www.autonomath.com")`
- Then:
  - Type: Dynamic
  - Expression: `concat("https://autonomath.ai", http.request.uri.path, http.request.uri.query)`
  - Status: 301
  - Preserve query string: ON

### 3-6. SSL/TLS
- Mode: **Full (strict)**
- Edge Certificate: Universal SSL (auto-issued, ~15min)
- Always Use HTTPS: ON
- HSTS: max-age=31536000 (autonomath.ai と同等)

### 3-7. 検証
```bash
curl -sLI https://autonomath.com/        # → 301 Location: https://autonomath.ai/
curl -sLI https://autonomath.com/pricing # → 301 Location: https://autonomath.ai/pricing
curl -sLI https://www.autonomath.com/    # → 301 Location: https://autonomath.ai/
```

---

## 4. 暫定対応 (Option A 選択かつ DNS 完了前 or Option B/C)

### dan.com 状態のまま:
- 何もできない (我々は owner でない)

### `.com` 取得直後 (NS 切替前) で GoDaddy/registrar admin 利用可能なら:
- registrar 標準の "Domain Forwarding" で `autonomath.com` → `https://autonomath.ai` 301 設定
- 数分で反映、SSL は registrar 提供 (品質低い場合あり)
- Cloudflare 移管完了後に解除

---

## 5. canonical & SEO 状態 (verified 2026-04-25)

site/index.html:
- L22: `<link rel="canonical" href="https://autonomath.ai/">` OK
- L23-25: hreflang ja/en/x-default 全て `.ai` OK
- L12: og:url = `.ai` OK
- L38, L65, L84, L91, L112-116, L137-169: JSON-LD url/logo/license/documentation/termsOfService 全て `.ai` OK
- L429: `data-api-base="https://api.autonomath.ai"` OK

→ **canonical 側は既に `.ai` 一本化完了**。`.com` 取得しても site 側変更不要、redirect rule のみで完結。

---

## 6. 推奨 launch action

**T+0 (launch day)**: 何もしない。Option B/C 継続。
**T+1w**: Cloudflare Analytics で `.com` typo referrer 数を観測 (Workers log or Pages analytics)
**T+1m**: typo 流入 weekly >10 なら Option A 検討、それ以下なら Option C 継続

**operator 判断必須項目**:
1. dan.com の現在 ask price 確認
2. 投資ゼロ原則と brand 防衛のトレードオフ
3. Bookyou株式会社 から escrow 送金可否

---

## 7. 触らない範囲 (本 runbook で確定)

- DNS 実変更なし (operator credential 必須)
- src/* 変更なし
- DB 変更なし
- site/_redirects 変更なし (Cloudflare Pages 側 `.ai` のみホスト、`.com` は別 zone なので無関係)

---

## 8. References

- dig logs: 本文 §1
- whois: `whois autonomath.com` (Registrar=GoDaddy Cayman / NS=dan.com)
- canonical verify: `grep -nE "canonical|autonomath\.(ai|com)" site/index.html`
- Cloudflare Redirect Rules docs: https://developers.cloudflare.com/rules/url-forwarding/single-redirects/
- dan.com aftermarket: https://dan.com/buy-domain/autonomath.com

---

## 9. P2.6.5 ドメイン側セキュリティ checklist (DNSSEC + HSTS preload)

API 側の HTTP セキュリティヘッダ (HSTS / CSP / X-Frame-Options /
X-Content-Type-Options / Referrer-Policy / Permissions-Policy) は
`src/jpintel_mcp/api/middleware/security_headers.py` の
`SecurityHeadersMiddleware` で全レスポンスに stamp 済 (P2.6.5 完了)。
**DNS 層** で残るのは下記 2 点 — どちらも Cloudflare ダッシュボードで
operator が 1 度操作すれば永続化、sustain 不要 (solo + zero-touch 原則):

### 9-1. DNSSEC 有効化 (`autonomath.ai`)

1. Cloudflare Dashboard → `autonomath.ai` zone → DNS → Settings
2. **DNSSEC** カードで `Enable DNSSEC` クリック
3. 表示される DS record を **registrar (現在の `.ai` registrar)** 側で
   登録 (Cloudflare は authoritative NS、registrar が parent zone へ
   chain-of-trust を設定する必要がある)
4. DS 登録後、`dig autonomath.ai DNSKEY +dnssec` と
   `dig autonomath.ai +dnssec` で `ad` flag が立つこと確認
5. https://dnssec-analyzer.verisignlabs.com/autonomath.ai で
   chain-of-trust が green になること確認 (propagation 数時間〜24h)

### 9-2. HSTS preload registry 登録

1. 上記 P2.6.5 middleware が既に `Strict-Transport-Security:
   max-age=31536000; includeSubDomains; preload` を返している
   → preload directive を含む = 申請可能状態
2. https://hstspreload.org/ で `autonomath.ai` を入力 → 自動で要件チェック
3. 要件: HTTPS redirect / max-age ≥ 31536000 / includeSubDomains /
   preload directive — 全て middleware で満たし済
4. `Submit autonomath.ai to the preload list` クリック
5. Chromium / Firefox / Safari の preload list に取り込まれるまで
   数週〜数ヶ月。取り込み後は HSTS をブラウザ初回訪問前から強制可能。
   **取り消しコストが高い** (delist 申請 + 数ヶ月 propagation) ので、
   `https://api.autonomath.ai` も含む全 subdomain が確実に HTTPS 専用
   であることを再確認してから申請すること。

### 9-3. 検証 (operator 操作後セルフチェック)

```bash
# DNSSEC chain-of-trust
dig autonomath.ai DNSKEY +dnssec +short
dig api.autonomath.ai +dnssec | grep -E "flags|ad"

# HSTS header (middleware が出している)
curl -sI https://api.autonomath.ai/meta | grep -i strict-transport-security
# → Strict-Transport-Security: max-age=31536000; includeSubDomains; preload

# preload registry status (申請後)
curl -s https://hstspreload.org/api/v2/status?domain=autonomath.ai
```

### 9-4. 触らない範囲 (本 checklist で確定)

- middleware 側コードはこれ以上触らない (HSTS preload directive 既在、
  CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy も全て
  P2.6.5 で投入済)
- DS record / preload 申請は operator credential 必須 — Claude は触れない
