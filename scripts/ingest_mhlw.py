#!/usr/bin/env python3
"""ingest_mhlw.py — 厚生労働省 (MHLW) 雇用関係助成金等を jpintel.db へ取り込む。

Source: https://www.mhlw.go.jp/  (一次資料のみ)
        + 雇用関係助成金: https://www.mhlw.go.jp/general/sosiki/roudou/koyou-kankei-jyoseikin/
        + 助成金検索ツール: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/

License: 政府標準利用規約 (gov_standard) — © Ministry of Health, Labour and Welfare.
         出典明示で再配布可。

Recon (2026-04-29):
  * MHLW 雇用関係助成金は 22 区分 (取組内容/対象者) × 約 30 個別制度 = 累計 50+ programs。
  * 既存 jpintel.db に 109 件 (mhlw 関連) 記録済 — duplicate 注意。
  * 主要制度 (Tier S/A 候補):
      - 雇用調整助成金 (継続)
      - キャリアアップ助成金 (正社員化コース等 7 コース)
      - 人材確保等支援助成金 (10 コース)
      - 人材開発支援助成金 (人材育成支援コース等 7 コース)
      - 業務改善助成金 (賃金引上げ + 設備投資)
      - 両立支援等助成金 (出生時両立支援等 5 コース)
      - トライアル雇用助成金
      - 特定求職者雇用開発助成金 (特定就職困難者・成長分野等 5 コース)
      - 65 歳超雇用推進助成金
      - 産業雇用安定助成金
      - 早期再就職支援等助成金
  * RSS: なし。/list_news.html 構造のみ。
  * 件数推定: curated 50-70 件 (主要制度 × 各コース)。

Strategy:
  * Curated seed list (制度コード + 公式 PDF/HTML URL)。
  * 各制度ページを 1 req/s で probe → meta description + 上限額抽出。
  * 上限額は seed で個別指定 (MHLW PDF 構造が複雑で正規表現抽出は不安定)。
  * Tier:
      S = 200 OK + 制度継続 + 上限額 + targets 全埋まり
      A = 200 OK + 上限額 or targets
      B = 200 OK のみ
      X = 廃止 / 終了 (excluded=1)
  * 冪等: source_checksum 一致なら skip。

Constraints:
  * NO Anthropic API. urllib + bs4. Rate-limit 1 req/s.
  * BEGIN IMMEDIATE + busy_timeout=300_000.
  * Aggregator 禁止: source_url は mhlw.go.jp 限定。

Run:
  .venv/bin/python scripts/ingest_mhlw.py
  .venv/bin/python scripts/ingest_mhlw.py --dry-run
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

try:
    import certifi  # type: ignore[import-untyped]

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "jpintel.db"

UA = "AutonoMath/0.1.0 (+https://bookyou.net)"
RATE_DELAY = 1.0
HTTP_TIMEOUT = 30

LICENSE_ATTR = "© 厚生労働省 (Ministry of Health, Labour and Welfare) / 政府標準利用規約 2.0 — 出典明示で再配布可"


@dataclasses.dataclass(frozen=True)
class MhlwSeed:
    slug: str
    name: str
    source_url: str
    program_kind: str  # 'subsidy' | 'grant' | 'loan'
    tier_hint: str
    description: str
    authority_name: str
    max_man_yen: float | None = None
    target_types: tuple[str, ...] = ("corporation",)
    funding_purpose: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


SEEDS: tuple[MhlwSeed, ...] = (
    # ---- 雇用調整 / 雇用維持 ----
    MhlwSeed(
        slug="mhlw-koyou-chousei-jyoseikin",
        name="雇用調整助成金",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/pageL07.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "経済上の理由により事業活動の縮小を余儀なくされた事業主が、"
            "従業員の雇用維持のため一時休業・教育訓練・出向を行う場合に、"
            "休業手当等の一部を助成する制度。"
        ),
        authority_name="厚生労働省 職業安定局",
        target_types=("corporation",),
        funding_purpose=("雇用維持", "休業手当"),
        aliases=("雇調金",),
    ),
    MhlwSeed(
        slug="mhlw-sangyo-koyou-antei-jyoseikin",
        name="産業雇用安定助成金",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/sangyokoyouantei.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "新型コロナの影響を受ける中、雇用維持のために在籍型出向に取り組む"
            "事業主への助成 (出向元・出向先双方が対象)。"
        ),
        authority_name="厚生労働省 職業安定局",
        target_types=("corporation",),
        funding_purpose=("出向", "雇用維持"),
    ),
    # ---- キャリアアップ助成金 ----
    MhlwSeed(
        slug="mhlw-career-up-seishain",
        name="キャリアアップ助成金 正社員化コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000118457_00007.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "有期雇用労働者・派遣労働者・短時間労働者を正規雇用労働者に転換した"
            "事業主に対する助成。1 人当たり最大 80 万円。"
        ),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=80.0,
        target_types=("corporation",),
        funding_purpose=("正社員化", "非正規雇用転換"),
    ),
    MhlwSeed(
        slug="mhlw-career-up-shogu-kaizen",
        name="キャリアアップ助成金 賃金規定等改定コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000118457_00007.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "有期雇用労働者等の基本給賃金規定等を増額改定し、増額後の賃金を"
            "支払った事業主に対する助成。"
        ),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=72.0,
        target_types=("corporation",),
        funding_purpose=("賃上げ", "非正規待遇改善"),
    ),
    MhlwSeed(
        slug="mhlw-career-up-tannjikan-roudou-jikan-encho",
        name="キャリアアップ助成金 短時間労働者労働時間延長コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000118457_00007.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "短時間労働者の所定労働時間を週 5 時間以上延長し、新たに社会保険を"
            "適用した事業主に対する助成。"
        ),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=22.5,
        target_types=("corporation",),
        funding_purpose=("社会保険加入", "労働時間延長"),
    ),
    # ---- 人材確保等支援助成金 ----
    MhlwSeed(
        slug="mhlw-jinzai-kakuho-koyo-kanri-seido",
        name="人材確保等支援助成金 雇用管理制度助成コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/jinzaikakuho.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "雇用管理制度 (評価・処遇制度、研修制度、健康づくり制度、メンター制度、短時間"
            "正社員制度) の導入により、離職率の低下に取り組む事業主への助成。"
        ),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=72.0,
        target_types=("corporation",),
        funding_purpose=("雇用管理改善", "離職率低下"),
    ),
    MhlwSeed(
        slug="mhlw-jinzai-kakuho-gaikokujin-roudousha-shuurou",
        name="人材確保等支援助成金 外国人労働者就労環境整備助成コース",
        source_url="https://www.mhlw.go.jp/content/11600000/001239692.pdf",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "外国人特有の事情に配慮した就労環境整備に取り組む事業主に対する助成。"
            "通訳・翻訳機器導入、就業規則等多言語化、社内研修等。"
        ),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=72.0,
        target_types=("corporation",),
        funding_purpose=("外国人雇用", "就労環境整備"),
    ),
    # ---- 人材開発支援助成金 ----
    MhlwSeed(
        slug="mhlw-jinzai-kaihatsu",
        name="人材開発支援助成金",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "従業員の職業訓練 (OFF-JT, OJT, e-Learning) を実施した事業主への助成。"
            "人材育成支援コース・教育訓練休暇等付与コース・人への投資促進コース等。"
        ),
        authority_name="厚生労働省 人材開発統括官",
        max_man_yen=1000.0,
        target_types=("corporation",),
        funding_purpose=("人材育成", "職業訓練"),
    ),
    # ---- 業務改善助成金 ----
    MhlwSeed(
        slug="mhlw-gyoumu-kaizen",
        name="業務改善助成金",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/zigyonushi/shienjigyou/03.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "中小企業・小規模事業者が事業場内最低賃金を引き上げ、生産性向上のための"
            "設備投資 (機械装置・コンサルティング・人材育成等) を行う場合に費用を助成。"
        ),
        authority_name="厚生労働省 労働基準局",
        max_man_yen=600.0,
        target_types=("corporation", "sole_proprietor"),
        funding_purpose=("最低賃金引上げ", "設備投資", "生産性向上"),
    ),
    # ---- 両立支援等助成金 ----
    MhlwSeed(
        slug="mhlw-ryouritsu-shussei-ryouritsu",
        name="両立支援等助成金 出生時両立支援コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
        program_kind="subsidy",
        tier_hint="B",
        description=("男性労働者の育児休業取得等に取り組む事業主に対する助成。"),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=60.0,
        target_types=("corporation",),
        funding_purpose=("男性育休", "両立支援"),
    ),
    MhlwSeed(
        slug="mhlw-ryouritsu-ikuji-kaigo-shokuba-fukki",
        name="両立支援等助成金 育児休業等支援コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
        program_kind="subsidy",
        tier_hint="B",
        description=("育児休業取得時・職場復帰時・代替要員確保時等の取組に応じて助成。"),
        authority_name="厚生労働省 雇用環境・均等局",
        max_man_yen=72.0,
        target_types=("corporation",),
        funding_purpose=("育児休業", "職場復帰"),
    ),
    # ---- トライアル雇用 ----
    MhlwSeed(
        slug="mhlw-trial-koyou",
        name="トライアル雇用助成金 一般トライアルコース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/trial_koyou.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "職業経験不足等による就職困難者を、ハローワーク等の紹介により"
            "原則 3 か月間の試行雇用を実施する事業主に対する助成 (月 4 万円)。"
        ),
        authority_name="厚生労働省 職業安定局",
        max_man_yen=12.0,
        target_types=("corporation",),
        funding_purpose=("トライアル雇用", "就職困難者支援"),
    ),
    # ---- 特定求職者雇用開発助成金 ----
    MhlwSeed(
        slug="mhlw-tokutei-kyushokusha-shuurou-konnan",
        name="特定求職者雇用開発助成金 特定就職困難者コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/tokutei_konnan.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "高年齢者・障害者・母子家庭の母等の就職困難者をハローワーク等の紹介により"
            "継続雇用する事業主に対する賃金助成 (1 人当たり最大 240 万円)。"
        ),
        authority_name="厚生労働省 職業安定局",
        max_man_yen=240.0,
        target_types=("corporation",),
        funding_purpose=("障害者雇用", "高齢者雇用", "母子家庭支援"),
    ),
    MhlwSeed(
        slug="mhlw-tokutei-seichou-bunya",
        name="特定求職者雇用開発助成金 成長分野等人材確保・育成コース",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/tokutei_konnan.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "デジタル・グリーン・コア人材分野の事業主が、ハローワーク等の紹介により"
            "未経験者を継続雇用し、人材育成を行う場合の助成 (賃金 + 研修費)。"
        ),
        authority_name="厚生労働省 職業安定局",
        max_man_yen=170.0,
        target_types=("corporation",),
        funding_purpose=("成長分野雇用", "DX人材", "GX人材"),
    ),
    # ---- 65 歳超雇用推進 ----
    MhlwSeed(
        slug="mhlw-65sai-koyou-suishin",
        name="65歳超雇用推進助成金",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/65koyou.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "65 歳以上への定年引上げ・継続雇用制度の導入・無期雇用転換等の措置を"
            "講じた事業主に対する助成。65 歳超継続雇用促進コース等 3 コース。"
        ),
        authority_name="厚生労働省 職業安定局",
        max_man_yen=160.0,
        target_types=("corporation",),
        funding_purpose=("高齢者雇用", "定年延長"),
    ),
    # ---- 早期再就職支援等 ----
    MhlwSeed(
        slug="mhlw-souki-saishuushoku",
        name="早期再就職支援等助成金 (旧 労働移動支援)",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "事業規模縮小等で離職を余儀なくされる労働者の早期再就職を支援する"
            "事業主に対する助成。再就職援助計画対象者 1 人につき助成。"
        ),
        authority_name="厚生労働省 職業安定局",
        max_man_yen=70.0,
        target_types=("corporation",),
        funding_purpose=("再就職支援", "労働移動"),
    ),
    # ---- 高年齢雇用継続給付 (個人受給だが事業主側の支給代行が一般的) ----
    MhlwSeed(
        slug="mhlw-konenrei-koyou-keizoku-kyufu",
        name="高年齢雇用継続給付金",
        source_url="https://www.mhlw.go.jp/content/001520023.pdf",
        program_kind="benefit",
        tier_hint="A",
        description=(
            "60 歳以後の賃金が 60 歳到達時の 75% 未満となった場合に、雇用保険から"
            "支給される給付。雇用継続給付の一種。"
        ),
        authority_name="厚生労働省 職業安定局 雇用保険課",
        target_types=("individual",),
        funding_purpose=("高齢者雇用継続",),
    ),
    # ---- 障害者雇用 ----
    MhlwSeed(
        slug="mhlw-shougaisha-sagyou-shisetsu",
        name="障害者作業施設設置等助成金",
        source_url="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/shougaishakoyou/jigyounushi/index.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "障害者の雇用に当たって、その障害特性に応じた作業施設・設備を設置・"
            "整備する事業主に対する助成 (最大 450 万円)。"
        ),
        authority_name="厚生労働省 職業安定局 障害者雇用対策課",
        max_man_yen=450.0,
        target_types=("corporation",),
        funding_purpose=("障害者雇用", "施設整備"),
    ),
)


# ---------------------------------------------------------------------------
# HTTP fetch + meta parse
# ---------------------------------------------------------------------------


def fetch(url: str, *, retries: int = 2) -> tuple[int, str]:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
                raw = resp.read()
                # PDF responses: skip text decode, return placeholder
                ctype = resp.headers.get_content_type() or ""
                if "pdf" in ctype.lower():
                    return resp.status, ""
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except LookupError:
                    text = raw.decode("utf-8", errors="replace")
                return resp.status, text
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (404, 410):
                return exc.code, ""
            time.sleep(2.0 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
    print(f"  [WARN] fetch failed: {url}: {last_err}", file=sys.stderr)
    return 0, ""


def parse_meta(html: str) -> tuple[str | None, str | None]:
    if not html:
        return None, None
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        desc = re.sub(r"\s+", " ", str(md["content"]).strip())
    return title, desc


def make_unified_id(slug: str) -> str:
    h = hashlib.sha1(f"mhlw:{slug}".encode("utf-8")).hexdigest()[:10]
    return f"UNI-{h}"


def classify(seed: MhlwSeed, http_status: int) -> tuple[str, int, str | None]:
    if http_status not in (200, 0):
        return "X", 1, "dead_source_url"
    if http_status == 0:
        return "C", 0, None
    has_amount = seed.max_man_yen is not None
    has_targets = bool(seed.target_types)
    if seed.tier_hint == "A" and has_amount and has_targets:
        return "A", 0, None
    if seed.tier_hint in ("S", "A") and (has_amount or has_targets):
        return "A", 0, None
    return seed.tier_hint, 0, None


def build_row(
    seed: MhlwSeed, http_status: int, meta: tuple[str | None, str | None], fetched_at: str
) -> dict[str, object]:
    tier, excluded, excl_reason = classify(seed, http_status)
    enriched = {
        "_meta": {
            "program_id": make_unified_id(seed.slug),
            "program_name": seed.name,
            "source_format": "html_or_pdf",
            "source_urls": [seed.source_url],
            "fetched_at": fetched_at,
            "model": "mhlw-seed-curated-v1",
            "worker_id": "ingest_mhlw",
            "primary_source_confirmed": http_status == 200,
            "http_status": http_status,
            "fetched_title": meta[0],
            "fetched_meta_description": meta[1],
        },
        "extraction": {
            "basic": {
                "正式名称": seed.name,
                "_source_ref": {"url": seed.source_url, "excerpt": meta[0] or ""},
            },
            "money": {
                "amount_max_man_yen": seed.max_man_yen,
                "_source_ref": {"url": seed.source_url, "excerpt": ""},
            },
        },
        "license_attribution": LICENSE_ATTR,
    }

    return {
        "unified_id": make_unified_id(seed.slug),
        "primary_name": seed.name,
        "aliases_json": json.dumps(list(seed.aliases), ensure_ascii=False)
        if seed.aliases
        else None,
        "authority_level": "national",
        "authority_name": seed.authority_name,
        "prefecture": None,
        "municipality": None,
        "program_kind": seed.program_kind,
        "official_url": seed.source_url,
        "amount_max_man_yen": seed.max_man_yen,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "1",
        "tier": tier,
        "coverage_score": None,
        "gap_to_tier_s_json": None,
        "a_to_j_coverage_json": None,
        "excluded": excluded,
        "exclusion_reason": excl_reason,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": json.dumps(list(seed.target_types), ensure_ascii=False)
        if seed.target_types
        else None,
        "funding_purpose_json": json.dumps(list(seed.funding_purpose), ensure_ascii=False)
        if seed.funding_purpose
        else None,
        "amount_band": None,
        "application_window_json": None,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"mhlw_seed": seed.slug}, ensure_ascii=False),
        "source_url": seed.source_url,
        "source_fetched_at": fetched_at,
        "source_checksum": hashlib.sha1(
            f"{seed.slug}|{seed.source_url}|{seed.name}|{seed.max_man_yen}|{','.join(seed.target_types)}".encode(
                "utf-8"
            )
        ).hexdigest()[:16],
        "updated_at": fetched_at,
    }


UPSERT_SQL = """
INSERT INTO programs (
    unified_id, primary_name, aliases_json, authority_level, authority_name,
    prefecture, municipality, program_kind, official_url,
    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
    excluded, exclusion_reason,
    crop_categories_json, equipment_category,
    target_types_json, funding_purpose_json, amount_band, application_window_json,
    enriched_json, source_mentions_json,
    source_url, source_fetched_at, source_checksum, updated_at
) VALUES (
    :unified_id, :primary_name, :aliases_json, :authority_level, :authority_name,
    :prefecture, :municipality, :program_kind, :official_url,
    :amount_max_man_yen, :amount_min_man_yen, :subsidy_rate,
    :trust_level, :tier, :coverage_score, :gap_to_tier_s_json, :a_to_j_coverage_json,
    :excluded, :exclusion_reason,
    :crop_categories_json, :equipment_category,
    :target_types_json, :funding_purpose_json, :amount_band, :application_window_json,
    :enriched_json, :source_mentions_json,
    :source_url, :source_fetched_at, :source_checksum, :updated_at
)
ON CONFLICT(unified_id) DO UPDATE SET
    primary_name = excluded.primary_name,
    authority_name = COALESCE(excluded.authority_name, programs.authority_name),
    program_kind = COALESCE(excluded.program_kind, programs.program_kind),
    official_url = COALESCE(excluded.official_url, programs.official_url),
    amount_max_man_yen = COALESCE(excluded.amount_max_man_yen, programs.amount_max_man_yen),
    target_types_json = COALESCE(excluded.target_types_json, programs.target_types_json),
    funding_purpose_json = COALESCE(excluded.funding_purpose_json, programs.funding_purpose_json),
    enriched_json = excluded.enriched_json,
    source_url = excluded.source_url,
    source_fetched_at = excluded.source_fetched_at,
    source_checksum = excluded.source_checksum,
    tier = CASE
        WHEN programs.tier IS NULL OR programs.tier IN ('X','C') THEN excluded.tier
        ELSE programs.tier
    END,
    excluded = excluded.excluded,
    exclusion_reason = excluded.exclusion_reason,
    updated_at = excluded.updated_at
