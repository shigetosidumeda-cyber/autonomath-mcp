"""License Export Gate — single chokepoint for paid-export redistribution.

Implements `docs/_internal/value_maximization_plan_no_llm_api.md` §24
("License / Redistribution Gate") + §28.9 No-Go #5
("`license in ('unknown','proprietary')` をexport eligibleにする").

Every paid export surface (DD ZIP / Annual Data License monthly ZIP /
future CSV / Excel / Parquet exports) MUST funnel its row set through
this module before serializing the bytes that leave the operator's
perimeter. Bypassing the gate is the single highest-severity legal risk
in the codebase.

Allow-list (NOT deny-list) policy
=================================

The gate uses an explicit *allow list* of redistributable license values.
Any row whose `license` field is not present in
`REDISTRIBUTABLE_LICENSES` is treated as blocked, including:

  * the explicit deny values `proprietary` / `unknown`
  * empty string / None / missing field
  * future license values that ship before the gate is updated
    (e.g. `cc_by_sa_4.0`, `mit-but-not-listed`, `gov_standard_v3.0`)

The allow-list policy is the safe default for §28.9 No-Go #5: a new
license value defaults to blocked until a human reviewer adds it here.
A deny-list would silently leak any unrecognized license string.

License values (per CLAUDE.md V4 absorption notes)
==================================================

Redistributable (allowed):

  * ``pdl_v1.0``      — NTA インボイス公表サイト bulk (PDL v1.0; attribution required)
  * ``gov_standard`` / ``gov_standard_v2.0`` — 政府標準利用規約
    (省庁全般; attribution required)
  * ``cc_by_4.0``     — e-Gov 法令 (Creative Commons BY 4.0; attribution required)
  * ``public_domain`` — public domain (no attribution required, but emitted anyway)

Blocked (NOT redistributable):

  * ``proprietary``   — JST etc.; explicit license-protected
  * ``unknown``       — license not yet resolved; safe default = block
  * any other value   — allow-list default

Note on the on-disk DB: `am_source.license` may carry either the
canonical short-form ``gov_standard`` or the production v2 string
``gov_standard_v2.0``. Both are intentionally allow-listed. Future
license strings still default to blocked until explicitly added here.

Attribution
===========

`annotate_attribution(row)` injects an `_attribution` line per row in
the format mandated by CC-BY 4.0 §3 (Attribution clause):

    出典: {publisher} / {source_url} / 取得 {fetched_at} / license={license}

The same string is emitted into the ZIP-side `attribution.txt` file by
the export route. ASCII-safe header equivalents are NOT generated here;
attribution stays in the body / file.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "REDISTRIBUTABLE_LICENSES",
    "BLOCKED_LICENSES",
    "LicenseGateError",
    "filter_redistributable",
    "assert_no_blocked",
    "annotate_attribution",
]


# ---------------------------------------------------------------------------
# Allow / block sets
# ---------------------------------------------------------------------------

#: Explicit allow list. Anything NOT in this set is blocked from export.
REDISTRIBUTABLE_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "pdl_v1.0",
        "gov_standard",
        "gov_standard_v2.0",
        "cc_by_4.0",
        "public_domain",
    }
)

#: Explicit deny list. Used by `assert_no_blocked` for a clear error
#: surface; the actual gate logic in `filter_redistributable` does NOT
#: consult this set — it consults `REDISTRIBUTABLE_LICENSES` only so
#: anything outside the allow list (including future / unknown values)
#: blocks. `BLOCKED_LICENSES` is for diagnostics + tests.
BLOCKED_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "proprietary",
        "unknown",
    }
)


class LicenseGateError(Exception):
    """Raised by `assert_no_blocked` when the input contains any row
    whose license value is in `BLOCKED_LICENSES` (or, by extension under
    the allow-list policy, any non-redistributable value).
    """


# ---------------------------------------------------------------------------
# Gate primitives
# ---------------------------------------------------------------------------


def filter_redistributable(
    rows: list[dict],
    license_field: str = "license",
) -> tuple[list[dict], list[dict]]:
    """Split `rows` into (allowed, blocked) based on `REDISTRIBUTABLE_LICENSES`.

    A row is *allowed* iff `row[license_field]` is exactly equal to one of
    the values in `REDISTRIBUTABLE_LICENSES`. All other rows are blocked,
    including:

      * rows where the field is missing (`license_field not in row`)
      * rows where the value is None / empty string
      * rows whose value is in `BLOCKED_LICENSES` (proprietary, unknown)
      * rows with any unrecognized string (e.g. `mit`, `gov_standard_v3.0`)

    The function does NOT mutate the input rows. Allowed rows preserve
    their original order; blocked rows likewise.

    Args:
        rows: list of dict rows. Each row should carry the license field;
            rows without it are treated as blocked (allow-list default).
        license_field: name of the field carrying the license value.
            Defaults to `"license"` to match the DB-side column name.

    Returns:
        Tuple of (allowed_rows, blocked_rows). Both are fresh `list`
        objects (the rows themselves are the same dict instances; we do
        not deep-copy).
    """
    allowed: list[dict] = []
    blocked: list[dict] = []
    for row in rows:
        # `dict.get` returns None on missing key; None is not in the
        # allow set so it falls through to `blocked`. This is exactly
        # the safe-default behavior we want.
        value = row.get(license_field)
        if isinstance(value, str) and value in REDISTRIBUTABLE_LICENSES:
            allowed.append(row)
        else:
            blocked.append(row)
    return allowed, blocked


def assert_no_blocked(
    rows: list[dict],
    license_field: str = "license",
) -> None:
    """Raise `LicenseGateError` if any row is non-redistributable.

    Stricter than `filter_redistributable`: instead of silently dropping
    blocked rows, this raises so the caller knows their input contains
    rows they should never have been preparing for export. Useful as a
    final safety net at the very last call site (e.g. just before
    `zipfile.writestr`).

    The error message lists up to 10 of the offending license values +
    the offending row count so the operator can debug without having to
    re-inspect the entire input.
    """
    _, blocked = filter_redistributable(rows, license_field=license_field)
    if not blocked:
        return

    # Roll up `(value, count)` so the error message is bounded even when
    # the offending list is huge.
    counts: dict[str, int] = {}
    for row in blocked:
        v = row.get(license_field)
        key = v if isinstance(v, str) and v else "<missing>"
        counts[key] = counts.get(key, 0) + 1

    summary = ", ".join(
        f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    )
    raise LicenseGateError(
        f"license_gate: refusing to export {len(blocked)} blocked row(s): "
        f"{summary}. Allowed licenses: "
        f"{sorted(REDISTRIBUTABLE_LICENSES)}."
    )


def annotate_attribution(row: dict) -> dict:
    """Add an `_attribution` field to a copy of `row`.

    The attribution string format is mandated by CC-BY 4.0 §3
    (Attribution clause) and is consistent across the four redistributable
    licenses (pdl_v1.0 / gov_standard / cc_by_4.0 / public_domain — even
    public_domain rows get the attribution line for downstream auditor
    reproducibility).

    Format:

        出典: {publisher} / {source_url} / 取得 {fetched_at} / license={license}

    Missing fields are rendered as the literal string ``unknown`` so the
    line stays parseable. The function returns a *shallow* copy of the
    row with the `_attribution` field added; the caller's input is not
    mutated.
    """
    publisher = row.get("publisher") or "unknown"
    source_url = row.get("source_url") or "unknown"
    fetched_at = row.get("fetched_at") or "unknown"
    license_value = row.get("license") or "unknown"
    attribution = f"出典: {publisher} / {source_url} / 取得 {fetched_at} / license={license_value}"
    out = dict(row)
    out["_attribution"] = attribution
    return out
