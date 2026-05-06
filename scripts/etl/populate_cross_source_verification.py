#!/usr/bin/env python3
"""Populate ``programs.cross_source_verified`` + ``programs.verification_count``.

Wave 24+ moat-signal hardening (2026-05-05). Migration 151 added the two
columns; this script is the deterministic, **non-LLM**, hostname-only
populator that fills them.

Why
---
The phantom-moat audit established that *cross-source agreement* is the
only durable signal we own: a program row whose claim is corroborated by
two or more independent first-party hosts (e.g. METI + a 都道府県 page,
or e-Gov + NTA) is a verifiable, replayable claim. A single source_url
is not.

What this does
--------------
For every row in ``programs`` we collect URLs from:

* ``programs.source_url`` (primary citation),
* ``am_source.source_url`` joined via ``entity_id_map`` →
  ``am_entity_source`` (every other source the entity-fact graph has
  recorded for this program — ``role`` IN ('primary_source', 'pdf_url',
  'application_url', '', …), all are evidence).

Each URL's hostname is mapped to a stable *source-kind token* (a coarse
bucket — see ``HOST_KIND_RULES``). Tokens are sorted, deduplicated, and
written back as ``cross_source_verified`` (JSON list) and
``verification_count`` (distinct token count).

Tokens (current bucket list)
----------------------------
* ``egov``          — laws.e-gov.go.jp / elaws.e-gov.go.jp / e-gov.go.jp
* ``nta``           — *.nta.go.jp (国税庁; includes 国税不服審判所)
* ``moj``           — *.moj.go.jp / *.houjin-bangou.nta.go.jp legal-side
* ``maff``          — *.maff.go.jp (農林水産省 + 林野庁 + 水産庁 sub-)
* ``meti``          — *.meti.go.jp / *.chusho.meti.go.jp / enecho /
                      mirasapo-plus.go.jp
* ``mhlw``          — *.mhlw.go.jp
* ``mlit``          — *.mlit.go.jp
* ``mext``          — *.mext.go.jp
* ``env``           — *.env.go.jp
* ``soumu``         — *.soumu.go.jp
* ``cao``           — *.cao.go.jp / *.cfa.go.jp / *.caa.go.jp / *.bunka.go.jp
* ``jfc``           — *.jfc.go.jp (日本政策金融公庫)
* ``jgrants``       — jgrants-portal.go.jp / *.go.jp grants portals
* ``courts``        — *.courts.go.jp
* ``jbaudit``       — *.jbaudit.go.jp
* ``smrj``          — *.smrj.go.jp / it-shien.smrj.go.jp
* ``nedo``          — *.nedo.go.jp
* ``jetro``         — *.jetro.go.jp
* ``fsa``           — *.fsa.go.jp / *.jftc.go.jp / *.npa.go.jp
* ``pref_lg_jp``    — *.pref.<...>.jp / *.metro.tokyo.lg.jp 都道府県
* ``city_lg_jp``    — *.city.<...>.lg.jp / *.town/.../*.village 市町村
* ``go_jp_other``   — any other *.go.jp (catch-all 国 source)
* ``lg_jp_other``   — any other *.lg.jp (catch-all 自治体 source)
* ``ac_jp``         — *.ac.jp (大学・研究機関 — limited use)
* ``or_jp``         — *.or.jp (公益法人・組合 — limited use)

Anything outside the above (commercial, aggregator, foreign, unknown
TLD) is intentionally **dropped** — those do not earn moat-signal
weight. (Aggregators like noukaweb / hojyokin-portal are banned from
``source_url`` per CLAUDE.md "Data hygiene" but defensive dedup remains.)

Idempotency
-----------
Re-runs are O(programs). Each row gets the freshly-derived sorted list,
so reordering is impossible and partial runs are safe. ``--dry-run``
emits the distribution without writing.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

_LOG = logging.getLogger("jpcite.populate_cross_source_verification")


# ---------------------------------------------------------------------------
# Host -> kind token classification (deterministic, hostname-only).
# Order matters: the first matching rule wins.
# ---------------------------------------------------------------------------

# Full-host or suffix pattern -> kind token.
# Use re.fullmatch on lowercased host. Suffix matches are written as
# ".*\\.suffix$" so they don't accidentally swallow shorter hosts.
HOST_KIND_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Specific go.jp ministries / agencies (most-specific first)
    (re.compile(r".*\.e-gov\.go\.jp$|^e-gov\.go\.jp$"), "egov"),
    (re.compile(r".*\.elaws\.e-gov\.go\.jp$|^elaws\.e-gov\.go\.jp$"), "egov"),
    (re.compile(r".*\.nta\.go\.jp$|^nta\.go\.jp$"), "nta"),
    (re.compile(r".*\.moj\.go\.jp$|^moj\.go\.jp$"), "moj"),
    (re.compile(r".*\.maff\.go\.jp$|^maff\.go\.jp$"), "maff"),
    # METI family (includes mirasapo + chusho + enecho sub-hosts)
    (re.compile(r".*\.chusho\.meti\.go\.jp$"), "meti"),
    (re.compile(r".*\.enecho\.meti\.go\.jp$"), "meti"),
    (re.compile(r".*\.meti\.go\.jp$|^meti\.go\.jp$"), "meti"),
    (re.compile(r"^mirasapo-plus\.go\.jp$|.*\.mirasapo-plus\.go\.jp$"), "meti"),
    (re.compile(r".*\.mhlw\.go\.jp$|^mhlw\.go\.jp$"), "mhlw"),
    (re.compile(r".*\.mlit\.go\.jp$|^mlit\.go\.jp$"), "mlit"),
    (re.compile(r".*\.mext\.go\.jp$|^mext\.go\.jp$"), "mext"),
    (re.compile(r".*\.env\.go\.jp$|^env\.go\.jp$"), "env"),
    (re.compile(r".*\.soumu\.go\.jp$|^soumu\.go\.jp$"), "soumu"),
    # 内閣府 family (cao + 関連庁: 子ども家庭庁 cfa, 消費者庁 caa, 文化庁 bunka)
    (re.compile(r".*\.cao\.go\.jp$|^cao\.go\.jp$"), "cao"),
    (re.compile(r".*\.cfa\.go\.jp$|^cfa\.go\.jp$"), "cao"),
    (re.compile(r".*\.caa\.go\.jp$|^caa\.go\.jp$"), "cao"),
    (re.compile(r".*\.bunka\.go\.jp$|^bunka\.go\.jp$"), "cao"),
    # 政策金融公庫
    (re.compile(r".*\.jfc\.go\.jp$|^jfc\.go\.jp$"), "jfc"),
    # jGrants portal
    (re.compile(r"^jgrants-portal\.go\.jp$|.*\.jgrants-portal\.go\.jp$"), "jgrants"),
    # 裁判所
    (re.compile(r".*\.courts\.go\.jp$|^courts\.go\.jp$"), "courts"),
    # 会計検査院
    (re.compile(r".*\.jbaudit\.go\.jp$|^jbaudit\.go\.jp$"), "jbaudit"),
    # 中小機構 + IT shien
    (re.compile(r".*\.smrj\.go\.jp$|^smrj\.go\.jp$"), "smrj"),
    (re.compile(r"^it-shien\.smrj\.go\.jp$"), "smrj"),
    # 産業技術総合 / NEDO
    (re.compile(r".*\.nedo\.go\.jp$|^nedo\.go\.jp$"), "nedo"),
    # JETRO
    (re.compile(r".*\.jetro\.go\.jp$|^jetro\.go\.jp$"), "jetro"),
    # 金融庁・公正取引・警察庁
    (re.compile(r".*\.fsa\.go\.jp$|^fsa\.go\.jp$"), "fsa"),
    (re.compile(r".*\.jftc\.go\.jp$|^jftc\.go\.jp$"), "fsa"),
    (re.compile(r".*\.npa\.go\.jp$|^npa\.go\.jp$"), "fsa"),
    # 都道府県 (pref.<XX>.{lg.jp,jp} + tokyo metro variant)
    (re.compile(r"^.*\.pref\.[a-z0-9-]+\.(?:lg\.jp|jp)$"), "pref_lg_jp"),
    (re.compile(r"^pref\.[a-z0-9-]+\.(?:lg\.jp|jp)$"), "pref_lg_jp"),
    (re.compile(r"^.*\.metro\.tokyo\.(?:lg\.jp|jp)$"), "pref_lg_jp"),
    (re.compile(r"^.*\.metro\.tokyo\.jp$"), "pref_lg_jp"),
    # 市町村 (city/town/village.<...>.{lg.jp,jp})
    (re.compile(r"^.*\.city\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    (re.compile(r"^city\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    (re.compile(r"^.*\.town\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    (re.compile(r"^town\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    (re.compile(r"^.*\.village\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    # `.vill.<municipality>.<prefecture>.jp` (legacy host shape used by
    # several villages — Gunma's 嬬恋村 is a notable example)
    (re.compile(r"^.*\.vill\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    (re.compile(r"^vill\.[a-z0-9.-]+\.(?:lg\.jp|jp)$"), "city_lg_jp"),
    # Catch-all *.go.jp (any other 国-side host)
    (re.compile(r".*\.go\.jp$|^go\.jp$"), "go_jp_other"),
    # Catch-all *.lg.jp (any other 自治体)
    (re.compile(r".*\.lg\.jp$|^lg\.jp$"), "lg_jp_other"),
    # 大学・研究機関
    (re.compile(r".*\.ac\.jp$"), "ac_jp"),
    # 公益法人・組合 (limited weight)
    (re.compile(r".*\.or\.jp$"), "or_jp"),
    # ------------------------------------------------------------------
    # W21-2 first-party host classifier extension (2026-05-05).
    # These are NOT aggregators — they are operated by the named issuing
    # body itself (政府系金融機関 / 商工会連合会 / 独立行政法人 / 自治体
    # 例規ホスティング). Bucket = `gov_portal` (durable signal, equal in
    # weight to a ministry citation for the program it owns).
    # ------------------------------------------------------------------
    # 例規ホスティング (g-reiki / g-reiki.net 例規 SaaS used by 100+
    # 自治体 — every URL on this host is a 自治体 ordinance verbatim).
    (re.compile(r".*\.g-reiki\.net$|^g-reiki\.net$"), "gov_portal"),
    (re.compile(r".*\.gyoseifuku\.go\.jp$"), "gov_portal"),
    # 政府系金融 (商工中金 / 信金中金 / DBJ / 日本政策投資銀行)
    (re.compile(r".*\.shokochukin\.co\.jp$|^shokochukin\.co\.jp$"), "gov_portal"),
    (re.compile(r".*\.shinkin-central-bank\.jp$|^shinkin-central-bank\.jp$"), "gov_portal"),
    (re.compile(r".*\.dbj\.jp$|^dbj\.jp$"), "gov_portal"),
    # JAバンク全国 (信用事業全国組織 — 政府機能の延長)
    (re.compile(r".*\.jabank\.org$|^jabank\.org$"), "gov_portal"),
    # 独立行政法人 JAXA (funding agency 系含む)
    (re.compile(r".*\.jaxa\.jp$|^jaxa\.jp$"), "gov_portal"),
    # 持続化補助金 / ものづくり補助金 / 共同共業補助金 official portals
    # (商工会連合会 / 中小機構 委託運営 — first-party for these programs)
    (re.compile(r".*\.jizokukanb\.com$|^jizokukanb\.com$"), "gov_portal"),
    (re.compile(r".*\.jizokukahojokin\.info$|^jizokukahojokin\.info$"), "gov_portal"),
    (re.compile(r".*\.jizokuka-post-corona\.jp$|^jizokuka-post-corona\.jp$"), "gov_portal"),
    (re.compile(r".*\.monodukuri-hojo\.jp$|^monodukuri-hojo\.jp$"), "gov_portal"),
    (re.compile(r".*\.smart-hojokin\.jp$|^smart-hojokin\.jp$"), "gov_portal"),
    (re.compile(r".*\.kyodokyogyohojokin\.info$|^kyodokyogyohojokin\.info$"), "gov_portal"),
    # mirasapo (旧 mirasapo.jp — 中小機構運営、新ドメイン mirasapo-plus.go.jp は既存ルールでカバー)
    (re.compile(r".*\.mirasapo\.jp$|^mirasapo\.jp$"), "gov_portal"),
    # 東京都ゼロエミ (東京都環境公社運営 — 都の公的事業)
    (re.compile(r".*\.tokyo-co2down\.jp$|^tokyo-co2down\.jp$"), "gov_portal"),
    # ------------------------------------------------------------------
    # 自治体 .jp (legacy hostname pattern: city/town published before
    # the .lg.jp scheme matured). Treated as `city_lg_jp` because the
    # signal is identical — the issuing body is the municipality.
    # Whitelisted by exact host (not pattern) to avoid false positives
    # on commercial domains that happen to share a stem.
    # ------------------------------------------------------------------
    (
        re.compile(
            r"^(www\.)?("
            r"akitakata|kuriharacity|kagoshima-iju|kuma-farm|sarabetsu|"
            r"betsukai|hyogo-shunou|city-kirishima|shintoku-town|shien-39|"
            r"farming-furano|ishikari-asc|nakashibetsu|rikubetsu|higashikagawa|"
            r"hyugacity|shinhidaka-hokkaido|masudanohito|hirado-nova|kochi-be-farmer|"
            r"shibetsutown|townkamiita|bungo-ohno|noufuku|higashikushira|"
            r"sumusumuyamaguchi|satsuma-net|noukatsu-nagano|yasugi-gurashi|"
            r"city-nakatsu|ibaragurashi|urahoro|townhamanaka|memuro|"
            r"jinsekigun|kumakogen|aomori-nogyoshien|saga888|kochi-iju|"
            r"nankyu-farming|hitoyoshi-life|ebina-nogyo|betsukai-kenboku|"
            r"shimonosekicitypromotion|cocomaniwa|yabugurashi|"
            r"agri-ishikari|akita-agri-navi"
            r")\.jp$"
        ),
        "city_lg_jp",
    ),
)


def classify_host(host: str | None) -> str | None:
    """Return the source-kind token for *host*, or ``None`` if outside the moat."""
    if not host:
        return None
    h = host.strip().lower()
    if not h:
        return None
    # Strip trailing dot if present
    if h.endswith("."):
        h = h[:-1]
    for pattern, kind in HOST_KIND_RULES:
        if pattern.fullmatch(h):
            return kind
    return None


def host_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
    except (ValueError, AttributeError):
        return None
    return (parsed.hostname or "").lower() or None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def load_program_primary_urls(jp_conn: sqlite3.Connection) -> dict[str, str | None]:
    rows = jp_conn.execute("SELECT unified_id, source_url FROM programs").fetchall()
    return {str(row["unified_id"]): row["source_url"] for row in rows}


def load_secondary_urls(am_conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return ``{jpi_unified_id: [secondary_url, ...]}`` from the EAV graph.

    The walk: ``entity_id_map`` (jpi -> am canonical) →
    ``am_entity_source`` (canonical -> source_id) → ``am_source.source_url``.
    De-duped per program before returning.
    """
    rows = am_conn.execute(
        """
        SELECT m.jpi_unified_id AS uid, s.source_url AS url
          FROM entity_id_map m
          JOIN am_entity_source es ON es.entity_id = m.am_canonical_id
          JOIN am_source        s  ON s.id = es.source_id
         WHERE s.source_url IS NOT NULL
           AND TRIM(s.source_url) != ''
        """
    ).fetchall()
    bucket: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        uid = str(row["uid"])
        url = str(row["url"]).strip()
        if url:
            bucket[uid].add(url)
    return {uid: sorted(urls) for uid, urls in bucket.items()}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def derive_tokens(urls: list[str | None]) -> list[str]:
    """Return the sorted, distinct kind-token list for a set of URLs."""
    tokens: set[str] = set()
    for url in urls:
        token = classify_host(host_of(url))
        if token:
            tokens.add(token)
    return sorted(tokens)


