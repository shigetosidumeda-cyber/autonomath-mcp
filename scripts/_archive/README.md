# Scripts Archive — 一度使い切り 済 (2026-04-23)

本ディレクトリ は **役割を終えた one-shot スクリプト** を archive. 
コード読解 / 今後の類似 fix 例 として 参照用.

## 含むファイル

- `fix_uni_e33d7b0613.py` — 栗原市 の row corruption 修正 (2026-04-23 執行済)
- `fix_url_integrity_blockers.py` — 5 URL integrity blockers の 8 column patches 一括適用 (B3 LAUNCH_BLOCKERS、2026-04-23 執行済)
- `apply_prefecture_overrides.py` — prefecture override 適用 (2026-04-23 執行済)

## 再利用時の注意

- これらの script を **再実行 すると 重複 patch エラー or DB 破損** の 可能性
- 同種の fix が必要な場合は 新 script を 書く (これら を template に 参考)
- 参考 doc: `docs/data_integrity.md`
