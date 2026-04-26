"""Graph traversal pre-computer for AutonoMath Layer 7.

Reads canonical data from /tmp/autonomath_data_collection_2026-04-23/*/records.jsonl
(read-only) and emits pre-computed closures keyed by program/measure/cert id.

Cache destination: `am_precomputed` table (see SQL_SCHEMA below). This module does NOT
write to a real DB — that's a different agent's job. We emit the payloads as plain
dicts and persist to a local JSON cache so match.py can bind them.

Inputs:
- 03_exclusion_rules/records.jsonl   (78 rules — compat / incompat / prerequisite)
- 12_tax_incentives/records.jsonl    (40 tax measures)
- 09_certification_programs/records.jsonl (certifications + unlocked_programs)
- 139_invoice_consumption_tax/records.jsonl (dated tax rules)

Outputs (to /tmp/autonomath_infra_2026-04-24/reasoning/_cache/precomputed.json):
- program.compat_closure[program_id]      -> list[program_id] (transitive)
- program.incompat_closure[program_id]    -> list[program_id] (transitive)
- program.prereq_closure[program_id]      -> list[certification_id]
- authority.parent_ministry[authority]    -> ministry name
- law.latest_amendment[law_id]            -> ISO date
- tax_measure.validity_index[measure_id]  -> {from, to, status_as_of(today)}
- certification.unlocks_programs[cert_id] -> list[program_id]

Usage:
    python -m reasoning.precompute                   # build cache
    from reasoning.precompute import load_cache      # consume

The transitive closure is computed naively (BFS per node). With ~160 programs this
completes in <100 ms. If/when we scale past ~10k programs, swap to Floyd-Warshall.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_ROOT = Path("/tmp/autonomath_data_collection_2026-04-23")
PKG_ROOT = Path(__file__).resolve().parent
CACHE_DIR = PKG_ROOT / "_cache"
CACHE_PATH = CACHE_DIR / "precomputed.json"

TODAY = date(2026, 4, 23)


# ---------------------------------------------------------------------------
# SQL schema sketch (not executed — schema-only, another agent owns the DB)
# ---------------------------------------------------------------------------

SQL_SCHEMA = """
-- am_precomputed / layer-7 cache
--
-- Key = (entity_type, entity_id, closure_kind).
-- Value = JSON payload. The shape depends on closure_kind.
--
-- entity_type ∈ {program, tax_measure, certification, authority, law}
-- closure_kind ∈ {
--   compat_closure,       -- list[program_id] — transitive compatible
--   incompat_closure,     -- list[program_id] — transitive incompatible (includes implicit pairs)
--   prereq_closure,       -- list[certification_id] — required upstream of this program
--   authority_parent,     -- {ministry, bureau}
--   law_latest_amendment, -- {fy, effective_date, summary}
--   validity_index,       -- {from, to, status_as_of, days_remaining, successor}
--   unlocks_programs      -- list[program_id]
-- }

CREATE TABLE IF NOT EXISTS am_precomputed (
  entity_type    TEXT    NOT NULL,
  entity_id      TEXT    NOT NULL,
  closure_kind   TEXT    NOT NULL,
  payload_json   TEXT    NOT NULL,
  computed_at    TEXT    NOT NULL,     -- ISO UTC
  source_version TEXT    NOT NULL,     -- e.g. "2026-04-23-exclusion_rules:78"
  PRIMARY KEY (entity_type, entity_id, closure_kind)
);

