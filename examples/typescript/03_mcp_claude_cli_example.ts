/**
 * 03_mcp_claude_cli_example.ts
 * -----------------------------
 * Spawn the jpintel MCP server via stdio and call `search_programs` directly
 * from Node — WITHOUT Claude Desktop / Cursor. This is the pattern for
 * wiring jpintel into a custom agent loop or a CI smoke test.
 *
 * Protocol: MCP 2025-06-18 JSON-RPC over stdio. We speak it by hand here so
 * you can see the actual 3 messages that flow on the wire (initialize,
 * initialized notification, tools/call).
 *
 * Prereqs: the jpintel-mcp Python package must be importable; easiest is:
 *     pip install jpintel-mcp
 * or, from the repo:
 *     pip install -e .   # then `jpintel-mcp` is on PATH
 *
 * env vars:
 *   JPINTEL_MCP_CMD   (default: "jpintel-mcp" — the installed entry point)
 *   JPINTEL_DB_PATH   (optional, override default DB location)
 *
 * run:
 *   npm install
 *   npx tsx 03_mcp_claude_cli_example.ts
 *
 * expected output (stderr lines from FastMCP interleaved):
 *
 *   -> initialize
 *   <- server protocolVersion=2025-06-18 name=jpintel
 *   -> tools/call search_programs prefecture=青森県 tier=[S,A]
 *   Processing request of type CallToolRequest
 *   <- 3 results (total=3)
 *      [S] 経営発展支援事業
 *      [A] PREF-02-101_青森_所得向上プログラム実践支援事業
 *      [A] 青森 スマート農業機械導入支援事業
 *   MCP session closed cleanly.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import type { Writable, Readable } from "node:stream";

const MCP_CMD = process.env.JPINTEL_MCP_CMD ?? "jpintel-mcp";

type JsonRpcMessage = {
  jsonrpc: "2.0";
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
};

class StdioMcpClient {
  private proc: ChildProcess;
  private stdin: Writable;
  private stdout: Readable;
  private nextId = 1;
  private pending = new Map<number, (msg: JsonRpcMessage) => void>();

  constructor(cmd: string) {
    this.proc = spawn(cmd, [], {
      stdio: ["pipe", "pipe", "inherit"],
      env: process.env,
    });
    if (!this.proc.stdin || !this.proc.stdout) {
      throw new Error("failed to open stdio pipes to MCP server");
    }
    this.stdin = this.proc.stdin;
    this.stdout = this.proc.stdout;
    const rl = createInterface({ input: this.stdout });
    rl.on("line", (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        const msg = JSON.parse(trimmed) as JsonRpcMessage;
        if (typeof msg.id === "number") {
          const resolver = this.pending.get(msg.id);
          if (resolver) {
            this.pending.delete(msg.id);
            resolver(msg);
          }
        }
      } catch {
        // non-JSON log line — ignore
      }
    });
    this.proc.on("exit", (code) => {
      if (code !== 0 && code !== null) {
        console.error(`MCP server exited with code ${code}`);
      }
    });
  }

  request(method: string, params?: unknown): Promise<JsonRpcMessage> {
    const id = this.nextId++;
    const body: JsonRpcMessage = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      this.pending.set(id, resolve);
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timeout waiting for ${method}`));
      }, 15_000);
      // clear timeout when resolved
      const orig = this.pending.get(id)!;
      this.pending.set(id, (msg) => {
        clearTimeout(timeout);
        orig(msg);
      });
      this.stdin.write(`${JSON.stringify(body)}\n`);
    });
  }

  notify(method: string, params?: unknown): void {
    const body: JsonRpcMessage = { jsonrpc: "2.0", method, params };
    this.stdin.write(`${JSON.stringify(body)}\n`);
  }

  close(): void {
    this.stdin.end();
    this.proc.kill("SIGTERM");
  }
}

async function main(): Promise<void> {
  const client = new StdioMcpClient(MCP_CMD);

  // 1) initialize
  console.log("-> initialize");
  const init = await client.request("initialize", {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "examples/03_mcp_claude_cli_example", version: "0.1.0" },
  });
  if (init.error) {
    console.error(`ERROR: initialize failed: ${init.error.message}`);
    client.close();
    process.exit(1);
  }
  const info = init.result as { protocolVersion: string; serverInfo: { name: string } };
  console.log(`<- server protocolVersion=${info.protocolVersion} name=${info.serverInfo.name}`);
  client.notify("notifications/initialized");

  // 2) tools/call search_programs
  console.log("-> tools/call search_programs prefecture=青森県 tier=[S,A]");
  const call = await client.request("tools/call", {
    name: "search_programs",
    arguments: {
      prefecture: "青森県",
      tier: ["S", "A"],
      amount_min_man_yen: 500,
      limit: 10,
    },
  });
  if (call.error) {
    console.error(`ERROR: tools/call failed: ${call.error.message}`);
    client.close();
    process.exit(1);
  }

  // FastMCP returns content as text parts; the tool output is JSON-stringified.
  const result = call.result as { content: Array<{ type: string; text: string }> };
  const textPart = result.content.find((c) => c.type === "text");
  if (!textPart) {
    console.error("ERROR: no text content in tool result");
    client.close();
    process.exit(1);
  }
  const payload = JSON.parse(textPart.text) as {
    total: number;
    results: Array<{ tier: string | null; primary_name: string }>;
  };
  console.log(`<- ${payload.results.length} results (total=${payload.total})`);
  for (const r of payload.results) {
    console.log(`   [${r.tier}] ${r.primary_name}`);
  }

  client.close();
  console.log("MCP session closed cleanly.");
}

main().catch((err) => {
  console.error("unhandled error:", err);
  process.exit(2);
});
