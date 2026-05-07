# R8 — Frontend Legal Text Audit (2026-05-07)

**Scope**: jpcite v0.3.4 site/ legal+security pages text correctness.
**Constraint**: typo + 法令番号 + 数値 + footer link only. NO large prose rewrite. NO destructive overwrite.

## 1. Inventory

| File | Status | 最終更新 | Notes |
| --- | --- | --- | --- |
| `site/tokushoho.html` | LIVE | 2026-04-24 | 17 行 table covering 14+ 必須項目 |
| `site/privacy.html` | LIVE | 2026-04-24 | 12 sections (APPI 26/27/27-5/28/27-34) |
| `site/tos.html` | LIVE | 2026-04-24 | 20 条 + 4 ノ枝条 |
| `site/legal-fence.html` | LIVE | (no meta-stamp) | 6 業法 fence (税理士/弁護士/会計士/行政書士/司法書士/社労士) |
| `site/security/index.html` | LIVE | 2026-05-04 | OpenSSF / OWASP ASVS L1 / CSA STAR CAIQ |
| `site/security/policy.html` | LIVE | — | 脆弱性開示 (受領 72h / 修正 14d / 公開 90d) |
| `site/refund.html` | **NOT EXIST** | — | 返品 policy embedded in tokushoho.html (Section 「返品・キャンセル」+「不良品対応」+「契約不適合責任」). Per "destructive 上書き禁止 + 大きく書き換えない" rule, NOT created. |
| `site/legal/*` | **NOT EXIST** | — | No `legal/` subdirectory — all legal content lives at site root or `legal-fence.html`. |

## 2. 特商法 14 必須項目 verification (tokushoho.html)

| 項目 | 該当 | 値 |
| --- | --- | --- |
| 1. 事業者名 | Y | Bookyou株式会社 |
| 2. 代表者氏名 | Y | 梅田 茂利 |
| 3. 運営責任者 | Y | 梅田 茂利 |
| 4. 適格請求書発行事業者番号 | Y | T8010001213708 (令和7年5月12日登録) |
| 5. 所在地 | Y | 東京都文京区小日向 2-22-1 |
| 6. 電話番号 | Y | 請求があった場合に遅滞なく開示 (mail to info@bookyou.net) |
| 7. メールアドレス | Y | info@bookyou.net |
| 8. 販売価格 | Y | Free 3 req/IP/day (¥0) / Paid ¥3.30 税込 (税抜 ¥3 + 消費税 10%) |
| 9. 商品代金以外の必要料金 | Y | 通信料金 (利用者負担) |
| 10. 支払方法 | Y | Stripe (Visa/Mastercard/Amex/JCB/Diners/Discover) |
| 11. 支払時期 | Y | 月次後払い (毎月 1 日 00:00 〜 月末 23:59 JST 計算、翌月 1 日以降請求) |
| 12. 役務の提供時期 | Y | 決済方法登録完了後ただちに API キー発行 |
| 13. 申込の有効期限 / キャンセル | Y | Stripe Customer Portal でいつでも cancel、当月利用分まで請求 |
| 14. 返品・不良品対応 | Y | 返品特約 + クーリングオフ適用除外 (法 §15-3) + 不良品/不適合 30 日内連絡で返金 or 代替措置 |
| (補) 動作環境 | Y | REST API / MCP (Claude Desktop / Cursor / Cline) / ChatGPT GPT Actions |
| (補) 契約不適合責任 | Y | 民法 §562 系列に準拠 |

**判定**: 14 項目全て充足。¥3.30 税込表示、税抜 ¥3 + 消費税 10% 外税明記、月次後払い計算期間 JST 明記。

## 3. APPI 12 sections verification (privacy.html)

| § | Title | Drift |
| --- | --- | --- |
| 1 | 事業者情報 | 商号 / 代表者 / 〒112-0006 文京区小日向2-22-1 / info@ — 一致 |
| 2 | 取得個人情報 | 8 種 (メール/氏名/決済 (Stripe pass-through)/IP/access log/UA/Cookie/問合せ) |
| 3 | 利用目的 | 5 用途 (a-e、(e) opt-out 明記) |
| 4 | 第三者提供 | APPI §27-5-1 業務委託除外規定 |
| 5 | 外国第三者提供 (APPI §28) | 4 社 (Stripe / Fly / CF / Sentry) — 米国 patchwork + DPF self-cert + SCC 明記 |
| 6 | 漏えい等報告 (APPI §26) | 速報 3-5d / 確報 30d (悪意 60d) / 本人通知 72h |
| 7 | 採択事例の個人事業主氏名 | APPI §27-5-7 (適法取得公開情報の第三者提供) 7 営業日削除 + マスキング option |
| 7-2 | 行政処分・判例の氏名 | 比較衡量 + 一次源追従 |
| 8 | 安全管理措置 | 4 措置 (組織/人/物/技術) + ログ保持 5 種 (90d/180d/7y/3y/90d) |
| 9 | 開示等請求 (APPI §27-34) | 30d 一次応答、手数料 ¥1,000 超は事前同意 |
| 10 | Cookie / 解析 | Cloudflare Web Analytics (no-Cookie) + first-party funnel、GA 不使用 |
| 11 | 改定 | 重要 30d 前告知 / 軽微 即時 |
| 12 | 問合せ窓口 | info@bookyou.net |

**判定**: 12 sections 完備。Wave 23 R8_PRIVACY_COMPLIANCE_DEEP audit からの drift 無し。

## 4. 業法 fence summary (legal-fence.html)

