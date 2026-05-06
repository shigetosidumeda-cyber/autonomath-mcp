import * as vscode from 'vscode';
import { JpciteClient } from './jpciteClient';
import { LawHoverProvider } from './lawHoverProvider';
import { LawCodeLensProvider } from './lawCodeLensProvider';
import { buildJpciteWebUrl } from './lawIdRegex';

const CONFIG_SECTION = 'jpcite';

const SUPPORTED_LANGUAGES: vscode.DocumentSelector = [
  { scheme: 'file', language: 'python' },
  { scheme: 'file', language: 'typescript' },
  { scheme: 'file', language: 'typescriptreact' },
  { scheme: 'file', language: 'javascript' },
  { scheme: 'file', language: 'javascriptreact' },
  { scheme: 'file', language: 'markdown' },
  { scheme: 'file', language: 'plaintext' },
  { scheme: 'file', language: 'yaml' },
  { scheme: 'file', language: 'json' },
  { scheme: 'file', language: 'jsonc' },
  { scheme: 'file', language: 'go' },
  { scheme: 'file', language: 'rust' },
  { scheme: 'file', language: 'java' },
  { scheme: 'file', language: 'ruby' },
  { scheme: 'file', language: 'php' },
  { scheme: 'file', language: 'csharp' },
  { scheme: 'file', language: 'html' },
  { scheme: 'file', language: 'sql' },
  // Also surface inside untitled scratch buffers.
  { scheme: 'untitled' },
];

export function activate(context: vscode.ExtensionContext): void {
  const getConfig = () => vscode.workspace.getConfiguration(CONFIG_SECTION);

  const client = new JpciteClient(
    () => getConfig().get<string>('apiBaseUrl', 'https://api.jpcite.com'),
    () => getConfig().get<string>('apiKey', ''),
    () => getConfig().get<number>('cacheTtlSeconds', 3600) * 1000,
  );

  const hoverProvider = new LawHoverProvider(client);
  const codeLensProvider = new LawCodeLensProvider();

  let hoverDisposable: vscode.Disposable | undefined;
  let codeLensDisposable: vscode.Disposable | undefined;

  const reregister = () => {
    hoverDisposable?.dispose();
    codeLensDisposable?.dispose();
    hoverDisposable = undefined;
    codeLensDisposable = undefined;

    const cfg = getConfig();
    if (cfg.get<boolean>('enableHover', true)) {
      hoverDisposable = vscode.languages.registerHoverProvider(SUPPORTED_LANGUAGES, hoverProvider);
      context.subscriptions.push(hoverDisposable);
    }
    if (cfg.get<boolean>('enableCodeLens', true)) {
      codeLensDisposable = vscode.languages.registerCodeLensProvider(
        SUPPORTED_LANGUAGES,
        codeLensProvider,
      );
      context.subscriptions.push(codeLensDisposable);
    }
  };

  reregister();

  // React to user-flipped settings without requiring an editor reload.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration(CONFIG_SECTION)) {
        return;
      }
      if (
        e.affectsConfiguration(`${CONFIG_SECTION}.enableHover`) ||
        e.affectsConfiguration(`${CONFIG_SECTION}.enableCodeLens`)
      ) {
        reregister();
      }
      if (
        e.affectsConfiguration(`${CONFIG_SECTION}.apiKey`) ||
        e.affectsConfiguration(`${CONFIG_SECTION}.apiBaseUrl`)
      ) {
        client.clearCache();
      }
      codeLensProvider.refresh();
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('jpcite.openLaw', async (lawId: string, _fallbackUrl?: string) => {
      if (!lawId || typeof lawId !== 'string') {
        await vscode.window.showWarningMessage('jpcite: no law ID provided.');
        return;
      }
      // We always send the user to the jpcite web view (which itself links to
      // the e-Gov primary source), keeping attribution and ¥3/req funnel in
      // one place.
      await vscode.env.openExternal(vscode.Uri.parse(buildJpciteWebUrl(lawId)));
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('jpcite.clearCache', async () => {
      client.clearCache();
      codeLensProvider.refresh();
      await vscode.window.showInformationMessage('jpcite: hover cache cleared.');
    }),
  );
}

// Required by VS Code even when there is no shutdown work to do.
// eslint-disable-next-line @typescript-eslint/no-empty-function
export function deactivate(): void {}
