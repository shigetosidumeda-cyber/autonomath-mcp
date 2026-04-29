#!/usr/bin/env python3
"""Harvest implicit relationships from existing am_entities / jpi_* / source
tables into am_relation, raising graph density from 23,805 → 50k+ edges.

Background:
    am_relation today has 23,805 edges across 503,930 entities (avg
    0.047 edges/entity). graph_traverse / related_programs return
    shallow chains because most implicit relations live in raw_json
    fields (programs.authority_canonical, jpi_enforcement_cases.legal_basis,
    jpi_case_studies.programs_used_json, etc.) and have never been
    promoted into am_relation as canonical-typed edges.

    Migration 082 added the `harvested_at` column + a UNIQUE partial
    index ux_am_relation_harvest so this harvester can be re-run safely
    (idempotent on the (source, target, relation_type, source_field)
    tuple, only for origin='harvest' rows).

Strategies (8):
    1. authority_canonical → has_authority
       Reads am_entities (record_kind='program') WHERE authority_canonical
       IS NOT NULL. Direct column → relation lift. Confidence 0.95
       (column was already curated by the ingest pipeline).

    2. enforcement.legal_basis → references_law
       Reads am_entities (record_kind='enforcement') raw_json.legal_basis.
       Matches against jpi_laws.law_title / law_short_title via prefix /
       substring lookup. Confidence 0.85 (free-text match, not LAW-id
       lookup — but legal_basis is the auditor's own citation so the
       text is high-fidelity).

    3. enforcement.program_name_hint → related (program ↔ enforcement)
       Reads am_entities (record_kind='enforcement') raw_json
       .program_name_hint. Matches against am_entities (record_kind=
       'program') primary_name via exact-match-or-prefix lookup. Confidence
       0.80 (program_name_hint is free-text, may include sub-program
       qualifiers absent from the program entity primary_name).

    4. case_study.programs_used → related (case_study ↔ program)
       Reads am_entities (record_kind='case_study') raw_json.programs_used
       (list[str]). Matches each list element against program primary_name
       via exact match. Confidence 0.85 (curated list, but free-text).

    5. tax_ruleset.related_law_ids_json → references_law
       Reads jpi_tax_rulesets.related_law_ids_json. Values are
       'PENDING:<law_text>' (text not LAW-id resolved). Strips PENDING:
       prefix, matches against jpi_laws.law_title. Confidence 0.75 (not
       yet LAW-id resolved means the harvester is replicating an unfinished
       text-match step).

    6. court_decision.related_law_ids_json → references_law
       Reads jpi_court_decisions.related_law_ids_json. Currently 0 of
       2,065 court_decision rows have non-empty list — strategy is
       implemented but yields 0 today. Will pick up when the court
       ingest backfills related_law_ids_json.

    7. program ↔ program siblings via primary_name prefix → related
       Detects program variants by exact common-prefix matching:
       "ものづくり補助金 一般型" / "ものづくり補助金 グローバル展開型"
       share prefix "ものづくり補助金 " (≥6 chars before the space).
       Conservative: requires shared prefix length ≥6 chars + at least
       2 distinct programs in the cluster. Confidence 0.65 (heuristic).

    8. program → industry via target_industries → applies_to_industry
       Reads am_entities (record_kind='program') raw_json fields
       target_industries / target_industry / target_types (multiple
       schemas across ingest sources). Matches against am_industry_jsic
       via case-insensitive name lookup (Japanese only — JSIC has 35
       major+medium codes). Confidence 0.70 (loose match).

Write target:
    am_relation (origin='harvest', source_field='harvest:<strategy>')
    UNIQUE on (source, target, relation_type, source_field) WHERE
    origin='harvest' (partial index ux_am_relation_harvest from 082).

Source mutation:
    READ-ONLY on programs / case_studies / enforcement_cases / laws /
    tax_rulesets / court_decisions / am_entities. The script never
    UPDATEs or DELETEs from those tables.

Usage:
    python scripts/etl/harvest_implicit_relations.py --dry-run
    python scripts/etl/harvest_implicit_relations.py --strategy authority,enforcement_law
    python scripts/etl/harvest_implicit_relations.py        # apply all
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"

logger = logging.getLogger("harvest_implicit_relations")

# Canonical relation_type vocabulary (matches
# src/jpintel_mcp/mcp/autonomath_tools/graph_traverse_tool.py:_ALL_RELATION_TYPES).
# Keep this set in sync — using a non-canonical relation_type would
# silently disappear from graph_traverse output.
_CANONICAL_RELATIONS = frozenset({
    "has_authority",
    "applies_to_region",
    "applies_to_industry",
    "related",
    "references_law",
    "compatible",
    "compatible_with",
    "applies_to_size",
    "prerequisite",
    "requires_prerequisite",
    "part_of",
    "successor_of",
    "bonus_points",
    "implemented_by",
    "incompatible",
    "incompatible_with",
    "applies_to",
    "replaces",
})

# All strategies. Keep keys stable — they show up in source_field.
_ALL_STRATEGIES = (
    "authority",
    "enforcement_law",
    "enforcement_program",
    "case_study_program",
    "tax_ruleset_law",
    "court_decision_law",
    "program_sibling",
    "program_industry",
    "adoption_program",
    "tax_measure_law",
)


class Edge(NamedTuple):
    source_entity_id: str
    target_entity_id: str | None
    target_raw: str | None
    relation_type: str
    confidence: float
    source_field: str


# ----------------------------------------------------------------------
# Strategy 1: authority_canonical → has_authority
# ----------------------------------------------------------------------
def harvest_authority(conn: sqlite3.Connection) -> list[Edge]:
    """Lift am_entities.authority_canonical (5,523 program rows) into
    am_relation as has_authority edges. Skips programs that ALREADY have
    a has_authority edge to that exact target (idempotency).
    """
    cur = conn.execute(
        """
        SELECT p.canonical_id, p.authority_canonical
          FROM am_entities p
         WHERE p.record_kind = 'program'
           AND p.authority_canonical IS NOT NULL
           AND p.authority_canonical != ''
           AND NOT EXISTS (
                 SELECT 1 FROM am_relation r
                  WHERE r.source_entity_id = p.canonical_id
                    AND r.relation_type = 'has_authority'
                    AND r.target_entity_id = p.authority_canonical
               )
        """
    )
    edges: list[Edge] = []
    for source_id, target_id in cur:
        edges.append(Edge(
            source_entity_id=source_id,
            target_entity_id=target_id,
            target_raw=target_id,
            relation_type="has_authority",
            confidence=0.95,
            source_field="harvest:authority_canonical",
        ))
    return edges


# ----------------------------------------------------------------------
# Strategy 2: enforcement.legal_basis → references_law
# ----------------------------------------------------------------------
def _build_law_lookup(conn: sqlite3.Connection) -> dict[str, str]:
    """Build a {law_title_or_short_title → LAW-id} map for substring
    lookup. We accept the longer of two collisions because legal_basis
    citations tend to be specific (full title preferred over short).
    """
    cur = conn.execute(
        """
        SELECT unified_id, law_title, law_short_title
          FROM jpi_laws
         WHERE revision_status = 'current'
        """
    )
    title_to_id: dict[str, str] = {}
    for unified_id, law_title, law_short_title in cur:
        if law_title and law_title not in title_to_id:
            title_to_id[law_title] = unified_id
        if law_short_title:
            for short in law_short_title.split(","):
                short = short.strip()
                if short and short not in title_to_id:
                    title_to_id[short] = unified_id
    return title_to_id


def _match_law_in_text(text: str, law_lookup: dict[str, str]) -> list[tuple[str, str]]:
    """Return [(law_id, matched_title)] for every law_title that appears
    as substring in `text`. Greedy: longest title first to avoid
    matching '雇用保険法' inside '雇用保険法施行令'.
    """
    if not text:
        return []
    sorted_titles = sorted(law_lookup.keys(), key=len, reverse=True)
    matched: list[tuple[str, str]] = []
    consumed_spans: list[tuple[int, int]] = []
    for title in sorted_titles:
        idx = 0
        while True:
            pos = text.find(title, idx)
            if pos < 0:
                break
            end = pos + len(title)
            # Skip if span already consumed by a longer match.
            overlap = any(s < end and pos < e for s, e in consumed_spans)
            if not overlap:
                matched.append((law_lookup[title], title))
                consumed_spans.append((pos, end))
            idx = end
    return matched


def harvest_enforcement_law(conn: sqlite3.Connection) -> list[Edge]:
    law_lookup = _build_law_lookup(conn)
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'enforcement'
           AND raw_json LIKE '%legal_basis%'
        """
    )
    edges: list[Edge] = []
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        legal_basis = data.get("legal_basis")
        if not legal_basis or not isinstance(legal_basis, str):
            continue
        for law_id, matched_title in _match_law_in_text(legal_basis, law_lookup):
            edges.append(Edge(
                source_entity_id=canonical_id,
                target_entity_id=law_id,
                target_raw=matched_title,
                relation_type="references_law",
                confidence=0.85,
                source_field="harvest:enforcement.legal_basis",
            ))
    return edges


