#!/usr/bin/env python3
# OPERATOR ONLY: Run manually from tools/offline/. Never imported from src/, scripts/cron/, or scripts/etl/.
"""am_invoice_buyer_seller_graph batch driver — EDINET XBRL から取引相手 edge 推論.

PURPOSE (migration wave24_133_am_invoice_buyer_seller_graph):
    EDINET XBRL (公開有価証券報告書 / 半期報告書) を Claude Code subagent に
    解析させ、seller × buyer の取引 edge を推論する helper。
    本 script は LLM SDK を一切呼ばない。

WORKFLOW:
    1. operator: `python tools/offline/run_invoice_buyer_seller_batch.py
                  --batch_id 1 --batch_size 200 --dry-run`
    2. 本 script: invoice_registrants から 適格事業者登録あり & EDINET 取得 URL あり
                  の seller candidate を SELECT、subagent 用 prompt + schema を出す。
                  さらに、まだ am_invoice_buyer_seller_graph に edge が無い seller を優先。
    3. operator: Claude Code subagent → EDINET XBRL を fetch / parse して
                 edge JSONL → tools/offline/_inbox/edinet_relations/.
    4. operator: ingest_offline_inbox.py が
                 UNIQUE (seller, buyer, evidence_kind) で INSERT OR REPLACE。

NO LLM IMPORT.
"""
from __future__ import annotations

import argparse
import sys

from _runner_common import (
    DEFAULT_AUTONOMATH_DB,
    emit,
    query_rows,
)

from jpintel_mcp.ingest.schemas.invoice_buyer_seller import BuyerSellerEdge


TOOL_SLUG = "edinet_relations"

# Pick sellers (houjin) we already have invoice / corp data for, ordered
# by adoption density (proxy for "active" houjin) and not yet edge-mined.
SQL_SELLER_CANDIDATES = """
    SELECT ir.houjin_bangou,
           ir.normalized_name,
           ir.invoice_registration_number,
           ir.address_normalized,
           ir.prefecture,
           hm.total_adoptions,
           hm.jsic_major,
           hm.corporation_type
      FROM invoice_registrants AS ir
 LEFT JOIN houjin_master AS hm USING (houjin_bangou)
     WHERE ir.houjin_bangou IS NOT NULL
       AND ir.houjin_bangou != ''
       AND ir.revoked_date IS NULL
       AND NOT EXISTS (
         SELECT 1 FROM am_invoice_buyer_seller_graph g
          WHERE g.seller_houjin_bangou = ir.houjin_bangou
       )
     ORDER BY COALESCE(hm.total_adoptions, 0) DESC, ir.houjin_bangou ASC
     LIMIT ?
"""

RULES = [
    "EDINET (https://disclosure2.edinet-fsa.go.jp/) から各 seller_houjin_bangou の "
    "有価証券報告書 / 半期報告書 XBRL を fetch し、主要販売先 / 主要仕入先を抽出。",
    "1 行 = 1 (seller, buyer, evidence_kind) edge。同一 seller-buyer ペアでも "
    "evidence_kind 違いなら別 row。",
    "buyer_houjin_bangou は EDINET 開示先名 → NTA 法人番号 lookup で 13 桁文字列に正規化。"
    "解決できない buyer は skip (行を作らない)。",
    "evidence_kind = 'public_disclosure' (有価証券報告書)、'co_filing' (連結子会社)、"
    "'press_release' (適時開示) など spec の enum から選ぶ。",
    "confidence = 0.0..1.0 の実数。confidence_band は high (>=0.8) / medium (>=0.5) / low。",
    "source_url_json に EDINET 開示書類 URL (httpd direct link) を必ず 1 つ入れる。",
    "first_seen_at / last_seen_at は当該開示の対象期間 (FY 末日 or 半期末日) の ISO8601 UTC。",
    "self-loop (seller == buyer) は出力しない (DB CHECK で reject)。",
    "subagent_run_id = '{batch_id}-{seq}'。computed_at は ISO8601 UTC。",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--batch_id", type=int, required=True)
    p.add_argument("--batch_size", type=int, default=200)
    p.add_argument("--autonomath-db", default=str(DEFAULT_AUTONOMATH_DB))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rows = query_rows(args.autonomath_db, SQL_SELLER_CANDIDATES, (args.batch_size,))
    schema = BuyerSellerEdge.model_json_schema()
    emit(
        tool_slug=TOOL_SLUG,
        batch_id=args.batch_id,
        rows=rows,
        schema_title="BuyerSellerEdge",
        schema_json=schema,
        title="am_invoice_buyer_seller_graph batch (EDINET XBRL)",
        purpose=(
            "適格事業者登録あり & 未 edge-mined な seller を batch_size 件取得し、"
            "EDINET XBRL から取引相手 edge を推論する素材を出力する。"
        ),
        rules=RULES,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
