# sdk/integrations/tkc-csv — TKC FX2 顧問先一覧 CSV import

TKC FX2 (税理士事務所向け会計ソフト) は **公式 API を持たない** が、
顧問先一覧の **CSV エクスポート** 機能を持っている。これは TKC モバイル
業務支援 / freee 顧問サービス と並走しつつ、税理士事務所が自分で持っている
顧問先データを jpcite の `client_profiles` (migration 096) に取り込む
最短ルート。

```
TKC FX2 (税理士事務所内)
        │ 顧問先一覧 → CSV export (utf-8-sig / cp932)
        ▼
import_tkc_fx2.py
        │ TKC 列名 → jpcite client_profiles JSON
        ▼
apply_to_client_profiles.py
        │ multipart POST (X-API-Key)
        ▼
api.jpcite.com /v1/me/client_profiles/bulk_import (migration 096)
```

DB 直書きはしない (CLAUDE.md 制約)。すべて REST API 経由。

## ファイル

| ファイル | 役割 |
|---|---|
| `import_tkc_fx2.py` | TKC FX2 CSV → jpcite client_profiles JSON 変換 (CLI / library) |
| `apply_to_client_profiles.py` | JSON → `/v1/me/client_profiles/bulk_import` POST (CLI) |
| `sample_tkc_fx2.csv` | 3 行の dummy CSV (列名検証 + 文字コード確認用) |
| `README.md` | 本ドキュメント |

(同階層に test は無し。test は `tests/test_tkc_csv_import.py` から呼ぶ)

## 使い方

### 1) TKC FX2 から CSV エクスポート

TKC FX2 の「関与先管理」→「関与先一覧」→「CSV 出力」。
既定の文字コードは TKC 旧版で cp932、新版で utf-8-sig。
本 SDK は **両方を auto-detect** するので、エクスポート時の選択は問わない。

### 2) 変換 (CSV → JSON)

```bash
python import_tkc_fx2.py /path/to/tkc_export.csv \
    --output /tmp/jpcite_profiles.json
```

`--encoding utf-8-sig` / `--encoding cp932` で強制指定可能。
`--max-rows 200` で安全上限 (jpcite の `MAX_BULK_IMPORT_ROWS` と一致)。

出力 JSON は以下の形:

```json
{
  "records": [
    {
      "name_label": "株式会社サンプル製造",
      "jsic_major": "E26",
      "prefecture": "東京都",
      "employee_count": 45,
      "capital_yen": 30000000,
      "last_active_program_ids": ["IT導入補助金2023", "ものづくり補助金R5"]
    }
  ],
  "errors": [],
  "summary": { "input_path": "...", "record_count": 1, "error_count": 0 }
}
```

### 3) jpcite REST に upsert 投入

```bash
export JPCITE_API_KEY=am_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
python apply_to_client_profiles.py /tmp/jpcite_profiles.json \
    --api-base https://api.jpcite.com
```

`--dry-run` で送信前に内容確認。`--no-upsert` で純粋 INSERT (重複は jpcite
側で `MAX_CLIENT_PROFILES_PER_KEY = 200` チェックに引っかかる)。

## TKC 列 → jpcite フィールド対応

| TKC FX2 列 (日本語) | jpcite client_profile | 備考 |
|---|---|---|
| 関与先コード | (drop) | `name_label` が PK 役 |
| 関与先名 | `name_label` | **必須**。空行は skip |
| 業種コード | `jsic_major` | 4 文字までに切り詰め (E26 → E26) |
| 業種名 | (drop) | `jsic_major` が canonical |
| 所在地都道府県 | `prefecture` | `東京都` / `大阪府` 等 |
| 従業員数 | `employee_count` | `1,000` / `45人` 等の suffix を許容 |
| 資本金（千円） | `capital_yen` | **×1,000 倍** して円単位に正規化 |
| 前年売上（千円） | (drop) | jpcite は売上枠なし |
| 適用補助金履歴 | `last_active_program_ids` | `\|` 区切り |

業種コードのテンプレが事務所ごとに違う場合は
`import_tkc_fx2.convert_csv_text(..., column_map={...})` を Python から
呼び、自分で対応マップを差し替える。

## 課金モデル (税理士事務所側目線)

- bulk_import 自体は **無料** (CRUD は metered surface ではない)。
- 投入された顧問先は `saved_searches` の cron fan-out で `1 req = ¥3.30` の
  metered 単価が発生する (`scripts/cron/run_saved_searches.py`)。
- 50 顧問先 × 月 100 req の運用で **想定** 月収 ¥150,000 (税込 ¥165,000、
  honest forecast、UNVERIFIED — 顧客 0 社時点の理論値)。
- TKC モバイル業務支援 / freee 顧問サービス と **競合せず並走** する設計
  (会計データには touch しない、jpcite は補助金/税制/法令/判例/インボイス
  公表情報の一次出典付き検索のみ)。

## 制約 (緩めない)

- LLM API 呼出 禁止 (本ファイル群のどこからも anthropic / openai を
  import しない、env も読まない)。
- DB 直書き禁止。`/v1/me/client_profiles/bulk_import` REST 経由のみ。
- `¥3/req` metered 単一料金。tier 提案禁止。
- 顧問先 PII (関与先名・所在地) は jpcite の `client_profiles` に
  user-managed で乗る。Bookyou 側はサーバ側の usage_events 30 日保管以外
  には保存しない。

## 提供事業者

- **Bookyou株式会社** (適格請求書発行事業者番号 T8010001213708)
- 代表 梅田茂利
- 所在地 東京都文京区小日向2-22-1
- 連絡先 info@bookyou.net