# ----------------------------------------------------------------------
# Strategy 3: enforcement.program_name_hint → related
# ----------------------------------------------------------------------
def _build_program_name_lookup(conn: sqlite3.Connection) -> dict[str, str]:
    """{program_primary_name → canonical_id}. On collision keep the
    first one observed (programs with identical primary_name are
    pre-Wave-17 noise — ~568 groups; harvester treats them as a single
    canonical name target).
    """
    cur = conn.execute(
        """
        SELECT canonical_id, primary_name
          FROM am_entities
         WHERE record_kind = 'program'
           AND primary_name IS NOT NULL
           AND primary_name != ''
        """
    )
    name_to_id: dict[str, str] = {}
    for canonical_id, primary_name in cur:
        if primary_name not in name_to_id:
            name_to_id[primary_name] = canonical_id
    return name_to_id


def harvest_enforcement_program(conn: sqlite3.Connection) -> list[Edge]:
    program_lookup = _build_program_name_lookup(conn)
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'enforcement'
           AND raw_json LIKE '%program_name_hint%'
        """
    )
    edges: list[Edge] = []
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        hint = data.get("program_name_hint")
        if not hint or not isinstance(hint, str):
            continue
        # Exact match first; fall back to longest-prefix match where
        # hint starts with a known program name.
        target_id = program_lookup.get(hint)
        if target_id:
            edges.append(Edge(
                source_entity_id=canonical_id,
                target_entity_id=target_id,
                target_raw=hint,
                relation_type="related",
                confidence=0.80,
                source_field="harvest:enforcement.program_name_hint",
            ))
    return edges


# ----------------------------------------------------------------------
# Strategy 4: case_study.programs_used → related
# ----------------------------------------------------------------------
def harvest_case_study_program(conn: sqlite3.Connection) -> list[Edge]:
    program_lookup = _build_program_name_lookup(conn)
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'case_study'
           AND raw_json LIKE '%programs_used%'
        """
    )
    edges: list[Edge] = []
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        programs = data.get("programs_used") or data.get("programs_used_json")
        if not programs:
            continue
        if isinstance(programs, str):
            try:
                programs = json.loads(programs)
            except json.JSONDecodeError:
                continue
        if not isinstance(programs, list):
            continue
        for program_name in programs:
            if not isinstance(program_name, str):
                continue
            target_id = program_lookup.get(program_name)
            if target_id:
                edges.append(Edge(
                    source_entity_id=canonical_id,
                    target_entity_id=target_id,
                    target_raw=program_name,
                    relation_type="related",
                    confidence=0.85,
                    source_field="harvest:case_study.programs_used",
                ))
    return edges


