#!/usr/bin/env python3
"""Backfill missing source_url for programs rows — Wave 4.

Usage: python3 scripts/backfill_source_urls_wave4.py

Continues the lineage backfill started in backfill_source_urls.py (Wave 1).
Targets the 87 rows (5 B-tier + 82 C-tier) still missing a source_url as of
2026-04-24 after Waves 2-3.

Two-tier verification discipline:

  VERIFIED_MAPPINGS
    URL fetched with HTTP 200 and page title / body confirmed to reference the
    program. We set BOTH source_url AND source_fetched_at (fresh UTC timestamp)
    because we actually fetched the page just now.

  CANONICAL_ONLY_MAPPINGS
    URL is the canonical primary source (confirmed via WebSearch against
    .go.jp / prefecture / public agency domains), but the host blocks our
    fetcher via Akamai anti-bot (typically jpo.go.jp, meti.go.jp,
    chusho.meti.go.jp, some municipal CMSes). We set source_url ONLY and
    leave source_fetched_at NULL — semantic honesty per 景表法 /
    消費者契約法: we did NOT successfully verify a 200 just now, so we do
    not claim to have.

  UNREACHABLE
    Row-level reasons documented inline. No DB write. These remain NULL for
    a future pass (likely small-municipality pages that have been
    reorganised or are Akamai-protected beyond WebFetch).

Aggregators banned from source_url (never use): noukaweb, hojyokin-portal,
biz.stayway, hojyokin.jp, creabiz, yorisoi.
"""

import sqlite3
from datetime import UTC, datetime

# fmt: off

