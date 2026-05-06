/**
 * Shared regex utilities for detecting Japanese law identifiers in source code.
 *
 * The canonical e-Gov law-ID format is `NNNAC0000000NNN` — three digits, the
 * literal `AC`, ten digits. Examples:
 *   - 322AC0000000049  (労働基準法 / Labor Standards Act, 昭和22年法律第49号)
 *   - 416AC0000000086  (会社法 / Companies Act, 平成17年法律第86号)
 *
 * We deliberately use word boundaries so the same pattern can be embedded in
 * URLs, comments, JSON keys, etc. without false-positive overlap on adjacent
 * digits.
 */

export const LAW_ID_REGEX = /\b\d{3}AC\d{10}\b/g;

export interface LawIdMatch {
  readonly id: string;
  readonly start: number;
  readonly end: number;
}

/**
 * Find all law IDs in a single line of text. Returns absolute character
 * offsets relative to the line start.
 */
export function findLawIdsInLine(line: string): LawIdMatch[] {
  const matches: LawIdMatch[] = [];
  // Reset .lastIndex because the regex is global (`g` flag) and will otherwise
  // remember state across calls, returning empty matches on the second pass.
  LAW_ID_REGEX.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = LAW_ID_REGEX.exec(line)) !== null) {
    matches.push({
      id: m[0],
      start: m.index,
      end: m.index + m[0].length,
    });
  }
  return matches;
}

/**
 * Build the canonical e-Gov public viewer URL for a given law ID.
 * jpcite hover previews use the API; this URL is what we open in the browser
 * when the user clicks the CodeLens.
 */
export function buildEGovUrl(lawId: string): string {
  return `https://laws.e-gov.go.jp/law/${lawId}`;
}

/**
 * Build the jpcite-hosted human-readable URL for a given law ID.
 * Used as the "出典" link inside the hover Markdown.
 */
export function buildJpciteWebUrl(lawId: string): string {
  return `https://jpcite.com/law/${lawId}`;
}
