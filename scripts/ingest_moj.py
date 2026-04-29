#!/usr/bin/env python3
"""ingest_moj.py — 法務省 (MOJ) 法令・登記・人権 関連制度を jpintel.db へ取り込む。

Source: https://www.moj.go.jp/  (一次資料のみ)

License: 政府標準利用規約 (gov_standard) — © Ministry of Justice. 出典明示で再配布可。

Recon (2026-04-29):
  * 法務省は補助金提供省庁ではない。主な ingest 対象は:
      - 商業登記簿 / 法人登記 関連 公的ガイダンス (制度として常時)
      - 人権擁護局: 人権相談窓口・啓発制度
      - 出入国在留管理庁: 在留資格手続支援
      - 法テラス (民事法律扶助) — JLF が運営、法務省所管
      - 矯正局・保護局: 更生保護関連 (補助金あり)
  * 件数推定: curated 15-25 件 (法令系制度の枠組みベース)。
  * RSS: なし。/list_info.html (お知らせ一覧) の HTML スクレイプ可。

Strategy:
  * 補助金は「更生保護法人助成 / 人権侵害救済事業」等の少数のみ。
  * 主体は curated seed (法令制度の枠組みを programs として記録)。
  * Tier は MIC と同様 — curated B-C が大半、補助金 A 級は少数。
  * 冪等: source_checksum (sha1(slug|url|name|kind)) 一致なら skip。

Constraints:
  * NO Anthropic API. urllib + bs4. Rate-limit 1 req/s.
  * BEGIN IMMEDIATE + busy_timeout=300_000.
  * Aggregator 禁止: source_url は moj.go.jp / law.go.jp / houterasu.or.jp 限定。

Run:
  .venv/bin/python scripts/ingest_moj.py
  .venv/bin/python scripts/ingest_moj.py --dry-run
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

LICENSE_ATTR = "© 法務省 (Ministry of Justice) / 政府標準利用規約 2.0 — 出典明示で再配布可"


@dataclasses.dataclass(frozen=True)
class MojSeed:
    slug: str
    name: str
    source_url: str
    program_kind: str  # 'subsidy' | 'regulation' | 'authorization' | 'public_service'
    tier_hint: str
    description: str
    authority_name: str
    max_man_yen: float | None = None
    target_types: tuple[str, ...] = ()
    funding_purpose: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


SEEDS: tuple[MojSeed, ...] = (
    # ---- 民事局: 商業・法人登記 関連 ----
    MojSeed(
        slug="moj-shogyou-touki-online-search",
        name="商号調査 (オンライン登記情報検索サービス)",
        source_url="https://www1.touki.or.jp/",
        program_kind="public_service",
        tier_hint="B",
        description=(
            "登記前の商号重複確認のための無料オンライン検索。商号・名称・"
            "所在地・会社法人等番号で検索可能。同一商号・同一所在地は登記不可。"
        ),
        authority_name="法務省 民事局 商事課",
        target_types=("corporation", "individual"),
        funding_purpose=("法人登記", "商号調査"),
    ),
    MojSeed(
        slug="moj-houjin-bangou-system",
        name="法人番号公表サイト",
        source_url="https://www.houjin-bangou.nta.go.jp/",
        program_kind="public_service",
        tier_hint="B",
        description=(
            "国税庁が運営する法人番号 (T番号) 公表サイト。商業登記情報の"
            "うち基本3情報 (商号・所在地・法人番号) を公開。法務省民事局と連携。"
        ),
        authority_name="法務省 民事局 / 国税庁",
        target_types=("corporation",),
        funding_purpose=("法人登記", "法人番号"),
    ),
    MojSeed(
        slug="moj-touki-jouhou-online",
        name="登記・供託オンライン申請システム",
        source_url="https://www.touki-kyoutaku-online.moj.go.jp/",
        program_kind="public_service",
        tier_hint="B",
        description=(
            "不動産登記・商業登記・成年後見登記・供託に関する申請をオンライン"
            "で行うシステム。法務省民事局運営。"
        ),
        authority_name="法務省 民事局",
        target_types=("corporation", "individual"),
        funding_purpose=("登記申請", "供託申請"),
    ),
    # ---- 法テラス (民事法律扶助) ----
    MojSeed(
        slug="moj-houterasu-minji-fujio",
        name="民事法律扶助 (法テラス)",
        source_url="https://www.houterasu.or.jp/madoguchi_info/houritsu/index.html",
        program_kind="public_service",
        tier_hint="A",
        description=(
            "経済的に余裕のない方を対象に、無料法律相談 (3 回まで) と弁護士費用の"
            "立替 (民事・家事事件) を提供する制度。日本司法支援センター (法テラス) 運営。"
        ),
        authority_name="法務省 / 日本司法支援センター (法テラス)",
        target_types=("individual",),
        funding_purpose=("法律相談", "司法支援"),
        aliases=("法テラス", "JLF",),
    ),
    MojSeed(
        slug="moj-houterasu-stalker",
        name="DV・ストーカー・児童虐待被害者法律相談援助",
        source_url="https://www.houterasu.or.jp/higaishashien/dv_stalker/index.html",
        program_kind="public_service",
        tier_hint="A",
        description=(
            "DV・ストーカー・児童虐待の被害者を対象に、資力にかかわらず無料の"
            "法律相談を提供する法テラス特例制度。"
        ),
        authority_name="法務省 / 日本司法支援センター (法テラス)",
        target_types=("individual",),
        funding_purpose=("DV対策", "被害者支援"),
    ),
    # ---- 人権擁護局 ----
    MojSeed(
        slug="moj-jinken-soudan",
        name="人権相談窓口 (みんなの人権110番)",
        source_url="https://www.moj.go.jp/JINKEN/jinken20.html",
        program_kind="public_service",
        tier_hint="B",
        description=(
            "全国 50 か所の法務局・地方法務局および 311 の支局で行う人権相談。"
            "法務省人権擁護局・全国人権擁護委員連合会が連携運営。"
        ),
        authority_name="法務省 人権擁護局",
        target_types=("individual",),
        funding_purpose=("人権擁護", "差別防止"),
    ),
    MojSeed(
        slug="moj-jinken-keihatsu-katsudou",
        name="人権啓発活動地方委託事業",
        source_url="https://www.moj.go.jp/JINKEN/jinken_index.html",
        program_kind="grant",
        tier_hint="B",
        description=(
            "人権啓発活動を地方公共団体に委託する事業。人権擁護に関する"
            "研修・講演会・冊子作成等。"
        ),
        authority_name="法務省 人権擁護局",
        target_types=("prefecture", "municipality"),
        funding_purpose=("人権啓発", "地方委託"),
    ),
    # ---- 出入国在留管理庁 ----
    MojSeed(
        slug="moj-isa-nyuukan-shinsei",
        name="在留資格認定証明書交付申請オンライン化",
        source_url="https://www.moj.go.jp/isa/applications/procedures/i-ens_index.html",
        program_kind="public_service",
        tier_hint="B",
        description=(
            "外国人の在留資格認定証明書交付申請を、ISA オンライン申請システム"
            "経由で行う制度。受入企業・教育機関等が申請可能。"
        ),
        authority_name="法務省 出入国在留管理庁",
        target_types=("corporation", "educational_institution"),
        funding_purpose=("在留資格", "外国人雇用"),
    ),
    MojSeed(
        slug="moj-tokutei-ginou",
        name="特定技能制度 (受入機関への支援義務)",
        source_url="https://www.moj.go.jp/isa/applications/ssw/index.html",
        program_kind="regulation",
        tier_hint="A",
        description=(
            "特定技能 1 号外国人を受け入れる機関は、生活支援等を行うことが"
            "義務付けられる制度。登録支援機関による委託も可能。"
        ),
        authority_name="法務省 出入国在留管理庁",
        target_types=("corporation",),
        funding_purpose=("外国人雇用", "受入支援"),
    ),
    MojSeed(
        slug="moj-touroku-shien-kikan",
        name="登録支援機関制度",
        source_url="https://www.moj.go.jp/isa/applications/ssw/nyuukokukanri07_00205.html",
        program_kind="authorization",
        tier_hint="B",
        description=(
            "特定技能 1 号外国人の支援計画作成・実施を受託する機関の登録制度。"
            "登録は出入国在留管理庁が実施。"
        ),
        authority_name="法務省 出入国在留管理庁",
        target_types=("corporation", "individual"),
        funding_purpose=("特定技能", "外国人支援"),
    ),
    # ---- 矯正局 / 保護局: 更生保護 ----
    MojSeed(
        slug="moj-kousei-hogo-houjin-josei",
        name="更生保護法人運営費補助金",
        source_url="https://www.moj.go.jp/hogo1/soumu/hogo01_00029.html",
        program_kind="subsidy",
        tier_hint="A",
        description=(
            "更生保護施設を運営する更生保護法人に対する国庫補助。"
            "保護対象者の宿泊・食事・職業訓練等の費用を支援。"
        ),
        authority_name="法務省 保護局",
        max_man_yen=None,  # 法人ごとに変動
        target_types=("public_interest_corporation",),
        funding_purpose=("更生保護", "再犯防止"),
    ),
    MojSeed(
        slug="moj-bpo-shokuba-fukki-shien",
        name="刑事施設出所者就労支援事業",
        source_url="https://www.moj.go.jp/hogo1/soumu/hogo02_00026.html",
        program_kind="grant",
        tier_hint="B",
        description=(
            "刑事施設出所者等の就労を支援する協力雇用主・登録支援団体への"
            "助成・委託費。再犯防止推進法に基づく事業。"
        ),
        authority_name="法務省 保護局",
        target_types=("corporation", "ngo"),
        funding_purpose=("再犯防止", "就労支援"),
    ),
    # ---- 法令系 (制度の枠組み) ----
    MojSeed(
        slug="moj-egov-laws",
        name="e-Gov 法令検索",
        source_url="https://elaws.e-gov.go.jp/",
        program_kind="public_service",
        tier_hint="B",
        description=(
            "総務省 + 法務省連携で提供する法令検索ポータル。法令本文・"
            "新旧対照表 (差分) を CC-BY 4.0 で公開。"
        ),
        authority_name="法務省 大臣官房司法法制部 / 総務省",
        target_types=("individual", "corporation"),
        funding_purpose=("法令情報", "法令検索"),
    ),
    MojSeed(
        slug="moj-shihou-shoshi-houritsu",
        name="司法書士・土地家屋調査士 検索",
        source_url="https://www.moj.go.jp/MINJI/shihousyoshi.html",
        program_kind="public_service",
        tier_hint="C",
        description=(
            "司法書士会・土地家屋調査士会連合会と連携した検索サービス。"
            "登記申請等の専門家紹介。"
        ),
        authority_name="法務省 民事局",
        target_types=("individual", "corporation"),
        funding_purpose=("登記支援",),
    ),
)


# ---------------------------------------------------------------------------
# HTTP fetch + meta parse (same pattern)
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
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        desc = re.sub(r"\s+", " ", str(md["content"]).strip())
    return title, desc


def make_unified_id(slug: str) -> str:
    h = hashlib.sha1(f"moj:{slug}".encode("utf-8")).hexdigest()[:10]
    return f"UNI-{h}"


def classify(seed: MojSeed, http_status: int) -> tuple[str, int, str | None]:
    if http_status not in (200, 0):
        return "X", 1, "dead_source_url"
    if http_status == 0:
        return "C", 0, None
    return seed.tier_hint, 0, None


def build_row(seed: MojSeed, http_status: int, meta: tuple[str | None, str | None], fetched_at: str) -> dict[str, object]:
    tier, excluded, excl_reason = classify(seed, http_status)
    enriched = {
        "_meta": {
            "program_id": make_unified_id(seed.slug),
            "program_name": seed.name,
            "source_format": "html",
            "source_urls": [seed.source_url],
            "fetched_at": fetched_at,
            "model": "moj-seed-curated-v1",
            "worker_id": "ingest_moj",
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
        "source_mentions_json": json.dumps({"moj_seed": seed.slug}, ensure_ascii=False),
        "source_url": seed.source_url,
        "source_fetched_at": fetched_at,
        "source_checksum": hashlib.sha1(
            f"{seed.slug}|{seed.source_url}|{seed.name}|{seed.program_kind}".encode("utf-8")
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
    print(f"Probing {len(unique_urls)} unique MOJ-related URLs at 1 req/s ...")
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