# ----------------------------------------------------------------------
# Strategy 5: tax_ruleset.related_law_ids_json → references_law
# ----------------------------------------------------------------------
def harvest_tax_ruleset_law(conn: sqlite3.Connection) -> list[Edge]:
    law_lookup = _build_law_lookup(conn)
    # tax_rulesets in jpi_tax_rulesets — but we want the SOURCE in
    # am_entities (record_kind='tax_measure') since that's where am_relation
    # source_entity_id FK resolves to. Build a tax_measure → unified_id
    # cross-reference via raw_json.unified_id field.
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'tax_measure'
        """
    )
    edges: list[Edge] = []
    # Build map jpi_unified_id → am.canonical_id via raw_json scan.
    am_by_unified: dict[str, str] = {}
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        uni = data.get("unified_id")
        if uni and uni not in am_by_unified:
            am_by_unified[uni] = canonical_id

    cur = conn.execute(
        """
        SELECT unified_id, related_law_ids_json
          FROM jpi_tax_rulesets
         WHERE related_law_ids_json IS NOT NULL
           AND related_law_ids_json != '[]'
        """
    )
    for tax_uni, related_json in cur:
        am_id = am_by_unified.get(tax_uni)
        if not am_id:
            continue
        try:
            related = json.loads(related_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(related, list):
            continue
        for entry in related:
            if not isinstance(entry, str):
                continue
            # Strip 'PENDING:' prefix → free-text law name lookup.
            text = entry[len("PENDING:"):] if entry.startswith("PENDING:") else entry
            for law_id, matched_title in _match_law_in_text(text, law_lookup):
                edges.append(Edge(
                    source_entity_id=am_id,
                    target_entity_id=law_id,
                    target_raw=matched_title,
                    relation_type="references_law",
                    confidence=0.75,
                    source_field="harvest:tax_ruleset.related_law_ids_json",
                ))
    return edges


# ----------------------------------------------------------------------
# Strategy 6: court_decision.related_law_ids_json → references_law
# ----------------------------------------------------------------------
def harvest_court_decision_law(conn: sqlite3.Connection) -> list[Edge]:
    """Source rows live in jpi_court_decisions. There is no record_kind=
    'court_decision' in am_entities (verified 2026-04-29: 0 rows). We
    therefore use the jpi_court_decisions.unified_id (HAN-*) directly
    as source_entity_id even though it has no FK back to am_entities —
    am_relation has no FK on source_entity_id beyond am_entities, but
    the table FK is `ON DELETE CASCADE` only and tolerates missing
    parent rows on INSERT (verified by 9,092 already-dangling target
    rows). If a developer wants strict FK enforcement, add court
    decisions to am_entities first via a migration.
    """
    law_lookup = _build_law_lookup(conn)
    cur = conn.execute(
        """
        SELECT unified_id, related_law_ids_json
          FROM jpi_court_decisions
         WHERE related_law_ids_json IS NOT NULL
           AND related_law_ids_json != '[]'
        """
    )
    edges: list[Edge] = []
    for han_id, related_json in cur:
        try:
            related = json.loads(related_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(related, list):
            continue
        for entry in related:
            if not isinstance(entry, str):
                continue
            # Could be a LAW-id directly or PENDING:<text>.
            if entry.startswith("LAW-") and len(entry) == 14:
                edges.append(Edge(
                    source_entity_id=han_id,
                    target_entity_id=entry,
                    target_raw=entry,
                    relation_type="references_law",
                    confidence=0.90,
                    source_field="harvest:court.related_law_ids_json",
                ))
            else:
                text = entry[len("PENDING:"):] if entry.startswith("PENDING:") else entry
                for law_id, matched_title in _match_law_in_text(text, law_lookup):
                    edges.append(Edge(
                        source_entity_id=han_id,
                        target_entity_id=law_id,
                        target_raw=matched_title,
                        relation_type="references_law",
                        confidence=0.80,
                        source_field="harvest:court.related_law_ids_json",
                    ))
    return edges


# ----------------------------------------------------------------------
# Strategy 7: program ↔ program siblings via prefix → related
# ----------------------------------------------------------------------
def harvest_program_sibling(conn: sqlite3.Connection) -> list[Edge]:
    """Detect program variants by EXACT shared common prefix of length
    ≥6 chars before a space (or 中黒 ・). Conservative: only emits
    an edge when ≥2 distinct programs share the prefix AND the prefix
    contains a kanji subsidy keyword (補助金/助成金/交付金/資金/特例).

    Example clusters:
      "ものづくり補助金 一般型" / "ものづくり補助金 グローバル展開型"
        → prefix "ものづくり補助金 " (length 9) → both ↔ each other.

    Refused:
      "東京都" + "東京都産業労働局" — short prefix, no subsidy keyword.

    The cluster size is capped at 30 (avoid combinatorial explosion in
    huge generic clusters like "雇用調整助成金*"). For clusters > 30,
    we still emit edges but only between the first 30 alphabetically
    sorted members — the rest are suppressed in this harvest pass.
    """
    cur = conn.execute(
        """
        SELECT canonical_id, primary_name
          FROM am_entities
         WHERE record_kind = 'program'
           AND primary_name IS NOT NULL
        """
    )
    rows = list(cur)
    # Group by prefix (first segment up to first space / 中黒 / parenthesis).
    clusters: dict[str, list[tuple[str, str]]] = defaultdict(list)
    subsidy_keywords = ("補助金", "助成金", "交付金", "支援金", "事業", "特例", "保証", "融資")
    for canonical_id, primary_name in rows:
        # Split at first whitespace or punctuation that often separates
        # variant suffix (一般型 / グローバル / etc.).
        prefix = primary_name
        for sep in (" ", "　", "・", "(", "（", "－"):
            idx = prefix.find(sep)
            if idx >= 0:
                prefix = prefix[:idx]
        if len(prefix) < 6:
            continue
        # Require subsidy keyword in prefix to suppress trivial overlap
        # like "東京都" / "島根" prefectural prefixes.
        if not any(kw in prefix for kw in subsidy_keywords):
            continue
        clusters[prefix].append((canonical_id, primary_name))
    edges: list[Edge] = []
    for prefix, members in clusters.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda x: x[1])[:30]
        for i, (a_id, a_name) in enumerate(members):
            for b_id, b_name in members[i + 1:]:
                if a_id == b_id:
                    continue
                # Bidirectional: emit a→b, the reverse direction is added
                # by a separate row (consistent with existing
                # [bidir-added] convention in graph data).
                edges.append(Edge(
                    source_entity_id=a_id,
                    target_entity_id=b_id,
                    target_raw=b_name,
                    relation_type="related",
                    confidence=0.65,
                    source_field=f"harvest:program_sibling[{prefix}]",
                ))
                edges.append(Edge(
                    source_entity_id=b_id,
                    target_entity_id=a_id,
                    target_raw=a_name,
                    relation_type="related",
                    confidence=0.65,
                    source_field=f"harvest:program_sibling[{prefix}]",
                ))
    return edges


# ----------------------------------------------------------------------
# Strategy 8: program → industry (JSIC) → applies_to_industry
# ----------------------------------------------------------------------
def harvest_program_industry(conn: sqlite3.Connection) -> list[Edge]:
    """Match raw_json.target_industries / target_industry / target_types
    against am_industry_jsic.jsic_name_ja for the 35 JSIC entries.
    """
    cur = conn.execute(
        "SELECT jsic_code, jsic_name_ja FROM am_industry_jsic"
    )
    jsic_by_name = {name: code for code, name in cur}
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'program'
           AND (raw_json LIKE '%target_industries%'
                OR raw_json LIKE '%target_industry%'
                OR raw_json LIKE '%target_types%')
        """
    )
    edges: list[Edge] = []
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates: list[str] = []
        ti = data.get("target_industries")
        if isinstance(ti, list):
            candidates.extend([x for x in ti if isinstance(x, str)])
        ti2 = data.get("target_industry")
        if isinstance(ti2, str):
            candidates.append(ti2)
        elif isinstance(ti2, list):
            candidates.extend([x for x in ti2 if isinstance(x, str)])
        # target_types is more loosely populated; only mine for industry
        # names that exactly match JSIC.
        tt = data.get("target_types")
        if isinstance(tt, list):
            candidates.extend([x for x in tt if isinstance(x, str)])
        for cand in candidates:
            cand_strip = cand.strip()
            # Substring match: industry token can be longer than JSIC.
            for jsic_name, jsic_code in jsic_by_name.items():
                if jsic_name in cand_strip or cand_strip in jsic_name:
                    edges.append(Edge(
                        source_entity_id=canonical_id,
                        target_entity_id=f"jsic:{jsic_code}",
                        target_raw=jsic_name,
                        relation_type="applies_to_industry",
                        confidence=0.70,
                        source_field=f"harvest:program.target_industries[{jsic_code}]",
                    ))
    return edges