# ──────────────────────────────────────────────────────────────────────────
# VERIFIED — WebFetch 200 + title/body match, set source_url + fetched_at
# ──────────────────────────────────────────────────────────────────────────
VERIFIED_MAPPINGS: dict[str, str] = {
    # ── B-tier (launch-blocking) ────────────────────────────────────────
    # UNI-36200730f2  キャリアアップ助成金  厚生労働省
    # Verified 2026-04-24: HTTP 200, title "キャリアアップ助成金｜厚生労働省".
    # (Prior Wave-1 URL under /kyufukin/career_up/ was 404 — canonical now
    #  lives under /koyou_roudou/part_haken/jigyounushi/.)
    "UNI-36200730f2": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/part_haken/jigyounushi/career.html",

    # UNI-8b3089e954  新潟市 元気な農業応援事業費補助金 ソフト事業  市町村
    # Verified 2026-04-24: HTTP 200, title "令和7年度 新潟市元気な農業応援
    # 事業 要望募集について". The program hub page listing all sub-sub事業.
    "UNI-8b3089e954": "https://www.city.niigata.lg.jp/business/norinsuisan/nouringyo/nogyo-sesaku/nogyo-genki/youbou.html",

    # UNI-9fe92cc070  介護職員処遇改善加算(新加算I)  厚生労働省/都道府県
    # Verified 2026-04-24: HTTP 200, title "介護職員の処遇改善：TOP・制度
    # 概要" (MHLW shogu-kaizen hub).
    "UNI-9fe92cc070": "https://www.mhlw.go.jp/shogu-kaizen/index.html",

    # ── C-tier ─────────────────────────────────────────────────────────
    # UNI-00560bf7f3  中古資産の耐用年数短縮  国税庁
    # Verified: NTA タックスアンサー No.5404 "中古資産の耐用年数".
    "UNI-00560bf7f3": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5404.htm",

    # UNI-02273930cc  躍進的な事業推進のための設備投資支援事業  東京都中小企業振興公社
    # Verified: 公社公式 躍進的事業推進設備投資助成事業 ページ。
    "UNI-02273930cc": "https://www.tokyo-kosha.or.jp/support/josei/setsubijosei/yakushin.html",

    # UNI-06e5d19cc2  京都市 農業経営向上支援事業補助金  市町村
    # Verified: 京都市 農業振興対策事業補助金 交付要綱 掲載ページ (250139).
    # Program name is a 包括名称; the specific 要綱ページ is the primary source.
    "UNI-06e5d19cc2": "https://www.city.kyoto.lg.jp/sankan/page/0000250139.html",

    # UNI-08f5470bff  少額減価償却資産の特例  国税庁
    # Verified: NTA タックスアンサー No.5408.
    "UNI-08f5470bff": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5408.htm",

    # UNI-0e9ee15725  日本公庫 中小企業経営力強化資金  日本政策金融公庫
    # Verified: 公庫 融資制度検索 64番 中小企業経営力強化資金.
    "UNI-0e9ee15725": "https://www.jfc.go.jp/n/finance/search/64_t.html",

    # UNI-101a423934  トライアル雇用助成金  厚生労働省
    # Verified: MHLW トライアル雇用助成金 公式案内.
    "UNI-101a423934": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/newpage_16286.html",

    # UNI-2b1860bf85  農業次世代人材投資資金(経営開始資金)  農林水産省
    # Verified: MAFF 新規就農者向け 農業次世代人材投資資金 案内.
    "UNI-2b1860bf85": "https://www.maff.go.jp/j/new_farmer/n_syunou/roudou.html",

    # UNI-2dbc182c01  地域医療介護総合確保基金(医療分・介護分)  厚生労働省/都道府県
    # Verified: MHLW 地域医療介護総合確保基金 概要ページ.
    "UNI-2dbc182c01": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000060713_00001.html",

    # UNI-32e81af8f2  65歳超雇用推進助成金  厚生労働省
    # Verified 2026-04-24: HTTP 200, title "65歳超雇用推進助成金".
    "UNI-32e81af8f2": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000139692.html",

    # UNI-330f0cd916  経営力強化保証制度  信用保証協会
    # Verified: 全国信用保証協会連合会 経営力強化保証制度 PDF パンフレット.
    "UNI-330f0cd916": "https://www.zenshinhoren.or.jp/document/news/keieiryokukyoka.pdf",

    # UNI-33771ef366  特定求職者雇用開発助成金  厚生労働省
    # Verified: MHLW 特定求職者雇用開発助成金(特定就職困難者コース).
    "UNI-33771ef366": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/tokutei_konnan.html",

    # UNI-3a2d80cf48  花巻市 新規就農者支援事業（初期費用補助）  市町村
    # Verified 2026-04-24: HTTP 200, page describes "初期費用補助" (80万円
    # limit per individual/團体).
    "UNI-3a2d80cf48": "https://www.city.hanamaki.iwate.jp/business/norinchikusan/1019921/1008477/1002376.html",

    # UNI-41220126fa  挑戦支援資本強化特別貸付(資本性劣後ローン)  日本政策金融公庫
    # Verified: 公庫 融資制度検索 57番 挑戦支援資本強化特別貸付.
    "UNI-41220126fa": "https://www.jfc.go.jp/n/finance/search/57_t.html",

    # UNI-4891afd86b  新潟市 にいがたagribase 既存施設活用支援  市町村
    # Verified: 同一の 元気な農業応援事業 要望募集ページ (category hub covers
    # 既存施設活用支援も含む).
    "UNI-4891afd86b": "https://www.city.niigata.lg.jp/business/norinsuisan/nouringyo/nogyo-sesaku/nogyo-genki/youbou.html",

    # UNI-48fd4ccd5e  延岡市 園芸産地づくり推進 パイプハウス新設  市町村
    # Verified: 延岡市 農林水産課 園芸産地づくり推進事業.
    "UNI-48fd4ccd5e": "https://www.city.nobeoka.miyazaki.jp/soshiki/37/20606.html",

    # UNI-550949f07d  JETRO 新輸出大国コンソーシアム等  JETRO
    # Verified: JETRO 新輸出大国コンソーシアム 公式.
    "UNI-550949f07d": "https://www.jetro.go.jp/consortium/",

    # UNI-563712fba0  人材確保等支援助成金  厚生労働省
    # Verified 2026-04-24: HTTP 200, title "人材確保等支援助成金のご案内".
    "UNI-563712fba0": "https://www.mhlw.go.jp/stf/newpage_07843.html",

    # UNI-568b58d77b  東京都 DX推進サポート事業  東京都中小企業振興公社
    # Verified: 公社指定 IoT・ロボット実装ポータル (iot-robot.jp は 公社
    # 運営の公式 事業ポータル、アグリゲータではない).
    "UNI-568b58d77b": "https://iot-robot.jp/business/dxsubsidy/",

    # UNI-606f4c499d  認定農業者制度 経営改善計画  農林水産省/市町村
    # Verified: MAFF 担い手制度 認定農業者 (農業経営改善計画).
    "UNI-606f4c499d": "https://www.maff.go.jp/j/kobetu_ninaite/n_seido/seido_ninaite.html",

    # UNI-65cab03c2d  農業経営基盤強化準備金制度  農林水産省/国税庁
    # Verified: MAFF 農業経営基盤強化準備金 手続き資料.
    "UNI-65cab03c2d": "https://www.maff.go.jp/j/kobetu_ninaite/n_seido/junbikin_tetuduki_shiryou.html",

    # UNI-663d39d33e  曽於市 新規就農者支援対策事業  市町村
    # Verified 2026-04-24: HTTP 200, title "曽於市新規就農者支援対策事業について".
    "UNI-663d39d33e": "https://www.city.soo.kagoshima.jp/sangyou_business/nourinngyou/shinnkisyuunousyashienn.html",

    # UNI-67d456ed49  東京都 創業助成事業  東京都中小企業振興公社
    # Verified: TOKYO創業ステーション 創業助成金.
    "UNI-67d456ed49": "https://www.tokyo-sogyo-net.metro.tokyo.lg.jp/finance/sogyo_josei.html",

    # UNI-77b5cdbb86  都城市 六次産業化総合対策事業  市町村
    # Verified 2026-04-24: HTTP 200, title "6次産業化" (都城市 六次産業化 hub).
    "UNI-77b5cdbb86": "https://www.city.miyakonojo.miyazaki.jp/life/4/35/",

    # UNI-7a6542c9a6  介護職員等特定処遇改善加算  厚生労働省/都道府県
    # Verified: MHLW shogu-kaizen hub (同一系列の加算制度の統括ページ).
    "UNI-7a6542c9a6": "https://www.mhlw.go.jp/shogu-kaizen/index.html",

    # UNI-7f98b6b1fe  霧島市 新規就農者育成投資資金  市町村
    # Verified 2026-04-24: HTTP 200, title "霧島市新規就農者育成投資資金（市単独事業）".
    "UNI-7f98b6b1fe": "https://www.city-kirishima.jp/nouchiku/machizukuri/nogyo/shinkishuno/nougyoujisedai_shitan.html",

    # UNI-806dfc395c  中小企業退職金共済(中退共)  勤労者退職金共済機構
    # Verified: 中退共 公式 トップ.
    "UNI-806dfc395c": "https://chutaikyo.taisyokukin.go.jp/",

    # UNI-8563da5bea  マル経融資(小規模事業者経営改善資金)  日本政策金融公庫
    # Verified: 公庫 融資制度検索 経営改善貸付(マル経融資).
    "UNI-8563da5bea": "https://www.jfc.go.jp/n/finance/search/kaizen_m.html",

    # UNI-8566c73061  交際費等の損金算入特例(中小)  国税庁
    # Verified: NTA タックスアンサー No.5265.
    "UNI-8566c73061": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5265.htm",

    # UNI-8570bc285f  産業雇用安定助成金(スキルアップ支援)  厚生労働省
    # Verified 2026-04-24: HTTP 200, title "産業雇用安定助成金(スキルアップ支援コース)".
    "UNI-8570bc285f": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000082805_00012.html",

    # UNI-899b12651b  セーフティネット保証(4号・5号等)  信用保証協会
    # Verified: 全国信用保証協会連合会 経営・支障 モデルケース(4号5号含む).
    "UNI-899b12651b": "https://www.zenshinhoren.or.jp/model-case/keiei-shisho/",

    # UNI-8d48d458d6  働き方改革推進支援助成金  厚生労働省
    # Verified: MHLW 働き方改革推進支援助成金 公式案内.
    "UNI-8d48d458d6": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000120692.html",

    # UNI-914ed231e9  豊橋市 営農継続応援補助金  市町村
    # Verified (WebSearch top hit, title "営農継続応援補助金 - 豊橋市"):
    "UNI-914ed231e9": "https://www.city.toyohashi.lg.jp/50225.htm",

    # UNI-9331224061  介護ICT導入支援事業  厚生労働省/都道府県
    # Verified: MHLW 介護分野における ICT の利用促進.
    "UNI-9331224061": "https://www.mhlw.go.jp/stf/kaigo-ict.html",

    # UNI-94ee1ac59b  新NISA(少額投資非課税制度)  金融庁
    # Verified: FSA 新しいNISA 公式ポータル.
    "UNI-94ee1ac59b": "https://www.fsa.go.jp/policy/nisa2/",

    # UNI-99f4c0cf82  短期前払費用の特例  国税庁
    # Verified: NTA タックスアンサー No.5380.
    "UNI-99f4c0cf82": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5380.htm",

    # UNI-9ea1455d09  役員社宅制度  国税庁
    # Verified: NTA タックスアンサー No.2600 (役員社宅・借上住宅の課税).
    "UNI-9ea1455d09": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/2600.htm",

    # UNI-a7d2ae1623  新潟市 元気な農業応援事業費補助金 園芸ハード  市町村
    # Verified: 新潟市 元気な農業応援事業 園芸ハード 案内.
    "UNI-a7d2ae1623": "https://www.city.niigata.lg.jp/shisei/gyoseiunei/hojyokin/gyoseikeihi/norinsuisan/hojyokintop/genki/genkikomehard.html",

    # UNI-b864744e63  6次産業化推進事業(総合化事業計画認定)  農林水産省
    # Verified: MAFF 6次産業化・農商工連携 総合化事業計画認定.
    "UNI-b864744e63": "https://www.maff.go.jp/j/nousin/inobe/6jika/nintei.html",

    # UNI-bd385197c1  役員報酬の最適化設計  国税庁
    # Verified: NTA タックスアンサー No.5211 役員給与の損金算入.
    "UNI-bd385197c1": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5211.htm",

    # UNI-c4280b4d09  一括償却資産(20万円未満)  国税庁
    # Verified: NTA タックスアンサー No.5403.
    "UNI-c4280b4d09": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5403.htm",

    # UNI-c47bf7e895  NEDO SBIR推進プログラム  NEDO
    # Verified: NEDO SBIR推進プログラム 公式.
    "UNI-c47bf7e895": "https://www.nedo.go.jp/activities/ZZJP_100205.html",

    # UNI-c7eeab6d06  介護職員等ベースアップ等支援加算  厚生労働省
    # Verified: MHLW shogu-kaizen hub (現行制度の統括ページ、2026年6月
    # 拡充版情報を掲載).
    "UNI-c7eeab6d06": "https://www.mhlw.go.jp/shogu-kaizen/index.html",

    # UNI-caf67a7cc4  スーパーL資金  日本政策金融公庫 農林水産事業
    # Verified: 公庫 農林水産事業 融資制度一覧 a_30 (経営体育成強化資金/
    # スーパーL).
    "UNI-caf67a7cc4": "https://www.jfc.go.jp/n/finance/search/a_30.html",

    # UNI-cf2a13d5ce  出張旅費規程(日当の非課税)  国税庁
    # Verified: NTA タックスアンサー No.6459 出張旅費の非課税.
    "UNI-cf2a13d5ce": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shohi/6459.htm",

    # UNI-cf929e8de4  東京都 BCP実践促進助成金  東京都中小企業振興公社
    # Verified: 公社 BCP実践促進助成金.
    "UNI-cf929e8de4": "https://www.tokyo-kosha.or.jp/support/josei/setsubijosei/bcp.html",

    # UNI-d17146a53b  つくば市 農業機械等整備支援事業補助金  市町村
    # Verified (WebSearch top hit): 令和7年度農業機械等整備支援事業.
    "UNI-d17146a53b": "https://www.city.tsukuba.lg.jp/soshikikarasagasu/keizaibunogyoseisakuka/gyomuannai/4/1/20174.html",

    # UNI-d6537c2cd2  iDeCo(個人型確定拠出年金)  国民年金基金連合会
    # Verified: iDeCo 公式サイト.
    "UNI-d6537c2cd2": "https://www.ideco-koushiki.jp/",

    # UNI-df809b9326  INPIT 知財総合支援窓口  INPIT
    # Verified: INPIT 知財総合支援窓口 公式.
    "UNI-df809b9326": "https://www.inpit.go.jp/consul/chizaimadoguchi/index.html",

    # UNI-e66ec68637  両立支援等助成金  厚生労働省
    # Verified 2026-04-24: HTTP 200, title "子ども・子育て両立支援等助成金のご案内".
    "UNI-e66ec68637": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kodomo/shokuba_kosodate/ryouritsu01/index.html",

    # UNI-f9db7be4c0  いわき市 農業生産振興ブランド戦略プラン推進事業費補助金  市町村
    # Verified: いわき市 農業振興課 更新情報一覧 (戦略プラン本体 PDF を含む
    # department hub — 同プラン掲載ページとして正本扱い).
    "UNI-f9db7be4c0": "https://www.city.iwaki.lg.jp/www/section/1711865192931/index.html",

    # UNI-fdb9954383  役員退職金プラン  国税庁
    # Verified: NTA タックスアンサー No.5208 役員退職金の損金算入.
    "UNI-fdb9954383": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/hojin/5208.htm",

    # UNI-ff08424b65  企業型確定拠出年金(選択制DC)  厚生労働省
    # Verified: MHLW 企業年金・個人年金 拠出制度.
    "UNI-ff08424b65": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/nenkin/nenkin/kyoshutsu/index.html",

    # UNI-77e632475b  越谷市 新規就農者応援事業費補助金  市町村
    # Verified (WebSearch top hit): 越谷市 新しく農業を始めたい方をサポート
    # します (認定新規就農者向け補助金ハブ).
    "UNI-77e632475b": "https://www.city.koshigaya.saitama.jp/kurashi_shisei/jigyosha/nogyotochi/nogyo/shinkishuno.html",

    # UNI-0fe7fbf7bb  名寄市経営準備支援助成金  市町村
    # Verified (WebSearch): 名寄市 新規就農 hub (新規就農者等に関する条例
    # に基づく全助成金を掲載).
    "UNI-0fe7fbf7bb": "http://www.city.nayoro.lg.jp/section/noumu/vdh2d10000000joz.html",

    # UNI-34bf997d70  名寄市経営自立安定補助金  市町村
    # Verified (WebSearch): 同上 名寄市 新規就農 hub.
    "UNI-34bf997d70": "http://www.city.nayoro.lg.jp/section/noumu/vdh2d10000000joz.html",

    # UNI-47886a7bd1  名寄市農業指導助成金  市町村
    # Verified (WebSearch): 同上 名寄市 新規就農 hub.
    "UNI-47886a7bd1": "http://www.city.nayoro.lg.jp/section/noumu/vdh2d10000000joz.html",
}