def compute_program_tokens(
    primary_by_uid: dict[str, str | None],
    secondary_by_uid: dict[str, list[str]],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for uid, primary in primary_by_uid.items():
        urls: list[str | None] = []
        if primary:
            urls.append(primary)
        urls.extend(secondary_by_uid.get(uid, []))
        out[uid] = derive_tokens(urls)
    return out


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_updates(
    jp_conn: sqlite3.Connection,
    tokens_by_uid: dict[str, list[str]],
    *,
    chunk_size: int = 1000,
) -> int:
    """Write tokens back. Returns updated row count."""
    rows = [
        (
            json.dumps(tokens, ensure_ascii=False, separators=(",", ":")),
            len(tokens),
            uid,
        )
        for uid, tokens in tokens_by_uid.items()
    ]
    updated = 0
    with jp_conn:
        for i in range(0, len(rows), chunk_size):
            batch = rows[i : i + chunk_size]
            jp_conn.executemany(
                """UPDATE programs
                      SET cross_source_verified = ?,
                          verification_count   = ?
                    WHERE unified_id = ?""",
                batch,
            )
            updated += len(batch)
    return updated


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def distribution(tokens_by_uid: dict[str, list[str]]) -> dict[str, Any]:
    """Summarise the verification_count and token-frequency distribution."""
    bucket = Counter()
    token_counter: Counter[str] = Counter()
    for tokens in tokens_by_uid.values():
        n = len(tokens)
        if n == 0:
            bucket["0"] += 1
        elif n == 1:
            bucket["1"] += 1
        elif n == 2:
            bucket["2"] += 1
        else:
            bucket["3+"] += 1
        token_counter.update(tokens)
    total = sum(bucket.values())
    return {
        "total_programs": total,
        "by_verification_count": {
            "0": bucket["0"],
            "1": bucket["1"],
            "2": bucket["2"],
            "3+": bucket["3+"],
        },
        "top_tokens": dict(token_counter.most_common(15)),
        "distinct_token_count": len(token_counter),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def populate(
    jp_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection,
    *,
    apply: bool,
) -> dict[str, Any]:
    primary = load_program_primary_urls(jp_conn)
    secondary = load_secondary_urls(am_conn)
    tokens_by_uid = compute_program_tokens(primary, secondary)
    dist_before = distribution(tokens_by_uid)
    updated_rows = 0
    if apply:
        updated_rows = apply_updates(jp_conn, tokens_by_uid)
    return {
        "mode": "apply" if apply else "dry_run",
        "programs_seen": len(primary),
        "programs_with_secondary_urls": sum(1 for v in secondary.values() if v),
        "secondary_urls_total": sum(len(v) for v in secondary.values()),
        "updated_rows": updated_rows,
        "distribution": dist_before,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with _connect(args.jpintel_db) as jp_conn, _connect(args.autonomath_db) as am_conn:
        result = populate(jp_conn, am_conn, apply=args.apply)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        d = result["distribution"]
        print(f"mode={result['mode']}")
        print(f"programs_seen={result['programs_seen']}")
        print(f"programs_with_secondary_urls={result['programs_with_secondary_urls']}")
        print(f"secondary_urls_total={result['secondary_urls_total']}")
        print(f"updated_rows={result['updated_rows']}")
        print(f"total={d['total_programs']}")
        print("verification_count distribution:")
        for k in ("0", "1", "2", "3+"):
            print(f"  {k}: {d['by_verification_count'][k]}")
        print(f"distinct_token_count={d['distinct_token_count']}")
        print("top_tokens:")
        for token, count in d["top_tokens"].items():
            print(f"  {token}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