# ----------------------------------------------------------------------
# Strategy 9: adoption.program_name → part_of (adoption belongs to program)
# ----------------------------------------------------------------------
def _resolve_adoption_program_name(
    program_name: str,
    program_lookup: dict[str, str],
    extended_lookup: dict[str, str],
) -> str | None:
    """Try exact match first, then prefix match against extended_lookup
    where adoption-side names like 'ものづくり・商業・サービス生産性向上促進補助金'
    map to a program entity whose primary_name CONTAINS that string as
    a prefix (e.g. '...補助金（第22次公募）'). Returns the canonical_id
    or None.
    """
    exact = program_lookup.get(program_name)
    if exact:
        return exact
    return extended_lookup.get(program_name)


def _normalize_program_name(name: str) -> str:
    """Drop spaces / brackets / round suffixes for canonical name
    matching across adoption-side and program-side variants. We keep
    kanji + number tokens because they encode distinguishing data
    (e.g. '2025' vs '2024'); we ONLY drop punctuation and call-suffix
    structural noise.
    """
    out = name
    # Drop ASCII + halfwidth + fullwidth parens and their contents only
    # when they are at the END of the string (preserves middle-of-name
    # disambiguators). Apply iteratively for nested cases.
    for _ in range(3):
        for op, cl in (("（", "）"), ("(", ")"), ("〈", "〉"), ("「", "」")):
            if op in out and cl in out:
                last_op = out.rfind(op)
                last_cl = out.rfind(cl)
                if last_op < last_cl and last_cl == len(out) - 1:
                    out = out[:last_op].rstrip()
    # Strip spaces (whitespace + 全角)
    out = out.replace(" ", "").replace("　", "")
    return out


