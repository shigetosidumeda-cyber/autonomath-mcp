import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AuthError,
  JpciteClient,
  JpciteError,
  NotFoundError,
  RateLimitError,
} from "../src/index.js";

const ORIGINAL_FETCH = globalThis.fetch;

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("JpciteClient", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    // @ts-expect-error — assigning mock to global fetch for the test scope
    globalThis.fetch = fetchMock;
  });

  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  // ─── searchPrograms ─────────────────────────────────────────────────

  it("searchPrograms returns array of programs and sends q + tier + limit", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        total: 2,
        limit: 5,
        offset: 0,
        results: [
          {
            unified_id: "PROG-jp-shoenergy-001",
            primary_name: "省エネ補助金",
            authority_name: "経済産業省",
            prefecture: null,
            tier: "S",
            amount_max_man_yen: 5000,
            official_url: "https://example.go.jp/shoenergy",
            excluded: false,
          },
          {
            unified_id: "PROG-jp-shoenergy-002",
            primary_name: "省エネ設備導入支援",
            authority_name: "東京都",
            prefecture: "東京都",
            tier: "A",
            amount_max_man_yen: 1000,
            official_url: "https://example.tokyo.lg.jp/shoenergy",
            excluded: false,
          },
        ],
      }),
    );

    const jp = new JpciteClient("test-key");
    const res = await jp.searchPrograms("省エネ", { tier: ["S", "A"], limit: 5 });

    expect(Array.isArray(res.results)).toBe(true);
    expect(res.results).toHaveLength(2);
    expect(res.results[0]?.unified_id).toBe("PROG-jp-shoenergy-001");
    expect(res.total).toBe(2);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/v1/programs/search");
    expect(String(url)).toContain("q=%E7%9C%81%E3%82%A8%E3%83%8D"); // 省エネ
    expect(String(url)).toContain("tier=S");
    expect(String(url)).toContain("tier=A");
    expect(String(url)).toContain("limit=5");
    expect(init.method).toBe("GET");
    expect(init.headers["X-API-Key"]).toBe("test-key");
  });

  // ─── getHoujin ──────────────────────────────────────────────────────

  it("getHoujin parses 13-digit T-number (with and without leading T)", async () => {
    const houjinPayload = {
      houjin_bangou: "8010001213708",
      name: "Bookyou株式会社",
      address: "東京都文京区小日向2-22-1",
      invoice_registered: true,
      invoice_registered_at: "2025-05-12",
      source_url: "https://www.invoice-kohyo.nta.go.jp",
    };
    // Each call gets its own Response — Response bodies are single-use streams.
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(houjinPayload)));

    const jp = new JpciteClient();

    // bare 13 digits
    const r1 = await jp.getHoujin("8010001213708");
    expect(r1.houjin_bangou).toBe("8010001213708");
    expect(r1.invoice_registered).toBe(true);

    // T-prefix should be stripped
    const r2 = await jp.getHoujin("T8010001213708");
    expect(r2.name).toBe("Bookyou株式会社");

    // both calls should hit the same path
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls[0]).toContain("/v1/houjin/8010001213708");
    expect(calls[1]).toContain("/v1/houjin/8010001213708");

    // invalid input rejected without HTTP call
    fetchMock.mockClear();
    await expect(jp.getHoujin("12345")).rejects.toThrow(TypeError);
    await expect(jp.getHoujin("")).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // ─── 429 → RateLimitError ───────────────────────────────────────────

  it("429 throws RateLimitError with retryAfter from header", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "rate limit exceeded" }), {
        status: 429,
        headers: {
          "Content-Type": "application/json",
          "Retry-After": "30",
        },
      }),
    );

    const jp = new JpciteClient("test-key");

    let caught: unknown;
    try {
      await jp.searchPrograms("test");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(RateLimitError);
    expect(caught).toBeInstanceOf(JpciteError);
    const e = caught as RateLimitError;
    expect(e.statusCode).toBe(429);
    expect(e.retryAfter).toBe(30);
    expect(e.message).toContain("rate limit");
  });

  // ─── 401 / 404 mapping (sanity) ─────────────────────────────────────

  it("401 throws AuthError, 404 throws NotFoundError", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("unauthorized", { status: 401 }),
    );
    await expect(new JpciteClient().searchPrograms("x")).rejects.toBeInstanceOf(
      AuthError,
    );

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(
      new JpciteClient().getHoujin("9999999999999"),
    ).rejects.toBeInstanceOf(NotFoundError);
  });

  // ─── checkCompliance ────────────────────────────────────────────────

  it("checkCompliance posts program_ids and returns hits", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        program_ids: ["PROG-A", "PROG-B"],
        hits: [
          {
            rule_id: "EXCL-001",
            kind: "exclude",
            severity: "absolute",
            programs_involved: ["PROG-A", "PROG-B"],
            description: "重複申請不可",
            source_urls: ["https://example.go.jp/rule"],
          },
        ],
        checked_rules: 181,
      }),
    );

    const jp = new JpciteClient("test-key");
    const res = await jp.checkCompliance(["PROG-A", "PROG-B"]);
    expect(res.hits).toHaveLength(1);
    expect(res.hits[0]?.rule_id).toBe("EXCL-001");

    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      program_ids: ["PROG-A", "PROG-B"],
    });

    // empty array rejected without HTTP call
    fetchMock.mockClear();
    await expect(jp.checkCompliance([])).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("checkFundingStack posts program_ids and returns next_actions", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        program_ids: ["PROG-A", "PROG-B"],
        all_pairs_status: "requires_review",
        pairs: [
          {
            program_a: "PROG-A",
            program_b: "PROG-B",
            verdict: "requires_review",
            confidence: 0.7,
            rule_chain: [],
            next_actions: [
              {
                action_id: "contact_program_office",
                label_ja: "制度事務局へ併用条件を照会する",
                detail_ja: "対象経費と申請年度を示して事務局に確認する。",
                reason: "requires_review 判定のため。",
                source_fields: ["verdict"],
              },
            ],
            _disclaimer: "review required",
          },
        ],
        blockers: [],
        warnings: [],
        next_actions: [
          {
            action_id: "contact_program_office",
            label_ja: "制度事務局へ併用条件を照会する",
            detail_ja: "対象経費と申請年度を示して事務局に確認する。",
            reason: "requires_review 判定のため。",
            source_fields: ["verdict"],
          },
        ],
        total_pairs: 1,
        _disclaimer: "stack review required",
        _billing_unit: 1,
      }),
    );

    const jp = new JpciteClient("test-key");
    const res = await jp.checkFundingStack(["PROG-A", "PROG-B"]);
    expect(res.next_actions[0]?.action_id).toBe("contact_program_office");
    expect(res.pairs[0]?.next_actions[0]?.label_ja).toContain("事務局");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/v1/funding_stack/check");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      program_ids: ["PROG-A", "PROG-B"],
    });

    fetchMock.mockClear();
    await expect(jp.checkFundingStack(["PROG-A"])).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("evidence packet methods call expected endpoints", async () => {
    const packet = {
      packet_id: "ep-test",
      generated_at: "2026-05-06T00:00:00Z",
      api_version: "v1",
      corpus_snapshot_id: "snap-test",
      query: { subject_kind: "program" },
      answer_not_included: true,
      records: [{ entity_id: "PROG-A" }],
      quality: { known_gaps: [] },
      verification: {},
    };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(packet))
      .mockResolvedValueOnce(jsonResponse({ ...packet, packet_id: "ep-query" }));

    const jp = new JpciteClient("test-key");
    const direct = await jp.getEvidencePacket("program", "PROG-A", {
      include_rules: true,
      packet_profile: "brief",
    });
    const queried = await jp.queryEvidencePacket({
      query_text: "省エネ 東京都",
      filters: { prefecture: "東京都" },
    });

    expect(direct.packet_id).toBe("ep-test");
    expect(queried.packet_id).toBe("ep-query");

    const [directUrl, directInit] = fetchMock.mock.calls[0]!;
    expect(String(directUrl)).toContain("/v1/evidence/packets/program/PROG-A");
    expect(String(directUrl)).toContain("include_rules=true");
    expect(String(directUrl)).toContain("packet_profile=brief");
    expect(directInit.method).toBe("GET");

    const [queryUrl, queryInit] = fetchMock.mock.calls[1]!;
    expect(String(queryUrl)).toContain("/v1/evidence/packets/query");
    expect(queryInit.method).toBe("POST");
    expect(JSON.parse(queryInit.body as string)).toEqual({
      query_text: "省エネ 東京都",
      filters: { prefecture: "東京都" },
    });
  });
});