WHERE programs.source_checksum IS NULL OR programs.source_checksum != excluded.source_checksum
"""

FTS_INSERT_SQL = (
    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)"
)


def upsert(conn: sqlite3.Connection, row: dict[str, object]) -> str:
    prev = conn.execute(
        "SELECT source_checksum FROM programs WHERE unified_id = ?", (row["unified_id"],)
    ).fetchone()
    if prev is None:
        action = "insert"
    elif prev[0] == row["source_checksum"]:
        return "skip"
    else:
        action = "update"
    conn.execute(UPSERT_SQL, row)
    if action == "insert":
        conn.execute(
            FTS_INSERT_SQL,
            (
                row["unified_id"],
                row["primary_name"],
                row["aliases_json"] or "",
                row["primary_name"],
            ),
        )
    return action


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"jpintel.db: {DB_PATH}")
    if not args.dry_run and not DB_PATH.exists():
        print(f"[ERROR] DB not found", file=sys.stderr)
        return 2

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    unique_urls = sorted({s.source_url for s in SEEDS})
    print(f"Probing {len(unique_urls)} unique MHLW URLs at 1 req/s ...")
    fetched: dict[str, tuple[int, tuple[str | None, str | None]]] = {}
    for i, url in enumerate(unique_urls, 1):
        status, html = fetch(url)
        meta = parse_meta(html) if status == 200 and html else (None, None)
        fetched[url] = (status, meta)
        ok = "OK" if status == 200 else f"HTTP {status}"
        print(f"  [{i:02d}/{len(unique_urls)}] {ok}  {url}")
        time.sleep(RATE_DELAY)

    for seed in SEEDS:
        status, meta = fetched.get(seed.source_url, (0, (None, None)))
        rows.append(build_row(seed, status, meta, fetched_at))

    if args.dry_run:
        dist = {}
        for r in rows:
            dist[r["tier"]] = dist.get(r["tier"], 0) + 1
        print(f"\nDRY RUN tier dist: {dist}")
        return 0

    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("BEGIN IMMEDIATE")
        ins = upd = skip = 0
        for r in rows:
            try:
                action = upsert(conn, r)
            except sqlite3.IntegrityError as exc:
                print(f"  [WARN] integrity: {r['unified_id']} {exc}", file=sys.stderr)
                skip += 1
                continue
            if action == "insert":
                ins += 1
            elif action == "update":
                upd += 1
            else:
                skip += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    print(f"\nDone: insert={ins} update={upd} skip={skip} (seeds={len(SEEDS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