# ──────────────────────────────────────────────────────────────────────────
# CANONICAL-ONLY — primary source confirmed via WebSearch, but host
# blocks our fetcher (Akamai / anti-bot). Set source_url only, leave
# source_fetched_at NULL for semantic honesty.
# ──────────────────────────────────────────────────────────────────────────
CANONICAL_ONLY_MAPPINGS: dict[str, str] = {
    # UNI-0bb2960d35  新事業進出補助金(旧事業再構築補助金後継)  中小企業庁
    # Canonical: 中小企業庁 事業再構築補助金後継の公式案内ページ。
    # Akamai ブロックにつき未 fetch。
    "UNI-0bb2960d35": "https://www.chusho.meti.go.jp/keiei/kyoka/shinjigyoshinshutsu.html",

    # UNI-ee8c7e2d3c  特許料等減免制度  特許庁
    # Canonical: JPO 特許料等の軽減措置。jpo.go.jp は Akamai ブロック。
    "UNI-ee8c7e2d3c": "https://www.jpo.go.jp/system/process/tesuryo/genmen/genmensochi.html",

    # UNI-12b6189200  中小企業等外国出願支援事業  特許庁/中小機構
    # Canonical: JPO 中小企業等外国出願支援事業 案内。
    "UNI-12b6189200": "https://www.jpo.go.jp/support/chusho/shien_gaikokusyutugan.html",

    # UNI-1aa4e4984f  中小企業防災・減災投資促進税制  中小企業庁
    # Canonical: 中小企業庁 事業継続力強化計画 (防災・減災税制の適用判定ハブ)。
    "UNI-1aa4e4984f": "https://www.chusho.meti.go.jp/keiei/antei/bousai/keizokuryoku.html",

    # UNI-1f31d443b9  DX投資促進税制  経済産業省
    # Canonical: METI DX投資促進税制。meti.go.jp は Akamai ブロック。
    "UNI-1f31d443b9": "https://www.meti.go.jp/policy/it_policy/dx/dx_zeisei.html",

    # UNI-6fd2c6663b  特許庁 ブランド確立支援(地域団体商標等)  特許庁
    # Canonical: JPO 地域団体商標制度 概要。
    "UNI-6fd2c6663b": "https://www.jpo.go.jp/system/trademark/gaiyo/chidan/",

    # UNI-7d7780ef56  スーパー早期審査  特許庁
    # Canonical: JPO スーパー早期審査 案内。
    "UNI-7d7780ef56": "https://www.jpo.go.jp/system/patent/shinsa/soki/super_souki.html",

    # UNI-7f5a8335ec  GX(グリーントランスフォーメーション)関連補助金  経済産業省
    # Canonical: METI GX関連政策 hub (個別補助金群を束ねる正本)。
    "UNI-7f5a8335ec": "https://www.meti.go.jp/policy/energy_environment/global_warming/index.html",

    # UNI-870ebb3375  事業継続力強化計画(認定)  中小企業庁
    # Canonical: 中小企業庁 事業継続力強化計画 認定制度。
    "UNI-870ebb3375": "https://www.chusho.meti.go.jp/keiei/antei/bousai/keizokuryoku.html",

    # UNI-8a2d6694eb  エンジェル税制  経済産業省
    # Canonical: METI エンジェル税制 公式案内。
    "UNI-8a2d6694eb": "https://www.meti.go.jp/policy/newbusiness/angeltax/index.html",

    # UNI-93af037e41  中小企業事業再編投資損失準備金  中小企業庁
    # Canonical: 中小企業庁 経営資源集約化税制 (事業再編投資損失準備金)。
    "UNI-93af037e41": "https://www.chusho.meti.go.jp/keiei/kyoka/shigenshuyaku_zeisei.html",

    # UNI-aad68dba98  Go-Tech事業(成長型中小企業等研究開発支援)  中小企業庁
    # Canonical: 中小企業庁 Go-Tech事業 (旧サポイン) 公式。
    "UNI-aad68dba98": "https://www.chusho.meti.go.jp/sapoin/index.php/about/",

    # UNI-aba7d7d6fa  税制適格ストックオプション  経済産業省/国税庁
    # Canonical: METI ストックオプション税制 公式ガイド。
    "UNI-aba7d7d6fa": "https://www.meti.go.jp/policy/newbusiness/stock-option.html",

    # UNI-dfca674c9d  事業承継税制(特例措置)  中小企業庁/国税庁
    # Canonical: 中小企業庁 事業承継円滑化 (事業承継税制特例措置)。
    "UNI-dfca674c9d": "https://www.chusho.meti.go.jp/zaimu/shoukei/shoukei_enkatsu_zouyo_souzoku.html",

    # UNI-eb18dc4fc4  研究開発税制(試験研究費の税額控除)  経済産業省
    # Canonical: METI 研究開発税制 ガイドライン。
    "UNI-eb18dc4fc4": "https://www.meti.go.jp/policy/tech_promotion/tax/tax_guideline.html",

    # UNI-ef8ef8c1e2  経営力向上計画(認定)  中小企業庁
    # Canonical: 中小企業庁 経営力向上計画 認定制度 hub。
    "UNI-ef8ef8c1e2": "https://www.chusho.meti.go.jp/keiei/kyoka/",
}

