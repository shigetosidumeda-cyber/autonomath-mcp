# 36協定 (`render_36_kyotei_am`) Launch Gate Decision — 2026-04-25

## TOC

1. Tool overview
2. Risk analysis
   1. 法的責任 (社労士法 / 労働基準法 §36)
   2. 顧客誤用リスク
   3. Brand damage
3. Mitigation options (A / B / C)
4. Decision: A + B 併用
5. Implementation
6. Re-evaluation triggers

---

## 1. Tool overview

**Tools added in Phase A absorption (2026-04-25):**

- `render_36_kyotei_am` — deterministic template substitution. Inputs 10
  required fields (会社名 / 住所 / 代表者 / 業種 / 労働者数 / 協定有効期間
  開始日・終了日 / 月間時間外労働時間 / 年間時間外労働時間 /
  月間休日労働日数). No LLM, no DB. Backed by
  `data/autonomath_static/templates/36_kyotei_template.txt`.
- `get_36_kyotei_metadata_am` — returns required fields + Japanese
  aliases + authority (厚生労働省) + license.

**Output**: rendered Japanese text styled after the 厚生労働省 official
様式. The output looks like a 労基署 提出可能 document, even though
the surrounding wrapper is a "draft" reformulation by Bookyou株式会社.

## 2. Risk analysis

### 2.1 法的責任 (社労士法 / 労働基準法)

- **社労士法 §27 (業務独占)**: 労働社会保険諸法令に基づく書類の作成
  業務は社会保険労務士の独占業務。"営業として" 36協定 書類を作成すると
  非社労士の独占業務侵害に該当しうる。
- **労基法 §36 / §32**: 36協定 は時間外労働の上限を労使で取り決める
  協定。誤った hours 設定 (上限超過 / 健康確保措置欠落) は労基署受付
  拒否のみならず、施行後に違法残業の根拠となり得る。
- **使用者 / 過半数代表者の押印・署名**: 様式そのものに 過半数代表者の
  選出方法・署名・押印の要件があり、テンプレ生成だけでは満たせない。
  AutonoMath はこの工程を automate できない / してはならない。

論点: AutonoMath が "提出可能な 36協定" を generation するという
positioning を取ると、社労士法違反を黙認することになる。一方で
"draft / 要社労士確認" の positioning に徹すれば、社労士の業務に
干渉しない (ワープロ機能と同等の道具) として整理できる。

### 2.2 顧客誤用リスク

- **想定誤用**: 顧客 (主に SMB / 個人事業主) が `render_36_kyotei_am`
  の出力をそのまま印刷し、労基署に提出する。AutonoMath が generation
  accuracy を保証していない事を読み飛ばし、内容ミスで受付拒否 or
  施行後の違法残業発覚。
- **CS / 解約圧力**: 受付拒否 / 違法残業 → 顧客は "AutonoMath が
  間違ったテンプレを生成した" と苦情。Solo + zero-touch ops では
  個別対応不可。
- **詐欺リスク**: 数千円の API 利用料で labor lawsuit リスクを買う
  顧客が現れる。memory `feedback_autonomath_fraud_risk.md` の延長線上。

### 2.3 Brand damage

- **AutonoMath の positioning**: "primary-source verified data API".
  自動生成書類が誤りを含む / 法的責任問題を起こすと、データ品質に
  対する評価まで巻き添えで毀損。
- **memory `feedback_autonomath_fraud_risk.md`**: 万単位営業×受給
  売り込みで詐欺リスクと隣合わせ。36協定 は "受給" 系ではないが、
  legal advice 系で同類のリスクを抱える。
- **Trademark (memory `project_jpintel_trademark_intel_risk.md`)**:
  既に "AutonoMath = Bookyou株式会社" branding に集約しており、
  社労士法トラブルが ブランドに直結する。

## 3. Mitigation options

### Option A: launch 時 env=False (operator が法務 review 後 enable)

- 効果: launch 時点で `mcp.list_tools()` から完全に消える。
  顧客に見えないので誤用ゼロ。
