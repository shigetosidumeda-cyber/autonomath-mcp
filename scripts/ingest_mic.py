#!/usr/bin/env python3
"""ingest_mic.py — 総務省 (MIC) 補助金・交付金 制度を jpintel.db へ取り込む。

Source: https://www.soumu.go.jp/  (一次資料のみ)
        + 自治財政局      https://www.soumu.go.jp/main_sosiki/jichi_zeisei/
        + 情報流通行政局  https://www.soumu.go.jp/menu_seisaku/ictseisaku/
        + 自治行政局      https://www.soumu.go.jp/main_sosiki/jichi_gyousei/

License: 政府標準利用規約 (gov_standard) — © 2009 Ministry of Internal Affairs
         and Communications. 出典明示で再配布可。

Recon (2026-04-29):
  * MIC は MAFF と異なり「公募一覧」が単一ページに集約されていない。
  * 主要制度は curated seed 方式が現実的:
      - 普通交付税 / 特別交付税 (制度として常時)
      - 過疎対策事業債 / 緊急防災・減災事業債 / 公共施設等適正管理推進事業債
      - 地方創生臨時交付金 (年度更新)
      - 5G/Beyond 5G/IoT/地域DX 推進補助
      - ふるさとテレワーク, スマートシティ
  * RSS: https://www.soumu.go.jp/menu_kyotsuu/important/index.html (RSS 配信)
  * 件数推定: curated 30-40 + 各局 公募 PDF からの追加 ≈ 60-80 programs

Strategy:
  * Curated seed (national 系制度) を中心に、各局の公募ページから補完。
  * 各 source_url を 1 req/s で probe → HTTP 200 / meta description 取得。
  * Tier:
      S = curated seed + amount + target_types + window 全埋まり
      A = curated seed + 2 軸埋まり
      B = curated seed + 1 軸 (常時制度の交付税等)
      X = HTTP 失敗 / 廃止制度 (excluded=1)
  * 冪等: source_checksum (sha1(url|name|amount|targets)) 一致なら skip。

Constraints:
  * NO Anthropic API. urllib + bs4. Rate-limit 1 req/s.
  * BEGIN IMMEDIATE + busy_timeout=300_000.
  * Aggregator 禁止: source_url は soumu.go.jp 限定。

Run:
  .venv/bin/python scripts/ingest_mic.py
  .venv/bin/python scripts/ingest_mic.py --dry-run
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

LICENSE_ATTR = "© 総務省 (Ministry of Internal Affairs and Communications) / 政府標準利用規約 2.0 — 出典明示で再配布可"


# ---------------------------------------------------------------------------
# Curated seed (主要 MIC 制度)
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class MicSeed:
    slug: str
    name: str
    source_url: str
    program_kind: str
    tier_hint: str
    description: str
    authority_name: str
    max_man_yen: float | None = None
    target_types: tuple[str, ...] = ("municipality", "prefecture")
    funding_purpose: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


SEEDS: tuple[MicSeed, ...] = (
    # ---- 自治財政局: 地方財政制度 ----
    MicSeed(
        slug="mic-futsu-koufuzei",
        name="普通交付税",
        source_url="https://www.soumu.go.jp/main_sosiki/c-zaisei/koufuzei.html",
        program_kind="grant",
        tier_hint="B",
        description=(
            "地方公共団体間の財源不均衡を調整し、すべての地方団体が一定の行政"
            "サービスを提供できるよう財源を保障する制度。基準財政需要額と"
            "基準財政収入額の差額を交付。"
        ),
        authority_name="総務省 自治財政局",
        funding_purpose=("地方財政調整", "財源保障"),
        aliases=("地方交付税",),
    ),
    MicSeed(
        slug="mic-tokubetsu-koufuzei",
        name="特別交付税",
        source_url="https://www.soumu.go.jp/main_sosiki/c-zaisei/koufuzei.html",
        program_kind="grant",
        tier_hint="B",
        description=(
            "災害・特別な事情により普通交付税では捕捉されない財政需要に"
            "対して交付される交付税。年 2 回 (12 月・3 月) 配分。"
        ),
        authority_name="総務省 自治財政局",
        funding_purpose=("災害対策", "特別財政需要"),
    ),
    MicSeed(
        slug="mic-kasou-saimu",
        name="過疎対策事業債",
        source_url="https://www.soumu.go.jp/main_sosiki/jichi_gyousei/c-gyousei/2001/kaso/kasomain0.htm",
        program_kind="local_bond",
        tier_hint="A",
        description=(
            "過疎地域の自立促進のため、過疎地域の市町村が実施する事業に"
            "充当できる地方債。元利償還金の 70% が普通交付税の基準財政"
            "需要額に算入。"
        ),
        authority_name="総務省 自治行政局 過疎対策室",
        funding_purpose=("過疎対策", "地域振興"),
        aliases=("過疎債",),
    ),
    MicSeed(
        slug="mic-kinkyu-bousai-saimu",
        name="緊急防災・減災事業債",
        source_url="https://www.soumu.go.jp/main_sosiki/c-zaisei/index.html",
        program_kind="local_bond",
        tier_hint="A",
        description=(
            "地方公共団体が実施する防災・減災対策事業 (耐震化・避難所・"
            "防災行政無線等) に充当できる地方債。元利償還金の 70% が"
            "普通交付税の基準財政需要額に算入。"
        ),
        authority_name="総務省 自治財政局",
        funding_purpose=("防災", "減災", "公共施設整備"),
    ),
    MicSeed(
        slug="mic-koukyo-tekisei-kanri-saimu",
        name="公共施設等適正管理推進事業債",
        source_url="https://www.soumu.go.jp/main_sosiki/c-zaisei/index.html",
        program_kind="local_bond",
        tier_hint="A",
        description=(
            "公共施設等の集約化・複合化・転用・長寿命化等を推進する地方公共団体"
            "の事業に充当できる地方債。元利償還金の一部が交付税措置。"
        ),
        authority_name="総務省 自治財政局",
        funding_purpose=("公共施設管理", "施設集約", "長寿命化"),
    ),
    # ---- 自治行政局: 地域振興 ----
    MicSeed(
        slug="mic-tokutei-chiiki-dukuri",
        name="特定地域づくり事業協同組合制度",
        source_url="https://www.soumu.go.jp/main_sosiki/jichi_gyousei/c-gyousei/tokutei_chiiki-dukuri-jigyou.html",
        program_kind="local_support_program",
        tier_hint="B",
        description=(
            "人口急減地域における事業協同組合の設立・運営を支援し、"
            "地域社会の維持に必要な事業の継続を図る制度。"
        ),
        authority_name="総務省 自治行政局 地域力創造グループ",
        target_types=("cooperative", "municipality"),
        funding_purpose=("地域振興", "人材確保"),
    ),
    MicSeed(
        slug="mic-furusato-workingholiday",
        name="ふるさとワーキングホリデー",
        source_url="https://www.soumu.go.jp/main_sosiki/jichi_gyousei/c-gyousei/02gyosei08_03000076.html",
        program_kind="local_support_program",
        tier_hint="C",
        description=(
            "都市部の若者等が地方で一定期間働きながら地域住民との交流・"
            "学びを通じて地域の魅力を体感する取組を支援。"
        ),
        authority_name="総務省 自治行政局 地域自立応援課",
        funding_purpose=("地方創生", "関係人口創出"),
    ),
    # ---- 情報流通行政局 / 総合通信基盤局: ICT 補助 ----
    MicSeed(
        slug="mic-ict-chiiki-souzou",
        name="ICT地域活性化大賞 / ICT活用推進地域創造事業",
        source_url="https://www.soumu.go.jp/menu_seisaku/ictseisaku/ict_town/index.html",
        program_kind="subsidy",
        tier_hint="B",
        description=(
            "ICT を活用した地域活性化の優良事例を表彰し、"
            "地域における ICT 利活用の促進を図る事業。"
        ),
        authority_name="総務省 情報流通行政局",
        target_types=("municipality", "prefecture", "private_organization"),
        funding_purpose=("ICT活用", "地域活性化"),
    ),
    MicSeed(
        slug="mic-beyond-5g",
        name="Beyond 5G (6G) 研究開発支援事業",
        source_url="https://www.soumu.go.jp/menu_seisaku/ictseisaku/B5G_sokushin/index.html",
        program_kind="rd_grant",
        tier_hint="A",
        description=(
            "Beyond 5G (6G) の実現に向けて、研究開発・国際標準化・知財戦略・"
            "実証・社会実装を一体的に進める NICT 委託・補助事業。"
        ),
        authority_name="総務省 国際戦略局 / NICT",
        max_man_yen=1000000.0,  # 大型 R&D 公募 (案件単位)
        target_types=("corporation", "research_institute"),
        funding_purpose=("研究開発", "5G", "Beyond 5G", "国際標準化"),
    ),
    MicSeed(
        slug="mic-chiho-keizai-junkan-soujou",
        name="地域経済循環創造事業交付金",
        source_url="https://www.soumu.go.jp/main_sosiki/joho_tsusin/SME_support/index.html",
        program_kind="grant",
        tier_hint="A",
        description=(
            "地域の資源と地域の資金を活用して雇用の創出を行う事業を支援。"
            "産学金官の連携による事業化計画を市町村が策定し国が支援。"
        ),
        authority_name="総務省 地域力創造グループ",
        max_man_yen=5000.0,
        target_types=("corporation", "municipality"),
        funding_purpose=("雇用創出", "地域資源活用"),
    ),
    MicSeed(
        slug="mic-iot-jouhou-tsushin",
        name="IoT サービス創出支援事業",
        source_url="https://www.soumu.go.jp/menu_seisaku/ictseisaku/index.html",
        program_kind="rd_grant",
        tier_hint="B",
        description=(
            "IoT を活用した新サービスの創出・実証・社会実装を支援する補助事業。"
        ),
        authority_name="総務省 情報流通行政局",
        target_types=("corporation",),
        funding_purpose=("IoT", "新サービス開発"),
    ),
    MicSeed(
        slug="mic-smartcity",
        name="データ連携型スマートシティ推進事業",
        source_url="https://www.soumu.go.jp/menu_seisaku/ictseisaku/index.html",
        program_kind="grant",
        tier_hint="B",
        description=(
            "スマートシティリファレンスアーキテクチャに基づくデータ連携基盤の"
            "構築と分野横断的サービス展開を支援。"
        ),
        authority_name="総務省 情報流通行政局",
        target_types=("municipality", "corporation"),
        funding_purpose=("スマートシティ", "データ連携"),
    ),
    MicSeed(
        slug="mic-furusato-telework",
        name="ふるさとテレワーク推進事業",
        source_url="https://www.soumu.go.jp/menu_seisaku/ictseisaku/index.html",
        program_kind="grant",
        tier_hint="C",
        description=(
            "都市部から地方への人や仕事の流れをつくるため、地方公共団体や"
            "民間事業者によるサテライトオフィス整備等を支援。"
        ),
        authority_name="総務省 情報流通行政局",
        target_types=("municipality", "corporation"),
        funding_purpose=("テレワーク", "サテライトオフィス"),
    ),
    MicSeed(
        slug="mic-shouboudan-shien",
        name="消防団等充実強化アドバイザー派遣事業",
        source_url="https://www.fdma.go.jp/",
        program_kind="advisory_dispatch",
        tier_hint="C",
        description=(
            "消防団員確保や処遇改善に取り組む市町村に対して有識者を派遣し、"
            "助言・指導を行う消防庁事業。"
        ),
        authority_name="総務省 消防庁",
        target_types=("municipality",),
        funding_purpose=("消防団", "地域防災"),
    ),
    MicSeed(
        slug="mic-chiiki-okoshi-kyoryokutai",
        name="地域おこし協力隊",
        source_url="https://www.soumu.go.jp/main_sosiki/jichi_gyousei/c-gyousei/02gyosei08_03000066.html",
        program_kind="local_support_program",
        tier_hint="A",
        description=(
            "都市地域から過疎地域等へ住民票を移し、地域協力活動を行う者を"
            "「地域おこし協力隊員」として委嘱。隊員 1 人あたり年間 470 万円を上限に特別交付税措置。"
        ),
        authority_name="総務省 自治行政局 地域自立応援課",
        max_man_yen=470.0,
        target_types=("municipality", "individual"),
        funding_purpose=("地方創生", "関係人口", "移住促進"),
    ),
)


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch(url: str, *, retries: int = 2) -> tuple[int, str]:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
                raw = resp.read()
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
    soup = BeautifulSoup(html, "html.parser")
    title = None
    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string.strip())
    desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        desc = re.sub(r"\s+", " ", str(md["content"]).strip())
    return title, desc


# ---------------------------------------------------------------------------
# Tier classification & Build row
# ---------------------------------------------------------------------------

def classify(seed: MicSeed, http_status: int) -> tuple[str, int, str | None]:
    if http_status not in (200, 0):  # 0 = our retry-failure sentinel; treat as B (do not exclude curated)
        return "X", 1, "dead_source_url"
    if http_status == 0:
        return "B", 0, None
    has_amount = seed.max_man_yen is not None
    has_targets = bool(seed.target_types)
    if seed.tier_hint == "A" and has_amount and has_targets:
        return "A", 0, None
    if seed.tier_hint in ("S", "A") and (has_amount or has_targets):
        return "A", 0, None
    return seed.tier_hint, 0, None


def make_unified_id(slug: str) -> str:
    h = hashlib.sha1(f"mic:{slug}".encode("utf-8")).hexdigest()[:10]
    return f"UNI-{h}"


def build_row(seed: MicSeed, http_status: int, meta: tuple[str | None, str | None], fetched_at: str) -> dict[str, object]:
    tier, excluded, excl_reason = classify(seed, http_status)
    enriched = {
        "_meta": {
            "program_id": make_unified_id(seed.slug),
            "program_name": seed.name,
            "source_format": "html",
            "source_urls": [seed.source_url],
            "fetched_at": fetched_at,
            "model": "mic-seed-curated-v1",
            "worker_id": "ingest_mic",
            "fetch_method": "urllib",
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
        "aliases_json": json.dumps(list(seed.aliases), ensure_ascii=False) if seed.aliases else None,
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
        "target_types_json": json.dumps(list(seed.target_types), ensure_ascii=False) if seed.target_types else None,
        "funding_purpose_json": json.dumps(list(seed.funding_purpose), ensure_ascii=False) if seed.funding_purpose else None,
        "amount_band": None,
        "application_window_json": None,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"mic_seed": seed.slug}, ensure_ascii=False),
        "source_url": seed.source_url,
        "source_fetched_at": fetched_at,
        "source_checksum": hashlib.sha1(
            f"{seed.slug}|{seed.source_url}|{seed.name}|{seed.max_man_yen}|{','.join(seed.target_types)}".encode("utf-8")
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
    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
    "VALUES (?,?,?,?)"
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
            (row["unified_id"], row["primary_name"], row["aliases_json"] or "", row["primary_name"]),
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
    print(f"Probing {len(unique_urls)} unique MIC URLs at 1 req/s ...")
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
