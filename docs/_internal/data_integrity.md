# データ整合性インバリアント

AutonoMath が有料 API として表示する全レコードは、本ドキュメントで定義する
整合性インバリアントを満たさなければならない。景品表示法 4 条 (優良誤認) /
5 条 (有利誤認) 不当表示への最小限の防御線であり、 CI とナイトリー走査で
機械的に検査する。

## インバリアント

1. **`source_url` は必ず実在する一次情報の URL を指すこと。**
   - 合成ホスト (`example.com` / `example.jp` / `example.org` / `example.net`
     / `localhost` / `test.com` / `test.jp`) は禁止。
   - ループバック / 未指定 IP (`127.0.0.1` / `0.0.0.0` / `::1`) は禁止。
   - プライベート IP 帯 (10.x / 172.16-31.x / 192.168.x / リンクローカル) は
     禁止。
   - プレースホルダ文字列 (`TODO` / `FIXME` / `XXXX` / `...` / `…`) を含む
     URL は禁止。
   - スキームが `http(s)` 以外、ホスト未設定、TLD なしの単一ラベルホストは
     禁止。
2. **`official_url` も同じ禁止ルールを満たすこと。** `source_url` と
   `official_url` は顧客表示に直結するため等価な扱い。
3. **`enriched_json` および `source_mentions_json` に埋め込まれた URL も
   同じルールで検査する。** 入れ子の奥でも捏造 URL は許容しない。
4. **`source_fetched_at` は ISO-8601 で保持する。** 6 か月超は「古い」と
   判定し警告対象 (ブロッカーではない、再フェッチの予定根拠)。
5. **`source_url` を含まない行は公開 API から非表示にする**、または
   `source_url: null` フラグと共に明示的に露出する (運用ポリシーで決定)。

## 検査 (guardrail)

- スクリプト: `scripts/url_integrity_scan.py`
  - `data/jpintel.db` を **read-only** で開く (`sqlite3 mode=ro`)。
  - `programs.source_url` / `programs.official_url` / `programs.enriched_json`
    / `programs.source_mentions_json` を走査し、上記インバリアントに違反する
    URL を `unified_id × column × url` 単位で列挙する。
  - 出力: `research/url_integrity_scan_YYYY-MM-DD.md` (人間向け) と
    同名 `.json` (機械向け)。違反 100 件超は理由別にページネーション。
  - 終了コード: 違反 0 件で `0`、1 件以上で `1`。
- ワークフロー: `.github/workflows/data-integrity.yml`
  - PR が `data/**` や本スクリプト自身を変更した場合に走り、違反が 1 件でも
    あれば merge を止める。
  - 毎日 04:30 JST (`ingest-daily` の後) に Fly マシン上で本番 DB を
    走査し、レポートを 30 日分保全する。
  - 手動 `workflow_dispatch` で修正後の再走査が可能。

## 違反を検知したときの対応

1. **Issue を立てる** (`label: data-integrity`)。対象 `unified_id`、該当
   column、違反理由 (スキャン出力) を貼る。
2. **一次情報の URL を人手で特定する**。MAFF 検索、自治体公式、JFC サイト
   検索で裏取り。WebFetch + Chrome headless で実ページを確認 (`feedback_no_fake_data.md`)。
3. **修正スクリプトを作成**: `scripts/fix_<unified_id>.py` を雛形に起こす。
   既存例として `scripts/_archive/fix_uni_e33d7b0613.py` 参照 (archive, 2026-04-23 execute 済). dry-run 既定、
   `--apply` を明示しない限り DB を変更しない構造を踏襲する。
4. **dry-run でプランを確認** → `--apply` で反映 → `url_integrity_scan.py`
   を再実行して 0 件を確認 → Issue に before/after を残してクローズ。
5. **再発防止**: 違反の源 (ingest ワーカーの defaults / テスト URL の
   漏れ込み) を特定し、上流で修正する。

## 例外扱いしないもの

- 「2 次ソース経由なので URL 自体は本物」は本インバリアント上は問題としない
  (例: `noukaweb.com` は実在ホスト)。ただし *品質* 別軸で追跡する (一次情報
  置換計画、`research/data_quality_report.md` 参照)。
- 「将来修正予定だからプレースホルダで一旦 commit」は禁止。プレースホルダは
  そもそも commit に乗せない。どうしても必要なら fixture ディレクトリを
  scan 対象外にするのではなく、本番 DB に到達しないパスへ隔離する。