CREATE INDEX IF NOT EXISTS ix_amp_entity    ON am_precomputed(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_amp_kind      ON am_precomputed(closure_kind);
"""


# ---------------------------------------------------------------------------
# Raw record loaders
# ---------------------------------------------------------------------------

def _jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_exclusion_rules() -> List[dict]:
    return list(_jsonl(DATA_ROOT / "03_exclusion_rules" / "records.jsonl"))


def load_tax_measures() -> List[dict]:
    return list(_jsonl(DATA_ROOT / "12_tax_incentives" / "records.jsonl"))


def load_certifications() -> List[dict]:
    return list(_jsonl(DATA_ROOT / "09_certification_programs" / "records.jsonl"))


def load_invoice_rules() -> List[dict]:
    return list(_jsonl(DATA_ROOT / "139_invoice_consumption_tax" / "records.jsonl"))


# ---------------------------------------------------------------------------
# Name canonicalization — collapse "ものづくり補助金 (第23次公募)" -> "ものづくり補助金"
# so pairwise edges align across records. Keep the round as a separate slot.
# ---------------------------------------------------------------------------

_NAME_NORMALIZE_RE = re.compile(
    r"\s*[\(（][^\)）]*[\)）]\s*"  # anything in parens
)
_ROUND_RE = re.compile(r"第\s*\d+\s*[回次]|R\d+|令和\s*\d+\s*年度|\d{4}年度")


def canonical_program_id(name: str) -> str:
    if not name:
        return ""
    stripped = _NAME_NORMALIZE_RE.sub("", name).strip()
    # Drop trailing round markers
    stripped = _ROUND_RE.sub("", stripped).strip()
    # Collapse spacing
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped


def extract_round(name: str) -> Optional[str]:
    if not name:
        return None
    m = _ROUND_RE.search(name)
    return m.group(0).strip() if m else None


# ---------------------------------------------------------------------------
# Edge extraction
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    a: str           # canonical program id
    b: str
    kind: str        # compatible | incompatible | prerequisite
    condition: str = ""
    source_url: str = ""


def build_edges_from_exclusions(rules: List[dict]) -> List[Edge]:
    edges: List[Edge] = []
    for r in rules:
        a_raw = r.get("program_name_a") or ""
        a = canonical_program_id(a_raw)
        if not a:
            continue
        rule_type = (r.get("rule_type") or "").strip()
        for b_raw in (r.get("excluded_programs") or []):
            b = canonical_program_id(b_raw)
            if not b or b == a:
                continue
            if rule_type == "exclude":
                kind = "incompatible"
            elif rule_type == "combine_ok":
                kind = "compatible"
            elif rule_type == "prerequisite":
                kind = "prerequisite"
            else:
                # Unknown rule_type — skip rather than invent
                continue
            edges.append(Edge(a=a, b=b, kind=kind,
                              condition=r.get("condition") or "",
                              source_url=r.get("source_url") or ""))
    return edges


def build_edges_from_tax_compat(measures: List[dict]) -> List[Edge]:
    """12_tax_incentives.compatible_with = explicit compatibility."""
    edges: List[Edge] = []
    for m in measures:
        a_raw = m.get("name") or ""
        a = canonical_program_id(a_raw)
        for b_raw in (m.get("compatible_with") or []):
            # Entries often read "X税制(重複不可)" — split that
            b_raw_s = str(b_raw)
            if "重複不可" in b_raw_s or "併用不可" in b_raw_s:
                kind = "incompatible"
                b_raw_s = re.sub(r"[\(（][^\)）]*[\)）]", "", b_raw_s)
            else:
                kind = "compatible"
            b = canonical_program_id(b_raw_s)
            if not b or b == a:
                continue
            edges.append(Edge(a=a, b=b, kind=kind,
                              condition="tax_incentive.compatible_with",
                              source_url=m.get("official_url") or ""))
        # prerequisite_certification -> prerequisite edge (cert id)
        prereq = m.get("prerequisite_certification")
        if prereq:
            # keep as prerequisite edge with cert as target
            edges.append(Edge(a=a, b=canonical_program_id(prereq),
                              kind="prerequisite",
                              condition="tax_incentive.prerequisite_certification",
                              source_url=m.get("official_url") or ""))
    return edges


def build_edges_from_certifications(certs: List[dict]) -> Tuple[List[Edge], Dict[str, List[str]]]:
    """09_certification_programs.linked_subsidies = unlocks relation."""
    edges: List[Edge] = []
    unlocks: Dict[str, List[str]] = defaultdict(list)
    for c in certs:
        cert_name = c.get("program_name") or ""
        cert_id = canonical_program_id(cert_name)
        for prog_raw in (c.get("linked_subsidies") or []):
            prog_id = canonical_program_id(str(prog_raw))
            if not prog_id:
                continue
            # Edge: program requires cert (prerequisite)
            edges.append(Edge(a=prog_id, b=cert_id, kind="prerequisite",
                              condition="certification.linked_subsidy",
                              source_url=c.get("official_url") or ""))
            unlocks[cert_id].append(prog_id)
    return edges, dict(unlocks)


# ---------------------------------------------------------------------------
# Transitive closure (BFS per source)
# ---------------------------------------------------------------------------

def transitive_closure(edges: List[Edge], kind: str) -> Dict[str, List[str]]:
    adj: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        if e.kind != kind:
            continue
        adj[e.a].add(e.b)
        # compat and incompat are symmetric at the pair level in the source data
        if kind in ("compatible", "incompatible"):
            adj[e.b].add(e.a)

    closure: Dict[str, List[str]] = {}
    for src in adj:
        seen: Set[str] = set()
        q = deque([src])
        while q:
            node = q.popleft()
            for nb in adj.get(node, ()):
                if nb not in seen and nb != src:
                    seen.add(nb)
                    q.append(nb)
        closure[src] = sorted(seen)
    return closure


# ---------------------------------------------------------------------------
# Authority -> parent ministry table
# ---------------------------------------------------------------------------

# Minimal hand-curated mapping — deliberately small, honest about gaps. If we need
# the full 所管 graph we'd ingest 10_municipality_master and the 官庁 registry.
AUTHORITY_PARENT: Dict[str, Dict[str, str]] = {
    "中小企業庁": {"ministry": "経済産業省", "bureau": "中小企業庁"},
    "中小機構": {"ministry": "経済産業省", "bureau": "独立行政法人中小企業基盤整備機構"},
    "経済産業省": {"ministry": "経済産業省", "bureau": "経済産業省"},
    "厚生労働省": {"ministry": "厚生労働省", "bureau": "厚生労働省"},
    "農林水産省": {"ministry": "農林水産省", "bureau": "農林水産省"},
    "国土交通省": {"ministry": "国土交通省", "bureau": "国土交通省"},
    "観光庁": {"ministry": "国土交通省", "bureau": "観光庁"},
    "環境省": {"ministry": "環境省", "bureau": "環境省"},
    "SII": {"ministry": "経済産業省", "bureau": "一般社団法人環境共創イニシアチブ"},
    "国税庁": {"ministry": "財務省", "bureau": "国税庁"},
    "財務省": {"ministry": "財務省", "bureau": "財務省"},
    "内閣府": {"ministry": "内閣府", "bureau": "内閣府"},
    "デジタル庁": {"ministry": "内閣府", "bureau": "デジタル庁"},
    "都道府県知事": {"ministry": "地方自治体", "bureau": "都道府県"},
    "都道府県": {"ministry": "地方自治体", "bureau": "都道府県"},
    "市区町村": {"ministry": "地方自治体", "bureau": "市区町村"},
}


def resolve_authority_parent(authority_text: str) -> Dict[str, str]:
    if not authority_text:
        return {"ministry": "unknown", "bureau": "unknown"}
    for key, val in AUTHORITY_PARENT.items():
        if key in authority_text:
            return dict(val)
    return {"ministry": "unknown", "bureau": authority_text[:40]}


# ---------------------------------------------------------------------------
# Validity index for tax measures
# ---------------------------------------------------------------------------

def parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).split("T")[0]).date()
    except (ValueError, TypeError):
        return None


def build_validity_index(measures: List[dict], as_of: date = TODAY) -> Dict[str, dict]:
    idx: Dict[str, dict] = {}
    for m in measures:
        mid = m.get("id") or canonical_program_id(m.get("name") or "")
        if not mid:
            continue
        frm = parse_iso_date(m.get("application_period_from"))
        to = parse_iso_date(m.get("application_period_to"))
        status = "unknown"
        days_remaining: Optional[int] = None
        if frm and to:
            if as_of < frm:
                status = "not_yet_active"
                days_remaining = (frm - as_of).days
            elif as_of > to:
                status = "expired"
                days_remaining = 0
            else:
                status = "active"
                days_remaining = (to - as_of).days
        idx[mid] = {
            "measure_id": mid,
            "name": m.get("name"),
            "tax_category": m.get("tax_category"),
            "root_law": m.get("root_law"),
            "application_period_from": m.get("application_period_from"),
            "application_period_to": m.get("application_period_to"),
            "status_as_of": as_of.isoformat(),
            "status": status,
            "days_remaining": days_remaining,
            "abolition_note": m.get("abolition_note"),
            "prerequisite_certification": m.get("prerequisite_certification"),
            "official_url": m.get("official_url"),
        }
    return idx


# ---------------------------------------------------------------------------
# Law latest-amendment index (best-effort from invoice records which have start_date)
# ---------------------------------------------------------------------------

def build_law_amendment_index(
    invoice_rules: List[dict],
    tax_measures: List[dict],
) -> Dict[str, dict]:
    idx: Dict[str, dict] = {}
    for r in invoice_rules:
        key_facts = r.get("key_facts") or {}
        law = key_facts.get("law") or r.get("governing_law")
        start = key_facts.get("start_date")
        if not law:
            continue
        prev = idx.get(law)
        if not prev or (start and start > (prev.get("effective_date") or "")):
            idx[law] = {
                "law_id": law,
                "effective_date": start,
                "source_url": r.get("source_url"),
                "source_name": r.get("source_name"),
            }
    # Also fold in root_law from tax_measures (no date — mark as 'current')
    for m in tax_measures:
        law = m.get("root_law")
        if not law or law in idx:
            continue
        idx[law] = {
            "law_id": law,
            "effective_date": None,
            "source_url": m.get("official_url"),
            "source_name": m.get("name"),
        }
    return idx


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@dataclass
class PrecomputedCache:
    computed_at: str
    source_versions: Dict[str, int]
    program_compat_closure: Dict[str, List[str]]
    program_incompat_closure: Dict[str, List[str]]
    program_prereq_closure: Dict[str, List[str]]
    authority_parent: Dict[str, Dict[str, str]]
    law_latest_amendment: Dict[str, dict]
    tax_measure_validity: Dict[str, dict]
    certification_unlocks: Dict[str, List[str]]
    # Flat edge log for audit / debugging
    edges: List[Dict[str, Any]] = field(default_factory=list)


def build_cache(as_of: date = TODAY) -> PrecomputedCache:
    excl = load_exclusion_rules()
    tax = load_tax_measures()
    certs = load_certifications()
    inv = load_invoice_rules()

    edges: List[Edge] = []
    edges.extend(build_edges_from_exclusions(excl))
    edges.extend(build_edges_from_tax_compat(tax))
    cert_edges, unlocks = build_edges_from_certifications(certs)
    edges.extend(cert_edges)

    # authority parent for every mention
    authority_mentions: Set[str] = set()
    for c in certs:
        if c.get("authority"):
            authority_mentions.add(c["authority"])
        if c.get("certifying_org"):
            authority_mentions.add(c["certifying_org"])
    for m in tax:
        for k in ("authority", "government_level", "target_taxpayer"):
            v = m.get(k)
            if isinstance(v, str):
                authority_mentions.add(v)
    authority_parent = {a: resolve_authority_parent(a) for a in sorted(authority_mentions)}

    return PrecomputedCache(
        computed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        source_versions={
            "exclusion_rules": len(excl),
            "tax_incentives": len(tax),
            "certification_programs": len(certs),
            "invoice_rules": len(inv),
        },
        program_compat_closure=transitive_closure(edges, "compatible"),
        program_incompat_closure=transitive_closure(edges, "incompatible"),
        program_prereq_closure=transitive_closure(edges, "prerequisite"),
        authority_parent=authority_parent,
        law_latest_amendment=build_law_amendment_index(inv, tax),
        tax_measure_validity=build_validity_index(tax, as_of=as_of),
        certification_unlocks=unlocks,
        edges=[asdict(e) for e in edges],
    )


def save_cache(cache: PrecomputedCache, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(asdict(cache), f, ensure_ascii=False, indent=2)


def load_cache(path: Path = CACHE_PATH) -> PrecomputedCache:
    if not path.exists():
        cache = build_cache()
        save_cache(cache, path)
        return cache
    with path.open() as f:
        raw = json.load(f)
    return PrecomputedCache(**raw)


# ---------------------------------------------------------------------------
# Pseudo-SQL upsert emitter (no real DB — another agent owns persistence)
# ---------------------------------------------------------------------------

def emit_upserts(cache: PrecomputedCache) -> List[str]:
    """Return SQL upsert statements (strings) that a downstream agent can replay.

    These are pseudo-SQL — syntactically valid SQLite but not executed here.
    """
    now = cache.computed_at
    stmts: List[str] = []

    def up(entity_type: str, entity_id: str, kind: str, payload: Any, source: str) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False).replace("'", "''")
        eid = entity_id.replace("'", "''")
        return (
            f"INSERT OR REPLACE INTO am_precomputed "
            f"(entity_type, entity_id, closure_kind, payload_json, computed_at, source_version) "
            f"VALUES ('{entity_type}', '{eid}', '{kind}', '{payload_json}', '{now}', '{source}');"
        )

    src_excl = f"2026-04-23-exclusion_rules:{cache.source_versions['exclusion_rules']}"
    src_tax = f"2026-04-23-tax_incentives:{cache.source_versions['tax_incentives']}"
    src_cert = f"2026-04-23-cert:{cache.source_versions['certification_programs']}"

    for pid, partners in cache.program_compat_closure.items():
        stmts.append(up("program", pid, "compat_closure", partners, src_excl))
    for pid, partners in cache.program_incompat_closure.items():
        stmts.append(up("program", pid, "incompat_closure", partners, src_excl))
    for pid, partners in cache.program_prereq_closure.items():
        stmts.append(up("program", pid, "prereq_closure", partners, src_cert))
    for auth, parent in cache.authority_parent.items():
        stmts.append(up("authority", auth, "authority_parent", parent, "hand-curated"))
    for lid, info in cache.law_latest_amendment.items():
        stmts.append(up("law", lid, "law_latest_amendment", info, "mixed"))
    for mid, info in cache.tax_measure_validity.items():
        stmts.append(up("tax_measure", mid, "validity_index", info, src_tax))
    for cid, progs in cache.certification_unlocks.items():
        stmts.append(up("certification", cid, "unlocks_programs", progs, src_cert))
    return stmts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    cache = build_cache()
    save_cache(cache)
    print(f"precomputed cache written -> {CACHE_PATH}")
    print(f"  sources            : {cache.source_versions}")
    print(f"  compat closures    : {len(cache.program_compat_closure)} programs")
    print(f"  incompat closures  : {len(cache.program_incompat_closure)} programs")
    print(f"  prereq closures    : {len(cache.program_prereq_closure)} programs")
    print(f"  authority parents  : {len(cache.authority_parent)}")
    print(f"  tax measure windows: {len(cache.tax_measure_validity)}")
    print(f"  cert unlocks       : {len(cache.certification_unlocks)}")
    print(f"  total edges        : {len(cache.edges)}")
    upserts = emit_upserts(cache)
    print(f"  SQL upsert count   : {len(upserts)} (schema only, not executed)")


if __name__ == "__main__":
    main()