- コスト: Phase A absorption で実装した tool が即座に出ない。
- 解除条件: 社労士監修体制 + 顧客向け disclaimer 文言の法務確認 +
  CS テンプレ ("受付拒否時の対応") が揃ったら True に flip。

### Option B: 「draft / 要法務確認」disclaimer を response に必ず添付

- 効果: 出力が draft であり、社労士確認を要する旨を毎回明示。
- コスト: 顧客が disclaimer を読み飛ばすリスクは残る。
- 既存の似た仕組み: REST 側の `quality_grade` / `uses_llm` メタ情報、
  および INV-22 response_sanitizer。
- INV-22 整合: disclaimer 文 `保証しません` は negation context。
  `src/jpintel_mcp/api/response_sanitizer.py:64-100` の affirmative
  regex (`保証します` / `必ず採択` 等) には hit しない。

### Option C: launch から有効、法務に随時 review 依頼

- 効果: tool が即座に使える、機能を Phase A の意図通り公開できる。
- コスト: 法務 review 未完で公開 = 詐欺リスク + 社労士法問題を
  抱えた状態で launch。memory `feedback_autonomath_fraud_risk.md`
  に直接違反。

## 4. Decision: A + B 併用

| 項目 | 選択 |
|---|---|
| **A: env-gate** | YES — `AUTONOMATH_36_KYOTEI_ENABLED=0` が default |
| **B: disclaimer** | YES — enable 時も `_disclaimer` field を必ず付ける |
| **C: 即時公開** | NO |

理由:

- A だけだと、enable 後に B が抜ける可能性 (operator が disclaimer 文言を
  忘れる / 削る) があるので両者を独立に enforce する。
- B だけだと、disclaimer 読み飛ばしによる誤用が消えない。A で hidden
  状態を baseline に。
- A + B の組み合わせは、`enable_preview_endpoints` (config.py:119) や
  `healthcare_enabled` (config.py:28) の既存パターンと整合的。

## 5. Implementation

### 5.1 `src/jpintel_mcp/config.py`

```python
saburoku_kyotei_enabled: bool = Field(
    default=False,
    alias="AUTONOMATH_36_KYOTEI_ENABLED",
    description="法務 review 完了後に true に設定。デフォルト disabled。",
)
```

### 5.2 `src/jpintel_mcp/mcp/autonomath_tools/template_tool.py`

- module-level `if settings.saburoku_kyotei_enabled:` block wraps both
  `@mcp.tool` decorators. When False, the functions are not defined and
  not registered → `mcp.list_tools()` does not return them.
- When True, the response gains a `_disclaimer` key:

  ```
  本テンプレートは draft です。労基署提出前に必ず社労士確認を行ってください。
  AutonoMath は generation accuracy について保証しません。
  ```

### 5.3 `tests/test_saburoku_gate.py`

- env=False (default): registry name set does NOT contain
  `render_36_kyotei_am` / `get_36_kyotei_metadata_am`.
- env=True: both names appear; render output carries `_disclaimer`.

### 5.4 Operator runbook (CLAUDE.md)

1 paragraph documenting that the gate exists and how to enable it.

## 6. Re-evaluation triggers

Re-open this decision when ANY of the following lands:

1. 社労士監修契約 (or 顧問社労士 placement) が確立.
2. 顧客向け disclaimer 文言を 弁護士 / 社労士 が 法務 review 済み.
3. CS テンプレ (受付拒否時 / 内容ミス時) を整備済み.
4. 36協定 系 tool への顧客需要が明確化 (organic enquiry > N 件 / 月).

すべて満たすまで `AUTONOMATH_36_KYOTEI_ENABLED=0` を維持。

---

## Source / context references

- Phase A absorption: `CLAUDE.md` "Phase A absorption (complete 2026-04-25)"
- Tool implementation: `src/jpintel_mcp/mcp/autonomath_tools/template_tool.py`
- Template renderer: `src/jpintel_mcp/templates/saburoku_kyotei.py`
- INV-22 response sanitizer: `src/jpintel_mcp/api/response_sanitizer.py`
- memory: `feedback_autonomath_fraud_risk.md`,
  `feedback_zero_touch_solo.md`, `feedback_no_fake_data.md`
