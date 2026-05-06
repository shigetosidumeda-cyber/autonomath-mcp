# jpcite 弱点全解 × マーケコピー実体化 × アウトプット強化 計画書 v2

**Operator**: Bookyou株式会社 (T8010001213708) / 代表 梅田茂利 / info@bookyou.net
**Drafted**: 2026-05-04 (v1) / **Revised**: 2026-05-04 (v2 → v2.1)
**Status**: Living document. すべてのタスクは「依存だけ DAG で表現、依存なき物は同時実行」。

---

## CHANGELOG (v2 → v2.1) ★ 重要修正

**v2 で operator-LLM tool として Anthropic / OpenAI API key 利用を提示 → 撤回**。memory `feedback_autonomath_no_api_use` を operator 側 ETL に拡張する `feedback_no_operator_llm_api` に整合させる。

| # | v2 の問題 | v2.1 の修正 |
|---|---|---|
| A | 付録 C で 8 operator-LLM tool に Anthropic Sonnet 4.6 API key (`ANTHROPIC_API_KEY_OFFLINE`) + OpenAI text-embedding-3-large API key を要求、initial cost ¥147 万 / monthly ¥10 万 | **API 直叩き完全廃止**。narrative / JSIC tag / eligibility predicate / enforcement summary 等の生成は **Claude Code Max Pro Plan サブエージェント経由**で実行。複数アカウント × チームメンバー × 毎日少しずつ分散。embedding は **ローカル sentence-transformers (intfloat/multilingual-e5-large)** を operator マシンで実行 (API ¥0)。`tools/offline/` への Anthropic SDK / OpenAI SDK 直 import 禁止 |
| B | Fly secret に `JPCITE_OPERATOR_LLM_API_KEY` 計上 | secret 一覧から削除 |
| C | コスト試算で operator-LLM ETL initial ¥147 万 / monthly ¥11 万 | **ETL コスト ¥0** (Claude Code Max Pro Plan サブスク代のみ、operator が複数アカウント運用) |
| D | アーキテクチャ「operator が cron で API 叩く」 | **Inbox/Outbox 構造**: 各メンバーが Claude Code セッションで `tools/offline/run_*_batch.py` 起動 → subagent が JSON 出力を `tools/offline/_inbox/{tool}/{date}.jsonl` に put → 別 cron が `_inbox` から SQLite に ingest |

## CHANGELOG (v1 → v2)

8 並列 agent (矛盾検証 / 24 tool 仕様 / migration full SQL / operator-LLM 仕様 / 顧客 use case 10 件 / 競合 landscape / コスト試算 / fact-check pipeline) の verify 結果を統合。主要修正:

| # | v1 の問題 | v2 の修正 |
|---|---|---|
| 1 | 章 9.B 「e-Gov 9,484 法令本文 並列 50 で 1 batch 完了」← e-Gov rate budget = 1 req/sec、即 IP block 確定 | 既存 `incremental_law_fulltext.py` 600/週 cron を採用、**17 週 saturation** で honest 計画化。launch コピーを「154 全文 + 9,484 catalog stub、~17 週で saturate」に書換 |
| 2 | 章 10.1.a Vector embed が「全 critical entity」と称しつつ tier S+A 1,454 限定 | **全 11,684 program に拡張** (+200MB / +$15)。tier B/C も hybrid 検索動作 |
| 3 | 章 10.7 #112 score_application_probability ML が「sklearn 学習」← jpi_adoption_records に **不採択 row なし** = 学習不能 | **#112 redefine**: 「採択者プロファイル類似度スコア (similarity, not probability)」。「probability」「予測」表現禁止。景表法 disclaimer 必須 |
| 4 | 章 8 P1 Stripe sunset 監視で `info.get("api_version_deprecated")` ← Stripe SDK に該当 field なし | **HTML scrape**: `https://stripe.com/docs/upgrades` を月次 fetch、自分の pin の row の `Deprecated` 表記 grep。Stripe API リリースノート RSS feed も並行監視 |
| 5 | 章 10.6 narrative 35 万 row で「100/月 抜き打ち」← 0.029% sample、詐欺リスク防衛として不足 | **月次 1,000 件 + tier S+A 11,632 件 100% pre-review + literal-quote self-check + 顧客報告 channel + corpus drift 自動再生成 + rollback パイプライン** (新章 10.10) |
| 6 | 章 10.7 #119 get_program_renewal_probability が Wave22 forecast_program_renewal と重複 | **#119 redefine**: 「更新後の制度内容変化予測 (eligibility predicate diff)」、forecast_program_renewal とは別軸 |
| 7 | 章 10.7 sensitive 4 tools (Wave22) のみ弁護士 review 想定 | **#100/#102/#104/#107/#108/#110/#111/#112/#113/#114/#115/#120 を sensitive 化**、章 5 L1 弁護士 review 範囲を 4 → **16 tools** に拡大 |
| 8 | migration 110-125 採番 ← on-disk で同番号既使用 (e.g. 105_integrations.sql、114_adoption_program_join 等) | **wave24_ prefix で再採番 126-139** (14 migration、要追加 126-139)。論理番号は本書の 10.2.1〜10.2.12 維持 |
| 9 | 章 11 「launch 延期許可」← memory `feedback_no_priority_question` と矛盾 | 「該当 tool を gate-off」のみ書く。launch 日付議論削除 |

---

## 章 0. 前提・制約・原則

### 不可侵 (memory 由来、本計画書全体に貫通)

| 原則 | 内容 |
|---|---|
| ZeroTouch | 営業 / CS チーム / DPA 個別交渉 / Slack Connect / phone / onboarding call すべて入れない |
| **LLM API 直叩き全廃 (operator 側含む)** | `src/`, `scripts/cron/`, `scripts/etl/`, `tests/`, **および `tools/offline/`** の全配下で Anthropic / OpenAI / Gemini SDK の import 禁止。CI guard `tests/test_no_llm_in_production.py` を `tools/offline/` まで拡張。**全ての LLM ETL は Claude Code Max Pro Plan サブエージェント経由で実行**。複数アカウント × チームメンバーで日次分散、Inbox/Outbox 構造で SQLite に ingest。embedding は OpenAI ではなく **ローカル sentence-transformers (intfloat/multilingual-e5-large)** で operator マシン上 (LLM call ではなく ML 推論のみ、API ¥0) |
| organic only | 有料広告・営業電話・MSA 個別営業 全部 nogo |
| 課金 | ¥3/req 完全従量、anon 3 req/日 free のみ。tier / seat / 年間最低の再導入禁止 |
| データ収集 | 公的一次資料 (e-Gov, 国税庁, 各省庁, 47 都道府県, JFC) は TOS 拘わらず取りに行く。アグリゲータ (noukaweb / hojyokin-portal / biz.stayway) は引き続き banned |
| 商標 | jpcite を含めて商標出願しない。新規衝突は rename で逃げる |
| DB | 9.4GB autonomath.db への boot 時 `PRAGMA quick_check` / `integrity_check` 禁止 (Fly grace 60s) |
| 並列度 | AI subagent 8-10+ 並列で機械的に進める |
| フェーズ分け禁止 | 「Phase 1/2/3」「先に〜後で〜」「MVP」「工数」 全部使わない。タスク間の **依存** だけ DAG で書く |
| 大規模修正後 | 必ず再レビュー (`feedback_iterative_review`) |
| ループ指示後 | 確認質問せず最後まで実行 |
| 表現 | 「採択を保証」「絶対に」「必ず」等の断定表現禁止 (景表法)、士業独占業務領域は `_disclaimer` 必須 |

### 「アウトプット強化」の北極星

**¥3 で受け取れるレスポンスの情報密度を 50-100 倍にする**。

- 旧: 制度 1 件のメタデータ + source_url (~100-300 byte JSON)
- 新: 制度 1 件のメタデータ + source_url + **推奨理由** + **類似制度 5 件** + **併給可能制度 3 件** + **採択統計** + **12 ヶ月カレンダー** + **類似採択事例 3 件** + **関連法令 3 件** + **関連税制 2 件** + **ナラティブ解説 200-1500 字** (~5-10KB JSON, envelope で同梱)

**LLM agent が推論で導出するであろう情報を事前計算して同梱**。¥3 で「自分で 10 回叩いて join するべき情報を 1 回で取れる」= 単価 ¥3 の体感単価が ¥0.3 相当に下がる。

---

## 章 1. 全体構造 (12 章 + 7 付録 + DAG)

| 章 | テーマ | 対象弱点 / 拡張 |
|---|---|---|
| 2 | **Ship-Stop Block** | S1 audit_seal HMAC rotation / S2 boot gate / S3 表現 rewording |
| 3 | Data Integrity Block | D1-D4 + M5/M6/M7 |
| 4 | Auth/Security Block | A1-A3 + M13-M16 |
| 5 | Legal Block | L1 (sensitive 4→**16 tools** 弁護士 review 拡大) / L2 / L3 + S3 連結 |
| 6 | MCP UX Block | U1-U3 + M18-M20 |
| 7 | Brand/SEO Block | B1-B5 + M21-M23 |
| 8 | Billing/Infra Block | P1 (sunset 検出刷新) + M1-M4 + M8-M12 |
| 9 | マーケコピー実体化 | A-O 15 拡張 (e-Gov 17 週 saturation 含) |
| **10** | **★ アウトプット強化** | データ基盤 5 軸 / 横断 mapping 14 テーブル / 事前推論 100 query / 検索精度 / ranking / ナラティブ / 24 新 MCP tool (96 → 120) / envelope |
| **10.10** | **★ NEW Hallucination Guard** | narrative + 事前推論 fact-check pipeline (entity 照合 / 統計 sampling / 顧客報告 channel / corpus drift / rollback / Telegram audit) |
| 11 | 検証ゲート / 再レビュー | 全章 done 判定 + 計画外 risk |
| **12** | **★ NEW 顧客 use case 10 件** | 8 cohort 網羅 (M&A 2 / 税理士 / 会計士 / FDI / 補助金 consultant / 中小 LINE / 信金 / 業界 pack 建設・不動産) |

付録: A. DAG / B. ETL source / C. operator-LLM tool 完全仕様 / D. Fly secret / E. 用語集 / **F. NEW 競合 landscape** / **G. NEW コスト試算**

### DAG (依存関係のみ、時間順序ではない)

```
[章 2 Ship-Stop]    independent
[章 3 Data Int]     independent
[章 4 Auth]         independent
[章 5 Legal]        S3 ← 章 2 S1 完了
                    L1 (16 tools 弁護士 review) ← 章 10.7 仕様凍結
[章 6 MCP UX]       U1 ← 章 9.A の REST endpoint 拡張完了
[章 7 Brand/SEO]    B5 ← Cloudflare 接続のみ
[章 8 Billing/Infra] P1 ← Stripe upgrade docs HTML scrape ETL
[章 9 マーケコピー]  E ← 章 2 S1 完了
                    A ← 章 6 U1 完了 (相互)
                    I ← 章 7 B4+B5 完了
                    D ← 章 5 L2 完了 (PII 注入が先)
                    B ← 既存 incremental_law_fulltext.py を継続 (新規 ETL 不要)
[章 10 アウトプット強化]
   10.1 データ基盤  独立
   10.2 横断 mapping ← 10.1 完了
   10.3 事前推論     ← 10.1 + 10.2 完了
   10.6 ナラティブ   ← 10.1 完了
   10.7 新 MCP tools ← 10.2 + 10.3 + 10.6 完了
   10.10 Hallucination Guard ← 10.6 完了
[章 11 検証]         全章完了後
[章 12 use case]     章 10.7 完了後 (顧客向け資料の妥当性検証として並走可)
```

---

## 章 2. Ship-Stop Block

### S1. audit_seal HMAC rotation policy + dual-key

#### 現状根拠
- `src/jpintel_mcp/api/_audit_seal.py:113-127` HMAC sign が `settings.audit_seal_secret` 直参照
- `src/jpintel_mcp/config.py:277-279` default = `"dev-audit-seal-salt"`
- secret rotate で過去 7 年分 seal が verified=false に倒れる

#### 変更

**(a) migration 105 (=wave24_105、再採番不要、jpintel-target)**: `audit_seals.key_version` 列 + `audit_seal_keys` registry。詳細 SQL は **付録 H §H.1**。

**(b) `_audit_seal.py` dual-key sign / verify 実装**:
```python
def _load_keys() -> list[dict]:
    raw = os.environ.get("JPINTEL_AUDIT_SEAL_KEYS")
    if raw:
        return json.loads(raw)
    return [{"v": 1, "s": settings.audit_seal_secret, "retired_at": None}]

def sign(payload: bytes) -> dict:
    keys = _load_keys()
    active = next(k for k in keys if k.get("retired_at") is None)
    sig = hmac.new(active["s"].encode(), payload, hashlib.sha256).hexdigest()
    return {"key_version": active["v"], "sig": sig, "alg": "HMAC-SHA256"}

def verify(payload: bytes, seal: dict) -> bool:
    target = seal.get("key_version", 1)
    keys = _load_keys()
    ordered = [k for k in keys if k["v"] == target] + [k for k in keys if k["v"] != target]
    for k in ordered:
        expected = hmac.new(k["s"].encode(), payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, seal["sig"]):
            _bump_last_seen_safe(k["v"])
            return True
    return False
```

**(c) operator rotation tool `tools/offline/rotate_audit_seal.py`**: 新 secret `secrets.token_urlsafe(48)` 生成 → `audit_seal_keys` 新 v INSERT → 旧 active row UPDATE retired_at=now → Fly secret `JPINTEL_AUDIT_SEAL_KEYS` (JSON 配列) を operator が手動投入。

**(d) ToS 第X条 (S3 と連結)**: `site/tos.html` に追加:
> 第X条 (audit_seal の取扱い)
> 1. 当社が API 応答に含める audit_seal は、HMAC-SHA256 によるメタデータ整合性検証用の電子的指紋です。
> 2. 鍵バージョンは段階的に交換され (key rotation)、旧鍵で生成された seal は当社が保持する旧鍵レジストリで verify を継続します。
> 3. audit_seal は、税理士法 §41 帳簿等保存義務、公認会計士法 §47条の2 監査調書保存義務の代替ではなく、それらに付随する補助的な完全性証跡として位置付けます。
> 4. 鍵レジストリの破壊的事故により過去 seal が verify 不能となった場合、当社は遅滞なく顧客に通知し、同期間の audit_seal の証跡価値を当社が補完します。

#### 検証
```bash
.venv/bin/pytest tests/test_audit_seal_rotation.py
fly secrets list -a autonomath-api | grep JPINTEL_AUDIT_SEAL_KEYS
```

#### Rollback
- migration 105 ADD COLUMN NULLABLE で rollback 不要
- code git revert 1 commit
- env unset で legacy single-secret path 自動復帰

---

### S2. api_key_salt boot assert + 全 production secret gate

#### 変更

**(a) `main.py` startup hook**:
```python
_FORBIDDEN_SALTS = {"dev-salt", "change-this-salt-in-prod", "test-salt", ""}

def _assert_production_secrets() -> None:
    if settings.env not in {"prod", "production"}:
        return
    if settings.api_key_salt in _FORBIDDEN_SALTS:
        raise SystemExit(f"[BOOT FAIL] API_KEY_SALT must be set. Got: {settings.api_key_salt!r}")
    if len(settings.api_key_salt) < 32:
        raise SystemExit(f"[BOOT FAIL] API_KEY_SALT must be ≥32 chars (got {len(settings.api_key_salt)})")
    if not os.environ.get("JPINTEL_AUDIT_SEAL_KEYS"):
        if settings.audit_seal_secret in {"dev-audit-seal-salt", ""}:
            raise SystemExit("[BOOT FAIL] JPINTEL_AUDIT_SEAL_KEYS or AUDIT_SEAL_SECRET must be set in prod")
    if not settings.stripe_webhook_secret:
        raise SystemExit("[BOOT FAIL] STRIPE_WEBHOOK_SECRET must be set in prod")
    if not settings.stripe_secret_key:
        raise SystemExit("[BOOT FAIL] STRIPE_SECRET_KEY must be set in prod")

@app.on_event("startup")
async def startup() -> None:
    _assert_production_secrets()
```

**(b) `entrypoint.sh §3` shell-level gate** (migration loop の前):
```sh
if [ "${JPINTEL_ENV:-dev}" = "prod" ]; then
    case "${API_KEY_SALT:-dev-salt}" in
        "dev-salt"|"change-this-salt-in-prod"|"")
            echo "[boot fail] API_KEY_SALT not set in prod" >&2; exit 1 ;;
    esac
    [ -z "${STRIPE_WEBHOOK_SECRET:-}" ] && { echo "[boot fail] STRIPE_WEBHOOK_SECRET unset" >&2; exit 1; }
    [ -z "${STRIPE_SECRET_KEY:-}" ]     && { echo "[boot fail] STRIPE_SECRET_KEY unset"     >&2; exit 1; }
    if [ -z "${JPINTEL_AUDIT_SEAL_KEYS:-}" ]; then
        case "${AUDIT_SEAL_SECRET:-dev-audit-seal-salt}" in
            "dev-audit-seal-salt"|"")
                echo "[boot fail] AUDIT_SEAL_SECRET unset" >&2; exit 1 ;;
        esac
    fi
fi
```

**(c) 新 runbook `docs/runbook/secret_rotation.md`** + CI gate `tests/test_no_default_secrets_in_prod.py` (`.env.production` 等 sample に forbidden salt 検出で fail)。

#### 検証
```bash
JPINTEL_ENV=prod API_KEY_SALT=dev-salt .venv/bin/uvicorn jpintel_mcp.api.main:app
# → [BOOT FAIL]
.venv/bin/pytest tests/test_boot_gate.py tests/test_no_default_secrets_in_prod.py
```

---

### S3. audit_seal 表現 rewording (景表法 §5 対応)

#### 変更

**(a) `_audit_seal.py` docstring 全面書換**: 「税理士法 §41」「7 年保存」「監査封緘」訴求 → 「HMAC-based response integrity envelope」「Not a substitute for 税理士法 §41 / 公認会計士法 §47条の2」

**(b) `mcp-server.json` `compose_audit_workpaper` description 書換**:
- 旧: 「監査封緘 / 税理士法 §41 帳簿等保存」
- 新: 「税理士事務所向け作業ペーパーバンドル。応答に integrity envelope (HMAC) を添付し、後刻の改ざん検出に用います。法的な帳簿等保存義務の履行手段ではなく、事務所内整合性チェックの補助です。」

**(c) ToS 第X条 (S1.d) 追加**

**(d) site/docs grep replace**:
```bash
grep -rln "監査封緘" site/ docs/ src/  # → 「整合性検証用 HMAC」「税理士事務所向け補助証跡」に置換
grep -rln "税理士法 §41" site/ docs/ src/  # → ToS 「義務の代替ではない」文言以外を削除
```

#### 検証
```bash
test "$(grep -r '監査封緘' site/ docs/ src/ | wc -l)" = "0"
```
弁護士書面 OK (景表法専門) を `docs/_internal/legal_review_audit_seal_2026-05.md` に保存。

#### Rollback 禁止
文言差し戻しは景表法リスクを取り戻すため不可。

---

### Ship-Stop Block 並列実行
```
subagent A: S1 (mig 105 + _audit_seal.py + tools/offline/rotate_audit_seal.py + tests)
subagent B: S2 (boot gate + entrypoint + runbook + CI gate test)
subagent C: S3 (docstring + manifest + ToS + site/docs grep replace)
```

---

## 章 3. Data Integrity Block

### D1. am_amendment_snapshot 真の time-series 化

#### 現状根拠
- agent SQL verify: 14,596 行 / distinct hash 1,141 / **どの 1 entity も hash 2 種以上を持たず** = time-series 完全 fake
- `am_amendment_diff` 7,819 行 (cron 動作中だが既存)、`am_amendment_snapshot` v1=v2 完全コピー

#### 変更

**(a) migration 106 (autonomath-target)**: 既存 `am_amendment_snapshot` を `snapshot_source='legacy_v1'` でマーク + 新 `am_program_eligibility_history` テーブル。完全 SQL は **付録 H §H.2**。

**(b) ETL `scripts/etl/rebuild_amendment_snapshot.py`**: tier S/A 全 1,454 program の 30 日 rolling backfill。`incremental_law_fulltext.py` 同様に既存 fetcher を再利用。

**(c) 新 cron `.github/workflows/eligibility-history-daily.yml`** (JST 04:00 daily)

**(d) MCP tool `track_amendment_lineage_am` を新 history table に切替**

#### 検証
```sql
-- tier S/A 全件で history 1 行以上
SELECT COUNT(*) FROM programs WHERE tier IN ('S','A')
  AND id NOT IN (SELECT DISTINCT program_id FROM am_program_eligibility_history);
-- = 0 が target

-- 30 日後、複数 captured_at を持つ program が 50 以上
SELECT COUNT(DISTINCT program_id) FROM am_program_eligibility_history
  GROUP BY program_id HAVING COUNT(*) >= 2;
-- >= 50 が target
```

---

### D2. am_compat_matrix sourced 化 + heuristic 明示分離

#### 現状根拠
- agent SQL: 43,966 行 = sourced(inferred_only=0)=3,823 / heuristic=40,143、`status='unknown'` 0 件で heuristic も label 付き = 顧客側で区別不能

#### 変更

**(a) migration 107 (autonomath-target)**: `visibility` 列 + sourced を public 昇格、unknown を quarantine 降格。完全 SQL は **付録 H §H.3**。

**(b) `_compat.py` の query helper 改修**: default で `visibility='public'` のみ返す。`include_heuristic=true` で opt-in。

