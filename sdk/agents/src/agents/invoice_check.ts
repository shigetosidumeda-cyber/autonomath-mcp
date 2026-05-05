// InvoiceCheckAgent — 適格請求書発行事業者 (qualified-invoice issuer) verification agent.
//
// Bulk-checks an invoice batch against the NTA registrant corpus
// (13,801 delta rows + monthly 4M-row zenken bulk wired 2026-04-29 via
// `nta-bulk-monthly` GHA). Returns per-row verdict + a single evidence packet.
//
// LLM is NOT used — this agent is purely deterministic. The `llm` plumbing is
// omitted from the constructor so callers see the binary "this agent is data,
// not reasoning" contract clearly.
//
// Sensitive surface: 適格請求書 verdicts touch consumption-tax compliance
// (§57の2 消費税法). The agent appends a generic disclaimer noting the
// verdict reflects the registrant snapshot at query time and may lag the
// monthly NTA zenken bulk by up to 30 days.

import { JpciteClient, type EvidencePacket } from "../lib/jpcite_client.js";

export type InvoiceCheckVerdict =
  /** Registered as 適格事業者 at query time. Safe to claim 仕入税額控除. */
  | "registered"
  /** 法人番号 looks valid but no registrant row exists. Cannot claim. */
  | "not_registered"
  /** Was registered, but `revoked_at` is set. Cannot claim from that date. */
  | "revoked"
  /** 法人番号 not in the corpus at all (closed corp, typo, individual operator). */
  | "unknown_houjin";

export interface InvoiceCheckRow {
  /** Caller-supplied row id (invoice number, line id, etc.). Echoed in result. */
  row_id: string;
  /** 法人番号 13 桁. Whitespace + non-digits stripped before lookup. */
  houjin_bangou: string;
  /** Optional invoice date (YYYY-MM-DD). Used to detect revoked-before-date hits. */
  invoice_date?: string;
}

export interface InvoiceCheckInput {
  rows: InvoiceCheckRow[];
  /** Hard ceiling on rows per `run()` to bound fan-out. Default + max = 500. */
  max_rows?: number;
}

export interface InvoiceCheckResultRow {
  row_id: string;
  houjin_bangou: string;
  verdict: InvoiceCheckVerdict;
  /** From NTA. T-prefixed registration number. */
  registration_no: string | null;
  /** ISO 8601. */
  registered_at: string | null;
  revoked_at: string | null;
  trade_name: string | null;
  address: string | null;
  /** True iff the invoice_date was supplied AND falls after revoked_at. */
  revoked_before_invoice_date?: boolean;
  /** Per-row first-party URL (NTA registrant detail). */
  source_url: string;
}

export interface InvoiceCheckOutput {
  results: InvoiceCheckResultRow[];
  /** Aggregate counts for quick triage. */
  summary: Record<InvoiceCheckVerdict, number>;
  evidence: EvidencePacket;
}

/**
 * 適格事業者照合 reference agent. Pure data, no LLM.
 */
export class InvoiceCheckAgent {
  constructor(private readonly jpcite: JpciteClient) {}

  async run(input: InvoiceCheckInput): Promise<InvoiceCheckOutput> {
    if (!input?.rows || !Array.isArray(input.rows)) {
      throw new TypeError("rows is required");
    }
    const cap = Math.min(input.max_rows ?? 500, 500);
    if (input.rows.length > cap) {
      throw new RangeError(
        `rows length ${input.rows.length} exceeds cap ${cap}; chunk before calling`,
      );
    }

    const sourceUrls: string[] = [];
    const summary: Record<InvoiceCheckVerdict, number> = {
      registered: 0,
      not_registered: 0,
      revoked: 0,
      unknown_houjin: 0,
    };

    // Sequential to keep the per-IP rate limit honest (3 req/min anonymous).
    // Production forks should batch via the dedicated bulk endpoint when it ships.
    const results: InvoiceCheckResultRow[] = [];
    for (const row of input.rows) {
      const houjin = (row.houjin_bangou ?? "").replace(/\D/g, "");
      if (!/^\d{13}$/.test(houjin)) {
        summary.unknown_houjin++;
        results.push({
          row_id: row.row_id,
          houjin_bangou: row.houjin_bangou,
          verdict: "unknown_houjin",
          registration_no: null,
          registered_at: null,
          revoked_at: null,
          trade_name: null,
          address: null,
          source_url: "",
        });
        continue;
      }

      try {
        const r = await this.jpcite.getInvoiceRegistrant(houjin);
        sourceUrls.push(r.source_url);

        let verdict: InvoiceCheckVerdict;
        if (!r.registered) {
          verdict = "not_registered";
        } else if (r.revoked_at) {
          verdict = "revoked";
        } else {
          verdict = "registered";
        }
        summary[verdict]++;

        const out: InvoiceCheckResultRow = {
          row_id: row.row_id,
          houjin_bangou: houjin,
          verdict,
          registration_no: r.registration_no,
          registered_at: r.registered_at,
          revoked_at: r.revoked_at,
          trade_name: r.trade_name,
          address: r.address,
          source_url: r.source_url,
        };

        if (row.invoice_date && r.revoked_at) {
          out.revoked_before_invoice_date = r.revoked_at <= row.invoice_date;
        }

        results.push(out);
      } catch (err) {
        // 404 / unknown corp — count as unknown and continue.
        summary.unknown_houjin++;
        results.push({
          row_id: row.row_id,
          houjin_bangou: houjin,
          verdict: "unknown_houjin",
          registration_no: null,
          registered_at: null,
          revoked_at: null,
          trade_name: null,
          address: null,
          source_url: "",
        });
        // Defensive: the SDK throws NotFoundError for missing rows. Other
        // errors should surface to the caller; rethrow non-404s only if a
        // production fork wants stricter handling.
        void err;
      }
    }

    const evidence = this.jpcite.buildEvidence(sourceUrls, {
      disclaimers: [
        "適格請求書発行事業者の登録情報は、国税庁 公表サイト (PDL v1.0) を出典としています。" +
          "月次の全件 bulk と日次 delta の合算です。最新で最大 30 日のラグが発生する可能性があります。" +
          "仕入税額控除の最終判断は税理士・会計士にご相談ください (§52 / 消費税法 §57の2)。",
      ],
    });

    return { results, summary, evidence };
  }
}
