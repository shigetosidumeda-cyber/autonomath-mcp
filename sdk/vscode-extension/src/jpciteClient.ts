import * as vscode from 'vscode';

/**
 * Minimal jpcite REST client used by the hover provider.
 *
 * We deliberately use the global `fetch` (Node 20+ / VS Code 1.85+ ships with
 * undici) instead of bundling axios, to keep the .vsix small.
 */

export interface LawArticleSummary {
  readonly id: string;
  readonly title: string;
  readonly promulgation_date?: string;
  readonly first_article?: {
    readonly number: string;
    readonly body: string;
  };
  readonly source_url: string;
  readonly license: string;
}

interface CacheEntry {
  readonly fetchedAt: number;
  readonly value: LawArticleSummary | null;
}

export class JpciteClient {
  private readonly cache = new Map<string, CacheEntry>();

  // eslint-disable-next-line no-useless-constructor
  constructor(
    private readonly getBaseUrl: () => string,
    private readonly getApiKey: () => string,
    private readonly getCacheTtlMs: () => number,
  ) {}

  clearCache(): void {
    this.cache.clear();
  }

  /**
   * Fetch a law summary by ID. Returns `null` on 404, throws on transport
   * errors so the caller can surface them in the hover UI.
   */
  async getLaw(
    lawId: string,
    token?: vscode.CancellationToken,
  ): Promise<LawArticleSummary | null> {
    const cached = this.cache.get(lawId);
    const now = Date.now();
    if (cached && now - cached.fetchedAt < this.getCacheTtlMs()) {
      return cached.value;
    }

    const url = `${this.getBaseUrl().replace(/\/+$/, '')}/v1/laws/${encodeURIComponent(lawId)}`;
    const headers: Record<string, string> = {
      Accept: 'application/json',
      'User-Agent': 'jpcite-vscode/0.1.0',
    };
    const apiKey = this.getApiKey();
    if (apiKey) {
      headers['Authorization'] = `Bearer ${apiKey}`;
    }

    const controller = new AbortController();
    const cancelSub = token?.onCancellationRequested(() => controller.abort());

    try {
      const res = await fetch(url, { headers, signal: controller.signal });
      if (res.status === 404) {
        this.cache.set(lawId, { fetchedAt: now, value: null });
        return null;
      }
      if (!res.ok) {
        throw new Error(`jpcite API ${res.status} ${res.statusText}`);
      }
      const json = (await res.json()) as LawArticleSummary;
      this.cache.set(lawId, { fetchedAt: now, value: json });
      return json;
    } finally {
      cancelSub?.dispose();
    }
  }
}
