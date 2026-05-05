// KessanBriefAgent — 月次/四半期 決算 briefing reference agent.
//
// Builds the package the cohort #2 (税理士) + cohort #3 (会計士) want every
// 月次/四半期: a corp-scoped recap of program eligibility deltas, sunset-tax
// alerts, and any 行政処分 hits since the previous close.
//
// Inputs: 法人番号 + FY window (start / end ISO dates).
// Outputs: structured brief with sections + an `evidence` packet that pins
//          the corpus snapshot id so the auditor can reproduce.
//
// Sensitive (§52 — touches 決算 territory). Disclaimer is mandatory.
//
// Backed by:
//   * `prepare_kessan_briefing` (Wave 22, autonomath_tools/wave22_tools.py)
//   * `am_amendment_diff` + `jpi_tax_rulesets` join inside the FY window
//   * `enforcement_history` from /v1/am/houjin/{法人番号}/snapshot
//   * `list_tax_sunset_alerts` for sunset-clock items

import { JpciteClient, type EvidencePacket } from "../lib/jpcite_client.js";
import type { LawAmendmentDiff } from "../lib/jpcite_client.js";
import type { TaxRule } from "@jpcite/sdk";
import type { LlmQuery } from "../index.js";

export interface KessanBriefInput {
  houjin_bangou: string;
  /** ISO date (YYYY-MM-DD) — start of FY window (inclusive). */
  fy_start: string;
  /** ISO date (YYYY-MM-DD) — end of FY window (inclusive). */
  fy_end: string;
  /**
   * Optional. If true and an `llm` was supplied, generate a 1-page narrative
   * brief in ja-JP suitable for emailing to the corp. Adds §52 disclaimer.
   * Default false.
   */
  narrate?: boolean;
}

export interface KessanBriefOutput {
  houjin: {
    houjin_bangou: string;
    trade_name: string | null;
    prefecture: string | null;
    municipality: string | null;
    jsic_major: string | null;
    invoice_registered: boolean;
  };
  /** New / changed / sunset programs eligible for this corp during the FY window. */
  program_changes: Array<{
    program_unified_id: string;
    program_name: string;
    change_kind: "added" | "amended" | "sunset" | "amount_changed";
    effective_from: string | null;
    notes: string | null;
    source_url: string | null;
  }>;
  /** 法令改正 within the window touching cited tax / subsidy law articles. */
  law_amendments: LawAmendmentDiff[];
  /** Sunset alerts (tax measures expiring inside or just after the FY window). */
  sunset_alerts: TaxRule[];
  /** 行政処分 hits against this corp in the FY window. */
  enforcement_hits: Array<{
    case_id: string;
    authority: string | null;
    case_kind: string | null;
    decided_at: string | null;
    summary: string | null;
  }>;
  /** Optional ja-JP narrative summary (only when `narrate: true` + `llm` wired). */
  summary?: string;
  evidence: EvidencePacket;
}

export interface KessanBriefAgentOptions {
  llm?: LlmQuery;
}

/**
 * 月次/四半期 決算 briefing reference agent. The Wave 22 server-side tool
 * `prepare_kessan_briefing` does most of the joining; this agent orchestrates
 * the surrounding evidence + optional narration so callers do not have to.
 */
export class KessanBriefAgent {
  constructor(
    private readonly jpcite: JpciteClient,
    private readonly options: KessanBriefAgentOptions = {},
  ) {}

  async run(input: KessanBriefInput): Promise<KessanBriefOutput> {
    if (!input?.houjin_bangou || !/^\d{13}$/.test(input.houjin_bangou)) {
      throw new TypeError("houjin_bangou must be a 13-digit string");
    }
    if (!isIsoDate(input.fy_start) || !isIsoDate(input.fy_end)) {
      throw new TypeError("fy_start / fy_end must be ISO YYYY-MM-DD");
    }
    if (input.fy_start > input.fy_end) {
      throw new RangeError("fy_start must be <= fy_end");
    }

    // Step 1 — houjin snapshot for header + enforcement filter.
    const houjin = await this.jpcite.getHoujin360(input.houjin_bangou);

    // Step 2 — Wave 22 server tool. Single round-trip; backend does the join.
    type BriefingResponse = {
      program_changes: KessanBriefOutput["program_changes"];
      _disclaimer?: string;
      _meta?: { corpus_snapshot_id?: string; corpus_checksum?: string };
    };
    const briefing = await this.jpcite.rest.fetch<BriefingResponse>(
      "POST",
      "/v1/am/kessan/prepare_briefing",
      {
        houjin_bangou: input.houjin_bangou,
        fy_start: input.fy_start,
        fy_end: input.fy_end,
      },
    );

    // Step 3 — law amendments touching the FY window.
    const lawPage = await this.jpcite.listRecentAmendments(input.fy_start, {
      limit: 200,
    });
    const law_amendments = lawPage.results.filter(
      (d) => d.captured_at <= input.fy_end + "T23:59:59Z",
    );

    // Step 4 — sunset tax alerts whose sunset_date overlaps or just misses FY end.
    const taxPage = await this.jpcite.searchTaxIncentives({
      effective_on: input.fy_end,
      limit: 100,
    });
    const sunset_alerts = taxPage.results.filter(
      (r) => r.sunset_date != null && r.sunset_date >= input.fy_start,
    );

    // Step 5 — 行政処分 hits inside the window.
    const enforcement_hits = houjin.enforcement_history.filter(
      (h) =>
        h.decided_at != null &&
        h.decided_at >= input.fy_start &&
        h.decided_at <= input.fy_end,
    );

    // Provenance.
    const sourceUrls: string[] = [];
    for (const c of briefing.program_changes ?? []) {
      if (c.source_url) sourceUrls.push(c.source_url);
    }
    for (const d of law_amendments) if (d.source_url) sourceUrls.push(d.source_url);
    for (const t of sunset_alerts) if (t.source_url) sourceUrls.push(t.source_url);

    const disclaimers: string[] = [
      "本ブリーフィングは jpcite 一次資料データセット (e-Gov / 国税庁 / 経産省 等) からの集計であり、" +
        "§52 に基づく税理士助言ではありません。最終判断は税理士・会計士にご相談ください。",
    ];
    if (briefing._disclaimer) disclaimers.push(briefing._disclaimer);

    let summary: string | undefined;
    if (input.narrate && this.options.llm) {
      // Reference stub — a production fork wires the customer LLM here. The
      // jpcite operator pays ¥0 LLM cost; the customer's Anthropic key is
      // billed for the rendered narrative.
    }

    const evidence = this.jpcite.buildEvidence(sourceUrls, {
      disclaimers,
      ...(briefing._meta?.corpus_snapshot_id !== undefined && {
        corpusSnapshotId: briefing._meta.corpus_snapshot_id,
      }),
      ...(briefing._meta?.corpus_checksum !== undefined && {
        corpusChecksum: briefing._meta.corpus_checksum,
      }),
    });

    const out: KessanBriefOutput = {
      houjin: {
        houjin_bangou: houjin.houjin_bangou,
        trade_name: houjin.trade_name,
        prefecture: houjin.prefecture,
        municipality: houjin.municipality,
        jsic_major: houjin.jsic_major,
        invoice_registered: houjin.invoice_registered,
      },
      program_changes: briefing.program_changes ?? [],
      law_amendments,
      sunset_alerts,
      enforcement_hits,
      evidence,
    };
    if (summary !== undefined) out.summary = summary;
    return out;
  }
}

function isIsoDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}
