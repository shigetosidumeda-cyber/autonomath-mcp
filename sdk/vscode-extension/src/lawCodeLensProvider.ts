import * as vscode from 'vscode';
import { findLawIdsInLine, buildEGovUrl } from './lawIdRegex';

/**
 * CodeLens provider that decorates lines containing a Japanese law ID with a
 * `▶ jpcite で見る` action. Clicking the lens fires the `jpcite.openLaw`
 * command with the matched ID.
 */
export class LawCodeLensProvider implements vscode.CodeLensProvider {
  private readonly _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  refresh(): void {
    this._onDidChangeCodeLenses.fire();
  }

  provideCodeLenses(
    document: vscode.TextDocument,
    token: vscode.CancellationToken,
  ): vscode.ProviderResult<vscode.CodeLens[]> {
    const lenses: vscode.CodeLens[] = [];
    const lineCount = document.lineCount;

    // Hard cap to avoid heavy work on giant generated files (e.g. minified
    // bundles or 10k-line JSON dumps).
    const MAX_LINES = 5000;
    const limit = Math.min(lineCount, MAX_LINES);

    for (let i = 0; i < limit; i++) {
      if (token.isCancellationRequested) {
        return lenses;
      }
      const line = document.lineAt(i);
      const matches = findLawIdsInLine(line.text);
      if (matches.length === 0) {
        continue;
      }
      // Surface one lens per matched ID so multi-citation lines stay legible.
      for (const m of matches) {
        const range = new vscode.Range(i, m.start, i, m.end);
        const lens = new vscode.CodeLens(range, {
          title: `▶ jpcite で見る (${m.id})`,
          command: 'jpcite.openLaw',
          tooltip: `Open ${m.id} on jpcite / e-Gov`,
          arguments: [m.id, buildEGovUrl(m.id)],
        });
        lenses.push(lens);
      }
    }
    return lenses;
  }
}
