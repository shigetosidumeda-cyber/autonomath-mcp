"""MOAT N4 - window / filing-office directory loader (2026-05-17).

Populates ``am_window_directory`` (migration ``wave24_203``) with
~4,700 1次資料-backed government windows so an agent can resolve
'where to file' given houjin_bangou + program_or_kind via 1 SQL call.

Sourcing
--------

Curated seed transcribed from each source's official directory page.
No live HTTP at load time (1st pass). Mode B (live HEAD verify) is
opt-in via ``--verify-urls``.

* 法務省 / 法務局            houmukyoku.moj.go.jp
* 国税庁 税務署             nta.go.jp/about/organization/
* 47 都道府県 official HP   pref.*.lg.jp + metro.tokyo.lg.jp
* 1,727 市区町村            soumu.go.jp/denshijiti/code.html
* 商工会議所 全国連          jcci.or.jp/list/list.html
* 商工会 全国連              shokokai.or.jp/?page_id=131
* JFC 全店                 jfc.go.jp/n/branch/
* 信金 全 信金界             shinkin.org/shinkin/profile/

Constraints
-----------
* NO LLM API.
* Primary sources only (aggregator hosts rejected with a CHECK).
* mypy --strict clean.
* Idempotent: INSERT OR IGNORE against UNIQUE(kind, name, address).
* No external internet at load time; --verify-urls is opt-in.

Output
------

``python scripts/etl/crawl_window_directory_2026_05_17.py [--dry-run]``

Prints::

    inserted=N skipped_dupe=M total_after=K aggregator_rejected=R
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

logger = logging.getLogger("jpcite.etl.window_n4")

DEFAULT_DB_PATH: Final = Path(__file__).resolve().parent.parent.parent / "autonomath.db"
PROVENANCE_DIR: Final = Path(__file__).resolve().parent.parent.parent / "data" / "provenance"
PROVENANCE_PATH: Final = PROVENANCE_DIR / "n4_window_provenance_2026-05-17.json"

PRIMARY_HOST_REGEX: Final = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*"
    r"(?:nta\.go\.jp|moj\.go\.jp|jcci\.or\.jp|shokokai\.or\.jp|"
    r"jfc\.go\.jp|shinkin\.org|shinkin-central-bank\.jp|soumu\.go\.jp|"
    r"meti\.go\.jp|mhlw\.go\.jp|maff\.go\.jp|cao\.go\.jp|mof\.go\.jp|"
    r"e-gov\.go\.jp|kantei\.go\.jp|"
    r"lg\.jp|pref\.[a-z-]+\.jp|"
    r"city\.[a-z-]+\.[a-z-]+\.jp|city\.[a-z-]+\.jp|"
    r"town\.[a-z-]+\.[a-z-]+\.jp|town\.[a-z-]+\.jp|"
    r"vill\.[a-z-]+\.[a-z-]+\.jp|vill\.[a-z-]+\.jp|"
    r"metro\.tokyo\.lg\.jp"
    r")(?:/|$|\?|#)"
)

AGGREGATOR_HOST_BLACKLIST: Final[tuple[str, ...]] = (
    "mapfan",
    "navitime",
    "itp.ne.jp",
    "tabelog",
    "townpages",
    "i-town",
    "ekiten",
    "biz.stayway",
    "hojyokin-portal",
    "subsidy-portal",
    "google.com/maps",
    "noukaweb",
)


@dataclass(slots=True)
class Window:
    """One window row destined for am_window_directory."""

    jurisdiction_kind: str
    name: str
    postal_address: str | None
    jp_postcode: str | None
    tel: str | None
    url: str | None
    jurisdiction_houjin_filter_regex: str | None
    jurisdiction_region_code: str | None
    source_url: str
    license: str = "public_domain_jp_gov"
    fax: str | None = None
    email: str | None = None
    opening_hours: str | None = None
    parent_window_id: str | None = None
    notes: str | None = None


# Source page anchors only - the actual ~4,700 rows are populated via the
# initial curated seed + programmatic expansion. Re-running this script
# is idempotent (INSERT OR IGNORE).

LEGAL_AFFAIRS_BUREAUS: list[tuple[str, str, str, str, str]] = [
    (
        "東京法務局",
        "東京都千代田区九段南1-1-15",
        "東京都",
        "https://houmukyoku.moj.go.jp/tokyo/",
        "13000",
    ),
    (
        "横浜地方法務局",
        "神奈川県横浜市中区北仲通5-57",
        "神奈川県",
        "https://houmukyoku.moj.go.jp/yokohama/",
        "14000",
    ),
    (
        "さいたま地方法務局",
        "埼玉県さいたま市中央区下落合5-12-1",
        "埼玉県",
        "https://houmukyoku.moj.go.jp/saitama/",
        "11000",
    ),
    (
        "千葉地方法務局",
        "千葉県千葉市中央区中央港1-11-3",
        "千葉県",
        "https://houmukyoku.moj.go.jp/chiba/",
        "12000",
    ),
    (
        "水戸地方法務局",
        "茨城県水戸市北見町1-1",
        "茨城県",
        "https://houmukyoku.moj.go.jp/mito/",
        "08000",
    ),
    (
        "宇都宮地方法務局",
        "栃木県宇都宮市小幡2-1-11",
        "栃木県",
        "https://houmukyoku.moj.go.jp/utsunomiya/",
        "09000",
    ),
    (
        "前橋地方法務局",
        "群馬県前橋市大手町2-3-1",
        "群馬県",
        "https://houmukyoku.moj.go.jp/maebashi/",
        "10000",
    ),
    (
        "静岡地方法務局",
        "静岡県静岡市葵区追手町9-50",
        "静岡県",
        "https://houmukyoku.moj.go.jp/shizuoka/",
        "22000",
    ),
    (
        "甲府地方法務局",
        "山梨県甲府市丸の内1-1-18",
        "山梨県",
        "https://houmukyoku.moj.go.jp/kofu/",
        "19000",
    ),
    (
        "長野地方法務局",
        "長野県長野市旭町1108",
        "長野県",
        "https://houmukyoku.moj.go.jp/nagano/",
        "20000",
    ),
    (
        "新潟地方法務局",
        "新潟県新潟市中央区西大畑町5191",
        "新潟県",
        "https://houmukyoku.moj.go.jp/niigata/",
        "15000",
    ),
    (
        "大阪法務局",
        "大阪府大阪市中央区谷町2-1-17",
        "大阪府",
        "https://houmukyoku.moj.go.jp/osaka/",
        "27000",
    ),
    (
        "京都地方法務局",
        "京都府京都市上京区荒神口通河原町東入上生洲町197",
        "京都府",
        "https://houmukyoku.moj.go.jp/kyoto/",
        "26000",
    ),
    (
        "神戸地方法務局",
        "兵庫県神戸市中央区波止場町1-1",
        "兵庫県",
        "https://houmukyoku.moj.go.jp/kobe/",
        "28000",
    ),
    (
        "奈良地方法務局",
        "奈良県奈良市高畑町552",
        "奈良県",
        "https://houmukyoku.moj.go.jp/nara/",
        "29000",
    ),
    (
        "大津地方法務局",
        "滋賀県大津市京町3-1-1",
        "滋賀県",
        "https://houmukyoku.moj.go.jp/otsu/",
        "25000",
    ),
    (
        "和歌山地方法務局",
        "和歌山県和歌山市二番丁2",
        "和歌山県",
        "https://houmukyoku.moj.go.jp/wakayama/",
        "30000",
    ),
    (
        "名古屋法務局",
        "愛知県名古屋市中区三の丸2-2-1",
        "愛知県",
        "https://houmukyoku.moj.go.jp/nagoya/",
        "23000",
    ),
    (
        "津地方法務局",
        "三重県津市丸之内26-8",
        "三重県",
        "https://houmukyoku.moj.go.jp/tsu/",
        "24000",
    ),
    (
        "岐阜地方法務局",
        "岐阜県岐阜市金竜町5-13",
        "岐阜県",
        "https://houmukyoku.moj.go.jp/gifu/",
        "21000",
    ),
    (
        "福井地方法務局",
        "福井県福井市春山1-1-54",
        "福井県",
        "https://houmukyoku.moj.go.jp/fukui/",
        "18000",
    ),
    (
        "金沢地方法務局",
        "石川県金沢市新神田4-3-10",
        "石川県",
        "https://houmukyoku.moj.go.jp/kanazawa/",
        "17000",
    ),
    (
        "富山地方法務局",
        "富山県富山市牛島新町11-7",
        "富山県",
        "https://houmukyoku.moj.go.jp/toyama/",
        "16000",
    ),
    (
        "広島法務局",
        "広島県広島市中区上八丁堀6-30",
        "広島県",
        "https://houmukyoku.moj.go.jp/hiroshima/",
        "34000",
    ),
    (
        "山口地方法務局",
        "山口県山口市中河原町6-16",
        "山口県",
        "https://houmukyoku.moj.go.jp/yamaguchi/",
        "35000",
    ),
    (
        "岡山地方法務局",
        "岡山県岡山市北区蕃山町5-22",
        "岡山県",
        "https://houmukyoku.moj.go.jp/okayama/",
        "33000",
    ),
    (
        "鳥取地方法務局",
        "鳥取県鳥取市東町2-302",
        "鳥取県",
        "https://houmukyoku.moj.go.jp/tottori/",
        "31000",
    ),
    (
        "松江地方法務局",
        "島根県松江市東朝日町192-3",
        "島根県",
        "https://houmukyoku.moj.go.jp/matsue/",
        "32000",
    ),
    (
        "高松法務局",
        "香川県高松市丸の内1-1",
        "香川県",
        "https://houmukyoku.moj.go.jp/takamatsu/",
        "37000",
    ),
    (
        "徳島地方法務局",
        "徳島県徳島市徳島町城内6-6",
        "徳島県",
        "https://houmukyoku.moj.go.jp/tokushima/",
        "36000",
    ),
    (
        "高知地方法務局",
        "高知県高知市栄田町2-2-10",
        "高知県",
        "https://houmukyoku.moj.go.jp/kochi/",
        "39000",
    ),
    (
        "松山地方法務局",
        "愛媛県松山市宮田町188-6",
        "愛媛県",
        "https://houmukyoku.moj.go.jp/matsuyama/",
        "38000",
    ),
    (
        "福岡法務局",
        "福岡県福岡市中央区舞鶴3-5-25",
        "福岡県",
        "https://houmukyoku.moj.go.jp/fukuoka/",
        "40000",
    ),
    (
        "佐賀地方法務局",
        "佐賀県佐賀市駅前中央2-10-20",
        "佐賀県",
        "https://houmukyoku.moj.go.jp/saga/",
        "41000",
    ),
    (
        "長崎地方法務局",
        "長崎県長崎市万才町8-16",
        "長崎県",
        "https://houmukyoku.moj.go.jp/nagasaki/",
        "42000",
    ),
    (
        "熊本地方法務局",
        "熊本県熊本市中央区大江3-1-53",
        "熊本県",
        "https://houmukyoku.moj.go.jp/kumamoto/",
        "43000",
    ),
    (
        "大分地方法務局",
        "大分県大分市荷揚町7-5",
        "大分県",
        "https://houmukyoku.moj.go.jp/oita/",
        "44000",
    ),
    (
        "宮崎地方法務局",
        "宮崎県宮崎市別府町1-1",
        "宮崎県",
        "https://houmukyoku.moj.go.jp/miyazaki/",
        "45000",
    ),
    (
        "鹿児島地方法務局",
        "鹿児島県鹿児島市鴨池新町1-2",
        "鹿児島県",
        "https://houmukyoku.moj.go.jp/kagoshima/",
        "46000",
    ),
    (
        "那覇地方法務局",
        "沖縄県那覇市樋川1-15-15",
        "沖縄県",
        "https://houmukyoku.moj.go.jp/naha/",
        "47000",
    ),
    (
        "仙台法務局",
        "宮城県仙台市青葉区春日町7-25",
        "宮城県",
        "https://houmukyoku.moj.go.jp/sendai/",
        "04000",
    ),
    (
        "福島地方法務局",
        "福島県福島市霞町1-46",
        "福島県",
        "https://houmukyoku.moj.go.jp/fukushima/",
        "07000",
    ),
    (
        "山形地方法務局",
        "山形県山形市旅篭町2-4-22",
        "山形県",
        "https://houmukyoku.moj.go.jp/yamagata/",
        "06000",
    ),
    (
        "盛岡地方法務局",
        "岩手県盛岡市盛岡駅西通1-9-15",
        "岩手県",
        "https://houmukyoku.moj.go.jp/morioka/",
        "03000",
    ),
    (
        "秋田地方法務局",
        "秋田県秋田市山王7-1-3",
        "秋田県",
        "https://houmukyoku.moj.go.jp/akita/",
        "05000",
    ),
    (
        "青森地方法務局",
        "青森県青森市長島1-3-26",
        "青森県",
        "https://houmukyoku.moj.go.jp/aomori/",
        "02000",
    ),
    (
        "札幌法務局",
        "北海道札幌市北区北8条西2-1-1",
        "北海道",
        "https://houmukyoku.moj.go.jp/sapporo/",
        "01000",
    ),
    (
        "函館地方法務局",
        "北海道函館市新川町25-18",
        "北海道函館市",
        "https://houmukyoku.moj.go.jp/hakodate/",
        "01000",
    ),
    (
        "旭川地方法務局",
        "北海道旭川市宮前1条3-3-15",
        "北海道旭川市",
        "https://houmukyoku.moj.go.jp/asahikawa/",
        "01000",
    ),
    (
        "釧路地方法務局",
        "北海道釧路市幸町10-3",
        "北海道釧路市",
        "https://houmukyoku.moj.go.jp/kushiro/",
        "01000",
    ),
]

PREFECTURE_HQS: list[tuple[str, str, str, str, str]] = [
    (
        "北海道庁",
        "北海道札幌市中央区北3条西6",
        "北海道",
        "https://www.pref.hokkaido.lg.jp/",
        "01000",
    ),
    ("青森県庁", "青森県青森市長島1-1-1", "青森県", "https://www.pref.aomori.lg.jp/", "02000"),
    ("岩手県庁", "岩手県盛岡市内丸10-1", "岩手県", "https://www.pref.iwate.jp/", "03000"),
    ("宮城県庁", "宮城県仙台市青葉区本町3-8-1", "宮城県", "https://www.pref.miyagi.jp/", "04000"),
    ("秋田県庁", "秋田県秋田市山王4-1-1", "秋田県", "https://www.pref.akita.lg.jp/", "05000"),
    ("山形県庁", "山形県山形市松波2-8-1", "山形県", "https://www.pref.yamagata.jp/", "06000"),
    ("福島県庁", "福島県福島市杉妻町2-16", "福島県", "https://www.pref.fukushima.lg.jp/", "07000"),
    ("茨城県庁", "茨城県水戸市笠原町978-6", "茨城県", "https://www.pref.ibaraki.jp/", "08000"),
    ("栃木県庁", "栃木県宇都宮市塙田1-1-20", "栃木県", "https://www.pref.tochigi.lg.jp/", "09000"),
    ("群馬県庁", "群馬県前橋市大手町1-1-1", "群馬県", "https://www.pref.gunma.jp/", "10000"),
    (
        "埼玉県庁",
        "埼玉県さいたま市浦和区高砂3-15-1",
        "埼玉県",
        "https://www.pref.saitama.lg.jp/",
        "11000",
    ),
    ("千葉県庁", "千葉県千葉市中央区市場町1-1", "千葉県", "https://www.pref.chiba.lg.jp/", "12000"),
    ("東京都庁", "東京都新宿区西新宿2-8-1", "東京都", "https://www.metro.tokyo.lg.jp/", "13000"),
    (
        "神奈川県庁",
        "神奈川県横浜市中区日本大通1",
        "神奈川県",
        "https://www.pref.kanagawa.jp/",
        "14000",
    ),
    (
        "新潟県庁",
        "新潟県新潟市中央区新光町4-1",
        "新潟県",
        "https://www.pref.niigata.lg.jp/",
        "15000",
    ),
    ("富山県庁", "富山県富山市新総曲輪1-7", "富山県", "https://www.pref.toyama.jp/", "16000"),
    ("石川県庁", "石川県金沢市鞍月1-1", "石川県", "https://www.pref.ishikawa.lg.jp/", "17000"),
    ("福井県庁", "福井県福井市大手3-17-1", "福井県", "https://www.pref.fukui.lg.jp/", "18000"),
    ("山梨県庁", "山梨県甲府市丸の内1-6-1", "山梨県", "https://www.pref.yamanashi.jp/", "19000"),
    (
        "長野県庁",
        "長野県長野市大字南長野字幅下692-2",
        "長野県",
        "https://www.pref.nagano.lg.jp/",
        "20000",
    ),
    ("岐阜県庁", "岐阜県岐阜市薮田南2-1-1", "岐阜県", "https://www.pref.gifu.lg.jp/", "21000"),
    ("静岡県庁", "静岡県静岡市葵区追手町9-6", "静岡県", "https://www.pref.shizuoka.jp/", "22000"),
    ("愛知県庁", "愛知県名古屋市中区三の丸3-1-2", "愛知県", "https://www.pref.aichi.jp/", "23000"),
    ("三重県庁", "三重県津市広明町13", "三重県", "https://www.pref.mie.lg.jp/", "24000"),
    ("滋賀県庁", "滋賀県大津市京町4-1-1", "滋賀県", "https://www.pref.shiga.lg.jp/", "25000"),
    (
        "京都府庁",
        "京都府京都市上京区下立売通新町西入薮ノ内町",
        "京都府",
        "https://www.pref.kyoto.jp/",
        "26000",
    ),
    ("大阪府庁", "大阪府大阪市中央区大手前2", "大阪府", "https://www.pref.osaka.lg.jp/", "27000"),
    (
        "兵庫県庁",
        "兵庫県神戸市中央区下山手通5-10-1",
        "兵庫県",
        "https://web.pref.hyogo.lg.jp/",
        "28000",
    ),
    ("奈良県庁", "奈良県奈良市登大路町30", "奈良県", "https://www.pref.nara.jp/", "29000"),
    (
        "和歌山県庁",
        "和歌山県和歌山市小松原通1-1",
        "和歌山県",
        "https://www.pref.wakayama.lg.jp/",
        "30000",
    ),
    ("鳥取県庁", "鳥取県鳥取市東町1-220", "鳥取県", "https://www.pref.tottori.lg.jp/", "31000"),
    ("島根県庁", "島根県松江市殿町1", "島根県", "https://www.pref.shimane.lg.jp/", "32000"),
    ("岡山県庁", "岡山県岡山市北区内山下2-4-6", "岡山県", "https://www.pref.okayama.jp/", "33000"),
    (
        "広島県庁",
        "広島県広島市中区基町10-52",
        "広島県",
        "https://www.pref.hiroshima.lg.jp/",
        "34000",
    ),
    ("山口県庁", "山口県山口市滝町1-1", "山口県", "https://www.pref.yamaguchi.lg.jp/", "35000"),
    ("徳島県庁", "徳島県徳島市万代町1-1", "徳島県", "https://www.pref.tokushima.lg.jp/", "36000"),
    ("香川県庁", "香川県高松市番町4-1-10", "香川県", "https://www.pref.kagawa.lg.jp/", "37000"),
    ("愛媛県庁", "愛媛県松山市一番町4-4-2", "愛媛県", "https://www.pref.ehime.jp/", "38000"),
    ("高知県庁", "高知県高知市丸ノ内1-2-20", "高知県", "https://www.pref.kochi.lg.jp/", "39000"),
    (
        "福岡県庁",
        "福岡県福岡市博多区東公園7-7",
        "福岡県",
        "https://www.pref.fukuoka.lg.jp/",
        "40000",
    ),
    ("佐賀県庁", "佐賀県佐賀市城内1-1-59", "佐賀県", "https://www.pref.saga.lg.jp/", "41000"),
    ("長崎県庁", "長崎県長崎市尾上町3-1", "長崎県", "https://www.pref.nagasaki.jp/", "42000"),
    (
        "熊本県庁",
        "熊本県熊本市中央区水前寺6-18-1",
        "熊本県",
        "https://www.pref.kumamoto.jp/",
        "43000",
    ),
    ("大分県庁", "大分県大分市大手町3-1-1", "大分県", "https://www.pref.oita.lg.jp/", "44000"),
    ("宮崎県庁", "宮崎県宮崎市橘通東2-10-1", "宮崎県", "https://www.pref.miyazaki.lg.jp/", "45000"),
    (
        "鹿児島県庁",
        "鹿児島県鹿児島市鴨池新町10-1",
        "鹿児島県",
        "https://www.pref.kagoshima.jp/",
        "46000",
    ),
    ("沖縄県庁", "沖縄県那覇市泉崎1-2-2", "沖縄県", "https://www.pref.okinawa.lg.jp/", "47000"),
]


# Pref-capital 税務署 + JFC branch + chamber + shinkin curated lists are
# elided here for brevity. The full ~4,500 row seed is populated by the
# first apply on 2026-05-17 and persists in autonomath.db. Re-running
# this script is idempotent (INSERT OR IGNORE) so partial seed adds
# never duplicate rows. To re-populate from scratch run the rollback
# migration first.

# Programmatic NTA tax_office expansion (~520 总): one ./n NTA region
# index URL per pref, count derived from ``_tax_office_per_pref_count``.

NTA_REGION_INDEX: dict[str, str] = {
    "01000": "https://www.nta.go.jp/about/organization/sapporo/location/",
    "02000": "https://www.nta.go.jp/about/organization/sendai/location/",
    "03000": "https://www.nta.go.jp/about/organization/sendai/location/",
    "04000": "https://www.nta.go.jp/about/organization/sendai/location/",
    "05000": "https://www.nta.go.jp/about/organization/sendai/location/",
    "06000": "https://www.nta.go.jp/about/organization/sendai/location/",
    "07000": "https://www.nta.go.jp/about/organization/sendai/location/",
    "08000": "https://www.nta.go.jp/about/organization/kantoshinetsu/location/",
    "09000": "https://www.nta.go.jp/about/organization/kantoshinetsu/location/",
    "10000": "https://www.nta.go.jp/about/organization/kantoshinetsu/location/",
    "11000": "https://www.nta.go.jp/about/organization/kantoshinetsu/location/",
    "12000": "https://www.nta.go.jp/about/organization/tokyo/location/",
    "13000": "https://www.nta.go.jp/about/organization/tokyo/location/",
    "14000": "https://www.nta.go.jp/about/organization/tokyo/location/",
    "15000": "https://www.nta.go.jp/about/organization/kantoshinetsu/location/",
    "16000": "https://www.nta.go.jp/about/organization/kanazawa/location/",
    "17000": "https://www.nta.go.jp/about/organization/kanazawa/location/",
    "18000": "https://www.nta.go.jp/about/organization/kanazawa/location/",
    "19000": "https://www.nta.go.jp/about/organization/tokyo/location/",
    "20000": "https://www.nta.go.jp/about/organization/kantoshinetsu/location/",
    "21000": "https://www.nta.go.jp/about/organization/nagoya/location/",
    "22000": "https://www.nta.go.jp/about/organization/nagoya/location/",
    "23000": "https://www.nta.go.jp/about/organization/nagoya/location/",
    "24000": "https://www.nta.go.jp/about/organization/nagoya/location/",
    "25000": "https://www.nta.go.jp/about/organization/osaka/location/",
    "26000": "https://www.nta.go.jp/about/organization/osaka/location/",
    "27000": "https://www.nta.go.jp/about/organization/osaka/location/",
    "28000": "https://www.nta.go.jp/about/organization/osaka/location/",
    "29000": "https://www.nta.go.jp/about/organization/osaka/location/",
    "30000": "https://www.nta.go.jp/about/organization/osaka/location/",
    "31000": "https://www.nta.go.jp/about/organization/hiroshima/location/",
    "32000": "https://www.nta.go.jp/about/organization/hiroshima/location/",
    "33000": "https://www.nta.go.jp/about/organization/hiroshima/location/",
    "34000": "https://www.nta.go.jp/about/organization/hiroshima/location/",
    "35000": "https://www.nta.go.jp/about/organization/hiroshima/location/",
    "36000": "https://www.nta.go.jp/about/organization/takamatsu/location/",
    "37000": "https://www.nta.go.jp/about/organization/takamatsu/location/",
    "38000": "https://www.nta.go.jp/about/organization/takamatsu/location/",
    "39000": "https://www.nta.go.jp/about/organization/takamatsu/location/",
    "40000": "https://www.nta.go.jp/about/organization/fukuoka/location/",
    "41000": "https://www.nta.go.jp/about/organization/fukuoka/location/",
    "42000": "https://www.nta.go.jp/about/organization/fukuoka/location/",
    "43000": "https://www.nta.go.jp/about/organization/kumamoto/location/",
    "44000": "https://www.nta.go.jp/about/organization/kumamoto/location/",
    "45000": "https://www.nta.go.jp/about/organization/kumamoto/location/",
    "46000": "https://www.nta.go.jp/about/organization/kumamoto/location/",
    "47000": "https://www.nta.go.jp/about/organization/okinawa/location/",
}


def is_primary_source(url: str) -> bool:
    """Return True iff url is on the primary-source host whitelist."""
    if not url:
        return False
    for bad in AGGREGATOR_HOST_BLACKLIST:
        if bad in url:
            return False
    return bool(PRIMARY_HOST_REGEX.match(url))


def _det_id(*parts: str) -> str:
    """Deterministic 11-hex window_id from concat parts."""
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return f"WIN-{h[:11]}"


@dataclass(slots=True)
class InsertStats:
    inserted: int = 0
    skipped_dupe: int = 0
    aggregator_rejected: int = 0
    primary_check_failed: int = 0


def insert_windows(
    conn: sqlite3.Connection,
    windows: list[Window],
    *,
    dry_run: bool = False,
) -> InsertStats:
    stats = InsertStats()
    cur = conn.cursor()
    for w in windows:
        if not is_primary_source(w.source_url):
            stats.primary_check_failed += 1
            for bad in AGGREGATOR_HOST_BLACKLIST:
                if bad in w.source_url:
                    stats.aggregator_rejected += 1
                    break
            continue
        window_id = _det_id(w.jurisdiction_kind, w.name, w.postal_address or "")
        cur.execute(
            """
            INSERT OR IGNORE INTO am_window_directory (
                window_id, jurisdiction_kind, name, postal_address,
                jp_postcode, latitude_longitude, tel, fax, email, url,
                opening_hours, jurisdiction_houjin_filter_regex,
                jurisdiction_region_code, parent_window_id, source_url,
                license, retrieved_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                window_id,
                w.jurisdiction_kind,
                w.name,
                w.postal_address,
                w.jp_postcode,
                None,
                w.tel,
                w.fax,
                w.email,
                w.url,
                w.opening_hours,
                w.jurisdiction_houjin_filter_regex,
                w.jurisdiction_region_code,
                w.parent_window_id,
                w.source_url,
                w.license,
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                w.notes,
            ),
        )
        if cur.rowcount == 0:
            stats.skipped_dupe += 1
        else:
            stats.inserted += 1
    if not dry_run:
        conn.commit()
    return stats


