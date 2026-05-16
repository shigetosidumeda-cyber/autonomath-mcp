#!/usr/bin/env python3
"""Generate 採択確率 (acceptance probability) cohort JPCIR packets.

The packet kind ``acceptance_probability_cohort_v1`` is jpcite's
differentiator for 補助金 consultants: it turns the question
「同業同規模同地域では何 % 採択されているのか?」 into a deterministic,
purely-statistical answer that 1 ``GET /v1/cases/cohort_match`` could
not. Each packet is JPCIR-contract-compliant (see
``schemas/jpcir/acceptance_probability_cohort.schema.json``) and stays
< 10 KB on disk.

Cohort definition (5 axes)
--------------------------

::

    cohort = (prefecture × jsic_major × scale_band × program_kind × fiscal_year)

* ``prefecture``     — 47 都道府県 ISO-romaji code in UPPER, or ``UNKNOWN``.
* ``jsic_major``     — 1-letter JSIC major (A..T) derived from
                       ``industry_jsic_medium[:1]``.
* ``scale_band``     — bucket on ``amount_granted_yen``:
                       ``micro`` (<¥1M) / ``small`` (<¥10M) / ``mid``
                       (<¥100M) / ``large`` (≥¥100M) / ``unknown``.
* ``program_kind``   — best-effort discriminator (subsidy / loan /
                       support / research_grant / grant / incentive
                       / regulation / certification / tax_deduction
                       / training).
* ``fiscal_year``    — 4-digit year extracted from ``announced_at``.

Wilson 95% confidence interval
------------------------------

For a binomial proportion ``p_hat = k / n`` with ``z = 1.96`` (95% CI):

::

    centre = (p_hat + z² / (2 n)) / (1 + z² / n)
    half_w = ( z * sqrt( (p_hat (1-p_hat) + z²/(4 n)) / n ) ) / (1 + z² / n)
    CI     = [centre - half_w, centre + half_w]

We clamp to ``[0, 1]`` and treat ``n_eligible_programs`` (distinct
programs targeting the cohort) as the implicit denominator. For
cohorts with ``n_sample = 0`` the renderer emits a CI of ``[0, 1]`` and
adds the ``no_hit_not_absence`` known_gap; cohorts whose freshest
adoption row is older than 12 months get the ``freshness_stale_or_unknown``
gap.

CLI
---

.. code-block:: text

    python scripts/aws_credit_ops/generate_acceptance_probability_packets.py \\
        --db autonomath.db \\
        --jpintel-db data/jpintel.db \\
        --out out/packets/acceptance_probability_cohort_v1 \\
        --limit 1000 \\
        --run-id smoke_20260516

The smoke job uses ``--limit 1000`` to land the first batch; the
production run drops ``--limit`` and emits every cohort observed in
``jpi_adoption_records`` (estimated O(45,000) non-empty cohorts on the
current 201,845-row mirror; the analytical cross product 47 × 20 × 4
× 12 × 5 = 225,600 is the design ceiling, but the natural Japanese
adoption distribution is sparse).

Constraints
-----------
* **NO LLM API calls.** Pure SQLite + Python statistics.
* Each cohort packet ``< 10 KB`` on disk (JSON canonical form).
* Wilson 95% CI (Wilson_score method) — explicitly NOT Bayesian.
* Always emits ``professional_review_required`` known_gap.
* Emits ``no_hit_not_absence`` when ``n_sample == 0``.
* Emits ``freshness_stale_or_unknown`` when ``freshest_announced_at`` is
  older than 12 months or unknown.
* ``mypy --strict`` + ``ruff 0``.
* ``[lane:solo]`` marker per CLAUDE.md dual-CLI lane convention.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import math
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("generate_acceptance_probability_packets")

PACKAGE_KIND: Final[str] = "acceptance_probability_cohort_v1"
SCHEMA_VERSION: Final[str] = "jpcir.p0.v1"
PRODUCER: Final[str] = "jpcite-ai-execution-control-plane"
WILSON_Z_95: Final[float] = 1.96
WILSON_Z2_95: Final[float] = WILSON_Z_95 * WILSON_Z_95
STALE_DAYS: Final[int] = 365
PACKET_MAX_BYTES: Final[int] = 10_240  # 10 KB hard ceiling

# Scale bands keyed on amount_granted_yen.
SCALE_BAND_THRESHOLDS: Final[tuple[tuple[int, str], ...]] = (
    (1_000_000, "micro"),
    (10_000_000, "small"),
    (100_000_000, "mid"),
)

DISCLAIMER: Final[str] = (
    "jpcite は情報検索・根拠確認の補助に徹し、個別具体的な税務・法律・"
    "申請・監査・登記・労務・知財・労基の判断は行いません。"
    "採択確率は過去公開済みの採択事例からの統計推定であり、"
    "個別案件の採択を保証するものではありません。"
)


@dataclasses.dataclass(frozen=True, slots=True)
class CohortRow:
    """One row of the cohort aggregation result."""

    prefecture: str
    jsic_major: str
    scale_band: str
    program_kind: str
    fiscal_year: str
    n_sample: int
    n_eligible_programs: int
    freshest_announced_at: str | None

    @property
    def cohort_id(self) -> str:
        return ".".join(
            (
                self.prefecture,
                self.jsic_major,
                self.scale_band,
                self.program_kind,
                self.fiscal_year,
            )
        )


@dataclasses.dataclass(frozen=True, slots=True)
class WilsonInterval:
    """Result of the Wilson 95% binomial proportion CI."""

    point: float
    low: float
    high: float


def scale_band(amount_granted_yen: int | None) -> str:
    """Bucket ``amount_granted_yen`` into the 5-band scale enum."""

    if amount_granted_yen is None:
        return "unknown"
    for threshold, label in SCALE_BAND_THRESHOLDS:
        if amount_granted_yen < threshold:
            return label
    return "large"


def wilson_95_ci(k: int, n: int) -> WilsonInterval:
    """Wilson 95% binomial proportion CI.

    ``k`` = positive count, ``n`` = trial count. ``n=0`` is treated as
    "no information" and returns CI ``[0, 1]`` with point ``0`` so the
    downstream renderer can pair it with the ``no_hit_not_absence``
    known_gap.
    """

    if n <= 0:
        return WilsonInterval(point=0.0, low=0.0, high=1.0)
    p_hat = k / n
    denom = 1.0 + WILSON_Z2_95 / n
    centre = (p_hat + WILSON_Z2_95 / (2.0 * n)) / denom
    inner = (p_hat * (1.0 - p_hat) + WILSON_Z2_95 / (4.0 * n)) / n
    half_w = (WILSON_Z_95 * math.sqrt(max(inner, 0.0))) / denom
    low = max(0.0, centre - half_w)
    high = min(1.0, centre + half_w)
    return WilsonInterval(point=p_hat, low=low, high=high)


def _fy_from_announced_at(announced_at: str | None) -> str:
    if not announced_at or len(announced_at) < 4:
        return ""
    fy = announced_at[:4]
    return fy if fy.isdigit() else ""


def _is_stale(freshest_announced_at: str | None, *, now: dt.date) -> bool:
    if not freshest_announced_at:
        return True
    try:
        observed = dt.date.fromisoformat(freshest_announced_at[:10])
    except ValueError:
        return True
    return (now - observed).days > STALE_DAYS


def _normalise_program_kind_lookup(
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """Best-effort program_id → program_kind lookup from jpintel.db.

    ``jpi_adoption_records`` does not carry ``program_kind`` directly,
    so we materialise the join once and bind in Python; this keeps the
    Athena query (the live-data path) and the SQLite smoke path
    semantically aligned.
    """

    out: dict[str, str] = {}
    with contextlib.suppress(sqlite3.OperationalError):
        for row in conn.execute(
            "SELECT unified_id, program_kind FROM programs WHERE excluded=0"
        ):
            unified_id, kind = row[0], (row[1] or "unknown") or "unknown"
            if isinstance(unified_id, str) and unified_id:
                out[unified_id] = kind
    return out


def aggregate_cohorts(
    adoption_db: Path,
    jpintel_db: Path,
    *,
    limit: int | None,
) -> Iterator[CohortRow]:
    """Aggregate cohort rows from autonomath.db (read-only).

    Uses the local SQLite mirror for the smoke path; the production
    path is driven by the matching Athena query
    (``infra/aws/athena/queries/cohort_acceptance_probability.sql``).
    """

    uri = f"file:{adoption_db}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        program_kind_lookup: dict[str, str] = {}
        jpintel_uri = f"file:{jpintel_db}?mode=ro&immutable=1"
        with contextlib.suppress(sqlite3.OperationalError):
            jpintel = sqlite3.connect(jpintel_uri, uri=True)
            try:
                program_kind_lookup = _normalise_program_kind_lookup(jpintel)
            finally:
                jpintel.close()

        rows_seen = 0
        # We do the GROUP BY in Python because we have to bind the
        # program_kind lookup that lives in the other DB.
        agg: dict[
            tuple[str, str, str, str, str],
            tuple[int, set[str], str | None],
        ] = {}
        for r in conn.execute(
            """
            SELECT
                COALESCE(NULLIF(UPPER(prefecture), ''), 'UNKNOWN'),
                COALESCE(UPPER(SUBSTR(industry_jsic_medium, 1, 1)), ''),
                amount_granted_yen,
                program_id,
                announced_at
            FROM jpi_adoption_records
            WHERE announced_at IS NOT NULL
              AND length(announced_at) >= 4
            """
        ):
            pref = r[0]
            jsic = r[1] or "Z"
            band = scale_band(r[2])
            program_id_raw = r[3] or ""
            program_kind = (
                program_kind_lookup.get(program_id_raw, "unknown") or "unknown"
            )
            fy = _fy_from_announced_at(r[4])
            if not fy:
                continue
            key = (pref, jsic, band, program_kind, fy)
            n, programs, freshest = agg.get(key, (0, set(), None))
            n += 1
            if program_id_raw:
                programs.add(program_id_raw)
            announced = r[4]
            if announced and (freshest is None or announced > freshest):
                freshest = announced
            agg[key] = (n, programs, freshest)
            rows_seen += 1

        for (pref, jsic, band, kind, fy), (n, programs, freshest) in agg.items():
            yield CohortRow(
                prefecture=pref,
                jsic_major=jsic,
                scale_band=band,
                program_kind=kind,
                fiscal_year=fy,
                n_sample=n,
                n_eligible_programs=max(len(programs), 1),
                freshest_announced_at=freshest,
            )
        logger.info(
            "aggregate_cohorts: rows_seen=%d distinct_cohorts=%d",
            rows_seen,
            len(agg),
        )
        _ = limit  # cohort emission limit is handled by the caller
    finally:
        conn.close()


def _known_gaps(
    cohort: CohortRow,
    *,
    now: dt.date,
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = [
        {
            "gap_id": f"prof_review_{cohort.cohort_id}",
            "gap_type": "professional_review_required",
            "gap_status": "known_gap",
            "explanation": (
                "採択確率は統計推定で個別案件の採択を保証しません。"
                "出願前に税理士・行政書士・社労士など専門家の確認を必須としてください。"
            ),
        }
    ]
    if cohort.n_sample == 0:
        gaps.append(
            {
                "gap_id": f"no_hit_{cohort.cohort_id}",
                "gap_type": "no_hit_not_absence",
                "gap_status": "known_gap",
                "explanation": (
                    "このコホートで採択事例が観測されないことは"
                    "「採択ゼロ」を意味しません。窓口確認が必要です。"
                ),
            }
        )
    if _is_stale(cohort.freshest_announced_at, now=now):
        gaps.append(
            {
                "gap_id": f"stale_{cohort.cohort_id}",
                "gap_type": "freshness_stale_or_unknown",
                "gap_status": "known_gap",
                "explanation": (
                    "コホート内で観測された最新採択告示日が 12 ヶ月以上前または不明です。"
                    "鮮度の観点で参照値として扱ってください。"
                ),
            }
        )
    return gaps


def render_packet(
    cohort: CohortRow,
    *,
    generated_at: dt.datetime,
    now: dt.date | None = None,
) -> dict[str, object]:
    """Render one JPCIR ``acceptance_probability_cohort_v1`` packet."""

    today = now or generated_at.date()
    # n must be >= k for a valid binomial. When the source data only
    # carries the positive arm (採択数) without a public denominator we
    # use n_eligible_programs as a lower-bound denominator and clamp.
    n_trials = max(cohort.n_sample, cohort.n_eligible_programs)
    interval = wilson_95_ci(cohort.n_sample, n_trials)
    header_payload = {
        "object_id": f"acceptance_probability.{cohort.cohort_id}",
        "object_type": PACKAGE_KIND,
        "created_at": generated_at.isoformat(timespec="seconds"),
        "producer": PRODUCER,
        "schema_version": SCHEMA_VERSION,
        "request_time_llm_call_performed": False,
    }
    packet: dict[str, object] = {
        "header": header_payload,
        "package_kind": PACKAGE_KIND,
        "cohort_definition": {
            "cohort_id": cohort.cohort_id,
            "prefecture": cohort.prefecture,
            "jsic_major": cohort.jsic_major,
            "scale_band": cohort.scale_band,
            "program_kind": cohort.program_kind,
            "fiscal_year": cohort.fiscal_year,
        },
        "probability_estimate": round(interval.point, 6),
        "confidence_interval": {
            "method": "wilson_score",
            "level": 0.95,
            "low": round(interval.low, 6),
            "high": round(interval.high, 6),
        },
        "n_sample": cohort.n_sample,
        "n_eligible_programs": cohort.n_eligible_programs,
        "freshest_announced_at": cohort.freshest_announced_at,
        "adjacency_suggestions": [],
        "known_gaps": _known_gaps(cohort, now=today),
        "disclaimer": DISCLAIMER,
    }
    return packet


def attach_adjacency(
    packets: list[dict[str, object]],
    *,
    max_suggestions: int = 5,
) -> None:
    """Attach top-N higher-probability cohorts as adjacency suggestions.

    For each packet we look at the same ``(prefecture, jsic_major)``
    bucket and surface up to ``max_suggestions`` cohort_ids whose
    point estimate is strictly higher. This is the "similar programs
    with higher 採択率" hint that turns the packet into an action.
    """

    by_axis: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for p in packets:
        defn = p.get("cohort_definition")
        prob = p.get("probability_estimate")
        if not isinstance(defn, dict) or not isinstance(prob, float | int):
            continue
        pref = defn.get("prefecture")
        jsic = defn.get("jsic_major")
        cid = defn.get("cohort_id")
        if (
            not isinstance(pref, str)
            or not isinstance(jsic, str)
            or not isinstance(cid, str)
        ):
            continue
        by_axis.setdefault((pref, jsic), []).append((float(prob), cid))

    for bucket in by_axis.values():
        bucket.sort(reverse=True)

    for p in packets:
        defn = p.get("cohort_definition")
        prob = p.get("probability_estimate")
        if not isinstance(defn, dict) or not isinstance(prob, float | int):
            continue
        pref = defn.get("prefecture")
        jsic = defn.get("jsic_major")
        cid = defn.get("cohort_id")
        if (
            not isinstance(pref, str)
            or not isinstance(jsic, str)
            or not isinstance(cid, str)
        ):
            continue
        bucket = by_axis.get((pref, jsic), [])
        suggestions: list[dict[str, object]] = []
        for cand_prob, cand_id in bucket:
            if cand_id == cid:
                continue
            if cand_prob <= float(prob):
                continue
            suggestions.append(
                {
                    "cohort_id": cand_id,
                    "probability_estimate": round(cand_prob, 6),
                    "delta": round(cand_prob - float(prob), 6),
                }
            )
            if len(suggestions) >= max_suggestions:
                break
        p["adjacency_suggestions"] = suggestions


def _packet_filename(cohort_id: str) -> str:
    digest = hashlib.sha256(cohort_id.encode("utf-8")).hexdigest()[:12]
    safe = cohort_id.replace("/", "_").replace(" ", "_")
    return f"{safe}.{digest}.json"


def write_packet(out_dir: Path, packet: dict[str, object]) -> Path:
    defn = packet.get("cohort_definition")
    if not isinstance(defn, dict):
        msg = "packet missing cohort_definition"
        raise ValueError(msg)
    cid = defn.get("cohort_id")
    if not isinstance(cid, str):
        msg = "cohort_definition missing cohort_id"
        raise ValueError(msg)
    body = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    raw = body.encode("utf-8")
    if len(raw) > PACKET_MAX_BYTES:
        msg = (
            f"packet {cid} exceeds {PACKET_MAX_BYTES} byte ceiling: {len(raw)}"
        )
        raise ValueError(msg)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / _packet_filename(cid)
    path.write_text(body, encoding="utf-8")
    return path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        prog="generate_acceptance_probability_packets",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=repo_root / "autonomath.db",
        help="Source SQLite DB (autonomath.db).",
    )
    parser.add_argument(
        "--jpintel-db",
        type=Path,
        default=repo_root / "data" / "jpintel.db",
        help="jpintel.db (for program_kind lookup).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            repo_root / "out" / "packets" / "acceptance_probability_cohort_v1"
        ),
        help="Output directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of emitted packets (smoke runs use 1000).",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="smoke",
        help="Run identifier embedded in the manifest.",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Optional path to write a JSONL manifest of emitted packets.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if ns.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    out_dir = Path(ns.out).resolve()
    generated_at = dt.datetime.now(dt.UTC)
    packets: list[dict[str, object]] = []
    cohort_iter = aggregate_cohorts(
        adoption_db=Path(ns.db),
        jpintel_db=Path(ns.jpintel_db),
        limit=ns.limit,
    )
    for idx, cohort in enumerate(cohort_iter):
        if ns.limit is not None and idx >= int(ns.limit):
            break
        packet = render_packet(cohort, generated_at=generated_at)
        packets.append(packet)
    attach_adjacency(packets)

    written: list[Path] = []
    for packet in packets:
        try:
            written.append(write_packet(out_dir, packet))
        except ValueError as exc:
            logger.error("packet write failed: %s", exc)
            return 2

    if ns.ledger is not None:
        ledger_path = Path(ns.ledger).resolve()
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as handle:
            for p in packets:
                handle.write(
                    json.dumps(
                        {
                            "run_id": ns.run_id,
                            "cohort_id": (
                                p["cohort_definition"]["cohort_id"]  # type: ignore[index]
                            ),
                            "n_sample": p["n_sample"],
                            "n_eligible_programs": p["n_eligible_programs"],
                            "probability_estimate": p["probability_estimate"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    logger.info(
        "wrote %d packets to %s (run_id=%s)",
        len(written),
        out_dir,
        ns.run_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