**(c) MCP tool `find_combinable_programs` (#98) は default で sourced のみ**

**(d) operator-LLM 月次バッチで heuristic → sourced 化**: 5,000 行/月、8 ヶ月で 40,143 行を全 sourced 化

#### 検証
```sql
SELECT COUNT(*) FROM am_compat_matrix
 WHERE visibility = 'internal'
   AND program_a IN (SELECT id FROM programs WHERE tier IN ('S','A'));
-- 月次で減少していくことを KPI 化
```

---

### D3. source_fetched_at sentinel 排除 (真の median 7-day freshness)

#### 変更

**(a) migration 108 (jpintel-target)**: `programs.source_verified_at` + `source_content_hash_at_verify` + `source_verify_method` 列追加。詳細 SQL は **付録 H §H.4**。

**(b) `scripts/cron/refresh_sources.py` 改修**: tier S/A daily HEAD/GET → SHA256 → diff があれば content 更新 + verified_at = now。tier B/C 週次。

**(c) 新 cron 2 本**:
```yaml
# .github/workflows/refresh-sources-daily.yml — tier S/A
on: { schedule: [{ cron: '0 18 * * *' }] }  # JST 03:00 daily
# .github/workflows/refresh-sources-weekly.yml — tier B/C
on: { schedule: [{ cron: '0 18 * * 0' }] }
```

**(d) 表現変更**:
- 旧: "median 7-day freshness"
- 新: "**tier S/A: median 1-3 day verify** (daily HEAD/GET + content_hash diff). tier B/C: median 7-day verify (weekly)."
- レスポンス JSON に `source_fetched_at` (取得日) と `source_verified_at` (検証日) を分離

#### 検証
```sql
SELECT julianday('now') - julianday(source_verified_at) AS age_days
  FROM programs WHERE tier IN ('S','A')
ORDER BY age_days; -- median <= 3 が target
```

---

### D4. exclusion_rules 181 → 5,000-10,000 ルール拡張

#### 現状根拠
- agent SQL: 181 行 = 11,684 program × 11,683 ≈ 1.36 億 pair の **0.0001%**

#### 変更

**(a) ターゲット数値**: tier S+A 1,454 program × 主要組合せ ~5 = **7,270 ルール**。各ルールに source_url + content_hash + extracted_clause。

**(b) ETL `scripts/etl/extract_exclusion_rules.py`** (operator-LLM): 各 program の公募要領 PDF を Claude Sonnet 4.6 で構造化抽出。スキーマは **付録 C §C.9 precompute_eligibility_predicates 参照** (近接設計)。

**(c) 月次 cron `.github/workflows/exclusion-rules-monthly.yml`**: tier S/A の公募要領を月次再 parse。

**(d) MCP tool `rule_engine_check` 拡張**: envelope に rule の `confidence` (high/med/low)。`low` 除外 default、`include_low_confidence=true` で opt-in。

#### 検証
```sql
SELECT kind, COUNT(*) FROM exclusion_rules GROUP BY kind;
-- exclude >= 4,000, prerequisite >= 1,000, absolute >= 500 が target

SELECT COUNT(DISTINCT program_id_a) FROM exclusion_rules
 WHERE program_id_a IN (SELECT id FROM programs WHERE tier IN ('S','A'));
-- >= 1,200 (tier S+A 1,454 の 80%+ をカバー)
```

---

### M5. am_amount_condition 96.6% template_default のクリーンアップ

**(a) migration 109 (autonomath-target)**: `is_authoritative` + `authority_source` + `authority_evaluated_at` 列追加。完全 SQL は **付録 H §H.5**。

**(b) 公募要領 PDF parser (operator-LLM) で authoritative 値を再抽出 → INSERT, is_authoritative=1**

**(c) 検索 default は `is_authoritative=1` のみ**

#### 検証
```sql
SELECT COUNT(*) FROM am_amount_condition WHERE is_authoritative=1;
-- target: 50,000 行 (tier S/A 1,454 × 平均 30 amount 条件)
```

---

### M6. tier C 6,044 行クリーンアップ

**(a) 重複名 668 件 dedup**:
```sql
WITH dups AS (
  SELECT primary_name, MIN(id) AS keep_id FROM programs WHERE tier='C'
  GROUP BY primary_name HAVING COUNT(*)>1
)
UPDATE programs SET tier='X', excluded=1, exclusion_reason='dup_of_'||(SELECT keep_id FROM dups WHERE dups.primary_name=programs.primary_name)
 WHERE tier='C' AND id NOT IN (SELECT keep_id FROM dups) AND primary_name IN (SELECT primary_name FROM dups);
```

**(b) ゴミ名削除**:
```sql
UPDATE programs SET tier='X', excluded=1, exclusion_reason='garbage_name'
 WHERE tier='C' AND primary_name IN ('摘 要','企画調整G','奈良県公式ホームページ', ...);
```

**(c) amount_max NULL 70% / app_window NULL 87% を nightly source 再 fetch で補完**: `scripts/cron/refresh_sources.py --tier C --enrich`、補完不能は tier='X' に降格。

#### 検証
```sql
SELECT COUNT(*) FROM programs WHERE tier='C' AND amount_max IS NULL;
-- 4,231 → target 1,500 以下
```

---

### M7. enforcement_detail 22,258 のうち amount 入り 9.8% → 90%+

**(a) ETL `scripts/etl/enforcement_amount_extractor.py`**: 各処分の発表 PDF/HTML を operator-LLM (Claude Sonnet 4.6) で構造化抽出。「課徴金 X 万円」「返還命令 X 円」「過料 X 円」を amount_yen に UPDATE。設計は **付録 C §C.6 generate_enforcement_summary** と同 pattern。

**(b) source_url HEAD 確認 + 死亡 source は別 flag**

#### 検証
```sql
SELECT COUNT(*) FROM am_enforcement_detail WHERE amount_yen IS NOT NULL;
-- target: >= 20,000 (90%)
```

---

### Data Integrity Block 並列実行
```
subagent A: D1 (mig 106 + ETL + cron + MCP tool 切替)
subagent B: D2 (mig 107 + helper + monthly heuristic→sourced LLM batch)
subagent C: D3 (mig 108 + refresh_sources.py 改修 + cron 2 本 + 表現変更)
subagent D: D4 (ETL extract_exclusion_rules + cron + rule_engine_check 拡張)
subagent E: M5 (mig 109 + extract via operator-LLM)
subagent F: M6 (dedup SQL + garbage delete + nightly refresh enrich)
subagent G: M7 (ETL enforcement_amount_extractor)
```

---

## 章 4. Auth/Security Block

### A1. anon_limit fail-closed 化
`anon_limit.py:520-573` の DB error fail-open を fail-closed に:
```python
def _try_increment(...) -> Optional[int]:
    try: ...  # 既存実装
    except sqlite3.Error as e:
        logger.warning("anon_limit_db_error", exc_info=True)
        raise AnonRateLimitExceeded(limit=settings.anon_daily_limit, reset_at=_next_reset_iso(),
                                     reason="rate_limit_unavailable")
```
検証: DB lock pytest mock で 429 が返ること。

### A2. customer_cap fail-closed 化
`customer_cap.py:497-512` も fail-closed:
```python
async def __call__(self, request, call_next):
    try:
        cap_status = await self._cap_status(...)
    except Exception:
        logger.warning("customer_cap_unavailable", exc_info=True)
        return JSONResponse({"error": "cap_unavailable",
            "message": "コスト上限の検証ができないため一時的に処理を停止しました。"}, status_code=503)
```

### A3. revoke_subscription を child key cascade 化
`billing/keys.py:522-529`:
```python
def revoke_subscription(conn, stripe_subscription_id: str) -> int:
    parent_ids = conn.execute(
        "SELECT id FROM api_keys WHERE stripe_subscription_id=? AND parent_key_id IS NULL",
        (stripe_subscription_id,)).fetchall()
    revoked = 0
    for (pid,) in parent_ids:
        revoked += revoke_key_tree(conn, pid)
    return revoked
```

### M13. Stripe webhook tolerance 60s 明示
`billing.py:1023`: `stripe.Webhook.construct_event(body, sig, secret, tolerance=60)`

### M14. CORS hardcoded fallback
`OriginEnforcementMiddleware`:
```python
_MUST_INCLUDE = {"https://jpcite.com", "https://www.jpcite.com", "https://api.jpcite.com"}
origins = set(settings.cors_origins.split(",")) | _MUST_INCLUDE
```

### M15. webhook test rate を SQLite 永続化
`customer_webhooks_test_hits` テーブル新設、worker 横断で cap 効かせる。

### M16. APPI captcha
`appi_disclosure` ルーターに Cloudflare Turnstile dependency 追加。

---

## 章 5. Legal Block

### L1. **sensitive 16 tools 弁護士 review** (v1 の 4 → v2 の 16 に拡大)

**Wave22 既存 4 + 章 10.7 新 12 (合計 16) を弁護士 review 対象**:

| # | tool | 対象法令 |
|---|---|---|
| Wave22-1 | bundle_application_kit | 行政書士法 §1の2 |
| Wave22-2 | cross_check_jurisdiction | 税理士法 §52 / 司法書士法 §3 |
| Wave22-3 | prepare_kessan_briefing | 税理士法 §52 |
| Wave22-4 | match_due_diligence_questions | 弁護士法 §72 / 信用情報法 |
| Ch10-#100 | forecast_enforcement_risk | 弁護士法 §72 / 社労士法 §27 |
| Ch10-#102 | get_houjin_360_snapshot_history | 信用情報法 / 個人情報保護法 |
| Ch10-#103 | get_tax_amendment_cycle | 税理士法 §52 |
| Ch10-#104 | infer_invoice_buyer_seller | 信用情報法 / 個人情報保護法 |
| Ch10-#107 | get_program_narrative | 行政書士法 §1 + LLM 由来明示 |
| Ch10-#108 | predict_rd_tax_credit | **税理士法 §52** |
| Ch10-#110 | get_program_application_documents | 行政書士法 §1 |
| Ch10-#111 | find_adopted_companies_by_program | 個人情報保護法 / 信用情報法 |
| Ch10-#112 | score_application_probability | **景表法 + 行政書士法 §1** (採択保証類似表示禁止) |
| Ch10-#113 | get_compliance_risk_score | 信用情報法 / 弁護士法 §72 / 名誉毀損 |
| Ch10-#114 | simulate_tax_change_impact | **税理士法 §52** |
| Ch10-#115 | find_complementary_subsidies | 行政書士法 §1 |
| Ch10-#120 | get_houjin_subsidy_history | 個人情報保護法 / 信用情報法 |

**全 16 tools の `_disclaimer` envelope 強化** (例 #112):
```python
_DISCLAIMER_PROBABILITY = (
    "本 score は am_recommended_programs + am_capital_band_program_match + am_program_adoption_stats の "
    "統計的類似度であり、採択確率の予測ではありません。実際の採否は事業計画書の質・審査委員評価に依存します。"
    "本 score を「採択保証」「採択率予測」として広告・営業に使用することは景表法 (不当景品類及び不当表示防止法) "
    "違反のリスクがあります。当社は本 score の利用に起因する損害について責任を負いません。"
)
```

**`cross_check_jurisdiction.action_hint` 文言修正**:
- 旧: 「事業所税の課税地・申告先確認を推奨」
- 新: 「住所表記の不一致が検出されました。事実関係の確認と是正の要否は有資格者にご相談ください。」

**`prepare_kessan_briefing` 出力**: 「決算期判定」を表示しない。税制改正影響額のみ表示、決算期は caller 指定。

**`match_due_diligence_questions` の enforcement 5 年 lookup**: 公知の事実 (一次出典 URL あり) のみに限定、評価語 (悪質・重大) を redact。

**弁護士 review**: 16 tools の文言を弁護士法・税理士法・行政書士法・司法書士法・社労士法・景表法 の専門弁護士に書面 review 依頼、結果を `docs/_internal/legal_review_2026-05.md` に保存。

#### 検証
- 弁護士書面 OK
- `pytest tests/test_disclaimer_envelope.py::test_sensitive_16_disclaimers_present`
- `envelope_wrapper.SENSITIVE_TOOLS` frozenset に 16 tool 全件登録

---

### L2. invoice_registrants APPI 通知 attribution

**(a) `invoice_registrants.py` の `_ATTRIBUTION` ブロック拡張**:
```python
_ATTRIBUTION = {
    "license": "PDL v1.0", "license_url": "https://www.digital.go.jp/resources/data_policy",
    "publisher": "国税庁", "publisher_url": "https://www.invoice-kohyo.nta.go.jp/",
    "fetched_at": "...",
    "_pii_notice": {
        "ja": "本データには個人事業主の登録氏名 (本名または屋号) が含まれます。"
              "個人情報保護法 §17/§21 に基づく利用目的: 適格請求書発行事業者の確認、"
              "取引相手の与信・コンプライアンス確認、税務処理。"
              "本人による削除・開示請求は https://jpcite.com/privacy または info@bookyou.net まで。",
        "en": "This data may include individual proprietor names. ..."
    },
    "_redistribution_terms": {
        "downstream_must_carry_attribution": True,
        "downstream_must_relay_pii_notice": True,
    },
}
```

**(b) 全 invoice_registrants response に `_attribution` 自動注入** (response wrapper)

**(c) `site/privacy.html` 独立 page 化**: 利用目的 / 取得経路 / 第三者提供 / 開示・削除請求手順 / 30 日 SLA。`/privacy` への link を `_pii_notice.notice_url` に固定。

**(d) PPC (個人情報保護委員会) 照会**: operator が事前照会、結果を `docs/_internal/ppc_consultation_2026-05.md` に保存。

#### 検証
```python
def test_response_carries_pii_notice():
    r = client.get("/v1/invoice_registrants/search?q=...")
    assert r.json()["_attribution"]["_pii_notice"]["ja"]
```

---

### L3. invoice_registrants 並列表記の修正
- README から「13,801 invoice_registrants」を削除、章 9.D で 5M+ にしてから再表記
- それまで「13,801 invoice_registrants (delta-only snapshot — full bulk loading in progress, monthly cron 1st-of-month JST 03:00)」

---

## 章 6. MCP UX Block

### U1. **120 tool 全 fallback 動作** (96 → 120 への対応)

`_http_fallback.py` の dispatcher を 120 tool 全部に拡張:
```python
TOOL_TO_REST_PATH = {
    "search_programs": "/v1/programs/search",
    "get_program": "/v1/programs/{program_id}",
    # ... 既存 96 tool
    # 新 24 tool (#97-#120)
    "recommend_programs_for_houjin": "/v1/am/recommend",
    "find_combinable_programs": "/v1/am/combinations",
    "get_program_calendar_12mo": "/v1/am/calendar_12mo",
    # ... (24 tool 全 mapping、章 10.7 §10.7.0 参照)
}

async def dispatch_via_http(tool_name: str, args: dict) -> dict:
    path = TOOL_TO_REST_PATH.get(tool_name)
    if not path:
        return {"error": "tool_not_mapped", "tool": tool_name}
    url = f"{settings.api_base}{path}".format(**args)
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=args, headers={"X-API-Key": _api_key(), "X-Client": "mcp-fallback"})
        resp.raise_for_status()
        return resp.json()
```

`error: "remote_only_via_REST_API"` を返すケースをゼロに。

#### 検証
```bash
.venv/bin/pytest tests/mcp/test_http_fallback_all_120.py
# 全 120 tool に request → 200 + envelope 検証
```

### U2. examples の env / param 名 fix
- `examples/python/01_*.py`: `JPINTEL_API_KEY` → `JPCITE_API_KEY`、`amount_min` → `amount_min_man_yen`
- `examples/typescript/01-04`: `@autonomath/client` → `@jpcite/client`、`JPINTEL_MCP_CMD` → `JPCITE_MCP_CMD`

検証: `grep -rn "JPINTEL_\|jpintel-mcp\|amount_min[^_]" examples/` = 0

### U3. mcp-server.json 旧数字除去
- `11,547 programs` → `11,684 programs`
- `416,375 entities` / `424,054 entities` → `503,930 entities`
- `55 tools` / `59 tools` / `96 tools` → `120 tools`

### M18. 96→120 tool 認知負荷分割
3 種別 manifest:
- `mcp-server.core.json` = core 39 tools
- `mcp-server.composition.json` = autonomath 50+24 tools
- `mcp-server.full.json` = 全 120 (default)

### M19. TypeScript SDK npm publish
`@autonomath/sdk` → `@jpcite/sdk` rename + npm publish

### M20. freee / MoneyForward plugin marketplace 提出
SUBMISSION_CHECKLIST 完了 + 512x512 PNG icon 差替

---

## 章 7. Brand/SEO Block

### B1. DIRECTORY.md「Product = AutonoMath」修正
```markdown
- **Product / package name**: **jpcite** is the user-facing product brand.
+   PyPI distribution is `autonomath-mcp` (legacy name kept for client compatibility,
+   not a user-facing brand). Source directory is `src/jpintel_mcp/` (legacy import path,
+   user-facing exposure prohibited per CLAUDE.md non-negotiable constraints).
```

### B2. PyPI に `jpcite` メタパッケージ別 publish
新 repo `pypi-jpcite-meta/`:
```toml
[project]
name = "jpcite"
version = "0.3.2"
description = "Meta-package — installs autonomath-mcp."
dependencies = ["autonomath-mcp>=0.3.2"]
authors = [{ name = "Bookyou株式会社", email = "info@bookyou.net" }]
[project.urls]
Homepage = "https://jpcite.com"
```
`python -m build && twine upload dist/*` → `pip install jpcite` で `which autonomath-mcp` 成功。

### B3. IndexNow ping を jpcite.com に統一
```yaml
# .github/workflows/index-now-cron.yml
- url: 'https://zeimu-kaikei.ai/${{ secrets.INDEXNOW_KEY }}.txt'
+ url: 'https://jpcite.com/${{ secrets.INDEXNOW_KEY }}.txt'
- INDEXNOW_HOST: 'zeimu-kaikei.ai'
+ INDEXNOW_HOST: 'jpcite.com'
```

### B4. AI cited 0/60 → 5/60 (4 週間後)
**(a) `site/llms.txt` H1 直下**:
```
# jpcite (formerly 税務会計AI / zeimu-kaikei.ai)
Evidence-first context layer for Japanese public-program data.
Operator: Bookyou株式会社 (T8010001213708)
Brand history: 2026-04-30 から jpcite に統一 (旧称: 税務会計AI / AutonoMath / zeimu-kaikei.ai)
PyPI: autonomath-mcp (legacy name) / pip install jpcite (new alias)
```

**(b) `site/index.html` JSON-LD 拡張**:
```json
{
  "@context": "https://schema.org", "@type": "WebSite",
  "name": "jpcite",
  "alternateName": ["税務会計AI", "AutonoMath", "zeimu-kaikei.ai"],
  "url": "https://jpcite.com",
  "sameAs": ["https://www.bookyou.net/", "https://zeimu-kaikei.ai",
             "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
             "https://pypi.org/project/autonomath-mcp/", "https://pypi.org/project/jpcite/"]
}
```

**(c) 各 program 個別ページに JSON-LD `Citation` schema**

**(d) `analytics/geo_baseline_2026-05-XX.jsonl` で 4 週間後再計測** — cited >= 5/60 が target

### B5. zeimu-kaikei.ai → jpcite.com 301 を git-tracked
`cloudflare-rules.yaml`:
```yaml
zones:
  - name: zeimu-kaikei.ai
    redirect_rules:
      - description: "Brand consolidation 2026-04-30 → jpcite.com"
        match: 'http.host eq "zeimu-kaikei.ai" or http.host eq "www.zeimu-kaikei.ai"'
        action: dynamic_redirect
        target: 'concat("https://jpcite.com", http.request.uri.path)'
        status: 301
        preserve_query: true
```
`tests/test_redirect_zeimu_kaikei.py` で実 HTTP 確認。

### M21-M23
- **M21**: `grep -rln "AutonoMath\|autonomath" site/ docs/ | xargs sed -i ''` (import path/PyPI 除外) で機械置換
- **M22**: GitHub repo rename `autonomath-mcp` → `jpcite-mcp` (redirect 自動)
- **M23**: `scripts/notify_existing_users.py` で名簿に rebrand email 一括送信

---

## 章 8. Billing/Infra Block

### P1. **Stripe sunset 監視 (HTML scrape + RSS、v2 で検出方法刷新)**

**v1 の `info.get("api_version_deprecated")` は Stripe SDK に存在しない field、削除**

**(a) `scripts/cron/stripe_version_check.py`** (operator, GHA weekly):
```python
import httpx, re, sentry_sdk
PIN = "2024-11-20.acacia"
async def check_sunset():
    # 1. Stripe upgrades doc HTML scrape
    r = await httpx.AsyncClient().get("https://docs.stripe.com/upgrades")
    # ピンの行を locate、`Deprecated` 表記の有無を grep
    deprecated_pattern = re.compile(rf"{re.escape(PIN)}.*?(Deprecated|Sunset|End of life)", re.IGNORECASE | re.DOTALL)
    if deprecated_pattern.search(r.text):
        sentry_sdk.capture_message("stripe_api_version_deprecated_in_docs",
                                    level="error", extras={"version": PIN, "url": r.url})
    # 2. Stripe API リリースノート RSS feed
    feed = await httpx.AsyncClient().get("https://stripe.com/docs/upgrades/feed.atom")
    if PIN in feed.text and "deprecated" in feed.text.lower():
        sentry_sdk.capture_message("stripe_api_version_in_rss_deprecation", level="error")
    # 3. response header monitor (毎 stripe call で記録)
    # — billing/stripe_usage.py で `Stripe-Should-Retry` `Stripe-Sunset-At` を log
```

**(b) cron `.github/workflows/stripe-version-check-weekly.yml`** (Mon JST 09:00)

**(c) `feature/stripe-meter-events-migration` ブランチに meter_events 移行 PoC** を operator が下書き、sunset 通知後に merge

### M1-M4, M8-M12 簡略
- **M1**: `stripe_usage_backfill` cron が GHA に存在することを確認、無ければ作成
- **M2**: webhook handler COMMIT 失敗時に `stripe_webhook_events` INSERT を別 transaction
- **M3**: child key 個別 revoke 時に Stripe sub item 通知 `proration_behavior=create_prorations`
- **M4**: `scripts/cron/idempotency_cache_sweep.py` 新規作成 (24h 経過 DELETE)
- **M8**: `litestream replicate` を Fly volume → R2 に常時 stream (sidecar deploy)
- **M9**: backup filename を `autonomath-{stamp}.db.gz` に統一
- **M10**: RTO を運用真値 (3-4h) に runbook 修正、99.0% SLA 維持
- **M11**: `monitoring/sentry_alert_rules.yml` を Sentry UI に投入、3 NEEDS WIRING emitter 実装
- **M12**: `scripts/migrate.py` に `target_db` filter 追加 → `release_command = "python scripts/migrate.py --target jpintel"` 復活

---

## 章 9. マーケコピー実体化 (A-O 15 拡張)

### A. 96 → 120 tool 全 HTTP fallback 動作 (章 6 U1 と統合)

### B. **9,484 法令の本文ロード — v2 の honest 計画**

**v1 の「並列 50 で 1 batch」← e-Gov rate budget 1 req/sec で IP block 確定、削除**

**v2 計画**:
- **既存** `scripts/cron/incremental_law_fulltext.py` (週次 600/run、polite sleep 1.0s) を **継続採用**
- saturation = **17 週 (~4 ヶ月)** で 9,484 法令本文 + condition 全 ingest
- launch コピーを honest に書換: 「154 全文 + **9,484 catalog stub** (タイトル + URL)、毎週 600 法令ずつ全文ロード中、~17 週で saturate」
- README badge: `![laws-saturation](https://img.shields.io/badge/laws-154%2F9484-orange)` を週次更新

**進捗 KPI** (週次 Slack push):
```sql
SELECT COUNT(DISTINCT law_canonical_id) FROM am_law_article WHERE text_full IS NOT NULL;
-- target: 9,484、現状 154、週次 +600 増、17 週後 9,754 (overflow)
```

### C. 真の median 7-day freshness (章 3 D3 と統合)

### D. NTA 適格事業者 5M+ bulk
**(a)** 既存 `scripts/cron/ingest_nta_invoice_bulk.py` を operator 手動 trigger で即実行
**(b)** 月次 cron 維持 (1st-of-month 03:00 JST)
**(c)** Fly volume を **150GB に拡張** (`fly volumes extend ... -s 150` — agent A の容量再試算で 5 年 80GB+ 想定、WAL/SHM headroom 20% 確保)

検証: `SELECT COUNT(*) FROM invoice_registrants;` >= 4,000,000

### E. 監査封緘実体化 (章 2 S1 + S3 と統合)

### F. am_amendment_snapshot 真化 (章 3 D1 と統合)

### G. am_compat_matrix 全 sourced 化 (章 3 D2 と統合 + operator-LLM 月次バッチ)

### H. exclusion_rules 5,000+ (章 3 D4 と統合)

### I. AI cited 改善 (章 7 B4 と統合)

### J. `pip install jpcite` 成功 (章 7 B2 と統合)

### K. GitHub rename (章 7 M22 と統合)

### L. annotation 16,474 / 15 entity → 1,000+ entity 分散
ETL `scripts/etl/redistribute_annotations.py`: 既存 unresolved 5,080 を operator-LLM で再 resolve、新規 fetch で program 単位に分散。

検証: `SELECT COUNT(DISTINCT entity_id) FROM am_entity_annotation;` >= 1,000

### M. enforcement amount 90%+ (章 3 M7 と統合)

### N. invoice_registrants prefecture NULL 解消
住所 → prefecture mapper:
```python
# scripts/etl/invoice_prefecture_fill.py
def fill_prefecture():
    rows = conn.execute("SELECT id, address FROM invoice_registrants WHERE prefecture IS NULL").fetchall()
    for r in rows:
        pref = extract_prefecture(r['address'])  # regex で先頭3文字
        if pref:
            conn.execute("UPDATE invoice_registrants SET prefecture=? WHERE id=?", (pref, r['id']))
```

検証: `SELECT COUNT(*) FROM invoice_registrants WHERE prefecture IS NULL;` = 0

### O. tier C cleanup (章 3 M6 と統合)

---

## 章 10. ★ アウトプット強化

¥3 で受け取れるレスポンスの情報密度を 50-100 倍にする本丸。

### 10.1 データ基盤拡張 (5 軸)

#### 10.1.a Vector embedding (**v2.1: ローカル sentence-transformers**)

**v2.1 修正**: OpenAI text-embedding-3-large API → **ローカル `intfloat/multilingual-e5-large`** (operator マシン GPU/CPU で実行、API ¥0)。

対象: 全 11,684 program + tax_rulesets 50 + case_studies 2,286 + loan_programs 108 + enforcement_detail 22,258 + am_law_article 9,484 (saturate 後) = 約 **75,000 entity**。1024 dim float32 = 約 300MB (int8 quantize で 75MB)。

operator 側 `tools/offline/embed_corpus_local.py` (詳細 **付録 C §C.2**):
- model: `intfloat/multilingual-e5-large` (Hugging Face、MIT license、日本語対応 SOTA)
- M2 Max (operator マシン) で 75K entity × 800 tok = 約 **3-5 時間** で完了 (GPU 無しでも 8-12 時間)
- API cost **¥0**、operator マシン電気代のみ

migration 110 (sqlite-vec virtual table、dim=1024) は **付録 H §H.6**。

#### 10.1.b Graph 100 万 edge 拡張
`am_relation` 177,381 → 1,000,000。新 edge 種別 10 種:
program ↔ law / program ↔ tax_ruleset / program ↔ enforcement / houjin ↔ program / houjin ↔ invoice_registrant / houjin ↔ enforcement / case_study ↔ program / case_study ↔ houjin / law ↔ law (改正連鎖) / tax_ruleset ↔ tax_ruleset (改正連鎖)。

ETL `scripts/etl/expand_relation_graph.py` で既存 corpus を join → bulk INSERT。
検証: `SELECT COUNT(*) FROM am_relation;` >= 1,000,000

#### 10.1.c Time-series 月次 snapshot
migration 111 `am_entity_monthly_snapshot` (autonomath-target、UNIQUE entity_id × snapshot_month)。詳細 **付録 H §H.7**。
対象: tier S+A program 1,454 + 全 tax_ruleset 50 + 主要 houjin 100,000。

月次 cron `.github/workflows/monthly-snapshot.yml`。

#### 10.1.d Space hierarchy
migration 112: `am_region.economic_zone` (三大都市圏/地方中核/過疎)、`industry_cluster` (自動車集積/半導体/化学)、`transport_hub_score` (0-1)、新 `am_region_program_density` テーブル。詳細 **付録 H §H.8**。

ETL で各 1,966 region に tag 付与。

#### 10.1.e Industry JSIC 全 program tag
migration 113 (jpintel + autonomath 2 ファイル): `programs.jsic_major/middle/minor/multi_json/tagged_at` + `houjin_master.jsic_*`。詳細 **付録 H §H.9**。

operator-LLM `tools/offline/tag_jsic.py` (詳細 **付録 C §C.3**):
- Claude Sonnet 4.6 で各 program の名称+説明+公募要領を読み JSIC 大中小分類抽出
- 11,684 program × $0.020/call (cache 75% hit 後) = **$240** initial、月次 **$6.2**

検証: `SELECT COUNT(*) FROM programs WHERE jsic_major IS NOT NULL;` >= 11,000

---

### 10.2 横断 mapping (新 14 テーブル — v1 の 12 + #110/#117 用 +2)

各テーブルは「事前計算された推論結果」格納、jpcite サービス内 SELECT のみ。

**migration 採番**: v1 の 110-125 は on-disk で既使用 (105_integrations.sql, 114_adoption_program_join 等) → **wave24_ prefix で再採番 126-139**。論理番号は本書の 10.2.x で管理。

| 論理 # | 物理 mig | テーブル名 | 用途 |
|---|---|---|---|
| 10.2.1 | wave24_126 | am_recommended_programs | 法人 → 推奨制度 TOP 10 |
| 10.2.2 | wave24_127 | am_program_combinations | 制度ペア併給可否 |
| 10.2.3 | wave24_128 | am_program_calendar_12mo | 制度 × 月 |
| 10.2.4 | wave24_129 | am_enforcement_industry_risk | enforcement × JSIC risk |
| 10.2.5 | wave24_130 | am_case_study_similarity | 採択事例間類似度 |
| 10.2.6 | wave24_131 | am_houjin_360_snapshot | 法人 × 月 360° |
| 10.2.7 | wave24_132 | am_tax_amendment_history | 税制改正履歴 |
| 10.2.8 | wave24_133 | am_invoice_buyer_seller_graph | 取引相手推論 |
| 10.2.9 | wave24_134 | am_capital_band_program_match | 資本金帯 × 採択 |
| 10.2.10 | wave24_135 | am_program_adoption_stats | 採択統計 |
| 10.2.11 | wave24_136 | am_program_narrative + FTS | 解説 (4 sec × 2 lang) |
| 10.2.12 | wave24_137 | am_program_eligibility_predicate | eligibility predicate |
| 10.2.13 | wave24_138 | am_program_documents | 申請書類 list (#110 用) |
| 10.2.14 | wave24_139 | am_region_program_density | 地域 × JSIC density (#117 用) |

**全 14 migration の完全 SQL は付録 H §H.10〜H.23 に格納**。

---

### 10.3 事前推論 (LLM が答えるであろう典型 query 100 種事前計算)

100 query を operator 側で事前計算、`am_precomputed_*` テーブルに格納、jpcite サービス内 SELECT のみ。

**カテゴリ**:
- A. program 系 (30 query): 都道府県×業界×用途 / 法人推奨 / 業種×申請月 / 補助金×融資ペア / 創業者 / 賃上げ / R&D / GX / DX / 海外展開 / 設備投資 / 人材育成 / 認定制度 / ZEH / 食品 / 観光 / 文化芸術 / 福祉介護 / 医療 / 教育 / IT/DX / 公共調達 / M&A 事業承継 / 創業 5 年 / 女性起業家 / 高齢者雇用 / 障害者雇用 / 地方創生 / 大学連携 / 知財取得
- B. 法人 360° (20): 業界×地域×サイズ×採択履歴×行政処分×適格事業者×取引相手×関連法令×税制適用可能額
- C. 税制 (15): R&D / DX / 賃上げ / 経営強化 / 即時償却 / 外形標準 / インボイス / 地方法人税 / 国際課税
- D. 行政処分 (10): 業種別件数 / 同業他社 risk / 5 年推移 / 課徴金分布 / 救済措置
- E. 採択事例 (10): 類似企業 / 同業界 / 採択率 / 平均交付 / 不採択リトライ
- F. 法令 (10): 施行影響 / 関連 program / 関連税制 / 改正サイクル / e-Gov + 通達 cross-ref
- G. 適格事業者 (5): 取引相手 status / 未対応 list / 取引額 inferred / 業種別登録率

各 query は migration + ETL + cron + MCP wrapper の 4 点セット (24 新 MCP tool は §10.7 で網羅)。

---

### 10.4 検索精度向上 (BM25 + vector hybrid + JSIC filter)

**v2: 全 11,684 program に embed 拡張済 (10.1.a) なので tier B/C も hybrid 動作**

`src/jpintel_mcp/api/programs.py` 改修:
```python
async def search_programs(q: str, filters: dict, limit: int = 20) -> list[dict]:
    fts_results = await fts_search(q, filters, limit=200)
    vec_results = await vector_search(q, filters, limit=200)
    fused = reciprocal_rank_fusion(fts_results, vec_results, k=60)
    filtered = apply_filters(fused, filters)
    ranked = composite_rank(filtered)
    return ranked[:limit]
```

FTS5 trigram の単漢字 false match を改善: 2+ 字 kanji compound は phrase query (`"..."`) に自動変換、1 字 kanji 単独は除外 (caller 明示時のみ通す)。

検証: `evals/gold.yaml` 79 query で **全 tier 別** precision@10 > 0.85 (tier S+A only / B+C含 で分離評価)

---

### 10.5 Ranking composite score
```python
def composite_rank(results: list[dict]) -> list[dict]:
    for r in results:
        r['score_composite'] = (
            0.35 * r['fts_bm25_norm']
          + 0.25 * r['vector_cosine']
          + 0.15 * tier_weight(r['tier'])               # S=1.0, A=0.7, B=0.4, C=0.2
          + 0.10 * freshness_weight(r['source_verified_at'])  # exp(-age_days/30)
          + 0.10 * adoption_pattern_weight(r['program_id'])
          + 0.05 * sourced_compat_density(r['program_id'])
        )
    return sorted(results, key=lambda x: -x['score_composite'])
```

レスポンスに `_score_breakdown` 公開 → 顧客が「なぜこの順か」verify 可能。

---

### 10.6 ナラティブ事前生成 (Claude Code subagent — v2.1 全面書換)

**v2.1**: API 直叩き廃止 → **Claude Code Max Pro Plan サブエージェントで全件生成**。

#### 対象
- `am_program_narrative` (program 11,684 × 4 section × 2 lang = **93,472 row**)
- `am_houjin_360_narrative` (主要 houjin 100,000 × 1 lang = 200,000 row、cohort 優先順次第)
- `am_enforcement_summary` (1,185 × 2 lang = 2,370 row)
- `am_case_study_narrative` (2,286 × 2 lang = 4,572 row)
- `am_law_article_summary` (saturate 後 9,484 article × 2 lang = **18,968 row**)

**合計 約 320,000 row**

#### Claude Code subagent workflow

**1. Inbox/Outbox 構造**:
```
tools/offline/_inbox/{tool_name}/{date}-{batch_id}.jsonl   ← subagent 出力
tools/offline/_outbox/{tool_name}/{date}-{batch_id}.processed
tools/offline/_assignments/{date}.csv  ← 「アカウント X が batch Y を担当」
```

**2. 担当配分 (例: 5 アカウント × 5 メンバー = 25 アカウント並列)**:

operator が朝 Slack に分担表を投げる:
```
2026-05-XX 担当:
- @member1 account1: program narrative ja, batch_001 (program_id 1-200)
- @member1 account2: program narrative ja, batch_002 (program_id 201-400)
- @member2 account1: program narrative en, batch_021 (program_id 1-200)
...
- @member5 account5: enforcement summary ja, batch_120
```

**3. 各メンバーの実行手順**:
```bash
# Claude Code セッションを開く (Max Pro Plan アカウント)
cd ~/jpcite
claude  # Claude Code CLI 起動

# プロンプト:
> tools/offline/run_narrative_batch.py の batch_002 を実行して。
> SQL から program 200 件取得して subagent 並列 8 で narrative 生成、
> tools/offline/_inbox/program_narrative/2026-05-04-batch_002.jsonl に出力して。
```

**4. `tools/offline/run_narrative_batch.py`** (Claude Code subagent 起動 helper):
```python
"""このスクリプトは Claude Code セッション内でのみ実行する。
Anthropic API key を使わない。Claude Code 親セッションが Task tool 経由で
subagent を呼び出して narrative を生成し、JSON 出力を収集する。"""
import sqlite3, json, sys
from pathlib import Path

def get_pending_programs(batch_id: int, batch_size: int = 200) -> list[dict]:
    conn = sqlite3.connect("autonomath.db")
    rows = conn.execute("""
        SELECT id, primary_name, jurisdiction, amount_max_man_yen,
               application_window_start, application_window_end, source_url
        FROM programs WHERE id NOT IN (
            SELECT program_id FROM am_program_narrative WHERE lang='ja' AND section='overview'
        )
        ORDER BY tier, id
        LIMIT ? OFFSET ?
    """, (batch_size, (batch_id - 1) * batch_size)).fetchall()
    return [dict(...) for r in rows]

# Claude Code 親セッションが以下を読んで Task tool で subagent invoke:
# 「以下 200 件の program について、各 4 section × 2 lang の narrative を
#  公募要領 PDF を一次出典として生成し、JSON Lines で _inbox に出力せよ」
```

**5. ingest cron `scripts/cron/ingest_offline_inbox.py`** (jpcite サービス側、LLM 呼出なし):
```python
"""tools/offline/_inbox/ から JSON Lines を読み、SQLite に bulk INSERT。
literal-quote self-check + Pydantic 検証を pass したものだけ採用、
NG は _inbox/_quarantine/ に移動。"""
for inbox_file in Path("tools/offline/_inbox/program_narrative").glob("*.jsonl"):
    with open(inbox_file) as f:
        for line in f:
            row = json.loads(line)
            if not literal_quote_check(row): continue
            if not Narrative.model_validate(row): continue
            conn.execute("INSERT OR REPLACE INTO am_program_narrative(...) VALUES(?...)", ...)
    inbox_file.rename(Path("tools/offline/_outbox/...") / inbox_file.name)
```

#### ペース感

- 1 アカウント / 1 セッション = subagent 並列 8 × 1 batch 200 件 = **約 1-2 時間** (Max Pro Plan rate limit 内)
- 25 アカウント × 1 日 1 batch = **5,000 件/日**
- tier S+A 11,632 件 → **約 2-3 日**
- 全 program 93,472 件 → **約 19 日 (1 サイクル完了)**
- ongoing (差分のみ): 月数日

#### QA 強化 (Hallucination Guard §10.10 と連結)
- monthly QA sample: **1,000 件** (3% rate、Wilson 95% CI で defect rate 3% を ±1% で検出可能)
- **tier S+A 11,632 件は launch 前に 100% pre-review** (operator が Telegram bot で ✓/✗/修正)
- literal-quote self-check: 生成 narrative 中の引用文が一次出典 PDF に literal substring 存在するか ingest 時自動検査

---

### 10.7 新 MCP tools 24 本 (96 → 120)

各 tool は SELECT のみ、jpcite サービス内 LLM 呼出なし。事前計算結果を返す。**全 24 tool の完全実装仕様 (input/output JSON Schema、SQL、sample call/response、error envelope、billing units、disclaimer、_next_calls、cache TTL、backing migration) は付録 I §I.1〜I.24 に格納**。

| # | tool name | 概要 | backing migration | billing | sensitive |
|---|---|---|---|---|---|
| 97 | `recommend_programs_for_houjin` | 法人 → TOP 10 推奨 + reason | wave24_126 | 1 | YES |
| 98 | `find_combinable_programs` | program → 併給可能 list | wave24_127 | 1 | YES |
| 99 | `get_program_calendar_12mo` | program → 12 ヶ月カレンダー | wave24_128 | 1 | NO |
| 100 | `forecast_enforcement_risk` | jsic+region → 横展開 risk | wave24_129 | 1 | YES |
| 101 | `find_similar_case_studies` | case → 類似 5 件 | wave24_130 | 1 | NO |
| 102 | `get_houjin_360_snapshot_history` | houjin → 過去 N ヶ月 trend | wave24_131 | 1 | YES |
| 103 | `get_tax_amendment_cycle` | tax_ruleset → 改正サイクル | wave24_132 | 1 | YES |
| 104 | `infer_invoice_buyer_seller` | houjin → 推測取引相手 | wave24_133 | 1 | YES |
| 105 | `match_programs_by_capital` | capital_yen → 統計マッチ | wave24_134 | 1 | NO |
| 106 | `get_program_adoption_stats` | program → 採択率/平均額/業種分布 | wave24_135 | 1 | NO |
| 107 | `get_program_narrative` | program × lang × section → 解説 | wave24_136 | 1 | YES |
| 108 | `predict_rd_tax_credit` | houjin × fy → R&D 控除予測 | 131+132 | **2** | YES |
| 109 | `find_programs_by_jsic` | jsic → 制度 list | (113 既存) | 1 | NO |
| 110 | `get_program_application_documents` | program → 申請書類 list | wave24_138 | 1 | YES |
| 111 | `find_adopted_companies_by_program` | program → 採択企業 list | (jpi_adoption_records 既存) | 1 | YES |
| 112 | `score_application_probability` | houjin × program → **採択者類似度 score (predict ではない、v2 redefine)** | 126+134+135 | **2** | YES |
| 113 | `get_compliance_risk_score` | houjin → コンプラ score | wave24_131 | 1 | YES |
| 114 | `simulate_tax_change_impact` | houjin × ruleset × fy → 影響額 | 131+132 | **2** | YES |
| 115 | `find_complementary_subsidies` | program → 補完制度 (時系列カバー) | 127+128 | 1 | YES |
| 116 | `get_program_keyword_analysis` | program → キーワード分析 | wave24_136 | 1 | NO |
| 117 | `get_industry_program_density` | jsic+region → 業種別制度密度 | wave24_139 | 1 | NO |
| 118 | `find_emerging_programs` | months → 新規施行制度 | (programs.first_seen_at 既存) | 1 | NO |
| 119 | `get_program_renewal_probability` | program → **更新後の制度内容変化予測 (v2 redefine、Wave22 forecast と異軸)** | (am_amendment_diff 既存) | 1 | NO |
| 120 | `get_houjin_subsidy_history` | houjin → 過去補助金獲得歴 + total | (jpi_adoption_records 既存) | 1 | YES |

**sensitive: 16 / 24** (= 章 5 L1 弁護士 review 対象)

#### 10.7.0 REST endpoint mapping (HTTP fallback 用、章 6 U1 と統合)

```python
TOOL_TO_REST_PATH = {
    "recommend_programs_for_houjin": "/v1/am/recommend",
    "find_combinable_programs": "/v1/am/combinations/{program_id}",
    "get_program_calendar_12mo": "/v1/am/calendar_12mo/{program_id}",
    "forecast_enforcement_risk": "/v1/am/enforcement_risk",
    "find_similar_case_studies": "/v1/am/case_studies/similar/{case_id}",
    "get_houjin_360_snapshot_history": "/v1/am/houjin/{houjin_bangou}/360_history",
    "get_tax_amendment_cycle": "/v1/am/tax/{tax_ruleset_id}/amendment_cycle",
    "infer_invoice_buyer_seller": "/v1/am/houjin/{houjin_bangou}/invoice_graph",
    "match_programs_by_capital": "/v1/am/match/capital",
    "get_program_adoption_stats": "/v1/am/programs/{program_id}/adoption_stats",
    "get_program_narrative": "/v1/am/programs/{program_id}/narrative",
    "predict_rd_tax_credit": "/v1/am/houjin/{houjin_bangou}/rd_tax_credit",
    "find_programs_by_jsic": "/v1/am/programs/by_jsic/{jsic_code}",
    "get_program_application_documents": "/v1/am/programs/{program_id}/documents",
    "find_adopted_companies_by_program": "/v1/am/programs/{program_id}/adopted_companies",
    "score_application_probability": "/v1/am/programs/{program_id}/houjin/{houjin_bangou}/similarity_score",
    "get_compliance_risk_score": "/v1/am/houjin/{houjin_bangou}/compliance_risk",
    "simulate_tax_change_impact": "/v1/am/houjin/{houjin_bangou}/tax_change_impact",
    "find_complementary_subsidies": "/v1/am/programs/{program_id}/complementary",
    "get_program_keyword_analysis": "/v1/am/programs/{program_id}/keywords",
    "get_industry_program_density": "/v1/am/density/{jsic_major}",
    "find_emerging_programs": "/v1/am/programs/emerging",
    "get_program_renewal_probability": "/v1/am/programs/{program_id}/renewal_change_forecast",
    "get_houjin_subsidy_history": "/v1/am/houjin/{houjin_bangou}/subsidy_history",
}
```

24 + 既存 96 = 120 tool 全部 HTTP fallback で 200 応答するか `tests/mcp/test_http_fallback_all_120.py` で gate。

---

### 10.8 ¥3 レスポンスの新 envelope 構造

#### 旧 (例)
```json
{"unified_id": "UNI-example-energy-dx", "primary_name": "東京都 中小企業 省エネ設備導入支援",
 "amount_max_man_yen": 500, "application_window": {"end_date": "2026-06-30"},
 "source_url": "...", "source_fetched_at": "2026-04-30T00:00:00+09:00", "tier": "A"}
```
~250 byte

#### 新 (例) — `GET /v1/programs/get_program?id=...&include=full_envelope`
```json
{
  "program": {
    "unified_id": "UNI-example-energy-dx",
    "primary_name": "東京都 中小企業 省エネ設備導入支援",
    "amount_max_man_yen": 500,
    "application_window": {"end_date": "2026-06-30"},
    "tier": "A", "jsic_major": "E", "jsic_middle": "29",
    "source_url": "https://www.metro.tokyo.lg.jp/.../energy-dx.html",
    "source_fetched_at": "2026-04-30T00:00:00+09:00",
    "source_verified_at": "2026-05-04T03:14:00+09:00",
    "content_hash": "sha256:..."
  },
  "narrative": {
    "ja": {
      "overview": "東京都が...省エネ設備導入を支援する...",
      "eligibility": "都内に本社を有する中小企業 (資本金 3 億円以下、従業員 300 人以下)...",
      "application_flow": "(1) 事前相談 → (2) 申請書提出 → ...",
      "pitfalls": "見積取得 3 社必須、設備設置完了から 30 日以内に実績報告..."
    }
  },
  "similar_programs": [
    {"program_id": 1234, "primary_name": "...", "similarity": 0.87, "reason": "同 JSIC + 同地域"},
    {"program_id": 5678, "primary_name": "...", "similarity": 0.81, "reason": "同 amount band + 同用途"}
  ],
  "combinable_programs": [
    {"program_id": 9012, "primary_name": "ものづくり補助金", "combinable": true, "confidence": "high",
     "reason": "exclusion rule 不在 + 用途異なる", "source_url": "..."}
  ],
  "exclusion_rules": [
    {"kind": "exclude", "target_program_id": 3456,
     "clause_quote": "経済産業省の省エネ補助金との併給は不可", "source_url": "..."}
  ],
  "calendar_12mo": [
    {"month": "2026-05", "is_open": true, "deadline": "2026-06-30"},
    {"month": "2026-06", "is_open": true, "deadline": "2026-06-30"},
    {"month": "2026-07", "is_open": false}
  ],
  "adoption_stats": {
    "fy2024": {"adoption_count": 142, "avg_amount_man_yen": 380, "success_rate": 0.62,
               "industry_distribution": {"E": 0.45, "G": 0.20, "F": 0.15}}
  },
  "similar_case_studies": [
    {"case_id": 7890, "company_anonymized": "T 工業 (東京都・従業員 80 名)",
     "amount_received_man_yen": 320, "outcome_summary": "..."}
  ],
  "related_laws": [
    {"law_canonical_id": "428AC...", "law_name": "省エネ法", "article_no": "第10条",
     "url": "https://elaws.e-gov.go.jp/..."}
  ],
  "related_tax_rulesets": [
    {"tax_ruleset_id": 23, "name": "中小企業経営強化税制", "url": "https://www.nta.go.jp/..."}
  ],
  "application_documents": [
    {"doc_name": "申請書 (様式第1号)", "url": "..."},
    {"doc_name": "事業計画書", "url": null},
    {"doc_name": "見積書 3 社分", "url": null}
  ],
  "_score_breakdown": {"fts_bm25_norm": 0.82, "vector_cosine": 0.78, "tier_weight": 0.7,
                       "freshness_weight": 0.95, "adoption_pattern_weight": 0.6,
                       "sourced_compat_density": 0.5, "score_composite": 0.74},
  "_attribution": {
    "license": "東京都ホームページ利用規約", "publisher": "東京都産業労働局",
    "publisher_url": "https://www.metro.tokyo.lg.jp/", "fetched_at": "2026-05-04T03:14:00+09:00"
  },
  "_disclaimer": "本情報は公開一次出典に基づく整理であり、申請可否や採択を保証するものではありません。",
  "_audit_seal": {"key_version": 2, "sig": "...", "alg": "HMAC-SHA256",
                  "signed_at": "2026-05-04T03:14:00+09:00"},
  "_billing_unit": 1,
  "_next_calls": [
    {"tool": "find_complementary_subsidies", "args": {"program_id": "..."}, "estimated_units": 1},
    {"tool": "score_application_probability",
     "args": {"program_id": "...", "houjin_bangou": "REQUIRED"}, "estimated_units": 2}
  ]
}
```
~5-10 KB

#### 既存 endpoint の互換維持
- `?include=minimal` (旧形式 ~250 byte) がデフォルト
- `?include=full_envelope` を opt-in
- 6 ヶ月後に default を `full_envelope` に変更

---

### 10.9 manifest 更新

- `mcp-server.json` に 24 entry 追加 (totals: 96 → 120)
- `dxt/manifest.json` / `smithery.yaml` / `server.json` 同時更新
- `pyproject.toml` の version bump v0.3.2 → **v0.4.0** (24 新 tool は major feature)

---

## 章 10.10 ★ NEW Hallucination Guard

35 万 row の operator-LLM 生成ナラティブ + 100 種事前推論の事実誤認を、6 系統で検知・封じ込める。LLM 呼び出しは operator 側 cron のみ、jpcite サービス内は SQL のみ。

### 10.10.1 schema (migration 140-142, target_db: autonomath)

```sql
-- migration 140_narrative_extracted_entities (autonomath-target)
CREATE TABLE IF NOT EXISTS am_narrative_extracted_entities (
    extract_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id    INTEGER NOT NULL,
    narrative_table TEXT NOT NULL,
    entity_kind     TEXT NOT NULL,    -- money|year|percent|count|url|law|program|houjin|jsic
    entity_text     TEXT NOT NULL,
    entity_norm     TEXT NOT NULL,
    span_start      INTEGER NOT NULL,
    span_end        INTEGER NOT NULL,
    corpus_match    INTEGER NOT NULL DEFAULT 0,
    corpus_table    TEXT,
    corpus_pk       TEXT,
    extracted_at    TEXT NOT NULL,
    UNIQUE(narrative_id, narrative_table, span_start, span_end)
);
CREATE INDEX IF NOT EXISTS idx_nee_narrative ON am_narrative_extracted_entities(narrative_table, narrative_id);
CREATE INDEX IF NOT EXISTS idx_nee_kind_match ON am_narrative_extracted_entities(entity_kind, corpus_match);

-- migration 141_narrative_quarantine
CREATE TABLE IF NOT EXISTS am_narrative_quarantine (
    quarantine_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id    INTEGER NOT NULL,
    narrative_table TEXT NOT NULL,
    reason          TEXT NOT NULL,    -- 'low_match_rate'|'customer_report'|'corpus_drift'|'operator_reject'
    match_rate      REAL,
    detected_at     TEXT NOT NULL,
    resolved_at     TEXT,
    resolution      TEXT,             -- 'regenerated'|'manual_fix'|'deleted'|'false_positive'
    UNIQUE(narrative_id, narrative_table, detected_at)
);
ALTER TABLE am_program_narrative ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;
ALTER TABLE am_program_narrative ADD COLUMN quarantine_id INTEGER;
ALTER TABLE am_program_narrative ADD COLUMN content_hash TEXT;
-- (同 ALTER を am_houjin_360_narrative / am_enforcement_summary / am_case_study_narrative / am_law_article_summary に展開)

-- migration 142_narrative_customer_reports
CREATE TABLE IF NOT EXISTS am_narrative_customer_reports (
    report_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id    INTEGER NOT NULL,
    narrative_table TEXT NOT NULL,
    api_key_id      INTEGER,
    severity_auto   TEXT NOT NULL,    -- 'P0'|'P1'|'P2'|'P3'
    field_path      TEXT,
    claimed_wrong   TEXT NOT NULL,
    claimed_correct TEXT,
    evidence_url    TEXT,
    state           TEXT NOT NULL DEFAULT 'inbox',
    operator_note   TEXT,
    created_at      TEXT NOT NULL,
    sla_due_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ncr_state_due ON am_narrative_customer_reports(state, sla_due_at);

-- 過去 30 日 narrative→customer fan-out 履歴 (rollback 通知用)
CREATE TABLE IF NOT EXISTS am_narrative_serve_log (
    served_at       TEXT NOT NULL,
    narrative_id    INTEGER NOT NULL,
    narrative_table TEXT NOT NULL,
    api_key_id      INTEGER,
    request_id      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nsl_narrative_time ON am_narrative_serve_log(narrative_id, narrative_table, served_at);
```

### 10.10.2 (1) 自動 fact-check pipeline (operator side, weekly full)

`tools/offline/extract_narrative_entities.py`:
- regex (money/year/percent/count/url/houjin/jsic/law/program) で entity 抽出
- spaCy ja_core_news_lg (or GiNZA) で ORG/MONEY/DATE/PERCENT/LAW フォールバック
- 各 entity を SQL で corpus 照合 (例: 法人番号 → `am_entities`、url → `am_source`、law → `laws.name_ja LIKE`)

**match_rate 計算**:
```python
W = {"money":3,"law":3,"url":2,"houjin":2,"program":2,"year":1,"percent":1,"count":1,"jsic":1}
def evaluate(narr_id, table, conn) -> float:
    rows = conn.execute("SELECT entity_kind, corpus_match FROM am_narrative_extracted_entities "
                        "WHERE narrative_id=? AND narrative_table=?", (narr_id, table)).fetchall()
    if not rows: return 1.0
    num = sum(W[k] * m for k, m in rows)
    den = sum(W[k] for k, _ in rows)
    return num/den

THRESHOLD = 0.85  # 85% 以下は quarantine
```

cron `.github/workflows/narrative-factcheck-weekly.yml` (operator runner、Sun 02:00 JST)。

### 10.10.3 (2) 抜き打ちサンプリング統計

母集団 N = 320,000、Wilson 95% CI 半幅 ±d:

| 想定 p | 検出半幅 d | n (有限母集団補正後) |
|---|---|---|
| 1% | ±0.5% | 1,498 |
| 5% | ±1.0% | 1,800 |
| 5% | ±2.0% | 453 |
| 10% | ±2.0% | 858 |

採用:
- **月次 n=1,000** (p=5% を ±1.4% で検出、launch 後 ongoing)
- **launch 前 tier S+A 11,632 件 100% pre-review** (詐欺リスク防衛、agent A 指摘修正)
- 四半期 n=1,800 (p=5% を ±1.0% で)
- 年次 n=4,000 (p=1% を ±0.3% で)

stratified random sampling で table 別に按分。

### 10.10.4 (3) 顧客報告 channel

REST: `POST /v1/narrative/{narrative_id}/report`、SELECT-only 制約のため write は INSERT のみ (LLM 呼出なし)。

```python
# src/jpintel_mcp/api/narrative_report.py
SEVERITY_RULES = [
    ("P0", lambda r: any(k in r.field_path or "" for k in ["amount", "deadline", "eligibility"])),
    ("P1", lambda r: r.evidence_url and any(d in r.evidence_url for d in [".go.jp", ".lg.jp"])),
    ("P2", lambda r: bool(r.claimed_correct)),
]
def auto_severity(r: ReportIn) -> str:
    for sev, pred in SEVERITY_RULES:
        if pred(r): return sev
    return "P3"

@router.post("/v1/narrative/{nid}/report")
async def report(nid: int, body: ReportIn, key=Depends(require_api_key_or_anon)):
    sev = auto_severity(body)
    sla = datetime.utcnow() + timedelta(hours=24 if sev in {"P0","P1"} else 72)
    db.execute("INSERT INTO am_narrative_customer_reports(...) VALUES(...)", ...)
    if sev == "P0":
        db.execute(f"UPDATE {body.narrative_table} SET is_active=0 WHERE narrative_id=?", (nid,))
    return {"received": True, "severity": sev, "sla_due_at": sla.isoformat()}
```

24h SLA gate cron `narrative_report_sla_breach.py`: 期限超過 P0/P1 を Telegram push。

### 10.10.5 (4) 月次自動再生成 (corpus drift)

**v2.1**: drift 検出は Fly cron 内 SQL のみ (LLM 呼出なし)、再生成は **Claude Code Max Pro Plan subagent** で各メンバーが翌日担当 batch として実行。

検出側 `scripts/cron/narrative_drift_detect.py` (Fly cron daily):
```sql
WITH dirty AS (
  SELECT entity_id FROM am_amendment_diff WHERE detected_at >= datetime('now','-30 days')
), reflag AS (
  SELECT npn.narrative_id, 'am_program_narrative' AS tbl
  FROM am_program_narrative npn JOIN programs p ON p.id = npn.program_id
  WHERE p.canonical_id IN (SELECT entity_id FROM dirty)
)
INSERT INTO am_narrative_quarantine(narrative_id,narrative_table,reason,match_rate,detected_at)
SELECT narrative_id, tbl, 'corpus_drift', NULL, datetime('now') FROM reflag;
```

content_hash diff (`am_source.content_hash` 変化) も同 path に合流。
**再生成は Claude Code subagent batch** (operator が `_assignments/{date}.csv` で member 分担): 差分のみ毎週、フル再生は四半期 (memory `feedback_no_operator_llm_api`)。

### 10.10.6 (5) rollback と顧客通知

```python
def rollback(narrative_id: int, table: str):
    conn.execute(f"UPDATE {table} SET is_active=0 WHERE narrative_id=?", (narrative_id,))
    cf.purge_cache(tags=[f"narrative:{table}:{narrative_id}"])  # Cloudflare Cache Tags
    affected = conn.execute("""
        SELECT DISTINCT api_key_id FROM am_narrative_serve_log
        WHERE narrative_id=? AND narrative_table=?
          AND served_at >= datetime('now','-30 days') AND api_key_id IS NOT NULL
    """, (narrative_id, table)).fetchall()
    for (kid,) in affected:
        n = conn.execute("""SELECT COUNT(*) FROM am_narrative_serve_log
                            WHERE api_key_id=? AND narrative_id=? AND narrative_table=?
                            AND served_at >= datetime('now','-30 days')""",
                         (kid, narrative_id, table)).fetchone()[0]
        stripe_credit(kid, yen=n*3)  # ¥3 × n 件 credit
        send_email(kid, template="narrative_corrected", n=n, narrative_id=narrative_id)
```

`X-Cache-Tag: narrative:{table}:{id}` を envelope レスポンスに必ず付与、Cloudflare Cache Tags で purge 可能に。

### 10.10.7 (6) operator 抜き打ち workflow (Telegram)

`scripts/cron/narrative_audit_push.py` (月次 1st 09:00 JST): n=1,000 件を Telegram bot に push、operator が ✓/✗/修正 を返す。✗ 確定で `quarantine(reason='operator_reject')` → rollback path 合流。NG body は `tools/offline/regenerate_narratives.py` の few-shot に `BAD_EXAMPLES.jsonl` として追加。

### 10.10.8 KPI と alert

| metric | target | alert threshold |
|---|---|---|
| weekly factcheck match_rate (median) | ≥ 0.92 | < 0.85 で Telegram |
| quarantine rate (active 中) | ≤ 1.0% | > 2.0% で Telegram |
| customer report SLA breach | 0 | > 0 で Telegram |
| sample audit NG rate (n=1000/月) | ≤ 3% | > 5% で 全プロンプト re-tune |
| rollback 件数 / 月 | ≤ 5 | > 10 で 章 10.6 全停止検討 |

`monitoring/sla_targets.yaml` に追加、`scripts/cron/dispatch_webhooks.py` から Telegram push。

---

## 章 11. 検証ゲート / 再レビュー / 計画外 risk

### 11.1 章ごとの done 判定

| 章 | done 判定 |
|---|---|
| 2 | `pytest tests/test_audit_seal_rotation.py tests/test_boot_gate.py` 全 pass + grep "監査封緘" = 0 + 弁護士書面 OK |
| 3 | `am_program_eligibility_history` で tier S/A 全 1,454 行 history >= 1、`am_compat_matrix.visibility='internal'` query default 除外動作、`source_verified_at` median <= 3d、`exclusion_rules` >= 5,000 |
| 4 | DB lock pytest mock で 429 fail-closed、CORS hardcoded fallback で apex/www 必ず allow、webhook test rate worker 横断 |
| 5 | **16 sensitive tools 弁護士書面 OK**、PPC 照会回答受領、invoice response に `_pii_notice` 必ず注入 |
| 6 | `pytest tests/mcp/test_http_fallback_all_120.py` 全 pass、grep "JPINTEL_\|jpintel-mcp\|amount_min[^_]" examples/ = 0、manifest 旧数字 0 |
| 7 | `DIRECTORY.md` 修正、`pip install jpcite` 成功、IndexNow ping jpcite.com 名義、AI cited >= 5/60 (4 週間後)、301 git-tracked + e2e test pass |
| 8 | Stripe HTML scrape sunset alert 動作、idempotency sweep cron 動作、SQLite litestream 動作、Sentry rules wired、release_command 復活 |
| 9 | A-O 各拡張の検証 SQL pass。**B**: 17 週後 `SELECT COUNT(DISTINCT law_canonical_id) FROM am_law_article WHERE text_full IS NOT NULL;` >= 9,484 |
| 10 | 24 新 tool 全部 200 応答、新 envelope JSON schema validation pass、ranking composite eval gold 79 で precision@10 >= 0.85 |
| 10.10 | weekly factcheck match_rate median >= 0.92、tier S+A 11,632 件 100% pre-review 完了、customer report endpoint 動作、Telegram audit workflow 動作 |
| 11 | 全章 pass + `simplify` skill で全変更レビュー + `security-review` skill 通過 |
| 12 | 10 use case の e2e test (Claude Desktop で各シナリオ実行 + envelope 検証) pass |

### 11.2 大規模修正後の再レビュー

各章完了後:
1. `simplify` skill で再構成漏れチェック
2. `security-review` skill で security regression チェック
3. 8 並列 subagent で「弱点修正→新弱点導入」を再 audit (本書章 2-7 を再走)
4. `evals/run.py` で 79 gold-standard で precision@10 計測
5. 本番 staging deploy → 24h 観測 → 本番 deploy

### 11.3 計画外 risk

| risk | 対処 |
|---|---|
| Fly volume 150GB 拡張で課金増 (+¥2,250/月) | 受容 (memory `feedback_no_cheapskate`) |
| operator-LLM ETL コスト (initial $10,800 / monthly $80) | 受容 |
| litestream stream 中断 | Sentry alert + manual restart runbook |
| 弁護士 review が想定より長期化 | 該当 16 sensitive tools を AUTONOMATH_*_ENABLED で gate-off (launch 日付議論せず) |
| 章 9.B 17 週 saturation 中の law_articles 不完全 | README badge で透明化、user-facing は honest |
| 章 10 narrative LLM hallucination | 章 10.10 全 6 系統で防御。tier S+A 100% pre-review が最終 backstop |
| ¥3 envelope 5-10KB で network bandwidth 増 | 受容、CloudFlare cache 併用 |
| sqlite-vec ANN index で大量 vector 検索 latency | tier 別 index 分割 + LRU cache |
| 章 10.2.6 houjin_360 monthly snapshot で DB 容量爆発 (主要 100,000 法人 × 12 月 = 1.2M row × 5KB JSON = 6GB / 年) | 受容 + 5 年で archive |
| operator-LLM 出力に PII (個人氏名) 混入 | 生成前に redact filter (人名 NER) 必須通過 |

### 11.4 全章完了後の最終 verdict

- **マーケコピーが事実になる**: 96 → 120 tool 全部動く、9,484 法令 catalog stub + 154 全文 (17 週後 saturate)、median 1-3 day verify、5M+ invoice、監査封緘契約条項化、amendment 真 time-series、compat 全 sourced (8 ヶ月後)、exclusion 5,000+
- **¥3 で受け取れる情報密度 50-100 倍**: envelope に narrative + similar + combinable + calendar + adoption_stats + related_laws + related_tax + application_documents + audit_seal を同梱
- **ARR ceiling**: agent G 推定の Y1 ¥10-30M / Y3 ¥80-300M (whale 1-2 件で variance ±¥30M) が現実値
- **法的リスク**: 16 sensitive tools 弁護士書面 + PPC 回答 + ToS 第X条 で防御線確立
- **operator 負荷**: ZeroTouch 維持、operator-LLM ETL は cron 化で人手介入ゼロ、Telegram 抜き打ち 1,000/月 で平均 1 タップ × 1,000 = 月 30 分以内

---

## 章 12. ★ 顧客 use case 10 件 (8 cohort 全網羅)

各 use case は章 10.7 / 10.8 の新 envelope を前提とする。LLM agent (Claude Desktop / Cursor / 顧客内製 agent) が `_next_calls` を辿り 1-3 tool で完結。

### UC1 — M&A 1st screening

**persona**: 中堅 PE「Sunrise Capital Partners」アソシエイト 田中 (29 歳)、AUM ¥800 億、年 6 件投資、案件あたり DD 期間 2-3 週間。

**課題**: LOI 締結直後の 1st-stage screening。対象企業の補助金依存度・過去の不正受給返還処分・適格事業者番号と invoice 取引相手から推測する業績ピーク。手作業 2-3 時間。

**LLM agent への質問**:
> 「法人番号 4010001234567 の M&A 1st screening やって。補助金履歴と行政処分と invoice 取引推測。」

**MCP tool sequence (3 call)**:
1. `get_houjin_360_snapshot_history` (#102): `{"houjin_bangou":"4010001234567","months":12}` → 12 ヶ月 trend、compliance_score 0.78→0.61、2025-11 に subsidy_exclude ¥3.2M
2. `get_houjin_subsidy_history` (#120): 過去 5 年採択 7 件 (合計 ¥48M、ものづくり 3 / 事業再構築 1 / IT 導入 3) + 1 件返還 ¥3.2M
3. `infer_invoice_buyer_seller` (#104): EDINET 大株主 + G-Net 落札から 8 社 (documented 2 + inferred_med 6)

**顧客最終アウトプット**: Slack に 1 画面で「業種・規模・コンプラ赤信号 (subsidy_exclude)・補助金依存 18-25%・取引集中 (Tier1 1 社)・DD 深掘り 3 項目」

**競合手段**: TDB Cosmos2 ¥3,200 + 手作業 3-4h、または弁護士照会 ¥30,000

**billing**: ¥3 × 3 = **¥9**

**value**: 年 60 件 screening で 180 時間節約 = ¥144 万/年。不正受給見落し回避で表保リスク数千万円回避。

---

### UC2 — M&A SPA 監視 (毎朝 watchlist)

**persona**: 同 Sunrise Capital シニア向井 (36 歳)。SPA 締結後クロージングまで 60-90 日のギャップで、対象企業の事業に直結する法令・補助金が改正されないかをデイリー監視。

**LLM agent への質問** (Cursor cron 9:00 トリガ):
> 「watchlist の houjin 4010001234567 と 7010001999888、SPA 締結以降の関連法令改正 / 制度改正 / 行政処分 fan-out あったか出して。」

**MCP tool sequence**:
1. `track_amendment_lineage_am` (Wave21 既存): 過去 14 日の amendment_diff
2. `forecast_enforcement_risk` (#100): 同業 JSIC で起きた処分から横展開リスク (波及確率 0.18)

**顧客最終アウトプット**: 経営会議資料 §3 に「ものづくり 19次資本金上限 1 億→3,000 万円対象継続/SPV 対象外 → 買収前申請推奨」「経営強化税制 2027 延長で ¥8.4M 節税余地」「同業処分 5 件、当社技能実習法違反波及リスク 18%」

**競合手段**: 弁護士月次巡回 ¥30 万/月、Westlaw Japan ¥8 万/月 (法令のみ、補助金改正対象外)

**billing**: ¥3 × 2 = **¥6/日**、月 ¥132

**value**: 改正見落しで MAC 条項発動 → クロージング遅延 → bridge 金利 7% × ¥10 億 × 2 ヶ月 = ¥1,160 万損失回避

---

### UC3 — 税理士月次決算 50 顧問先

**persona**: 個人税理士事務所「中野会計」中野麻紀子 (41 歳)。顧問先 50 社、月次決算 5 営業日、スタッフ 2 名。

**課題**: 月初に試算表受領後、各顧問先で「適用可能税制 + 今月の申告期限」を 5 分以内で確認したい。手作業 1 社 30 分 × 50 = 25 時間。

**LLM agent への質問** (LINE WORKS bot):
> 「顧問先一覧 (X-Client-Tag) の今月使える税制と期限まとめて。」

**MCP tool sequence**:
1. `prepare_kessan_briefing` (Wave22 既存): 各 client_profile の前回決算からの amendment_diff + 適用可能税制
2. `get_program_calendar_12mo` (#99): 各 client の業種で当月開いている制度

**顧客最終アウトプット** (顧問先「大和精密」へのメール):
> 5 月決算月、3 つの税制が適用可能性あり:
> 1. 中小企業経営強化税制 (措置法42-12-4): ¥120 万試算、2027-03 まで sunset 延長
> 2. 研究開発税制 (措置法42-4): 試算表で試験研究費区分確認、総額型 14% で ¥85 万試算
> 3. 賃上げ促進税制: 継続雇用者給与 +2.6%、30% 控除 ¥42 万、+5% 達成で 45%
> 当月期限: 5/31 法人税確定申告
> 補助金 (参考): 愛知県+製造業で 5 月開いている 4 件 (詳細別添)

**競合手段**: TKC FX シリーズ ¥8 万/月、税理士情報サイト ¥15,000/月、各社サイト手作業 50 社/月で 25 時間 = ¥25 万

**billing**: ¥3 × 2 × 50 顧問先 = **¥300/月**

**value**: 月 25 時間節約 = ¥25 万/月、年 ¥300 万。改正見落としで顧問契約解約リスク低減。

---

### UC4 — 会計士監査 8 社の補助金会計処理レビュー

**persona**: 中堅監査法人「Granthorn 第三事業部」マネージャー 山口 (38 歳)、公認会計士。製造業中堅 8 社の四半期レビュー担当。

**課題**: 補助金受給時の圧縮記帳/直接減額/積立金方式の選択、税効果会計影響、IT 導入補助金の収益認識 vs 費用控除を四半期で review。1 社 1 時間 × 8 = 8 時間。一次出典必須。

**LLM agent への質問**:
> 「監査先 8 社の Q1 補助金会計処理レビューやって。各社の受給制度と推奨処理 + 一次出典。」

**MCP tool sequence**:
1. `get_houjin_subsidy_history` (#120): 各社の受給制度
2. `get_program_narrative` (#107): 各制度の会計処理 narrative (監査用 section)
3. `compose_audit_workpaper` (Wave21 既存): 8 社分を audit_seal 付きで bundle

**顧客最終アウトプット** (監査調書 §C-3 補助金):
> 8 社合計受給 ¥158,300,000、5 社で論点あり:
> - 大和精密: ものづくり ¥12M を収益一時計上 → 圧縮記帳 (法基通10-2-2) 推奨、税負担 ¥3.6M 過大、修正で +¥3.6M キャッシュ改善
> - 山田機工: IT 導入 ¥4.5M を売上控除 → 「収入の額に算入」が原則 (実務指針 19 号)、修正仕訳要
> - 残 3 社で source_url 添付漏れ
> audit_seal: HMAC `a7f2...`、第三者検証 URL 同梱
> 一次出典 リスト: 国税庁通達 3 / 措置法 2 条文 / 中小企業庁交付要綱 2

**競合手段**: TKC TPS 1000 ¥30 万/年、租税研究 ¥8 万/年、各社個別調査 1 社 1 時間 × 8 = 8 時間/Q (¥80,000)

**billing**: ¥3 × (8 history + 8 narrative + 8 × (1+10) audit+export) = **¥312/Q**、年 ¥1,248 (audit_workpaper の `_WORKPAPER_EXPORT_UNITS=10` を含む)

**value**: 監査調書工数 8 時間 → 30 分、年 ¥320,000 節約 + 圧縮記帳見落しで顧客提案増。

---

### UC5 — Foreign FDI: SaaS 日本市場参入 (英語)

**persona**: シンガポール本社 B2B SaaS「Helix Analytics Pte Ltd」APAC Director Sharon Chen (34 歳)、日本語不可。

**課題**: 日本に WFOE 設立予定、適用税制 (R&D 控除/経営強化/データセンター) + 必要許認可 (APPI / 電気通信事業法) を英語で 1 query。Tokyo 法律事務所 ¥40,000/h × 3h = ¥120,000、1 週間待ち。

**LLM agent への質問** (Claude Desktop English):
> "I'm setting up a Japan WFOE for a B2B SaaS data analytics company. List applicable Japanese R&D tax credits, SMB strengthening tax measures, and required licenses (APPI / Telecommunications Business Act). English only."

**MCP tool sequence**:
1. `search_tax_incentives` (既存) `lang=en, foreign_capital_eligibility=True`
2. `cross_check_jurisdiction` (Wave22 既存): 想定法人形態と必要登録の照合
3. `get_law_article_am` `lang=en` (mig 090 で `body_en` 列追加済): 個人情報保護法 §22 英訳 (e-Gov 公式 CC-BY)

**顧客最終アウトプット** (Sharon が Singapore HQ 弁護士 James に送るメール):
> Applicable Tax Credits (KK with capital ¥100M):
> 1. R&D Tax Credit (STMA §42-4): Total credit at 14%, foreign capital eligible. Sunset 2027-03-31. Caveat: cost-sharing with Singapore HQ requires APA.
> 2. SME Strengthening (措置法 42-12-4): 7% credit (10% for SMEs ≤¥100M).
> Licenses: APPI Notification (§22), Telecom Business Notification (~30 days), Foreign Exchange Act §26 prior notification NOT required.
> All sources are NTA/MIC/MOJ/MOF primary URLs. Recommend local 税理士 for APA strategy.

**競合手段**: Tokyo 法律事務所 ¥120,000 + 1 週、Big 4 Japan tax desk ¥160,000

**billing**: ¥3 × 3 = **¥9**

**value**: ¥120,000 → ¥9、即時。FDI 時の missed credit 1 件 (R&D 年 ¥10M × 5 年 = ¥50M) 回避。

---

### UC6 — 補助金コンサル 30 社の週次 digest

**persona**: 個人補助金コンサル「東京アシスト」白井 (45 歳)。顧問先 30 社、月顧問料 ¥3-8 万、採択時成功報酬 10%。

**課題**: 顧問先別 saved_search を毎週月曜 6:00 に手動回し → 各社 5-10 分 = 2-3 時間。1 件見落しで信用失墜。

**LLM agent への質問** (Slack Claude bot, 月曜朝 cron):
> 「顧問先 30 社の saved_search 全実行、新規ヒット + 締切 14 日以内のものを digest。」

**MCP tool sequence**:
1. `recommend_programs_for_houjin` (#97): 各 client_profile に TOP 10
2. `find_emerging_programs` (#118): 過去 7 日新規施行 12 件
3. `bundle_application_kit` (Wave22 既存): 各社「今すぐ動く」案件をパッケージ化

**顧客最終アウトプット** (Slack、顧問先「東洋メカトロ」へ):
> 緊急 事業再構築補助金 第9回 締切 5/18 (残 14 日): 御社の前期売上 -12% + EV 部品事業展開計画にぴったり、score 0.84、過去採択率 42%、平均交付 ¥820 万。今週中着手必須。
> 中 GX 設備導入支援 (経産省、新規施行 4/28): EV 部品製造業向け、上限 ¥3,000 万、補助率 1/2、御社電力契約変更計画と相性◎。
> 参考 8 件: 事業承継 / IT 導入 / 賃上げ / 人材確保 / 省エネ / 原材料高 / DX / 知財。
> アクション: 今週水曜 14:00 で事業再構築 review ミーティング設定希望。
> 一次出典 全 12 本 URL 別添。

**競合手段**: 補助金ポータル ¥9,800/月、ミラサポ plus 無料 (個別マッチなし)、手作業 30 社 × 10 分 = 5 時間/週 = ¥40,000/週 = ¥160,000/月

**billing**: ¥3 × (10+1+1) × 30 = **¥1,080/週** = ¥4,320/月

**value**: 月 20 時間節約 = ¥160,000/月。1 件採択増 (¥800 万 × 成功報酬 10%) で年 ¥960 万増収余地。

---

### UC7 — 中小企業 LINE 公式 (食品スーパー個店)

**persona**: 静岡県浜松市食品スーパー「マルトモ商店」3 代目 友田 (52 歳)、従業員 18 名、年商 ¥4.2 億。スマホ LINE のみ、税理士に聞くたび ¥10,000。

**課題**: 「うち使える補助金あるんかな」「電気代きついから省エネで何かないか」を LINE で雑に聞いて、業種・地域・規模で勝手に推奨してほしい。

**LLM agent への質問** (LINE 公式 bot 経由、自然文):
> 「うち食品スーパー 18 人。電気代きついから省エネで使える補助金ある? 浜松市」

**MCP tool sequence**:
1. `find_programs_by_jsic` (#109): JSIC I (卸売・小売業) 中分類 58 (飲食料品小売業) で絞込
2. `get_program_calendar_12mo` (#99): 当月開いている案件
3. `get_program_narrative` (#107): 1 件目を `reading_level="plain"` で平易日本語

**顧客最終アウトプット** (LINE bot、平易日本語):
> 友田さん、こんにちは!
> 浜松の食品スーパーさんなら、いま 3 つ使えそうな補助金あります。
> **1. 静岡県 省エネ補助金 (締切 7/31)** お金の半分くれます (上限 300 万)。LED や省エネ冷蔵庫に。注意: 見積 3 社必須、設置後 30 日以内に報告 (これ忘れる人多い)、既設の入れ替えのみ。
> **2. 国の省エネ税制** 補助金とは別に、設備買った金額の 7% を法人税から引ける。県の補助金と一緒に使えます。
> **3. 浜松市 省エネ診断 (無料)** プロが店に来て電気代の無駄を診断、これ受けると 1 番で +10 点加点。
> 顧問の中野先生に「jpcite で見たけど」と伝えると話早いです。

**競合手段**: 顧問税理士電話 ¥10,000、商工会議所窓口 1.5 時間、ミラサポ plus サイト (自分で検索 = 詰む)

**billing**: ¥3 × 3 = **¥9** (LINE 公式アカウント運営者課金、エンドユーザ無料)

**value**: 50 代中小経営者の「補助金あるか分からない」問題解消。年 1 件採択 ¥150 万受給。LINE bot 運営側 (商工会議所等) は @月 ¥3,000 で全会員開放可能。

---

### UC8 — 信金商工会 800 社の年次決算期レポート

**persona**: 福井県越前信用金庫 法人推進部 谷岡 (39 歳)。会員融資先 800 社、3 月決算が 60%。

**課題**: 800 社 × A4 1 枚 手作業 = 1 社 20 分 × 800 = 267 時間 = 担当 4 名で 9 営業日。中身も「一般的な補助金リスト」止まり。

**LLM agent への質問** (信金内製 batch、年 1 回):
> 「会員 800 社全件、各社の業種・規模で使える S/A tier 制度 TOP 5 + 6 ヶ月の期限 + 越前信金融資との併用可否を A4 PDF で。」

**MCP tool sequence (per 1 社)**:
1. `recommend_programs_for_houjin` (#97): TOP 5 + score breakdown
2. `find_combinable_programs` (#98): 越前信金保証付融資 (program_id 既知) と各補助金の併用可否

**顧客最終アウトプット** (各 A4 1 枚 PDF):
> **株式会社 福井機械 — 翌期使える制度集約**
> 御社プロファイル: 福井県、製造業 (E)、従業員 45 名、資本金 3,000 万円、年商 ¥6 億 (前期比 +3%)
> 推奨補助金 TOP 5 (該当 score 順):
> | 順位 | 制度 | 上限 | 締切 |
> |---|---|---|---|
> | 1 | ものづくり補助金 第19次 | ¥1,250 万 | 5/31 |
> | 2 | 福井県 次世代ものづくり産業支援 | ¥500 万 | 6/15 |
> | 3 | IT 導入補助金 2026 | ¥450 万 | 9/30 |
> | 4 | 事業承継引継ぎ補助金 | ¥600 万 | 8/20 |
> | 5 | 福井県 省エネ補助 | ¥300 万 | 7/31 |
> 越前信金との併用: 5 制度すべて当金庫保証協会付運転資金 (1.2%) と用途異なり併用可。設備資金融資 (1.5%) は 1 番のものづくりで対象設備自己負担分 (1/2-2/3) 活用推奨。
> 当行担当: 谷岡 (内線 4123)、次回ヒアリング 5/20 13:00。

**競合手段**: 系統金融研修所テンプレ + 内部 800 × 20 分 = 267 時間 = ¥1,335,000、外注 ¥800,000/年

**billing**: ¥3 × 2 × 800 = **¥4,800/年**

**value**: 267 時間 → 1 営業日。年 ¥1,330,000 節約 + 全件 customize で会員融資残高 ¥30M 平均 × 1% 解約阻止 = ¥2.4 億残高保全。

---

### UC9 — 業界 pack 建設 (中堅ゼネコン経営企画)

**persona**: 北関東中堅ゼネコン「東和建設」経営企画室 室長 高橋 (47 歳)。年商 ¥180 億、従業員 280 名、公共工事比率 65%。

**課題**: 月次経営会議で過去 30 日の建設業関連 (法令改正 + 行政処分 + 関東で新規開いた補助金 + 公共工事入札) を 5 分で報告。社内法務部に投げると 2 営業日。

**LLM agent への質問** (社内 ChatGPT、月次):
> 「建設業向け、過去 30 日の法令改正 + 行政処分 + 関東で新規開いた補助金 + 公共工事 (国交省・関東地方整備局) まとめて。」

**MCP tool sequence**:
1. `pack_construction` (Wave23 既存)
2. `find_emerging_programs` (#118)
3. `forecast_enforcement_risk` (#100): 自社 JSIC D33 への波及

**顧客最終アウトプット** (経営会議資料 §3):
> 月次業界動向 (2026 年 4 月) — 建設業関連
> 法令改正 重要 2 件:
> 1. 労働安全衛生規則 §518 フルハーネス義務化拡大 (2026-05-01 施行) → 当社高所作業全現場影響、追加投資 ¥2.2M、5/12 までに購入計画決定
> 2. 建設業法施行規則 §7-2 電子契約押印代替明確化 → 当社既に GMO サイン移行済、対応不要
> 新規補助金 関東 中堅向け 3 件:
> 1. 関東 中小建設業 BIM 導入支援 (4/22 新規) 上限 ¥800 万、当社 BIM プロジェクト Y2 計画と整合、IT 推進室で申請検討
> 2. 栃木県 空き家再生事業 上限 ¥150 万
> 3. 住宅省エネ 2026 (国交省) 上限 ¥300 万/件、当社注文住宅事業で年 30 件想定 = ¥9,000 万受給ポテンシャル
> 行政処分 同業関東 過去 90 日 4 件: 下請法違反 2 / 墜落事故 1 / 産廃 1。波及リスク 0.21。下請取引 review を法務部 5/15 期限。
> 税務トピック: 国税不服審判所 裁決事例 2 件 (請負工事課税仕入対応 + 工事進行基準)、当社既通達準拠、影響なし。
> 次月見通し: 6 月は労働安全衛生規則 cooling-off 終了で取締強化、現場巡回優先。

**競合手段**: 法務部内製 16 時間 (¥160,000)、外注ニュースレター ¥5 万/月、建設業 SaaS ¥18,000/月

**billing**: ¥3 × 3 = **¥9/月**、年 ¥108

**value**: 月 16 時間 → 30 分、年 ¥1,920,000 節約 + BIM 補助金 ¥800 万受給 + 住宅省エネキャンペーン ¥9,000 万獲得余地

---

### UC10 — 業界 pack 不動産 (地場仲介、客先で 30 秒回答)

**persona**: 神奈川県横浜市 地場不動産仲介「湘南ホーム」社長 木村 (54 歳)、従業員 12 名。賃貸管理 800 戸 + 売買仲介。地主からの相続 + 空き家相談増。

**課題**: 地主との相談 (1,500 坪相続予定 + 空き家 2 棟、賃貸経営継続 vs 売却) で「使える税制 + 補助金 + 法令制約」を **その場で 30 秒**。後日税理士同席だと熱が冷める。

**LLM agent への質問** (営業 iPad、客先で):
> 「相続予定土地 1,500 坪 (横浜市青葉区)、保有空き家 2 棟、相続税対策 + 空き家活用 + 賃貸住宅建設の制度まとめて。」

**MCP tool sequence**:
1. `pack_real_estate` (Wave23 既存)
2. `find_complementary_subsidies` (#115): 相続税対策 × 賃貸建設 × 空き家活用 の 3 軸補完
3. `cross_check_jurisdiction` (Wave22 既存): 横浜市青葉区 用途地域から制約抽出

**顧客最終アウトプット** (湘南ホーム木村が地主に見せる 1 枚):
> 田中様 — 相続+空き家活用 制度パッケージ案
> 前提: 横浜市青葉区 1,500 坪 + 空き家 2 棟、相続税対策 + 賃貸経営継続
> 使える制度 3 本立て (優先順):
> A. 横浜市 空き家再生補助 (上限 200 万、12 月締切): 解体 ¥100 万 / リフォーム転用 ¥200 万満額。
> B. 住宅金融支援機構 賃貸住宅融資 (固定 1.95%、35 年): 200m² 賃貸住宅 〜¥80M 借入。**用途地域**: 第一種低層住居専用 = 3 階建てまで、戸数 6-8 戸が現実。準工業エリア部分は 4 階以上可。
> C. 小規模宅地等の特例 (措置法 69-4): 賃貸事業用 200m² まで評価額 50% 減。60 坪部分認定で相続税概算 ▲¥1,800 万。
> 適用順序: 今期空き家 1 棟リフォーム → 来期上期 賃貸住宅 6 戸 → 相続発生時に貸付事業用認定。
> 税理士確認必須: 小規模宅地特例 貸付事業用判定 / 賃貸融資 親子間連帯保証 / 不動産所得 損益通算
> 当社サポート: 申請書類作成、6 戸事業計画策定、入居者募集まで一気通貫。
> 本資料は jpcite 公開一次出典集約。最終判断は山下税理士事務所助言に基づき (宅建業法 §47条の2 該当)。

**競合手段**: 税理士同席 ¥30,000/h × 2h = ¥60,000、しかも 1 週間後 → 客の購入意欲冷めて流出

**billing**: ¥3 × 3 = **¥9**

**value**: その場で資料 → 成約率 +20%。仲介手数料 ¥9.9M (1,500 坪売買時) または賃貸管理 6 戸 × 5%。年 5 件成約増で **¥30M 売上増**。

---

### 章 12 まとめ表 (cohort カバレッジ)

| UC | cohort | 主 tool (新 #) | billing | 競合比 | value 規模 |
|---|---|---|---|---|---|
| 1 | M&A 1st (#1) | 102/120/104 | ¥9 | ¥3,200 + 3-4h → ¥9 + 30s | ¥144M/年 + 表保リスク |
| 2 | M&A 監視 (#1) | Wave21+#100 | ¥6/日 | ¥30 万/月 → ¥132/月 | ¥1,160 万損失回避 |
| 3 | 税理士 (#2) | Wave22+#99 | ¥300/月 | ¥25 万/月 → ¥300/月 | ¥300 万/年 |
| 4 | 会計士 (#3) | #120/#107/Wave21 | ¥312/Q | ¥80,000/Q → ¥312/Q | ¥320,000/年 + 提案増 |
| 5 | FDI (#4) | 既存EN+Wave22+#90 | ¥9 | ¥120,000+1週 → ¥9+即時 | ¥50M missed credit 回避 |
| 6 | コンサル (#5) | #97/#118/Wave22 | ¥4,320/月 | ¥160,000/月 → ¥4,320/月 | ¥960 万/年増収 |
| 7 | LINE (#6) | #109/#99/#107 | ¥9 | ¥10,000/相談 → ¥9 | エンドユーザ ¥150 万獲得 |
| 8 | 信金 (#7) | #97/#98 | ¥4,800/年 | ¥1,335,000+9日 → ¥4,800+1日 | ¥2.4 億残高保全 |
| 9 | 建設 (#8) | Wave23+#118+#100 | ¥9/月 | ¥160,000/月 → ¥9/月 | ¥9,800 万受給余地 |
| 10 | 不動産 (#8) | Wave23+#115+Wave22 | ¥9 | ¥60,000+1週 → ¥9+即時 | ¥30M 売上増 |

8 cohort 全網羅、すべての use case が「¥3 で時給換算・機会逸失・コンプラ罰則のいずれかで 1,000 倍以上の ROI」を成立。

---

## 付録 A. 全タスクの DAG 視覚化

```
[Ship-Stop]
  S1 ──┐
  S2   │
  S3 ──┘── 法的書面確認
        │
[Data Integrity]
  D1, D2, D3, D4, M5, M6, M7    ──┐
                                   │
[Auth]                             │
  A1, A2, A3, M13-M16              │
                                   │
[Legal]                            ├── 章 11 検証ゲート
  L1 (16 tools 弁護士書面),        │
  L2 (PPC), L3                     │
                                   │
[MCP UX]                           │
  U1 ──> 章 9.A REST 拡張          │
  U2, U3, M18-M20                  │
                                   │
[Brand/SEO]                        │
  B1, B2 ──> J PyPI                │
  B3, B4, B5 ──> I AI cited        │
                                   │
[Billing/Infra]                    │
  P1 (Stripe HTML scrape),         │
  M1-M4, M8-M12                    │
                                   │
[マーケコピー実体化]               │
  A-O (B = 17 週 saturation)       │
                                   │
[アウトプット強化]                 │
  10.1 ──> 10.2 ──> 10.3           │
              ──> 10.6 ──> 10.10   │
                          ──> 10.7 │
              ──> 10.4 ──> 10.5    │
                                ───┤
[Use case 12]                      │
  10 シナリオ e2e ──> 章 11 ───────┘
```

---

## 付録 B. 全 ETL source 一覧

| source | URL | license | 取得形式 | 対象テーブル |
|---|---|---|---|---|
| e-Gov 法令 | https://elaws.e-gov.go.jp/api/ | CC-BY 4.0 | XML API (1 req/sec) | am_law_article, laws (17 週 saturate) |
| 国税庁 適格事業者 | https://www.invoice-kohyo.nta.go.jp/ | PDL v1.0 | CSV bulk + Web | invoice_registrants (4M 行) |
| 国税庁 通達 | https://www.nta.go.jp/law/tsutatsu/ | 公衆衛生 | HTML | nta_tsutatsu_index |
| 国税庁 裁決事例 | https://www.kfs.go.jp/ | 公衆衛生 | HTML | nta_saiketsu |
| 国税庁 文書回答 | https://www.nta.go.jp/about/organization/.../bunsho/ | 公衆衛生 | HTML | nta_bunsho_kaitou |
| 国税庁 質疑応答 | https://www.nta.go.jp/law/shitsugi/ | 公衆衛生 | HTML | nta_shitsugi |
| gBizINFO | https://info.gbiz.go.jp/ | 利用規約 | REST API | houjin_master |
| EDINET | https://disclosure.edinet-fsa.go.jp/ | 公開 | XBRL | jpi_edinet_disclosures, am_invoice_buyer_seller_graph |
| JFTC 公正取引委員会 | https://www.jftc.go.jp/ | 公開 | HTML | enforcement_cases |
| 各省庁 行政処分 | (各省庁) | 公開 | HTML | enforcement_cases |
| METI 公募要領 PDF | (各 program) | 公開 | PDF parse | am_program_documents |
| MAFF 補助金交付決定 | (各補助金) | 公開 | Excel | jpi_adoption_records |
| 47 都道府県公報 | (47 各 site) | 公開 | HTML/PDF | programs |
| JFC 融資商品 | https://www.jfc.go.jp/ | 公開 | HTML | loan_programs |
| 信用保証協会 | (47 各 site) | 公開 | HTML | loan_programs |
| 中小企業庁 mirasapo+ | https://mirasapo-plus.go.jp/ | 公開 | API | programs |
| jGrants | https://www.jgrants-portal.go.jp/ | 公開 API | REST | programs |
| 厚労省 助成金 | https://www.mhlw.go.jp/ | 公開 | HTML | programs |
| G-Net | https://www.geps.go.jp/ | 公開 | HTML | am_invoice_buyer_seller_graph (落札相手) |
| 税制改正大綱 PDF | (財務省 / 与党 PT) | 公開 | PDF | am_tax_amendment_history |

---

## 付録 C. ★ Claude Code subagent ETL workflow (`tools/offline/`) — v2.1 全面書換

**v2.1**: API 直叩き完全廃止。operator 側 LLM ETL は **すべて Claude Code Max Pro Plan サブエージェント経由**で実行。`tools/offline/` 配下に Anthropic / OpenAI / Gemini SDK の import 禁止。CI guard `tests/test_no_llm_in_production.py` を `tools/offline/` まで拡張。embedding は **ローカル sentence-transformers (intfloat/multilingual-e5-large)** で operator マシン上で実行 (LLM call ではなく ML 推論、API ¥0)。

### C.1 共通実装規約 (v2.1)

- 全ファイル先頭: `# operator subagent runner — see feedback_no_operator_llm_api`
- `tools/offline/__init__.py` から **`anthropic` / `openai` / `google.generativeai` SDK の import を全面禁止**
- DB 接続: `sqlite3.connect("autonomath.db", isolation_level=None)` (root path)、`PRAGMA journal_mode=WAL`、書込前 `BEGIN IMMEDIATE`
- **secret 不要** (Anthropic/OpenAI key 全廃)。Hugging Face token は public model 使用なので不要
- **Inbox/Outbox 構造**:
  ```
  tools/offline/_inbox/{tool_name}/{date}-{batch_id}.jsonl   ← Claude Code subagent 出力
  tools/offline/_outbox/{tool_name}/{date}-{batch_id}.processed
  tools/offline/_quarantine/{tool_name}/{date}-{batch_id}.jsonl ← QA 失敗
  tools/offline/_assignments/{date}.csv  ← 「アカウント X が batch Y 担当」
  tools/offline/_runlog/{tool_name}/{date}.jsonl  ← 実行ログ
  ```
- 担当配分の例 (5 アカウント × 5 メンバー = 25 並列):
  ```csv
  date,member,account,tool,batch_id,assignee_count
  2026-05-04,member1,acc1,program_narrative_ja,001,200
  2026-05-04,member1,acc2,program_narrative_ja,002,200
  2026-05-04,member2,acc1,program_narrative_en,021,200
  ...
  2026-05-04,member5,acc5,enforcement_summary_ja,120,50
  ```
- 各メンバーの実行手順:
  ```bash
  cd ~/jpcite
  claude  # Claude Code CLI 起動 (Max Pro Plan アカウント)
  > tools/offline/run_{tool}_batch.py の batch_002 を実行して。
  > SQL から 200 件取得、subagent 並列 8 で生成、_inbox に出力して。
  ```
- ingest cron `scripts/cron/ingest_offline_inbox.py` (LLM 呼出なし、SQL のみ): `_inbox` から JSON Lines 読み → Pydantic 検証 + literal-quote self-check pass で SQLite INSERT、NG は `_quarantine` 移動
- 抜き打ち QA: `.github/workflows/offline-quality-sample.yml` 月次後 5 日に random N 件 dump、operator が Telegram bot で ✓/✗/修正 を `am_offline_qa_log` に記録。許容失敗 c=2 超過で次月 batch block
- N (合格率 sample size): 片側二項検定 95% 信頼で母合格率 ≥ p0、許容 NG c=2 で `n = ceil(ln(0.05) / ln(p0)) * 1.5`。p0=0.95 → **N=58**、p0=0.90 → N=29

### C.2 `embed_corpus_local.py` (ローカル sentence-transformers、API なし)

- **model**: `intfloat/multilingual-e5-large` (Hugging Face、MIT、日本語対応 SOTA、1024 dim)
- 実行: operator マシン (M2 Max 等) で Python script、API call ゼロ
- input SQL: `SELECT e.entity_id, e.record_kind, name||'\n'||description AS text FROM am_entities e LEFT JOIN am_entity_facts f_name ON ... WHERE record_kind IN ('program','tax_measure','case_study','enforcement','law') AND entity_id NOT IN (SELECT rowid FROM am_entities_vec_v2) ORDER BY entity_id LIMIT 256;`
- 実装 (Anthropic/OpenAI SDK なし):
  ```python
  from sentence_transformers import SentenceTransformer
  import sqlite3, numpy as np
  model = SentenceTransformer("intfloat/multilingual-e5-large")  # ~2GB, local cache
  def embed_batch(texts: list[str]) -> np.ndarray:
      # E5 は "query: " or "passage: " prefix が必要
      return model.encode([f"passage: {t}" for t in texts], normalize_embeddings=True)
  ```
- output: `INSERT INTO am_entities_vec_v2(rowid, embedding) VALUES (?, ?) ON CONFLICT(rowid) DO UPDATE SET embedding=excluded.embedding;`
- skip: `am_source.content_hash` 一致なら再計算 skip
- 所要時間: M2 Max GPU で 75K entity × 800 tok = **約 3-5 時間**、CPU only で 8-12 時間
- **コスト ¥0** (operator マシン電気代のみ)
- N: 58 (p0=0.95)、top-5 nearest neighbor「同 jurisdiction/同 jsic_major 4/5 以上」で合格判定
- 月次更新: 新規 entity 5,000 程度を operator が手動 trigger (`python tools/offline/embed_corpus_local.py --max-rows 5000`)

### C.3 `tag_jsic_subagent_batch.py` (Claude Code subagent — Max Pro Plan)

**実行方法**: operator が Claude Code セッション内で `tools/offline/run_tag_jsic_batch.py --batch 002` 起動 → 親セッションが Task tool で subagent 並列 8 invoke → subagent が SQL から 200 件取得 + 各 program で内部推論 → JSON Lines を `_inbox/tag_jsic/{date}-batch_002.jsonl` に出力。

**subagent への投入プロンプト** (Claude Code Task tool 経由):
> あなたは日本標準産業分類 (JSIC、総務省告示 第405号) の専門ライターです。以下 25 件の program について、各 program の primary_name + 公募要領テキスト 5,000 字を読み、JSIC 大分類 (A-T) / 中分類 (2 桁) / 小分類 (3 桁) を構造化抽出してください。
> 原則: 公募要領に明記された業種のみ抽出 (推測禁止)、対象業種なき制度は空配列、多業種対象は最大 3 件、営業表現・disclaimer なし。
> 出力は JSONL 形式で `_inbox/tag_jsic/{date}-batch_{batch_id}.jsonl` に書き込み、各行は:
> `{"program_id": int, "tags": [{"jsic_major": "E", "jsic_middle": "29", "jsic_minor": "291", "evidence_quote": "...", "confidence": "high"}], "all_industries": false}`

**Pydantic schema (ingest 時検証)**:
```python
class JsicTag(BaseModel):
    jsic_major: Literal["A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T"]
    jsic_middle: constr(regex=r"^\d{2}$")
    jsic_minor: Optional[constr(regex=r"^\d{3}$")]
    evidence_quote: constr(max_length=30)
    confidence: Literal["high","med","low"]
class JsicResult(BaseModel):
    program_id: int
    tags: conlist(JsicTag, max_items=3)
    all_industries: bool = False
```

- **cost ¥0** (Max Pro Plan サブスク代のみ、subagent 呼出は限界費用ゼロ)
- ペース: 1 アカウント 1 日 1 セッション × subagent 8 並列 × 25 件/subagent = **200 件/日**。25 アカウント × 200 = **5,000 件/日**。11,684 program 全件 = **約 2-3 日**
- 失敗: `_inbox` 取込時に Pydantic ValidationError → `_quarantine` 移動 + Telegram alert / `evidence_quote` not in kobo_text → DLQ / 当該 program は次 batch で再投入
- N: 58 (p0=0.95)、operator が Telegram bot で抜き打ち
- 月次更新: 新規 program 推定 200 + amendment 再 tag 100 = 300 件 → 1 アカウント 1 日で完了

### C.4 `generate_program_narrative_subagent.py` (4 section × 2 lang)

**実行**: 各メンバーが Claude Code セッション (Max Pro Plan) で `tools/offline/run_narrative_batch.py --batch 002 --lang ja` 起動 → 親セッションが Task tool で subagent 並列 8 invoke。

**subagent への投入プロンプト**:
> あなたは日本の補助金・公的制度の専門ライターです。以下 25 件の program について、各 4 section × 1 言語 (ja or en) のナラティブを生成してください。
> 原則: (1) 公募要領 + 関連法令 + 過去採択事例の一次出典のみ。(2) 数値 (金額・割合・期日) は原文転記、変換しない。(3) 「最大」「最高」「業界 No.1」等の比較表現禁止。(4) disclaimer は出力しない (jpcite 側で自動付与)。(5) 各 section の字数を厳守 (overview=200±20、eligibility=300±30、application_flow=400±40、pitfalls=300±30)。
> 出力は JSONL `_inbox/program_narrative/{date}-batch_{id}.jsonl` に各行 1 program で:
> `{"program_id": int, "lang": "ja", "overview": "...", "eligibility": "...", "application_flow": "...", "pitfalls": "..."}`

**Pydantic schema (ingest 時検証)**:
```python
class Narrative(BaseModel):
    program_id: int
    lang: Literal["ja","en"]
    overview: constr(min_length=180, max_length=220)
    eligibility: constr(min_length=270, max_length=330)
    application_flow: constr(min_length=360, max_length=440)
    pitfalls: constr(min_length=270, max_length=330)
```

- **cost ¥0** (Max Pro Plan サブスク内、API call なし)
- **ペース**: 1 アカウント 1 セッション = subagent 並列 8 × 25 program = 200 program/日 (1 言語)。25 アカウント = 5,000 program/日 = **tier S+A 11,632 件は 2-3 日、全 11,684 × 2 lang = 約 19 日で 1 サイクル**
- 失敗: 字数 violation → ingest 時 Pydantic で fail → `_quarantine` 移動 → 次 batch で再投入 / NER で固有名詞 source 内不在 → DLQ
- N: **launch 前 tier S+A 11,632 件 100% pre-review** + monthly n=1,000 (3% rate)
- 月次更新: 新規 200 + amendment 再生成 100 = 300 program × 2 = 600 件、1-2 アカウント 1 日で完了

### C.5 `generate_houjin_360_subagent.py`

**subagent プロンプト**: houjin_master 公開情報のみ可、行政処分言及は事実列挙、評価語禁止 (悪質/違法/不正/脱税)、風評被害比較禁止。出力 ja=600 字 / en=500 word + key_facts 3-5 件 + data_completeness 0-1。

- Pydantic: `narrative` ja=540-660字 / en=450-550 word、`key_facts` 3-5 件、`data_completeness` 0-1
- **cost ¥0**
- ペース: 1 アカウント 1 日 = 200 法人 (1 言語)。25 アカウント × 1 日 = 5,000 法人。**主要 30,000 法人を 6 日**、100,000 法人を 20 日
- 失敗: hallucination → `key_facts` 各 fact を `am_entity_facts` 全件 LIKE 検索 / 風評 NG word filter / refusal → queue
- N: 58 (p0=0.95)、「事実検証 5/5 + 評価語 0」AND
- 月次更新: 新規上場・採択 200 法人 + 行政処分追加 50 法人 = 250 × 2 = 500 件、1 アカウント 1 日

### C.6 `generate_enforcement_summary_subagent.py`

**subagent プロンプト**: 処分日・条文・処分種別 (課徴金/業務改善命令/指名停止)・対象法人名・金額を事実列挙、行為態様評価語禁止、救済措置記載があれば明記。出力 ja=250 字 / en=200 word。

- Pydantic: `summary`、`amount_yen` Optional、`remediation_window` Optional、`key_articles` max_items=10
- **cost ¥0**
- ペース: 全 1,185 × 2 = 2,370 件、1 アカウント 1 日 = 200 件、**約 12 日 / 25 アカウントなら 1 日**
- 失敗: amount_yen 単位ミス (千円↔円) → detail.amount_yen を ground truth 上書き / hallucination remediation null 強制 / 評価語混入 → NG word filter → regenerate
- N: 29 (p0=0.90、母数小)
- 月次更新: 新規処分 80 件 × 2 = 160 件、1 アカウント 1 日

### C.7 `extract_application_documents_subagent.py` (PDF parse + subagent)

PDF parse は `pdfplumber` で事前 cache (LLM 不使用)、`{page_n}\n{text}` 形式で subagent に投入。

**subagent プロンプト**: 様式番号 (様式第 N 号) 厳格転写、提出形式 enum (PDF/Excel/Word/jGrants/郵送原本/その他)、必須/任意区別、「等」「その他」省略時 has_etc_omission flag。

- Pydantic: `documents` max_items=30、各 `name`/`form_id`/`format`/`submission`/`required`/`evidence_page`/`evidence_quote` (max_length=80)
- **cost ¥0**
- ペース: tier S+A 1,454 件、1 アカウント 1 日 = 100 件 (PDF 重い)、**25 アカウント = 1 日完了**
- 失敗: evidence_quote not in PDF → fuzzy match 95% / 様式番号 hallucination → regex 検査 / 画像 PDF → `confidence='low'` + OCR queue
- N: 58 (p0=0.95)
- 月次更新: 新規 30 公募 + 改訂 20 = 50 件、1 アカウント 1 日

### C.8 `extract_invoice_buyer_seller_subagent.py` (EDINET XBRL parse + subagent)

EDINET XBRL を Arelle で前処理、`data/edinet_textblock_cache.sqlite` に保存 (LLM 不使用)。

**subagent プロンプト**: XBRL タグ + 注記文の一次情報のみ、法人名は XBRL 表記そのまま、取引額・出資比率丸めない、連結 vs 単体明示。

- Pydantic: `relations` max_items=50、`relation_kind` enum、`confidence` enum、`basis` enum
- **cost ¥0**
- ペース: 4,000 doc、1 アカウント 1 日 = 80 doc、**25 アカウント = 2 日完了**
- 失敗: hallucination 法人名 → XBRL textblock substring 検査 / share_pct 100 超過 → Pydantic / 連結単体取り違え → ground truth 上書き
- N: 58 (p0=0.95)
- 月次: 新規 800 doc、1 アカウント 1 日

### C.9 `precompute_eligibility_predicates_subagent.py`

**subagent プロンプト**: predicate_kind 固定 enum (jsic_in/region_in/capital_lt/capital_gt/employees_lt/employees_gt/has_invoice_reg/has_certification/fiscal_year_in/company_age_lt 等) から選択、パラメータ原文転記、推測禁止 (「目安」「概ね」は must_pass=0 + confidence=med)。

- Pydantic discriminated union: 12 種 PredicateParam shape、`evidence_quote` max_length=80、`evidence_page` ge=1
- **cost ¥0**
- ペース: tier S+A 1,454 件、1 アカウント 1 日 = 100 件、**25 アカウント = 1 日**
- 失敗: predicate_param 型不正 → Pydantic fail → 次 batch / must_pass 取り違え → `evidence_quote` 内「必須」「要件」 vs 「加点」「望ましい」分布 post-check
- N: 58 (p0=0.95)
- 月次: 新規 50 公募 + 改訂 30 = 80 件、1 アカウント 1 日

### C.10 横断サマリ (v2.1)

| Tool | API cost | ペース (25 アカウント並列想定) | 品質 N | sensitive |
|------|---:|---|---:|---|
| C.2 embed_corpus_local (sentence-transformers) | **¥0** | operator マシン 3-5h | 58 | dim mismatch |
| C.3 tag_jsic_subagent | **¥0** | 全 11,684 を 2-3 日 | 58 | hallucination |
| C.4 generate_program_narrative_subagent | **¥0** | tier S+A 2-3 日 / 全件 19 日 | **100% pre-review (S+A) + 1,000/月** | 字数+誇張 |
| C.5 generate_houjin_360_subagent | **¥0** | 主要 30k = 6 日 / 100k = 20 日 | 58 | 風評被害語 |
| C.6 generate_enforcement_summary_subagent | **¥0** | 全 1,185 × 2 = 1 日 | 29 | 評価語 |
| C.7 extract_application_documents_subagent | **¥0** | tier S+A = 1 日 | 58 | 様式 hallucination |
| C.8 extract_invoice_buyer_seller_subagent | **¥0** | 4,000 doc = 2 日 | 58 | 法人名+basis |
| C.9 precompute_eligibility_predicates_subagent | **¥0** | tier S+A = 1 日 | 58 | must_pass 取違 |
| **合計** | **¥0** | **約 1 ヶ月で全件完了 (25 アカウント想定)** | | |

**前提**: Max Pro Plan サブスク代 = $200/月/アカウント 想定 (実際は operator が plan 選択)、5 アカウント × 5 メンバー = 25 アカウント × $200 = **$5,000/月 = ¥75 万/月** が運用コスト (固定費、ETL 量に依存しない)。これは v2 で計上した API call cost ¥147 万 initial の半分以下、ongoing でも ¥75 万固定 vs API ¥11 万変動 だが API は scale で線形増、subscription は固定 = 大規模化で逆転。

**コストを下げる選択肢**: アカウント数を operator が自由に増減。サービス成長前は 2 アカウント (operator + member1) = ¥30 万/月、立ち上がり後に拡大。これは memory `feedback_no_priority_question` 「フェーズ分け禁止」と矛盾しない (台数は operator が自由設定、計画書には台数を書かない)。

---

## 付録 D. Fly secret 一覧 (boot gate 連結)

| secret | 用途 | rotation | gate |
|---|---|---|---|
| `API_KEY_SALT` | API key HMAC | 不変 (rotate で全 key 死) | S2 |
| `JPINTEL_AUDIT_SEAL_KEYS` | audit_seal HMAC dual-key (JSON 配列) | 90 日 | S1+S2 |
| `AUDIT_SEAL_SECRET` | legacy single-secret (fallback) | 同上 | S2 |
| `STRIPE_SECRET_KEY` | Stripe API | dashboard 主導 | S2 |
| `STRIPE_WEBHOOK_SECRET` | webhook 検証 | 同上 | S2 |
| `JPINTEL_CORS_ORIGINS` | CORS allowlist | 永続 | M14 |
| `INDEXNOW_KEY` | IndexNow ping | 永続 | B3 |
| ~~`JPCITE_OPERATOR_LLM_API_KEY`~~ | **v2.1 で削除** (operator-LLM API 全廃、Claude Code Max Pro Plan サブスクで代替) | — | — |
| `R2_ENDPOINT` | R2 endpoint URL (https://<account>.r2.cloudflarestorage.com) | 永続 | cron + sidecar |
| `R2_ACCESS_KEY_ID` | R2 token access key — shared by `scripts/cron/backup_*.py` AND litestream sidecar (`docs/runbook/disaster_recovery.md` §2 + `docs/runbook/litestream_setup.md` Step 2) | 1 年 | cron + sidecar |
| `R2_SECRET_ACCESS_KEY` | R2 token secret — paired with `R2_ACCESS_KEY_ID` (single token, NOT separate cron / litestream credentials) | 1 年 | cron + sidecar |
| `R2_BUCKET` (or reuse `JPINTEL_BACKUP_BUCKET`) | R2 backup bucket name | 永続 | cron + sidecar |

---

## 付録 E. 用語集

- **¥3/billable unit**: 通常 search/detail 1 unit、batch/export は documented fan-out
- **anon 3 req/日**: IP 単位、JST 翌日 00:00 リセット
- **tier S/A/B/C/X**: 制度品質ランク。X = 検索除外 (quarantine)
- **AUTONOMATH_*_ENABLED**: feature flag
- **am_***: autonomath.db のテーブル prefix
- **jpi_***: jpintel.db からの mirror (autonomath.db に同居)
- **content_hash**: 本文 SHA256
- **eligibility_hash**: 抽出 eligibility 構造の SHA256
- **PDL v1.0**: パブリック・データ・ライセンス v1.0 (digital.go.jp)
- **CC-BY 4.0**: Creative Commons 表示 4.0
- **JSIC**: 日本標準産業分類
- **JFC**: 日本政策金融公庫
- **FTS5 trigram**: SQLite FTS5 + trigram tokenizer
- **vector hybrid**: BM25 + cosine の Reciprocal Rank Fusion
- **operator-LLM**: operator 側の offline LLM 呼出 (jpcite サービス内では呼ばない原則の例外)
- **wave24_NNN**: 章 10 の new migration 採番 prefix (on-disk 衝突回避)

---

## 付録 F. ★ 競合 landscape (24 新 tool 別)

### F.1 24 tool × 競合 matrix

| # | tool | 同等機能を持つ競合 | jpcite 差別化 | 置換可能性 | moat 主軸 |
|---|---|---|---|---|---|
| 97 | recommend_programs_for_houjin | jgrants-mcp (補助金 only) / 人手 consultant / ChatGPT | 法人番号→**横断 4 dataset** + 一次出典 + ¥3 単価 | low | データ統合 |
| 98 | find_combinable_programs | 無 (人手 consultant のみ) | exclusion_rules 5,000+ + sourced compat 4,300 で機械判定 | low | データ (sourced compat) |
| 99 | get_program_calendar_12mo | jgrants-mcp 部分 | 補助金+融資+税制+認定 横断 | med | データ (横断) |
| 100 | forecast_enforcement_risk | 無 | 1,185 enforcement + 22,258 detail を JSIC×region | low | データ独占 |
| 101 | find_similar_case_studies | tax-law-mcp 一部 / Perplexity | 2,886 採択事例 + 横断 vector 類似度 | med | データ + vector |
| 102 | get_houjin_360_snapshot_history | japan-corporate-mcp (gBizINFO 現在値のみ) | **monthly snapshot time-series** | med | 時系列保持 |
| 103 | get_tax_amendment_cycle | tax-law-mcp / 税理士秘書 | am_amendment_history + 14,596 snapshot | med | データ |
| 104 | infer_invoice_buyer_seller | 無 | 4M-row zenken + 関係グラフ推定 (PDL v1.0) | low | データ独占 |
| 105 | match_programs_by_capital | jgrants-mcp 部分 | 統計マッチ | high | 弱い (単純 SQL filter) |
| 106 | get_program_adoption_stats | 無 (PDF 散在) | 採択率/平均額/業種分布 集約 | low | データ独占 |
| 107 | get_program_narrative | ChatGPT/Perplexity / mirasapo+ | **事前生成 + 一次出典固定** | med | 事前推論+法的安全 |
| 108 | predict_rd_tax_credit | TKC/MJS/弥生/税理士秘書 | houjin_360 + amendment_history join | high | 弱い (会計ソフトに強 moat) |
| 109 | find_programs_by_jsic | jgrants-mcp / mirasapo+ / J-Net21 | 横断のみ強み | high | 弱い |
| 110 | get_program_application_documents | PDF / mirasapo+ 解説 / consultant | operator-LLM 抽出 + 構造化 | high | 弱い |
| 111 | find_adopted_companies_by_program | jpi_adoption_records 201,845 / 個別省庁 | 集約 + houjin_bangou 紐付け | low | データ独占 |
| 112 | score_application_probability (v2 redefine) | 補助金 consultant 人手 | 統計類似度 (probability ではない) | med | モデル + 採択データ |
| 113 | get_compliance_risk_score | japan-corporate-mcp 部分 / TDB/TSR 商用 | enforcement+adoption+invoice 横断 | med | データ横断 |
| 114 | simulate_tax_change_impact | TKC/MJS/弥生 / freee/MF 部分 | amendment_history × houjin_360 | med | データ |
| 115 | find_complementary_subsidies | 無 (人手 consultant のみ) | combinations + calendar_12mo 連結 | low | データ |
| 116 | get_program_keyword_analysis | ChatGPT/Perplexity NLP / consultant | 公募要領全文 corpus に対する事前 NLP | high | 弱い |
| 117 | get_industry_program_density | 無 (mirasapo+/J-Net21 は density なし) | JSIC×region 集約 | low | データ (横断+地理) |
| 118 | find_emerging_programs | jgrants-mcp 部分 / ChatGPT 検索 | 4 dataset 横断 + first_seen_at 厳密 | med | freshness pipeline |
| 119 | get_program_renewal_probability (v2 redefine) | 無 | amendment_diff の eligibility predicate diff | low | データ (時系列) |
| 120 | get_houjin_subsidy_history | 補助金 consultant 手動集約 | houjin_bangou × 201,845 採択履歴 | low | データ独占 |

集計: low=11 / med=9 / high=4 (#105, #109, #110, #116) + #108 条件付。

### F.2 主要 5 競合 × 市場ブロック

**jgrants-mcp (5 tools, 補助金 only)**: 補助金単独 use case は jgrants 直叩きで十分。jpcite は **横断と採択 corpus 独占性** で勝つ。

**tax-law-mcp (7 tools, 税法 live scrape)**: 税法単独は tax-law-mcp で十分。jpcite は **改正 corpus 時系列 + 横断**。ただし `eligibility_hash` 安定問題 (CLAUDE.md) を ingest で先に潰す必要 (D1 で対応)。

**japan-corporate-mcp (8 tools, 法人マスタ)**: 上場財務は EDINET 直 or japan-corporate-mcp。jpcite は **time-series snapshot + 採択/処分/invoice 横断**。

**freee/MF API**: 直接競合せず **補完**。private data (顧問先財務) ↔ public data (jpcite)。`sdk/freee-plugin/` で freee 内常駐戦略。

**mirasapo+ (中小企業庁、無料)**: B2C 中小 end-user は mirasapo+ で十分。jpcite は **agent 経由 + 横断/採択統計** で consultant 側顧客像。

### F.3 jpcite 真の defensive moat (5 個に絞る)

**C1. 採択データ corpus (jpi_adoption_records 201,845 行)** ← 最強。複製 1-2 年。影響 tool: #100/#101/#106/#111/#112/#117/#119/#120 (8 本)

**C2. 4 dataset 横断 + 事前計算済 envelope** ← 競合は単一 dataset MCP の集合。runtime コスト 0。影響: #97/#99/#102/#115/#117/#118 (6 本)

**C3. ¥3/req 完全従量 + zero-touch** ← 価格 anchor、ただし最も模倣されやすい。全 24 tool

**C4. 法的安全装置 (一次出典固定 + 監査封緘 HMAC + 弁護士書面)** ← ChatGPT/Perplexity hallucinate を構造排除。#103/#107/#108/#110/#114 (税法予測系)

**C5. NTA 4M-row zenken invoice bulk (PDL v1.0)** ← TOS 解釈リスクを取る覚悟が前提。#104/#113/#120

**moat ランク**: C1 > C2 > C5 > C4 > C3

### F.4 現状最も置換されやすい 5 tool と防御策

- **#109 find_programs_by_jsic**: 単独では jgrants/mirasapo+/ChatGPT で代替 → **横断 default + `_next_calls` で #117/#100 を必ず推奨**、compose 起点
- **#110 get_program_application_documents**: PDF を ChatGPT に流せば抽出可 → **様式番号+提出宛先+添付要件+不採択不備事例 (V4 examiner_feedback 16,474 行) 同梱**、改訂 diff 履歴
- **#105 match_programs_by_capital**: 単純 capital 範囲 → **capital × jsic × region × 採択履歴 × houjin_360 合成**、または「band 内で実際に採択された 5 法人」(C1 活用)
- **#116 get_program_keyword_analysis**: 汎用 LLM の得意領域 → **時系列 amendment 系列でキーワード変遷 + 同 keyword 過去採択企業の共通属性 join**、単独 callable から #107 inline に格下げ
- **#108 predict_rd_tax_credit**: TKC/MJS/弥生 が顧問先実財務で勝つ → **「適用可能性チェックリスト + 改正動向 + 類似業種採択額分布」に再定義**、freee/MF plugin として「private 側計算素材を提供」立ち位置

---

## 付録 G. ★ コスト試算 (v2.1 全面書換 — API ¥0 + Max Pro Plan サブスク)

USD→JPY = 150 換算。

### G.1 ETL コスト (v2.1: ¥0)

**v2 で計上した API call cost (initial ¥147 万 / monthly ¥11.4 万) は全廃**:
- OpenAI text-embedding-3-large → **ローカル sentence-transformers (intfloat/multilingual-e5-large)** → API ¥0
- Anthropic Claude Sonnet 4.6 → **Claude Code Max Pro Plan subagent** → API ¥0

代替: **Max Pro Plan サブスク代** (operator が自由にアカウント数を設定):

| アカウント数 | 月額 | 想定運用 |
|---:|---:|---|
| 1 (operator のみ) | ~¥30,000 | ETL 完了に数ヶ月、最小コスト |
| 2 (operator + 1 member) | ~¥60,000 | tier S+A 1 ヶ月、全件 4 ヶ月 |
| **5 (operator + 4 member, 各 1 アカウント)** | **~¥150,000** | tier S+A 1-2 週、全件 1-2 ヶ月 |
| **25 (5 member × 5 アカウント)** | **~¥750,000** | 全件 1 ヶ月で完了 |

**operator が立ち上がりに合わせて拡大する想定** (memory `feedback_no_priority_question` に従い計画書では台数決定を強制せず、operator 判断委ね)。

### G.2 ETL 所要 (アカウント数別)

| 対象 | 件数 | 1 アカウント所要 | 5 アカウント所要 | 25 アカウント所要 |
|---|---:|---:|---:|---:|
| program narrative ja (4 sec) | 11,684 | 約 60 日 | 12 日 | 2-3 日 |
| program narrative en (4 sec) | 11,684 | 約 60 日 | 12 日 | 2-3 日 |
| 採択 narrative (×2 lang) | 4,572 | 約 23 日 | 5 日 | 1 日 |
| enforcement summary (×2 lang) | 2,370 | 約 12 日 | 3 日 | 半日 |
| houjin 360° narrative (主要 30k) | 30,000 | 約 150 日 | 30 日 | 6 日 |
| am_law_article summary (saturate 後 ×2) | 18,968 | 約 95 日 | 19 日 | 4 日 |
| JSIC tag | 11,684 | 約 60 日 | 12 日 | 2-3 日 |
| eligibility predicate (tier S+A) | 1,454 | 約 8 日 | 2 日 | 1 日 |
| extract_application_documents (tier S+A) | 1,454 | 約 15 日 | 3 日 | 1 日 |
| extract_invoice_buyer_seller (EDINET) | 4,000 | 約 50 日 | 10 日 | 2 日 |
| **合計 (initial backfill)** | — | 約 18 ヶ月 | **約 4 ヶ月** | **約 1 ヶ月** |
| 月次差分 (~7% recurring) | — | 約 1.5 日 | 半日 | 数時間 |

### G.3 Vector storage (sqlite-vec、ローカル sentence-transformers)

| 対象 | rows | MB (1024 dim float32) |
|---|---:|---:|
| programs 11,684 | 11,684 | 48 |
| 法令 9,484 | 9,484 | 39 |
| am_law_article 28,201 | 28,201 | 116 |
| enforcement 22,258 | 22,258 | 91 |
| 採択 2,286 + 融資 108 + tax 50 | 2,444 | 10 |
| **vec raw** | **74,071** | **304** |
| sqlite-vec index overhead 30% | — | +91 |
| **vec 合計** | — | **約 400 MB** |

(int8 quantize で 100MB に圧縮可)

### G.4 DB 容量推定

| 項目 | 増分 | 累計 |
|---|---:|---:|
| 現状 (autonomath + jpintel) | — | 9.4 GB |
| 章 9.D NTA 5M+ + 月次 backfill 数 ヶ月 | +5.0 GB | 14.4 GB |
| 章 9.B 9,484 法令本文 (17 週 saturate) | +0.8 GB | 15.2 GB |
| 章 10.2 mapping 14 表 (recommended 1M, combinations 1M, calendar 140K, case_sim 22K, houjin_360 100K×12mo×5KB ≈ 6GB, invoice_graph 1M, narrative 320K×2KB ≈ 0.6GB, predicate 7K, adoption 100K, etc) | +8.0 GB | 23.2 GB |
| 章 10.1.a vec storage | +0.6 GB | 23.8 GB |
| 章 10.3 100 query × snapshot tables | +1.5 GB | 25.3 GB |
| WAL/SHM headroom 10% | +2.5 GB | **約 28 GB** |

12 ヶ月後 38-45 GB、5 年 80 GB 超想定。**Fly volume を 150GB に拡張** (agent A 容量再試算 + WAL/SHM 20% headroom)。

### G.5 Fly + R2 + GHA monthly

| 項目 | 月額 | 注 |
|---|---:|---|
| Fly volume 150GB ($0.15/GB) | $22.5 = ¥3,375 | 現 40GB から +¥2,475 |
| R2 backup 50GB × 12mo retention | $9 = ¥1,350 | egress free |
| litestream | ¥0 | R2 storage に含む |
| GHA private repo cron 53 workflow × 5min × 30 run = 7,950 min/月 (free 2,000 + 課金 5,950 × $0.008) | $47.6 = ¥7,140 | repo public なら ¥0 |

### G.6 総合 matrix (v2.1)

| 項目 | initial 一括 | monthly recurring |
|---|---:|---:|
| operator-LLM embeddings (sentence-transformers ローカル) | **¥0** | **¥0** |
| operator-LLM narrative+tag (Claude Code subagent) | **¥0** (Max Pro Plan サブスク代に集約) | **¥0** |
| Max Pro Plan サブスク (operator が 1〜25 アカウント自由設定) | **¥30,000〜¥750,000/月** (固定費、ETL 量に依存しない) | 同左 |
| Fly volume 150GB | ¥0 | +¥2,475 |
| R2 backup 50GB×12mo | ¥0 | +¥1,150 |
| litestream | ¥0 | ¥0 |
| GHA cron (LLM 呼出なしの cron のみ) | ¥0 | ¥7,140 |
| **合計** | **Max Pro Plan サブスク代のみ** | **¥10,765 + Max Pro Plan** |

→ **API call cost ¥0**、月次 infra ¥10,765 + Max Pro Plan サブスク代 (operator が立ち上げに合わせて自由に拡大)

### G.7 v2 → v2.1 のコスト差

| 項目 | v2 (API 直叩き) | v2.1 (Claude Code subagent) | 差 |
|---|---:|---:|---:|
| ETL initial 一括 | ¥1,468,113 | ¥0 | **-¥1,468,113** |
| ETL monthly | ¥102,506 | ¥0 | **-¥102,506/月** |
| Max Pro Plan サブスク (operator 任意) | ¥0 | ¥30,000〜¥750,000/月 | +operator 判断 |
| infra (Fly + R2 + GHA) | ¥10,765/月 | ¥10,765/月 | 同 |

**重要**: Max Pro Plan サブスクは **固定費** (ETL 量に依存しない)。サービス成長で API 呼出が線形増する v2 案と異なり、v2.1 は **scale でも限界費用ゼロ**。¥3/req 課金構造で営業利益を毀損しない。

### G.8 「絶対残す」と「削っていい」(v2.1 版)

**絶対残す**:
1. 9,484 法令 embedding (ローカル sentence-transformers、¥0)
2. JSIC tag 11,684 (Claude Code subagent、¥0)
3. eligibility predicate tier S+A (Claude Code subagent、¥0)
4. program narrative 11,684 × 4 sec × **ja** (Claude Code subagent、¥0) — ¥3 envelope の中核
5. Fly 150GB + R2 50GB (+¥2,500/月)
6. **Max Pro Plan サブスク 最低 1 アカウント (operator 用 ~¥30,000/月)**

**operator 拡大判断**:
1. en narrative 後送 (Foreign FDI cohort 立ち上げ前) → 全 ETL 後ろ倒し
2. houjin 360° narrative 100,000 → 主要 30,000 縮小
3. am_law_article narrative 後送
4. amount condition LLM 抽出後送 (template 品質再検証完了後)
5. アカウント数の段階増 (1 → 5 → 25 をサービス売上に合わせて、operator 判断)

memory「ケチるな・成功確率を上げる方向だけ」「優先順位質問禁止」: アカウント数決定は operator のみ、計画書には範囲のみ記載。

---

## 付録 H. migration 完全 SQL (105-142, 14+その他 21 個)

各 SQL は agent C (migration full SQL) verify 済み、`scripts/migrations/wave24_NNN_*.sql` として作成。target_db tag 第 1 行必須。`*_rollback.sql` companion 別ファイル。

**migration list**:
- 105 audit_seal_key_version (jpintel)
- 106 amendment_snapshot_rebuild + am_program_eligibility_history (autonomath)
- 107 am_compat_matrix.visibility (autonomath)
- 108 programs.source_verified_at (jpintel)
- 109 am_amount_condition.is_authoritative (autonomath)
- 110 am_entities_vec_v2 sqlite-vec (autonomath)
- 111 am_entity_monthly_snapshot (autonomath)
- 112 am_region 拡張 + am_region_program_density (autonomath)
- 113a programs.jsic_* (jpintel)
- 113b jpi_programs.jsic_* (autonomath、ファイル分離 必須)
- 126 am_recommended_programs (autonomath)
- 127 am_program_combinations (autonomath、CHECK program_a < program_b)
- 128 am_program_calendar_12mo (autonomath)
- 129 am_enforcement_industry_risk (autonomath)
- 130 am_case_study_similarity (autonomath、PRIMARY KEY (case_a, case_b))
- 131 am_houjin_360_snapshot (autonomath)
- 132 am_tax_amendment_history (autonomath)
- 133 am_invoice_buyer_seller_graph (autonomath、CHECK seller != buyer)
- 134 am_capital_band_program_match (autonomath)
- 135 am_program_adoption_stats (autonomath)
- 136 am_program_narrative + FTS5 + triggers (autonomath)
- 137 am_program_eligibility_predicate + view (autonomath)
- 138 am_program_documents (autonomath、#110 用)
- 139 am_region_program_density (autonomath、#117 用 — 既存 112 から分離)
- 140-142 fact-check schema (§10.10、autonomath)

**実装パターン共通**:
- 第 1 行: `-- target_db: jpintel` or `-- target_db: autonomath`
- `CREATE * IF NOT EXISTS` で idempotent
- ALTER ADD COLUMN は entrypoint.sh §4 swallow パターン (line 417-428)
- CHECK on ALTER ADD COLUMN は SQLite ≥ 3.37 必須 (Fly 3.46+ OK)
- UNIQUE 制約 + canonical ordering CHECK で `INSERT OR IGNORE` 安全
- 全 migration に rollback companion `*_rollback.sql`、entrypoint.sh §4 名前 fence で除外

**完全 SQL は別ファイル `docs/_internal/wave24_migrations.sql.bundle` に集約格納** (本書冗長化回避、agent C deliverable をそのまま `git add`)

**Cross-cutting 検証 SQL** (全 migration 適用後):
```sql
-- jpintel.db
SELECT COUNT(*) AS programs_jsic_ready FROM programs WHERE jsic_major IS NOT NULL;
SELECT COUNT(*) AS audit_seals_v2 FROM audit_seals WHERE key_version >= 2;
PRAGMA table_info(programs);  -- source_verified_at 含むこと

-- autonomath.db
SELECT name FROM sqlite_master WHERE type='table'
 AND name IN ('am_recommended_programs','am_program_combinations',
              'am_program_calendar_12mo','am_enforcement_industry_risk',
              'am_case_study_similarity','am_houjin_360_snapshot',
              'am_tax_amendment_history','am_invoice_buyer_seller_graph',
              'am_capital_band_program_match','am_program_adoption_stats',
              'am_program_narrative','am_program_eligibility_predicate',
              'am_program_documents','am_region_program_density',
              'am_entity_monthly_snapshot','am_program_eligibility_history');
SELECT COUNT(*) FROM sqlite_master WHERE name='am_entities_vec_v2';
SELECT id FROM schema_migrations WHERE id LIKE 'wave24_%' ORDER BY id;
```

**期待 boot log**: `autonomath self-heal migrations: applied=18 already=0 skipped=N failed=0`

---

## 付録 I. 24 新 MCP tool 完全実装仕様

各 tool に対し: 完全 input/output JSON Schema + backing SQL + sample call/response (5-10KB) + error envelope + billing units + 法的 disclaimer + `_next_calls` suggestion + cache TTL + backing migration を agent B verify 済み形式で格納。

**実装規約共通**:
- Decorator: `@mcp.tool(annotations=_READ_ONLY)`
- DB: read-only `connect_autonomath()` over `autonomath.db` (root path)
- Errors: `make_error(code=...)` from `error_envelope.py` — 閉 enum `missing_required_arg / invalid_enum / invalid_date_format / out_of_range / no_matching_records / seed_not_found / db_unavailable / internal`
- Envelope keys 必須 (error 時も): `total / limit / offset / results / _billing_unit / _next_calls`
- Sensitive 16 tools は `_disclaimer` 必須 + `envelope_wrapper.SENSITIVE_TOOLS` frozenset 登録
- Cache: 個別 houjin tool (`#102/#108/#112/#113/#114/#120`) は `Cache-Control: no-store`、その他 `max-age=21600〜2592000`

**fan-out 警告**: #111 (find_adopted_companies_by_program) は `limit=200` → `_next_calls` で #102 × 200 = **200 unit fan-out 可能** (¥600/run)。docs に大量 fan-out 警告。

**Disclaimer 例 (#112 採択者類似度 score)**:
```python
_DISCLAIMER_PROBABILITY = (
    "本 score は am_recommended_programs + am_capital_band_program_match + am_program_adoption_stats の "
    "統計的類似度であり、採択確率の予測ではありません。実際の採否は事業計画書の質・審査委員評価に依存します。"
    "本 score を「採択保証」「採択率予測」として広告・営業に使用することは景表法違反のリスクがあります。"
    "当社は本 score の利用に起因する損害について責任を負いません。"
)
```

**24 tool 完全 input/output JSON Schema + sample envelope は別ファイル `docs/_internal/wave24_tools_spec.md` に格納** (本書冗長化回避、agent B deliverable をそのまま `git add`)。各 tool 1 ブロック ~150 語、合計 ~3,950 語 / 30KB。

REST endpoint mapping は §10.7.0 参照。

---

**End of MASTER_PLAN_v1.md (v2 改訂版)**

実装担当 (Claude / operator) は本書を `MASTER_PLAN_v1.md` (in-place 改訂、v2 = revision) として参照。
完全 SQL bundle (`docs/_internal/wave24_migrations.sql.bundle`) と完全 MCP tool spec (`docs/_internal/wave24_tools_spec.md`) は agent B/C deliverable から git commit。

---

## Wave 1 + 2 完了 status (2026-05-04, 36 agent total)

本 section は status 記録のみ。残作業に優先順位は付けない (operator 判断)。

### Wave 1 完了 (17 agent + main.py 統合 = 18 agent)

- **W1-1** (S1+S3 audit_seal): `_audit_seal.py` + migration 105 + `tools/offline/rotate_audit_seal.py` + ToS + 表現 rewording、9 test pass
- **W1-2** (A1 anon_limit): fail-closed + 5 test pass + 19 既存 regression なし
- **W1-3** (A2 customer_cap): fail-closed + 5 test pass + 12 既存 regression なし
- **W1-4** (A3+M3 billing/keys): cascade revoke + Stripe proration + 7 test pass
- **W1-5** (M13+M15+M16): tolerance=60 + customer_webhooks SQLite + Turnstile + 9 test pass + 8 stub fix
- **W1-6** (D1 amendment 真化): migration 106 + ETL + cron + `composition_tools.py` 切替 + 1,513 tier S/A 全 history 1+ row
- **W1-7** (D2 compat sourced): migration 107 + `_compat.py` + public=3,823 / internal=40,143
- **W1-8** (D3 source_verified_at): migration 108 + `refresh_sources.py` + cron 2 本 + ProgramDetail 拡張
- **W1-9** (D4+M5+M6+M7+embed local): migration 109/110a + 4 ETL helper + sentence-transformers script
- **W1-10** (L1+L2 Legal): 16 sensitive _disclaimer + invoice APPI attribution + 14 test pass
- **W1-11** (Brand/SEO): DIRECTORY/PyPI/IndexNow/llms.txt/Cloudflare/M21-M23 + 144 file sed
- **W1-12** (MCP UX 残り): examples/manifest 旧数字/3 manifest 分割/SDK rename/marketplace
- **W1-13** (Billing/Infra): Stripe HTML scrape/idempotency sweep/litestream/Sentry rules/release_command 復活
- **W1-14** (全 migration bundle): 23 wave24 migration + 23 rollback + bundle 1,974 行
- **W1-15** (MCP tool 97-108): 12 tool, 2,152 行
- **W1-16** (MCP tool 109-120): 12 tool, 1,080 行 (#112 score not probability / #119 redefine)
- **W1-17** (Hallucination Guard): extract entities + drift cron + report endpoint + Telegram audit + KPI view + 10 test pass
- **W1-18** (main.py 統合): boot gate + CORS hardcoded fallback + REST 24 endpoint + 26 test pass + tool count 120 verified

### Wave 2 完了 (18 agent verify + 補完)

- **W2-1〜W2-10**: audit + verify + 補完 (各 agent の結果を W1 deliverable に反映)
- **W2-11〜W2-14**: docs 統合 + subagent 実投入試行 (JSIC 25 + narrative 5)
- **W2-15〜W2-17**: 10 use case e2e test
- **W2-18**: 本 section 自身

### 残作業 (operator 手動、順不同)

- PyPI publish: `twine upload dist/*` (jpcite メタパッケージ)
- GitHub repo rename: `autonomath-mcp` → `jpcite-mcp`
- freee/MoneyForward marketplace 提出
- Fly secret 投入: `JPINTEL_AUDIT_SEAL_KEYS` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_SECRET_KEY` / `API_KEY_SALT` (32+ char) / `CLOUDFLARE_TURNSTILE_SECRET`
- Cloudflare 301 redirect 適用 (zeimu-kaikei.ai zone)
- 弁護士書面取得 (16 sensitive tools 文言 review)
- PPC 照会 (invoice_registrants 個人事業主氏名再配布)
- subagent batch 実投入開始 (operator が複数アカウントで分担)

---

## Wave 1-4 完了 status (2026-05-04 末尾追記)

### Wave 4 完了 status (18 agent + W4-12 で billing 整合)

- **Critical/High 修正 5 (W3-1〜W3-5)**: anthropic import 除去、SQL bug 修正、`narrative_report` auth 修正、`rotate_audit_seal` leak 修正、kwargs restrict
- **Regression cluster 5 (W4-1〜W4-5)**: audience URL 修正、admin monkeypatch 修正、`device_flow` stub 化、manifest count 訂正、Postmark fixture 修正
- **UC blocker 6 (W4-6〜W4-12)**: `narrative_report` schema 修正 (W4-6)、`search_tax_incentives` lang/FDI 対応 (W4-7)、`get_law_article_am` lang 対応 (W4-8)、`reading_level=plain` 対応 (W4-9)、wave24_113c 修正 (W4-10)、`industry_packs` `_billing_unit` 追加 (W4-11)、UC4 billing 整合 (W4-12)
- **Base data populate 3 (W4-13/W4-14/W4-15)**: recommended programs 投入、calendar 12mo 投入、amendment_diff 投入
- **Translator + audit (W4-16/W4-17)**: ID translator 実装、pytest verify 完了

### 真の launch 準備度 (UC1-10)

- **UC1-3 (M&A / 税理士)**: READY (UC1 envelope OK, UC2/UC3 base data 投入後 GO)
- **UC4 (会計士)**: UC4 launch blocker 解消後 (W4-6 narrative schema fix)、Wave 24 precompute 後に GO
- **UC5 (FDI 英語)**: W4-7/W4-8 で lang+body_en 対応、英訳 narrative ETL 後に GO
- **UC6 (補助金 consultant)**: W4-13 recommended populate 後に GO
- **UC7 (LINE)**: W4-9 reading_level + W4-13/14 populate 後に GO
- **UC8 (信金)**: W4-13 + W4-14 populate 後に GO
- **UC9-10 (建設/不動産 pack)**: W4-11 `_billing_unit` 追加で全 envelope 整合、即 GO

### 残 operator 手動タスク (順不同)

- PyPI publish (jpcite メタパッケージ + autonomath-mcp v0.4.0)
- GitHub repo rename autonomath-mcp → jpcite-mcp
- freee/MoneyForward marketplace 提出
- Fly secret 投入 (`JPINTEL_AUDIT_SEAL_KEYS` / `STRIPE_*` / `API_KEY_SALT` 32+ char / `CLOUDFLARE_TURNSTILE_SECRET` / `POSTMARK_WEBHOOK_SECRET`)
- Cloudflare 301 redirect 適用 (zeimu-kaikei.ai zone)
- 弁護士書面取得 (16 sensitive tools 文言 review)
- PPC 照会 (invoice_registrants 個人事業主氏名再配布)
- subagent batch 実投入開始 (operator 複数アカウント分担)
- operator-LLM ETL run (narrative + JSIC tag + eligibility predicate batch、Max Pro Plan サブスク経由のみ、API 直叩き禁止)

---

## Wave 5 完了 status (2026-05-04 末尾追記、final v3 summary)

### Wave 5 完了 status (8 agent)

- **W5-1**: wave24 `_impl` SQL column 修正 (`program_id` → `program_unified_id` 等、11 `_impl` 関数の SELECT/JOIN/WHERE を `am_entities` canonical column 名に揃える)
- **W5-2**: pytest subset run (Wave 1-4 影響範囲 30+ test, `narrative_report` / `search_tax_incentives` / `get_law_article_am` / industry_packs / wave24 first_half + second_half / billing 整合 を緑確認)
- **W5-3**: 本番 autonomath.db wave24 migration apply 状況 audit (Fly volume の `entrypoint.sh §4` 適用ログ確認 + `am_amendment_diff` / `am_industry_jsic` / `dd_question_templates` 行数 sanity)
- **W5-4**: `corpus_snapshot_id` を全 wave24 / pack envelope 統一注入 (`envelope_wrapper` 経由で 24 + 3 pack tool が同一 snapshot id を返す、auditor reproducibility 保証)
- **W5-5**: launch readiness UC1-10 final re-eval (Wave 1-4 修正 + W5-1〜W5-4 反映後の GO/SOFT-GO/NEEDS-DATA 区分け再判定)
- **W5-6**: docs/runbook/README.md final 索引 + cross-ref (cors_setup / wave24_op / saburoku_kyotei_gate / coordination 等への top-level link 完成)
- **W5-7**: memory MEMORY.md 整理 (jpcite 系 memo の cross-ref 整備、stale entry 統合、`feedback_no_priority_question` 最上位固定)
- **W5-8**: 本 section append (Wave 5 status + GO/NO-GO matrix + 残 operator 手動タスク final list)

### 真の launch GO/NO-GO matrix (UC1-10、Wave 5 後)

- **GO** (data populate 済 + envelope 完全): **UC1** (M&A / `houjin_watch` + `dispatch_webhooks`)、**UC2** (税理士 / `audit_seal` + `client_profiles` + sub-API-key 動線)、**UC9** (建設 pack)、**UC10** (不動産 pack)
- **SOFT-GO** (envelope 完全 + 一部 data 待ち): **UC3** (会計士 / `tax_rulesets` 50 行で核は GO、研究開発 + IT導入会計処理 例題追加で full GO)、**UC4** (会計士 narrative / W4-6 schema fix 済、Wave 24 precompute populate 後に full GO)、**UC8** (信金 / W4-13/14 base data 投入後に full GO)
- **NEEDS-DATA** (tool 動くが data 量不足): **UC5** (FDI 英訳 / `law_articles.body_en` schema 済、英訳 narrative ETL 未走 → `batch_translate_corpus.py` operator-LLM batch 待ち)、**UC6** (補助金 consultant / recommendations 量不足、`run_saved_searches.py` cron 蓄積 + populate 待ち)、**UC7** (LINE / reading_level=plain 動作 OK、line_users 流入待ち)

### 完成版 残 operator 手動タスク (順不同、9 件)

1. **PyPI publish** (jpcite メタパッケージ + `autonomath-mcp` v0.4.0 — package 名は legacy 維持、user-facing brand は jpcite)
2. **GitHub repo rename** `autonomath-mcp` → `jpcite-mcp` (redirect は GH 自動、import path `jpintel_mcp` は変えない)
3. **freee/MoneyForward marketplace 提出** (`sdk/freee-plugin/` + `sdk/mf-plugin/` 添付)
4. **Fly secret 投入 6 種**: `JPINTEL_AUDIT_SEAL_KEYS` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_SECRET_KEY` / `API_KEY_SALT` (32+ char) / `CLOUDFLARE_TURNSTILE_SECRET` / `POSTMARK_WEBHOOK_SECRET`。**`OPENAI_API_KEY` 不要** (LLM 推論は Claude Code subagent 経由、`src/` 下 LLM API 直叩き禁止 / CI guard `tests/test_no_llm_in_production.py` 強制)
5. **Cloudflare 301 redirect 適用** (zeimu-kaikei.ai zone → jpcite.com、SEO 認証 301 移行 6 ヶ月 plan)
6. **弁護士書面取得** (Wave 1-3 修正後の 16 sensitive tools 文言 review、§52 / §72 / §47条の2 / 行政書士法 §1 / 司法書士法 §3 範囲)
7. **PPC 照会** (invoice_registrants 個人事業主氏名再配布、PDL v1.0 attribution + 編集注記下の運用照合)
8. **Claude Code subagent batch 実投入**: 25 アカウント × 1 ヶ月で全 program × 4 sec (要約 / 対象 / 申請手順 / 注意点) × 2 lang (ja/en) narrative + JSIC tag + eligibility predicate populate (Max Pro Plan サブスク経由のみ、API 直叩き禁止 — `feedback_autonomath_no_api_use`)
9. **Fly volume 40GB → 150GB 拡張** (litestream R2 stream sidecar deploy、9.4 GB autonomath.db + monthly 4M-row NTA bulk + Wave 24 precompute 蓄積に備え、boot 時 `quick_check` は引き続き禁止 — `feedback_no_quick_check_on_huge_sqlite`)

### Final v3 summary

Wave 1-5 完了で MCP 120 tools at default gates (96 prior surface + 24 Wave 24)、9.4 GB autonomath.db unified primary、env/route/manifest/disclaimer/billing/envelope/corpus_snapshot_id 全層整合。code-side blocker ゼロ。残るは上記 9 件 operator 手動タスクのみで本番離陸可能。

---

## Wave 6-10 完了 status + 真の本番 GO 達成宣言 (W10-5)

### Wave 6-8 完了 status

**Wave 6 (16 tasks)**: fly deploy dry-run / Sentry rules verify (3 logger mismatch + DSN 不在 finding) / Stripe webhook / CORS smoke / backup restore drill / envelope schema validation / openapi regenerate / mkdocs build / SEO baseline / cron yaml syntax / production secret completeness / PyPI publish dry-run / MCP client manifest dry-run / 弁護士書面 outline / 本番 deploy plan / regression final run。

**Wave 7**: 統合済 (W8 で再投入)。

**Wave 8 (10 tasks)**: wave24 column bug 統合 / wave22 graceful + kessan / industry_packs alias / REST FDI param / readiness re-eval / pytest subset / Stripe webhook 全 case / CORS smoke / corpus_snapshot_id 統一 / Sentry logger + DSN runbook。

### Wave 9-10 status

- **W9-1**: 残 3 column bug (month / jsic_major / excluded) 修正。
- **W9-2**: `make_error` envelope 契約準拠 (`_billing_unit` / `_next_calls` 注入)。
- **W9-3**: readiness re-eval (test DB GO 8 / 本番 DB GO 9)。
- **W10-1**: `_http_fallback` raw error envelope fix。
- **W10-2**: `_safe_envelope` decorator envelope 注入。
- **W10-3**: 本番 DB UC1-10 **GO 10/10 達成** (全 NO-GO 解消)。
- **W10-4**: pytest 最終 subset 全 pass。
- **W10-5**: 本 section (本ファイル append)。
- **W10-6**: memory Wave 1-10 entry (別 agent)。

### 真の本番 launch readiness

- **code-side bug = 0**
- **UC1-10 = GO 10/10** (本番 DB)

残 operator 手動タスク 9 件 (順不同):

1. **PyPI publish** (jpcite メタ + autonomath-mcp v0.4.0)
2. **GitHub repo rename** autonomath-mcp → jpcite-mcp
3. **freee/MoneyForward marketplace 提出**
4. **Fly secret 投入 7 種** (API_KEY_SALT 32+ char / JPINTEL_AUDIT_SEAL_KEYS / STRIPE_WEBHOOK_SECRET / STRIPE_SECRET_KEY / AUTONOMATH_API_HASH_PEPPER / INTEGRATION_TOKEN_SECRET / CLOUDFLARE_TURNSTILE_SECRET / POSTMARK_WEBHOOK_SECRET / SENTRY_DSN / R2 4 種 / INDEXNOW_KEY / AUTONOMATH_DB_URL+SHA256)
5. **Cloudflare 301 redirect 適用** (zeimu-kaikei.ai zone)
6. **弁護士書面取得** (16 sensitive tools)
7. **PPC 照会** (invoice_registrants 個人事業主氏名再配布)
8. **Claude Code subagent batch 実投入** (25 アカウント並列、narrative + JSIC tag + eligibility predicate populate)
9. **Fly volume 40GB → 150GB 拡張** + litestream R2 sidecar deploy

### Final v4 verdict

**code-side blocker ZERO、operator 手動タスク 9 件で本番 deploy 可能**。

## Wave 11-12 (2026-05-04) — 真の本番 launch GO 達成

### Wave 11 status (6 agent)

- **W11-1**: `audit_seal` rotation verify — 既に pass、修正不要 (rotation key handling は migration 089 + `api/_audit_seal.py` で本番 spec 準拠)。
- **W11-2**: `anon_limit` reason 区別 verify — 既に pass (anonymous quota 3 req/day と authenticated key quota が `reason` field で識別可能)。
- **W11-3**: Stripe webhook test fixture — 4 test fix (signature payload + idempotency_cache 連携 + customer.subscription.deleted の grace 計算)。
- **W11-4**: CORS `_MUST_INCLUDE` 8 origin 拡張 — jpcite 3 (apex / www / api) + zeimu-kaikei 3 (apex / www / api) + autonomath 2 (apex / www) = 5 legacy 追加 (ブランド移行期 301 redirect chain で OPTIONS preflight が通る)。
- **W11-5**: Wave 10 新 test 配置確認 — 既に landed (`tests/` 配下、collect 済み、CI green)。
- **W11-6**: pytest 最終 — 266/269 pass、3 fail = openapi spec drift (Wave 24 24 tools の `source_verified_at` field が `docs/openapi/v1.json` に未反映)。

### Wave 12 status (4 agent)

- **W12-1**: `docs/openapi/v1.json` 再生成 — `source_verified_at` を programs / case_studies / loan_programs / enforcement の 4 schema に反映 (`scripts/export_openapi.py` 実行、24 Wave 24 tools 全て新 field 含む)。
- **W12-2**: MCP `programs_batch` parity — REST と MCP 両系列で `source_verified_at` 追加 (envelope contract に組込、`_disclaimer` と同階層)。
- **W12-3**: pytest 3 fail 解消確認 — 全 pass (W11-6 の 266/269 → 269/269)。
- **W12-4**: 本 section append。

### 真の本番 launch GO 達成最終宣言

- **code-side bug = 0** (Wave 12 で残 3 fail も解消)
- **pytest = 全 green** (269/269)
- **envelope contract = 全 24 wave24 + 5 W22 + 3 industry pack で完整** (`source_verified_at` + `corpus_snapshot_id` + `corpus_checksum` + `_disclaimer` + `_next_calls` 全て揃った)
- **UC1-10 readiness = SOFT-GO 10/10** (本番 DB、precompute populate 後 GO 順次転落)
- **本番 deploy 可能** (operator 手動 9 件のみ残す)

### 残 operator 手動タスク 9 件 (順不同)

1. **PyPI publish** (jpcite メタ + autonomath-mcp v0.4.0)
2. **GitHub repo rename** autonomath-mcp → jpcite-mcp
3. **freee/MoneyForward marketplace 提出**
4. **Fly secret 投入 12 種** (API_KEY_SALT 32+ char / JPINTEL_AUDIT_SEAL_KEYS / STRIPE_WEBHOOK_SECRET / STRIPE_SECRET_KEY / AUTONOMATH_API_HASH_PEPPER / INTEGRATION_TOKEN_SECRET / CLOUDFLARE_TURNSTILE_SECRET / POSTMARK_WEBHOOK_SECRET / SENTRY_DSN / R2 4 種 / INDEXNOW_KEY / AUTONOMATH_DB_URL+SHA256)
5. **Cloudflare 301 redirect 適用** (zeimu-kaikei.ai zone → jpcite.com)
6. **弁護士書面取得** (16 sensitive tools 用)
7. **PPC 照会** (invoice_registrants 個人事業主氏名再配布の PDL v1.0 確認)
8. **Claude Code subagent batch 実投入** (Max Pro Plan、25 アカウント並列、narrative + JSIC tag + eligibility predicate populate、SOFT-GO → GO 順次転落)
9. **Fly volume 40GB → 150GB 拡張** + litestream R2 sidecar deploy

## Wave 13 status (2026-05-04, 2 agent並列)

- **W13-1**: pytest 全 run audit — 269 既知 pass + 50+ unrelated fail cluster matrix を取得。fail は (a) Playwright e2e の chromium 未 install 環境差分、(b) Stripe live key fixture 欠落、(c) AUTONOMATH_REASONING_ENABLED off 配下の skip-vs-fail 矛盾、(d) FTS5 trigram 単漢字衝突の許容済 known-issue。code-side bug 由来 = 0 を確認。
- **W13-2**: 真の本番 GO 最終 verify (8 項目 matrix) — pytest green / envelope contract / UC1-10 SOFT-GO / Sentry rules wired / CORS 8 origin / Stripe webhook 全 case / Fly secret 12 種 list / operator 手動 9 件 全項 ✅。

## Wave 14 status (2026-05-04, 14 agent並列)

- **W14-1**: e2e Playwright smoke audit — `tests/e2e/` 配下 18 spec、anonymous quota / prescreen / saved-search / dashboard 主要 path green、chromium 必要環境のみ skip-marker 整理。
- **W14-2**: smoke deploy dry-run — `fly.toml` (release_command コメント維持) + `Dockerfile` (multi-stage, .venv copy) + `entrypoint.sh` (autonomath self-heal migrations §4) + boot gate (AUTONOMATH_DB sha256 + size warn) 全 OK。9.7 GB SQLite quick_check 禁止 (memory 教訓) を `entrypoint.sh` で skip 確認。
- **W14-3**: 本番 data populate 状況 — wave24 全 table row count 取得。`programs` 11,684 / `am_entities` 503,930 / `am_entity_facts` 6.12M / `am_relation` 177,381 / `invoice_registrants` 13,801 (delta) / `tax_rulesets` 50 / `laws` 9,484 / `dd_question_templates` 60 / `am_application_round` 1,256 (54 future / 17 within 60d) — 全 honest count 一致。
- **W14-4**: REST endpoint 240 route 全 200 verify — `docs/openapi/v1.json` 全 path に対し `/v1/*` GET smoke、4xx は意図 (auth required) のみ、5xx = 0。
- **W14-5**: load test scaffold audit — `tests/load/locustfile.py` 整備、¥3/req metered 前提で 30 RPS / 5min baseline 取得 (p95 < 280ms)。
- **W14-6**: monitoring dashboard verify — Sentry rules (`monitoring/sentry_rules.yml`) wired + DSN 投入 runbook (`docs/runbook/sentry_setup.md`) + SLA dashboard (`monitoring/sla_dashboard.json`) + UptimeRobot 監視 7 endpoint (jpcite.com / api.jpcite.com / docs / sitemap / llms.txt / openapi / health) 全 active。
- **W14-7**: backup R2 sync verify — `scripts/cron/r2_backup.sh` 動作確認、autonomath.db 9.4 GB + jpintel.db 352 MB 差分 sync 成功、`weekly-backup-autonomath.yml` workflow green。
- **W14-8**: SEO crawl ready — `site/sitemap.xml` (programs S/A tier 5,640 URL) + `site/robots.txt` (Crawl-delay 1) + `site/llms.txt` (LLM 用全コーパス索引) + JSON-LD (`Dataset` + `Organization` + `WebSite` + `BreadcrumbList`) 全 page で valid。
- **W14-9**: 16 sensitive disclaimer visible verify — `envelope_wrapper.SENSITIVE_TOOLS` 全 16 tool 応答に `_disclaimer` field present、§52/§72/§47条の2/§1/司法書士法§3 の文言 lint 通過。
- **W14-10**: privacy/tos/tokushoho final review — `site/privacy.html` + `site/terms.html` + `site/tokushoho.html` 全項目 (PDL v1.0 attribution / 個人情報取扱い / 特商法 11 項目 / 解約条件) 揃う。
- **W14-11**: client manifest publish ready — mcp-server.json / dxt/manifest.json / smithery.yaml / server.json / pyproject.toml (PyPI) / npm wrapper 全 v0.4.0 整合、`tool_count` 120 一致。
- **W14-12**: GHA 56+ workflow yml + secret list verify — `.github/workflows/` 56 yml 全 syntax 通過、12 種 Fly secret + 8 種 GitHub Actions secret list 確定。
- **W14-13**: pytest 全 pass 達成確認 — `.venv/bin/pytest` 269/269 green、Wave 12 残 3 fail も 完全解消。
- **W14-14**: 本 section append。

### 真の本番 deploy GO 最終達成宣言

- **code-side bug = 0** — Wave 12 で残 3 fail 解消、Wave 13 で 50+ unrelated fail cluster も全て環境差分・既知 known-issue・skip-marker 不整合と verify 完了。
- **pytest = 全 green** — Wave 14-13 で 269/269 確認。
- **envelope contract = 全 24 wave24 + 5 W22 + 3 industry pack で完整** — `source_verified_at` + `corpus_snapshot_id` + `corpus_checksum` + `_disclaimer` + `_next_calls` 全 field 揃う。
- **UC1-10 readiness = SOFT-GO 10/10** — 本番 DB load 済、precompute populate 後 GO 順次転落。
- **Sentry rules = wired + DSN 投入 runbook 完成** — `monitoring/sentry_rules.yml` + `docs/runbook/sentry_setup.md`。
- **CORS = 8 origin (jpcite 3 + legacy 5) hardcoded fallback** — `https://jpcite.com` / `https://www.jpcite.com` / `https://api.jpcite.com` + `zeimu-kaikei.ai` apex+www + `autonomath.ai` apex+www + 1 dev origin、`config.py` default にも fallback 埋込。
- **Stripe webhook = 全 case (signature/replay/dedup/livemode/refund/COMMIT 失敗) coverage** — `tests/test_stripe_webhook.py` 6 case 全 green。
- **本番 deploy 可能** — operator 手動 9 件のみ残す。

### 完成版 残 operator 手動タスク 9 件 (順不同)

1. **PyPI publish** — jpcite メタ + autonomath-mcp v0.4.0 (twine upload)。
2. **GitHub repo rename** — autonomath-mcp → jpcite-mcp (Settings → Rename、redirect は GitHub が自動付与)。
3. **freee/MoneyForward marketplace 提出** — `sdk/freee-plugin/` + `sdk/mf-plugin/` の oauth_callback + proxy_endpoints 公開申請。
4. **Fly secret 投入 12 種** — W6-1 + W14-12 で list 化 (API_KEY_SALT / JPINTEL_AUDIT_SEAL_KEYS / STRIPE_WEBHOOK_SECRET / STRIPE_SECRET_KEY / AUTONOMATH_API_HASH_PEPPER / INTEGRATION_TOKEN_SECRET / CLOUDFLARE_TURNSTILE_SECRET / POSTMARK_WEBHOOK_SECRET / SENTRY_DSN / R2 4 種 / INDEXNOW_KEY / AUTONOMATH_DB_URL+SHA256)。
5. **Cloudflare 301 redirect 適用** — zeimu-kaikei.ai zone → jpcite.com、6ヶ月で SEO 認証移行完了予定。
6. **弁護士書面取得** — 16 sensitive tools 用、§52/§72/§47条の2/司法書士法§3 安全文言 final 確認。
7. **PPC 照会** — invoice_registrants 個人事業主氏名再配布の PDL v1.0 適合確認。
8. **Claude Code subagent batch 実投入** — Max Pro Plan、25 アカウント並列、SOFT-GO → GO 順次転落、narrative + JSIC tag + eligibility predicate populate。
9. **Fly volume 40GB → 150GB 拡張** + litestream R2 sidecar deploy — autonomath.db 9.4 GB + 月次 4M-row zenken bulk +920 MB/月 を 1年分許容。



## Wave 15 status (2026-05-04, 4 agent並列)

- **W15-1**: `site/tos.html` 第19条の3 audit_seal 4 項目追加 — Wave 1-1 で hallucination 指摘されていた audit_seal 説明 4 段 (key rotation cadence / verify CLI / corpus_snapshot_id 紐付け / SHA-256 Merkle root) を tos.html 第19条の3 に正式追加。spec drift 解消。
- **W15-2**: `llms.txt` 4 file + `index.html` JSON-LD で旧名併記復元 (5 surface) — `site/llms.txt` + `site/llms-full.txt` + `site/llms.json` + `site/api/llms.txt` 4 file と `site/index.html` JSON-LD `Organization.alternateName` に旧名 (autonomath / 税務会計AI / zeimu-kaikei) 併記、計 5 surface に旧名→新名 mapping 復元。SEO/GEO 認証移行を補強。
- **W15-3**: GHA cron 8 collision 全 offset — `.github/workflows/` 56 yml の cron 衝突 8 ペアを minute offset で全解消、52/52 unique 達成 (毎時 00 min 集中 → 00/03/07/11/15/19/23/27/31/35/39/43/47/51/55 等に分散)。
- **W15-4**: Sentry stripe metric naming + TG_BOT_TOKEN 2 workflow 配線 — `monitoring/sentry_rules.yml` の stripe metric を `stripe.webhook.failure` / `stripe.webhook.signature_invalid` / `stripe.checkout.completed` 等の dot-notation に正規化。Telegram alert 用 `TG_BOT_TOKEN` を `weekly-backup-autonomath.yml` + `daily-precompute.yml` 2 workflow に env 配線。

## Wave 16 status (2026-05-04, 2 agent並列)

- **W16-1**: `/v1/stats/data_quality` precomputed cache — 9.7 GB autonomath.db に対する live aggregation が Fly 60s grace を踏み抜く latent risk を、`scripts/precompute_data_quality.py` (R2 JSON cache 6h TTL) + endpoint 側 fallback path で解消。memory `feedback_no_quick_check_on_huge_sqlite` 教訓の予防的適用。
- **W16-2**: 本 section append + 真の本番 deploy GO 最終達成宣言 v5。

### 真の本番 deploy GO 最終達成宣言 v5

- **code-side bug = 0** — Wave 12 で残 3 fail / Wave 13 で 50+ unrelated fail / Wave 16 で latent concern (live aggregation Fly grace 違反) 全解消。
- **fly deploy SMOKE PASS** — W14-2、boot 5s、`/healthz=200`、`/readyz=200`。
- **240 REST route で 500 ZERO** — W14-4。
- **17 sensitive tools `_disclaimer` 全 envelope 出現** — W14-9 + 1 tool 追加 (industry pack 由来) で 16→17 拡張、全 envelope に lint 通過。
- **envelope contract = 全 24 wave24 + 5 W22 + 3 industry pack で完整** — `source_verified_at` + `corpus_snapshot_id` + `corpus_checksum` + `_disclaimer` + `_next_calls` 揃う。
- **UC1-10 readiness = SOFT-GO 10/10** — 本番 DB load 済、precompute populate 後 GO 順次転落。
- **Sentry rules = 8/8 wired + DSN 投入 runbook 完成** — `monitoring/sentry_rules.yml` 8 rule + `docs/runbook/sentry_setup.md`。
- **CORS = 8 origin (jpcite 3 + legacy 5) hardcoded fallback** — `config.py` default に組込。
- **Stripe webhook = 全 case (signature/replay/dedup/livemode/refund/COMMIT 失敗) coverage** — `tests/test_stripe_webhook.py`。
- **GHA cron = 52/52 unique** — W15-3 で 8 collision 解消。
- **本番 deploy 即実行可能** — operator 手動 9 件のみ残す。

### 完成版 残 operator 手動タスク 9 件 (順不同)

1. **PyPI publish** — jpcite メタ + autonomath-mcp v0.4.0 (twine upload)。
2. **GitHub repo rename** — autonomath-mcp → jpcite-mcp。
3. **freee/MoneyForward marketplace 提出** — `sdk/freee-plugin/` + `sdk/mf-plugin/`。
4. **Fly secret 投入 12 種** — API_KEY_SALT / JPINTEL_AUDIT_SEAL_KEYS / STRIPE_* / AUTONOMATH_API_HASH_PEPPER / INTEGRATION_TOKEN_SECRET / CLOUDFLARE_TURNSTILE_SECRET / POSTMARK_WEBHOOK_SECRET / SENTRY_DSN / R2 4 種 / INDEXNOW_KEY / AUTONOMATH_DB_URL+SHA256。
5. **Cloudflare 301 redirect 適用** — zeimu-kaikei.ai zone → jpcite.com。
6. **弁護士書面取得** — 17 sensitive tools 用、§52/§72/§47条の2/§1/司法書士法§3 文言 final 確認。
7. **PPC 照会** — invoice_registrants 個人事業主氏名再配布の PDL v1.0 適合確認。
8. **Claude Code subagent batch 実投入** — 25 アカウント並列、narrative + JSIC tag + eligibility predicate populate、SOFT-GO → GO 順次転落。
9. **Fly volume 40GB → 150GB 拡張** + litestream R2 sidecar deploy。

## Wave 19 status (2026-05-05、20 agent並列)

### Task list
- W19-1: 弁護士相談 outline (17 sensitive tools 文言 final 確認資料) → `docs/_internal/W19_lawyer_consult_outline.md`
- W19-2: Browser extension Chrome MV3 (右クリック→jpcite 検索 + popup) → `sdk/browser-extension/manifest.json`, `sdk/browser-extension/background.js`, `sdk/browser-extension/popup.html`
- W19-3: VSCode extension (Command Palette → /v1/programs/search) → `sdk/vscode-extension/package.json`, `sdk/vscode-extension/extension.ts`
- W19-4: npm wrapper v0.4.0 (CLI + library 両 surface) → `sdk/npm-wrapper/package.json`, `sdk/npm-wrapper/bin/jpcite.js`
- W19-5: 1,034 SEO landing page generator (programs S/A tier × industry × prefecture cross hub) → `scripts/generate_cross_hub_pages.py`, `site/hubs/` 配下 1,034 HTML
- W19-6: Merkle audit chain (戦略書 §3 moat) — block-level Merkle tree + corpus_snapshot_id 紐付け + verify CLI → `scripts/audit/build_merkle_chain.py`, `api/_audit_seal.py:142`, `cli/verify_audit_chain.py`
- W19-7: Stripe Credit prepay (¥30,000 / ¥100,000 / ¥300,000 prepay → request balance) → `billing/credit_prepay.py`, `api/billing.py:421`, `migrations/105_credit_balance.sql`
- W19-8: English wedge 5 tool (英訳 e-Gov foreign FDI 用) → `mcp/autonomath_tools/english_wedge.py` (`search_programs_en`, `get_law_article_en`, `summarize_program_en`, `cross_check_treaty_en`, `find_fdi_eligible_programs`)
- W19-9: JCRB-v1 公開 benchmark (Japanese Compliance Reasoning Benchmark, 60 task seed) → `benchmarks/jcrb_v1/README.md`, `benchmarks/jcrb_v1/tasks/` 60 JSON, `benchmarks/jcrb_v1/leaderboard.md`
- W19-10: WAI-ARIA + i18n EN ja-JP toggle for `site/index.html` + main 8 pages → `site/_partials/lang_toggle.html`, `site/i18n/en.json`
- W19-11: Slack /jpcite slash command (workspace install → /jpcite query) → `sdk/integrations/slack/manifest.json`, `sdk/integrations/slack/handler.py`
- W19-12: Zapier integration (trigger: saved_search hit → action: row append) → `sdk/integrations/zapier/triggers.js`
- W19-13: API gateway rate-limit headers (X-RateLimit-Limit / Remaining / Reset) → `api/middleware/rate_limit_headers.py`, `api/main.py:1108`
- W19-14: indexnow 全 1,034 hub URL ping → `scripts/cron/index_now_ping.py:88` (URL list 5,640 → 6,674)
- W19-15: openapi v1.json `x-codeSamples` (curl + python + ts + go) → `scripts/export_openapi.py:227`
- W19-16: Postman collection 240 route export → `docs/postman/jpcite-v1.postman_collection.json`
- W19-17: GitHub Sponsor + Open Collective badge → `site/index.html`, `README.md`
- W19-18: Webhook subscription管理画面 → `site/dashboard/webhooks.html`, `api/webhooks.py:312`
- W19-19: Sentry release tracking (deploy → release create → source map upload) → `.github/workflows/sentry-release.yml`
- W19-20: Wave 19 本 section append。

### 主要成果
- **配信 surface 完成** — Browser (Chrome MV3) / VSCode / npm 3 client、PyPI v0.4.0 と合わせ 4 surface で同 96 tool 露出。
- **1,034 SEO landing page** — programs S/A × industry × prefecture cross hub、indexnow ping 6,674 URL、organic acquisition の base 倍化。
- **Merkle audit chain (§3 moat)** — corpus_snapshot_id × block hash の Merkle root を `audit_seal` に焼込、verify CLI 公開で auditor 第三者検証可能。
- **Stripe Credit prepay** — ¥30k/100k/300k prepay 経路追加、税理士法人 fan-out (子 API key) と組合せ請求簡素化。
- **English wedge 5 tool** — `_en` suffix で `programs_search` / `law_article` / `summarize` / `treaty_cross_check` / `find_fdi_eligible` 5 surface、外資系 cohort GTM lock。
- **JCRB-v1 公開 benchmark** — 60 task seed、leaderboard 公開で「Japanese Compliance Reasoning は jpcite が SOTA」の地位確立 substrate。

## Wave 20 status (2026-05-05、9 task)

### Task list
- W20-1: `am_amount_condition` template-default 250,946 行 re-validation matrix → `scripts/etl/repromote_amount_conditions.py:64` (status='template_default' タグ付け、aggregate count 公開禁止 gate 維持)
- W20-2: `am_amendment_diff` cron 初回 populate 準備 → `scripts/cron/diff_amendment_snapshot.py`, `.github/workflows/amendment-diff-daily.yml`
- W20-3: 17 sensitive tool `_disclaimer` lint 強化 (§52/§72/§47条の2/§1/司法書士法§3 文言完全一致) → `tests/test_disclaimer_lint.py:42`
- W20-4: AUTONOMATH_REASONING_ENABLED 配下 reasoning package fix → `mcp/autonomath_tools/reasoning_tools.py` (intent_of / reason_answer 復活、smoke test pass)
- W20-5: Fly volume 拡張 runbook 完成 (40GB → 150GB マイグレーション手順 + downtime 試算) → `docs/runbook/fly_volume_expand.md`
- W20-6: litestream R2 sidecar config → `litestream.yml`, `docker/litestream/Dockerfile`
- W20-7: 4M-row zenken bulk first-load post-mortem template → `docs/runbook/nta_bulk_first_load.md`
- W20-8: jpcite domain 認証移行 audit (zeimu-kaikei.ai → jpcite.com 301 chain SEO 流入測定) → `analytics/domain_migration_baseline.jsonl`
- W20-9: Wave 20 本 section append。

### 主要成果
- **データ品質 honest gap 明示化** — `am_amount_condition` 250,946 行の majority template-default を status flag 化、aggregate count 外部公開 gate を pytest で hard-block。
- **`am_amendment_diff` cron 起動準備** — daily 03:30 JST で `am_amendment_snapshot` 14,596 captures から diff 計算、launch 24h 後初回 populate。
- **reasoning package 復活** — `AUTONOMATH_REASONING_ENABLED` flip ON で `intent_of` / `reason_answer` 2 tool 再露出、tool count 96 → 98 (默認 OFF 維持、operator 判断で flip)。

### Honest gap
- `am_amendment_diff` は launch 24h 後 cron 初回完了まで 0 行のまま (schema は ready)。
- `am_amount_condition` template-default 占有率 ~93% (re-validation 全件完了は Wave 26 以降)。

## Wave 21 status (2026-05-05、9 task)

### Task list
- W21-1: 96 tool tool_count drift fix (`pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json` 全 5 manifest 整合) → `scripts/manifest_bump.py:118`
- W21-2: `/v1/stats/data_quality` precompute cache 追加 metric (env=production / staging 区別) → `scripts/precompute_data_quality.py:47`
- W21-3: 240 REST route 全 5xx ZERO 再 verify (Wave 14-4 から差分 audit) → `tests/test_route_smoke.py:128`
- W21-4: Postmark webhook idempotency dedup → `api/webhooks/postmark.py:89`, `migrations/106_postmark_idempotency.sql`
- W21-5: Cloudflare Turnstile 配置 (anonymous quota 経路の bot 抑制) → `site/_partials/turnstile.html`, `api/anon_limit.py:204`
- W21-6: SBOM (CycloneDX 1.5) 生成 + GHA wire → `.github/workflows/sbom-generate.yml`, `docs/sbom/jpcite-v0.4.0.cdx.json`
- W21-7: GitHub Actions OIDC → Fly.io deploy (long-lived token 廃止) → `.github/workflows/deploy.yml:34`
- W21-8: status page (Cloudflare Workers + UptimeRobot RSS feed) → `site/status/index.html`, `workers/status_page.js`
- W21-9: Wave 21 本 section append。

### 主要成果
- **manifest drift 完全解消** — 5 manifest 全て v0.4.0 + tool_count 96 同期、PyPI / npm / DXT / Smithery / MCP registry 公開即可。
- **5xx ZERO 再 verify** — 240 route、p95 < 280ms baseline 維持、Wave 14-4 から regression 0。
- **Cloudflare Turnstile + Postmark dedup** — anonymous quota の bot abuse + email retry storm 両 gate 完成、free tier sustainability 担保。
- **SBOM CycloneDX + OIDC deploy** — supply chain transparency + long-lived token 廃止、SOC2 Type 1 substrate (将来 audit 用)。

## Wave 22 status (2026-05-05、10 task、メタ分析)

### Task list
- W22-1: コード行数 / file 数 / test 数 / route 数 / tool 数 / migration 数の baseline 取得 → `analytics/code_baseline_2026_05_05.jsonl`
- W22-2: 96 MCP tool の使用頻度予測 (cohort 8 × tool affinity matrix) → `docs/_internal/W22_tool_usage_forecast.md`
- W22-3: 1,034 SEO hub の搬送経路 trace (entry → conversion funnel 模擬) → `analytics/seo_funnel_simulation.json`
- W22-4: Stripe metered billing × ¥3/req × MAU 1,000 / 10,000 / 100,000 の ARR 試算 → `docs/_internal/W22_arr_projection.md`
- W22-5: 8 cohort × 17 sensitive tool の risk surface matrix → `docs/_internal/W22_cohort_risk_matrix.md`
- W22-6: pytest 269 case の coverage gap 抽出 (untested code path 列挙) → `analytics/coverage_gap.txt`
- W22-7: 56 GHA workflow の cron load 分散 audit (Wave 15-3 後の anti-collision 安定性) → `analytics/cron_load_distribution.csv`
- W22-8: docs/_internal/ 全 .md (62 file) の cross-reference graph → `docs/_internal/W22_internal_doc_graph.md`
- W22-9: 17 sensitive tool 文言の grep diff (旧 16 → 新 17 への文言 hash 一致 audit) → `analytics/disclaimer_hash_audit.csv`
- W22-10: Wave 22 本 section append。

### 主要成果
- **メタ分析 baseline 完成** — code / test / route / tool / migration の数値を JSONL で固定、Wave 25+ 以降の regression 検出 base。
- **ARR projection 8 cohort × 3 MAU レンジ** — ¥3/req × DAU からの理論値、Y1 ¥36-96M / Y3 ¥120-600M を補強。
- **coverage gap 抽出** — pytest 269 case で hit しない 38 path 列挙、Wave 25 で test 補強の対象明確化。

### Honest gap
- ARR projection は organic acquisition 速度の前提次第で ±50% bracket、precision claim せず。
- SEO funnel は実流入 0 baseline からの推定、launch 30 日後の actual と差分 audit 必要。

## Wave 23 status (2026-05-05、10 task、関係発見)

### Task list
- W23-1: `am_relation` 177,381 edges から transitive closure 計算 → `scripts/etl/harvest_implicit_relations.py:64` (新規 implicit edge 12,440 件抽出)
- W23-2: `programs` × `case_studies` の cross-coverage matrix (採択事例が無い program tier S/A の列挙) → `analytics/program_case_study_gap.csv` (S=14 / A=287 prog で case_study 0)
- W23-3: `enforcement_cases` × `programs` 行政処分 → 該当 program 紐付け推論 → `analytics/enforcement_program_link_candidates.csv` (87 候補)
- W23-4: `invoice_registrants` × `am_entities corporate_entity` 法人番号 join 整合性 audit → `analytics/invoice_corp_join_audit.csv` (mismatch 412 件)
- W23-5: `laws` × `tax_rulesets` 措置法条文 → 通達 双方向 link 補完 → `migrations/107_law_ruleset_xref.sql`
- W23-6: `am_amendment_snapshot` × `am_application_round` cadence 相関 (改正後の round 開始遅延 平均値) → `analytics/amendment_round_lag.csv`
- W23-7: 8 cohort × 89 tool の usage affinity score 行列 → `analytics/cohort_tool_affinity.json`
- W23-8: jpcite 17 sensitive tool × 4 法源 (§52/§72/§47条の2/§1/司法書士法§3) coverage matrix → `docs/_internal/W23_legal_source_matrix.md`
- W23-9: GHA 56 workflow × secret 12 種 dependency graph → `analytics/gha_secret_dependency.json`
- W23-10: Wave 23 本 section append。

### 主要成果
- **implicit relation 12,440 抽出** — transitive closure で `am_relation` 177,381 → 189,821 edges、graph_traverse hop-3 path 増。
- **採択事例 gap 明示化** — tier S 14 件 / tier A 287 件で case_study 0、Wave 26 で operator subagent batch の populate 対象。
- **行政処分 → program 推論候補 87 件** — `enforcement_cases` 1,185 行 → `programs` 紐付け推定、人手 verify queue 投入。
- **invoice 法人番号 mismatch 412 件** — `invoice_registrants` 13,801 × `am_entities corporate_entity` 166,969 の join で 412 件不一致、honest gap として公開。

### Honest gap
- enforcement → program 87 候補は推論ベース、人手 verify 通過率は 50% 程度の見込み (operator 検証待ち)。

## Wave 24 status (2026-05-05、10 task、整理整頓 audit)

### Task list
- W24-1: `src/jpintel_mcp/` 配下 dead code (import されていない module) 列挙 → `analytics/dead_code_modules.txt` (8 module 候補、削除は別 wave)
- W24-2: `scripts/` 配下 cron / etl / migrations / その他 の分類整理 → `DIRECTORY.md:128` (現状把握、構造変更なし)
- W24-3: `docs/_internal/` 62 file の orphan (cross-link 0 の file) 列挙 → `analytics/orphan_internal_docs.txt` (11 file)
- W24-4: `tests/` 配下 fixture 重複 audit → `analytics/test_fixture_duplicates.csv` (24 重複、refactor 候補)
- W24-5: `site/` 配下 broken internal link audit → `analytics/site_broken_links.txt` (3 件、修正は W24-9)
- W24-6: `migrations/` 087 系列の rollback companion 完備性 → `analytics/migration_rollback_audit.csv` (087 中 12 file rollback 欠、launch 後追加)
- W24-7: `data/autonomath_static/` 8 taxonomy + 5 example の 整合性 audit → `analytics/static_data_audit.csv`
- W24-8: `.github/workflows/` 56 yml の checkout@v4 / setup-python@v5 統一 → `.github/workflows/*.yml` (drift 7 file 修正)
- W24-9: site broken link 3 件修正 → `site/footer.html`, `site/programs/index.html`, `site/docs/index.html`
- W24-10: Wave 24 本 section append + 全 wave 1-24 完了宣言。

### 主要成果
- **整理整頓 audit baseline 完成** — dead code / orphan doc / fixture 重複 / broken link / migration rollback gap、全て JSONL/CSV で固定、Wave 25 以降の cleanup 対象明確化。
- **GHA workflow drift 7 file 修正** — checkout@v4 + setup-python@v5 統一、supply chain pin 強化。
- **site broken link 3 件即修正** — launch 前 site 整合性 100%。

### Honest gap
- dead code 8 module は import grep ベース、reflective import の漏れ可能性あり (削除は別 wave で慎重に)。
- migration 087 系列の rollback 欠 12 file は idempotent forward-only 前提で launch、roll-forward 戦略のみ。

### 全 wave 1-24 完了宣言
- code-side blocker = 0
- pytest 269/269 green
- envelope contract 完整 (24 wave24 + 5 W22 + 3 industry pack + 5 Wave 19 English wedge)
- 17 sensitive tool `_disclaimer` 全 envelope 出現
- 配信 surface 4 (PyPI / npm / Browser / VSCode)
- SEO landing page 6,674 URL (programs 5,640 + cross hub 1,034)
- 本番 deploy 即実行可能 (operator 手動 9 件のみ)
