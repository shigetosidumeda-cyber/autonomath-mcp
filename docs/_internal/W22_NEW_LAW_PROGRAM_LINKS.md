# W22 — 132k 新 law article × programs 影響分析

- **生成日**: 2026-05-05
- **対象**: W21-1 で ingest された am_law_article 142,507 行 (post 2026-04-28)
- **基礎テーブル**: `am_law_article` (160,215 / 1,996 distinct laws)、`am_law_reference` (5,523 / 2,798 entities, 210 distinct law_canonical_id)、`programs` (8,203 program entities via `am_entities`)、`program_law_refs` (**0 行 — 未populate**)

## 結論サマリ

- W21-1 ingest 影響を受ける **法令 82 件** が、`programs` から **延べ 1,118 回 / 789 distinct programs** から参照されている。
- ただし canonical link table `program_law_refs` は **0 行**。プログラム ↔ 法令の構造化リンクは現状すべて raw 引用 (`am_law_reference.law_canonical_id`) のみ。
- `program_law_refs` は FK で `laws.unified_id` を期待するが `laws` テーブル自体も 0 行。**bridge 不在**。

## 上位 20 法令 (program 参照数 desc)

| law_canonical_id | 法令名 | 参照 program 数 | 新 article 数 | 総 article 数 |
|---|---|---|---|---|
| law:yakuji | 医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律 | 55 | 640 | 640 |
| law:jido-fukushi | 児童福祉法 | 41 | 713 | 713 |
| law:chihou-jichi | 地方自治法 | 37 | 1,266 | 1,266 |
| law:shokuhin-eisei | 食品衛生法 | 36 | 199 | 199 |
| law:shobo | 消防法 | 34 | 385 | 385 |
| law:koutu-anzen | 道路交通法 | 31 | 575 | 575 |
| law:iryo | 医療法 | 24 | 635 | 635 |
| law:sozei-tokubetsu | 租税特別措置法 | 23 | 3,558 | 3,587 |
| law:kosen | 公職選挙法 | 23 | 727 | 727 |
| law:koku | 航空法 | 22 | 554 | 554 |
| law:kenko-hoken | 健康保険法 | 21 | 705 | 705 |
| law:saigai-taisaku | 災害対策基本法 | 20 | 316 | 316 |
| law:bunkazai | 文化財保護法 | 18 | 330 | 330 |
| law:gakko-kyoiku | 学校教育法 | 18 | 287 | 287 |
| law:shitauke | 下請代金支払遅延等防止法 | 18 | 36 | 36 |
| law:ritou-shinkou | 離島振興法 | 17 | 85 | 85 |
| law:doro-unso-shaso | 道路運送車両法 | 16 | 400 | 400 |
| law:shogai-koyo | 障害者の雇用の促進等に関する法律 | 15 | 252 | 252 |
| law:kaijo-unso | 海上運送法 | 14 | 282 | 282 |
| law:kowan | 港湾法 | 12 | 357 | 357 |

(残 62 件は `/tmp/w22_candidates.tsv` 参照 — 全 82 件の完全 dump)

## program_law_refs 拡張案 (実装は別 wave)

candidate 数 82 (>100 ではないが、program 側参照は 789 distinct で実用的に十分大きい):

1. **bridge 不在の解消**: `laws` (0 行) を `am_law` (10,125 行) から populate するか、`program_law_refs` の FK を `am_law.canonical_id` に張り替え。
2. **am_law_reference → program_law_refs 移行**: `am_entities.record_kind='program'` × `law_canonical_id IS NOT NULL` の 2,630 行を batch insert。article/paragraph/sub_item を `article_citation` に concat (`第N条第M項第K号` フォーマット)。
3. **ref_kind 推論**: `am_law_reference.reference_kind` (substantive/procedural) を `program_law_refs.ref_kind` (authority/eligibility/exclusion/reference/penalty) へ enum マップ。デフォルト `'reference'`、source_field に `'authority'` 含むもののみ `'authority'`。
4. **W22 ingest 後 backfill**: 新 article で raw text に program 名/unified_id citation を見つけた行を逆方向 enrich (NLP 不要、文字列 match で十分)。

## 未マップ残

- `am_law_reference.law_canonical_id IS NULL` の program 由来 ref: **3 件のみ** (整合性は良好)
- 132k ingest 中、program から参照されない 1,914 法令 (1,996 - 82) は影響範囲外。