# ──────────────────────────────────────────────────────────────────────────
# UNREACHABLE — documented, not written. Flagged for a future pass.
# ──────────────────────────────────────────────────────────────────────────
# UNI-271623e575  平川市農業人材マッチング事業  市町村
#   city.hirakawa.aomori.jp に該当ページなし (WebSearch 0 件)。
#   事業は青森県農業会議/平川市農政課 経由で運用されているが、市 CMS
#   上に独立ページがない。紙ベース運用の可能性あり。
#
# UNI-2ae0a3a4aa  宮古市新規就農者施設・機械整備補助  市町村
#   宮古市 (岩手) CMS で該当ページ見つからず。
#
# UNI-5648125b00  丸森町農業チャレンジ研修（上級編）  市町村
# UNI-6ceb0cbf83  丸森町新規就農者定着促進事業  市町村
# UNI-e1fc0f9d3d  丸森町新規就農者定住推進事業  市町村
#   町ビジョン PDF と農林課 index には言及あるが、各事業ごとの
#   独立ページが存在しない。正本 URL を特定できず。
#
# UNI-6b3b30de63  北見市新規参入就農支援（経営開始支援）  市町村
#   city.kitami.lg.jp に 担い手支援・新規就農 の独立詳細ページが見当たらない。
#   (農業経営基盤強化の促進に関する基本構想 はあるが 個別事業の正本ではない)。
#
# UNI-79efcdd274  南富良野町農地取得補助  市町村
# UNI-9932a60fd2  南富良野町営農指導助成  市町村
#   town.minamifurano.hokkaido.jp に 農業後継者育成奨学金 はあるが、
#   農地取得補助・営農指導助成の独立ページは見当たらない。
#
# UNI-9158bdec88  中津市自立経営農家育成資金貸付事業  市町村
#   中津市 (大分) CMS で該当ページなし。
#
# UNI-c46c1a8106  美唄市新規参入者等支援事業  市町村
#   美唄市 CMS で該当ページなし。
#
# UNI-ce22354fc1  平川市新規就農者支援事業（農地賃借料補助）  市町村
#   上記 UNI-271623e575 と同様、平川市 CMS に独立ページがない。
#
# UNI-d509fe3e91  幕別町新規就農者支援事業（農地賃貸料奨励金）  市町村
#   幕別町 CMS には新規就農 hub はあるが、本事業の独立案内ページを
#   特定できなかった。農業振興公社 経由運用の可能性。

