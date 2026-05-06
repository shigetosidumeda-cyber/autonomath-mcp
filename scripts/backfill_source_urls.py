#!/usr/bin/env python3
"""Backfill missing source_url for programs rows.

Usage: python scripts/backfill_source_urls.py

Only updates rows where source_url IS NULL OR source_url = ''.
All URLs below were verified to return HTTP 200 and contain the program
name in the page title or H1 before being added here.

Banned aggregators (never use): noukaweb, hojyokin-portal, biz.stayway,
hojyokin.jp, creabiz, yorisoi.
"""

import sqlite3
from datetime import datetime, timezone

# fmt: off
MAPPINGS = {
    # ── S / A tier (launch-blocking) ────────────────────────────────────────
    # UNI-08c8a33792  tier=A  人材開発支援助成金
    # Verified: HTTP 200, page title "人材開発支援助成金" (MHLW)
    "UNI-08c8a33792": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",

    # UNI-3a9b7f91e1  tier=S  企業版ふるさと納税
    # Verified: HTTP 200, page title contains "企業版ふるさと納税" (内閣府 地方創生推進事務局)
    # Note: original pre-researched URL chisou.go.jp/tiiki/tiikisaisei/kigyohometax.html returned 404;
    # current canonical found by following the 404 redirect links from that page.
    "UNI-3a9b7f91e1": "https://www.chisou.go.jp/tiiki/tiikisaisei/kigyou_furusato.html",

    # UNI-6b32629951  tier=S  スマート農業技術の開発・実証プロジェクト
    # Verified: HTTP 200, page title "スマート農業実証プロジェクト", body contains
    # "スマート農業技術の開発・実証プロジェクト" (NARO / 農研機構)
    "UNI-6b32629951": "https://www.naro.go.jp/smart-nogyo/index.html",

    # UNI-795e155ee7  tier=S  環境保全型農業直接支払交付金
    # Verified: HTTP 200 via curl with browser UA, page title
    # "環境保全型農業直接支払交付金：農林水産省" (MAFF)
    # Note: original URL kakyou_chokusetsu/mainp.html was a 404;
    # correct path is kakyou_chokubarai/mainp.html (discovered from MAFF hozen_type index).
    "UNI-795e155ee7": "https://www.maff.go.jp/j/seisan/kankyo/kakyou_chokubarai/mainp.html",

    # ── B tier ──────────────────────────────────────────────────────────────
    # UNI-23f9767df9  小規模企業共済
    # Verified: HTTP 200, title contains "小規模企業共済" (SMRJ)
    "UNI-23f9767df9": "https://www.smrj.go.jp/kyosai/skyosai/index.html",

    # UNI-2611050f9a  小規模事業者持続化補助金
    # Verified: HTTP 200, official admin site run by 日本商工会議所 (Japan Chamber of Commerce)
    # Not an aggregator; this is the government-designated administrative body.
    "UNI-2611050f9a": "https://jizokukahojokin.info/",

    # UNI-2b37415d3b  中小企業省力化投資補助金
    # Verified: HTTP 200, title "中小企業省力化投資補助金" (SMRJ official portal)
    "UNI-2b37415d3b": "https://shoryokuka.smrj.go.jp/",

    # UNI-39fe6be3e2  賃上げ促進税制(中小企業向け)
    # Verified: HTTP 200, title "No.5927-2 ... 中小企業者等における賃上げ促進税制" (NTA)
    "UNI-39fe6be3e2": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5927-2.htm",

    # UNI-a69e56e0c4  ものづくり・商業・サービス生産性向上補助金
    # Verified: HTTP 200, official ものづくり補助金 portal
    "UNI-a69e56e0c4": "https://portal.monodukuri-hojo.jp/",

    # UNI-c58c205461  介護ロボット導入支援事業
    # Verified: HTTP 200, title "介護ロボットの開発・普及の促進｜厚生労働省" (MHLW)
    "UNI-c58c205461": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000209634.html",

    # UNI-d17980c957  IT導入補助金
    # Verified: HTTP 200, title "トップページ | IT導入補助金2023" (official portal)
    "UNI-d17980c957": "https://it-hojo.jp/",

    # UNI-eeb04a5853  経営セーフティ共済(倒産防止共済)
    # Verified: HTTP 200, title contains "経営セーフティ共済" (SMRJ)
    "UNI-eeb04a5853": "https://www.smrj.go.jp/kyosai/tkyosai/index.html",

    # ── B tier rows that could NOT be verified (flagged, not written) ────────
    # UNI-0bb2960d35  新事業進出補助金(旧事業再構築補助金後継)
    #   METI URL timed out; program may still be in early public notice phase.
    #   Not written — no confirmed 200 primary-source URL found.
    #
    # UNI-36200730f2  キャリアアップ助成金
    #   All known MHLW kyufukin/career_up paths return 404 as of 2026-04-24.
    #   The page appears to have been reorganised; no confirmed 200 URL found.
    #   Not written — flagged for manual follow-up.
    #
    # UNI-8b3089e954  新潟市 元気な農業応援事業費補助金 ソフト事業
    #   Multiple Niigata City paths tried, all 404.
    #   Not written — flagged for manual follow-up.
    #
    # UNI-9fe92cc070  介護職員処遇改善加算(新加算I)
    #   MHLW shogu_kaizen path returned 404; page appears moved.
    #   Not written — flagged for manual follow-up.
    #
    # UNI-ee8c7e2d3c  特許料等減免制度
    #   JPO (jpo.go.jp) is network-unreachable from this environment (exit 000).
    #   Not written — flagged for manual follow-up.
}
# fmt: on


def main() -> None:
    db_path = "data/jpintel.db"
    conn = sqlite3.connect(db_path)
    ts = datetime.now(timezone.utc).isoformat()
    updated = 0
    skipped = 0
    for uid, url in MAPPINGS.items():
        cur = conn.execute(
            "UPDATE programs SET source_url = ?, source_fetched_at = ? "
            "WHERE unified_id = ? AND (source_url IS NULL OR source_url = '')",
            (url, ts, uid),
        )
        if cur.rowcount:
            print(f"  UPDATED  {uid}: {url}")
            updated += cur.rowcount
        else:
            print(f"  SKIPPED  {uid}: already has source_url or not found")
            skipped += 1
    conn.commit()
    conn.close()
    print(f"\nDone: {updated} row(s) updated, {skipped} row(s) skipped.")


if __name__ == "__main__":
    main()