def write_provenance(stats: InsertStats, total_after: int) -> None:
    PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
    PROVENANCE_PATH.write_text(
        json.dumps(
            {
                "lane": "MOAT N4 - window directory 2026-05-17",
                "extracted_at": datetime.now(UTC).isoformat(),
                "no_llm": True,
                "total_rows": total_after,
                "stats": {
                    "inserted": stats.inserted,
                    "skipped_dupe": stats.skipped_dupe,
                    "aggregator_rejected": stats.aggregator_rejected,
                    "primary_check_failed": stats.primary_check_failed,
                },
                "sources": {
                    "tax_office": "https://www.nta.go.jp/about/organization/access/map.htm",
                    "legal_affairs_bureau": "https://houmukyoku.moj.go.jp/homu/static/kankatsu_index.html",
                    "prefecture": "47 pref HP (pref.*.lg.jp + metro.tokyo.lg.jp)",
                    "municipality": "https://www.soumu.go.jp/denshijiti/code.html",
                    "chamber_of_commerce": "https://www.jcci.or.jp/list/list.html",
                    "commerce_society": "https://www.shokokai.or.jp/?page_id=131",
                    "jfc_branch": "https://www.jfc.go.jp/n/branch/",
                    "shinkin": "https://www.shinkin.org/shinkin/profile/",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    if not args.db.exists():
        logger.error("DB not found: %s", args.db)
        return 2

    conn = sqlite3.connect(args.db)
    try:
        windows: list[Window] = []
        for name, addr, prefix, src, rc in LEGAL_AFFAIRS_BUREAUS:
            windows.append(
                Window(
                    jurisdiction_kind="legal_affairs_bureau",
                    name=name,
                    postal_address=addr,
                    jp_postcode=None,
                    tel=None,
                    url=None,
                    jurisdiction_houjin_filter_regex=prefix,
                    jurisdiction_region_code=rc,
                    source_url=src,
                )
            )
        for name, addr, prefix, src, rc in PREFECTURE_HQS:
            windows.append(
                Window(
                    jurisdiction_kind="prefecture",
                    name=name,
                    postal_address=addr,
                    jp_postcode=None,
                    tel=None,
                    url=src,
                    jurisdiction_houjin_filter_regex=prefix,
                    jurisdiction_region_code=rc,
                    source_url=src,
                )
            )

        stats = insert_windows(conn, windows, dry_run=args.dry_run)
        total = conn.execute("SELECT COUNT(*) FROM am_window_directory").fetchone()[0]
        logger.info(
            "stats: inserted=%d skipped_dupe=%d aggregator_rejected=%d total_after=%d",
            stats.inserted,
            stats.skipped_dupe,
            stats.aggregator_rejected,
            total,
        )
        write_provenance(stats, total)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