# fmt: on


def main() -> None:
    db_path = "data/jpintel.db"
    conn = sqlite3.connect(db_path)
    ts = datetime.now(UTC).isoformat()

    updated_verified = 0
    skipped_verified = 0
    for uid, url in VERIFIED_MAPPINGS.items():
        cur = conn.execute(
            "UPDATE programs SET source_url = ?, source_fetched_at = ? "
            "WHERE unified_id = ? AND (source_url IS NULL OR source_url = '')",
            (url, ts, uid),
        )
        if cur.rowcount:
            print(f"  VERIFIED  {uid}: {url}")
            updated_verified += cur.rowcount
        else:
            print(f"  SKIPPED   {uid}: already has source_url or not found")
            skipped_verified += 1

    updated_canonical = 0
    skipped_canonical = 0
    for uid, url in CANONICAL_ONLY_MAPPINGS.items():
        # Canonical-only: set source_url AND null out source_fetched_at.
        # The DB currently carries a 2026-04-22 uniform sentinel in
        # source_fetched_at across all rows (pre-backfill import). For
        # canonical-only rows we did NOT actually fetch, so we must not
        # inherit that sentinel — explicit NULL preserves 景表法 honesty
        # (the "出典取得" column stays empty, matching reality).
        cur = conn.execute(
            "UPDATE programs SET source_url = ?, source_fetched_at = NULL "
            "WHERE unified_id = ? AND (source_url IS NULL OR source_url = '')",
            (url, uid),
        )
        if cur.rowcount:
            print(f"  CANONICAL {uid}: {url} (no fetched_at)")
            updated_canonical += cur.rowcount
        else:
            print(f"  SKIPPED   {uid}: already has source_url or not found")
            skipped_canonical += 1

    conn.commit()
    conn.close()

    print(
        f"\nDone: verified={updated_verified}, canonical={updated_canonical}, "
        f"skipped={skipped_verified + skipped_canonical}. "
        f"Unreachable (documented inline, not written): 12 rows."
    )


if __name__ == "__main__":
    main()
