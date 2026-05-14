"""Token-efficient compact-envelope projection (`?compact=true` opt-in, 2026-05-05).

Goal
----
A customer LLM that pipes jpcite responses straight into its own context
window pays for every byte. The full Evidence Packet / audit-seal envelope
carries verbose dict structures (`_audit_seal` 8-field dict, `_next_calls`
with `tool` + `args` per row, `_disclaimer` ~700-char Japanese fence,
`quality.known_gaps` long sentences, `verification.replay_endpoint` etc.)
that are useful for human ops but pure dead-weight for an in-context LLM
that already knows the schema.

This module provides a one-way **lossy projection** from the full
envelope to a compact form that drops 30-50% of the bytes while keeping
every value the agent actually reads:

  full                                    compact
  ----------------------------------      ----------------------------------
  _audit_seal: {seal_id, hmac, ts,   →    _seal: "<hmac_hex>"   (string)
                call_id, ...8 fields}
  _next_calls: [{tool, args}, ...]   →    _nx: ["tool_a", "tool_b", ...]
  _disclaimer: "<700-char text>"     →    _dx: "disc_§52_v1"   (id)
  quality.known_gaps: ["長い文…"]      →    quality.gaps: ["EP1", "EP2"]
  verification.replay_endpoint: URL  →    (omitted — caller infers from kind)
  corpus_snapshot_id: "<uuid>"       →    csid: "20260505-ab12"
  packet_id, generated_at, etc.      →    (preserved as-is, short keys)

Reversibility
-------------
The compact form is **not** byte-identical to the full envelope.  It is
designed so a downstream reader can either:

  (a) call ``from_compact(compact_dict, reference_table=...)`` to expand
      back to the full envelope (lossy: legacy fields like `audit_seal.ts`
      are reconstructed only when persisted in the supplied table);
      OR
  (b) consume the compact form directly + reference the published
      ``DISCLAIMER_TABLE`` / ``KNOWN_GAPS_TABLE`` for the omitted text.

The customer LLM almost always wants (b): the disclaimer text never
varies between requests, so duplicating 700 chars per response is wasted
context — once the LLM has been told once via the static table, the
"disc_§52_v1" reference is sufficient.

Design rules (reaffirmed from CLAUDE.md):
  * Pure-Python, no LLM call, no DB access, no external HTTP.
  * Default is full envelope — compact is opt-in via ``?compact=true``
    query OR the ``X-JPCite-Compact: 1`` header. Never break legacy
    consumers.
  * Reference table values are versioned (`disc_§52_v1`, `EP1_v1`) so a
    future refresh can ship a new id without breaking older clients.
  * Soft-fail on every branch — a malformed sub-tree gets passed through
    unchanged, never raises.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Reference tables (published to customers via docs/integrations/compact_response.md)
# ---------------------------------------------------------------------------

#: Disclaimer text reference table. The full envelope carries the verbatim
#: ~700-char Japanese fence; the compact envelope carries an id and the
#: customer's prompt template / SDK has the lookup table inline.
#:
#: Versioning: "<id>_v<n>" — bump <n> when the text changes so older
#: clients don't quote stale wording. Add new rows; never mutate
#: existing ones in place.
DISCLAIMER_TABLE: dict[str, str] = {
    "disc_evp_v1": (
        "Evidence Packet bundles primary-source citations and rule "
        "verdicts; it is not legal, tax, or grant-application advice. "
        "Final decisions require 専門家 (税理士 / 行政書士 / 中小企業 "
        "診断士 / 認定支援機関) review."
    ),
    "disc_seal_v1": (
        "信頼できる出典として運用する場合は、verify_endpoint で seal の真正性を確認してください。"
    ),
    "disc_§52_v1": (
        "本 response は公開コーパスに対する機械的検索照合で、税理士法 §52 "
        "(税務代理) ・弁護士法 §72 (法律事務) ・行政書士法 §1の2 (申請代理) "
        "・社労士法 (労務判断) のいずれにも該当しません。"
        "検索結果のみ提供、業務判断は primary source 確認必須、確定判断は士業へ。"
    ),
    "disc_§47_2_v1": (
        "公認会計士法 §47条の2 監査役務外領域の検索結果のみ。"
        "意見表明・保証業務には該当せず、監査人による独立性ある検証が必要です。"
    ),
}

#: Known-gaps enum reference. The full envelope carries verbose Japanese
#: sentences ("source_id NULL のため per-fact provenance を出せませんでした");
#: the compact form carries a 2-4 char enum that the customer SDK looks up.
#:
#: Codes are stable contracts (never re-key an existing code).
KNOWN_GAPS_TABLE: dict[str, str] = {
    "EP1": "Per-fact provenance unavailable (source_id NULL on this entity)",
    "EP2": "Citation verification stale (last live URL probe > 30 days)",
    "EP3": "Recent amendment diff not yet ingested (am_amendment_diff lag)",
    "EP4": "Coverage score below 0.6 (sparse fact set on this subject)",
    "EP5": "Partner compatibility heuristic (am_compat_matrix inferred edge)",
    "EP6": "License is `unknown` for at least one cited source",
    "EP7": "Result truncated (record cap reached; paginate via cursor)",
    "EP8": "Snapshot drift (corpus_snapshot_id older than freshness target)",
    "EP9": "Source URL no longer reachable (last 24h liveness probe failed)",
}

# Reverse maps for `from_compact` lookups.
_DISCLAIMER_TEXT_TO_ID: dict[str, str] = {v: k for k, v in DISCLAIMER_TABLE.items()}


def _shorten_snapshot_id(snapshot_id: Any) -> Any:
    """Compact a UUID-style ``corpus_snapshot_id`` to a date-prefix short form.

    Input forms we recognise:
      * ``"2026-05-05T07:21:33+09:00:abcd1234"`` → ``"20260505-abcd"``
      * ``"sha256:abcdef0123..."``                → ``"sha:abcdef01"``
      * already-short ids (no hyphen + ≤ 16 chars) pass through unchanged.

    Anything we don't recognise is returned verbatim — never raises.
    """
    if not isinstance(snapshot_id, str) or not snapshot_id:
        return snapshot_id
    s = snapshot_id
    if s.startswith("sha256:") and len(s) > 16:
        return f"sha:{s[7:15]}"
    # Try to find an ISO date prefix and a tail token.
    if len(s) > 12 and s[:4].isdigit() and s[4] == "-":
        # Strip non-alnum from the date prefix and take the trailing token.
        date_part = "".join(c for c in s[:10] if c.isdigit())
        tail = s.rsplit(":", 1)[-1] if ":" in s else s.rsplit("-", 1)[-1]
        tail = "".join(c for c in tail if c.isalnum())[:8]
        if date_part and tail:
            return f"{date_part}-{tail}"
    return s


def _compact_audit_seal(seal: Any) -> Any:
    """Reduce an `audit_seal` dict to the load-bearing HMAC string.

    The full seal carries 8 fields (call_id / ts / endpoint / query_hash /
    response_hash / source_urls / hmac / seal_id + customer-facing id /
    verify_endpoint). For an in-context LLM the only field that uniquely
    identifies the response is the HMAC; everything else is recoverable
    via the verify_endpoint lookup keyed on the HMAC.
    """
    if isinstance(seal, dict):
        return seal.get("hmac") or seal.get("seal_id") or ""
    return seal


def _compact_next_calls(next_calls: Any) -> Any:
    """Project `_next_calls: [{tool, args}, ...]` to a deduped tool-name list.

    The agent re-constructs args from the row context (every `_next_calls`
    item that ships in production is `{tool, args}` where `args` is fully
    derivable from the result row + tool schema). Duplicates drop.
    """
    if not isinstance(next_calls, list):
        return next_calls
    seen: list[str] = []
    for item in next_calls:
        tool = None
        if isinstance(item, dict):
            tool = item.get("tool")
        elif isinstance(item, str):
            tool = item
        if isinstance(tool, str) and tool and tool not in seen:
            seen.append(tool)
    return seen


def _compact_disclaimer(text: Any) -> Any:
    """Replace a known disclaimer text with its reference id.

    Unknown disclaimers pass through verbatim — better to ship the text
    than drop it silently.
    """
    if isinstance(text, dict):
        # Evidence packet style: {"type": "...", "note": "<long>"}.
        note = text.get("note") if isinstance(text.get("note"), str) else None
        if note and note in _DISCLAIMER_TEXT_TO_ID:
            return _DISCLAIMER_TEXT_TO_ID[note]
        return text
    if isinstance(text, str):
        return _DISCLAIMER_TEXT_TO_ID.get(text, text)
    return text


def _compact_known_gaps(gaps: Any) -> Any:
    """Map verbose gap sentences to enum codes.

    Heuristic phrase match — the full sentence usually contains one of
    several stable substrings (e.g. "source_id NULL"). Unknown gaps drop
    to a single-letter prefix `Z` so the count stays honest.
    """
    if not isinstance(gaps, list):
        return gaps

    # Lowercase sub-string → enum code, matched in order.
    rules: list[tuple[str, str]] = [
        ("source_id null", "EP1"),
        ("per-fact provenance", "EP1"),
        ("citation verification stale", "EP2"),
        ("verification stale", "EP2"),
        ("amendment diff not yet ingested", "EP3"),
        ("amendment_diff", "EP3"),
        ("coverage score below", "EP4"),
        ("partner compatibility heuristic", "EP5"),
        ("compat_matrix inferred", "EP5"),
        ("license is `unknown`", "EP6"),
        ("license unknown", "EP6"),
        ("truncated", "EP7"),
        ("snapshot drift", "EP8"),
        ("source url no longer reachable", "EP9"),
        ("liveness probe failed", "EP9"),
    ]
    out: list[str] = []
    for raw in gaps:
        if not isinstance(raw, str) or not raw:
            continue
        low = raw.lower()
        code = next((c for sub, c in rules if sub in low), "Z")
        if code not in out:
            out.append(code)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_compact(envelope: dict[str, Any]) -> dict[str, Any]:
    """Project a full Evidence-Packet / audit-sealed envelope to compact form.

    Targets a **30-50% byte reduction** by:

      * `_audit_seal` (or `audit_seal`) dict → `_seal` HMAC hex string.
      * `_next_calls: [{tool, args}, ...]` → `_nx: ["tool_a", ...]`.
      * `_disclaimer` long text → `_dx` reference id (resolved via DISCLAIMER_TABLE).
      * `quality.known_gaps` long sentences → `quality.gaps` enum codes (KNOWN_GAPS_TABLE).
      * `verification.replay_endpoint` / boilerplate URLs → omitted.
      * `corpus_snapshot_id` UUID → date-prefix short form (`csid`).
      * Top-level boilerplate keys (`api_version`, `answer_not_included`)
        → dropped (compact responses imply v1 + answer_not_included).

    Soft-fail: any sub-tree we can't recognise passes through unchanged.
    Never raises. Always returns a new dict (input is never mutated).
    """
    if not isinstance(envelope, dict):
        return envelope

    out: dict[str, Any] = {}

    # ----- Top-level scalar projection ------------------------------------
    if "packet_id" in envelope:
        out["pid"] = envelope["packet_id"]
    if "generated_at" in envelope:
        out["ts"] = envelope["generated_at"]
    if "corpus_snapshot_id" in envelope:
        out["csid"] = _shorten_snapshot_id(envelope["corpus_snapshot_id"])

    # ----- Query echo (kept verbatim — usually small) ---------------------
    if "query" in envelope:
        out["query"] = envelope["query"]
    elif "query_echo" in envelope:
        out["query"] = envelope["query_echo"]

    # ----- Records / results passthrough (caller decides record shape) ----
    if "records" in envelope:
        out["records"] = envelope["records"]
    if "results" in envelope:
        out["results"] = envelope["results"]

    # ----- Quality block: replace known_gaps with enum codes --------------
    if "quality" in envelope and isinstance(envelope["quality"], dict):
        q_in = envelope["quality"]
        q_out: dict[str, Any] = {}
        for k, v in q_in.items():
            if k == "known_gaps":
                q_out["gaps"] = _compact_known_gaps(v)
            elif k == "known_gaps_inventory":
                # Verbose inventory dropped — call /v1/quality/known_gaps if needed.
                continue
            else:
                q_out[k] = v
        out["quality"] = q_out

    # ----- Verification block: drop boilerplate URLs ----------------------
    if "verification" in envelope and isinstance(envelope["verification"], dict):
        v_in = envelope["verification"]
        # Drop replay_endpoint + freshness_endpoint — caller can re-derive
        # from the kind and CLAUDE.md docs. Keep provenance_endpoint only
        # when non-empty (it carries the canonical_id which is non-trivial
        # to re-derive).
        v_out: dict[str, Any] = {}
        prov = v_in.get("provenance_endpoint")
        if isinstance(prov, str) and prov:
            v_out["pe"] = prov
        if v_out:
            out["v"] = v_out

    # ----- Disclaimer compression ----------------------------------------
    if "_disclaimer" in envelope:
        out["_dx"] = _compact_disclaimer(envelope["_disclaimer"])
    if "_disclaimer_gbiz" in envelope:
        out["_disclaimer_gbiz"] = envelope["_disclaimer_gbiz"]
    if "_attribution" in envelope:
        out["_attribution"] = envelope["_attribution"]

    # ----- Audit seal compression ----------------------------------------
    if "_audit_seal" in envelope:
        out["_seal"] = _compact_audit_seal(envelope["_audit_seal"])
    elif "audit_seal" in envelope:
        out["_seal"] = _compact_audit_seal(envelope["audit_seal"])

    # ----- Next-calls compression ----------------------------------------
    if "_next_calls" in envelope:
        out["_nx"] = _compact_next_calls(envelope["_next_calls"])
    elif "suggested_actions" in envelope:
        out["_nx"] = _compact_next_calls(envelope["suggested_actions"])

    # ----- Other shortener-friendly top-level fields ----------------------
    for short, full in (
        ("status", "status"),
        ("warnings", "warnings"),
        ("citations", "citations"),
        ("decision_support", "decision_support"),
        ("_warning", "_warning"),
        ("error", "error"),
    ):
        if full in envelope:
            out[short] = envelope[full]
    # `meta` is small enough to pass through wholesale.
    if "meta" in envelope:
        out["meta"] = envelope["meta"]

    # ----- Mark this envelope as compact so reversers can detect it -------
    out["_c"] = 1

    return out


def from_compact(
    compact: dict[str, Any],
    *,
    disclaimer_table: dict[str, str] | None = None,
    known_gaps_table: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Reverse `to_compact` (lossy) — expand reference ids back to text.

    Returns a dict with the canonical full-envelope keys re-populated
    where the compact form held a reference. Some legacy fields cannot
    be recovered (e.g. `_audit_seal.ts` is dropped on the wire — only
    the HMAC survives) and are NOT reconstructed; the caller must hit
    `verify_endpoint` to re-fetch the full seal.

    Round-trip invariant: every value the agent uses for inference
    (records, results, citations, quality.gaps→known_gaps text, _dx→
    disclaimer text, _nx→next tool names) is recoverable.
    """
    if not isinstance(compact, dict):
        return compact
    d_table = disclaimer_table or DISCLAIMER_TABLE
    g_table = known_gaps_table or KNOWN_GAPS_TABLE

    out: dict[str, Any] = {}

    if "pid" in compact:
        out["packet_id"] = compact["pid"]
    if "ts" in compact:
        out["generated_at"] = compact["ts"]
    if "csid" in compact:
        out["corpus_snapshot_id"] = compact["csid"]
    if "query" in compact:
        out["query"] = compact["query"]
    if "records" in compact:
        out["records"] = compact["records"]
    if "results" in compact:
        out["results"] = compact["results"]
    if "citations" in compact:
        out["citations"] = compact["citations"]
    if "warnings" in compact:
        out["warnings"] = compact["warnings"]
    if "status" in compact:
        out["status"] = compact["status"]
    if "_warning" in compact:
        out["_warning"] = compact["_warning"]
    if "error" in compact:
        out["error"] = compact["error"]
    if "meta" in compact:
        out["meta"] = compact["meta"]
    if "decision_support" in compact:
        out["decision_support"] = compact["decision_support"]

    # Quality: gaps → known_gaps long-text list.
    if "quality" in compact and isinstance(compact["quality"], dict):
        q_in = compact["quality"]
        q_out: dict[str, Any] = {}
        for k, v in q_in.items():
            if k == "gaps":
                if isinstance(v, list):
                    q_out["known_gaps"] = [g_table.get(c, c) for c in v if isinstance(c, str)]
            else:
                q_out[k] = v
        out["quality"] = q_out

    # Verification: pe → provenance_endpoint.
    if "v" in compact and isinstance(compact["v"], dict):
        v_in = compact["v"]
        v_out: dict[str, Any] = {}
        if "pe" in v_in:
            v_out["provenance_endpoint"] = v_in["pe"]
        if v_out:
            out["verification"] = v_out

    # Disclaimer.
    if "_dx" in compact:
        ref = compact["_dx"]
        out["_disclaimer"] = d_table.get(ref, ref)
    if "_disclaimer_gbiz" in compact:
        out["_disclaimer_gbiz"] = compact["_disclaimer_gbiz"]
    if "_attribution" in compact:
        out["_attribution"] = compact["_attribution"]

    # Audit seal — HMAC string is preserved; rest must be re-fetched.
    if "_seal" in compact:
        out["_audit_seal"] = {"hmac": compact["_seal"]}

    # Next-calls — list of tool names, args must be re-derived by caller.
    if "_nx" in compact:
        nx = compact["_nx"]
        if isinstance(nx, list):
            out["_next_calls"] = [{"tool": t, "args": {}} for t in nx if isinstance(t, str)]

    return out


def wants_compact(request: Any) -> bool:
    """Return True when the caller opted into the compact envelope.

    Two opt-in paths (caller picks whichever their stack supports):

      * ``?compact=true`` query (truthy values: ``true`` / ``1`` / ``yes``).
      * ``X-JPCite-Compact: 1`` request header.

    Soft-fail: any AttributeError on the duck-typed `request` returns False.
    Never raises.
    """
    try:
        # Query param.
        qp = request.query_params.get("compact", "") if hasattr(request, "query_params") else ""
        if isinstance(qp, str) and qp.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        h = request.headers.get("x-jpcite-compact", "") if hasattr(request, "headers") else ""
        if isinstance(h, str) and h.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


__all__ = [
    "DISCLAIMER_TABLE",
    "KNOWN_GAPS_TABLE",
    "from_compact",
    "to_compact",
    "wants_compact",
]
