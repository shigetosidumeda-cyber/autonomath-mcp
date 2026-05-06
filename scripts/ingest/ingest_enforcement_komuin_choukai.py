#!/usr/bin/env python3
"""Ingest 公務員 (国家+地方+教員) 懲戒処分 公表 into ``am_enforcement_detail``.

Background:
  Public servants subject to 国家公務員法第82条 (national) /
  地方公務員法第29条 (local) / 教育公務員特例法第26条 (teacher) get
  publicly disclosed disciplinary actions:
    免職 (license_revoke)  / 停職 (contract_suspend)
    減給 (business_improvement) / 戒告 (other)

  各省庁人事課 / 都道府県人事課 / 都道府県教育委員会 / 政令市 publish
  records on a per-incident or quarterly cadence.

Sources (primary only — TOS: data-collection-phase ignore aggregator-bans
strictly observed; press releases and 公表基準 PDFs are primary sources):

  *Education prefecture lists (multi-record PDFs):*
    - 北海道教育庁: /fs/.../R{Y}.{M}.{D}.pdf per disposition date
      (~30+ PDFs; ~3-5 records each)
    - 長野県教育委員会: shobunichiran080324.pdf 一覧 (~50+ records, single PDF)
    - 山梨県教育委員会: kyouisyobun_r705.pdf / r602.pdf (per-FY single PDF)
    - 岩手県知事部局: quarterly choukai PDF per 四半期
    - 福島県知事部局: 処分事案一覧 PDF per FY (multi-record)

  *Single-incident press releases (HTML or PDF):*
    - 東京都総務局: choukai{YYYYMMDD}.pdf (per disposition)
    - 横浜市: kishahappyou.files/{YYYYMMDD}.pdf per disposition
    - 千葉県: choukai{YYMMDD}.html and shobun{YYYYMMDD}.html
    - 神戸市: {YYYYMMDD}chokai.html
    - 埼玉県: documents/.../070710_tyoukaishobun.pdf

Anonymization (per task requirements):
  - Individual public-servant subjects are anonymized to
    "{役所/学校種別} 職員 #{seq:03d} (氏名非公表)".
  - Personal-name field is NEVER carried into target_name even when the
    primary source publishes it.
  - Most published records DO NOT name individuals — they describe by 職層
    / 年代 / 性別 (e.g. "教諭・男性・40代") and 所属 (e.g. "県立学校").
    Those are kept verbatim in `reason_summary` since they are not
    identifying.

Schema mapping (am_enforcement_detail CHECK enum):
    免職             → 'license_revoke'
    懲戒免職         → 'license_revoke'
    諭旨退職         → 'license_revoke'
    停職             → 'contract_suspend'
    減給             → 'business_improvement'
    戒告             → 'other'
    訓告 / 文書注意  → 'other'

Parallel-write:
  BEGIN IMMEDIATE + busy_timeout=300000 (CLAUDE.md §5).

CLI:
  python scripts/ingest/ingest_enforcement_komuin_choukai.py \\
      [--db autonomath.db] [--dry-run] [--verbose] [--limit 1000] \\
      [--source-filter parser_substr]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import PDF_MAX_BYTES, HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.komuin_choukai")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Source:
    locale: str  # 都道府県 / 政令市 / 中央省庁 名 (logical bucket)
    authority: str  # issuing_authority (人格)
    url: str
    parser: str
    law_basis: str  # 国家公務員法第82条 / 地方公務員法第29条 / 教育公務員特例法第26条
    org_class: str  # 国家公務員 / 地方公務員 / 教員 (for breakdown)
    note: str = ""


@dataclass
class EnfRow:
    target_name: str  # anonymized: "{authority} 職員 #{seq:03d} (氏名非公表)"
    issuance_date: str  # ISO yyyy-mm-dd
    issuing_authority: str
    enforcement_kind: str  # CHECK enum
    reason_summary: str
    related_law_ref: str
    source_url: str
    org_class: str  # 国家/地方/教員
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHOUKAI_LAW_KOKKA = "国家公務員法第82条"
CHOUKAI_LAW_CHIHO = "地方公務員法第29条"
CHOUKAI_LAW_TEACHER = "教育公務員特例法第26条"

ORG_KOKKA = "国家公務員"
ORG_CHIHO = "地方公務員"
ORG_TEACHER = "教員"


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

SOURCES: list[Source] = [
    # === 教員 (Teacher) ===
    # 長野県教育委員会 — 一覧 PDF (多数記録)
    Source(
        "長野県",
        "長野県教育委員会",
        "https://www.pref.nagano.lg.jp/kyoiku/kyoiku02/kyoshokuin/shishin/chokai/documents/shobunichiran080324.pdf",
        "nagano_edu_list_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="長野県教育委員会 懲戒処分一覧 (R5.4.1～)",
    ),
    # 山梨県教育委員会 — 年度別 PDF
    Source(
        "山梨県",
        "山梨県教育委員会",
        "https://www.pref.yamanashi.jp/documents/38330/kyouisyobun_r705.pdf",
        "yamanashi_edu_list_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="山梨県教育委員会 処分一覧 (R7年度)",
    ),
    Source(
        "山梨県",
        "山梨県教育委員会",
        "https://www.pref.yamanashi.jp/documents/38330/kyouisyobun_r602.pdf",
        "yamanashi_edu_list_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="山梨県教育委員会 処分一覧 (R6年度)",
    ),
    # 北海道教育庁 — 個別公表 PDF (per disposition date)
    *[
        Source(
            "北海道",
            "北海道教育委員会",
            f"https://www.dokyoi.pref.hokkaido.lg.jp{path}",
            "hokkaido_edu_pdf",
            CHOUKAI_LAW_TEACHER,
            ORG_TEACHER,
            note=f"北海道教育委員会 学校職員懲戒 ({label})",
        )
        for path, label in [
            # FY2025 (R7)
            ("/fs/1/3/0/9/1/1/5/5/_/R7.4.24.pdf", "R7.4.24"),
            ("/fs/1/3/0/9/1/1/5/6/_/R7.5.29.pdf", "R7.5.29"),
            ("/fs/1/3/0/9/1/1/5/7/_/R7.6.12.pdf", "R7.6.12"),
            ("/fs/1/3/0/9/1/1/5/8/_/R7.7.10.pdf", "R7.7.10"),
            ("/fs/1/3/0/9/1/1/5/9/_/R7.7.24.pdf", "R7.7.24"),
            ("/fs/1/3/0/9/1/1/6/0/_/R7.8.6.pdf", "R7.8.6"),
            ("/fs/1/3/0/9/1/1/6/2/_/R7.9.4.pdf", "R7.9.4"),
            ("/fs/1/3/0/9/1/1/6/1/_/R7.9.25.pdf", "R7.9.25"),
            ("/fs/1/3/0/9/1/1/4/6/_/R7.10.30.pdf", "R7.10.30"),
            ("/fs/1/3/0/9/1/1/4/7/_/R7.11.20.pdf", "R7.11.20"),
            ("/fs/1/3/0/9/1/1/4/9/_/R7.12.4.pdf", "R7.12.4"),
            ("/fs/1/3/0/9/9/8/0/1/_/R7.12.18.pdf", "R7.12.18"),
            ("/fs/1/3/0/9/1/1/4/8/_/R7.12.18.pdf", "R7.12.18-2"),
            ("/fs/1/3/0/9/1/1/6/5/_/R8.1.15.pdf", "R8.1.15"),
            ("/fs/1/3/0/9/1/1/6/6/_/R8.1.29.pdf", "R8.1.29"),
            ("/fs/1/3/0/9/1/1/6/7/_/R8.2.12.pdf", "R8.2.12"),
            ("/fs/1/3/0/9/1/1/6/9/_/R8.2.26.pdf", "R8.2.26"),
            ("/fs/1/3/0/9/1/1/7/0/_/R8.3.12.pdf", "R8.3.12"),
            ("/fs/1/3/1/0/6/9/5/6/_/R8.3.26.pdf", "R8.3.26"),
            # FY2024 (R6)
            ("/fs/1/3/0/9/1/1/4/4/_/R6425.pdf", "R6.4.25"),
            ("/fs/1/3/0/9/1/1/3/5/_/R60516.pdf", "R6.5.16"),
            ("/fs/1/3/0/9/1/0/7/6/_/R060613.pdf", "R6.6.13"),
            ("/fs/1/3/0/9/1/1/3/6/_/R60627.pdf", "R6.6.27"),
            ("/fs/1/3/0/9/1/0/7/7/_/R060725.pdf", "R6.7.25"),
            ("/fs/1/3/0/9/1/1/3/3/_/R6.8.8.pdf", "R6.8.8"),
            ("/fs/1/3/0/9/1/0/7/9/_/R060905.pdf", "R6.9.5"),
            ("/fs/1/3/0/9/1/1/3/4/_/R6.9.26.pdf", "R6.9.26"),
            ("/fs/1/3/0/9/1/1/2/8/_/R6.10.10.pdf", "R6.10.10"),
            ("/fs/1/3/0/9/1/1/2/9/_/R6.11.07.pdf", "R6.11.7"),
            ("/fs/1/3/0/9/1/1/3/8/_/R61121.pdf", "R6.11.21"),
            ("/fs/1/3/0/9/1/1/3/0/_/R6.12.05.pdf", "R6.12.5"),
            ("/fs/1/3/0/9/1/0/8/2/_/R061219.pdf", "R6.12.19"),
            ("/fs/1/3/0/9/1/1/6/3/_/R70130.pdf", "R7.1.30"),
            ("/fs/1/3/0/9/1/1/5/0/_/R7.2.13.pdf", "R7.2.13"),
            ("/fs/1/3/0/9/1/1/6/4/_/R70225.pdf", "R7.2.25"),
            ("/fs/1/3/0/9/1/1/5/1/_/R7.3.11.pdf", "R7.3.11"),
            ("/fs/1/3/0/9/1/1/5/3/_/R7.3.27.pdf", "R7.3.27"),
            # FY2023 (R5)
            ("/fs/1/3/0/9/1/1/1/4/_/R50427.pdf", "R5.4.27"),
            ("/fs/1/3/0/9/1/1/1/6/_/R505103.pdf", "R5.5.10"),
            ("/fs/1/3/0/9/1/1/1/7/_/R50629.pdf", "R5.6.29"),
            ("/fs/1/3/0/9/1/1/1/8/_/R50713.pdf", "R5.7.13"),
            ("/fs/1/3/0/9/1/1/1/9/_/R50727.pdf", "R5.7.27"),
            ("/fs/1/3/0/9/1/0/7/1/_/R050804.pdf", "R5.8.4"),
            ("/fs/1/3/0/9/1/0/5/6/_/(R50907).pdf", "R5.9.7"),
            ("/fs/1/3/0/9/1/0/5/5/_/(R5.9.28).pdf", "R5.9.28"),
            ("/fs/1/3/0/9/1/1/2/3/_/R51026.pdf", "R5.10.26"),
        ]
    ],
    # 横浜市 (政令市) 教育委員会 — known multi-record PDFs
    Source(
        "横浜市",
        "横浜市教育委員会",
        "https://www.city.yokohama.lg.jp/city-info/koho-kocho/press/kyoiku/2025/20251114kisyahappyou.files/20251114.pdf",
        "yokohama_edu_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="横浜市教育委員会 教職員懲戒 (R7.11.14)",
    ),
    # === 国家公務員 ===
    # METI 経済産業省 quarterly
    Source(
        "経済産業省",
        "経済産業大臣",
        "https://www.meti.go.jp/press/2024/01/20250131001/20250131001.html",
        "meti_quarterly_html",
        CHOUKAI_LAW_KOKKA,
        ORG_KOKKA,
        note="METI 懲戒処分公表 R6第3四半期",
    ),
    Source(
        "経済産業省",
        "経済産業大臣",
        "https://www.meti.go.jp/press/2025/04/20250425002/20250425002.html",
        "meti_quarterly_html",
        CHOUKAI_LAW_KOKKA,
        ORG_KOKKA,
        note="METI 懲戒処分公表 R6第4四半期",
    ),
    Source(
        "経済産業省",
        "経済産業大臣",
        "https://www.meti.go.jp/press/2025/10/20251031001/20251031001.html",
        "meti_quarterly_html",
        CHOUKAI_LAW_KOKKA,
        ORG_KOKKA,
        note="METI 懲戒処分公表 R7第2四半期",
    ),
    Source(
        "経済産業省",
        "経済産業大臣",
        "https://www.meti.go.jp/press/2024/10/20241025001/20241025001.html",
        "meti_quarterly_html",
        CHOUKAI_LAW_KOKKA,
        ORG_KOKKA,
        note="METI 懲戒処分公表 R6第2四半期",
    ),
    Source(
        "経済産業省",
        "経済産業大臣",
        "https://www.meti.go.jp/press/2024/04/20240426006/20240426006.html",
        "meti_quarterly_html",
        CHOUKAI_LAW_KOKKA,
        ORG_KOKKA,
        note="METI 懲戒処分公表 R5第4四半期",
    ),
    Source(
        "経済産業省",
        "経済産業大臣",
        "https://www.meti.go.jp/press/2023/01/20240126001/20240126001.html",
        "meti_quarterly_html",
        CHOUKAI_LAW_KOKKA,
        ORG_KOKKA,
        note="METI 懲戒処分公表 R5第3四半期",
    ),
    # === 地方公務員 (知事部局) ===
    # 岩手県 知事部局 quarterly
    Source(
        "岩手県",
        "岩手県知事",
        "https://www.pref.iwate.jp/_res/projects/default_project/_page_/001/011/022/080420syoubun.pdf",
        "iwate_quarterly_pdf",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="岩手県知事部局 懲戒処分公表 R7第4四半期",
    ),
    Source(
        "岩手県",
        "岩手県知事",
        "https://www.pref.iwate.jp/_res/projects/default_project/_page_/001/011/022/kakononaiyou080420.pdf",
        "iwate_quarterly_pdf",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="岩手県知事部局 過去内容",
    ),
    # 福島県 知事部局
    Source(
        "福島県",
        "福島県知事",
        "https://www.pref.fukushima.lg.jp/uploaded/life/840986_2568632_misc.pdf",
        "fukushima_list_pdf",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="福島県知事部局 処分事案一覧 R7年度",
    ),
    Source(
        "福島県",
        "福島県知事",
        "https://www.pref.fukushima.lg.jp/uploaded/life/840986_2568662_misc.pdf",
        "fukushima_list_pdf",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="福島県知事部局 処分事案一覧 R6年度",
    ),
    # 埼玉県 教育委員会 — single-incident PDF
    Source(
        "埼玉県",
        "埼玉県教育委員会",
        "https://www.pref.saitama.lg.jp/documents/270496/070710_tyoukaishobun.pdf",
        "saitama_edu_singlepdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="埼玉県教育委員会 教職員懲戒 (R7.7.10)",
    ),
    # 千葉県 知事部局 single
    Source(
        "千葉県",
        "千葉県知事",
        "https://www.pref.chiba.lg.jp/cj-jinji/press/2025/choukai080326.html",
        "chiba_chiji_html",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="千葉県知事部局 懲戒処分 (R8.3.26)",
    ),
    # 神戸市 single
    Source(
        "神戸市",
        "神戸市長",
        "https://www.city.kobe.lg.jp/a06667/20250620chokai.html",
        "kobe_html",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="神戸市 職員懲戒 (R7.6.20)",
    ),
    # === 千葉県教育委員会 multi-record HTML ===
    Source(
        "千葉県",
        "千葉県教育委員会",
        "https://www.pref.chiba.lg.jp/kyouiku/syokuin/press/2026/shobun20260416.html",
        "chiba_edu_html",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="千葉県教育委員会 教職員懲戒 (R8.4.16)",
    ),
    # === 神奈川県教育委員会 multi-incident HTML ===
    Source(
        "神奈川県",
        "神奈川県教育委員会",
        "https://www.pref.kanagawa.jp/docs/t8d/prs/r8404680.html",
        "kanagawa_edu_html",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="神奈川県教育委員会 教員懲戒 (R7.9.4)",
    ),
    Source(
        "神奈川県",
        "神奈川県教育委員会",
        "https://www.pref.kanagawa.jp/docs/t8d/prs/r1076189.html",
        "kanagawa_edu_html",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="神奈川県教育委員会 教職員懲戒",
    ),
    Source(
        "神奈川県",
        "神奈川県教育委員会",
        "https://www.pref.kanagawa.jp/docs/t8d/prs/r1061475.html",
        "kanagawa_edu_html",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="神奈川県教育委員会 教員懲戒",
    ),
    Source(
        "神奈川県",
        "神奈川県教育委員会",
        "https://www.pref.kanagawa.jp/docs/t8d/prs/r3623782.html",
        "kanagawa_edu_html",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="神奈川県教育委員会 教員懲戒",
    ),
    Source(
        "神奈川県",
        "神奈川県知事",
        "https://www.pref.kanagawa.jp/docs/s6d/prs/r4975823.html",
        "kanagawa_edu_html",
        CHOUKAI_LAW_CHIHO,
        ORG_CHIHO,
        note="神奈川県知事部局 職員懲戒",
    ),
    # === 福岡県教育委員会 single-record PDFs ===
    *[
        Source(
            "福岡県",
            "福岡県教育委員会",
            f"https://www.pref.fukuoka.lg.jp/uploaded/attachment/{pdf_id}.pdf",
            "fukuoka_edu_singlepdf",
            CHOUKAI_LAW_TEACHER,
            ORG_TEACHER,
            note=f"福岡県教育委員会 教職員懲戒 attachment/{pdf_id}",
        )
        for pdf_id in [
            "270310",
            "270312",
            "270314",  # R7-4 (2025-11-13)
            "260222",
            "260291",  # R7-1 (2025-7-3)
            "268355",  # R7-3 (2025-10-15)
        ]
    ],
    # === 宮城県教育委員会 multi-record PDFs ===
    Source(
        "宮城県",
        "宮城県教育委員会",
        "https://www.pref.miyagi.jp/documents/59446/20250424_syokuuinnosyobun.pdf",
        "miyagi_edu_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="宮城県教育委員会 職員処分 (R7.4.24)",
    ),
    Source(
        "宮城県",
        "宮城県教育委員会",
        "https://www.pref.miyagi.jp/documents/53345/240711syokuinsyobun.pdf",
        "miyagi_edu_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="宮城県教育委員会 職員処分 (R6.7.11)",
    ),
    Source(
        "宮城県",
        "宮城県教育委員会",
        "https://www.pref.miyagi.jp/documents/62057/1023-1syokuinnosyobun.pdf",
        "miyagi_edu_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="宮城県教育委員会 職員処分 (R7.10.23)",
    ),
    Source(
        "宮城県",
        "宮城県教育委員会",
        "https://www.pref.miyagi.jp/documents/50680/20240202_syokuinnnosyobunnnituite.pdf",
        "miyagi_edu_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="宮城県教育委員会 職員処分 (R6.2.2)",
    ),
    Source(
        "宮城県",
        "宮城県教育委員会",
        "https://www.pref.miyagi.jp/documents/48083/20230714_5.pdf",
        "miyagi_edu_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="宮城県教育委員会 職員処分 (R5.7.14)",
    ),
    # === 埼玉県教育委員会 multi-record PDFs ===
    Source(
        "埼玉県",
        "埼玉県教育委員会",
        "https://www.pref.saitama.lg.jp/documents/264464/news2025020601.pdf",
        "saitama_edu_multipdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="埼玉県教育委員会 教職員懲戒6件 (R7.2.6)",
    ),
    Source(
        "埼玉県",
        "埼玉県教育委員会",
        "https://www.pref.saitama.lg.jp/documents/259800/news20241017.pdf",
        "saitama_edu_singlepdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="埼玉県教育委員会 職員懲戒 (R6.10.17)",
    ),
    # === 札幌市教育委員会 multi-record PDFs ===
    *[
        Source(
            "札幌市",
            "札幌市教育委員会",
            f"https://www.city.sapporo.jp/kyoiku/kyoshokuin/documents/{stem}.pdf",
            "sapporo_edu_pdf",
            CHOUKAI_LAW_TEACHER,
            ORG_TEACHER,
            note=f"札幌市教育委員会 学校職員懲戒 ({label})",
        )
        for stem, label in [
            ("080327_tyoukaisyobunn", "R8.3.27"),
            ("080311_tyoukaisyobunn", "R8.3.11"),
            ("080203_tyoukaisyobunn", "R8.2.3"),
            ("080120_tyoukaisyobunn", "R8.1.20"),
            ("071219_tyoukaisyobunn", "R7.12.19"),
            ("071118_tyoukaisyobunn", "R7.11.18"),
            ("070626_tyoukaisyobunn", "R7.6.26"),
            ("070609_tyoukaisyobunn", "R7.6.9"),
            ("tyokaisyobun0423_1", "R6.4.23"),
            ("tyoukaishobunn_0917", "R6.9.17"),
            ("tyoukaisyobunn_0711", "R6.7.11"),
            ("tyoukaisyobunn_1016", "R6.10.16"),
        ]
    ],
    # === 名古屋市 (政令市) 表形式 PDF ===
    Source(
        "名古屋市",
        "名古屋市教育委員会",
        "https://www.city.nagoya.jp/shikouhou/_res/projects/project_kouhou/_page_/002/000/120/385.pdf",
        "nagoya_table_pdf",
        CHOUKAI_LAW_TEACHER,
        ORG_TEACHER,
        note="名古屋市教育委員会 役職別6件 (R6.11.8)",
    ),
]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|R|H)\s*(\d+|元)\s*[年.\-．／/]\s*"
    r"(\d{1,2})\s*[月.\-．／/]\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988}


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
    if not text:
        return None
    s = _normalize(text)
    m = SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# Disposition kind classification
# ---------------------------------------------------------------------------


def _classify_kind(text: str) -> str:
    """Map 処分内容 keywords → enforcement_kind (CHECK enum)."""
    t = text or ""
    # Order matters: check more specific (免職) before substrings (停職).
    if any(k in t for k in ("懲戒免職", "免職", "諭旨退職")):
        return "license_revoke"
    if "停職" in t:
        return "contract_suspend"
    if "減給" in t:
        return "business_improvement"
    if "戒告" in t or "訓告" in t or "文書注意" in t:
        return "other"
    return "other"


def _classify_summary(reason: str) -> str:
    """Generate concise category tag from reason text."""
    r = reason or ""
    if any(
        k in r for k in ("セクハラ", "セクシュアル", "わいせつ", "盗撮", "痴漢", "性的", "性暴力")
    ):
        return "性的非違行為"
    if any(k in r for k in ("酒気帯び", "酒酔い", "飲酒運転", "酒気を帯び")):
        return "飲酒運転"
    if any(
        k in r
        for k in ("速度超過", "速度違反", "信号無視", "過失運転", "交通事故", "速度", "道交法")
    ):
        return "交通法規違反"
    if any(
        k in r
        for k in (
            "横領",
            "着服",
            "詐取",
            "詐欺",
            "不正受給",
            "不正に出金",
            "不正に受給",
            "私的流用",
        )
    ):
        return "金銭不正"
    if any(k in r for k in ("パワハラ", "パワー", "暴力", "暴行", "体罰")):
        return "暴行・パワハラ"
    if any(k in r for k in ("情報漏洩", "個人情報", "情報流出", "情報管理")):
        return "情報漏洩"
    if any(k in r for k in ("無断欠勤", "勤務時間", "職務専念", "出勤簿")):
        return "勤務不適正"
    if any(k in r for k in ("通勤手当", "手当不正", "通勤届")):
        return "手当不正受給"
    return "服務規律違反"


# ---------------------------------------------------------------------------
# Anonymization
# ---------------------------------------------------------------------------


def _anonymize_target(authority: str, role_label: str | None, seq: int) -> str:
    """Build anonymized target_name. Public-servant subjects are NEVER named.

    role_label is taken from 職層 + 性別 + 年代 metadata where available
    (e.g. "教諭・男性・40代") and added for searchability — these fields
    cannot identify a specific person on their own.
    """
    role = role_label or "職員"
    return f"{authority} {role} #{seq:03d} (氏名非公表)"


def _make_role_label(position: str | None, gender: str | None, age: str | None) -> str:
    parts = []
    if position:
        parts.append(_normalize(position))
    if gender:
        g = _normalize(gender)
        # Map common forms to short tag
        if "男" in g:
            parts.append("男性")
        elif "女" in g:
            parts.append("女性")
    if age:
        a = _normalize(age)
        if a:
            parts.append(a)
    return "・".join(parts) if parts else "職員"


# ---------------------------------------------------------------------------
# Parser: 長野県教育委員会 一覧 PDF
# ---------------------------------------------------------------------------


def parse_nagano_edu_list_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Each block starts with `R<x>.<m>.<d>` then 4-cell row:
    [所属/職位], [処分内容], [年齢], [理由文 multi-line].
    """
    out: list[EnfRow] = []
    text = pdf_text
    lines = text.splitlines()
    # Group lines into records: each record begins with WAREKI date in col 1.
    rec_start_re = re.compile(r"^(R[0-9元]+\.\s*\d{1,2}\.\s*\d{1,2})")
    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if rec_start_re.match(ln.lstrip()):
            if cur:
                blocks.append(cur)
            cur = [ln]
        else:
            if cur:
                cur.append(ln)
    if cur:
        blocks.append(cur)
    seq = 0
    for block in blocks:
        joined = " ".join(_normalize(b) for b in block)
        date_m = WAREKI_RE.search(joined) or rec_start_re.search(_normalize(block[0]))
        if not date_m:
            continue
        # Try parsing date; if rec_start_re used, normalize to wareki.
        m = WAREKI_RE.search(joined)
        if m:
            era = m.group(1)
            y_raw = m.group(2)
            try:
                y_off = 1 if y_raw == "元" else int(y_raw)
            except ValueError:
                continue
            year = ERA_OFFSET.get(era, 2018) + y_off
            mo, d = int(m.group(3)), int(m.group(4))
            if not (2010 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
                continue
            date_iso = f"{year:04d}-{mo:02d}-{d:02d}"
        else:
            continue
        # Position (e.g. 中学校教頭, 高校教諭, 特別支援学校 寄宿舎指導員)
        pos_m = re.search(
            r"(小学校|中学校|高校|高等学校|特別支援学校|養護学校)"
            r"\s*(教諭|教頭|校長|副校長|主幹教諭|養護教諭|"
            r"寄宿舎指導員|事務職員|実習助手|主任|教員|栄養職員)",
            joined,
        )
        position = pos_m.group(0) if pos_m else "教職員"
        # Disposition kind keyword
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職[\s０-９0-9]*[月日年]?[\s０-９0-9]*[月日年]?|"
            r"減給[\s０-９0-9/／]*[月日年]?[\s０-９0-9/／]*[月日年]?|戒告)",
            joined,
        )
        if not kind_m:
            continue
        kind_text = _normalize(kind_m.group(1))
        kind = _classify_kind(kind_text)
        # Age (e.g. 55 歳, 40 代)
        age_m = re.search(r"([0-9]{2})\s*(歳|代)", joined)
        age = (age_m.group(1) + age_m.group(2)) if age_m else None
        # Reason text — everything after kind keyword, truncated.
        reason_start = kind_m.end()
        reason_raw = joined[reason_start : reason_start + 1200]
        reason = _normalize(reason_raw)
        if not reason:
            reason = "詳細は出典PDF参照"
        category = _classify_summary(reason)
        full_reason = f"[{category}] 職位={position} 年齢={age or '不明'} {kind_text}: {reason}"[
            :1500
        ]
        seq += 1
        target_name = _anonymize_target(
            "長野県教育委員会",
            _make_role_label(position, None, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="長野県教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "position": position,
                    "age": age,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 山梨県教育委員会 年度別 PDF
# ---------------------------------------------------------------------------


def parse_yamanashi_edu_list_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Records each begin with date "R7.7.22" / "R8.1.28" in col 1, then
    multiple lines for [所属先], [職名], [処分量定], [事案]."""
    out: list[EnfRow] = []
    rec_re = re.compile(r"R[0-9元]+\.\s*\d{1,2}\.\s*\d{1,2}")
    lines = pdf_text.splitlines()
    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if rec_re.match(ln.lstrip()):
            if cur:
                blocks.append(cur)
            cur = [ln]
        else:
            if cur:
                cur.append(ln)
    if cur:
        blocks.append(cur)
    seq = 0
    for block in blocks:
        joined = " ".join(_normalize(b) for b in block)
        m = WAREKI_RE.search(joined)
        if not m:
            continue
        era = m.group(1)
        y_raw = m.group(2)
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            continue
        year = ERA_OFFSET.get(era, 2018) + y_off
        mo, d = int(m.group(3)), int(m.group(4))
        if not (2010 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        date_iso = f"{year:04d}-{mo:02d}-{d:02d}"
        # Position e.g. 県立学校 教諭, 公立小学校 教諭
        pos_m = re.search(
            r"(県立学校|公立小学校|公立中学校|公立高校|"
            r"公立特別支援学校|特別支援学校|小学校|中学校|高校)"
            r"\s*(教諭(?:（[^）]*）)?|教頭|校長|副校長|主幹教諭|養護教諭|"
            r"寄宿舎指導員|事務職員|実習助手|主任|栄養職員)?",
            joined,
        )
        position = pos_m.group(0).strip() if pos_m else "教職員"
        # Gender
        g_m = re.search(r"([男女])\s*$|([男女])\s+", joined)
        gender = (g_m.group(1) or g_m.group(2)) if g_m else None
        # Age
        age_m = re.search(r"(\d{2})\s*歳代?|(\d{2})\s*代", joined)
        age = None
        if age_m:
            age = (age_m.group(1) or age_m.group(2)) + "代"
        # Disposition
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職\s*\d*\s*[月年]?|"
            r"減給\s*[0-9０-９/／分のこ]*\s*\d*\s*[月年]?|戒告)",
            joined,
        )
        if not kind_m:
            continue
        kind_text = _normalize(kind_m.group(1))
        kind = _classify_kind(kind_text)
        reason_start = kind_m.end()
        reason = _normalize(joined[reason_start : reason_start + 1500])
        if not reason:
            reason = "詳細は出典PDF参照"
        category = _classify_summary(reason)
        full_reason = (
            f"[{category}] 職位={position} 年代={age or '不明'} 性別={gender or '不明'} "
            f"{kind_text}: {reason}"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(
            "山梨県教育委員会",
            _make_role_label(position, gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="山梨県教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "position": position,
                    "age": age,
                    "gender": gender,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 北海道教育庁 個別公表 PDF
# ---------------------------------------------------------------------------


def parse_hokkaido_edu_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """北海道教育委員会 公表書: 表頭 [番号 / 被処分者 / 処分内容 / 事案の概要].
    Each numbered row 1.. is a record. Issuance date is in the doc header
    "令和７年(2025年)４月２４日付".
    """
    out: list[EnfRow] = []
    text = pdf_text
    # Header date — Hokkaido PDFs have wide-spaced glyphs, so collapse all
    # whitespace before regex.
    norm_text = _normalize(text)
    collapsed = re.sub(r"\s+", "", norm_text)
    # Pattern: 令和N年(YYYY年)M月D日付  (sometimes 令和N年(YYYY年)M月D日)
    header_m = re.search(
        r"令和([0-9元]+)年\((\d{4})年\)(\d{1,2})月(\d{1,2})日",
        collapsed,
    )
    if header_m:
        year = int(header_m.group(2))
        mo = int(header_m.group(3))
        d = int(header_m.group(4))
    else:
        # Fallback: try generic wareki regex on collapsed text
        m = WAREKI_RE.search(collapsed)
        if not m:
            # Last resort: look for filename-style date in URL (e.g. R7.7.10)
            url_m = re.search(r"R(\d+)\.?(\d{1,2})\.?(\d{1,2})", source_url)
            if not url_m:
                return out
            try:
                y_off = int(url_m.group(1))
                year = 2018 + y_off
                mo = int(url_m.group(2))
                d = int(url_m.group(3))
            except ValueError:
                return out
        else:
            era = m.group(1)
            y_raw = m.group(2)
            try:
                y_off = 1 if y_raw == "元" else int(y_raw)
            except ValueError:
                return out
            year = ERA_OFFSET.get(era, 2018) + y_off
            mo = int(m.group(3))
            d = int(m.group(4))
    if not (2010 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return out
    date_iso = f"{year:04d}-{mo:02d}-{d:02d}"
    # Find each numbered record. The PDF layout has two variants:
    #   (A) seq number on same line as 所属:  "1 旭川市 中学校  ..."
    #   (B) seq number alone on a line, with surrounding lines giving 所属,
    #       内容, 概要 in a tabular block:
    #            旭 川 市 中学校 ...        懲 戒 免 職  事案概要
    #            １
    #            事 務 職 員 (男性・26歳)             事案続き
    # Strategy: scan for lines that contain ONLY a small number (1-50),
    # treat it as record marker, then accumulate ±10 lines of context.
    lines = text.splitlines()
    record_lines: list[list[str]] = []
    seq_marker_idx: list[tuple[int, int]] = []  # (line_idx, seq)
    last_seen_seq = 0
    for i, ln in enumerate(lines):
        norm = _normalize(ln).strip()
        # Variant A: leading number then 所属
        m = re.match(r"^\s*([0-9]{1,2})\s+\S", norm)
        # Variant B: line is JUST a number (and possibly whitespace)
        m_alone = re.match(r"^\s*([0-9]{1,2})\s*$", norm)
        target_m = m or m_alone
        if target_m:
            try:
                num = int(target_m.group(1))
            except ValueError:
                continue
            if num == last_seen_seq + 1 and num <= 50:
                seq_marker_idx.append((i, num))
                last_seen_seq = num
    # Build blocks from markers: each block = lines [marker_i - 5 : marker_i+1 + 5]
    # bounded by next marker.
    n = len(lines)
    for k, (idx, seq_num) in enumerate(seq_marker_idx):
        # Start: prev marker idx + 1 OR (idx - 5)
        prev_idx = seq_marker_idx[k - 1][0] + 1 if k > 0 else max(0, idx - 5)
        start = max(prev_idx, idx - 5)
        # End: next marker idx OR (idx + 12)
        next_idx = seq_marker_idx[k + 1][0] if k + 1 < len(seq_marker_idx) else n
        end = min(next_idx, idx + 12, n)
        record_lines.append(lines[start:end])
    seq = 0
    for block in record_lines:
        joined = " ".join(_normalize(b) for b in block)
        # Disposition keyword
        kind_m = re.search(
            r"(懲\s*戒\s*免\s*職|諭\s*旨\s*退\s*職|"
            r"停\s*職\s*[0-9０-９]*\s*[かヶか]?\s*月?|"
            r"減\s*給\s*[0-9０-９]*\s*[かヶか]?\s*月?\s*"
            r"(?:給\s*料\s*の?\s*[0-9０-９]+\s*分\s*の\s*[0-9０-９]+)?|"
            r"戒\s*告)",
            joined,
        )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # Subject 職位 (e.g. "特別支援学校 寄宿舎指導員 (男性・42歳)")
        pos_m = re.search(
            r"((?:札幌市|道央|胆振管内|渡島管内|空知管内|石狩管内|"
            r"後志管内|上川管内|留萌管内|宗谷管内|オホーツク管内|"
            r"十勝管内|釧路管内|根室管内|日高管内|檜山管内|"
            r"中標津町|別海町|釧路市|帯広市|旭川市|函館市|苫小牧市|"
            r"小樽市|室蘭市|岩見沢市|北見市|江別市|登別市|名寄市|"
            r"恵庭市|千歳市|稚内市|滝川市|赤平市|芦別市|歌志内市|"
            r"砂川市|深川市|根室市|富良野市|伊達市|北広島市|石狩市|"
            r"網走市|紋別市)?\s*"
            r"(?:小学校|中学校|高校|高等学校|特別支援学校|養護学校))",
            joined,
        )
        school = _normalize(pos_m.group(0)) if pos_m else "学校"
        role_m = re.search(
            r"(教諭|教頭|校長|副校長|主幹教諭|養護教諭|寄宿舎指導員|"
            r"事務職員|実習助手|主任|教員|栄養職員|事務長|司書)",
            joined,
        )
        role = role_m.group(1) if role_m else "教職員"
        # Gender + age e.g. "(男性・42歳)"
        ga_m = re.search(r"\(\s*([男女])性?\s*[・,，、]\s*(\d{2})\s*歳\s*\)", joined)
        gender = ga_m.group(1) if ga_m else None
        age = (ga_m.group(2) + "歳") if ga_m else None
        # Reason: take everything after kind_m.end() up to next seq or end.
        reason_start = kind_m.end()
        reason_raw = joined[reason_start : reason_start + 1500]
        reason = _normalize(reason_raw)
        if not reason:
            reason = "詳細は出典PDF参照"
        category = _classify_summary(reason)
        full_reason = (
            f"[{category}] 学校={school} 職位={role} 年齢={age or '不明'} "
            f"性別={gender or '不明'} {kind_text}: {reason}"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(
            "北海道教育委員会",
            _make_role_label(f"{school}{role}", gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="北海道教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "school": school,
                    "role": role,
                    "age": age,
                    "gender": gender,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 横浜市教育委員会 multi-record PDF
# ---------------------------------------------------------------------------


def parse_yokohama_edu_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Yokohama PDF format: each record is a labeled block:
        所属 / 被処分者 / 処分日 / 処分内容 / 監督者責任 / 概要
    Records are separated by reset of "所属" label.
    """
    out: list[EnfRow] = []
    text = pdf_text
    # Split by 所属 occurrences
    chunks = re.split(r"\n\s*所\s*属\s+", text)
    seq = 0
    for chunk in chunks[1:]:  # First chunk is header.
        block = "所属 " + chunk
        joined = " ".join(_normalize(line) for line in block.splitlines())
        # Date from 処分日 row
        date_m = re.search(
            r"処\s*分\s*日\s+([^\s]+令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
            joined,
        )
        if not date_m:
            date_m = WAREKI_RE.search(joined)
        if not date_m:
            continue
        date_iso = _parse_date(date_m.group(0))
        if not date_iso:
            continue
        # Disposition kind
        kind_m = re.search(
            r"処\s*分\s*内\s*容\s+(懲戒免職[^\s]*|諭旨退職|免職|停職\s*\d*\s*[ヶか]?\s*月?|"
            r"減給\s*\d*\s*[ヶか]?\s*月?[^\s]*|戒告|訓告|文書注意)",
            joined,
        )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # 所属 (e.g. 特別支援学校, 小学校, 中学校)
        school_m = re.search(r"所\s*属\s+([^\s\n被]{1,30}?)(?=\s+被)", joined)
        school = _normalize(school_m.group(1)) if school_m else "学校"
        # 被処分者 (e.g. 教諭（男性・40代）)
        subj_m = re.search(
            r"被\s*処\s*分\s*者\s+([^\s\n処]{1,40}?)(?=\s+処)",
            joined,
        )
        subj = _normalize(subj_m.group(1)) if subj_m else "教諭"
        # 概要
        gaiyou_m = re.search(r"概\s*要\s+(.+?)(?=所\s*属\s+|$)", joined)
        gaiyou = _normalize(gaiyou_m.group(1)) if gaiyou_m else ""
        if not gaiyou:
            gaiyou = "詳細は出典PDF参照"
        category = _classify_summary(gaiyou)
        full_reason = (f"[{category}] 所属={school} 被処分者={subj} {kind_text}: {gaiyou}")[:1500]
        seq += 1
        target_name = _anonymize_target("横浜市教育委員会", subj, seq)
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="横浜市教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "school": school,
                    "subj": subj,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: METI quarterly HTML
# ---------------------------------------------------------------------------


def parse_meti_quarterly_html(html: str, source_url: str) -> list[EnfRow]:
    """METI quarterly public-disclosure page. The HTML body lists each case
    in a paragraph form:
        １．○○局 ●● 戒告 (yyyy.m.d) 公務外非違行為 ...
    Sometimes there's an attached PDF — but text inline is sufficient for
    most quarterly notices.
    """
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize(soup.get_text("\n", strip=True))
    # Each case prefix: "事案１" or numbering plus 処分量定 line.
    case_re = re.compile(
        r"(?:事案[\s０-９0-9]*|^\s*[０-９0-9]+[.\s．]\s*)"
        r"(?:[^\n]*?)\n"
        r"((?:[^\n]+\n){0,12})",
        re.MULTILINE,
    )
    # Fallback simpler approach: split text by 事案 markers
    blocks = re.split(r"(?:事案\s*[０-９0-9]+|^\s*[０-９0-9]+\s*[\.．])", text, flags=re.MULTILINE)
    seq = 0
    for block in blocks[1:]:
        block_norm = block[:2500]
        # Disposition keyword
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職[\s０-９0-9]*[かヶか]?[\s０-９0-9]*月?|"
            r"減給[\s０-９0-9/／のこ]*[\s０-９0-9]*月?|戒告|訓告)",
            block_norm,
        )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # Date — try seireki first
        date_m = SEIREKI_RE.search(block_norm) or WAREKI_RE.search(block_norm)
        if not date_m:
            continue
        date_iso = _parse_date(date_m.group(0))
        if not date_iso:
            continue
        # Position / dept
        dept_m = re.search(
            r"(本省|資源エネルギー庁|特許庁|中小企業庁|"
            r"[一-鿿]{2,8}局|[一-鿿]{2,8}庁)",
            block_norm,
        )
        dept = dept_m.group(0) if dept_m else "経済産業省"
        # Reason text — take first 1000 chars after kind
        reason_start = kind_m.end()
        reason = block_norm[reason_start : reason_start + 1000].strip()
        if not reason or len(reason) < 5:
            # Try preceding text as reason fallback
            reason = block_norm[: kind_m.start()][-500:].strip()
        category = _classify_summary(reason)
        full_reason = f"[{category}] 部局={dept} {kind_text}: {reason}"[:1500]
        seq += 1
        target_name = _anonymize_target("経済産業省", dept, seq)
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="経済産業大臣",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_KOKKA,
                source_url=source_url,
                org_class=ORG_KOKKA,
                extra={
                    "kind_text": kind_text,
                    "dept": dept,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 岩手県知事部局 quarterly PDF
# ---------------------------------------------------------------------------


def parse_iwate_quarterly_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Iwate quarterly format: each record numbered "１" "２" "３"... with
    columns [処分事由, 処分年月日, 処分内容, 所属, 年齢, 性別, 事案発生時期]
    plus a multi-line ≪事案の概要≫ block.
    """
    out: list[EnfRow] = []
    # Split by record numbering (e.g. "1\n", "2\n") at column 1
    text = pdf_text
    blocks = re.split(r"\n\s*([０-９0-9]+)\s*\n", text)
    # blocks[0] is header preamble; pairs (num, content) follow.
    seq = 0
    for i in range(1, len(blocks), 2):
        try:
            num_raw = blocks[i].strip()
            content = blocks[i + 1] if i + 1 < len(blocks) else ""
        except IndexError:
            break
        joined = " ".join(_normalize(line) for line in content.splitlines())
        # Date — wareki R8.x.y inside content
        date_m = WAREKI_RE.search(joined)
        if not date_m:
            continue
        date_iso = _parse_date(date_m.group(0))
        if not date_iso:
            continue
        # Kind
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職\s*\d*\s*[ヶか]?\s*月?|"
            r"減給\s*\d*\s*[ヶか]?\s*月?|戒告|訓告)",
            joined,
        )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # 所属部局
        dept_m = re.search(
            r"(総務部|農林水産部|保健福祉部|県土整備部|商工労働観光部|"
            r"環境生活部|文化スポーツ部|復興防災部|秘書広報室|教育委員会|"
            r"会計管理室|警察本部|出納局)",
            joined,
        )
        dept = dept_m.group(0) if dept_m else "岩手県知事部局"
        # Position level
        rank_m = re.search(
            r"(主任主査級|主査級|主事級|一般級|再任用職員|総括[^,\s]*|主幹[^,\s]*|副[^\s]+級)",
            joined,
        )
        rank = rank_m.group(0) if rank_m else "職員"
        # Gender / age
        ga_m = re.search(r"(\d{2})\s+([男女])", joined)
        age = ga_m.group(1) if ga_m else None
        gender = ga_m.group(2) if ga_m else None
        # Reason — take ≪事案の概要≫ block
        reason_m = re.search(r"≪\s*事案の概要\s*≫\s*(.+?)(?=≪|$)", joined)
        if reason_m:
            reason = _normalize(reason_m.group(1))
        else:
            reason = _normalize(joined[kind_m.end() : kind_m.end() + 1200])
        if not reason:
            reason = "詳細は出典PDF参照"
        category = _classify_summary(reason)
        full_reason = (
            f"[{category}] 部局={dept} 職位={rank} 年代={age or '不明'} "
            f"性別={gender or '不明'} {kind_text}: {reason}"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(
            "岩手県知事",
            _make_role_label(f"{dept}{rank}", gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="岩手県知事",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_CHIHO,
                source_url=source_url,
                org_class=ORG_CHIHO,
                extra={
                    "kind_text": kind_text,
                    "dept": dept,
                    "rank": rank,
                    "age": age,
                    "gender": gender,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 福島県知事部局 list PDF
# ---------------------------------------------------------------------------


def parse_fukushima_list_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Fukushima format: table per record [被処分者 / 処分の程度 / 処分年月日 / 事件概要].
    Each record's date "R7.5.13" appears in col 3.
    """
    out: list[EnfRow] = []
    text = pdf_text
    lines = text.splitlines()
    # Find anchor lines with WAREKI date and disposition keyword.
    seq = 0
    # Pre-scan windows of 10 lines around each WAREKI occurrence.
    n = len(lines)
    used = set()
    for i, ln in enumerate(lines):
        if i in used:
            continue
        norm = _normalize(ln)
        date_m = WAREKI_RE.search(norm)
        if not date_m:
            continue
        # Window: 5 lines before, 15 lines after
        start = max(0, i - 5)
        end = min(n, i + 20)
        window = " ".join(_normalize(lines[j]) for j in range(start, end))
        # Skip if window is too short
        if len(window) < 50:
            continue
        date_iso = _parse_date(date_m.group(0))
        if not date_iso:
            continue
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職[\s0-9０-９]*[かヶ]?\s*月?|"
            r"減給[\s0-9０-９]*\s*[かヶ]?\s*月?|戒告|訓告)",
            window,
        )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # Subject: "いわき方部の出先機関の一般職員"
        subj_m = re.search(
            r"([一-鿿]{2,4}方部の[^\n]{1,20}の[^\n]{1,15}職員)",
            window,
        )
        subj = subj_m.group(0) if subj_m else "知事部局職員"
        # Gender + age "(20代、女性)"
        ga_m = re.search(r"\(\s*(\d{2})\s*代\s*[、,，]\s*([男女])性?\s*\)", window)
        age = (ga_m.group(1) + "代") if ga_m else None
        gender = ga_m.group(2) if ga_m else None
        # Reason — content after kind
        reason = _normalize(window[kind_m.end() : kind_m.end() + 1200])
        if not reason or len(reason) < 5:
            reason = "詳細は出典PDF参照"
        category = _classify_summary(reason)
        full_reason = (
            f"[{category}] 所属={subj} 年代={age or '不明'} 性別={gender or '不明'} "
            f"{kind_text}: {reason}"
        )[:1500]
        seq += 1
        # Mark used lines so we don't double-extract
        used.update(range(start, end))
        target_name = _anonymize_target(
            "福島県知事",
            _make_role_label(subj, gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="福島県知事",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_CHIHO,
                source_url=source_url,
                org_class=ORG_CHIHO,
                extra={
                    "kind_text": kind_text,
                    "subj": subj,
                    "age": age,
                    "gender": gender,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 埼玉県教育委員会 single-incident PDF
# ---------------------------------------------------------------------------


def parse_saitama_edu_singlepdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Saitama single-record format: labeled fields
    [処分内容, 処分年月日, 職名・年齢・性別, 所属名, 発生年月日, 事件・事故の概要].
    """
    text = _normalize(pdf_text)
    kind_m = re.search(
        r"処\s*分\s*内\s*容\s+(懲戒免職[^\n]*|諭旨退職|免職|停職[^\n]*|"
        r"減給[^\n]*|戒告|訓告)",
        text,
    )
    if not kind_m:
        return []
    kind_text = re.sub(r"\s+", "", kind_m.group(1))
    kind = _classify_kind(kind_text)
    date_m = re.search(
        r"処\s*分\s*年\s*月\s*日\s+(令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        text,
    )
    if not date_m:
        date_m = WAREKI_RE.search(text)
    if not date_m:
        return []
    date_iso = _parse_date(date_m.group(0) if hasattr(date_m, "group") else date_m)
    if not date_iso:
        return []
    # Position
    pos_m = re.search(
        r"職\s*名\s*・\s*年\s*齢\s*・\s*性\s*別\s+([^\n]{1,40})",
        text,
    )
    position = _normalize(pos_m.group(1)) if pos_m else "教職員"
    # 所属
    school_m = re.search(r"所\s*属\s*名\s+([^\n]{1,40})", text)
    school = _normalize(school_m.group(1)) if school_m else "公立学校"
    # Gaiyou — last labeled field
    gaiyou_m = re.search(
        r"事\s*件\s*・\s*事\s*故\s*の\s*概\s*要\s*\n+(.+?)(?=●|問\s*合\s*せ|\Z)", pdf_text, re.S
    )
    gaiyou = _normalize(gaiyou_m.group(1) if gaiyou_m else "")[:1200]
    if not gaiyou:
        gaiyou = "詳細は出典PDF参照"
    category = _classify_summary(gaiyou)
    full_reason = f"[{category}] 学校={school} 職位={position} {kind_text}: {gaiyou}"[:1500]
    target_name = _anonymize_target("埼玉県教育委員会", position, 1)
    return [
        EnfRow(
            target_name=target_name,
            issuance_date=date_iso,
            issuing_authority="埼玉県教育委員会",
            enforcement_kind=kind,
            reason_summary=full_reason,
            related_law_ref=CHOUKAI_LAW_TEACHER,
            source_url=source_url,
            org_class=ORG_TEACHER,
            extra={
                "kind_text": kind_text,
                "school": school,
                "position": position,
                "category": category,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Parser: 千葉県知事部局 single HTML
# ---------------------------------------------------------------------------


def parse_chiba_chiji_html(html: str, source_url: str) -> list[EnfRow]:
    """Chiba 知事部局 single-incident HTML page format."""
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize(soup.get_text("\n", strip=True))
    kind_m = re.search(
        r"(懲戒免職|諭旨退職|免職|停職[\s0-9０-９]*[ヶか]?\s*月?|"
        r"減給[\s0-9０-９]*\s*[ヶか]?\s*月?|戒告|訓告)",
        text,
    )
    if not kind_m:
        return []
    kind_text = re.sub(r"\s+", "", kind_m.group(1))
    kind = _classify_kind(kind_text)
    # Find date — most recent processing date in body (after 処分日)
    date_m = re.search(r"処\s*分\s*日[^\d]*(令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", text)
    if not date_m:
        date_m = WAREKI_RE.search(text)
    if not date_m:
        return []
    raw = date_m.group(1) if hasattr(date_m, "group") and date_m.lastindex else date_m.group(0)
    date_iso = _parse_date(raw)
    if not date_iso:
        return []
    dept_m = re.search(
        r"(総務部|農林水産部|保健福祉部|県土整備部|商工労働部|環境生活部|文化スポーツ部|"
        r"復興防災部|警察本部|教育委員会|会計管理室|出納局|健康福祉部)",
        text,
    )
    dept = dept_m.group(0) if dept_m else "千葉県知事部局"
    # Subject summary, may include 性別 + 年齢 + 出先
    subj_m = re.search(
        r"([一-鿿]{2,8}部の[^\n]{1,20}の[^\n]{1,15}職員|"
        r"出先機関の[^\n]{1,15}職員|(?:本庁|出先機関)\s*[^\n]{1,15}職員)",
        text,
    )
    subj = subj_m.group(0) if subj_m else "知事部局職員"
    gaiyou = text[max(0, kind_m.end() - 50) : kind_m.end() + 1200]
    category = _classify_summary(gaiyou)
    full_reason = f"[{category}] 部局={dept} 所属={subj} {kind_text}: {gaiyou}"[:1500]
    target_name = _anonymize_target("千葉県知事", subj, 1)
    return [
        EnfRow(
            target_name=target_name,
            issuance_date=date_iso,
            issuing_authority="千葉県知事",
            enforcement_kind=kind,
            reason_summary=full_reason,
            related_law_ref=CHOUKAI_LAW_CHIHO,
            source_url=source_url,
            org_class=ORG_CHIHO,
            extra={
                "kind_text": kind_text,
                "dept": dept,
                "category": category,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Parser: 神戸市 single HTML
# ---------------------------------------------------------------------------


def parse_kobe_html(html: str, source_url: str) -> list[EnfRow]:
    """Kobe-shi multi-incident HTML page — typically 1-3 cases per page."""
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize(soup.get_text("\n", strip=True))
    # Date — generally a single 処分日 at top
    date_m = re.search(r"令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", text)
    if not date_m:
        date_m = SEIREKI_RE.search(text)
    if not date_m:
        return out
    date_iso = _parse_date(date_m.group(0))
    if not date_iso:
        return out
    # Each case: blocks containing 戒告/停職/減給/免職 keyword paragraphs
    blocks = re.split(r"処\s*分\s*案\s*件|案\s*件\s*[０-９0-9]+", text)
    seq = 0
    for block in blocks:
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職\s*\d*\s*[ヶか]?\s*月?|"
            r"減給\s*\d*\s*[ヶか]?\s*月?|戒告|訓告)",
            block,
        )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # 所属
        dept_m = re.search(
            r"([一-鿿]{2,8}局|[一-鿿]{2,8}課|"
            r"[一-鿿]{2,4}区(?:[一-鿿]{1,5})?|消防局|水道局|交通局)",
            block,
        )
        dept = dept_m.group(0) if dept_m else "神戸市"
        # Reason
        reason = block[kind_m.end() : kind_m.end() + 1200].strip()
        if not reason or len(reason) < 5:
            reason = block[max(0, kind_m.start() - 500) : kind_m.start()].strip()
        category = _classify_summary(reason)
        full_reason = f"[{category}] 部局={dept} {kind_text}: {reason}"[:1500]
        seq += 1
        target_name = _anonymize_target("神戸市長", dept, seq)
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="神戸市長",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_CHIHO,
                source_url=source_url,
                org_class=ORG_CHIHO,
                extra={
                    "kind_text": kind_text,
                    "dept": dept,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 千葉県教育委員会 press HTML (multi-record, labeled "（1）被処分者...")
# ---------------------------------------------------------------------------


def parse_chiba_edu_html(html: str, source_url: str) -> list[EnfRow]:
    """Chiba edu press release HTML with （1）被処分者 ... （5）根拠条項 fields,
    1-3 records per page. Names may be present — strip them per anonymization
    policy."""
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize(soup.get_text("\n", strip=True))
    # Find page-level disposition date in title 「令和X年Y月Z日」
    title_date_m = WAREKI_RE.search(text)
    page_date = _parse_date(title_date_m.group(0)) if title_date_m else None
    # Each record block starts with （1）被処分者 / (1)被処分者
    blocks = re.split(r"[（(][1１][）)]\s*被処分者", text)
    seq = 0
    for block in blocks[1:]:
        # Truncate block to next "（1）" or end
        next_m = re.search(r"[（(][1１][）)]\s*被処分者", block)
        if next_m:
            block = block[: next_m.start()]
        # Truncate to "再発防止" boundary
        end_m = re.search(r"再発防止|綱紀の粛正|問合せ先", block)
        if end_m:
            block = block[: end_m.start()]
        # Position / 所属
        pos_m = re.search(
            r"[（(][2２][）)]\s*所\s*属\s*[　\s]*([^\n（()(]{1,40})",
            block,
        )
        school = _normalize(pos_m.group(1)) if pos_m else "公立学校"
        # 処分内容
        kind_m = re.search(
            r"[（(][3３][）)]\s*処\s*分\s*内\s*容\s*[　\s]*"
            r"(懲戒免職[^\n（(]*|諭旨退職|免職|停職[^\n（(]*|減給[^\n（(]*|戒告|訓告)",
            block,
        )
        if not kind_m:
            kind_m = re.search(
                r"(懲戒免職|諭旨退職|免職|停職[^\n（(]*|減給[^\n（(]*|戒告|訓告)",
                block,
            )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # 事故の概要
        gaiyou_m = re.search(
            r"[（(][4４][）)]\s*事\s*故\s*の\s*概\s*要\s*[　\s]*(.+?)(?=[（(][5５][）)]|$)",
            block,
            flags=re.S,
        )
        gaiyou = _normalize(gaiyou_m.group(1)) if gaiyou_m else ""
        if not gaiyou:
            gaiyou = "詳細は出典ページ参照"
        # Position role from 被処分者 (position word + age + gender)
        head_m = re.search(
            r"([男女]性?教諭[^\n]{0,20}|教諭[^\n]{0,30}|[^\n]{0,30}[歳代][^\n]{0,30})",
            block[:200],
        )
        head = _normalize(head_m.group(0)) if head_m else "教職員"
        category = _classify_summary(gaiyou)
        full_reason = (f"[{category}] 所属={school} {head} {kind_text}: {gaiyou}")[:1500]
        seq += 1
        target_name = _anonymize_target("千葉県教育委員会", head, seq)
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=page_date or "1900-01-01",
                issuing_authority="千葉県教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "school": school,
                    "head": head,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 神奈川県教育委員会 press HTML (multi-incident paragraph, named ind.)
# ---------------------------------------------------------------------------


def parse_kanagawa_edu_html(html: str, source_url: str) -> list[EnfRow]:
    """Kanagawa edu press: prose with 「事案の概要」「処分内容」「処分年月日」
    sub-headings, sometimes 2-3 incidents per page. Names are sometimes
    present — anonymize."""
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize(soup.get_text("\n", strip=True))
    # Each case has "1　<name> 不祥事" pattern, then sub-1/2/3.
    # Use 処分内容 anchor as record marker.
    kind_anchors = list(
        re.finditer(
            r"処\s*分\s*内\s*容\s*[　\s]*"
            r"(懲戒免職[^\n（(]*|諭旨退職|免職|停職[^\n（(]*|減給[^\n（(]*|戒告|訓告)",
            text,
        )
    )
    if not kind_anchors:
        return out
    # For each kind anchor, look back ~600 chars for 事案の概要 and forward 200 for 処分年月日
    seq = 0
    for k_m in kind_anchors:
        # Reason: 事案の概要 in preceding 800 chars
        win_start = max(0, k_m.start() - 800)
        prev_window = text[win_start : k_m.start()]
        gaiyou_m = re.search(r"事\s*案\s*の\s*概\s*要\s*(.+?)$", prev_window, flags=re.S)
        gaiyou = _normalize(gaiyou_m.group(1)) if gaiyou_m else _normalize(prev_window[-500:])
        # Date: 処分年月日 in next ~200 chars
        post_window = text[k_m.end() : k_m.end() + 200]
        date_m = WAREKI_RE.search(post_window)
        if not date_m:
            date_m = WAREKI_RE.search(text)
        if not date_m:
            continue
        date_iso = _parse_date(date_m.group(0))
        if not date_iso:
            continue
        kind_text = re.sub(r"\s+", "", k_m.group(1))
        kind = _classify_kind(kind_text)
        # Position role: search the gaiyou for 教諭/教頭/校長 + age/gender
        role_m = re.search(
            r"([一-鿿]{2,8}市?(?:内?の)?(?:県立|公立|市立|町立|村立)?\s*"
            r"(?:小学校|中学校|高校|高等学校|特別支援学校|養護学校)\s*"
            r"(?:総括)?(教諭|教頭|校長|副校長|主幹教諭|養護教諭|寄宿舎指導員|事務職員|主任|教員|栄養職員))",
            gaiyou,
        )
        role = _normalize(role_m.group(0)) if role_m else "教職員"
        ga_m = re.search(r"\(\s*(\d{2})\s*[歳代]\s*[、,，・]\s*([男女])性?\s*\)", gaiyou)
        gender = ga_m.group(2) if ga_m else None
        age = (ga_m.group(1) + "歳") if ga_m else None
        category = _classify_summary(gaiyou)
        full_reason = (
            f"[{category}] 学校={role} 性別={gender or '不明'} 年齢={age or '不明'} "
            f"{kind_text}: {gaiyou}"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(
            "神奈川県教育委員会",
            _make_role_label(role, gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="神奈川県教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "role": role,
                    "age": age,
                    "gender": gender,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 福岡県 単件 PDF (1-record format with labeled 1-7 fields)
# ---------------------------------------------------------------------------


def parse_fukuoka_edu_singlepdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Single-record PDF with labeled fields:
        1 被処分者  Name(男)
        2 年齢     XX歳代
        3 所属     <地区>の<学校種>
        4 職名     教諭/講師
        5 処分時期  令和X年X月X日
        6 処分の程度 免職/停職/減給/戒告
        7 処分の理由 ...
    Per anonymization rule: names in field 1 are STRIPPED.
    """
    text = _normalize(pdf_text)
    # 5 処分時期
    date_m = re.search(
        r"[5５]\s+処\s*分\s*時\s*期\s+(令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        text,
    )
    if not date_m:
        date_m = WAREKI_RE.search(text)
    if not date_m:
        return []
    raw_date = date_m.group(1) if date_m.lastindex else date_m.group(0)
    date_iso = _parse_date(raw_date)
    if not date_iso:
        return []
    # 6 処分の程度
    kind_m = re.search(
        r"[6６]\s+処\s*分\s*の\s*程\s*度\s+"
        r"(懲戒免職[^\n]*|諭旨退職|免職|停職[^\n]*|減給[^\n]*|戒告|訓告)",
        text,
    )
    if not kind_m:
        kind_m = re.search(
            r"(懲戒免職|諭旨退職|免職|停職[^\n]*|減給[^\n]*|戒告|訓告)",
            text,
        )
    if not kind_m:
        return []
    kind_text = re.sub(r"\s+", "", kind_m.group(1))
    kind = _classify_kind(kind_text)
    # 2 年齢
    age_m = re.search(r"[2２]\s+年\s*齢\s+([\d０-９]{1,3})\s*歳代?", text)
    age = (age_m.group(1) + "歳代") if age_m else None
    # 3 所属
    sho_m = re.search(r"[3３]\s+所\s*属\s+([^\n]{1,50})", text)
    school = _normalize(sho_m.group(1)) if sho_m else "学校"
    # 4 職名
    job_m = re.search(r"[4４]\s+職\s*名\s+([^\n]{1,30})", text)
    job = _normalize(job_m.group(1)) if job_m else "教職員"
    # 1 被処分者: extract gender only (NEVER name)
    bsho_m = re.search(r"[1１]\s+被\s*処\s*分\s*者\s+[^\n]*?(\([男女]\)|（[男女]）)", text)
    gender = None
    if bsho_m:
        gtxt = bsho_m.group(1)
        gender = "男" if "男" in gtxt else "女"
    # 7 処分の理由 — multi-line until end of doc
    reason_m = re.search(
        r"[7７]\s+処\s*分\s*の\s*理\s*由\s*\n+(.+?)(?=\Z|担当|問合せ|印\s*刷|教育委員会)",
        pdf_text,
        re.S,
    )
    reason = _normalize(reason_m.group(1)) if reason_m else ""
    if not reason:
        # Fallback: take everything after kind_m.end()
        reason = _normalize(text[kind_m.end() : kind_m.end() + 1200])
    if not reason:
        reason = "詳細は出典PDF参照"
    # Determine authority based on header
    if "県立学校" in text and "市町村立" not in text[:300]:
        authority = "福岡県教育委員会(県立)"
    elif "市町村立" in text:
        authority = "福岡県教育委員会(市町村立)"
    else:
        authority = "福岡県教育委員会"
    category = _classify_summary(reason)
    full_reason = (
        f"[{category}] 所属={school} 職名={job} 性別={gender or '不明'} 年齢={age or '不明'} "
        f"{kind_text}: {reason}"
    )[:1500]
    target_name = _anonymize_target(
        authority,
        _make_role_label(f"{school}{job}", gender, age),
        1,
    )
    return [
        EnfRow(
            target_name=target_name,
            issuance_date=date_iso,
            issuing_authority=authority,
            enforcement_kind=kind,
            reason_summary=full_reason,
            related_law_ref=CHOUKAI_LAW_TEACHER,
            source_url=source_url,
            org_class=ORG_TEACHER,
            extra={
                "kind_text": kind_text,
                "school": school,
                "job": job,
                "age": age,
                "gender": gender,
                "category": category,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Parser: 宮城県教育委員会 multi-incident PDF (1-9 numbered fields per record)
# ---------------------------------------------------------------------------


def parse_miyagi_edu_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Miyagi 職員の処分について PDF — each record has 9 numbered fields:
       1 発生年月日 / 2 所属の所在地区 / 3 所属の種別 / 4 年齢 /
       5 管理職、一般職の別 / 6 教育職員と教育職員以外の別 /
       7 事件・事故の概要 / 8 処分内容 / 9 処分年月日
    Multi-record per PDF (separated by 「職員の処分について（その１/２...）」).
    Names appear in field 7 — STRIP per anonymization rule.
    """
    out: list[EnfRow] = []
    text = pdf_text
    # Split by 「職員の処分について」 markers
    blocks = re.split(r"職\s*員\s*の\s*処\s*分\s*に\s*つ\s*い\s*て\s*[（(][^）)]*[）)]", text)
    seq = 0
    for block in blocks[1:]:  # First chunk is preamble
        norm = _normalize(block)
        # Truncate to 3000 chars per record
        norm_short = norm[:3500]
        # 処分年月日 (most reliable date) — labeled as 8 or 9 depending on schema
        date_m = re.search(
            r"[8９９8]?\s*処\s*分\s*年\s*月\s*日\s*\n?\s*(令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
            norm_short,
        )
        if not date_m:
            date_m = re.search(
                r"処\s*分\s*年\s*月\s*日[^令]*?(令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
                norm_short,
            )
        if not date_m:
            # Fallback: header date (e.g. "令和６年７月１１日")
            date_m = WAREKI_RE.search(norm_short)
        if not date_m:
            continue
        raw_date = date_m.group(1) if date_m.lastindex else date_m.group(0)
        date_iso = _parse_date(raw_date)
        if not date_iso:
            continue
        # 処分内容 — labeled 7 or 8
        kind_m = re.search(
            r"処\s*分\s*内\s*容\s*\n?\s*(?:懲戒処分として\s*)?[「『]?\s*"
            r"(懲戒免職|諭旨退職|免職|停職[^\n「」『』（()]*|減給[^\n「」『』（()]*|戒告|訓告)",
            norm_short,
        )
        if not kind_m:
            kind_m = re.search(
                r"(懲戒免職|諭旨退職|免職|停職[^\n「」『』（()]*|減給[^\n「」『』（()]*|戒告|訓告)",
                norm_short,
            )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # 所属の種別 (labeled 2 or 3)
        sho_m = re.search(
            r"所\s*属\s*の\s*種\s*別\s*\n?\s*([^\n]{1,30})",
            norm_short,
        )
        school_kind = _normalize(sho_m.group(1)) if sho_m else "学校"
        # 所属の所在地区 (only present in newer schema)
        chiku_m = re.search(
            r"所\s*属\s*の\s*所\s*在\s*地\s*区\s*\n?\s*([^\n]{1,30})",
            norm_short,
        )
        chiku = _normalize(chiku_m.group(1)) if chiku_m else "県内"
        # 年齢
        age_m = re.search(r"年\s*齢\s*\n?\s*([\d０-９]{1,3})\s*歳", norm_short)
        age = (age_m.group(1) + "歳") if age_m else None
        # 管理職別
        kanri_m = re.search(r"(管理職|一般職)", norm_short)
        kanri = kanri_m.group(1) if kanri_m else "一般職"
        # 事件・事故の概要 — multi-line, may contain name. ANONYMIZE.
        gaiyou_m = re.search(
            r"事\s*件\s*・\s*事\s*故\s*の\s*概\s*要\s*\n+(.+?)"
            r"(?=処\s*分\s*内\s*容|\Z)",
            block,
            re.S,
        )
        gaiyou_raw = (
            gaiyou_m.group(1) if gaiyou_m else norm_short[kind_m.end() : kind_m.end() + 1500]
        )
        # Strip Japanese name patterns: 「<姓> <名>」 of 2-4 kanji each
        gaiyou_clean = re.sub(
            r"(?:[一-鿿]{1,4}\s*[一-鿿]{1,4})\s*(?:は|が|に|を|の)?",
            "[氏名非公表]",
            gaiyou_raw,
            count=2,  # only strip first 2 to avoid mangling other text
        )
        gaiyou = _normalize(gaiyou_clean[:1200])
        if not gaiyou:
            gaiyou = "詳細は出典PDF参照"
        category = _classify_summary(gaiyou)
        full_reason = (
            f"[{category}] 地区={chiku} 学校種={school_kind} 年齢={age or '不明'} "
            f"職層={kanri} {kind_text}: {gaiyou}"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(
            "宮城県教育委員会",
            _make_role_label(f"{chiku}{school_kind}{kanri}", None, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="宮城県教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "chiku": chiku,
                    "school_kind": school_kind,
                    "age": age,
                    "kanri": kanri,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 埼玉県教育委員会 multi-record PDF (【処分N】 marker format)
# ---------------------------------------------------------------------------


def parse_saitama_edu_multipdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Saitama multi-record format with 【処分N】 markers.
    Each record has labeled fields:
        1 処 分 内 容    懲戒処分（XXX）
        2 処 分 年 月 日 令和X年X月X日
        3 職名・年齢・性別 教諭・XX歳・男性 (or 職名・氏名・年齢・性別 with name)
        4 地 域 ・ 校 種 / 所属名 (region+school or specific school)
        5 発 生 年 月 日
        6 事件・事故の概要 ...
    Names in field 3 (when 氏名 present) are STRIPPED.
    """
    out: list[EnfRow] = []
    text = pdf_text  # preserve newlines
    # Split by 【処分N】 markers
    blocks = re.split(r"【\s*処\s*分\s*\d+\s*】", text)
    seq = 0
    for block in blocks[1:]:  # First chunk is preamble
        norm = _normalize(block)
        norm_short = norm[:3500]
        # 1 処分内容
        kind_m = re.search(
            r"処\s*分\s*内\s*容\s*\n?\s*(?:懲戒処分\s*[（(])?\s*"
            r"(懲戒免職|諭旨退職|免職|停職[^\n（()）]*|減給[^\n（()）]*|戒告|訓告)",
            norm_short,
        )
        if not kind_m:
            kind_m = re.search(
                r"(懲戒免職|諭旨退職|免職|停職|減給|戒告|訓告)",
                norm_short,
            )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # 2 処分年月日
        date_m = re.search(
            r"処\s*分\s*年\s*月\s*日[^\n令]*?(令和\s*\d+\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
            norm_short,
        )
        if not date_m:
            date_m = WAREKI_RE.search(norm_short)
        if not date_m:
            continue
        raw_date = date_m.group(1) if date_m.lastindex else date_m.group(0)
        date_iso = _parse_date(raw_date)
        if not date_iso:
            continue
        # 3 職名・年齢・性別 (may contain name when 氏名 included)
        # Format A: 教諭・34 歳・男性
        # Format B: 教諭・穴澤 政史・54 歳・男性
        pos_m = re.search(
            r"職\s*名\s*(?:・\s*氏\s*名)?\s*・\s*年\s*齢\s*・\s*性\s*別\s*\n?\s*([^\n]{1,80})",
            norm_short,
        )
        position_raw = _normalize(pos_m.group(1)) if pos_m else "教職員"
        # Strip name (2-4 kanji + space + 2-4 kanji preceded by ・)
        position_clean = re.sub(
            r"・\s*[一-鿿]{1,4}\s+[一-鿿]{1,4}\s*",
            "・",
            position_raw,
        )
        # Extract age/gender from position before stripping
        ag_m = re.search(r"(\d{1,3})\s*歳", position_clean)
        age = (ag_m.group(1) + "歳") if ag_m else None
        g_m = re.search(r"([男女])性?", position_clean)
        gender = g_m.group(1) if g_m else None
        # Strip age + gender from position so role label doesn't duplicate
        position = re.sub(r"・?\s*\d{1,3}\s*歳", "", position_clean)
        position = re.sub(r"・?\s*[男女]性?", "", position)
        position = re.sub(r"・{2,}", "・", position)
        position = position.strip("・ ")
        if not position:
            position = "教職員"
        # 4 地域・校種 or 所属名
        area_m = re.search(
            r"(?:地\s*域\s*・\s*校\s*種|所\s*属\s*名)\s*\n?\s*([^\n]{1,40})",
            norm_short,
        )
        school = _normalize(area_m.group(1)) if area_m else "公立学校"
        # 6 事件・事故の概要 — multi-line, may contain name
        gaiyou_m = re.search(
            r"事\s*件\s*・\s*事\s*故\s*の\s*概\s*要\s*\n+(.+?)"
            r"(?=【\s*処\s*分|\Z)",
            block,
            re.S,
        )
        gaiyou_raw = (
            _normalize(gaiyou_m.group(1))
            if gaiyou_m
            else _normalize(norm_short[kind_m.end() : kind_m.end() + 1500])
        )
        # Strip Japanese name patterns
        gaiyou_clean = re.sub(
            r"(?:[一-鿿]{1,4}\s*[一-鿿]{1,4})\s*(?:は|が|に|を|の)?",
            "[氏名非公表]",
            gaiyou_raw,
            count=2,
        )
        gaiyou = gaiyou_clean[:1200]
        if not gaiyou:
            gaiyou = "詳細は出典PDF参照"
        category = _classify_summary(gaiyou)
        full_reason = (
            f"[{category}] 学校={school} 職位={position} 性別={gender or '不明'} "
            f"年齢={age or '不明'} {kind_text}: {gaiyou}"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(
            "埼玉県教育委員会",
            _make_role_label(f"{school}{position}", gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="埼玉県教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "school": school,
                    "position": position,
                    "gender": gender,
                    "age": age,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 札幌市教育委員会 多数記録 PDF (numbered records with 被処分者/処分内容/事案概要)
# ---------------------------------------------------------------------------


def parse_sapporo_edu_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Sapporo City edu format: numbered records with labeled fields.
    No individual names — just school+role+gender+age range.
        1 被処分者: 札幌市立中学校 教諭 男性 60歳代
          処分内容: 減給1月
          事案概要: ...
    Some PDFs have multi-subject records (被処分者1, 被処分者2).
    """
    out: list[EnfRow] = []
    # Header date — 令和X年(YYYY年)M月D日
    header_text = _normalize(pdf_text)
    collapsed = re.sub(r"\s+", "", header_text[:300])
    header_m = re.search(
        r"令和([0-9元]+)年[（(]?(\d{4})年[)）]?(\d{1,2})月(\d{1,2})日",
        collapsed,
    )
    default_date_iso: str | None = None
    if header_m:
        try:
            year = int(header_m.group(2))
            mo = int(header_m.group(3))
            d = int(header_m.group(4))
            default_date_iso = f"{year:04d}-{mo:02d}-{d:02d}"
        except (ValueError, TypeError):
            default_date_iso = None
    if not default_date_iso:
        # URL fallback: 080327 → R8.3.27 → 2026-03-27
        url_m = re.search(r"/(\d{2})(\d{2})(\d{2})_t", source_url)
        if url_m:
            era_y = int(url_m.group(1))
            mo = int(url_m.group(2))
            d = int(url_m.group(3))
            year = 2018 + era_y
            if 1 <= mo <= 12 and 1 <= d <= 31:
                default_date_iso = f"{year:04d}-{mo:02d}-{d:02d}"
        else:
            url_m = re.search(r"/0(\d{3})_t", source_url)
            if url_m:
                pass  # skip 0423 etc — fallback to body parsing only
    # Strip zero-width + bidi-override chars FIRST (Sapporo PDFs heavily use
    # ZWSP/ZWNJ/ZWJ + LRO/RLO/LRE/RLE/PDF/LRI/RLI/FSI/PDI bidi-override chars)
    cleaned = re.sub(
        r"[​-‏‪-‮⁦-⁩]",
        "",
        pdf_text,
    )
    # Each record block is anchored by 被処分者 followed by school info.
    # Layout variants:
    #   "1\n     被処分者     札幌市立..."  (number alone above)
    #   "2  被処分者      札幌市立..."      (number inline)
    #   "      被処分者      札幌市立..."   (no number, single record)
    # Multi-subject records start with 被処分者1; keep them in same block by
    # not matching 被処分者[1-9]. ALSO require that 被処分者 is followed by
    # school info (not the body "は" / "1と" prose) to avoid mid-sentence false
    # splits in 事案概要 text.
    blocks = re.split(
        r"(?:^|\n)\s*(?:[\d１-９][\s ]*\n?[\s ]*)?被\s*処\s*分\s*者(?![1-9])"
        r"(?=\s*\n?\s*(?:札幌市立|札幌市[一-鿿]+学校|学校))",
        cleaned,
    )
    seq = 0
    for block in blocks[1:]:
        norm = _normalize(block)
        norm_short = norm[:3500]
        # 処分内容
        kind_m = re.search(
            r"処\s*分\s*内\s*容\s*\n?\s*"
            r"(懲戒免職|諭旨退職|免職|停職[^\n、,，。]*|減給[^\n、,，。]*|戒告|訓告)",
            norm_short,
        )
        if not kind_m:
            kind_m = re.search(
                r"(懲戒免職|諭旨退職|免職|停職[^\n、,，。]*|減給[^\n、,，。]*|戒告|訓告)",
                norm_short,
            )
        if not kind_m:
            continue
        kind_text = re.sub(r"\s+", "", kind_m.group(1))
        kind = _classify_kind(kind_text)
        # The block starts with subject info (since 被処分者 was the split anchor).
        # Take first non-empty line.
        first_lines = [ln for ln in norm.split("\n")[:3] if ln.strip()]
        subject_raw = first_lines[0] if first_lines else ""
        subject_full = re.sub(r"\s{2,}", " ", subject_raw).strip()[:120]
        # Extract age (歳代 OR 歳)
        ag_m = re.search(r"(\d{2})\s*歳代?", subject_full)
        age = None
        if ag_m:
            age = ag_m.group(1) + ("歳代" if "歳代" in subject_full else "歳")
        # Extract gender
        g_m = re.search(r"([男女])性?", subject_full)
        gender = g_m.group(1) if g_m else None
        # Clean subject for role label: keep school + role labels, drop names.
        # Strategy: tokenize by spaces, drop any token-pair that looks like a
        # kanji name (姓 + 名), drop age/gender (we already extracted them).
        ROLE_KEYWORDS = (
            "教諭",
            "教頭",
            "校長",
            "副校長",
            "主幹",
            "養護教諭",
            "学校職員",
            "事務職員",
            "業務職員",
            "用務員",
            "栄養教諭",
            "栄養職員",
            "講師",
            "副園長",
            "保育士",
        )
        SCHOOL_KEYWORDS = (
            "小学校",
            "中学校",
            "高校",
            "高等学校",
            "特別支援学校",
            "養護学校",
            "幼稚園",
            "保育所",
            "市立",
            "県立",
        )

        # Strip kanji-name patterns like "渡邊 健次", "佐藤 直哉" — but skip
        # tokens containing role keywords.
        # Bind `ROLE_KEYWORDS` / `SCHOOL_KEYWORDS` via default args so the
        # closure captures THIS iteration's tuples (B023 fix). Each block
        # iteration redefines these locals; without default-arg binding the
        # nested function would late-bind to whichever value the variables
        # held when the function was finally called — a classic Python
        # closure-in-a-loop bug.
        def _is_name_pair(
            s: str,
            _roles: tuple[str, ...] = ROLE_KEYWORDS,
            _schools: tuple[str, ...] = SCHOOL_KEYWORDS,
        ) -> bool:
            # 2-4 kanji + space + 1-3 kanji, not containing role/school words
            if re.fullmatch(r"[一-鿿]{1,4}\s+[一-鿿]{1,4}", s.strip()):
                lower = s
                if any(k in lower for k in _roles + _schools):
                    return False
                return True
            return False

        # Sapporo PDF subjects look like:
        #   "札幌市立中学校 教諭 男性 60歳代"  (no name)
        #   "札幌市立厚別中学校 業務職員(用務員) 渡邊 健次 61歳"  (has name)
        # Strip name spans by token-pair scan.
        tokens = subject_full.split()
        clean_tokens: list[str] = []
        i = 0
        while i < len(tokens):
            if i + 1 < len(tokens):
                pair = tokens[i] + " " + tokens[i + 1]
                if _is_name_pair(pair):
                    i += 2
                    continue
            tok = tokens[i]
            # Drop standalone gender / age tokens (already extracted)
            if re.fullmatch(r"[男女]性?", tok):
                i += 1
                continue
            if re.fullmatch(r"\d{1,3}歳代?", tok):
                i += 1
                continue
            clean_tokens.append(tok)
            i += 1
        subject = " ".join(clean_tokens).strip()
        if not subject:
            subject = "札幌市立学校 職員"
        # 事案概要
        gaiyou_m = re.search(
            r"事\s*案\s*概\s*要\s*\n*(.+?)"
            r"(?=被\s*処\s*分\s*者|\Z|\n\s*[\d１-９]\s*\n)",
            block,
            re.S,
        )
        gaiyou_raw = (
            _normalize(gaiyou_m.group(1))
            if gaiyou_m
            else _normalize(norm_short[kind_m.end() : kind_m.end() + 1200])
        )
        gaiyou = gaiyou_raw[:1200]
        if not gaiyou:
            gaiyou = "詳細は出典PDF参照"
        category = _classify_summary(gaiyou)
        # Date — fall back to default header date
        date_iso = default_date_iso
        if not date_iso:
            date_m = WAREKI_RE.search(norm_short)
            if date_m:
                date_iso = _parse_date(date_m.group(0))
        if not date_iso:
            continue
        full_reason = (f"[{category}] 被処分者={subject} {kind_text}: {gaiyou}")[:1500]
        seq += 1
        target_name = _anonymize_target(
            "札幌市教育委員会",
            _make_role_label(subject, gender, age),
            seq,
        )
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="札幌市教育委員会",
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=CHOUKAI_LAW_TEACHER,
                source_url=source_url,
                org_class=ORG_TEACHER,
                extra={
                    "kind_text": kind_text,
                    "subject": subject,
                    "gender": gender,
                    "age": age,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 名古屋市 表形式 PDF (役職別の3列テーブル)
# ---------------------------------------------------------------------------


def parse_nagoya_table_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """Nagoya City format: 3-column table {所属及び任用段階等 | 処分の内容 | 処分理由}.
    Already anonymous (only role/職層 labels, no individual names).
    """
    out: list[EnfRow] = []
    text = pdf_text
    # Find header date
    norm_full = _normalize(text)
    date_m = WAREKI_RE.search(norm_full[:500])
    if not date_m:
        return out
    date_iso = _parse_date(date_m.group(0))
    if not date_iso:
        return out
    # Find issuing committee (教育委員会 / 市長 / 知事)
    if "教育委員会" in norm_full[:500]:
        authority = "名古屋市教育委員会"
        org_class = ORG_TEACHER
        law = CHOUKAI_LAW_TEACHER
    else:
        authority = "名古屋市長"
        org_class = ORG_CHIHO
        law = CHOUKAI_LAW_CHIHO
    # Each row: position-text whitespace kind whitespace law-citation
    # Parse line-by-line, accumulating multi-line position cells
    lines = text.splitlines()
    rows: list[tuple[str, str]] = []  # (position, kind_text)
    pending_pos: list[str] = []
    KIND_RE = re.compile(
        r"(懲戒免職|諭旨退職|免職|停職[^\n、,，。地]*|減給\s*[\d０-９/分の]+\s*[、,，]?\s*\d+\s*月?|減給[^\n、,，。地]*|戒告|訓告)"
    )
    # Header sentinel: skip everything until table header found, OR until we
    # see a line ending in 教育委員会 (the issuing body, end of preamble).
    header_seen = False
    for raw_line in lines:
        line = _normalize(raw_line)
        if not line:
            continue
        # Detect end of preamble — table header has 「所属及び任用段階等」 or
        # the issuing committee on its own line.
        if "所属及び任用段階等" in line or "処分の内容" in line and "処分理由" in line:
            header_seen = True
            pending_pos = []
            continue
        if not header_seen:
            # Treat lines that contain only an issuing body as header end
            if re.search(r"(教育委員会|市長|市議会|消防局)\s*$", line):
                header_seen = True
            continue
        # Past header — table content lines.
        if "地方公務員法（昭和" in line:
            continue
        if line.startswith("地方公務員法") or line.startswith("国家公務員法"):
            continue
        # Try to find a kind in this line
        k_m = KIND_RE.search(line)
        if k_m:
            # The position is everything before the kind, plus any pending lines
            before = line[: k_m.start()].strip()
            position = " ".join(pending_pos + [before]).strip()
            position = re.sub(r"\s+", " ", position)
            if position and len(position) >= 2 and len(position) <= 80:
                rows.append((position, k_m.group(1).strip()))
            pending_pos = []
        else:
            # Likely position-cell continuation
            stripped = line.strip()
            if (
                stripped
                and "地方公務員法" not in stripped
                and "懲戒処分" not in stripped
                and "懲戒免職" not in stripped
            ):
                pending_pos.append(stripped)
                # cap at 3 lines
                if len(pending_pos) > 3:
                    pending_pos = pending_pos[-3:]
    seq = 0
    for position, kind_text in rows:
        kind_text_clean = re.sub(r"\s+", "", kind_text)
        kind = _classify_kind(kind_text_clean)
        category = _classify_summary(position)  # position has very limited info
        full_reason = (
            f"[{category}] 所属={position} {kind_text_clean}: 地方公務員法第29条第1項各号"
        )[:1500]
        seq += 1
        target_name = _anonymize_target(authority, position, seq)
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority=authority,
                enforcement_kind=kind,
                reason_summary=full_reason,
                related_law_ref=law,
                source_url=source_url,
                org_class=org_class,
                extra={
                    "kind_text": kind_text_clean,
                    "position": position,
                    "category": category,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Source dispatch
# ---------------------------------------------------------------------------

PARSERS = {
    "nagano_edu_list_pdf": parse_nagano_edu_list_pdf,
    "yamanashi_edu_list_pdf": parse_yamanashi_edu_list_pdf,
    "hokkaido_edu_pdf": parse_hokkaido_edu_pdf,
    "yokohama_edu_pdf": parse_yokohama_edu_pdf,
    "meti_quarterly_html": parse_meti_quarterly_html,
    "iwate_quarterly_pdf": parse_iwate_quarterly_pdf,
    "fukushima_list_pdf": parse_fukushima_list_pdf,
    "saitama_edu_singlepdf": parse_saitama_edu_singlepdf,
    "saitama_edu_multipdf": parse_saitama_edu_multipdf,
    "chiba_chiji_html": parse_chiba_chiji_html,
    "kobe_html": parse_kobe_html,
    "chiba_edu_html": parse_chiba_edu_html,
    "kanagawa_edu_html": parse_kanagawa_edu_html,
    "fukuoka_edu_singlepdf": parse_fukuoka_edu_singlepdf,
    "miyagi_edu_pdf": parse_miyagi_edu_pdf,
    "sapporo_edu_pdf": parse_sapporo_edu_pdf,
    "nagoya_table_pdf": parse_nagoya_table_pdf,
}


def fetch_source(http: HttpClient, src: Source) -> list[EnfRow]:
    is_pdf = src.url.lower().endswith(".pdf") or src.parser.endswith("_pdf")
    if is_pdf:
        res = http.get(src.url, max_bytes=PDF_MAX_BYTES)
    else:
        res = http.get(src.url)
    if not res.ok:
        _LOG.warning("[%s] fetch failed status=%s url=%s", src.parser, res.status, src.url)
        return []
    parser = PARSERS.get(src.parser)
    if not parser:
        _LOG.warning("unknown parser %s", src.parser)
        return []
    try:
        if is_pdf:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(res.body)
                tmp_path = f.name
            try:
                proc = subprocess.run(
                    ["pdftotext", "-layout", tmp_path, "-"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                rows = parser(proc.stdout, src.url)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        else:
            rows = parser(res.text, src.url)
    except Exception as exc:
        _LOG.error("[%s] parser failed: %s", src.parser, exc)
        return []
    # Dedup within source by (target_name, date, authority).
    seen: set[tuple[str, str, str]] = set()
    deduped: list[EnfRow] = []
    for r in rows:
        key = (r.target_name, r.issuance_date, r.issuing_authority)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """Return existing dedup tuples for komuin-choukai records.

    All known authorities used by this script: 教育委員会 / 知事 / 大臣 /
    市長.
    """
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT target_name, issuance_date, issuing_authority "
        "FROM am_enforcement_detail "
        "WHERE issuing_authority LIKE '%教育委員会%' "
        "   OR issuing_authority LIKE '%知事%' "
        "   OR issuing_authority LIKE '%大臣%' "
        "   OR issuing_authority LIKE '%市長%' "
    )
    for n, d, a in cur.fetchall():
        if n and d and a:
            out.add((n, d, a))
    return out


def upsert_entity(
    conn: sqlite3.Connection,
    canonical_id: str,
    primary_name: str,
    url: str,
    raw_json: str,
    now_iso: str,
) -> None:
    domain = urlparse(url).netloc or None
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', 'komuin_choukai', NULL,
                  ?, NULL, 0.85, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name      = excluded.primary_name,
            source_url        = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at        = excluded.fetched_at,
            raw_json          = excluded.raw_json,
            updated_at        = datetime('now')
        """,
        (
            canonical_id,
            primary_name[:500],
            url,
            domain,
            now_iso,
            raw_json,
        ),
    )


def insert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    row: EnfRow,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)
        """,
        (
            entity_id,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            row.reason_summary[:4000],
            row.related_law_ref[:1000],
            row.source_url,
            now_iso,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
    limit: int | None = None,
    batch_size: int = 50,
) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0
    chunks: list[list[EnfRow]] = []
    cur_chunk: list[EnfRow] = []
    for r in rows:
        cur_chunk.append(r)
        if len(cur_chunk) >= batch_size:
            chunks.append(cur_chunk)
            cur_chunk = []
    if cur_chunk:
        chunks.append(cur_chunk)
    for chunk_idx, chunk in enumerate(chunks):
        if limit is not None and inserted >= limit:
            break
        try:
            conn.execute("BEGIN IMMEDIATE")
            for idx, r in enumerate(chunk, 1):
                if limit is not None and inserted >= limit:
                    break
                key = (r.target_name, r.issuance_date, r.issuing_authority)
                if key in db_keys:
                    dup_db += 1
                    continue
                if key in batch_keys:
                    dup_batch += 1
                    continue
                batch_keys.add(key)
                seq = _slug8(
                    f"{r.target_name}|{r.issuance_date}|{r.issuing_authority}|{chunk_idx}|{idx}"
                )
                canonical_id = f"AM-ENF-KOMU-{r.issuance_date.replace('-', '')}-{seq}"
                primary_name = f"{r.target_name} ({r.issuance_date}) - {r.issuing_authority}"
                raw_json = json.dumps(
                    {
                        "target_name": r.target_name,
                        "issuance_date": r.issuance_date,
                        "issuing_authority": r.issuing_authority,
                        "enforcement_kind": r.enforcement_kind,
                        "related_law_ref": r.related_law_ref,
                        "reason_summary": r.reason_summary,
                        "source_url": r.source_url,
                        "org_class": r.org_class,
                        "extra": r.extra or {},
                        "source_attribution": r.issuing_authority,
                        "anonymized": True,
                        "license": ("国家・地方公務員 懲戒処分 公表資料（出典明記で転載引用可）"),
                    },
                    ensure_ascii=False,
                )
                try:
                    upsert_entity(
                        conn,
                        canonical_id,
                        primary_name,
                        r.source_url,
                        raw_json,
                        now_iso,
                    )
                    insert_enforcement(conn, canonical_id, r, now_iso)
                    inserted += 1
                except sqlite3.Error as exc:
                    _LOG.error(
                        "DB error name=%r date=%s: %s",
                        r.target_name,
                        r.issuance_date,
                        exc,
                    )
                    continue
            conn.commit()
        except sqlite3.Error as exc:
            _LOG.error("BEGIN/commit failed chunk=%d: %s", chunk_idx, exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--source-filter",
        type=str,
        default=None,
        help="Only run sources whose parser name matches this substring (debug)",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    all_rows: list[EnfRow] = []
    per_source_count: dict[str, int] = {}
    for src in SOURCES:
        if args.source_filter and args.source_filter not in src.parser:
            continue
        rows = fetch_source(http, src)
        per_source_count[f"{src.locale}/{src.parser}/{src.note}"] = len(rows)
        _LOG.info(
            "[%s] %s (%s): %d rows",
            src.locale,
            src.parser,
            src.note,
            len(rows),
        )
        all_rows.extend(rows)

    _LOG.info("total parsed rows=%d (sources=%d)", len(all_rows), len(SOURCES))

    if args.dry_run:
        for r in all_rows[:30]:
            _LOG.info(
                "sample: name=%r date=%s auth=%s kind=%s law=%s class=%s",
                r.target_name,
                r.issuance_date,
                r.issuing_authority,
                r.enforcement_kind,
                r.related_law_ref,
                r.org_class,
            )
        http.close()
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        http.close()
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_tables(conn)

    inserted, dup_db, dup_batch = write_rows(
        conn,
        all_rows,
        now_iso=now_iso,
        limit=args.limit,
    )
    # Per-org / per-authority breakdown for caller
    org_counts: dict[str, int] = {}
    auth_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    for r in all_rows:
        org_counts[r.org_class] = org_counts.get(r.org_class, 0) + 1
        auth_counts[r.issuing_authority] = auth_counts.get(r.issuing_authority, 0) + 1
        kind_counts[r.enforcement_kind] = kind_counts.get(r.enforcement_kind, 0) + 1
    try:
        conn.close()
    except sqlite3.Error:
        pass
    http.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(all_rows),
        inserted,
        dup_db,
        dup_batch,
    )
    print(
        f"Komuin Choukai ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    print("breakdown by source:")
    for k in sorted(per_source_count.keys()):
        print(f"  {k}: parsed={per_source_count[k]}")
    print(f"breakdown by org_class: {json.dumps(org_counts, ensure_ascii=False)}")
    print(f"breakdown by issuing_authority: {json.dumps(auth_counts, ensure_ascii=False)}")
    print(f"breakdown by enforcement_kind: {json.dumps(kind_counts, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