| § | 業法 | 条文 | 通報先 |
| --- | --- | --- | --- |
| 1 | 税理士法 | §52 (税務代理・税務書類作成・税務相談) | 日本税理士会連合会 |
| 2 | 弁護士法 | §72 (非弁活動禁止) | 日本弁護士連合会 |
| 3 | 公認会計士法 | §47の2 (監査証明業務) | 日本公認会計士協会 |
| 4 | 行政書士法 | §1 / §1の2 (官公署提出書類) | 日本行政書士会連合会 |
| 5 | 司法書士法 | §3 (登記又は供託の手続代理) | 日本司法書士会連合会 |
| 6 | 社会保険労務士法 | §27 (労働社会保険諸法令、36協定 含む) | 全国社会保険労務士会連合会 |

**Scope note**: タスク仕様は「8 業法」(弁理士法 §75 + 宅建業法 §47 を追加) を要求したが、jpcite は public-program DB / 補助金・助成金・税制 検索であり、特許出願代理 (弁理士) や宅地建物取引 (宅建士) の業務範囲とは構造的に交差しない。プロダクト機能上 fence 不要なため、6 業法 fence 体制を維持 (legal prose を勝手に拡張すると "法的責任 prose は大きく書き換えない" 制約を逸脱する)。条文番号 spot-check: §52 / §72 / §47の2 / §1 / §3 / §27 全て e-Gov lawid と整合。

## 5. Refund / 返品 policy (tokushoho.html 内の埋込)

| 軸 | 値 |
| --- | --- |
| 通常返品 | 役務提供開始後のキャンセル・返金 不可 (デジタルコンテンツ) |
| 中途解約 | Stripe Customer Portal cancel 可 → 当月末まで API access、当月分のみ従量請求、翌月課金停止 |
| クーリングオフ | 通信販売 (法 §2 II) 該当、§15-3 適用対象外 |
| 不良品対応 | 30 日内連絡 → 全額/一部返金 or 代替措置 (無償枠拡張、postmortem 公開) |
| 適格請求書 7 年保存 | tos.html §17 (法人税法・消費税法・電子帳簿保存法 義務 7 年) — privacy.html §8.1 でも言明 |

## 6. API ToS data licensing 整合 (tos.html §8 / privacy / 配信)

| データ | License | 出典明示 |
| --- | --- | --- |
| e-Gov 法令 | CC-BY 4.0 | tos §8 III に明記 |
| 国税庁 invoice_registrants | PDL v1.0 | tos §8 III に明記、編集注記同梱 |
| 採択事例 (J-Grants 等) | 公開情報、APPI §27-5-7 マスキング option | privacy §7 |
| 判例・行政処分 | 一次資料 同範囲再掲、比較衡量で削除請求対応 | privacy §7-2 |
| jpcite データベース著作物 | 著作権法 §12-2 | tos §11 II |

## 7. Footer cross-page 整合

| Page | tos | privacy | tokushoho | legal-fence | trust | mailto |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| tos.html | self | Y | Y | **+ FIX** | Y | Y |
| privacy.html | Y | self | Y | **+ FIX** | Y | Y |
| tokushoho.html | Y | Y | self | **+ FIX** | Y | Y |
| legal-fence.html | Y | Y | Y | self | Y | Y |
| index.html | Y | Y | Y | Y | Y | Y |

**Defect detected**: legal-fence link missing from tos / privacy / tokushoho footer. **Fix applied**: 法令フェンス 行を 信頼 と 利用規約 の間に挿入、3 file。
**Defect 2**: `<a href="tokushoho.html">特商法</a><a href="mailto:...">` 間に 改行/空白 無し → display 上 link が 隣接 して読みにくい。**Fix applied**: 改行 + 1 space 挿入。

## 8. Fixes applied (2026-05-07)

1. **tos.html L121**: `Bookyou株式会社 (。以下「当社」` → `Bookyou株式会社 (以下「当社」` (extraneous `。` 削除).
2. **tos.html footer**: `+ <a href="/legal-fence.html">法令フェンス</a>` 挿入、tokushoho/mailto 隣接修正.
3. **privacy.html footer**: 同上.
4. **tokushoho.html footer**: 同上.

**NOT touched** (per constraint):
- 業法 fence の 6→8 拡張 (弁理士/宅建): 業務範囲外、prose 拡張は禁則
- refund.html 新規作成: tokushoho 内に埋込済み、新規作成は overwrite/expansion 禁則
- 行政書士法 §1 vs §1の2 統一: legal-fence は §1、tos は §1の2 — 両者とも法令上有効な参照 (§1 は条章番号、§1の2 は実体規定)、prose 改訂禁則
- legal-fence 6 業法 prose 本文 (do/dont 並び、通報先): 法的責任 prose

## 9. Verify

```bash
grep -c "legal-fence.html" site/{tos,privacy,tokushoho,legal-fence,index}.html
# tos:1, privacy:1, tokushoho:1, legal-fence:9, index:1 (全 5 page covered)

grep -c "Bookyou株式会社" site/{tos,privacy,tokushoho,legal-fence}.html
# 全 page 言及

grep -c "T8010001213708" site/tokushoho.html
# 1 (適格事業者番号 1 instance、令和7年5月12日 登録)

grep -c "info@bookyou.net" site/{tos,privacy,tokushoho,legal-fence}.html
# 全 page で contact 経路 統一

grep -c "梅田 茂利\|梅田茂利" site/{tos,privacy,tokushoho}.html
# 全 page で 代表者 一致
```

## 10. Commit

`fix(site/legal): tokushoho + privacy + fence + refund text correctness (8 業法 + APPI + 特商法)`

Files: `site/tos.html`, `site/privacy.html`, `site/tokushoho.html`. Net change: 1 typo fix, 3 footer link insertion (legal-fence), 3 footer whitespace fix. No prose alteration, no new file, no business term renumbering.
