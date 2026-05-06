import * as vscode from 'vscode';
import { JpciteClient } from './jpciteClient';
import { LAW_ID_REGEX, buildJpciteWebUrl, buildEGovUrl } from './lawIdRegex';

/**
 * Hover provider that resolves Japanese law identifiers (e-Gov format,
 * e.g. `322AC0000000049`) into an inline Markdown preview containing the law
 * title, the first article body, and 出典 / e-Gov links.
 */
export class LawHoverProvider implements vscode.HoverProvider {
  // eslint-disable-next-line no-useless-constructor
  constructor(private readonly client: JpciteClient) {}

  async provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    token: vscode.CancellationToken,
  ): Promise<vscode.Hover | undefined> {
    // `getWordRangeAtPosition` with a custom regex returns the full match the
    // cursor is inside. The `g` flag is preserved by VS Code internally.
    const range = document.getWordRangeAtPosition(position, LAW_ID_REGEX);
    if (!range) {
      return undefined;
    }

    const lawId = document.getText(range);
    if (!/^\d{3}AC\d{10}$/.test(lawId)) {
      return undefined;
    }

    let law;
    try {
      law = await this.client.getLaw(lawId, token);
    } catch (err) {
      const md = new vscode.MarkdownString();
      md.isTrusted = false;
      md.appendMarkdown(`**jpcite** — \`${lawId}\`\n\n`);
      md.appendMarkdown(`_lookup failed: ${(err as Error).message}_\n\n`);
      md.appendMarkdown(`[e-Gov で開く](${buildEGovUrl(lawId)})`);
      return new vscode.Hover(md, range);
    }

    if (!law) {
      const md = new vscode.MarkdownString();
      md.isTrusted = false;
      md.appendMarkdown(`**jpcite** — \`${lawId}\`\n\n`);
      md.appendMarkdown(`_no record in jpcite corpus._\n\n`);
      md.appendMarkdown(`[e-Gov で開く](${buildEGovUrl(lawId)})`);
      return new vscode.Hover(md, range);
    }

    const md = new vscode.MarkdownString();
    md.isTrusted = false;
    md.supportHtml = false;

    md.appendMarkdown(`### ${escapeMd(law.title)}\n\n`);
    md.appendMarkdown(`\`${lawId}\`${law.promulgation_date ? `  ·  公布日 ${escapeMd(law.promulgation_date)}` : ''}\n\n`);

    if (law.first_article) {
      md.appendMarkdown(`**第${escapeMd(law.first_article.number)}条**\n\n`);
      md.appendMarkdown(`> ${escapeMd(truncate(law.first_article.body, 400))}\n\n`);
    }

    md.appendMarkdown(`---\n\n`);
    md.appendMarkdown(
      `[jpcite で開く](${buildJpciteWebUrl(lawId)}) · [出典 e-Gov](${escapeUrl(law.source_url || buildEGovUrl(lawId))}) · _license: ${escapeMd(law.license || 'cc_by_4.0')}_`,
    );

    return new vscode.Hover(md, range);
  }
}

function truncate(s: string, n: number): string {
  if (s.length <= n) {
    return s;
  }
  return `${s.slice(0, n)}…`;
}

function escapeMd(s: string): string {
  // Escape characters that would otherwise be interpreted by the Markdown
  // renderer inside the hover popup.
  return s.replace(/([\\`*_{}\[\]()#+\-!>])/g, '\\$1');
}

function escapeUrl(s: string): string {
  // VS Code's MarkdownString renderer is tolerant, but we still defend against
  // accidental closing parens in the URL breaking the link target.
  return s.replace(/\)/g, '%29');
}