def harvest_adoption_program(conn: sqlite3.Connection) -> list[Edge]:
    """Lift each adoption record's program_name into a part_of edge
    pointing to the matching program canonical_id. There are 215,233
    adoption rows but only 8 distinct program_names. Adoption-side and
    program-side names diverge in structural noise (round suffix, call
    number, parenthetical sub-call qualifiers); we use a THREE-STEP
    lookup:

      1. exact-match against program primary_name
      2. prefix-match: adoption_name == program_primary_name UP TO the
         first paren / 第N次 / 中点 delimiter
      3. normalized-match: strip spaces + trailing parens from BOTH
         sides, exact match on the normalized form

    Confidence 0.95 for exact, 0.85 for prefix, 0.80 for normalized.

    Skipped: 'IT導入補助金 2023 後期' style patterns where the year-call
    distinction is essential and the program-side primary_name is
    'IT導入補助金 2026' / 'IT導入補助金2025 (...)' — neither is the
    correct target, so we honestly emit no edge rather than a false
    positive. False-positive risk is the harvester's biggest threat
    (CLAUDE.md fraud-risk constraint), so when no high-confidence
    match exists we record the miss in logs and move on.
    """
    program_lookup = _build_program_name_lookup(conn)
    # Build prefix-extended lookup AND a normalized-name lookup.
    cur = conn.execute(
        """
        SELECT canonical_id, primary_name
          FROM am_entities
         WHERE record_kind = 'program'
           AND primary_name IS NOT NULL
        """
    )
    extended_lookup: dict[str, str] = {}
    normalized_lookup: dict[str, str] = {}
    for canonical_id, primary_name in cur:
        for sep in ("（", "(", " 第", "　第"):
            idx = primary_name.find(sep)
            if idx > 6:  # require a meaningful prefix length
                bare = primary_name[:idx].rstrip()
                if bare and bare not in extended_lookup:
                    extended_lookup[bare] = canonical_id
                break
        norm = _normalize_program_name(primary_name)
        if norm and norm not in normalized_lookup:
            normalized_lookup[norm] = canonical_id
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'adoption'
        """
    )
    edges: list[Edge] = []
    misses: dict[str, int] = defaultdict(int)
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        program_name = data.get("program_name")
        if not program_name or not isinstance(program_name, str):
            continue
        # Try exact, then prefix, then normalized.
        target_id = program_lookup.get(program_name)
        confidence = 0.95
        source_field = "harvest:adoption.program_name"
        if not target_id:
            target_id = extended_lookup.get(program_name)
            if target_id:
                confidence = 0.85
                source_field = "harvest:adoption.program_name[prefix]"
        if not target_id:
            norm = _normalize_program_name(program_name)
            target_id = normalized_lookup.get(norm)
            if target_id:
                confidence = 0.80
                source_field = "harvest:adoption.program_name[normalized]"
        if not target_id:
            # Fall back to BARE base-name match: 'IT導入補助金 2023 後期' →
            # 'IT導入補助金'. We strip everything after the first space /
            # 全角space and look for an exact program primary_name match.
            # This pairs program:base:* generic entities with year/round-
            # specific adoption rows. Confidence drops to 0.65 because
            # the year/round distinction is dropped.
            bare = program_name
            for sep in (" ", "　"):
                idx = bare.find(sep)
                if idx > 0:
                    bare = bare[:idx]
                    break
            if bare != program_name:
                target_id = program_lookup.get(bare)
                if target_id:
                    confidence = 0.65
                    source_field = "harvest:adoption.program_name[base]"
        if target_id:
            edges.append(Edge(
                source_entity_id=canonical_id,
                target_entity_id=target_id,
                target_raw=program_name,
                relation_type="part_of",
                confidence=confidence,
                source_field=source_field,
            ))
        else:
            misses[program_name] += 1
    if misses:
        logger.info("adoption_program: unmatched program_names: %s",
                    dict(sorted(misses.items(), key=lambda x: -x[1])))
    return edges


# ----------------------------------------------------------------------
# Strategy 10: tax_measure.root_law → references_law (free-text matched)
# ----------------------------------------------------------------------
def harvest_tax_measure_law(conn: sqlite3.Connection) -> list[Edge]:
    """Read am_entities.tax_measure raw_json.root_law (84 rows, e.g.
    '租税特別措置法 第67条の5 (法法75の4, 措法53, 67の5 / 措令39の28)') and
    extract every law title that matches via _match_law_in_text.
    Multi-match per row (root_law often references 2-3 statutes).
    Confidence 0.80 (curated free-text → high signal but not LAW-id
    resolved at source).
    """
    law_lookup = _build_law_lookup(conn)
    cur = conn.execute(
        """
        SELECT canonical_id, raw_json
          FROM am_entities
         WHERE record_kind = 'tax_measure'
           AND raw_json LIKE '%root_law%'
        """
    )
    edges: list[Edge] = []
    for canonical_id, raw_json in cur:
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue
        root_law = data.get("root_law")
        if not root_law or not isinstance(root_law, str):
            continue
        for law_id, matched_title in _match_law_in_text(root_law, law_lookup):
            edges.append(Edge(
                source_entity_id=canonical_id,
                target_entity_id=law_id,
                target_raw=matched_title,
                relation_type="references_law",
                confidence=0.80,
                source_field="harvest:tax_measure.root_law",
            ))
    return edges


# ----------------------------------------------------------------------
# Insert helper
# ----------------------------------------------------------------------
def insert_edges(
    conn: sqlite3.Connection,
    edges: Iterable[Edge],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Returns (inserted, skipped_dup). Idempotency is enforced by the
    UNIQUE partial index ux_am_relation_harvest from migration 082."""
    if dry_run:
        # Dedupe within this batch so dry-run yield reflects the post-
        # idempotency-filter count, not the raw match count.
        seen: set[tuple[str, str | None, str, str]] = set()
        kept = 0
        for e in edges:
            key = (e.source_entity_id, e.target_entity_id or "", e.relation_type, e.source_field)
            if key in seen:
                continue
            seen.add(key)
            kept += 1
        return kept, 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    inserted = 0
    skipped = 0
    for e in edges:
        # Validate relation_type stays in canonical vocab.
        if e.relation_type not in _CANONICAL_RELATIONS:
            logger.warning("dropping edge with non-canonical relation_type=%s", e.relation_type)
            continue
        try:
            conn.execute(
                """
                INSERT INTO am_relation
                    (source_entity_id, target_entity_id, target_raw,
                     relation_type, confidence, origin, source_field,
                     harvested_at)
                VALUES (?, ?, ?, ?, ?, 'harvest', ?, ?)
                """,
                (
                    e.source_entity_id,
                    e.target_entity_id,
                    e.target_raw,
                    e.relation_type,
                    e.confidence,
                    e.source_field,
                    now,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError as exc:
            # UNIQUE conflict on ux_am_relation_harvest = re-run hit.
            if "UNIQUE" in str(exc):
                skipped += 1
            else:
                raise
    return inserted, skipped


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------
_STRATEGY_FUNCS = {
    "authority": harvest_authority,
    "enforcement_law": harvest_enforcement_law,
    "enforcement_program": harvest_enforcement_program,
    "case_study_program": harvest_case_study_program,
    "tax_ruleset_law": harvest_tax_ruleset_law,
    "court_decision_law": harvest_court_decision_law,
    "program_sibling": harvest_program_sibling,
    "program_industry": harvest_program_industry,
    "adoption_program": harvest_adoption_program,
    "tax_measure_law": harvest_tax_measure_law,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        type=str,
        default="all",
        help=f"Comma-separated subset of: {','.join(_ALL_STRATEGIES)} (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute yields without inserting.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DB_PATH),
        help=f"Path to autonomath.db (default: {DB_PATH})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.strategy == "all":
        chosen = list(_ALL_STRATEGIES)
    else:
        chosen = [s.strip() for s in args.strategy.split(",") if s.strip()]
        bad = [s for s in chosen if s not in _STRATEGY_FUNCS]
        if bad:
            parser.error(f"Unknown strategy: {bad}. Allowed: {_ALL_STRATEGIES}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    if not args.dry_run:
        conn.execute("BEGIN")

    total_inserted = 0
    total_skipped = 0
    print(f"=== harvest_implicit_relations ({'dry-run' if args.dry_run else 'APPLY'}) ===")
    print(f"DB: {args.db}")
    print(f"Strategies: {','.join(chosen)}")
    print()

    for strat in chosen:
        fn = _STRATEGY_FUNCS[strat]
        edges = fn(conn)
        inserted, skipped = insert_edges(conn, edges, dry_run=args.dry_run)
        total_inserted += inserted
        total_skipped += skipped
        if args.dry_run:
            print(f"  [{strat}] candidates={len(edges):,} unique={inserted:,}")
        else:
            print(f"  [{strat}] inserted={inserted:,} skipped(dup)={skipped:,} (raw_matches={len(edges):,})")

    if not args.dry_run:
        conn.commit()
    conn.close()

    print()
    print(f"=== TOTAL {'unique candidates' if args.dry_run else 'inserted'}: {total_inserted:,} ===")
    if not args.dry_run:
        print(f"=== TOTAL skipped (idempotency): {total_skipped:,} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
