# reject reason templates (R1 - R5)

CLI の `[r]eject` 後の番号選択で発火する固定文。 reviewer_notes column に prefix `manual:RX:` または `auto_reject:RX:` で 記録。 contributor へは DEEP-31 ack mailer 経由で本文がそのまま 返信される (LLM 呼出 0)。

---

## R1: 1 次資料 source_url 不足 / aggregator URL 検出

> ご寄稿ありがとうございます。 1 次資料 (官公署 site) の URL を 1 つ以上 ご提示頂けますか? aggregator (noukaweb 等) は受付不可です。

trigger:
- `source_urls` が 空
- aggregator host (`noukaweb.com` / `noukanavi` / `matome` / `nta-` / `j-grants-aggregate`) を含む

---

## R2: 業法 fence 違反 phrase 検出

> 『採択保証』『確実な税額』 等の phrase は §52 / §72 業法 fence で受付不可です。 観察事実のみ ご寄稿頂けますか?

trigger (DEEP-38 detector mirror):
- `採択保証` / `確実な税額` / `確実に採択` / `100%採択` / `節税保証` / `必ず受給` / `絶対採択` を含む
- `observed_eligibility_text` 内のみ check

---

## R3: APPI risk (個人 PII detected)

> 個人 PII (マイナンバー / 電話番号 / email) が含まれています。 削除した上で再寄稿頂けますか? 法人番号は OK です。

trigger:
- `\b\d{12}\b` (マイナンバー)
- `0\d{1,4}-?\d{1,4}-?\d{4}` (電話)
- email regex
- 法人番号 13 桁 + hash 化済 column は対象外

---

## R4: program_id mismatch

> ご寄稿の program_id が autonomath corpus に見つかりません。 autocomplete から 選択し直して頂けますか?

trigger:
- `program_id` が `autonomath_corpus.programs` table に not found (DEEP-31 client-side autocomplete をバイパスした手入力ケース)

---

## R5: outlier (2σ 超え)

> ご寄稿の値が同 cluster 寄稿と 2σ 以上離れています。 一次資料 cross-walk で再確認頂けますか?

trigger:
- DEEP-33 で `outlier_sigma` が UPDATE 済、 `> 2.0`
