#!/usr/bin/env python3
"""Ingest 建築基準法・消防法・危険物保安法・高圧ガス保安法 違反による
行政処分 (是正命令・使用停止・許可取消) into ``am_enforcement_detail``.

Background:
  Existing 建築士法 + 宅建業法 rows from
  ``ingest_enforcement_mlit_kenchikushi_takken.py`` (W26) live under
  ``record_kind='enforcement', source_topic='mlit_*'`` and target
  individual 建築士 / 宅建業者. THIS script targets a different cluster:
  buildings/structures/facilities themselves under

    建築基準法 第9条 (是正命令・工事施工停止・使用禁止・除却命令)
    消防法 第5条 / 第5条の3 (措置命令・使用停止命令)
    消防法 第8条 / 第17条 (重大な防火対象物 違反対象物公表制度)
    高圧ガス保安法 第38条 (許可取消・事業停止)

  All three categories are 都道府県知事/市町村長 (or 経産省 産業保安G) 発の
  公表/命令データで、被処分者は法人/個人どちらもあり得る。

Sources (primary only — aggregators BANNED):
  ── 建築基準法 違反建築物 ──
    pref.{slug}.lg.jp / city.{slug}.lg.jp の建築指導課等

  ── 消防法 違反対象物公表制度 ──
    総務省消防庁 fdma.go.jp/relocation/publication/ 経由で都道府県別の
    消防本部リンク集に到達。各市消防局/消防本部の公表ページ。

  ── 高圧ガス保安法 ──
    経産省 meti.go.jp/press/ ENEOS / 太陽石油 等の press release.
    (主要事業者のみ press 発表あり、件数限定的)

Strategy:
  - Curated SOURCES per source-type, all HTML (no PDF/XLS in scope this run).
  - Format-aware parsers:
      table_7col_kenchiku (大阪府/大阪市 type) ─ 命令施行日 / 所在地 / 対象者氏名 / 住所 / 用途 / 処分内容 / 備考
      table_yokohama_fire (横浜市 type)        ─ 行政区 / 名称 / 所在地 / 違反内容 / 根拠条項 / 違反位置 / その他
      table_chiba_fire (千葉市 type)            ─ 区別小見出し → 名称/所在地/違反/年月日 各セル
      table_kawasaki_fire (川崎市 type)        ─ 名称 / 所在地 / 違反 / 適用条項 / 公表日 / 消防署
      table_nagoya_fire (名古屋市 type)        ─ 区別ブロック → 名称/所在地/違反/公表日
      generic_fire_table_html (fallback)       ─ 他の自治体 (1-5 件) の wide variation 吸収

Schema mapping (am_enforcement_detail.enforcement_kind CHECK):
    工事施工停止 / 工事の施工停止 / 是正命令     → business_improvement
    使用禁止 / 使用停止 / 営業停止                → contract_suspend
    除却 / 撤去 / 取壊し                          → contract_suspend (建物使用全面停止と同義)
    許可取消 / 認定取消                          → license_revoke
    重大な消防法令違反 (公表のみ)                → business_improvement
    その他                                        → other

issuing_authority (例):
    "大阪府"           (建築基準法 都道府県知事命令)
    "大阪市"           (政令市建築主事)
    "横浜市消防局"     (消防法 違反対象物公表)
    "経済産業省 関東東北産業保安監督部" (高圧ガス保安法)

Parallel-write contract:
  - BEGIN IMMEDIATE
  - PRAGMA busy_timeout = 300000
  - 50-row periodic commit
  - dedup against existing am_enforcement_detail (target_name + issuance_date
    + enforcement_kind) so re-runs are idempotent.

CLI:
    python scripts/ingest/ingest_enforcement_building_fire.py \
        --db autonomath.db [--stop-at 500] [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as html_lib
import json
import logging
import re
import sqlite3
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

DEFAULT_DB = REPO_ROOT / "autonomath.db"
HTML_MAX_BYTES = 4 * 1024 * 1024

_LOG = logging.getLogger("autonomath.ingest.building_fire")


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------


@dataclass
class Source:
    cluster: str  # "kenchiku" | "fire" | "kouatsu_gas"
    authority: str  # 大阪府 / 横浜市消防局 / etc.
    url: str
    parser: str  # parser hint
    law_basis_default: str  # 建築基準法第9条 / 消防法第17条 / etc.
    note: str = ""
    # The default kind assigned when row-level mapping fails.
    default_enforcement_kind: str = "business_improvement"


SOURCES: list[Source] = [
    # =====================================================================
    # 建築基準法 違反建築物 命令一覧 (prefecture / 政令市)
    # =====================================================================
    Source(
        "kenchiku",
        "大阪府",
        "https://www.pref.osaka.lg.jp/o130190/kenshi_anzen/ihan/index.html",
        "table_7col_kenchiku",
        "建築基準法第9条",
        note="都市計画法+建築基準法 命令一覧 / 大阪府知事",
    ),
    Source(
        "kenchiku",
        "大阪市",
        "https://www.city.osaka.lg.jp/toshikeikaku/page/0000112362.html",
        "table_5col_osaka_city",
        "建築基準法第9条",
        note="大阪市建築主事 命令建築物一覧",
    ),
    # =====================================================================
    # 消防法 違反対象物公表 一覧 (政令市 + 中核市 消防本部)
    # =====================================================================
    Source(
        "fire",
        "横浜市消防局",
        "https://www.city.yokohama.lg.jp/bousai-kyukyu-bohan/shobo/ihankenbutsu/ihankouhyou.html",
        "table_yokohama_fire",
        "消防法第17条",
        note="横浜市 違反公表制度",
    ),
    Source(
        "fire",
        "千葉市消防局",
        "https://www.city.chiba.jp/shobo/yobo/yobo/ihan_kohyo_list.html",
        "table_chiba_fire",
        "消防法第17条",
        note="千葉市 公表されている違反対象物",
    ),
    Source(
        "fire",
        "川崎市消防局",
        "https://www.city.kawasaki.jp/840/page/0000059518.html",
        "table_kawasaki_fire",
        "消防法第17条",
        note="川崎市 違反対象物公表",
    ),
    Source(
        "fire",
        "名古屋市消防局",
        "https://www.city.nagoya.jp/bousai/shoubou/1012727/1034497/1013168/1013171.html",
        "table_nagoya_fire",
        "消防法第17条",
        note="名古屋市 違反対象物 (区別)",
    ),
    Source(
        "fire",
        "東京消防庁",
        "https://www.tfd.metro.tokyo.lg.jp/kouhyou/kouji/com-sub.html",
        "generic_fire_html",
        "消防法第5条の3",
        note="東京消防庁 命令対象物一覧",
    ),
    Source(
        "fire",
        "東京消防庁",
        "https://www.tfd.metro.tokyo.lg.jp/kouhyou/kouji/ihan/ihan_02.html",
        "generic_fire_html",
        "消防法第8条の2の5",
        note="東京消防庁 違反対象物公表",
    ),
    Source(
        "fire",
        "札幌市消防局",
        "https://www.city.sapporo.jp/shobo/yobo/oshirase/ansinjouhou/tatemonoansin.html",
        "generic_fire_html",
        "消防法第17条",
        note="札幌市 建物の安心情報",
    ),
    Source(
        "fire",
        "京都市消防局",
        "https://www.city.kyoto.lg.jp/shobo/page/0000167890.html",
        "generic_fire_html",
        "消防法第17条",
        note="京都市 違反対象物公表",
    ),
    Source(
        "fire",
        "さいたま市消防局",
        "https://www.city.saitama.lg.jp/minuma/005/003/p100253.html",
        "table_minuma_fire",
        "消防法第17条",
        note="さいたま市 見沼区 違反対象物公表",
    ),
    Source(
        "fire",
        "柏市消防局",
        "https://www.city.kashiwa.lg.jp/yobo/fdk/anshinjoho/kasaiyobo/horeihan/taishobutsu.html",
        "generic_fire_html",
        "消防法第17条",
        note="柏市 違反対象物",
    ),
    Source(
        "fire",
        "横須賀市消防局",
        "https://www.city.yokosuka.kanagawa.jp/7415/kouji-kouhyou.html",
        "generic_fire_html",
        "消防法第5条",
        note="横須賀市 公示+違反対象物",
    ),
    Source(
        "fire",
        "相模原市消防局",
        "https://www.city.sagamihara.kanagawa.jp/kurashi/bousai/1023378/1023381/1027113.html",
        "generic_fire_html",
        "消防法第17条",
        note="相模原市 違反公表",
    ),
    Source(
        "fire",
        "藤沢市消防局",
        "http://www.city.fujisawa.kanagawa.jp/sasatu/bosai/shobo/sasatu/kohyo.html",
        "generic_fire_html",
        "消防法第17条",
        note="藤沢市 違反対象物",
    ),
    Source(
        "fire",
        "厚木市消防本部",
        "https://www.city.atsugi.kanagawa.jp/material/files/group/60/kouhyouihan.pdf",
        "generic_fire_html",
        "消防法第17条",
        note="厚木市 違反対象物 (PDF, skip parsing — listing only)",
    ),
    Source(
        "fire",
        "鎌倉市消防本部",
        "http://www.city.kamakura.kanagawa.jp/fd-yobou/kasaiyobou_meirei.html",
        "generic_fire_html",
        "消防法第5条",
        note="鎌倉市 火災予防命令",
    ),
    Source(
        "fire",
        "茅ヶ崎市消防本部",
        "https://www.city.chigasaki.kanagawa.jp/fire/oshirase/1023557.html",
        "generic_fire_html",
        "消防法第17条",
        note="茅ヶ崎市",
    ),
    Source(
        "fire",
        "小田原市消防本部",
        "https://www.city.odawara.kanagawa.jp/f-fight/safety/ihantaishoubutsu/p38280.html",
        "generic_fire_html",
        "消防法第17条",
        note="小田原市",
    ),
    Source(
        "fire",
        "綾瀬市消防本部",
        "https://www.city.ayase.kanagawa.jp/soshiki/yoboka/kasaiyobou/13399.html",
        "generic_fire_html",
        "消防法第17条",
        note="綾瀬市",
    ),
    Source(
        "fire",
        "海老名市消防本部",
        "https://www.city.ebina.kanagawa.jp/guide/kyukyu/1007244/1007314/1016855.html",
        "generic_fire_html",
        "消防法第17条",
        note="海老名市",
    ),
    Source(
        "fire",
        "大和市消防本部",
        "https://www.city.yamato.lg.jp/gyosei/soshik/56/boukabousaikannrikannkei/18300.html",
        "generic_fire_html",
        "消防法第17条",
        note="大和市",
    ),
    Source(
        "fire",
        "座間市消防本部",
        "https://www.city.zama.kanagawa.jp/kurashi/kyukyu/hourei/1001774.html",
        "generic_fire_html",
        "消防法第17条",
        note="座間市",
    ),
    # 大阪府下 消防本部
    Source(
        "fire",
        "堺市消防局",
        "https://www.city.sakai.lg.jp/kurashi/bosai/shobo/jigyosha/kasaiyobou/onegai/df_filename_3134.html",
        "generic_fire_html",
        "消防法第17条",
        note="堺市",
    ),
    Source(
        "fire",
        "豊中市消防局",
        "https://www.city.toyonaka.osaka.jp/kurashi/bosai/toyonakafiredept/info/ihan/a00120005000.html",
        "generic_fire_html",
        "消防法第17条",
        note="豊中市",
    ),
    Source(
        "fire",
        "茨木市消防本部",
        "https://www.city.ibaraki.osaka.jp/kikou/shobo/menu/46114.html",
        "generic_fire_html",
        "消防法第17条",
        note="茨木市",
    ),
    Source(
        "fire",
        "東大阪市消防局",
        "http://www.city.higashiosaka.lg.jp/0000019327.html",
        "generic_fire_html",
        "消防法第17条",
        note="東大阪市",
    ),
    Source(
        "fire",
        "貝塚市消防本部",
        "https://www.city.kaizuka.lg.jp/shobo/honbu/yobou/bosai/ihanntaishoubutu.html",
        "generic_fire_html",
        "消防法第17条",
        note="貝塚市",
    ),
    Source(
        "fire",
        "枚方寝屋川消防組合",
        "https://hnfd119.jp/?p=11608",
        "generic_fire_html",
        "消防法第17条",
        note="枚方+寝屋川",
    ),
    Source(
        "fire",
        "泉州南広域消防本部",
        "https://senshu-minami119.jp/inf/YOBOU/ihantaishoubutu_Y/index.htm",
        "generic_fire_html",
        "消防法第17条",
        note="泉州南",
    ),
    # 名古屋圏
    Source(
        "fire",
        "名古屋市消防局",
        "http://www.city.nagoya.jp/shobo/page/0000060545.html",
        "generic_fire_html",
        "消防法第17条",
        note="名古屋市 命令対象物",
    ),
    Source(
        "fire",
        "豊橋市消防本部",
        "http://www.city.toyohashi.lg.jp/32253.htm",
        "generic_fire_html",
        "消防法第17条",
        note="豊橋市",
    ),
    Source(
        "fire",
        "岡崎市消防本部",
        "https://www.city.okazaki.lg.jp/1100/1115/1310/kohyo.html",
        "generic_fire_html",
        "消防法第17条",
        note="岡崎市",
    ),
    Source(
        "fire",
        "豊田市消防本部",
        "http://www.city.toyota.aichi.jp/kurashi/shoubou/bokaanzen/1021998.html",
        "generic_fire_html",
        "消防法第17条",
        note="豊田市",
    ),
    Source(
        "fire",
        "一宮市消防本部",
        "https://www.city.ichinomiya.aichi.jp/shoubou/shoubouyobou/1044066/1000022/1019292.html",
        "generic_fire_html",
        "消防法第17条",
        note="一宮市",
    ),
    Source(
        "fire",
        "春日井市消防本部",
        "https://www.city.kasugai.lg.jp/kurashi/syobo/yobo/1004029/index.html",
        "generic_fire_html",
        "消防法第17条",
        note="春日井市",
    ),
    Source(
        "fire",
        "瀬戸市消防本部",
        "http://www.city.seto.aichi.jp/docs/2018030600037/",
        "generic_fire_html",
        "消防法第17条",
        note="瀬戸市",
    ),
    # 北海道圏
    Source(
        "fire",
        "函館市消防本部",
        "https://www.city.hakodate.hokkaido.jp/docs/2016121200029/",
        "generic_fire_html",
        "消防法第17条",
        note="函館市",
    ),
    Source(
        "fire",
        "旭川市消防本部",
        "https://www.city.asahikawa.hokkaido.jp/kurashi/311/314/d067967.html",
        "generic_fire_html",
        "消防法第17条",
        note="旭川市",
    ),
    Source(
        "fire",
        "苫小牧市消防本部",
        "http://www.city.tomakomai.hokkaido.jp/kurashi/shobo/kasaiyobo/ihannkouhyou.html",
        "generic_fire_html",
        "消防法第17条",
        note="苫小牧市",
    ),
    Source(
        "fire",
        "石狩北部地区消防事務組合",
        "https://www.ishikarihokubu.jp/anzen-anshin/ihankouhyou/kouji.html",
        "generic_fire_html",
        "消防法第17条",
        note="石狩北部",
    ),
    # 福岡圏
    Source(
        "fire",
        "福岡市消防局",
        "https://www.city.fukuoka.lg.jp/syobo/sasatsu/anzen-anshin/kouhyou.html",
        "table_kv_2col_fire",
        "消防法第17条",
        note="福岡市 違反対象物公表",
    ),
    Source(
        "fire",
        "北九州市消防局",
        "https://www.city.kitakyushu.lg.jp/kurashi/menu01_00125.html",
        "generic_fire_html",
        "消防法第17条",
        note="北九州市",
    ),
    Source(
        "fire",
        "久留米広域消防本部",
        "http://www.fire-city.kurume.fukuoka.jp/toukei/ihantaisyoubutsu/",
        "generic_fire_html",
        "消防法第17条",
        note="久留米",
    ),
    Source(
        "fire",
        "うるま市消防本部",
        "https://www.city.uruma.lg.jp/2001002000/contents/16062.html",
        "generic_fire_html",
        "消防法第17条",
        note="うるま市",
    ),
    # =====================================================================
    # 第二弾 - fdma.go.jp 都道府県別 index から抽出された working sources
    # =====================================================================
    # 埼玉県
    Source(
        "fire",
        "上尾市消防本部",
        "https://www.city.ageo.lg.jp/site/shoubou/055117041201.html",
        "table_minuma_fire",
        "消防法第17条",
        note="上尾市",
    ),
    Source(
        "fire",
        "戸田市消防本部",
        "https://www.city.toda.saitama.jp/site/firedepartment/syo-yobo-ihantaisyoubutuhtml.html",
        "generic_fire_html",
        "消防法第17条",
        note="戸田市",
    ),
    # 三郷市 has only sample placeholders (○○ビル) — skip.
    # 千葉県
    Source(
        "fire",
        "船橋市消防局",
        "https://www.city.funabashi.lg.jp/kurashi/shoubou/001/p121959.html",
        "generic_fire_html",
        "消防法第17条",
        note="船橋市",
    ),
    Source(
        "fire",
        "野田市消防本部",
        "https://www.city.noda.chiba.jp/kurashi/oshirase/seikatsukankyo/1021953.html",
        "generic_fire_html",
        "消防法第17条",
        note="野田市",
    ),
    Source(
        "fire",
        "成田市消防本部",
        "https://www.city.narita.chiba.jp/anshin/page0158_00006.html",
        "generic_fire_html",
        "消防法第17条",
        note="成田市",
    ),
    Source(
        "fire",
        "八千代市消防本部",
        "https://www.city.yachiyo.lg.jp/site/yachiyo-fire-dept/25054.html",
        "generic_fire_html",
        "消防法第17条",
        note="八千代市",
    ),
    Source(
        "fire",
        "我孫子市消防本部",
        "http://www.city.abiko.chiba.jp/anshin/shobou_kyukyu/kanrenjoho/abk10009000320190326.html",
        "generic_fire_html",
        "消防法第17条",
        note="我孫子市",
    ),
    Source(
        "fire",
        "富津市消防本部",
        "http://www.city.futtsu.lg.jp/0000006002.html",
        "generic_fire_html",
        "消防法第17条",
        note="富津市",
    ),
    # 静岡県
    Source(
        "fire",
        "静岡市消防局",
        "https://www.city.shizuoka.lg.jp/467_000005.html",
        "table_minuma_fire",
        "消防法第17条",
        note="静岡市 違反対象物公表",
    ),
    Source(
        "fire",
        "浜松市消防局",
        "https://www.city.hamamatsu.shizuoka.jp/hfdyobo/anzen/kouhyou.html",
        "generic_fire_html",
        "消防法第17条",
        note="浜松市",
    ),
    Source(
        "fire",
        "駿東伊豆消防本部",
        "https://www.suntoizufd119.jp/ihankohyo/",
        "generic_fire_html",
        "消防法第17条",
        note="駿東伊豆 (静岡県東部)",
    ),
    Source(
        "fire",
        "富士市消防本部",
        "https://www.city.fuji.shizuoka.jp/safety/c0305/rn2ola000000ho11.html",
        "generic_fire_html",
        "消防法第17条",
        note="富士市",
    ),
    # 福岡 (再訪 - 福岡市は kv 2col、北九州は通常)
    Source(
        "fire",
        "糸島市消防本部",
        "https://www.city.itoshima.lg.jp/s039/010/010/010/020/20180308171341.html",
        "generic_fire_html",
        "消防法第17条",
        note="糸島市",
    ),
    Source(
        "fire",
        "筑紫地区消防本部",
        "http://www.chikuta119.jp/info/ihan_kohyo/index.html",
        "generic_fire_html",
        "消防法第17条",
        note="筑紫地区広域",
    ),
    Source(
        "fire",
        "飯塚地区消防本部",
        "http://www.iizuka119.jp/ihan.htm",
        "generic_fire_html",
        "消防法第17条",
        note="飯塚地区",
    ),
    # 神奈川 追加
    Source(
        "fire",
        "平塚市消防本部",
        "http://www.city.hiratsuka.kanagawa.jp/shobo/page12_00003.html",
        "generic_fire_html",
        "消防法第17条",
        note="平塚市",
    ),
    Source(
        "fire",
        "秦野市消防本部",
        "https://www.city.hadano.kanagawa.jp/www/contents/1513132184652/index.html",
        "generic_fire_html",
        "消防法第17条",
        note="秦野市",
    ),
    Source(
        "fire",
        "葉山町",
        "https://www.town.hayama.lg.jp/soshiki/yobou/boukataisyoubutu/8524.html",
        "generic_fire_html",
        "消防法第17条",
        note="葉山町",
    ),
    Source(
        "fire",
        "二宮町",
        "https://www.town.ninomiya.kanagawa.jp/0000001481.html",
        "generic_fire_html",
        "消防法第17条",
        note="二宮町",
    ),
    Source(
        "fire",
        "大磯町",
        "http://www.town.oiso.kanagawa.jp/soshiki/shobo/somu/tanto/kasaiyobou/yoboujyouhou/1550417622153.html",
        "generic_fire_html",
        "消防法第17条",
        note="大磯町",
    ),
    Source(
        "fire",
        "湯河原町",
        "https://www.town.yugawara.kanagawa.jp/bosai/fire/p03918.html",
        "generic_fire_html",
        "消防法第17条",
        note="湯河原町",
    ),
    # 愛知県 追加
    Source(
        "fire",
        "豊川市消防本部",
        "https://www.city.toyokawa.lg.jp/kurashi/anzenanshin/shobo/shoboyoboka20191205.html",
        "generic_fire_html",
        "消防法第17条",
        note="豊川市",
    ),
    Source(
        "fire",
        "西尾市消防本部",
        "https://www.city.nishio.aichi.jp/kurashi/shobo/1004766/1004587.html",
        "generic_fire_html",
        "消防法第17条",
        note="西尾市",
    ),
    Source(
        "fire",
        "犬山市消防本部",
        "https://www.city.inuyama.aichi.jp/kurashi/shobo/1006043.html",
        "generic_fire_html",
        "消防法第17条",
        note="犬山市",
    ),
    Source(
        "fire",
        "常滑市消防本部",
        "http://www.city.tokoname.aichi.jp/kurashi/syobo/1005423/1005662.html",
        "generic_fire_html",
        "消防法第17条",
        note="常滑市",
    ),
    Source(
        "fire",
        "江南市消防本部",
        "https://www.city.konan.lg.jp/shobo/kasaiyobou/1006317/1001917.html",
        "generic_fire_html",
        "消防法第17条",
        note="江南市",
    ),
    Source(
        "fire",
        "小牧市消防本部",
        "https://www.city.komaki.aichi.jp/admin/soshiki/shobo/yobou/3/1/2/25115.html",
        "generic_fire_html",
        "消防法第17条",
        note="小牧市",
    ),
    Source(
        "fire",
        "稲沢市消防本部",
        "https://www.city.inazawa.aichi.jp/0000000382.html",
        "generic_fire_html",
        "消防法第17条",
        note="稲沢市",
    ),
    Source(
        "fire",
        "東海市消防本部",
        "https://www.city.tokai.aichi.jp/iza/1003214/1003284/1003287.html",
        "generic_fire_html",
        "消防法第17条",
        note="東海市",
    ),
    Source(
        "fire",
        "大府市消防本部",
        "https://www.city.obu.aichi.jp/shobo/yobou/1008861.html",
        "generic_fire_html",
        "消防法第17条",
        note="大府市",
    ),
    Source(
        "fire",
        "尾張旭市消防本部",
        "https://www.city.owariasahi.lg.jp/kurasi/shoubou/ihanntaishoubutsu.html",
        "generic_fire_html",
        "消防法第17条",
        note="尾張旭市",
    ),
    # 大阪府 追加
    Source(
        "fire",
        "岸和田市消防本部",
        "https://www.city.kishiwada.osaka.jp/soshiki/77/kouhyouseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="岸和田市",
    ),
    Source(
        "fire",
        "池田市消防本部",
        "https://www.city.ikeda.osaka.jp/soshiki/shobohonbu/yobou/oshirase/1503986998796.html",
        "generic_fire_html",
        "消防法第17条",
        note="池田市",
    ),
    Source(
        "fire",
        "吹田市消防本部",
        "http://www.city.suita.osaka.jp/home/soshiki/div-shoubo/syoubosomu/_80835/oshirase2/_80447.html",
        "generic_fire_html",
        "消防法第17条",
        note="吹田市",
    ),
    Source(
        "fire",
        "和泉市消防本部",
        "https://www.city.osaka-izumi.lg.jp/syoubou/osirase/14014.html",
        "generic_fire_html",
        "消防法第17条",
        note="和泉市",
    ),
    Source(
        "fire",
        "箕面市消防本部",
        "http://www.city.minoh.lg.jp/yobou/ihanntaisyoubutu.html",
        "generic_fire_html",
        "消防法第17条",
        note="箕面市",
    ),
    Source(
        "fire",
        "摂津市消防本部",
        "https://www.city.settsu.osaka.jp/soshiki/shoubousho/yobou/9992.html",
        "generic_fire_html",
        "消防法第17条",
        note="摂津市",
    ),
    Source(
        "fire",
        "松原市消防本部",
        "https://www.city.matsubara.lg.jp/docs/page12072.html",
        "generic_fire_html",
        "消防法第17条",
        note="松原市",
    ),
    # 兵庫県
    Source(
        "fire",
        "西宮市消防局",
        "https://www.nishi.or.jp/kurashi/anshin/shobokyoku/104057120180.html",
        "generic_fire_html",
        "消防法第17条",
        note="西宮市",
    ),
    Source(
        "fire",
        "尼崎市消防局",
        "https://www.city.amagasaki.hyogo.jp/kurashi/syobo/kasaiyobo/1037033/index.html",
        "generic_fire_html",
        "消防法第17条",
        note="尼崎市",
    ),
    Source(
        "fire",
        "伊丹市消防局",
        "http://www.city.itami.lg.jp/SOSIKI/FIREDEPT/shoubou_soshiki/F_YOBOU/defence/1523407936661.html",
        "generic_fire_html",
        "消防法第17条",
        note="伊丹市",
    ),
    Source(
        "fire",
        "宝塚市消防本部",
        "https://www.city.takarazuka.hyogo.jp/anzen/shobo/1008508/1027496/1018450.html",
        "generic_fire_html",
        "消防法第17条",
        note="宝塚市",
    ),
    Source(
        "fire",
        "川西市消防本部",
        "https://www.city.kawanishi.hyogo.jp/fire/1010286/1008943.html",
        "generic_fire_html",
        "消防法第17条",
        note="川西市",
    ),
    Source(
        "fire",
        "明石市消防局",
        "https://www.city.akashi.lg.jp/shoubou/sho_yobou_ka/bouka/houreiihan.html",
        "generic_fire_html",
        "消防法第17条",
        note="明石市",
    ),
    Source(
        "fire",
        "姫路市消防局",
        "https://www.city.himeji.lg.jp/bousai/0000004868.html",
        "generic_fire_html",
        "消防法第17条",
        note="姫路市",
    ),
    Source(
        "fire",
        "淡路広域消防",
        "https://www.awaji119.jp/kasai/ihantaishobutsu/",
        "generic_fire_html",
        "消防法第17条",
        note="淡路広域",
    ),
    # 福岡 サブエリア
    Source(
        "fire",
        "直方市消防本部",
        "https://www.city.nogata.fukuoka.jp/syobo/_1249/_5368.html",
        "generic_fire_html",
        "消防法第17条",
        note="直方市",
    ),
    # 東京
    Source(
        "fire",
        "稲城市消防本部",
        "https://www.city.inagi.tokyo.jp/iza/shoubou/kasai_yobou/kouhyouseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="稲城市",
    ),
    Source(
        "fire",
        "東京消防庁",
        "https://www.tfd.metro.tokyo.lg.jp/kk/ihan/index.html",
        "generic_fire_html",
        "消防法第8条の2の5",
        note="東京消防庁 違反対象物公表",
    ),
    # =====================================================================
    # 第三弾: 高歩留り source 群
    # =====================================================================
    Source(
        "fire",
        "大阪市消防局",
        "http://www.city.osaka.lg.jp/shobo/page/0000301578.html",
        "generic_fire_html",
        "消防法第17条",
        note="大阪市 消防局 違反対象物",
    ),
    Source(
        "fire",
        "神戸市消防局",
        "https://www.city.kobe.lg.jp/a92906/bosai/shobo/kouzikouhyo.html",
        "generic_fire_html",
        "消防法第17条",
        note="神戸市消防局 (ihan)",
    ),
    Source(
        "fire",
        "御殿場小山広域",
        "https://www.gotemba-oyama-kouiki.jp/pages/109/",
        "generic_fire_html",
        "消防法第17条",
        note="御殿場小山広域行政組合",
    ),
    Source(
        "fire",
        "須坂市消防本部",
        "https://www.city.suzaka.nagano.jp/shobo/kasaiyajikofusegu/1147.html",
        "generic_fire_html",
        "消防法第17条",
        note="須坂市",
    ),
    Source(
        "fire",
        "長生郡市広域市町村圏組合",
        "http://fdhp.choseikouiki.jp/02_04_03_ihan.html",
        "generic_fire_html",
        "消防法第17条",
        note="千葉県 長生郡市",
    ),
    Source(
        "fire",
        "幸田町消防本部",
        "https://www.town.kota.lg.jp/soshiki/21/19332.html",
        "generic_fire_html",
        "消防法第17条",
        note="愛知県 幸田町",
    ),
    Source(
        "fire",
        "小松市消防本部",
        "https://www.city.komatsu.lg.jp/komatsu_fire/3/1/15353.html",
        "generic_fire_html",
        "消防法第17条",
        note="石川県 小松市",
    ),
    Source(
        "fire",
        "有田広域消防本部",
        "https://yuasahirogawa.sakura.ne.jp/yoboukouhyouseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="和歌山県 有田広域",
    ),
    Source(
        "fire",
        "比謝川行政事務組合消防本部",
        "https://hijagawa.or.jp/nirai/yobou/ihan.html",
        "generic_fire_html",
        "消防法第17条",
        note="沖縄県 比謝川 (中部)",
    ),
    Source(
        "fire",
        "長崎県央地域広域市町村圏組合",
        "https://www.nagasaki-kenoukumiai.jp/syoubou/kasaiyobou/houreiihan_kouhyou/",
        "generic_fire_html",
        "消防法第17条",
        note="長崎県央",
    ),
    Source(
        "fire",
        "高知市消防局",
        "https://www.city.kochi.kochi.jp/soshiki/74/kohyoseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="高知市",
    ),
    Source(
        "fire",
        "嶺北消防組合",
        "http://www.reihoku-k.jp/kumiai/syoubou.html",
        "generic_fire_html",
        "消防法第17条",
        note="高知県 嶺北",
    ),
    Source(
        "fire",
        "熱海市消防本部",
        "https://www.city.atami.lg.jp/kurashi/kyukyu/1004366.html",
        "generic_fire_html",
        "消防法第17条",
        note="熱海市",
    ),
    Source(
        "fire",
        "新潟市消防局",
        "http://www.city.niigata.lg.jp/kurashi/bohan/shobo/boukataishobutu/kouhyou.html",
        "generic_fire_html",
        "消防法第17条",
        note="新潟市",
    ),
    Source(
        "fire",
        "笛吹市消防本部",
        "https://www.city.fuefuki.yamanashi.jp/yobo/bosaikyukyu/kouhyouseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="笛吹市",
    ),
    Source(
        "fire",
        "長野市消防局",
        "https://www.city.nagano.nagano.jp/n801000/contents/p000130.html",
        "generic_fire_html",
        "消防法第17条",
        note="長野市",
    ),
    Source(
        "fire",
        "羽島市消防本部",
        "http://www.city.hashima.lg.jp/0000010547.html",
        "generic_fire_html",
        "消防法第17条",
        note="羽島市",
    ),
    Source(
        "fire",
        "各務原市消防本部",
        "https://www.city.kakamigahara.lg.jp/life/bousai/1001268/1001326/1001332.html",
        "generic_fire_html",
        "消防法第17条",
        note="各務原市",
    ),
    Source(
        "fire",
        "奈良市消防局",
        "https://www.city.nara.lg.jp/site/shobo-kyukyu/146783.html",
        "generic_fire_html",
        "消防法第17条",
        note="奈良市",
    ),
    Source(
        "fire",
        "彦根市消防本部",
        "https://www.city.hikone.lg.jp/kurashi/bosai/2/3/6287.html",
        "generic_fire_html",
        "消防法第17条",
        note="彦根市",
    ),
    Source(
        "fire",
        "高島市消防本部",
        "https://www.city.takashima.lg.jp/kurashi_tetsuzuki/bosai_shobo_kyukyu/2/5/5290.html",
        "generic_fire_html",
        "消防法第17条",
        note="高島市",
    ),
    Source(
        "fire",
        "臼杵市消防本部",
        "https://www.city.usuki.oita.jp/docs/2019111900015",
        "generic_fire_html",
        "消防法第17条",
        note="臼杵市",
    ),
    Source(
        "fire",
        "有明広域消防",
        "http://www.ariake-119.or.jp/ihankouhyou/ihankouhyou2_5_11.html",
        "generic_fire_html",
        "消防法第17条",
        note="熊本県 有明広域",
    ),
    Source(
        "fire",
        "桑名市消防本部",
        "https://www.city.kuwana.lg.jp/main/9bo/p019100.html",
        "generic_fire_html",
        "消防法第17条",
        note="三重県 桑名市",
    ),
    Source(
        "fire",
        "広島市消防局",
        "https://www.city.hiroshima.lg.jp/site/shobo/12216.html",
        "generic_fire_html",
        "消防法第17条",
        note="広島市",
    ),
    Source(
        "fire",
        "村上市消防本部",
        "https://www.city.murakami.lg.jp/soshiki/58/ihantaisyoubutuitiran.html",
        "generic_fire_html",
        "消防法第17条",
        note="村上市",
    ),
    Source(
        "fire",
        "南魚沼市消防本部",
        "https://www.city.minamiuonuma.niigata.jp/shoubouhonbu/docs/4260.html",
        "generic_fire_html",
        "消防法第17条",
        note="南魚沼市",
    ),
    Source(
        "fire",
        "東予新居浜消防組合",
        "https://www.city.saijo.ehime.jp/site/shobo/ihantaishobutsu.html",
        "generic_fire_html",
        "消防法第17条",
        note="西条市消防 (愛媛)",
    ),
    Source(
        "fire",
        "松山市消防局",
        "http://www.city.matsuyama.ehime.jp/kurashi/bosai/sbbousai/sboshirase/kouhyouseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="松山市",
    ),
    Source(
        "fire",
        "東温市消防本部",
        "https://www.city.toon.ehime.jp/soshiki/19/1272.html",
        "generic_fire_html",
        "消防法第17条",
        note="東温市",
    ),
    Source(
        "fire",
        "栃木県消防本部 (足利)",
        "https://www.city.ashikaga.tochigi.jp/environment/000073/000404/000795/p004998.html",
        "generic_fire_html",
        "消防法第17条",
        note="足利市",
    ),
    Source(
        "fire",
        "佐野市消防本部",
        "https://www.city.sano.lg.jp/sp/shobohonbu/oshirase/1202.html",
        "generic_fire_html",
        "消防法第17条",
        note="佐野市",
    ),
    Source(
        "fire",
        "上田地域広域連合",
        "http://www.area.ueda.nagano.jp/?page_id=2965",
        "generic_fire_html",
        "消防法第17条",
        note="上田地域広域連合",
    ),
    Source(
        "fire",
        "長野市南部",
        "https://119.minami.nagano.jp/violation/",
        "generic_fire_html",
        "消防法第17条",
        note="南信州広域",
    ),
    Source(
        "fire",
        "鯖江丹生消防組合",
        "http://www.fd-sabaenyu.jp/%e9%81%95%e5%8f%8d%e5%af%be%e8%b1%a1%e7%89%a9%e5%85%ac%e8%a1%a8%e5%88%b6%e5%ba%a6%e3%80%90%e4%ba%88%e9%98%b2%e8%aa%b2%e3%83%bb%e9%98%b2%e7%81%ab%e6%8c%87%e5%b0%8e%e8%aa%b2%e3%80%91/",
        "generic_fire_html",
        "消防法第17条",
        note="鯖江丹生",
    ),
    Source(
        "fire",
        "岐阜市消防本部",
        "https://www.city.gifu.lg.jp/kurashi/syoubou/1001427/1001432.html",
        "generic_fire_html",
        "消防法第17条",
        note="岐阜市",
    ),
    Source(
        "fire",
        "橋本市消防本部",
        "https://www.city.hashimoto.lg.jp/guide/shobohonbu/oshirase/jigyoshooshirase/15841.html",
        "generic_fire_html",
        "消防法第17条",
        note="橋本市 (和歌山)",
    ),
    Source(
        "fire",
        "美方広域消防本部",
        "http://www.kouiki-mikata.jp/mikata-fd/ihan/index.html",
        "generic_fire_html",
        "消防法第17条",
        note="美方広域 (兵庫北部)",
    ),
    Source(
        "fire",
        "奈良県広域消防組合",
        "http://www.naraksk119.jp/contents_detail.php?co=cat&frmId=524&frmCd=6-2-0-0-0",
        "generic_fire_html",
        "消防法第17条",
        note="奈良県広域",
    ),
    Source(
        "fire",
        "益田広域消防本部",
        "http://www.fd-masuda.net/modules/topics/index.php?content_id=86",
        "generic_fire_html",
        "消防法第17条",
        note="益田広域 (島根)",
    ),
    Source(
        "fire",
        "大竹市消防本部",
        "http://www.city.otake.hiroshima.jp/soshiki/shobo/shobohonbu/syobo_kyukyu/1590997032962.html",
        "generic_fire_html",
        "消防法第17条",
        note="大竹市",
    ),
    Source(
        "fire",
        "鳥取県西部広域行政管理組合",
        "https://www.tottori-seibukoiki.jp/1260.htm",
        "generic_fire_html",
        "消防法第17条",
        note="鳥取県西部",
    ),
    Source(
        "fire",
        "東部消防組合",
        "https://tfd119okayama.jp/schedule/yobou-01/",
        "generic_fire_html",
        "消防法第17条",
        note="岡山県",
    ),
    Source(
        "fire",
        "伊万里有田消防本部",
        "https://www.imari-arita119.saga.jp/bewarefire/_1509/_1510/_1505.html",
        "generic_fire_html",
        "消防法第17条",
        note="佐賀県 伊万里有田",
    ),
    Source(
        "fire",
        "薩摩川内市消防本部",
        "https://www.city.kagoshima-izumi.lg.jp/page/page_03201.html",
        "generic_fire_html",
        "消防法第17条",
        note="出水市",
    ),
    Source(
        "fire",
        "尾張西部消防組合",
        "https://www.bisan-fd.togo.aichi.jp/houkoku/ihantaisyou/",
        "generic_fire_html",
        "消防法第17条",
        note="愛知県 尾張西部",
    ),
    Source(
        "fire",
        "越谷市消防本部",
        "https://www.city.koshigaya.saitama.jp/anzen_anshin/syobohonbu/fhonbu_annai/oshirase/kasaiyobo/kouhyou.html",
        "generic_fire_html",
        "消防法第17条",
        note="越谷市",
    ),
    Source(
        "fire",
        "入間東部消防組合",
        "http://www.irumatohbu119.jp/important/2018-0403-1738-1.html",
        "generic_fire_html",
        "消防法第17条",
        note="入間東部 (埼玉)",
    ),
    Source(
        "fire",
        "川越地区消防組合",
        "http://www.119kawagoechiku.jp/yobou/kentikubutuanzen/kouhyou/kouhyouseido.html",
        "generic_fire_html",
        "消防法第17条",
        note="川越地区",
    ),
    Source(
        "fire",
        "富里市",
        "http://www.city.tomisato.lg.jp/0000010518.html",
        "generic_fire_html",
        "消防法第17条",
        note="富里市消防本部",
    ),
    Source(
        "fire",
        "安房広域消防本部",
        "http://awakouiki.jp/shobo_honbu/ihantaisyoubutsu.html",
        "generic_fire_html",
        "消防法第17条",
        note="安房広域",
    ),
]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

# 平成17年5月16日 / 平成17年 5月16日 / 令和5年 / 令和7年4月8日
_JP_ERA_DATE = re.compile(
    r"(明治|大正|昭和|平成|令和)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
_JP_AD_DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ISO_DATE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")

_ERA_BASE: dict[str, int] = {
    "明治": 1867,
    "大正": 1911,
    "昭和": 1925,
    "平成": 1988,
    "令和": 2018,
}


def parse_jp_date(s: str) -> str | None:
    if not s:
        return None
    s = s.replace("\xa0", " ")
    m = _JP_ERA_DATE.search(s)
    if m:
        era, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            return dt.date(_ERA_BASE[era] + y, mo, d).isoformat()
        except ValueError:
            return None
    m = _JP_AD_DATE.search(s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = _ISO_DATE.search(s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL_RE = re.compile(r"<(t[hd])\b[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_H_RE = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.DOTALL | re.IGNORECASE)


def _strip_html(s: str) -> str:
    s = _BR_RE.sub("\n", s or "")
    s = _TAG_RE.sub("", s)
    s = html_lib.unescape(s)
    # Compact whitespace, but keep newlines as commit boundaries.
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\s*\n\s*", " / ", s)
    return s.strip()


def _decode(body: bytes) -> str:
    """Best-effort decode for jp pages that may be UTF-8 or Shift_JIS."""
    for enc in ("utf-8", "cp932", "euc_jp"):
        try:
            text = body.decode(enc)
            if "違反" in text or "命令" in text or "防火" in text or "建築" in text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _iter_tables(html: str) -> list[str]:
    return _TABLE_RE.findall(html)


def _iter_rows(table_html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in _TR_RE.findall(table_html):
        cells = [_strip_html(m.group(2)) for m in _CELL_RE.finditer(tr)]
        if cells:
            rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# enforcement_kind mapping
# ---------------------------------------------------------------------------

KIND_MAP: list[tuple[str, str]] = [
    # priority order
    ("許可取消", "license_revoke"),
    ("認定取消", "license_revoke"),
    ("登録取消", "license_revoke"),
    ("使用禁止", "contract_suspend"),
    ("使用停止", "contract_suspend"),
    ("営業停止", "contract_suspend"),
    ("操業停止", "contract_suspend"),
    ("除却", "contract_suspend"),
    ("撤去", "contract_suspend"),
    ("取壊", "contract_suspend"),
    ("施工停止", "business_improvement"),
    ("工事停止", "business_improvement"),
    ("是正命令", "business_improvement"),
    ("是正措置", "business_improvement"),
    ("措置命令", "business_improvement"),
    ("命令", "business_improvement"),
    ("公表", "business_improvement"),
    ("違反", "business_improvement"),
]


def map_kind(text: str, default: str = "business_improvement") -> str:
    s = text or ""
    for kw, k in KIND_MAP:
        if kw in s:
            return k
    return default


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    cluster: str  # kenchiku / fire / kouatsu_gas
    target_name: str
    address: str | None
    issuance_date: str  # ISO
    issuing_authority: str
    enforcement_kind: str
    related_law_ref: str
    reason_summary: str
    source_url: str
    raw_extras: dict[str, str] = field(default_factory=dict)
    houjin_bangou: str | None = None
    owner_name: str | None = None
    owner_address: str | None = None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_table_7col_kenchiku(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """大阪府/大阪市 形式: 7-col 命令一覧テーブル."""
    html = _decode(body)
    out: list[EnfRow] = []
    # Section heading map: heading text → law basis override.
    section_law: dict[str, str] = {
        "都市計画法": "都市計画法第81条",
        "建築基準法": "建築基準法第9条",
    }
    # Walk H2 sections + their tables in order. Use position-based pairing.
    spans: list[tuple[int, str, str]] = []  # (start, kind, text)
    for m in _H_RE.finditer(html):
        text = _strip_html(m.group(1))
        spans.append((m.start(), "h", text))
    for m in _TABLE_RE.finditer(html):
        spans.append((m.start(), "t", m.group(1)))
    spans.sort(key=lambda x: x[0])

    current_law = source.law_basis_default
    for _, kind, payload in spans:
        if kind == "h":
            for sub_kw, ref in section_law.items():
                if sub_kw in payload:
                    current_law = ref
                    break
            continue
        rows = _iter_rows(payload)
        if not rows:
            continue
        # Skip header row (containing 命令施行日 + 所在地)
        for r in rows:
            if any("命令" in c and "日" in c for c in r) and any("所在地" in c for c in r):
                continue
            if len(r) < 5:
                continue
            d_iso = parse_jp_date(r[0])
            if not d_iso:
                continue
            address = r[1] if len(r) > 1 else ""
            target = r[2] if len(r) > 2 else ""
            owner_addr = r[3] if len(r) > 3 else ""
            usage = r[4] if len(r) > 4 else ""
            disposition = r[5] if len(r) > 5 else ""
            if not target:
                continue
            kind_enum = map_kind(disposition or current_law, "business_improvement")
            summary_parts = [
                f"対象: {target}",
                f"所在地: {address}" if address else "",
                f"用途: {usage}" if usage else "",
                f"処分: {disposition}" if disposition else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="kenchiku",
                    target_name=target[:300],
                    address=address[:300] if address else None,
                    issuance_date=d_iso,
                    issuing_authority=source.authority,
                    enforcement_kind=kind_enum,
                    related_law_ref=current_law[:200],
                    reason_summary=summary,
                    source_url=fetched_url,
                    owner_name=target[:200],
                    owner_address=owner_addr[:200] or None,
                    raw_extras={"usage": usage, "disposition": disposition},
                )
            )
    return out


def parse_table_5col_osaka_city(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """大阪市 建築主事 命令建築物一覧 (5-col).

    Layout: 命令施行日 / 違反建築物の所在地 / 命令を受けた者の住所及び氏名 /
            建築物の用途・構造・規模 / 処分事由・内容
    The col[2] cell stores the *owner address* and *owner name* concatenated
    via <br>; we split on the trailing slash that ``_strip_html`` introduces.
    """
    html = _decode(body)
    out: list[EnfRow] = []
    for table in _iter_tables(html):
        rows = _iter_rows(table)
        if not rows:
            continue
        # Header detection
        head_idx = -1
        for i, r in enumerate(rows[:3]):
            joined = " ".join(r)
            if "命令" in joined and "所在地" in joined and "住所" in joined:
                head_idx = i
                break
        if head_idx < 0:
            continue
        for r in rows[head_idx + 1 :]:
            if len(r) < 5:
                continue
            d_iso = parse_jp_date(r[0])
            if not d_iso:
                continue
            address = r[1] or ""
            owner_blob = r[2] or ""
            usage = r[3] or ""
            disposition = r[4] or ""

            # The owner cell looks like: "<address> / <name>" or
            # "<address> / <name> /". Try to split on first "/".
            owner_addr = ""
            owner_name = ""
            parts = [p.strip() for p in owner_blob.split(" / ") if p.strip() and p.strip() != "/"]
            if len(parts) >= 2:
                # First part is address, the remaining join is name.
                # Treat first " / "-separated chunk as the address; the rest
                # is the name (possibly with hierarchical components).
                owner_addr = parts[0]
                owner_name = " ".join(parts[1:]).rstrip("/").strip()
            elif parts:
                owner_name = parts[0].rstrip("/").strip()

            # ``target_name`` should be the entity that owns the building —
            # this is the most useful identifier for downstream matching.
            target = owner_name or owner_blob
            if not target:
                continue
            kind_enum = map_kind(disposition, "business_improvement")
            summary_parts = [
                f"所在地: {address}" if address else "",
                f"用途: {usage}" if usage else "",
                f"処分: {disposition}" if disposition else "",
                f"被命令者住所: {owner_addr}" if owner_addr else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="kenchiku",
                    target_name=target[:300],
                    address=address[:300] if address else None,
                    issuance_date=d_iso,
                    issuing_authority=source.authority,
                    enforcement_kind=kind_enum,
                    related_law_ref=source.law_basis_default,
                    reason_summary=summary,
                    source_url=fetched_url,
                    owner_name=owner_name[:200] or None,
                    owner_address=owner_addr[:200] or None,
                    raw_extras={"usage": usage, "disposition": disposition},
                )
            )
    return out


def parse_table_kv_2col_fire(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """福岡市 etc.: vertical key-value table per building.

    Each ``<table>`` has 2 columns, with rows for 名称 / 所在地 /
    違反の内容 / 根拠法令 / 公表日 / その他.
    """
    html = _decode(body)
    out: list[EnfRow] = []
    for table in _iter_tables(html):
        rows = _iter_rows(table)
        if len(rows) < 4:
            continue
        kv: dict[str, str] = {}
        for r in rows:
            if len(r) < 2:
                continue
            key = r[0].replace(" ", "").replace("　", "")
            val = r[1]
            kv[key] = val
        # Map common key variants
        name = (kv.get("名称") or kv.get("対象物の名称") or kv.get("建物名") or "").strip()
        address = (kv.get("所在地") or kv.get("住所") or "").strip()
        violation = (kv.get("違反の内容") or kv.get("違反内容") or kv.get("違反") or "").strip()
        law_basis = (kv.get("根拠法令") or kv.get("根拠条項") or kv.get("適用条項") or "").strip()
        pub_date = (kv.get("公表日") or kv.get("公表年月日") or kv.get("公示年月日") or "").strip()
        other = (kv.get("その他") or kv.get("備考") or "").strip()
        if not name or not (violation or law_basis):
            continue
        iso = parse_jp_date(pub_date) or _extract_update_date(html) or dt.date.today().isoformat()
        if not iso:
            continue
        summary_parts = [
            f"所在地: {address}" if address else "",
            f"違反: {violation}" if violation else "",
            f"備考: {other}" if other else "",
        ]
        summary = " / ".join(p for p in summary_parts if p)[:1500]
        out.append(
            EnfRow(
                cluster="fire",
                target_name=name[:300],
                address=address[:300] if address else None,
                issuance_date=iso,
                issuing_authority=source.authority,
                enforcement_kind=map_kind(violation, "business_improvement"),
                related_law_ref=(law_basis or source.law_basis_default)[:200],
                reason_summary=summary,
                source_url=fetched_url,
                raw_extras={"other": other},
            )
        )
    return out


def parse_table_minuma_fire(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """さいたま市 見沼区 type: merged-header 6-col fire violation table.

    Header row 1: 防火対象物名 / 防火対象物の所在地 / 違反の内容 / 公表年月日
    Header row 2 (under '違反の内容' colspan): 違反指摘事項 / 根拠法令の条項 /
                                              違反の位置等
    Data row: 6 cols (name, address, item, law, position, date).
    """
    html = _decode(body)
    out: list[EnfRow] = []
    for table in _iter_tables(html):
        rows = _iter_rows(table)
        if len(rows) < 3:
            continue
        # Locate first row that looks like a 6-col body row containing both a
        # 名称 and a date.
        for r in rows:
            if len(r) < 6:
                continue
            if any("防火対象物名" in c for c in r):
                continue  # header
            if any("違反指摘事項" in c for c in r):
                continue  # sub-header
            name = r[0]
            address = r[1]
            item = r[2]
            law_basis = r[3]
            location = r[4]
            date_cell = r[5]
            iso = parse_jp_date(date_cell) or _extract_update_date(html)
            if not iso or not name:
                continue
            summary_parts = [
                f"所在地: {address}" if address else "",
                f"違反指摘: {item}" if item else "",
                f"違反の位置: {location}" if location else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="fire",
                    target_name=name[:300],
                    address=address[:300] if address else None,
                    issuance_date=iso,
                    issuing_authority=source.authority,
                    enforcement_kind=map_kind(item, "business_improvement"),
                    related_law_ref=(law_basis or source.law_basis_default)[:200],
                    reason_summary=summary,
                    source_url=fetched_url,
                    raw_extras={"location": location},
                )
            )
    return out


def parse_table_yokohama_fire(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """横浜市: 行政区/名称/所在地/違反内容/根拠条項/違反位置/その他."""
    html = _decode(body)
    out: list[EnfRow] = []
    update_iso = _extract_update_date(html) or dt.date.today().isoformat()
    for table in _iter_tables(html):
        rows = _iter_rows(table)
        if not rows:
            continue
        # Header detection: first row contains 行政区 + 違反
        head = rows[0]
        if not (any("行政区" in c or c == "区" for c in head) and any("違反" in c for c in head)):
            continue
        for r in rows[1:]:
            if len(r) < 4:
                continue
            district = r[0]
            name = r[1]
            address = r[2]
            violation = r[3]
            law_basis = r[4] if len(r) > 4 else source.law_basis_default
            location = r[5] if len(r) > 5 else ""
            other = r[6] if len(r) > 6 else ""
            if not name or "名称" in name:
                continue
            summary_parts = [
                f"行政区: {district}",
                f"所在地: {address}" if address else "",
                f"違反内容: {violation}" if violation else "",
                f"違反位置: {location}" if location else "",
                f"備考: {other}" if other else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="fire",
                    target_name=name[:300],
                    address=address[:300] if address else None,
                    issuance_date=update_iso,
                    issuing_authority=source.authority,
                    enforcement_kind="business_improvement",
                    related_law_ref=(law_basis or source.law_basis_default)[:200],
                    reason_summary=summary,
                    source_url=fetched_url,
                    raw_extras={"district": district},
                )
            )
    return out


def parse_table_chiba_fire(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """千葉市: 区別 H2/H3 + 名称/所在地/違反/年月日 セル."""
    html = _decode(body)
    out: list[EnfRow] = []
    # Iterate H + tables alternately to associate ward.
    spans: list[tuple[int, str, str]] = []
    for m in _H_RE.finditer(html):
        spans.append((m.start(), "h", _strip_html(m.group(1))))
    for m in _TABLE_RE.finditer(html):
        spans.append((m.start(), "t", m.group(1)))
    spans.sort(key=lambda x: x[0])
    current_district = ""
    for _, kind, payload in spans:
        if kind == "h":
            if "区" in payload and len(payload) <= 30:
                current_district = payload
            continue
        rows = _iter_rows(payload)
        if not rows:
            continue
        # Look for header row containing 名称 / 所在地 / 違反 / 公表
        header_idx = -1
        for i, r in enumerate(rows):
            joined = " ".join(r)
            if "名称" in joined and ("所在地" in joined or "住所" in joined):
                header_idx = i
                break
        for r in rows[(header_idx + 1) if header_idx >= 0 else 0 :]:
            if len(r) < 3:
                continue
            joined = " ".join(r)
            if "名称" in joined and "所在地" in joined:
                continue
            name = r[0]
            address = r[1] if len(r) > 1 else ""
            violation = r[2] if len(r) > 2 else ""
            date_cell = r[3] if len(r) > 3 else ""
            if not name or len(name) > 200:
                continue
            iso = parse_jp_date(date_cell) or parse_jp_date(violation) or _extract_update_date(html)
            if not iso:
                continue
            summary_parts = [
                f"区: {current_district}" if current_district else "",
                f"所在地: {address}" if address else "",
                f"違反: {violation}" if violation else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="fire",
                    target_name=name[:300],
                    address=address[:300] if address else None,
                    issuance_date=iso,
                    issuing_authority=source.authority,
                    enforcement_kind="business_improvement",
                    related_law_ref=source.law_basis_default,
                    reason_summary=summary,
                    source_url=fetched_url,
                    raw_extras={"district": current_district, "date_cell": date_cell},
                )
            )
    return out


def parse_table_kawasaki_fire(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """川崎市: 名称/所在地/違反/根拠条項/違反位置/公表日/消防署."""
    html = _decode(body)
    out: list[EnfRow] = []
    for table in _iter_tables(html):
        rows = _iter_rows(table)
        if not rows:
            continue
        head = rows[0]
        joined_head = " ".join(head)
        if not ("違反" in joined_head and ("名称" in joined_head or "建物" in joined_head)):
            continue
        for r in rows[1:]:
            if len(r) < 4:
                continue
            name = r[0]
            address = r[1] if len(r) > 1 else ""
            violation = r[2] if len(r) > 2 else ""
            law_basis = r[3] if len(r) > 3 else source.law_basis_default
            location = r[4] if len(r) > 4 else ""
            pub_date = r[5] if len(r) > 5 else ""
            station = r[6] if len(r) > 6 else ""
            iso = (
                parse_jp_date(pub_date) or _extract_update_date(html) or dt.date.today().isoformat()
            )
            if not name:
                continue
            summary_parts = [
                f"所在地: {address}" if address else "",
                f"違反: {violation}" if violation else "",
                f"違反位置: {location}" if location else "",
                f"消防署: {station}" if station else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="fire",
                    target_name=name[:300],
                    address=address[:300] if address else None,
                    issuance_date=iso,
                    issuing_authority=source.authority,
                    enforcement_kind=map_kind(violation, "business_improvement"),
                    related_law_ref=(law_basis or source.law_basis_default)[:200],
                    reason_summary=summary,
                    source_url=fetched_url,
                    raw_extras={"station": station},
                )
            )
    return out


def parse_table_nagoya_fire(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """名古屋市: 区別ブロック (H3) → 名称/所在地/違反/公表日 セル."""
    html = _decode(body)
    out: list[EnfRow] = []
    spans: list[tuple[int, str, str]] = []
    for m in _H_RE.finditer(html):
        spans.append((m.start(), "h", _strip_html(m.group(1))))
    for m in _TABLE_RE.finditer(html):
        spans.append((m.start(), "t", m.group(1)))
    spans.sort(key=lambda x: x[0])
    current_district = ""
    for _, kind, payload in spans:
        if kind == "h":
            if "区" in payload and len(payload) <= 30:
                current_district = payload
            continue
        rows = _iter_rows(payload)
        if not rows:
            continue
        # Two common header layouts: (名称/所在地/違反/公表日) or
        # (名称/所在地/違反内容/公表年月日).
        header_idx = 0
        for i, r in enumerate(rows[:3]):
            joined = " ".join(r)
            if "名称" in joined and "違反" in joined:
                header_idx = i
                break
        body_rows = rows[header_idx + 1 :] if header_idx >= 0 else rows
        for r in body_rows:
            if len(r) < 3:
                continue
            name = r[0]
            address = r[1] if len(r) > 1 else ""
            violation = r[2] if len(r) > 2 else ""
            date_cell = r[3] if len(r) > 3 else ""
            iso = parse_jp_date(date_cell) or parse_jp_date(violation) or _extract_update_date(html)
            if not iso or not name:
                continue
            joined = " ".join(r)
            if "名称" in joined and "違反" in joined:
                continue
            summary_parts = [
                f"区: {current_district}" if current_district else "",
                f"所在地: {address}" if address else "",
                f"違反: {violation}" if violation else "",
            ]
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="fire",
                    target_name=name[:300],
                    address=address[:300] if address else None,
                    issuance_date=iso,
                    issuing_authority=source.authority,
                    enforcement_kind="business_improvement",
                    related_law_ref=source.law_basis_default,
                    reason_summary=summary,
                    source_url=fetched_url,
                    raw_extras={"district": current_district},
                )
            )
    return out


def parse_generic_fire_html(
    body: bytes,
    source: Source,
    fetched_url: str,
) -> list[EnfRow]:
    """Fallback: walk all tables, accept rows that look like
    (name, address, violation [, date]) with at least one fire-related kw."""
    html = _decode(body)
    out: list[EnfRow] = []
    update_iso = _extract_update_date(html) or dt.date.today().isoformat()
    for table in _iter_tables(html):
        rows = _iter_rows(table)
        if len(rows) < 2:
            continue
        head_joined = " ".join(rows[0])
        if not any(kw in head_joined for kw in ("名称", "建物", "対象物", "事業所")):
            continue
        if not any(kw in head_joined for kw in ("違反", "未設置", "公表", "命令", "所在地")):
            continue
        for r in rows[1:]:
            if len(r) < 2:
                continue
            " ".join(r)
            if "名称" in r[0] or r[0] == "建物" or r[0] == "対象物":
                continue
            name = r[0]
            address = r[1] if len(r) > 1 else ""
            # Find a violation cell
            violation = ""
            for c in r[2:]:
                if any(kw in c for kw in ("違反", "未設置", "義務", "措置", "命令", "公表")):
                    violation = c
                    break
            # Find a date cell
            iso: str | None = None
            for c in r:
                iso = parse_jp_date(c)
                if iso:
                    break
            if not iso:
                iso = update_iso
            if not name or len(name) > 250:
                continue
            if not address and not violation:
                continue
            # Reject pure header-like remnants
            if name in ("行政区", "区", "用途", "種別"):
                continue
            summary_parts = [
                f"所在地: {address}" if address else "",
                f"違反: {violation}" if violation else "",
            ]
            extras = {f"col_{i}": c for i, c in enumerate(r) if c}
            summary = " / ".join(p for p in summary_parts if p)[:1500]
            out.append(
                EnfRow(
                    cluster="fire",
                    target_name=name[:300],
                    address=address[:300] if address else None,
                    issuance_date=iso,
                    issuing_authority=source.authority,
                    enforcement_kind=map_kind(violation, "business_improvement"),
                    related_law_ref=source.law_basis_default,
                    reason_summary=summary,
                    source_url=fetched_url,
                    raw_extras=extras,
                )
            )
    return out


_UPDATE_DATE_RE = re.compile(r"(?:更新日|最終更新|公表日|更新)[:\s：]*([^<\n]{1,40})")


def _extract_update_date(html: str) -> str | None:
    m = _UPDATE_DATE_RE.search(html)
    if not m:
        return None
    return parse_jp_date(m.group(1))


PARSERS: dict[str, Any] = {
    "table_7col_kenchiku": parse_table_7col_kenchiku,
    "table_5col_osaka_city": parse_table_5col_osaka_city,
    "table_yokohama_fire": parse_table_yokohama_fire,
    "table_chiba_fire": parse_table_chiba_fire,
    "table_kawasaki_fire": parse_table_kawasaki_fire,
    "table_nagoya_fire": parse_table_nagoya_fire,
    "table_kv_2col_fire": parse_table_kv_2col_fire,
    "table_minuma_fire": parse_table_minuma_fire,
    "generic_fire_html": parse_generic_fire_html,
}


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000")
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_enforcement_detail'"
    ).fetchone()
    if not row:
        conn.close()
        raise SystemExit("am_enforcement_detail table missing")
    return conn


def load_dedup(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(target_name,''), issuance_date, IFNULL(enforcement_kind,'') "
        "FROM am_enforcement_detail"
    ):
        if r[0] and r[1]:
            out.add((r[0], r[1], r[2]))
    return out


def make_canonical_id(row: EnfRow) -> str:
    h = hashlib.sha1(
        (
            row.target_name
            + "|"
            + row.issuance_date
            + "|"
            + row.issuing_authority
            + "|"
            + row.related_law_ref
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"enforcement:bldg_fire:{row.cluster}:{row.issuance_date}:{h}"


def upsert(
    conn: sqlite3.Connection,
    row: EnfRow,
    fetched_at: str,
) -> str:
    canonical_id = make_canonical_id(row)
    raw_json = {
        "cluster": row.cluster,
        "target_name": row.target_name,
        "address": row.address,
        "owner_name": row.owner_name,
        "owner_address": row.owner_address,
        "issuance_date": row.issuance_date,
        "issuing_authority": row.issuing_authority,
        "enforcement_kind": row.enforcement_kind,
        "related_law_ref": row.related_law_ref,
        "reason_summary": row.reason_summary,
        "source_url": row.source_url,
        "raw_extras": row.raw_extras,
        "fetched_at": fetched_at,
        "source": "building_fire_pref_pages",
        "source_attribution": "都道府県/政令市/中核市 公式サイト",
        "license": "政府機関の著作物（出典明記で転載引用可）",
    }
    src_url = row.source_url
    src_domain = urllib.parse.urlparse(src_url).netloc

    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', ?, ?, 0.90, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            f"bldg_fire_{row.cluster}",
            row.target_name[:500],
            src_url,
            src_domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    inserted_entity = cur.rowcount > 0

    existing = conn.execute(
        "SELECT enforcement_id FROM am_enforcement_detail WHERE entity_id=?",
        (canonical_id,),
    ).fetchone()
    if existing:
        return "skip"

    conn.execute(
        """INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, reason_summary,
            related_law_ref, source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            row.houjin_bangou,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            (row.reason_summary or f"{row.related_law_ref}に基づく違反対象")[:4000],
            row.related_law_ref[:1000],
            src_url,
            fetched_at,
        ),
    )
    return "insert" if inserted_entity else "update"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--clusters", type=str, default="kenchiku,fire", help="comma-separated cluster names"
    )
    ap.add_argument("--stop-at", type=int, default=0, help="stop after N inserts (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    clusters = {c.strip() for c in args.clusters.split(",") if c.strip()}
    sources = [s for s in SOURCES if s.cluster in clusters]
    if not sources:
        _LOG.error("no sources for clusters=%s", clusters)
        return 2

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    http = HttpClient(respect_robots=False)  # gov sites; we are polite via pacing.

    # Pre-load dedup keys, then close so other writers aren't blocked during HTTP.
    dedup: set[tuple[str, str, str]] = set()
    if not args.dry_run:
        conn0 = open_db(args.db)
        try:
            dedup = load_dedup(conn0)
            _LOG.info("preload dedup keys=%d", len(dedup))
        finally:
            conn0.close()

    pending: list[EnfRow] = []
    fetch_stats: dict[str, dict[str, int]] = {}

    for source in sources:
        key = f"{source.authority}|{source.note}"
        st = {"fetched": 0, "rows_built": 0}
        fetch_stats[key] = st
        _LOG.info(
            "fetching cluster=%s authority=%s url=%s", source.cluster, source.authority, source.url
        )
        res = http.get(source.url, max_bytes=HTML_MAX_BYTES)
        if not res.ok or not res.body:
            _LOG.warning(
                "fetch failed cluster=%s auth=%s status=%s reason=%s url=%s",
                source.cluster,
                source.authority,
                res.status,
                res.skip_reason,
                source.url,
            )
            continue
        st["fetched"] = 1
        parser_fn = PARSERS.get(source.parser)
        if parser_fn is None:
            _LOG.warning("no parser for hint=%s", source.parser)
            continue
        try:
            rows = parser_fn(res.body, source, source.url)
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("parser %s failed: %s", source.parser, exc)
            continue
        st["rows_built"] = len(rows)
        pending.extend(rows)
        _LOG.info(
            "  parsed cluster=%s authority=%s rows=%d",
            source.cluster,
            source.authority,
            len(rows),
        )

    http.close()
    _LOG.info("total parsed rows: %d", len(pending))

    inserted = 0
    skipped_db = 0
    skipped_batch = 0
    by_law: dict[str, int] = {}
    by_authority: dict[str, int] = {}
    by_cluster: dict[str, int] = {}
    samples: list[EnfRow] = []

    if args.dry_run:
        for row in pending:
            inserted += 1
            by_law[row.related_law_ref] = by_law.get(row.related_law_ref, 0) + 1
            by_authority[row.issuing_authority] = by_authority.get(row.issuing_authority, 0) + 1
            by_cluster[row.cluster] = by_cluster.get(row.cluster, 0) + 1
            if len(samples) < 8:
                samples.append(row)
            if args.stop_at and inserted >= args.stop_at:
                break
    else:
        conn = open_db(args.db)
        conn.execute("BEGIN IMMEDIATE")
        batch_keys: set[tuple[str, str, str]] = set()
        try:
            for row in pending:
                if args.stop_at and inserted >= args.stop_at:
                    break
                k = (row.target_name, row.issuance_date, row.enforcement_kind)
                if k in dedup:
                    skipped_db += 1
                    continue
                if k in batch_keys:
                    skipped_batch += 1
                    continue
                batch_keys.add(k)
                try:
                    verdict = upsert(conn, row, fetched_at)
                except sqlite3.Error as exc:
                    _LOG.error(
                        "DB upsert fail name=%r date=%s: %s",
                        row.target_name,
                        row.issuance_date,
                        exc,
                    )
                    continue
                if verdict in ("insert", "update"):
                    inserted += 1
                    by_law[row.related_law_ref] = by_law.get(row.related_law_ref, 0) + 1
                    by_authority[row.issuing_authority] = (
                        by_authority.get(row.issuing_authority, 0) + 1
                    )
                    by_cluster[row.cluster] = by_cluster.get(row.cluster, 0) + 1
                    if len(samples) < 8:
                        samples.append(row)
                else:
                    skipped_db += 1
                if inserted and inserted % 50 == 0:
                    conn.commit()
                    conn.execute("BEGIN IMMEDIATE")
            conn.commit()
        finally:
            conn.close()

    print("=" * 70)
    print(
        f"建築・消防 ingest: parsed={len(pending)} inserted={inserted} "
        f"dup_db={skipped_db} dup_batch={skipped_batch}"
    )
    print(f"by_cluster: {json.dumps(by_cluster, ensure_ascii=False)}")
    print(
        "by_law: "
        + json.dumps(
            dict(sorted(by_law.items(), key=lambda kv: -kv[1])[:20]),
            ensure_ascii=False,
        )
    )
    print(
        "by_authority (top 20): "
        + json.dumps(
            dict(sorted(by_authority.items(), key=lambda kv: -kv[1])[:20]),
            ensure_ascii=False,
        )
    )
    print("samples:")
    for s in samples[:6]:
        print(
            f"  - [{s.cluster}] {s.issuance_date} | {s.target_name} | "
            f"{s.enforcement_kind} | law={s.related_law_ref} | "
            f"auth={s.issuing_authority} | url={s.source_url}"
        )

    src_summary = {
        k: {"fetched": v["fetched"], "rows": v["rows_built"]} for k, v in fetch_stats.items()
    }
    print(
        "by_source (rows_built top 12): "
        + json.dumps(
            dict(
                sorted(
                    src_summary.items(),
                    key=lambda kv: -kv[1]["rows"],
                )[:12]
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
